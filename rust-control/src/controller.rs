use crate::provider::{self, ImageReceipt, ProviderInput, Receipt, RequestState};
use crate::store::{self, Store};
use crate::types::*;
use crate::util::{self, Result};
use crate::{validation, worker};
use base64::{engine::general_purpose::STANDARD, Engine};
use serde_json::{json, Value};
use std::collections::BTreeMap;
use std::path::PathBuf;
use std::time::{Duration, Instant};

#[path = "model_review.rs"]
pub mod model_review;

/// Test-only hook into finalization. It runs at "after_predicate" (current
/// contract passed, domain guard held) and "before_commit" (review-ready state
/// set, not yet committed). Tests use it for the interleavings that the Python
/// tests reached by monkeypatching. Release builds contain no hook.
#[cfg(test)]
pub type FinalizationHook = fn(&std::path::Path, &str);

#[cfg(test)]
#[allow(dead_code)]
pub static FINALIZATION_HOOK: std::sync::Mutex<Option<FinalizationHook>> =
    std::sync::Mutex::new(None);

#[cfg(test)]
fn finalization_point(task: &std::path::Path, point: &str) {
    let hook = *FINALIZATION_HOOK.lock().unwrap_or_else(|e| e.into_inner());
    if let Some(hook) = hook {
        hook(task, point);
    }
}

#[cfg(not(test))]
fn finalization_point(_task: &std::path::Path, _point: &str) {}

pub fn new_state(config: Config) -> State {
    State {
        schema_version: CONTROL_VERSION.into(),
        task_id: format!("task-{}", util::nonce()),
        status: Status::Ready,
        termination_reason: None,
        config,
        counters: Counters::default(),
        source_manifest_sha256: None,
        domain_checkpoint_sha256: None,
        worker_implementation_sha256: None,
        audit_implementation_sha256: None,
        generation_id: None,
        revision_id: None,
        pending: None,
        staged_decision: None,
        domain: json!({}),
        last_observation: json!({}),
        engineering_approved: false,
        action_fingerprints: BTreeMap::new(),
        created_ms: util::now_ms(),
    }
}
fn stop(store: &mut Store, status: Status, reason: &str) -> Result<()> {
    store.state.status = status;
    store.state.termination_reason = Some(reason.into());
    store.append(
        "task_terminated",
        json!({"reason":reason,"engineering_approved":false}),
    )
}
fn source_spec(store: &Store) -> PathBuf {
    let captured = store.path.join("domain/input/spec.json");
    if captured.exists() {
        captured
    } else {
        PathBuf::from(&store.state.config.source_spec)
    }
}
fn budget_admission(store: &Store) -> Result<()> {
    let l = &store.state.config.limits;
    let c = &store.state.counters;
    if store::directory_size(&store.path)? >= l.task_disk_bytes {
        return Err("task_storage_limit".into());
    }
    if l.max_requests.is_some_and(|n| c.requests_intended >= n)
        || l.max_total_tokens
            .is_some_and(|n| c.prompt_tokens + c.completion_tokens >= n)
        || l.max_spend_usd.is_some_and(|n| c.observed_cost_usd >= n)
    {
        return Err("configured_deployment_budget".into());
    }
    Ok(())
}
fn current_binary(store: &Store) -> Result<()> {
    if util::file_hash(&std::env::current_exe().map_err(|_| "binary_path")?)?
        != store.state.config.binary_sha256
    {
        return Err("controller_binary_changed".into());
    }
    Ok(())
}
pub fn call_worker(store: &mut Store, operation: &str, arguments: Value) -> Result<bool> {
    current_binary(store)?;
    store.verify(false)?;
    budget_admission(store)?;
    let id = format!("worker-{}", util::nonce());
    let pending = Pending {
        kind: "worker".into(),
        id: id.clone(),
        operation: operation.into(),
        response_path: format!("receipts/{id}.json"),
        request_path: format!("requests/{id}.json"),
        domain_before: store.state.domain_checkpoint_sha256.clone(),
        started_ms: util::now_ms(),
    };
    let request = json!({"protocol":WORKER_VERSION,"request_id":id,"operation":operation,"arguments":arguments,
        "expected_domain_sha256":store.state.domain_checkpoint_sha256,"expected_worker_sha256":store.state.worker_implementation_sha256});
    util::atomic_json(&store.path.join(&pending.request_path), &request, false)?;
    store.state.pending = Some(pending.clone());
    store.state.staged_decision = None;
    store.state.status = Status::Running;
    if !["initialize", "observe"].contains(&operation) {
        store.state.counters.operations += 1;
    }
    if ["build_provisional", "build_draft"].contains(&operation) {
        store.state.counters.builds += 1;
    }
    store.append("worker_intent",json!({"operation":operation,"request":store::artifact(&store.path,&pending.request_path,"worker_request")?}))?;
    let outcome = worker::run(
        &store.path,
        &store.state.config,
        &pending,
        &util::json_bytes(&request)?,
        &source_spec(store),
    )?;
    if !outcome.spawned {
        store.state.pending = None;
        store.append(
            "worker_not_started",
            json!({"operation":operation,"supervision":outcome}),
        )?;
        stop(
            store,
            if matches!(outcome.state, worker::ProcessState::Cancelled) {
                Status::Cancelled
            } else {
                Status::Interrupted
            },
            "worker_not_started",
        )?;
        return Ok(false);
    }
    if store.path.join(&pending.response_path).is_file() {
        let success = apply_worker(store, &pending, json!(outcome), false)?;
        if success && !matches!(outcome.state, worker::ProcessState::Exited) {
            stop(
                store,
                if matches!(outcome.state, worker::ProcessState::Cancelled) {
                    Status::Cancelled
                } else {
                    Status::Interrupted
                },
                "worker_supervision_limit",
            )?;
            return Ok(false);
        }
        Ok(success)
    } else {
        let status = if matches!(outcome.state, worker::ProcessState::Cancelled) {
            Status::Cancelled
        } else {
            Status::Interrupted
        };
        // Keep the durable pending intent: changed/unreceipted domain state is
        // never adopted merely because a STEP file exists.
        stop(store, status, "worker_receipt_missing")?;
        Ok(false)
    }
}
/// The controller, not the worker, decides which audit implementation is
/// acceptable: the identity from the initialize receipt becomes the task's pin
/// and every later receipt must repeat it. A task without a pin (created before
/// the pin existed, or initialized by a worker that reports none) gets no pin
/// later and cannot finalize; see `validation::ready`.
fn reconcile_audit_identity(
    pinned: Option<&str>,
    operation: &str,
    result: &Value,
) -> Result<Option<String>> {
    let reported = match result.get("audit_implementation_sha256") {
        None if pinned.is_some() => return Err("audit_implementation_missing".into()),
        None => return Ok(None),
        Some(value) => value
            .as_str()
            .filter(|hash| util::valid_hash(hash))
            .ok_or("audit_implementation_format")?,
    };
    match pinned {
        Some(pin) if pin == reported => Ok(Some(pin.into())),
        Some(_) => Err("audit_implementation_changed".into()),
        None if operation == "initialize" => Ok(Some(reported.into())),
        None => Ok(None),
    }
}
fn apply_worker(
    store: &mut Store,
    pending: &Pending,
    supervision: Value,
    reconciled: bool,
) -> Result<bool> {
    let path = util::safe_file(&store.path, &pending.response_path)?;
    let response: WorkerResponse = util::parse(
        &util::read_bounded(&path, 2 * 1024 * 1024)?,
        2 * 1024 * 1024,
    )?;
    response.validate(&pending.id, &pending.operation)?;
    if response.execution_state == "completed"
        && !reconciled
        && supervision["state"] == "exited"
        && supervision["exit_code"] != 0
    {
        return Err("worker_exit_receipt_contradiction".into());
    }
    if store
        .state
        .worker_implementation_sha256
        .as_ref()
        .is_some_and(|h| h != &response.implementation_sha256)
    {
        return Err("worker_implementation_changed".into());
    }
    if response.execution_state != "completed" {
        store.append("worker_failure_receipt",json!({"receipt":store::artifact(&store.path,&pending.response_path,"worker_receipt")?,"response":response,"supervision":supervision}))?;
        stop(
            store,
            if response.execution_state == "cancelled" {
                Status::Cancelled
            } else {
                Status::Blocked
            },
            response.error_code.as_deref().unwrap_or("worker_failed"),
        )?;
        return Ok(false);
    }
    let _domain_guard = worker::domain_guard(&store.path)?;
    let domain = response.domain.clone().ok_or("worker_domain_missing")?;
    let result = response.result.clone().ok_or("worker_result_missing")?;
    if result["ok"].as_bool().is_none()
        || result["engineering_approved"] != false
        || result["human_semantic_review_required"] != true
    {
        return Err("worker_result_review_contract".into());
    }
    let audit_pin = reconcile_audit_identity(
        store.state.audit_implementation_sha256.as_deref(),
        &pending.operation,
        &result,
    )?;
    let checkpoint = util::file_hash(&util::safe_file(&store.path, "domain/state.json")?)?;
    if response.domain_checkpoint_sha256.as_deref() != Some(&checkpoint) {
        return Err("worker_checkpoint_not_current".into());
    }
    store::verify_domain_identity(&store.path, &domain)?;
    store::verify_artifact_values(&store.path, &result, &mut 0)?;
    if store
        .state
        .source_manifest_sha256
        .as_deref()
        .is_some_and(|h| Some(h) != domain["source_manifest_sha256"].as_str())
    {
        return Err("worker_source_changed".into());
    }
    if pending.operation == "validate_candidate" && result.get("validation").is_some() {
        validation::assess(&store.path, &result, &domain, &result["validation_context"])?;
    }
    if pending.operation == "render_candidate" && result["ok"] == true {
        let candidate = &domain["current_candidate"];
        if result["stale_candidate"] != true {
            if result["rendered_generation_id"] != domain["generation_id"]
                || result["rendered_revision_id"] != domain["revision_id"]
                || candidate["valid"] != true
            {
                return Err("render_candidate_mismatch".into());
            }
            // A draft build tags its export name (run_record.py).
            let step_name = if candidate["draft"] == true {
                "model-draft.step"
            } else {
                "model.step"
            };
            let step = util::safe_file(
                &store.path,
                &format!(
                    "{}/{step_name}",
                    candidate["path"].as_str().ok_or("render_candidate_path")?
                ),
            )?;
            if result["geometry_audit"]["source"] != "independently_reimported_exported_STEP"
                || result["geometry_audit"]["step_sha256"] != util::file_hash(&step)?
            {
                return Err("render_step_identity".into());
            }
        }
    }
    store.state.domain_checkpoint_sha256 = Some(checkpoint);
    store.state.worker_implementation_sha256 = Some(response.implementation_sha256.clone());
    store.state.audit_implementation_sha256 = audit_pin;
    store.state.source_manifest_sha256 =
        domain["source_manifest_sha256"].as_str().map(String::from);
    store.state.generation_id = domain["generation_id"].as_str().map(String::from);
    store.state.revision_id = domain["revision_id"].as_str().map(String::from);
    store.state.domain = domain;
    store.state.last_observation = result;
    store.state.pending = None;
    store.state.status = Status::Running;
    store.state.termination_reason = None;
    store.append(if reconciled{"worker_reconciled"}else{"worker_result"},json!({"operation":pending.operation,"response":response,"receipt":store::artifact(&store.path,&pending.response_path,"worker_receipt")?,"supervision":supervision}))?;
    if worker::cancelled(&store.path) {
        stop(store, Status::Cancelled, "cancelled_after_worker_receipt")?;
        return Ok(false);
    }
    Ok(true)
}

type BoundImage = (u64, Value, Option<String>, Option<String>, Option<String>);
fn visit(
    v: &Value,
    seq: u64,
    g: &Option<String>,
    r: &Option<String>,
    step: &Option<String>,
    out: &mut BTreeMap<String, BoundImage>,
) {
    match v {
        Value::Object(o) => {
            if v["model_eligible"] == true && v["mime_type"] == "image/png" {
                if let Some(id) = v["id"].as_str() {
                    out.insert(
                        id.into(),
                        (
                            seq,
                            v.clone(),
                            v["generation_id"].as_str().map(String::from).or(g.clone()),
                            v["revision_id"].as_str().map(String::from).or(r.clone()),
                            v["step_sha256"].as_str().map(String::from).or(step.clone()),
                        ),
                    );
                }
            }
            for value in o.values() {
                visit(value, seq, g, r, step, out);
            }
        }
        Value::Array(a) => {
            for value in a {
                visit(value, seq, g, r, step, out);
            }
        }
        _ => (),
    }
}
/// The live model investigates in draft mode: it has the investigation tools,
/// its own prompt, and accepted claims become open guesses.
fn investigation_mode(store: &Store) -> bool {
    store.state.config.policy == Policy::Live
        && store.state.config.on_ambiguity == OnAmbiguity::Draft
}
fn collect_images(store: &Store) -> Result<Vec<(ImageReceipt, String)>> {
    let mut found = BTreeMap::<String, BoundImage>::new();
    for e in &store.events {
        let o = &e.payload["response"]["result"];
        let g = o["rendered_generation_id"].as_str().map(String::from);
        let r = o["rendered_revision_id"].as_str().map(String::from);
        let step = o["geometry_audit"]["step_sha256"]
            .as_str()
            .map(String::from);
        visit(o, e.sequence, &g, &r, &step, &mut found);
    }
    let mut values = found.into_values().collect::<Vec<_>>();
    values.retain(|(_, a, g, r, _)| {
        a.get("view").is_none()
            || (g == &store.state.generation_id && r == &store.state.revision_id)
    });
    let investigating = investigation_mode(store);
    if investigating {
        // The model asked for these pixels: the newest views come first.
        values.sort_by_key(|(seq, _, _, _, _)| std::cmp::Reverse(*seq));
    } else {
        values.sort_by_key(|(seq, a, _, _, _)| (!a.get("view").is_some(), std::cmp::Reverse(*seq)));
    }
    // Preserve at least one source observation beside current CAD observations.
    let mut chosen = vec![];
    if investigating {
        chosen.extend(
            values
                .iter()
                .take(store.state.config.limits.max_images_per_request)
                .cloned(),
        );
    } else if let Some(source) = values
        .iter()
        .filter(|(_, a, _, _, _)| a.get("view").is_none())
        .min_by_key(|(seq, a, _, _, _)| {
            (a["evidence_kind"] != "source_page", std::cmp::Reverse(*seq))
        })
    {
        chosen.push(source.clone());
    }
    for v in values {
        if chosen.len() >= store.state.config.limits.max_images_per_request {
            break;
        }
        if !chosen.iter().any(|x| x.1["id"] == v.1["id"]) {
            chosen.push(v);
        }
    }
    let mut images = vec![];
    for (_, a, g, r, step) in chosen {
        let path = a["path"].as_str().ok_or("image_path")?;
        let bytes = util::read_bounded(
            &util::safe_file(&store.path, path)?,
            store.state.config.limits.max_image_bytes,
        )?;
        provider::check_png(&bytes)?;
        let sha = util::hash(&bytes);
        if a["sha256"] != sha {
            return Err("image_hash_changed".into());
        }
        let meta = ImageReceipt {
            artifact_id: a["id"].as_str().ok_or("image_id")?.into(),
            path: path.into(),
            sha256: sha,
            bytes: bytes.len() as u64,
            mime_type: "image/png".into(),
            evidence_kind: if a["view"].is_string() && !a["evidence_kind"].is_string() {
                "step_reimport_render"
            } else {
                a["evidence_kind"]
                    .as_str()
                    .or(a["kind"].as_str())
                    .unwrap_or("unknown")
            }
            .into(),
            view: a["view"].as_str().map(String::from),
            generation_id: g,
            revision_id: r,
            step_sha256: step,
            pixels_attached: true,
            // Investigation receipts record the sheet region and the pixel
            // size of every image sent.
            crop_box_px: if investigating {
                serde_json::from_value(a["crop_box_px"].clone()).ok()
            } else {
                None
            },
            pixel_size: investigating.then(|| provider::png_size(&bytes)),
        };
        images.push((meta, STANDARD.encode(bytes)));
    }
    Ok(images)
}
/// The live model's tools. `build_draft` is offered only when the task's
/// ambiguity policy is `draft`.
pub fn tool_catalog(on_ambiguity: &OnAmbiguity) -> Value {
    let empty = json!({"type":"object","properties":{},"additionalProperties":false});
    let mut tools = base_tool_catalog(&empty);
    if *on_ambiguity == OnAmbiguity::Draft {
        tools.as_array_mut().unwrap().insert(3, json!({"name":"build_draft","description":"After every section is inspected: build a best-effort draft that takes the best-scoring line where a section is ambiguous and spans unreadable stations. Each choice is an open guess; a draft is never verified and only a person can resolve its guesses.","parameters":empty}));
        tools
            .as_array_mut()
            .unwrap()
            .extend(investigation_catalog());
    }
    tools
}
/// Investigation tools of the live model (draft mode only). Each one is
/// executed by the harness; every claim is checked by deterministic code.
fn investigation_catalog() -> Vec<Value> {
    let region = json!({"type":"array","items":{"type":"integer","minimum":0},"minItems":4,"maxItems":4,"description":"[left, top, right, bottom] in sheet pixels"});
    let id = json!({"type":"string","maxLength":64});
    vec![
        json!({"name":"view_region","description":"Return the pixels of any sheet region at any zoom (up to 1024 px per side, 4x enlargement). Start with the whole sheet, then zoom.","parameters":{"type":"object","properties":{"region_px":region,"max_side_px":{"type":"integer","minimum":256,"maximum":1024}},"required":["region_px"],"additionalProperties":false}}),
        json!({"name":"read_region","description":"Return the pixels of a region to read station labels, a scale bar, dimensions or the title block. What you read is your claim.","parameters":{"type":"object","properties":{"region_px":region,"subject":{"enum":["labels","scale_bar","dimensions","title_block"]}},"required":["region_px","subject"],"additionalProperties":false}}),
        json!({"name":"trace_corridor","description":"Draw a corridor on a view (2-24 points in that view's pixels, top to bottom, and a half width in view pixels) around one curve of a section. The host traces the real ink in it and re-reads it with the engine; it returns a candidate id with support scores, or refuses when no ink supports one continuous line.","parameters":{"type":"object","properties":{"section_id":id,"view_id":id,"path_px":{"type":"array","items":{"type":"array","items":{"type":"number"},"minItems":2,"maxItems":2},"minItems":2,"maxItems":24},"half_width_px":{"type":"number","minimum":1,"maximum":64}},"required":["section_id","view_id","path_px","half_width_px"],"additionalProperties":false}}),
        json!({"name":"enumerate_strokes","description":"The host traces every ink stroke of this section's drawing panel (or those crossing one height) and returns one image with each stroke in its own colour and a numbered tag at its top end and middle, plus each tag's candidate id. All sections that share the panel get these candidates. Usually the best first step on a crowded body plan.","parameters":{"type":"object","properties":{"section_id":id,"height_m":{"type":"number"}},"required":["section_id"],"additionalProperties":false}}),
        json!({"name":"trace_from_point","description":"Click one point on a curve of a section (in a view's pixels, on the ink itself, for example just below its label). The host follows that ink stroke up and down, then traces and verifies it like a corridor; it returns a candidate id or refuses with an image of the point.","parameters":{"type":"object","properties":{"section_id":id,"view_id":id,"point_px":{"type":"array","items":{"type":"number"},"minItems":2,"maxItems":2}},"required":["section_id","view_id","point_px"],"additionalProperties":false}}),
        json!({"name":"assign_station","description":"Claim that a traced candidate is this section's station line, with the label you read and the view where you read it. Checked by the host; if accepted it is an open model_choice guess for a person to confirm.","parameters":{"type":"object","properties":{"section_id":id,"candidate_id":id,"label_view_id":id,"label_text":{"type":"string","maxLength":64},"reason":{"type":"string","maxLength":300},"comparison_id":id},"required":["section_id","candidate_id","label_view_id","label_text","reason"],"additionalProperties":false}}),
        json!({"name":"propose_sheet_setup","description":"Propose the scale and datum lines of one view (body, plan or profile). The host checks them against the drawn grid and the declared calibration. Accepted setups serve compare_views; the build keeps the declared calibration.","parameters":{"type":"object","properties":{"view":{"enum":["body","plan","profile"]},"region_px":region,"pixels_per_metre":{"type":"number"},"grid_spacing_m":{"type":"number"},"centreline_px":{"type":"number"},"baseline_px":{"type":"number"},"x_origin_px":{"type":"number"},"x_direction":{"enum":[1,-1]},"evidence_view_id":id,"scale_claim":{"type":"string","maxLength":128},"reason":{"type":"string","maxLength":300}},"required":["view","region_px","pixels_per_metre","grid_spacing_m","evidence_view_id","scale_claim","reason"],"additionalProperties":false}}),
        json!({"name":"compare_views","description":"Compare a candidate's body-plan half-breadths at given heights with ink on the plan-view station line of an accepted plan setup.","parameters":{"type":"object","properties":{"section_id":id,"candidate_id":id,"setup_id":id,"heights_m":{"type":"array","items":{"type":"number"},"minItems":1,"maxItems":12}},"required":["section_id","candidate_id","setup_id","heights_m"],"additionalProperties":false}}),
        json!({"name":"ask_person","description":"Stop and ask a person a question when the evidence is insufficient.","parameters":{"type":"object","properties":{"question":{"type":"string","maxLength":512}},"required":["question"],"additionalProperties":false}}),
    ]
}
fn base_tool_catalog(empty: &Value) -> Value {
    json!([
        {"name":"inspect_source","description":"Inspect source regions and preserved candidate alternatives; section_ids optional, at most12 sections per observation.","parameters":{"type":"object","properties":{"section_ids":{"type":"array","items":{"type":"string"}}},"additionalProperties":false}},
        {"name":"select_contours","description":"Choose already inspected candidate IDs; retains alternatives and invalidates previous validation and renders.","parameters":{"type":"object","properties":{"selections":{"type":"array","items":{"type":"object","properties":{"section_id":{"type":"string"},"candidate_id":{"type":"string"}},"required":["section_id","candidate_id"],"additionalProperties":false}}},"required":["selections"],"additionalProperties":false}},
        {"name":"build_provisional","description":"Build current source-supported selections with the trusted CAD engine.","parameters":empty},
        {"name":"render_candidate","description":"Reimport exported STEP and render view for visual inspection.","parameters":{"type":"object","properties":{"view":{"enum":["body","plan","profile","oblique"]}},"required":["view"],"additionalProperties":false}},
        {"name":"validate_candidate","description":"Audit current exported STEP against selected source traces; failures remain failures on cache hits.","parameters":empty},
        {"name":"finish","description":"Abstain or request human review after current passing validation and visual inspection; never engineering approval.","parameters":{"type":"object","properties":{"outcome":{"enum":["candidate_ready_for_review","abstain"]},"summary":{"type":"string","maxLength":512}},"required":["outcome","summary"],"additionalProperties":false}}
    ])
}
/// The investigating model's observation: a compact task state (one line per
/// section), the last tool result and the recent history. Full evidence stays
/// in the task; the model asks for more with the tools.
fn investigation_observation(store: &Store) -> Result<Value> {
    let d = &store.state.domain;
    let guesses = d["open_guesses"]
        .as_array()
        .map(|g| {
            g.iter()
                .filter_map(|g| Some((g["section_id"].as_str()?, g)))
                .collect::<BTreeMap<_, _>>()
        })
        .unwrap_or_default();
    let sections = d["sections"].as_array().map(|s| {
        s.iter()
            .map(|s| {
                let guess = s["id"].as_str().and_then(|id| guesses.get(id));
                json!({"id":s["id"],"x_m":s["x_m"],"panel_roi_px":s["roi_px"],"inspected":s["inspected"],
                    "selected_candidate_id":s["selected_candidate_id"],
                    "guess":guess.map(|g| json!({"kind":g["kind"],"chosen_candidate_id":g["chosen_candidate_id"]}))})
            })
            .collect::<Vec<_>>()
    });
    // Keep the latest tagged strokes of each panel across later label views.
    // Otherwise the model sees pixels but loses the candidate ids to assign.
    let mut panels = vec![];
    let mut seen_panels = std::collections::BTreeSet::new();
    for event in store.events.iter().rev() {
        let result = &event.payload["response"]["result"];
        if result["status"] == "strokes_enumerated" {
            let key = util::hash_json(&result["panel_section_ids"])?;
            if seen_panels.insert(key) {
                panels.push(json!({"panel_section_ids":result["panel_section_ids"],
                    "strokes":result["strokes"], "view":result["view"]}));
            }
        }
    }
    let candidate = &d["current_candidate"];
    let history = store
        .events
        .iter()
        .rev()
        .filter(|e| {
            ["decision", "operation_rejected", "model_output_rejected"].contains(&e.kind.as_str())
        })
        .take(12)
        .map(|e| {
            json!({"kind":e.kind,"tool":e.payload["decision"]["tool"],
                "arguments":e.payload["decision"]["arguments"],"reason":e.payload["reason"]})
        })
        .collect::<Vec<_>>();
    let mut value = json!({"task_id":store.state.task_id,
        "sections":sections,"catalog_ready":d["catalog_ready"],"selected_count":d["selected_count"],
        "open_guess_count":guesses.len(),"model_choice_section_ids":d["model_choice_section_ids"],
        "sheet_setup_ids":d["sheet_setup_ids"],"rendered_views":d["rendered_views"],
        "current_draft":if candidate.is_null(){Value::Null}else{json!({"valid":candidate["valid"],"draft":candidate["draft"],"status":candidate["status"]})},
        "last_observation":store.state.last_observation,"recent_history_newest_first":history,
        "retained_stroke_panels":panels,"omitted_stroke_panel_ids":[],
        "current_policy":"live_investigation","engineering_approved":false,
        "source_truth":"source evidence and deployment-available checks only; no evaluator references"});
    // Images are attached separately. Their artifact inventories can be large;
    // omit them before reducing tool evidence such as tags and view mappings.
    if let Some(last) = value["last_observation"].as_object_mut() {
        last.remove("artifacts");
    }
    let limit = store.state.config.limits.max_observation_bytes;
    while util::json_bytes(&value)?.len() > limit
        && !value["retained_stroke_panels"]
            .as_array()
            .unwrap()
            .is_empty()
    {
        let removed = value["retained_stroke_panels"]
            .as_array_mut()
            .unwrap()
            .pop()
            .unwrap();
        value["omitted_stroke_panel_ids"]
            .as_array_mut()
            .unwrap()
            .push(removed["panel_section_ids"].clone());
    }
    if util::json_bytes(&value)?.len() > limit {
        // A large inspection result keeps its section and candidate ids only.
        let last = &store.state.last_observation;
        let reduced = last["sections"].as_array().map(|sections| {
            sections
                .iter()
                .map(|s| json!({"section_id":s["section_id"],"candidates":s["candidates"].as_array().map(|c| c.iter().map(|c| json!({"candidate_id":c["candidate_id"],"hypothesis":c["hypothesis"],"selectable":c["selectable"],"non_grid_competing_components":c["non_grid_competing_components"]})).collect::<Vec<_>>())}))
                .collect::<Vec<_>>()
        });
        value["last_observation"] = json!({"ok":last["ok"],"status":last["status"],"error_code":last["error_code"],
            "message":last["message"],"sections":reduced,"truncated_for_size":true});
    }
    if util::json_bytes(&value)?.len() > limit {
        return Err("observation_size_limit".into());
    }
    Ok(value)
}
fn model_observation(store: &Store) -> Result<Value> {
    if investigation_mode(store) {
        return investigation_observation(store);
    }
    let history=store.events.iter().rev().filter(|e|["decision","worker_result","worker_reconciled","operator_intervention"].contains(&e.kind.as_str())).take(10).map(|e|json!({"sequence":e.sequence,"kind":e.kind,"decision":e.payload.get("decision"),"operation":e.payload.get("operation"),"status":e.payload["response"]["result"]["status"],"error_code":e.payload["response"]["result"]["error_code"]})).collect::<Vec<_>>();
    let previous_failure=store.events.iter().rev().find(|e|["provider_result","provider_reconciled"].contains(&e.kind.as_str())&&e.payload["receipt"]["state"]=="failed")
        .map(|e|json!({"request_id":e.payload["receipt"]["request_id"],"error_code":e.payload["receipt"]["error_code"],"automatic_retry":false}));
    // Source evidence is persistent task memory, not just the immediately last
    // tool result. In particular an existing-candidate continuation must retain
    // the same alternatives and endpoint witnesses shown during inspection.
    let mut source_memory = BTreeMap::<String, Value>::new();
    if !store.state.last_observation["sections"].is_array() {
        for event in store.events.iter().rev() {
            if let Some(sections) = event.payload["response"]["result"]["sections"].as_array() {
                for section in sections {
                    if let Some(id) = section["section_id"].as_str() {
                        if source_memory.len() < 12 && !source_memory.contains_key(id) {
                            source_memory.insert(id.to_string(), section.clone());
                        }
                    }
                }
            }
        }
    }
    let mut value = json!({"task_id":store.state.task_id,"domain":store.state.domain,"last_observation":store.state.last_observation,"previous_failed_provider_attempt":previous_failure,
        "retained_source_observations":source_memory.values().cloned().collect::<Vec<_>>(),"omitted_source_observation_ids":[],
        "recent_history_newest_first":history,"current_policy":"live","engineering_approved":false,"source_truth":"source evidence and deployment-available checks only; no evaluator references"});
    while util::json_bytes(&value)?.len() > store.state.config.limits.max_observation_bytes
        && !value["retained_source_observations"]
            .as_array()
            .unwrap()
            .is_empty()
    {
        let removed = value["retained_source_observations"]
            .as_array_mut()
            .unwrap()
            .pop()
            .unwrap();
        value["omitted_source_observation_ids"]
            .as_array_mut()
            .unwrap()
            .push(removed["section_id"].clone());
    }
    if util::json_bytes(&value)?.len() > store.state.config.limits.max_observation_bytes {
        return Err("observation_size_limit".into());
    }
    Ok(value)
}

/// The decision purpose of this task: investigation in live draft mode.
fn decision_purpose(store: &Store) -> provider::Purpose {
    if investigation_mode(store) {
        provider::Purpose::Investigation
    } else {
        provider::Purpose::ModelDecision
    }
}
fn apply_provider(
    store: &mut Store,
    pending: &Pending,
    supervision: Value,
    reconciled: bool,
) -> Result<Option<Receipt>> {
    let path = store.path.join(&pending.response_path);
    if !path.is_file() && supervision["spawned"] == false {
        store.state.counters.requests_not_sent += 1;
        store.state.pending = None;
        store.append(
            "provider_not_sent",
            json!({"request_id":pending.id,"supervision":supervision,"state":"not_sent"}),
        )?;
        stop(
            store,
            if worker::cancelled(&store.path) {
                Status::Cancelled
            } else {
                Status::ProviderFailed
            },
            "provider_worker_not_started",
        )?;
        return Ok(None);
    }
    if !path.is_file() {
        store.state.counters.requests_unknown += 1;
        store.state.counters.requests_without_cost += 1;
        store.state.pending = None;
        store.append("provider_outcome_unknown",json!({"request_id":pending.id,"supervision":supervision,"state":"transmission_or_completion_unknown","automatic_retry":false}))?;
        stop(
            store,
            Status::Interrupted,
            "provider_transmission_or_completion_unknown",
        )?;
        return Ok(None);
    }
    let receipt: Receipt = util::parse(
        &util::read_bounded(&path, 2 * 1024 * 1024)?,
        2 * 1024 * 1024,
    )?;
    let input: ProviderInput = util::parse(
        &util::read_bounded(
            &util::safe_file(&store.path, &pending.request_path)?,
            2 * 1024 * 1024,
        )?,
        2 * 1024 * 1024,
    )?;
    if receipt.protocol != provider::PROTOCOL
        || receipt.request_id != pending.id
        || receipt.endpoint != GO_ENDPOINT
        || receipt.requested_model != GO_MODEL
        || receipt.evidence_mode != "live"
        // The controller loop accepts only decision receipts of the task's
        // mode; a table transcription receipt can never stage a decision here.
        || receipt.purpose != decision_purpose(store)
        || input.purpose != receipt.purpose
        || receipt.transcription.is_some()
        || receipt.source_manifest_sha256
            != store.state.source_manifest_sha256.as_deref().unwrap_or("")
        || receipt.generation_id != store.state.generation_id.as_deref().unwrap_or("")
        || receipt.revision_id != store.state.revision_id.as_deref().unwrap_or("")
    {
        return Err("provider_receipt_identity".into());
    }
    if receipt.request_sha256 != util::hash_json(&input.payload)?
        || receipt.prompt_sha256 != util::hash(receipt.purpose.prompt().as_bytes())
        || receipt.observation_sha256 != input.observation_sha256
        || util::hash_json(&receipt.images)? != util::hash_json(&input.images)?
        || receipt.attempt != input.attempt
        || receipt.retry_of != input.retry_of
        || !receipt.latency_seconds.is_finite()
        || receipt.latency_seconds < 0.
        || receipt
            .response_sha256
            .as_deref()
            .is_some_and(|h| !util::valid_hash(h))
    {
        return Err("provider_receipt_request_binding".into());
    }
    if receipt.state == RequestState::Completed
        && (receipt.http_status != Some(200)
            || receipt.response_sha256.is_none()
            || receipt.error_code.is_some())
        || receipt.state != RequestState::Completed && receipt.decision.is_some()
    {
        return Err("provider_receipt_state_contradiction".into());
    }
    let usage = receipt.usage.as_object().ok_or("provider_usage_type")?;
    for (name, value) in usage {
        match name.as_str() {
            "prompt_tokens" | "completion_tokens" | "total_tokens" => {
                if value.as_u64().is_none_or(|n| n > 1_000_000_000) {
                    return Err("provider_usage_integer".into());
                }
            }
            "cost" | "list_cost" | "allowance" => {
                if value.as_f64().is_none_or(|n| !n.is_finite() || n < 0.) {
                    return Err("provider_usage_cost".into());
                }
            }
            "billing_source" => {
                if !value
                    .as_str()
                    .is_some_and(|s| ["go", "go-plus", "free", "balance", "byok"].contains(&s))
                {
                    return Err("provider_billing_source".into());
                }
            }
            _ => return Err("provider_unknown_usage_field".into()),
        }
    }
    if receipt.observed_cost_usd != receipt.usage.get("cost").and_then(Value::as_f64) {
        return Err("provider_cost_receipt_contradiction".into());
    }
    // An investigation decision must be derivable from the raw response body
    // that the provider worker stored: an edited decision, model or usage in
    // the receipt is refused.
    if receipt.purpose == provider::Purpose::Investigation && receipt.http_status == Some(200) {
        let body = util::read_bounded(
            &util::safe_file(&store.path, &provider::body_path(&pending.response_path))
                .map_err(|_| "provider_receipt_body_missing")?,
            262_144,
        )
        .map_err(|_| "provider_receipt_body_missing")?;
        provider::verify_receipt_body(&receipt, &body)?;
    }
    if let (Some(p), Some(c), Some(t)) = (
        receipt.usage["prompt_tokens"].as_u64(),
        receipt.usage["completion_tokens"].as_u64(),
        receipt.usage["total_tokens"].as_u64(),
    ) {
        if p + c != t {
            return Err("provider_usage_total_contradiction".into());
        }
    }
    match receipt.state {
        RequestState::Completed => {
            if receipt.returned_model.as_deref() != Some(GO_MODEL) || receipt.decision.is_none() {
                return Err("provider_completion_incomplete".into());
            }
            receipt.decision.as_ref().unwrap().operation()?;
            store.state.counters.requests_completed += 1;
            store.state.counters.policy_decisions += 1;
            store.state.staged_decision = receipt.decision.clone();
        }
        RequestState::Failed => store.state.counters.requests_failed += 1,
        RequestState::NotSent => store.state.counters.requests_not_sent += 1,
        RequestState::TransmissionOrCompletionUnknown => store.state.counters.requests_unknown += 1,
    }
    store.state.counters.prompt_tokens += receipt.usage["prompt_tokens"].as_u64().unwrap_or(0);
    store.state.counters.completion_tokens +=
        receipt.usage["completion_tokens"].as_u64().unwrap_or(0);
    if let Some(cost) = receipt.observed_cost_usd {
        if !cost.is_finite() || cost < 0. {
            return Err("provider_cost_type".into());
        }
        store.state.counters.observed_cost_usd += cost;
    } else {
        store.state.counters.requests_without_cost += 1;
    }
    store.state.pending = None;
    store.append(if reconciled{"provider_reconciled"}else{"provider_result"},json!({"receipt":receipt,"receipt_file":store::artifact(&store.path,&pending.response_path,"provider_receipt")?,"supervision":supervision}))?;
    if receipt.state == RequestState::TransmissionOrCompletionUnknown {
        stop(
            store,
            Status::Interrupted,
            "provider_transmission_or_completion_unknown",
        )?;
    }
    Ok(Some(receipt))
}
fn live_decision(store: &mut Store) -> Result<bool> {
    if !store.state.config.provider_transfer_authorized
        || store.state.config.authorization_basis.is_empty()
    {
        return Err("provider_transfer_not_authorized".into());
    }
    let observation = model_observation(store)?;
    let images = collect_images(store)?;
    let metas = images.iter().map(|x| x.0.clone()).collect::<Vec<_>>();
    let prompt = json!({"observation":observation,"tools":tool_catalog(&store.state.config.on_ambiguity),"images":metas});
    let mut content = vec![
        json!({"type":"text","text":String::from_utf8(util::json_bytes(&prompt)?).map_err(|_|"prompt_encoding")?}),
    ];
    for (_, pixels) in images {
        content.push(json!({"type":"image_url","image_url":{"url":format!("data:image/png;base64,{pixels}"),"detail":"original"}}));
    }
    let purpose = decision_purpose(store);
    let payload = json!({"model":GO_MODEL,"max_tokens":store.state.config.limits.max_output_tokens_per_request,"stream":false,"thinking":{"type":"disabled"},"temperature":0,
        "response_format":{"type":"json_object"},"messages":[{"role":"system","content":purpose.prompt()},{"role":"user","content":content}]});
    let mut retry_of = None;
    for attempt in 1..=3 {
        budget_admission(store)?;
        current_binary(store)?;
        let id = format!("request-{}", util::nonce());
        let pending = Pending {
            kind: "provider".into(),
            id: id.clone(),
            operation: "model_decision".into(),
            response_path: format!("receipts/{id}.json"),
            request_path: format!("requests/{id}.json"),
            domain_before: store.state.domain_checkpoint_sha256.clone(),
            started_ms: util::now_ms(),
        };
        let input = ProviderInput {
            protocol: provider::PROTOCOL.into(),
            request_id: id.clone(),
            source_manifest_sha256: store
                .state
                .source_manifest_sha256
                .clone()
                .ok_or("source_binding")?,
            generation_id: store
                .state
                .generation_id
                .clone()
                .ok_or("generation_binding")?,
            revision_id: store.state.revision_id.clone().ok_or("revision_binding")?,
            observation_sha256: util::hash_json(&prompt)?,
            images: metas.clone(),
            payload: payload.clone(),
            attempt,
            retry_of: retry_of.clone(),
            purpose,
        };
        util::atomic_json(&store.path.join(&pending.request_path), &input, false)?;
        store.state.pending = Some(pending.clone());
        store.state.counters.requests_intended += 1;
        store.append("provider_intent",json!({"request_id":id,"request":store::artifact(&store.path,&pending.request_path,"provider_request")?,"source_manifest_sha256":input.source_manifest_sha256,"images":metas,"attempt":attempt,"retry_of":retry_of,"aggregate_caps":null}))?;
        let outcome = worker::run(
            &store.path,
            &store.state.config,
            &pending,
            &util::json_bytes(&input)?,
            &source_spec(store),
        )?;
        let receipt = apply_provider(store, &pending, json!(outcome), false)?;
        let Some(receipt) = receipt else {
            return Ok(false);
        };
        if receipt.state == RequestState::Completed {
            return Ok(true);
        }
        if receipt.state == RequestState::TransmissionOrCompletionUnknown {
            return Ok(false);
        }
        if purpose == provider::Purpose::Investigation && model_output_refused(&receipt) {
            // The model answered, but not with one valid tool call. The reason
            // goes back to it as an observation; repeated refusals stop.
            store.state.last_observation = json!({"ok":false,"status":"rejected",
                "error_code":receipt.error_code,"message":"Your reply was not one valid tool call within the argument bounds. Reply with one JSON object: tool, arguments, reason.",
                "engineering_approved":false,"human_semantic_review_required":true});
            store.append(
                "model_output_rejected",
                json!({"request_id":id,"reason":receipt.error_code}),
            )?;
            if consecutive_refusals(store) > refusal_limit(store) {
                stop(store, Status::NoProgress, "repeated_refused_model_output")?;
                return Ok(false);
            }
            return Ok(true);
        }
        let retryable = receipt.state == RequestState::Failed
            && matches!(receipt.http_status, Some(429 | 502 | 503 | 504))
            && receipt.error_code.as_deref()
                != Some("provider_retry_after_requires_deferred_resume")
            && attempt < 3;
        let wait = receipt.retry_after_seconds.unwrap_or(2u64.pow(attempt));
        if retryable && wait <= 30 {
            store.append(
                "provider_backoff",
                json!({"request_id":id,"seconds":wait,"next_attempt":attempt+1}),
            )?;
            let until = Instant::now() + Duration::from_secs(wait);
            while Instant::now() < until {
                if worker::cancelled(&store.path) {
                    stop(store, Status::Cancelled, "cancelled_during_backoff")?;
                    return Ok(false);
                }
                std::thread::sleep(Duration::from_millis(25));
            }
            retry_of = Some(id);
            continue;
        }
        stop(
            store,
            Status::ProviderFailed,
            receipt
                .error_code
                .as_deref()
                .unwrap_or("provider_request_not_completed"),
        )?;
        return Ok(false);
    }
    Ok(false)
}

/// A completed HTTP exchange whose content was not one valid tool call (bad
/// JSON, unknown tool, arguments out of bounds). Transport, identity and
/// credential failures are not model output and still stop the task.
fn model_output_refused(receipt: &Receipt) -> bool {
    receipt.state == RequestState::Failed
        && receipt.http_status == Some(200)
        && receipt.returned_model.as_deref() == Some(GO_MODEL)
        && !matches!(
            receipt.error_code.as_deref(),
            None | Some(
                "provider_credential_echo"
                    | "provider_model_identity"
                    | "provider_response_limit"
                    | "provider_incomplete_or_unexpected_choice"
            )
        )
}
/// Refused proposals and refused outputs since the model's last accepted action.
fn consecutive_refusals(store: &Store) -> u64 {
    let mut count = 0;
    for event in store.events.iter().rev() {
        match event.kind.as_str() {
            "operation_rejected" | "model_output_rejected" => count += 1,
            // Provider bookkeeping between refusals is not an accepted action.
            "provider_intent" | "provider_result" | "provider_reconciled" | "provider_backoff" => {}
            _ => break,
        }
    }
    count
}
/// Consecutive refusals allowed before a no-progress stop.
fn refusal_limit(store: &Store) -> u64 {
    2 * store.state.config.limits.max_repeated_action
}
/// Model decisions allowed without progress. Progress is a change of the
/// generation (an assignment or a selection) or a build. This is a
/// no-progress stop, not an aggregate cap: any number of decisions is allowed
/// while the model makes progress.
const NO_PROGRESS_DECISIONS: usize = 40;
fn decisions_without_progress(store: &Store) -> usize {
    let mut count = 0;
    let generation = &store.state.generation_id;
    for event in store.events.iter().rev() {
        if event.kind == "decision" && event.payload["actor"] == "live_model" {
            let tool = event.payload["decision"]["tool"]
                .as_str()
                .unwrap_or_default();
            if ["build_draft", "build_provisional"].contains(&tool) {
                break;
            }
            count += 1;
        }
        if event.kind == "worker_result"
            && event.payload["response"]["domain"]["generation_id"].as_str()
                != generation.as_deref()
        {
            break;
        }
    }
    count
}
/// Rejections that return to the live model as observations. Other errors
/// (integrity, identity, storage) still stop the task.
const PROPOSAL_REFUSALS: [&str; 13] = [
    "guess_requires_operator_confirmation",
    "unknown_or_unsupported_candidate",
    "source_ambiguity_requires_explicit_operator_selection",
    "model_traced_candidate_requires_person",
    "unsnapped_or_unknown_candidate",
    "section_already_selected",
    "unknown_section_id",
    "uninspected_section",
    "candidate_missing",
    "investigation_requires_draft_mode",
    "draft_mode_disabled",
    "investigation_argument_bounds",
    "operation_contract",
];
/// What the model can do instead of a refused proposal. Guidance only: the
/// refusal itself does not change.
fn refusal_hint(code: &str) -> &'static str {
    match code {
        "source_ambiguity_requires_explicit_operator_selection"
        | "model_traced_candidate_requires_person"
        | "guess_requires_operator_confirmation" => {
            "A model cannot select this line. Make a view of the section (view_region or read_region), then call assign_station with this candidate_id, that view_id as label_view_id, the label you read and your reason. It becomes an open guess for a person."
        }
        "unsnapped_or_unknown_candidate" | "unknown_or_unsupported_candidate" | "candidate_missing" => {
            "Use a candidate id returned by inspect_source or trace_corridor for this section. To get a new one, draw a corridor around the curve on a view with trace_corridor."
        }
        "section_already_selected" => {
            "This section already has a selected line; work on another section."
        }
        _ => "Revise the arguments within the tool bounds, or choose another tool.",
    }
}
/// Harness preparation of a live investigation: the deterministic inspection
/// of every section and the unique source-supported selections, exactly as
/// the deterministic draft policy makes them. No model call is spent on it.
fn investigation_preparation(store: &Store) -> Result<Option<Decision>> {
    if !investigation_mode(store) || store.state.last_observation["ok"] == false {
        return Ok(None);
    }
    let d = &store.state.domain;
    if d["input_errors"].as_array().is_some_and(|a| !a.is_empty()) {
        return Ok(None);
    }
    let prepared = deterministic_decision(store)?;
    Ok(["inspect_source", "select_contours"]
        .contains(&prepared.tool.as_str())
        .then_some(prepared))
}
fn decision(tool: &str, arguments: Value, reason: &str) -> Decision {
    Decision {
        tool: tool.into(),
        arguments,
        reason: reason.into(),
    }
}
/// Inspect the next uninspected sections, named explicitly.
///
/// The Python domain inspects a CPU-bounded prefix of the named sections, so a
/// large drawing needs more calls than `max_repeated_action` allows for one
/// identical action. Naming the sections makes each call that inspects new
/// sections a different action; a call that inspects nothing new repeats the
/// same names and still stops at the repeat limit.
fn inspect_next(sections: &[Value]) -> Decision {
    let ids = sections
        .iter()
        .filter(|s| s["inspected"] != true)
        .filter_map(|s| s["id"].as_str())
        .take(12)
        .collect::<Vec<_>>();
    let arguments = if ids.is_empty() {
        json!({})
    } else {
        json!({"section_ids":ids})
    };
    decision(
        "inspect_source",
        arguments,
        "Inspect the next source regions and retain alternatives.",
    )
}
pub fn deterministic_decision(store: &Store) -> Result<Decision> {
    let d = &store.state.domain;
    let last = &store.state.last_observation;
    let abstain = |reason: &str| {
        decision(
            "finish",
            json!({"outcome":"abstain","summary":reason}),
            "Deterministic source-grammar comparison; no model inference.",
        )
    };
    if d["input_errors"].as_array().is_some_and(|a| !a.is_empty()) {
        return Ok(abstain(
            "Invalid source specification or calibration; inspect the recorded input errors.",
        ));
    }
    if last["ok"] == false {
        let code = last["error_code"]
            .as_str()
            .unwrap_or("source_or_geometry_operation_failed");
        return Ok(abstain(&format!(
            "The deterministic operation failed: {code}. Preserved evidence requires review."
        )));
    }
    let sections = d["sections"].as_array().ok_or("domain_sections_missing")?;
    let selected = sections
        .iter()
        .filter(|s| s["selected_candidate_id"].is_string())
        .filter_map(|s| s["id"].as_str())
        .collect::<std::collections::BTreeSet<_>>();
    if store.state.config.on_ambiguity == OnAmbiguity::Draft {
        return deterministic_draft_mode(store, sections, &selected);
    }
    let inspected = last["sections"]
        .as_array()
        .or(d["inspected_sections"].as_array());
    let mut selections = vec![];
    if let Some(items) = inspected {
        for s in items {
            let id = s["section_id"]
                .as_str()
                .ok_or("inspected_section_identity")?;
            if selected.contains(id) {
                continue;
            }
            let candidates = s["candidates"]
                .as_array()
                .ok_or("candidate_inventory")?
                .iter()
                .filter(|c| c["selectable"] == true)
                .collect::<Vec<_>>();
            let chosen = s["grid_evidence"]["unique_non_grid_candidate_id"]
                .as_str()
                .or_else(|| {
                    if candidates.len() == 1 {
                        candidates[0]["candidate_id"].as_str()
                    } else {
                        None
                    }
                });
            let Some(chosen) = chosen else {
                return Ok(abstain("The source has multiple or no supported contour interpretations. An explicit source-backed selection is required."));
            };
            selections.push(json!({"section_id":id,"candidate_id":chosen}));
        }
    }
    if !selections.is_empty() {
        return Ok(decision(
            "select_contours",
            json!({"selections":selections}),
            "Unique source-grammar hypothesis; semantic identity remains unapproved.",
        ));
    }
    if d["catalog_ready"] != true {
        return Ok(inspect_next(sections));
    }
    if selected.len() < sections.len() {
        let ids = sections
            .iter()
            .filter_map(|s| s["id"].as_str())
            .filter(|id| !selected.contains(id))
            .take(12)
            .collect::<Vec<_>>();
        return Ok(decision(
            "inspect_source",
            json!({"section_ids":ids}),
            "Inspect the remaining unselected sections.",
        ));
    }
    deterministic_build_to_finish(store)
}

/// The unique supported candidate of one inspected section, if any: the grid
/// grammar's unique proposal or the only selectable candidate. With `strict`,
/// the candidate must also have no non-grid competitor, which is what
/// `validate_selection` requires from a policy.
fn unique_choice(section: &Value, strict: bool) -> Option<&str> {
    let selectable = section["candidates"]
        .as_array()?
        .iter()
        .filter(|c| c["selectable"] == true)
        .collect::<Vec<_>>();
    let chosen = section["grid_evidence"]["unique_non_grid_candidate_id"]
        .as_str()
        .or_else(|| match selectable.as_slice() {
            [only] => only["candidate_id"].as_str(),
            _ => None,
        })?;
    if strict {
        let candidate = selectable.iter().find(|c| c["candidate_id"] == chosen)?;
        if candidate["non_grid_competing_components"].as_u64() != Some(0) {
            return None;
        }
    }
    Some(chosen)
}

/// Deterministic policy with `--on-ambiguity draft`. Unique supported lines are
/// selected exactly as in abstain mode. A section without one is not a reason
/// to stop: after full inspection, the policy asks for a draft, which records
/// each remaining choice as an open guess. Sections with an open guess are left
/// to a person. Once every section is selected, the ordinary verified path runs.
fn deterministic_draft_mode(
    store: &Store,
    sections: &[Value],
    selected: &std::collections::BTreeSet<&str>,
) -> Result<Decision> {
    let d = &store.state.domain;
    let guessed = d["open_guesses"]
        .as_array()
        .map(|guesses| {
            guesses
                .iter()
                .filter_map(|g| g["section_id"].as_str())
                .collect::<std::collections::BTreeSet<_>>()
        })
        .unwrap_or_default();
    let catalog_ready = d["catalog_ready"] == true;
    // After full inspection, read every section from the checkpoint catalog:
    // the domain description lists at most 12 inspected sections.
    let checkpoint = if catalog_ready {
        Some(validation::domain_checkpoint(&store.path)?)
    } else {
        None
    };
    let inspected: Vec<&Value> = match &checkpoint {
        Some(checkpoint) => sections
            .iter()
            .filter_map(|s| s["id"].as_str())
            .filter_map(|id| checkpoint["catalog"].get(id))
            .collect(),
        None => store.state.last_observation["sections"]
            .as_array()
            .or(d["inspected_sections"].as_array())
            .map(|items| items.iter().collect())
            .unwrap_or_default(),
    };
    let mut selections = vec![];
    for section in inspected {
        let id = section["section_id"]
            .as_str()
            .ok_or("inspected_section_identity")?;
        if selected.contains(id) || guessed.contains(id) {
            continue;
        }
        if let Some(chosen) = unique_choice(section, true) {
            selections.push(json!({"section_id":id,"candidate_id":chosen}));
        }
    }
    if !selections.is_empty() {
        return Ok(decision(
            "select_contours",
            json!({"selections":selections}),
            "Unique source-grammar hypothesis; semantic identity remains unapproved.",
        ));
    }
    if !catalog_ready {
        return Ok(inspect_next(sections));
    }
    if selected.len() < sections.len() {
        return Ok(decision(
            "build_draft",
            json!({}),
            "Some sections have no unique supported line; build a draft that records each choice as an open guess.",
        ));
    }
    deterministic_build_to_finish(store)
}

/// The verified path after every section is selected: build, render, validate,
/// finish. It is the same for both ambiguity policies.
fn deterministic_build_to_finish(store: &Store) -> Result<Decision> {
    let d = &store.state.domain;
    let abstain = |reason: &str| {
        decision(
            "finish",
            json!({"outcome":"abstain","summary":reason}),
            "Deterministic source-grammar comparison; no model inference.",
        )
    };
    if d["current_candidate"].is_null() {
        return Ok(decision(
            "build_provisional",
            json!({}),
            "Build the selected source traces with the trusted engine.",
        ));
    }
    if d["current_candidate"]["valid"] != true {
        return Ok(abstain("The current native build failed; the failure and any older candidate remain available for diagnosis."));
    }
    let rendered = d["rendered_views"].as_array().cloned().unwrap_or_default();
    for view in ["body", "oblique"] {
        if !rendered.iter().any(|v| v == view) {
            return Ok(decision(
                "render_candidate",
                json!({"view":view}),
                "Inspect a view reimported from the actual exported STEP.",
            ));
        }
    }
    if d["validation"].is_null() {
        return Ok(decision(
            "validate_candidate",
            json!({}),
            "Perform the current deterministic STEP and selected-source audit.",
        ));
    }
    Ok(decision(
        "finish",
        json!({"outcome":if d["validation"]["geometry_checks_passed"]==true{"candidate_ready_for_review"}else{"abstain"},"summary":"Deterministic sequence completed. All semantic and professional review remains outstanding."}),
        "Apply the authoritative current-candidate finalization predicate.",
    ))
}

fn known_section(store: &Store, section_id: &str) -> Result<()> {
    let sections = store.state.domain["sections"]
        .as_array()
        .ok_or("domain_sections_missing")?;
    if sections.iter().any(|s| s["id"] == section_id) {
        Ok(())
    } else {
        Err("unknown_section_id".into())
    }
}
fn validate_selection(store: &Store, operation: &Operation, actor: &str) -> Result<()> {
    if operation.is_investigation() && store.state.config.on_ambiguity != OnAmbiguity::Draft {
        return Err("investigation_requires_draft_mode".into());
    }
    let checkpoint = util::read_json(
        &util::safe_file(&store.path, "domain/state.json")?,
        32 * 1024 * 1024,
    )?;
    let policy = ["live_model", "deterministic_policy"].contains(&actor);
    match operation {
        Operation::SelectContours(x) => {
            for choice in &x.selections {
                // Selecting a guessed section resolves its guess. Only a
                // person may confirm or replace a guess, never a policy.
                if policy
                    && validation::open_guesses(&checkpoint)?
                        .iter()
                        .any(|g| g["section_id"] == choice.section_id.as_str())
                {
                    return Err("guess_requires_operator_confirmation".into());
                }
                let candidates = checkpoint["catalog"][&choice.section_id]["candidates"]
                    .as_array()
                    .ok_or("uninspected_section")?;
                if !candidates
                    .iter()
                    .any(|c| c["candidate_id"] == choice.candidate_id && c["selectable"] == true)
                {
                    return Err("unknown_or_unsupported_candidate".into());
                }
                let candidate = candidates
                    .iter()
                    .find(|c| c["candidate_id"] == choice.candidate_id)
                    .ok_or("candidate_missing")?;
                // A line the model traced is the model's choice: it enters
                // only as an open guess (assign_station), never as a policy
                // selection on the verified path.
                if policy && candidate["model_traced"] == true {
                    return Err("model_traced_candidate_requires_person".into());
                }
                if policy && candidate["non_grid_competing_components"].as_u64() != Some(0) {
                    return Err("source_ambiguity_requires_explicit_operator_selection".into());
                }
            }
        }
        Operation::AssignStation(x) => {
            known_section(store, &x.section_id)?;
            if checkpoint["selected"].get(&x.section_id).is_some() {
                return Err("section_already_selected".into());
            }
            let candidate = checkpoint["catalog"][&x.section_id]["candidates"]
                .as_array()
                .and_then(|c| {
                    c.iter()
                        .find(|c| c["candidate_id"] == x.candidate_id.as_str())
                })
                .ok_or("unsnapped_or_unknown_candidate")?;
            if !validation::snapped_candidate(candidate) {
                return Err("unsnapped_or_unknown_candidate".into());
            }
        }
        Operation::TraceCorridor(x) => known_section(store, &x.section_id)?,
        Operation::TraceFromPoint(x) => known_section(store, &x.section_id)?,
        Operation::EnumerateStrokes(x) => known_section(store, &x.section_id)?,
        Operation::CompareViews(x) => known_section(store, &x.section_id)?,
        Operation::InspectSource(x) => {
            if let Some(ids) = &x.section_ids {
                let sections = store.state.domain["sections"]
                    .as_array()
                    .ok_or("domain_sections_missing")?;
                if ids
                    .iter()
                    .any(|id| !sections.iter().any(|s| s["id"] == *id))
                {
                    return Err("unknown_section_id".into());
                }
            }
        }
        _ => (),
    }
    Ok(())
}
/// With `--on-ambiguity draft`, a live-model abstention after full inspection
/// becomes a draft, the same as the deterministic policy. An abstention before
/// full inspection, or after a build exists, stays an abstention.
fn live_abstention_becomes_draft(store: &Store, actor: &str) -> bool {
    let d = &store.state.domain;
    actor == "live_model"
        && store.state.config.on_ambiguity == OnAmbiguity::Draft
        && d["catalog_ready"] == true
        && d["current_candidate"].is_null()
        && d["input_errors"].as_array().is_none_or(Vec::is_empty)
}

/// Build a best-effort draft. When it has open guesses, the task stops at
/// `draft_not_verified`; a person resolves each guess with an operator
/// `select_contours`, and then the ordinary verified path runs. An
/// investigating model's own rebuild (`stop_when_built` false) does not stop:
/// the model inspects the draft and revises it, and its submission stops.
fn build_draft(store: &mut Store, stop_when_built: bool) -> Result<bool> {
    if store.state.config.on_ambiguity != OnAmbiguity::Draft {
        return Err("draft_mode_disabled".into());
    }
    if !call_worker(store, "build_draft", json!({}))? {
        return Ok(false);
    }
    let checkpoint = validation::domain_checkpoint(&store.path)?;
    let guesses = validation::open_guesses(&checkpoint)?.to_vec();
    let candidate = store.state.domain["current_candidate"].clone();
    if store.state.last_observation["ok"] != true || guesses.is_empty() {
        // A failed draft build is handled like any failed build; without
        // guesses the build is an ordinary candidate on the verified path.
        return Ok(true);
    }
    if candidate["draft"] != true || candidate["valid"] != true {
        return Err("draft_candidate_contract".into());
    }
    store.append(
        "draft_built",
        json!({"status":"draft_not_verified","guesses":guesses,"candidate":candidate,
            "verified":false,"engineering_approved":false}),
    )?;
    if !stop_when_built {
        return Ok(true);
    }
    stop(
        store,
        Status::DraftNotVerified,
        "draft_built_with_open_guesses",
    )?;
    Ok(false)
}
fn live_visual_coverage(store: &Store, step_hash: &str) -> bool {
    let mut views = std::collections::BTreeSet::new();
    for event in &store.events {
        if !["provider_result", "provider_reconciled"].contains(&event.kind.as_str()) {
            continue;
        }
        let r = &event.payload["receipt"];
        if r["state"] != "completed"
            || r["evidence_mode"] != "live"
            || r["returned_model"] != GO_MODEL
        {
            continue;
        }
        if let Some(images) = r["images"].as_array() {
            for image in images {
                if image["pixels_attached"] == true
                    && image["generation_id"].as_str() == store.state.generation_id.as_deref()
                    && image["revision_id"].as_str() == store.state.revision_id.as_deref()
                    && image["step_sha256"] == step_hash
                {
                    if let Some(v) = image["view"].as_str() {
                        views.insert(v.to_string());
                    }
                }
            }
        }
    }
    views.contains("body") && views.contains("oblique")
}
pub fn execute_decision(store: &mut Store, choice: Decision, actor: &str) -> Result<bool> {
    let operation = choice.operation()?;
    store.verify(false)?;
    validate_selection(store, &operation, actor)?;
    let fingerprint =
        util::hash_json(&json!({"operation":operation,"generation_id":store.state.generation_id}))?;
    let repeats = store
        .state
        .action_fingerprints
        .entry(fingerprint)
        .or_default();
    *repeats += 1;
    if *repeats > store.state.config.limits.max_repeated_action {
        stop(
            store,
            Status::NoProgress,
            "repeated_identical_action_without_generation_progress",
        )?;
        return Ok(false);
    }
    store.append(
        "decision",
        json!({"decision":choice,"actor":actor,"live_inference":actor=="live_model"}),
    )?;
    if let Operation::BuildDraft(_) = operation {
        let investigating = actor == "live_model" && investigation_mode(store);
        return build_draft(store, !investigating);
    }
    if let Operation::AskPerson(ask) = &operation {
        store.state.staged_decision = None;
        store.append(
            "person_requested",
            json!({"actor":actor,"question":ask.question,"engineering_approved":false}),
        )?;
        stop(store, Status::Paused, "model_asked_person")?;
        return Ok(false);
    }
    if let Operation::Finish(finish) = &operation {
        // The investigating model submits its draft: when its latest choices
        // are not built yet, the harness builds the draft first. With open
        // guesses that build stops at draft_not_verified.
        if actor == "live_model"
            && investigation_mode(store)
            && finish.outcome == FinishOutcome::CandidateReadyForReview
            && store.state.domain["current_candidate"].is_null()
            && store.state.domain["catalog_ready"] == true
        {
            store.state.staged_decision = None;
            store.append("submission_builds_draft", json!({"actor":actor}))?;
            return build_draft(store, true);
        }
    }
    if let Operation::Finish(finish) = operation {
        store.state.staged_decision = None;
        if finish.outcome == FinishOutcome::Abstain {
            if live_abstention_becomes_draft(store, actor) {
                store.append(
                    "abstention_replaced_by_draft",
                    json!({"actor":actor,"summary":finish.summary,"policy":"on_ambiguity_draft"}),
                )?;
                return build_draft(store, true);
            }
            stop(store, Status::Abstained, &finish.summary)?;
            return Ok(false);
        }
        // Open guesses make the task a draft: it is never validated or
        // finalized for review. `validation::ready` refuses it independently.
        if !validation::open_guesses(&validation::domain_checkpoint(&store.path)?)?.is_empty() {
            stop(store, Status::DraftNotVerified, "open_guesses_block_review")?;
            return Ok(false);
        }
        if !call_worker(store, "validate_candidate", json!({}))? {
            return Ok(false);
        }
        let _domain_guard = worker::domain_guard(&store.path)?;
        store.verify(false)?;
        if worker::cancelled(&store.path) {
            stop(store, Status::Cancelled, "cancelled_before_finalization")?;
            return Ok(false);
        }
        match validation::ready(
            &store.path,
            &store.state.last_observation,
            &store.state.domain,
            &store.state.last_observation["validation_context"],
            store.state.audit_implementation_sha256.as_deref(),
        ) {
            Ok(contract) => {
                finalization_point(&store.path, "after_predicate");
                if store.state.config.policy == Policy::Live
                    && !live_visual_coverage(store, &contract.binding.step_sha256)
                {
                    store.state.last_observation = json!({"ok":false,"status":"rejected","error_code":"current_step_body_and_oblique_pixels_not_observed_by_model","engineering_approved":false,"human_semantic_review_required":true});
                    store.append("finalization_rejected",json!({"reason":"current_step_body_and_oblique_pixels_not_observed_by_model"}))?;
                    return Ok(true);
                }
                // The vision model can only add a blocking finding here; no veto changes nothing.
                if let Some(veto) = model_review::veto(store, &contract.binding.step_sha256)? {
                    store.state.last_observation = json!({"ok":false,"status":"rejected","error_code":"model_review_veto","model_review":veto,"engineering_approved":false,"human_semantic_review_required":true});
                    stop(store, Status::ValidationFailed, "model_review_veto")?;
                    return Ok(false);
                }
                store.state.status = Status::AwaitingHumanReview;
                store.state.termination_reason = Some(finish.summary);
                finalization_point(&store.path, "before_commit");
                if worker::cancelled(&store.path) {
                    stop(
                        store,
                        Status::Cancelled,
                        "cancelled_before_finalization_commit",
                    )?;
                    return Ok(false);
                }
                store.append("candidate_ready_for_human_review",json!({"validation_binding":contract.binding,"geometry_audit_passed":true,"semantic_review":"required","engineering_approved":false}))?;
                Ok(false)
            }
            Err(reason) => {
                stop(store, Status::ValidationFailed, &reason)?;
                Ok(false)
            }
        }
    } else {
        let done = call_worker(store, operation.name(), operation.args())?;
        if done
            && store.state.last_observation["ok"] == false
            && store.state.last_observation["error_code"] == "domain_integrity_or_input_error"
        {
            stop(store, Status::Blocked, "domain_integrity_or_input_error")?;
            return Ok(false);
        }
        Ok(done)
    }
}

pub fn initialize(store: &mut Store) -> Result<bool> {
    if !call_worker(store, "initialize", json!({}))? {
        return Ok(false);
    }
    if store.state.domain["input_errors"]
        .as_array()
        .is_some_and(|a| !a.is_empty())
    {
        let kind = store.state.domain["input_errors"][0]["kind"]
            .as_str()
            .filter(|s| util::valid_id(s, 128))
            .unwrap_or("invalid_specification")
            .to_string();
        stop(store, Status::Blocked, &format!("input:{kind}"))?;
        return Ok(false);
    }
    Ok(true)
}
pub fn run_loop(store: &mut Store, max_steps: Option<u64>) -> Result<()> {
    let mut steps = 0;
    loop {
        if worker::cancelled(&store.path) {
            return stop(store, Status::Cancelled, "operator_or_signal_cancelled");
        }
        if max_steps.is_some_and(|n| steps >= n) {
            return stop(store, Status::Paused, "requested_step_boundary");
        }
        store.verify(false)?;
        let mut actor = if store.state.config.policy == Policy::Live {
            "live_model"
        } else {
            "deterministic_policy"
        };
        if store.state.staged_decision.is_none() {
            match store.state.config.policy {
                Policy::Deterministic => {
                    store.state.staged_decision = Some(deterministic_decision(store)?);
                    store.state.counters.policy_decisions += 1;
                    store.append(
                        "deterministic_decision_staged",
                        json!({"live_inference":false}),
                    )?;
                }
                Policy::Live => {
                    if let Some(prepared) = investigation_preparation(store)? {
                        store.state.staged_decision = Some(prepared);
                        store.state.counters.policy_decisions += 1;
                        store.append(
                            "harness_preparation_staged",
                            json!({"live_inference":false}),
                        )?;
                        actor = "deterministic_policy";
                    } else {
                        if investigation_mode(store)
                            && decisions_without_progress(store) >= NO_PROGRESS_DECISIONS
                        {
                            return stop(
                                store,
                                Status::NoProgress,
                                "investigation_without_progress",
                            );
                        }
                        if !live_decision(store)? {
                            return Ok(());
                        }
                        if store.state.staged_decision.is_none() {
                            // A refused model output became an observation.
                            steps += 1;
                            continue;
                        }
                    }
                }
            }
        }
        let choice = store
            .state
            .staged_decision
            .clone()
            .ok_or("decision_not_staged")?;
        if worker::cancelled(&store.path) {
            return stop(store, Status::Cancelled, "cancelled_after_model_receipt");
        }
        match execute_decision(store, choice.clone(), actor) {
            Ok(true) => (),
            Ok(false) => return Ok(()),
            Err(reason)
                if actor == "live_model"
                    && investigation_mode(store)
                    && PROPOSAL_REFUSALS.contains(&reason.as_str()) =>
            {
                // A refused model proposal is an observation for the model,
                // not a stop; repeated refusals end in a no-progress stop.
                store.state.staged_decision = None;
                store.state.last_observation = json!({"ok":false,"status":"proposal_refused","error_code":reason,
                    "refused_decision":choice,"what_you_can_do":refusal_hint(&reason),
                    "engineering_approved":false,"human_semantic_review_required":true});
                store.append(
                    "operation_rejected",
                    json!({"reason":reason,"actor":actor,"decision":choice}),
                )?;
                if consecutive_refusals(store) > refusal_limit(store) {
                    return stop(store, Status::NoProgress, "repeated_refused_proposals");
                }
            }
            Err(reason) => {
                store.state.staged_decision = None;
                store.state.last_observation = json!({"ok":false,"status":"rejected","error_code":reason,"engineering_approved":false,"human_semantic_review_required":true});
                store.append("operation_rejected", json!({"reason":reason,"actor":actor}))?;
                // Integrity errors fail closed. A malformed/unknown model choice
                // is not repeatedly retried against the same observations.
                return stop(store, Status::Blocked, &reason);
            }
        }
        steps += 1;
    }
}
pub fn resume(
    store: &mut Store,
    continue_unknown: bool,
    clear_cancel: bool,
    max_steps: Option<u64>,
) -> Result<()> {
    current_binary(store)?;
    store.verify(true)?;
    if clear_cancel && store.path.join("cancel.request").exists() {
        std::fs::remove_file(store.path.join("cancel.request")).map_err(|_| "cancel_clear")?;
        store.append("cancellation_acknowledged", json!({"actor":"operator"}))?;
    }
    if worker::cancelled(&store.path) {
        return stop(
            store,
            Status::Cancelled,
            "cancellation_requires_explicit_clear",
        );
    }
    if let Some(pending) = store.state.pending.clone() {
        if pending.kind == "worker" {
            if !store.path.join(&pending.response_path).is_file() {
                return stop(
                    store,
                    Status::Interrupted,
                    "unreceipted_worker_state_not_adopted",
                );
            }
            if !apply_worker(
                store,
                &pending,
                json!({"state":"recovered_after_controller_interruption"}),
                true,
            )? {
                return Ok(());
            }
        } else {
            let receipt = apply_provider(
                store,
                &pending,
                json!({"state":"recovered_after_controller_interruption"}),
                true,
            )?;
            if receipt
                .as_ref()
                .is_none_or(|r| r.state == RequestState::TransmissionOrCompletionUnknown)
                && !continue_unknown
            {
                return Ok(());
            }
        }
    }
    if store.state.termination_reason.as_deref()
        == Some("provider_transmission_or_completion_unknown")
    {
        if !continue_unknown {
            return Err("explicit_unknown_outcome_acknowledgement_required".into());
        }
        store.append("unknown_provider_outcome_acknowledged",json!({"actor":"operator","repeat_previous_request":false,"unknown_cost_retained":true}))?;
    }
    if matches!(
        store.state.status,
        Status::AwaitingHumanReview
            | Status::Abstained
            | Status::DraftNotVerified
            | Status::ValidationFailed
            | Status::Blocked
            | Status::NoProgress
    ) {
        return Err("terminal_task_requires_explicit_source_backed_intervention".into());
    }
    store.state.status = Status::Running;
    store.state.termination_reason = None;
    store.append("task_resumed", json!({"actor":"operator"}))?;
    if store.state.domain_checkpoint_sha256.is_none() && !initialize(store)? {
        return Ok(());
    }
    run_loop(store, max_steps)
}

#[derive(serde::Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Intervention {
    pub schema_version: String,
    pub task_id: String,
    pub expected_head_sha256: String,
    pub expected_generation_id: String,
    pub expected_revision_id: String,
    pub decision: Decision,
}
pub fn intervene(store: &mut Store, input: Intervention, actor: &str, note: &str) -> Result<()> {
    current_binary(store)?;
    store.verify(false)?;
    if !["human_operator", "assistant_operator"].contains(&actor) || note.chars().count() > 512 {
        return Err("intervention_actor_or_note".into());
    }
    if input.schema_version != "marinaframe.intervention.v1"
        || input.task_id != store.state.task_id
        || Some(&input.expected_head_sha256) != store.head.as_ref()
        || Some(&input.expected_generation_id) != store.state.generation_id.as_ref()
        || Some(&input.expected_revision_id) != store.state.revision_id.as_ref()
    {
        return Err("stale_or_foreign_intervention".into());
    }
    if store.state.pending.is_some() || worker::cancelled(&store.path) {
        return Err("intervention_requires_reconciled_uncancelled_state".into());
    }
    input.decision.operation()?;
    store.state.counters.operator_actions += 1;
    store.state.staged_decision = None;
    store.state.status = Status::Running;
    store.state.termination_reason = None;
    store.append("operator_intervention",json!({"actor":actor,"note":note,"decision":input.decision,"previous_head":input.expected_head_sha256,"semantic_identity_certified":false,"engineering_approved":false}))?;
    if execute_decision(store, input.decision, actor)? {
        stop(store, Status::Paused, "operator_action_completed")?;
    }
    Ok(())
}

pub fn summary(store: &Store) -> Value {
    json!({"schema_version":CONTROL_VERSION,"controller":"rust","task_id":store.state.task_id,"status":store.state.status,
    "termination_reason":store.state.termination_reason,"generation_id":store.state.generation_id,"revision_id":store.state.revision_id,
    "current_candidate":store.state.domain.get("current_candidate"),"counters":store.state.counters,"head_sha256":store.head,
    "engineering_approved":false,"semantic_review":"required","pending":store.state.pending,"policy":store.state.config.policy})
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn inspect_next_names_the_next_uninspected_sections() {
        // 59 sections inspected 5 per call (Gunnerus) need 12 calls; each call
        // names other sections, so it is not one action repeated 12 times.
        let mut sections = (0..59)
            .map(|i| json!({"id":format!("s{i}"),"inspected":false}))
            .collect::<Vec<_>>();
        let first = inspect_next(&sections);
        assert_eq!(first.arguments["section_ids"][0], "s0");
        assert_eq!(first.arguments["section_ids"].as_array().unwrap().len(), 12);
        for section in sections.iter_mut().take(5) {
            section["inspected"] = json!(true);
        }
        let second = inspect_next(&sections);
        assert_eq!(second.arguments["section_ids"][0], "s5");
        assert_ne!(first.arguments, second.arguments);
        for section in sections.iter_mut() {
            section["inspected"] = json!(true);
        }
        assert_eq!(inspect_next(&sections).arguments, json!({}));
    }
    fn fixture() -> (tempfile::TempDir, Store) {
        let tmp = tempfile::tempdir().unwrap();
        let config = Config {
            worker_python: "/not/executed".into(),
            worker_source: None,
            source_spec: "/not/executed.json".into(),
            policy: Policy::Live,
            limits: OperationalLimits::default(),
            provider_transfer_authorized: true,
            authorization_basis: "protocol fixture".into(),
            model: GO_MODEL.into(),
            binary_sha256: "a".repeat(64),
            on_ambiguity: OnAmbiguity::Abstain,
        };
        let store = Store::create(&tmp.path().join("task"), new_state(config)).unwrap();
        (tmp, store)
    }
    #[test]
    fn model_cannot_erase_a_retained_competing_stroke() {
        let (_tmp, store) = fixture();
        let operation = Operation::SelectContours(Select {
            selections: vec![Selection {
                section_id: "frame 1".into(),
                candidate_id: "contour-test".into(),
            }],
        });
        util::atomic_json(&store.path.join("domain/state.json"),&json!({"catalog":{"frame 1":{"candidates":[{"candidate_id":"contour-test","selectable":true,"non_grid_competing_components":1}]}}}),false).unwrap();
        assert_eq!(
            validate_selection(&store, &operation, "live_model").unwrap_err(),
            "source_ambiguity_requires_explicit_operator_selection"
        );
        assert!(validate_selection(&store, &operation, "deterministic_policy").is_err());
        assert!(validate_selection(&store, &operation, "assistant_operator").is_ok());
        assert!(validate_selection(&store, &operation, "human_operator").is_ok());
    }
    #[test]
    fn only_an_operator_can_resolve_an_open_guess() {
        let (_tmp, store) = fixture();
        let operation = Operation::SelectContours(Select {
            selections: vec![Selection {
                section_id: "s0".into(),
                candidate_id: "contour-test".into(),
            }],
        });
        util::atomic_json(
            &store.path.join("domain/state.json"),
            &json!({"catalog":{"s0":{"candidates":[{"candidate_id":"contour-test","selectable":true,"non_grid_competing_components":0}]}},
                "guesses":[{"section_id":"s0","chosen_candidate_id":"contour-test"}]}),
            false,
        )
        .unwrap();
        for policy in ["live_model", "deterministic_policy"] {
            assert_eq!(
                validate_selection(&store, &operation, policy).unwrap_err(),
                "guess_requires_operator_confirmation"
            );
        }
        for operator in ["human_operator", "assistant_operator"] {
            assert!(validate_selection(&store, &operation, operator).is_ok());
        }
    }
    #[test]
    fn draft_tool_is_offered_only_in_draft_mode() {
        let names = |catalog: Value| {
            catalog
                .as_array()
                .unwrap()
                .iter()
                .map(|t| t["name"].as_str().unwrap().to_string())
                .collect::<Vec<_>>()
        };
        assert!(!names(tool_catalog(&OnAmbiguity::Abstain)).contains(&"build_draft".into()));
        assert!(names(tool_catalog(&OnAmbiguity::Draft)).contains(&"build_draft".into()));
    }
    #[test]
    fn abstain_mode_refuses_a_draft_build() {
        let (_tmp, mut store) = fixture();
        assert_eq!(
            build_draft(&mut store, true).unwrap_err(),
            "draft_mode_disabled"
        );
    }
    #[test]
    fn source_witnesses_survive_later_build_observations() {
        let (_tmp, mut store) = fixture();
        let source = json!({"section_id":"s0","source_sha256":"x","candidates":[{"candidate_id":"a","endpoint_evidence":{"centroid_alternative_id":"b","source_supported":true}}]});
        store
            .append(
                "worker_result",
                json!({"response":{"result":{"sections":[source.clone()]}}}),
            )
            .unwrap();
        store.state.last_observation = json!({"ok":true,"status":"review_required"});
        let observation = model_observation(&store).unwrap();
        assert_eq!(observation["retained_source_observations"][0], source);
        assert!(observation.get("reference_geometry").is_none());
    }

    // ------------------------------------------- investigation receipts

    /// A live draft-mode task with one pending investigation request, its
    /// honest response body on disk and the honest receipt for it.
    fn investigation_receipt_fixture() -> (tempfile::TempDir, Store, Pending, Receipt, Vec<u8>) {
        let (tmp, mut store) = fixture();
        store.state.config.on_ambiguity = OnAmbiguity::Draft;
        store.state.source_manifest_sha256 = Some("a".repeat(64));
        store.state.generation_id = Some(format!("generation-{}", "b".repeat(24)));
        store.state.revision_id = Some("r0001".into());
        let pending = Pending {
            kind: "provider".into(),
            id: "request-investigation".into(),
            operation: "model_decision".into(),
            response_path: "receipts/request-investigation.json".into(),
            request_path: "requests/request-investigation.json".into(),
            domain_before: None,
            started_ms: util::now_ms(),
        };
        let input = ProviderInput {
            protocol: provider::PROTOCOL.into(),
            request_id: pending.id.clone(),
            source_manifest_sha256: "a".repeat(64),
            generation_id: store.state.generation_id.clone().unwrap(),
            revision_id: "r0001".into(),
            observation_sha256: "c".repeat(64),
            images: vec![],
            payload: json!({"model":GO_MODEL,"messages":[{"role":"system","content":provider::INVESTIGATION_PROMPT}]}),
            attempt: 1,
            retry_of: None,
            purpose: provider::Purpose::Investigation,
        };
        util::atomic_json(&store.path.join(&pending.request_path), &input, false).unwrap();
        let decision = json!({"tool":"view_region","arguments":{"region_px":[0,0,400,300]},"reason":"Look at the body plan."});
        let body = util::json_bytes(&json!({"id":"completion-1","model":GO_MODEL,
            "choices":[{"finish_reason":"stop","message":{"content":decision.to_string()}}],
            "usage":{"prompt_tokens":30,"completion_tokens":5,"total_tokens":35,"cost":0.0,"opencode":{"billing_source":"go"}}}))
        .unwrap();
        let mut receipt = Receipt {
            protocol: provider::PROTOCOL.into(),
            request_id: pending.id.clone(),
            state: RequestState::NotSent,
            endpoint: GO_ENDPOINT.into(),
            requested_model: GO_MODEL.into(),
            returned_model: None,
            completion_id: None,
            provider_request_id: None,
            http_status: Some(200),
            response_sha256: Some(util::hash(&body)),
            request_sha256: util::hash_json(&input.payload).unwrap(),
            prompt_sha256: util::hash(provider::INVESTIGATION_PROMPT.as_bytes()),
            source_manifest_sha256: input.source_manifest_sha256.clone(),
            generation_id: input.generation_id.clone(),
            revision_id: input.revision_id.clone(),
            observation_sha256: input.observation_sha256.clone(),
            images: vec![],
            usage: json!({}),
            observed_cost_usd: None,
            latency_seconds: 0.5,
            decision: None,
            error_code: None,
            attempt: 1,
            retry_of: None,
            retry_after_seconds: None,
            aggregate_request_cap: None,
            aggregate_token_cap: None,
            aggregate_spend_cap: None,
            evidence_mode: "live".into(),
            credential_selection: None,
            purpose: provider::Purpose::Investigation,
            transcription: None,
        };
        provider::interpret_completion(&mut receipt, &body, "").unwrap();
        store.state.pending = Some(pending.clone());
        (tmp, store, pending, receipt, body)
    }
    fn apply_forged(
        store: &mut Store,
        pending: &Pending,
        receipt: &Receipt,
        body: Option<&[u8]>,
    ) -> Result<Option<Receipt>> {
        util::atomic_json(&store.path.join(&pending.response_path), receipt, true).unwrap();
        let body_file = store.path.join(provider::body_path(&pending.response_path));
        match body {
            Some(bytes) => std::fs::write(&body_file, bytes).unwrap(),
            None => {
                let _ = std::fs::remove_file(&body_file);
            }
        }
        apply_provider(store, pending, json!({"state":"exited"}), false)
    }
    #[test]
    fn honest_investigation_receipt_stages_its_decision() {
        let (_tmp, mut store, pending, receipt, body) = investigation_receipt_fixture();
        let applied = apply_forged(&mut store, &pending, &receipt, Some(&body)).unwrap();
        assert_eq!(applied.unwrap().state, RequestState::Completed);
        assert_eq!(store.state.staged_decision.unwrap().tool, "view_region");
        assert_eq!(store.state.counters.prompt_tokens, 30);
    }
    /// Edits a receipt or its body; returns false to remove the body file.
    type ReceiptForgery = fn(&mut Receipt, &mut Vec<u8>) -> bool;
    #[test]
    fn edited_or_unbacked_investigation_receipts_are_refused() {
        let cases: [(&str, ReceiptForgery); 6] = [
            ("decision edited in the receipt", |r, _| {
                r.decision.as_mut().unwrap().tool = "finish".into();
                r.decision.as_mut().unwrap().arguments =
                    json!({"outcome":"candidate_ready_for_review","summary":"Approved."});
                true
            }),
            ("arguments edited in the receipt", |r, _| {
                r.decision.as_mut().unwrap().arguments = json!({"region_px":[0,0,10,10]});
                true
            }),
            ("usage edited in the receipt", |r, _| {
                r.usage = json!({"prompt_tokens":3,"completion_tokens":5,"total_tokens":8,"cost":0.0,"billing_source":"go"});
                true
            }),
            ("body edited on disk", |_, b| {
                let text = String::from_utf8(b.clone()).unwrap().replace("400", "900");
                *b = text.into_bytes();
                true
            }),
            ("body missing", |_, _| false),
            ("completion id edited", |r, _| {
                r.completion_id = Some("completion-2".into());
                true
            }),
        ];
        for (name, forge) in cases {
            let (_tmp, mut store, pending, mut receipt, mut body) = investigation_receipt_fixture();
            let keep_body = forge(&mut receipt, &mut body);
            let error = apply_forged(
                &mut store,
                &pending,
                &receipt,
                keep_body.then_some(&body[..]),
            )
            .unwrap_err();
            assert!(
                [
                    "provider_receipt_body_mismatch",
                    "provider_receipt_body_missing"
                ]
                .contains(&error.as_str()),
                "{name}: {error}"
            );
            assert!(store.state.staged_decision.is_none(), "{name}");
        }
    }
    #[test]
    fn a_decision_receipt_of_another_mode_is_refused() {
        // A receipt made with the ordinary decision prompt cannot stage a
        // decision in an investigation task, and the reverse.
        let (_tmp, mut store, pending, mut receipt, body) = investigation_receipt_fixture();
        receipt.purpose = provider::Purpose::ModelDecision;
        receipt.prompt_sha256 = util::hash(provider::SYSTEM_PROMPT.as_bytes());
        assert_eq!(
            apply_forged(&mut store, &pending, &receipt, Some(&body)).unwrap_err(),
            "provider_receipt_identity"
        );
    }
    #[test]
    fn investigation_receipts_bind_images_and_observation_on_recovery() {
        let forgeries: [fn(&mut Receipt); 6] = [
            |r| r.images[0].sha256 = "d".repeat(64),
            |r| r.images[0].crop_box_px = Some([0, 0, 40, 30]),
            |r| r.images[0].pixel_size = Some([40, 30]),
            |r| r.observation_sha256 = "d".repeat(64),
            |r| r.generation_id = "generation-forged".into(),
            |r| r.revision_id = "r0002".into(),
        ];
        for reconciled in [false, true] {
            for forge in forgeries {
                let (_tmp, mut store, pending, mut receipt, body) = investigation_receipt_fixture();
                let image = ImageReceipt {
                    artifact_id: "view-1".into(),
                    path: "domain/views/view.png".into(),
                    sha256: "e".repeat(64),
                    bytes: 100,
                    mime_type: "image/png".into(),
                    evidence_kind: "region_view".into(),
                    view: None,
                    generation_id: None,
                    revision_id: None,
                    step_sha256: None,
                    pixels_attached: true,
                    crop_box_px: Some([0, 0, 400, 300]),
                    pixel_size: Some([400, 300]),
                };
                let path = store.path.join(&pending.request_path);
                let mut input: ProviderInput =
                    serde_json::from_value(util::read_json(&path, 2 * 1024 * 1024).unwrap())
                        .unwrap();
                input.images = vec![image.clone()];
                util::atomic_json(&path, &input, true).unwrap();
                receipt.images = vec![image];
                forge(&mut receipt);
                util::atomic_json(&store.path.join(&pending.response_path), &receipt, false)
                    .unwrap();
                std::fs::write(
                    store.path.join(provider::body_path(&pending.response_path)),
                    body,
                )
                .unwrap();
                assert!(apply_provider(
                    &mut store,
                    &pending,
                    json!({"state":"exited"}),
                    reconciled
                )
                .is_err());
                assert!(store.state.staged_decision.is_none());
                assert_eq!(store.state.counters.requests_completed, 0);
            }
        }
    }
    #[test]
    fn investigation_tools_require_draft_mode_and_are_bounded() {
        let (_tmp, store) = fixture();
        let view = Operation::ViewRegion(ViewRegion {
            region_px: [0, 0, 10, 10],
            max_side_px: None,
        });
        assert_eq!(
            validate_selection(&store, &view, "live_model").unwrap_err(),
            "investigation_requires_draft_mode"
        );
        let names = |catalog: Value| {
            catalog
                .as_array()
                .unwrap()
                .iter()
                .map(|t| t["name"].as_str().unwrap().to_string())
                .collect::<Vec<_>>()
        };
        let draft = names(tool_catalog(&OnAmbiguity::Draft));
        for tool in [
            "view_region",
            "trace_corridor",
            "assign_station",
            "ask_person",
        ] {
            assert!(draft.contains(&tool.to_string()));
            assert!(!names(tool_catalog(&OnAmbiguity::Abstain)).contains(&tool.to_string()));
        }
    }
    #[test]
    fn a_model_can_assign_only_snapped_ink() {
        let (_tmp, mut store) = fixture();
        store.state.config.on_ambiguity = OnAmbiguity::Draft;
        store.state.domain = json!({"sections":[{"id":"s0"}]});
        let snapped = json!({"candidate_id":"c","selectable":true,"source_support":{"observed_row_fraction":0.97},
            "contour_selection":{"anchors_px":[[1.0,0.0],[2.0,9.0]],"half_width_px":2.75}});
        let assign = Operation::AssignStation(AssignStation {
            section_id: "s0".into(),
            candidate_id: "c".into(),
            label_view_id: "view-1".into(),
            label_text: "0".into(),
            reason: "Label 0.".into(),
            comparison_id: None,
        });
        let write = |candidate: &Value| {
            util::atomic_json(
                &store.path.join("domain/state.json"),
                &json!({"selected":{},"catalog":{"s0":{"candidates":[candidate]}}}),
                true,
            )
            .unwrap()
        };
        write(&snapped);
        assert!(validate_selection(&store, &assign, "live_model").is_ok());
        let mut unsnapped: Vec<Value> = vec![];
        for (key, value) in [
            ("selectable", json!(false)),
            ("source_support", json!({"observed_row_fraction":0.6})),
            ("contour_selection", Value::Null),
            ("model_traced", json!(true)),
        ] {
            let mut candidate = snapped.clone();
            candidate[key] = value;
            unsnapped.push(candidate);
        }
        for candidate in unsnapped {
            write(&candidate);
            assert_eq!(
                validate_selection(&store, &assign, "live_model").unwrap_err(),
                "unsnapped_or_unknown_candidate",
                "{candidate}"
            );
        }
    }
    #[test]
    fn enumeration_tags_survive_a_later_label_view() {
        let (_tmp, mut store) = fixture();
        store.state.config.on_ambiguity = OnAmbiguity::Draft;
        store
            .append(
                "worker_result",
                json!({"operation":"enumerate_strokes","response":{"result":{
            "ok":true,"status":"strokes_enumerated","panel_section_ids":["s0","s1"],
            "strokes":[{"tag":1,"candidate_id":"trace-1"}],"view":{"view_id":"view-1"}}}}),
            )
            .unwrap();
        store.state.last_observation = json!({"ok":true,"status":"viewed"});
        let observed = investigation_observation(&store).unwrap();
        assert_eq!(
            observed["retained_stroke_panels"][0]["strokes"][0]["candidate_id"],
            "trace-1"
        );
    }
    #[test]
    fn old_panel_memory_cannot_exhaust_the_observation_budget() {
        let (_tmp, mut store) = fixture();
        store.state.config.on_ambiguity = OnAmbiguity::Draft;
        for i in 0..30 {
            store
                .append(
                    "worker_result",
                    json!({"response":{"result":{
                "status":"strokes_enumerated","panel_section_ids":[format!("s{i}")],
                "strokes":[{"tag":1,"candidate_id":format!("trace-{i}"),"detail":"x".repeat(4000)}],
                "view":{"view_id":format!("view-{i}")}}}}),
                )
                .unwrap();
        }
        store.state.last_observation = json!({"ok":true,"status":"viewed"});
        let observed = investigation_observation(&store).unwrap();
        assert!(
            util::json_bytes(&observed).unwrap().len()
                <= store.state.config.limits.max_observation_bytes
        );
        assert_eq!(
            observed["retained_stroke_panels"][0]["view"]["view_id"],
            "view-29"
        );
        assert!(!observed["omitted_stroke_panel_ids"]
            .as_array()
            .unwrap()
            .is_empty());
    }
    #[test]
    fn large_enumeration_preserves_tags_and_view_mapping() {
        let (_tmp, mut store) = fixture();
        store.state.config.on_ambiguity = OnAmbiguity::Draft;
        store.state.last_observation = json!({"ok":true,"status":"strokes_enumerated",
            "section_id":"s0", "strokes":[{"tag":1,"candidate_id":"trace-1"}],
            "view":{"view_id":"view-1","crop_box_px":[0,0,400,300],"view_px_per_source_px":[1,1]},
            "artifacts":[{"id":"image-1","padding":"x".repeat(100_000)}]});
        let observed = investigation_observation(&store).unwrap();
        assert_eq!(
            observed["last_observation"]["strokes"][0]["candidate_id"],
            "trace-1"
        );
        assert_eq!(observed["last_observation"]["view"]["view_id"], "view-1");
    }
    #[test]
    fn refusals_are_counted_until_an_accepted_action() {
        let (_tmp, mut store) = fixture();
        for _ in 0..3 {
            store.append("provider_intent", json!({})).unwrap();
            store
                .append("operation_rejected", json!({"reason":"x"}))
                .unwrap();
        }
        assert_eq!(consecutive_refusals(&store), 3);
        store.append("worker_result", json!({})).unwrap();
        assert_eq!(consecutive_refusals(&store), 0);
        assert_eq!(refusal_limit(&store), 6);
    }
}
