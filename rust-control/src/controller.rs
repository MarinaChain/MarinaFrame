use crate::provider::{self, ImageReceipt, ProviderInput, Receipt, RequestState};
use crate::store::{self, Store};
use crate::types::*;
use crate::util::{self, Result};
use crate::{models, validation, worker};
use base64::{engine::general_purpose::STANDARD, Engine};
use serde_json::{json, Value};
use std::collections::BTreeMap;
use std::path::PathBuf;
use std::time::{Duration, Instant};

#[path = "model_review.rs"]
pub mod model_review;
#[path = "revision.rs"]
pub mod revision;
#[path = "transcript.rs"]
pub mod transcript;

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
        active_model: None,
    }
}
fn stop(store: &mut Store, status: Status, reason: &str) -> Result<()> {
    let has_draft = status != Status::Paused
        && store.state.config.on_ambiguity == OnAmbiguity::Draft
        && ["current_candidate", "last_valid_candidate"]
            .iter()
            .any(|key| {
                let candidate = &store.state.domain[*key];
                candidate["draft"] == true && candidate["valid"] == true
            });
    store.state.status = if has_draft {
        Status::DraftNotVerified
    } else {
        status
    };
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
        let recalled = store.state.last_observation["recalled_view_id"].as_str();
        values.sort_by_key(|(seq, artifact, _, _, _)| {
            (
                recalled.is_none_or(|id| artifact["view_id"] != id),
                std::cmp::Reverse(*seq),
            )
        });
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
        tools
            .as_array_mut()
            .unwrap()
            .push(crate::types::authoring::tool());
    }
    tools
}
fn phase_tool_catalog(store: &Store) -> Value {
    let mut tools = tool_catalog(&store.state.config.on_ambiguity);
    if revision::active(store) {
        // A focused revision pass asks for section edits only.
        tools
            .as_array_mut()
            .unwrap()
            .retain(|tool| tool["name"] == "propose_section");
        return tools;
    }
    let next = match store.state.domain["description_phase"].as_str() {
        Some("views") => Some("describe_views"),
        Some("setups") => Some("propose_sheet_setup"),
        Some("vessel") => Some("describe_vessel"),
        _ => None,
    };
    if investigation_mode(store) {
        if let Some(name) = next {
            tools.as_array_mut().unwrap().retain(|tool| {
                tool["name"] == name || (name == "describe_vessel" && tool["name"] == "read_region")
            });
        }
    }
    tools
}

/// Investigation tools of the live model (draft mode only). Each one is
/// executed by the harness; every claim is checked by deterministic code.
fn investigation_catalog() -> Vec<Value> {
    let region = json!({"type":"array","items":{"type":"integer","minimum":0},"minItems":4,"maxItems":4,"description":"[left, top, right, bottom] in sheet pixels"});
    let id = json!({"type":"string","maxLength":64});
    vec![
        json!({"name":"survey_sheet","description":"Survey the sheet without CAD. The harness normally runs this before view identification.","parameters":{"type":"object","properties":{},"additionalProperties":false}}),
        json!({"name":"describe_views","description":"Name view families and sheet-pixel bounds. All same-scale body panels are ONE family: use one body view with optional panels [{region_px,centreline_px,baseline_px}], family_id and shared setup {pixels_per_metre,grid_spacing_m}. The first body setup is reused across the family. Include plan/profile and useful title or offset tables.","parameters":{"type":"object","properties":{"views":{"type":"array","minItems":1,"maxItems":32,"items":{"type":"object","properties":{"view_id":{"type":"string","maxLength":64},"kind":{"enum":["body","body_fore","body_aft","plan","profile","title_block","offsets_table","other"]},"region_px":region,"halves":{"type":"string","maxLength":2000},"mirror":{"type":"boolean"},"grid_roles":{"type":"object"},"family_id":{"type":"string"},"panels":{"type":"array","items":{"type":"object"}},"setup":{"type":"object"}},"required":["view_id","kind","region_px"],"additionalProperties":true}}},"required":["views"],"additionalProperties":false}}),
        json!({"name":"describe_vessel","description":"Record the vessel before CAD: principal dimensions with value/source/view_id, stations (id/x_m), waterlines (id/z_m), buttocks (id/y_m), ends, deck and form. Keep measured and inferred values labelled. Doubtful dimensions receive warnings, not approval.","parameters":{"type":"object","properties":{"description":{"type":"object","properties":{"units":{"type":"string"},"dimension_text":{"type":"string","description":"Exact labelled dimension text read from the title/dimension crop: LOA, LWL, BEAM, DEPTH, DRAFT (DWL), units. Do not invent unreadable numbers."},"frame":{},"principal":{"type":"object"},"stations":{"type":"array","maxItems":300,"items":{"type":"object"}},"waterlines":{"type":"array","maxItems":300,"items":{"type":"object"}},"buttocks":{"type":"array","maxItems":300,"items":{"type":"object"}},"ends":{"type":"object"},"deck":{"type":"object"},"form":{"type":"object"}},"additionalProperties":true}},"required":["description"],"additionalProperties":false}}),
        json!({"name":"recall_view","description":"Reattach a previous task view by view_id without creating a new crop.","parameters":{"type":"object","properties":{"view_id":id},"required":["view_id"],"additionalProperties":false}}),
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
fn description_pending(store: &Store) -> bool {
    investigation_mode(store)
        && store.state.domain["description_phase"]
            .as_str()
            .is_some_and(|phase| phase != "complete")
}

/// Added to the description instructions when the spec is a sheet-only intake:
/// the harness declares the sections from this reading before the first hull.
const SHEET_ONLY_INSTRUCTIONS: &str = "This sheet came from intake with NO declared stations or calibration. The survey's intake_regions are code-measured view regions in ORIGINAL sheet pixels (label body_plan, profile, half_breadth, title_block); use their region_px boxes, corrected only where you see an error, never 0-1000 coordinates. Your reading declares the sections: the harness builds one section per station you list, on the body view and setup you give. In describe_views give the body plan its own kind (body, or body_fore/body_aft halves) and, for separate station panels, panels in reading order; give each non-body view its own family_id. In propose_sheet_setup for the body read pixels_per_metre from labelled grid lines (pixel distance between two labelled lines divided by their metre difference), and give centreline_px and baseline_px. In describe_vessel list EVERY station drawn in the body plan in order as {id, x_m, side}: x_m in metres from the aft end forward, read from the profile/plan station marks and LOA; when positions are not printed, space stations evenly over LOA and say so in a note; the hull ends (x 0 and LOA) are stations only when the body plan draws a curve for them, because the harness makes the ends from the profile outline; side 'fore' or 'aft' only for halves of an overlaid body plan. The two halves of one overlaid body plan share one centreline: describe them as one body view (or body_aft and body_fore), never as two panels. Give loa, beam and depth when readable. Missing values become labelled guesses, never a stop.";

/// Said while a sheet-only task reads the sheet again (best of N readings,
/// `first_hull_tools.READINGS`).
const SECOND_READING_NOTE: &str = "Repeat reading: the best first hull so far is built and kept as the draft. Read the sheet again as an independent check with the listed tool (describe_views, then propose_sheet_setup, then describe_vessel); the reading whose first hull fits the drawing best is kept. Section edits (propose_section), build_draft and finish are offered again after the last reading's describe_vessel.";

fn description_instructions(phase: &Value) -> &'static str {
    match phase.as_str() {
        Some("survey") => "The harness surveys the sheet first; do not build CAD.",
        Some("views") => "Read the attached whole sheet and survey. Call describe_views with named view bounds in ORIGINAL sheet pixels from the survey sheet size, not normalized 0-1000 coordinates or resized attachment pixels. Convert visual positions using the sheet width/height. Same-scale body panels are ONE view family: name one body bounding box and optional panels with per-panel region_px/centreline_px/baseline_px. You may include shared setup pixels_per_metre/grid_spacing_m from declared calibration; otherwise one setup call serves every body panel. Include the title_block for legible dimensions. For a 2590-pixel wide sheet, the rightmost quarter is near x=1940..2590, NOT x=750..1000. The whole-sheet ruler is normalized; multiply x by sheet_width/1000 and y by sheet_height/1000. Copy title text into dimension_text only after reading a legible crop. Do not trace sections or build CAD yet.",
        Some("setups") => "Call propose_sheet_setup once for description_next_view. Use its actual crop view_id as evidence_view_id and its sheet region_px. Map body_fore/body_aft to body. Read scale, grid spacing and datums; label inferences. The result attaches the next view crop. Do not build CAD yet.",
        Some("vessel") => "Before describe_vessel, inspect the title crop. If it shows geometry or is unreadable, call read_region with subject=title_block and corrected ORIGINAL sheet-pixel region_px; do not guess text from the thumbnail. On a three-view sheet the title is normally below the body plan at right. Transcribe exact labelled lines into dimension_text, e.g. LOA ... m LWL ... m BEAM ... m DEPTH ... m DRAFT (DWL) ... m. Read digits carefully: LOA is not LWL; DRAFT is not a grid interval. Prefer printed values with source=title_block over pixel extents. Then call describe_vessel. Use the survey declared specification, measured sheet_setups and source pixels for principal dimensions, station identities/positions, waterlines, buttocks, ends, deck and form. Keep principal dimensions supplied by declared specification bounds as source=spec (including depth from declared z_max); retain measured discrepancies as warnings, not replacements. Measure beam and other undeclared dimensions from hull ink and the measured grid, not grid extents. A body-only drawing does not supply loa/lpp/draft: use {value:null,source:ai_inferred,note:not on sheet}, not invented numbers. In three-view drawings read LOA/BEAM/DEPTH/DRAFT directly from the attached title_block; keep title_block values rather than mistaking LWL for LOA. Use declared station IDs/x_m unless a clear measured correction exists. Label each dimension source (spec, title_block, measured, ai_inferred); do not confuse grid extents with hull extents. Keep doubtful fields explicit; warnings are advisory. Do not build CAD yet.",
        _ => "The vessel description is complete. The harness builds the first hull unless this is a Phase 1-only run.",
    }
}

/// Surveys can contain tile and stroke inventories. Send only a bounded sample
/// beside declared specification data; the full survey stays in the checkpoint.
fn compact_survey(value: &Value, depth: usize) -> Value {
    if depth >= 10 {
        return Value::Null;
    }
    match value {
        Value::Array(items) => Value::Array(
            items
                .iter()
                .take(300)
                .map(|v| compact_survey(v, depth + 1))
                .collect(),
        ),
        Value::Object(items) => Value::Object(
            items
                .iter()
                .filter(|(key, _)| !["artifacts", "ink_components"].contains(&key.as_str()))
                .take(32)
                .map(|(key, value)| {
                    let limit = match key.as_str() {
                        "strokes" => 6,
                        "tiles" => 32,
                        "grid_families" | "positions_px" => 128,
                        _ => 300,
                    };
                    let bounded = if let Some(items) = value.as_array() {
                        Value::Array(items.iter().take(limit).cloned().collect())
                    } else {
                        value.clone()
                    };
                    (key.clone(), compact_survey(&bounded, depth + 1))
                })
                .collect(),
        ),
        Value::String(text) => Value::String(text.chars().take(512).collect()),
        _ => value.clone(),
    }
}

/// Observation fields that change rarely within a task (on a new reading or
/// phase). They go first in the request, so that a cached prefix covers them.
const STABLE_OBSERVATION_KEYS: [&str; 9] = [
    "task_id",
    "current_policy",
    "engineering_approved",
    "source_truth",
    "notes_warning",
    "sheet_only_instructions",
    "sheet_survey",
    "described_views",
    "vessel_description",
];
/// Split an observation into its stable fields and the rest.
fn split_stable_context(observation: &Value) -> (Value, Value) {
    let mut current = observation.clone();
    let mut stable = serde_json::Map::new();
    if let Some(object) = current.as_object_mut() {
        for key in STABLE_OBSERVATION_KEYS {
            if let Some(value) = object.remove(key) {
                stable.insert(key.into(), value);
            }
        }
    }
    (Value::Object(stable), current)
}

/// The largest arguments (JSON bytes) that one history entry repeats. Larger
/// arguments (describe_views, describe_vessel) are already in the observation
/// as described_views and vessel_description.
const HISTORY_ARGUMENTS_BYTES: usize = 800;
fn bounded_history_arguments(arguments: &Value) -> Value {
    match util::json_bytes(arguments) {
        Ok(bytes) if bytes.len() <= HISTORY_ARGUMENTS_BYTES => arguments.clone(),
        Ok(bytes) => json!(format!(
            "(omitted: {} bytes; the result is in the current observation)",
            bytes.len()
        )),
        Err(_) => Value::Null,
    }
}

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
                    "catalog_available":s["catalog_available"],"inspection_failure":s["inspection_failure"],
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
                "arguments":bounded_history_arguments(&e.payload["decision"]["arguments"]),
                "reason":e.payload["decision"].get("reason").unwrap_or(&e.payload["reason"])})
        })
        .collect::<Vec<_>>();
    let notes = store
        .events
        .iter()
        .rev()
        .filter(|event| event.kind == "decision" && event.payload["actor"] == "live_model")
        .filter_map(|event| {
            event.payload["decision"]["notes"]
                .as_str()
                .map(|claim| json!({"claim":claim,"verified":false,"source":"model_claim"}))
        })
        .take(8)
        .collect::<Vec<_>>();
    let mut value = json!({"task_id":store.state.task_id,
        "your_notes_newest_first":notes,
        "notes_warning":"Unverified model claims, not measurements or certified station identities.",
        "sections":sections,"catalog_ready":d["catalog_ready"],"selected_count":d["selected_count"],
        "open_guess_count":guesses.len(),"model_choice_section_ids":d["model_choice_section_ids"],
        "sheet_setup_ids":d["sheet_setup_ids"],"rendered_views":d["rendered_views"],
        "current_draft":if candidate.is_null(){Value::Null}else{json!({"valid":candidate["valid"],"draft":candidate["draft"],"status":candidate["status"]})},
        "last_observation":store.state.last_observation,"recent_history_newest_first":history,
        "retained_stroke_panels":panels,"omitted_stroke_panel_ids":[],
        "current_policy":"live_investigation","engineering_approved":false,
        "source_truth":"source evidence and deployment-available checks only; no evaluator references"});
    if d["description_phase"].is_string() {
        value["description_phase"] = d["description_phase"].clone();
        value["description_instructions"] =
            json!(description_instructions(&d["description_phase"]));
        if d["sheet_only"] == true && description_pending(store) {
            value["sheet_only_instructions"] = json!(SHEET_ONLY_INSTRUCTIONS);
            if d["last_valid_candidate"].is_object() {
                // Sonnet 5.5 live (round 7ac5e2b): during the second reading it
                // tried finish or propose_section, which this phase does not list.
                value["reading_note"] = json!(SECOND_READING_NOTE);
            }
        }
        value["description_next_view"] = d["description_next_view"].clone();
        value["described_views"] = d["described_views"].clone();
        value["sheet_setups"] = json!(d["sheet_setups"].as_array().map(|setups| setups
            .iter()
            .take(32)
            .map(|setup| {
                let mut summary = serde_json::Map::new();
                for key in [
                    "view_id",
                    "view",
                    "region_px",
                    "pixels_per_metre",
                    "centreline_px",
                    "baseline_px",
                    "x_origin_px",
                    "x_direction",
                    "grid_spacing_m",
                    "datum_snaps",
                    "warnings",
                ] {
                    if let Some(value) = setup.get(key) {
                        summary.insert(key.into(), compact_survey(value, 0));
                    }
                }
                Value::Object(summary)
            })
            .collect::<Vec<_>>()));
        value["vessel_description"] = d["vessel_description"].clone();
        value["phase1_only"] =
            json!(store.state.config.limits.phase1_only || d["phase1_only"] == true);
        // The survey serves the reading of the views. Once the vessel is
        // described, the description and setups carry what was read from it
        // (about 11 kB of every later request in the Sonnet round 217660c).
        if description_pending(store) {
            value["sheet_survey"] = compact_survey(&d["sheet_survey"], 0);
        }
        if let Some(last) = value["last_observation"].as_object_mut() {
            for key in ["sheet_survey", "survey"] {
                if let Some(survey) = last.get_mut(key) {
                    *survey = compact_survey(survey, 0);
                }
            }
        }
    }
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
        || !provider::model_bound(&receipt, &input)
        || !store.state.config.models().contains(&receipt.requested_model.as_str())
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
                if !value.as_str().is_some_and(|s| {
                    ["go", "go-plus", "free", "balance", "byok", "subscription"].contains(&s)
                }) {
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
            if !provider::returned_requested_model(&receipt) || receipt.decision.is_none() {
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
    // Two text parts: first what stays the same from request to request (tools,
    // survey, vessel description), then what changes. A transport that caches
    // a prompt prefix can reuse the first part (claude_cli::build marks it).
    let (stable, current) = split_stable_context(&observation);
    let stable = json!({"tools":phase_tool_catalog(store),"stable_context":stable});
    let prompt = json!({"observation":observation,"tools":stable["tools"],"images":metas});
    let changing = json!({"observation":current,"images":metas});
    let text = |value: &Value| -> Result<Value> {
        let text = String::from_utf8(util::json_bytes(value)?).map_err(|_| "prompt_encoding")?;
        Ok(json!({"type":"text","text":text}))
    };
    let mut content = vec![text(&stable)?, text(&changing)?];
    for (_, pixels) in images {
        content.push(json!({"type":"image_url","image_url":{"url":format!("data:image/png;base64,{pixels}"),"detail":"original"}}));
    }
    let purpose = decision_purpose(store);
    let thinking = investigation_mode(store) && store.state.config.limits.investigation_thinking;
    let temperature = if investigation_mode(store) {
        store.state.config.limits.investigation_temperature
    } else {
        0.0
    };
    let mut messages = vec![
        json!({"role":"system","content":purpose.prompt()}),
        json!({"role":"user","content":content.clone()}),
    ];
    let mut context = Value::Null;
    if investigation_mode(store) && store.state.config.limits.investigation_conversation {
        let mut current = prompt["observation"].clone();
        if let Some(object) = current.as_object_mut() {
            object.remove("recent_history_newest_first");
            object.remove("your_notes_newest_first");
        }
        let transcript = transcript::build(
            &store.events,
            &store.state,
            purpose.prompt(),
            current,
            phase_tool_catalog(store),
            content,
        )?;
        context = json!({"format":1,"steps_total":transcript.steps_total,"steps_kept":transcript.steps_kept,"estimated_tokens":transcript.estimated_tokens});
        if let Some(summary) = transcript.summary {
            let previous = store
                .events
                .iter()
                .rev()
                .find(|e| e.kind == "context_compacted");
            if previous.is_none_or(|e| e.payload["summary"] != summary) {
                store.append(
                    "context_compacted",
                    json!({"summary":summary,"context":context}),
                )?;
            }
        }
        messages = transcript.messages;
    }
    let messages = json!(messages);
    let mut retry_of = None;
    let mut attempt = 0;
    while attempt < 3 {
        attempt += 1;
        // Built per attempt: a rate-limit switch changes the model.
        let payload = models::payload(
            store.state.current_model(),
            store.state.config.limits.max_output_tokens_per_request,
            thinking,
            temperature,
            messages.clone(),
        )?;
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
            observation_sha256: if context.is_null() {
                util::hash_json(&prompt)?
            } else {
                let mut text_messages = payload["messages"].clone();
                if let Some(content) = text_messages
                    .as_array_mut()
                    .and_then(|messages| messages.last_mut())
                    .and_then(|last| last["content"].as_array_mut())
                {
                    content.retain(|part| part["type"] != "image_url");
                }
                util::hash_json(&json!({"messages":text_messages,"images":metas}))?
            },
            images: metas.clone(),
            payload: payload.clone(),
            attempt,
            retry_of: retry_of.clone(),
            purpose,
        };
        util::atomic_json(&store.path.join(&pending.request_path), &input, false)?;
        store.state.pending = Some(pending.clone());
        store.state.counters.requests_intended += 1;
        store.append("provider_intent",json!({"request_id":id,"request":store::artifact(&store.path,&pending.request_path,"provider_request")?,"source_manifest_sha256":input.source_manifest_sha256,"images":metas,"attempt":attempt,"retry_of":retry_of,"aggregate_caps":null,"context":context}))?;
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
            let refused = refused_call_feedback(store, &pending, &receipt);
            store.state.last_observation = json!({"ok":false,"status":"rejected",
                "error_code":receipt.error_code,"message":"Your reply was not one valid tool call within the argument bounds. Reply with one JSON object: tool, arguments, reason.",
                "refused_call":refused,
                "hint":if receipt.error_code.as_deref() == Some(provider::claude_cli::INVALID_STRUCTURED_OUTPUT) {
                    "Your answer was not valid JSON: its brackets did not match. Send the same call again with balanced braces; keep long arguments shallow and short."
                } else {
                    "Correct the call with the contract error and schema in refused_call, or choose a listed tool."
                },
                "engineering_approved":false,"human_semantic_review_required":true});
            // The history shows the refused tool and its contract error, not only the code.
            let decision = refused
                .as_ref()
                .map(|r| json!({"tool":r["tool"],"contract_error":r["contract_error"]}));
            store.append(
                "model_output_rejected",
                json!({"request_id":id,"reason":receipt.error_code,"decision":decision}),
            )?;
            if consecutive_refusals(store) > refusal_limit(store) {
                stop(store, Status::NoProgress, "repeated_refused_model_output")?;
                return Ok(false);
            }
            return Ok(true);
        }
        if models::rate_limited(&receipt) && switch_model(store, &receipt)? {
            // A new model starts a new request chain.
            attempt = 0;
            retry_of = None;
            continue;
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

/// What the model is told about its refused tool call: the call, the contract
/// error, the tools offered now and, for a tool that the current phase does not
/// list, that tool's argument schema, so that a valid intent passes next time.
/// None when the reply held no readable tool call.
fn refused_call_feedback(store: &Store, pending: &Pending, receipt: &Receipt) -> Option<Value> {
    let body = std::fs::read(store.path.join(provider::body_path(&pending.response_path))).ok()?;
    let mut refused = provider::refused_call(receipt, &body)?;
    // The arguments were the model's own; only a bounded copy returns.
    if util::json_bytes(&refused["arguments"]).map_or(true, |b| b.len() > REFUSED_ARGUMENTS_BYTES) {
        refused["arguments"] = json!("(omitted: too long)");
    }
    let offered = phase_tool_catalog(store);
    let names: Vec<Value> = offered
        .as_array()
        .map(|tools| tools.iter().map(|t| t["name"].clone()).collect())
        .unwrap_or_default();
    let tool = refused["tool"].clone();
    refused["tools_offered_now"] = json!(names);
    if !names.contains(&tool) {
        let catalog = tool_catalog(&store.state.config.on_ambiguity);
        if let Some(schema) = catalog
            .as_array()
            .and_then(|tools| tools.iter().find(|t| t["name"] == tool))
        {
            refused["schema_of_this_tool"] = schema["parameters"].clone();
            refused["phase_note"] = json!("This tool is not listed in the current phase. Finish the listed step first, or send the call again with these exact argument names.");
        }
    }
    Some(refused)
}
/// The largest refused-arguments copy (JSON bytes) that goes back to the model.
const REFUSED_ARGUMENTS_BYTES: usize = 4096;

/// A completed HTTP exchange whose content was not one valid tool call (bad
/// JSON, unknown tool, arguments out of bounds). Transport, identity and
/// credential failures are not model output and still stop the task.
fn model_output_refused(receipt: &Receipt) -> bool {
    receipt.state == RequestState::Failed
        && receipt.http_status == Some(200)
        && provider::returned_requested_model(receipt)
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
/// After a rate-limit or usage-exhausted answer, move the run to the next
/// model of its list and record the switch. False when no model is left.
fn switch_model(store: &mut Store, receipt: &Receipt) -> Result<bool> {
    let models = store.state.config.models();
    let Some(next) = models::next(&models, &receipt.requested_model) else {
        return Ok(false);
    };
    let next = next.to_string();
    store.state.active_model = Some(next.clone());
    store.append(
        "model_switched",
        json!({"from":receipt.requested_model,"to":next,"request_id":receipt.request_id,
            "returned_model":receipt.returned_model,"http_status":receipt.http_status,
            "reason":receipt.error_code.as_deref().unwrap_or("provider_rate_limited")}),
    )?;
    Ok(true)
}
/// Refused proposals and refused outputs since the model's last accepted action.
fn consecutive_refusals(store: &Store) -> u64 {
    let mut count = 0;
    for event in store.events.iter().rev() {
        match event.kind.as_str() {
            "operation_rejected" | "model_output_rejected" => count += 1,
            // Provider bookkeeping between refusals is not an accepted action.
            "provider_intent"
            | "provider_result"
            | "provider_reconciled"
            | "provider_backoff"
            | "context_compacted" => {}
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
    if !investigation_mode(store)
        || description_pending(store)
        || store.state.last_observation["ok"] == false
    {
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
        notes: None,
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
        .filter(|s| s["inspected"] != true && s["catalog_available"] != true)
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
        Operation::ProposeSection(x) => known_section(store, &x.section_id)?,
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

fn ask_to_fill_missing_once(store: &mut Store) -> Result<bool> {
    if store
        .events
        .iter()
        .any(|e| e.kind == "missing_sections_hint")
    {
        return Ok(false);
    }
    let checkpoint = validation::domain_checkpoint(&store.path)?;
    let missing = store.state.domain["sections"]
        .as_array()
        .map(|sections| {
            sections
                .iter()
                .filter(|s| {
                    let id = s["id"].as_str().unwrap_or("");
                    !checkpoint["selected"][id].is_string()
                        && !checkpoint["model_choices"][id]["candidate_id"].is_string()
                        && !checkpoint["authored_sections"][id]["candidate_id"].is_string()
                        && checkpoint["catalog"][id]["candidates"]
                            .as_array()
                            .is_none_or(|c| {
                                !c.iter()
                                    .any(|c| c["selectable"] == true && c["model_traced"] != true)
                            })
                })
                .map(|s| s["id"].clone())
                .collect::<Vec<_>>()
        })
        .unwrap_or_default();
    if missing.is_empty() {
        return Ok(false);
    }
    store.state.staged_decision = None;
    store.state.last_observation = json!({"ok":true,"status":"fill_missing_sections",
        "missing_section_ids":missing,"message":"Before building, use propose_section to fill these missing sections. This is a one-time suggestion; build_draft again to keep the current gaps.",
        "engineering_approved":false,"human_semantic_review_required":true});
    store.append("missing_sections_hint", json!({"section_ids":missing}))?;
    Ok(true)
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
            || !r["returned_model"]
                .as_str()
                .is_some_and(|m| store.state.config.models().contains(&m))
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
/// Evidence changes, unlike new crops, permit a previously used action again.
fn investigation_progress_key(store: &Store) -> Result<String> {
    let domain = &store.state.domain;
    util::hash_json(&json!({"generation":store.state.generation_id,
        "revision":store.state.revision_id,"sections":domain["sections"],
        "catalog":domain["inspected_sections"],"guesses":domain["open_guesses"],
        "setups":domain["sheet_setup_ids"],"candidate":domain["current_candidate"],
        "description_phase":domain["description_phase"],"described_views":domain["described_views"],
        "description_next_view":domain["description_next_view"],"vessel_description":domain["vessel_description"]}))
}

fn refuse_repeated_investigation(store: &mut Store, choice: &Decision) -> Result<bool> {
    let progress = if choice.tool == "build_draft" {
        util::hash_json(&json!({"generation":store.state.generation_id}))?
    } else {
        investigation_progress_key(store)?
    };
    let earlier = store.events.iter().rev().find(|event| {
        event.kind == "decision"
            && event.payload["actor"] == "live_model"
            && event.payload["progress_key"] == progress
            && event.payload["decision"]["tool"] == choice.tool
            && event.payload["decision"]["arguments"] == choice.arguments
            && !(choice.tool == "build_draft"
                && store.events.iter().any(|hint| {
                    hint.kind == "missing_sections_hint" && hint.sequence == event.sequence + 1
                }))
    });
    let Some(earlier) = earlier else {
        return Ok(false);
    };
    let earlier_id = earlier.sequence;
    let result = store
        .events
        .iter()
        .find(|event| {
            event.sequence > earlier_id
                && ["worker_result", "worker_reconciled"].contains(&event.kind.as_str())
        })
        .map(|event| {
            json!({"event_id":event.sequence,"status":event.payload["response"]["result"]["status"],
            "view":event.payload["response"]["result"]["view"]})
        });
    let key = format!(
        "repeat_refusal:{}",
        util::hash_json(
            &json!({"progress":progress,"tool":choice.tool,"arguments":choice.arguments})
        )?
    );
    let count = store.state.action_fingerprints.entry(key).or_default();
    *count += 1;
    let count = *count;
    let limit = store.state.config.limits.max_repeated_action;
    store.state.staged_decision = None;
    let message = if count >= limit {
        format!("You repeated this action {count} times with unchanged evidence. It will not run again. Pick a different tool now (build_draft if you have not built yet).")
    } else {
        "This action was already executed with unchanged evidence. Use its earlier result and your notes; choose a different next action.".to_string()
    };
    store.state.last_observation = json!({"ok":false,"status":"repeated_action_refused",
        "error_code":"repeated_action_refused","earlier_decision_event_id":earlier_id,"earlier_result":result,
        "message":message,
        "useful_next_actions":["assign_station for unassigned sections", "build_draft", "render_candidate after building", "trace_from_point on different ink"],
        "engineering_approved":false,"human_semantic_review_required":true});
    store.append(
        "repeated_action_refused",
        json!({"decision":choice,"progress_key":progress,"earlier_decision_event_id":earlier_id}),
    )?;
    // After the strong hint above the model gets `limit` more chances to
    // change course before the run stops. `stop` keeps a valid draft.
    if count >= 2 * limit {
        stop(
            store,
            Status::NoProgress,
            "repeated_identical_action_refusals",
        )?;
    }
    Ok(true)
}

pub fn execute_decision(store: &mut Store, choice: Decision, actor: &str) -> Result<bool> {
    let operation = choice.operation()?;
    store.verify(false)?;
    validate_selection(store, &operation, actor)?;
    let investigating = actor == "live_model" && investigation_mode(store);
    if investigating && refuse_repeated_investigation(store, &choice)? {
        return Ok(store.state.status == Status::Running);
    }
    let progress_key = if investigating && choice.tool == "build_draft" {
        Some(util::hash_json(
            &json!({"generation":store.state.generation_id}),
        )?)
    } else {
        investigating
            .then(|| investigation_progress_key(store))
            .transpose()?
    };
    let fingerprint =
        util::hash_json(&json!({"operation":operation,"generation_id":store.state.generation_id}))?;
    let repeats = store
        .state
        .action_fingerprints
        .entry(fingerprint)
        .or_default();
    *repeats += 1;
    if !investigating && *repeats > store.state.config.limits.max_repeated_action {
        stop(
            store,
            Status::NoProgress,
            "repeated_identical_action_without_generation_progress",
        )?;
        return Ok(false);
    }
    store.append(
        "decision",
        json!({"decision":choice,"actor":actor,"live_inference":actor=="live_model","progress_key":progress_key}),
    )?;
    if let Operation::RecallView(recall) = &operation {
        let known = store
            .events
            .iter()
            .any(|event| event.payload["response"]["result"]["view"]["view_id"] == recall.view_id);
        store.state.staged_decision = None;
        store.state.last_observation = if known {
            json!({"ok":true,"status":"view_recalled","recalled_view_id":recall.view_id,"engineering_approved":false,"human_semantic_review_required":true})
        } else {
            json!({"ok":false,"status":"proposal_refused","error_code":"unknown_view","message":"Recall a view_id returned by this task.","engineering_approved":false,"human_semantic_review_required":true})
        };
        store.append(
            "view_recalled",
            json!({"view_id":recall.view_id,"known":known}),
        )?;
        return Ok(true);
    }
    if let Operation::BuildDraft(_) = operation {
        if actor == "live_model" && ask_to_fill_missing_once(store)? {
            return Ok(true);
        }
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
        if store.state.config.on_ambiguity == OnAmbiguity::Draft
            && finish.outcome == FinishOutcome::CandidateReadyForReview
            && store.state.domain["current_candidate"]["valid"] != true
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
            if store.state.domain["current_candidate"]["valid"] == true
                || store.state.domain["last_valid_candidate"]["valid"] == true
            {
                stop(store, Status::DraftNotVerified, "open_guesses_block_review")?;
                return Ok(false);
            }
            // A failed build's existing feedback remains actionable; do not
            // claim a delivered draft when no STEP has been made.
            return Ok(true);
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
                    let status = if store.state.config.on_ambiguity == OnAmbiguity::Draft {
                        store.state.last_observation["status"] = json!("draft_warning");
                        store.state.last_observation["message"] = json!(
                            "Model review findings remain warnings on this unverified draft."
                        );
                        Status::DraftNotVerified
                    } else {
                        Status::ValidationFailed
                    };
                    stop(store, status, "model_review_veto")?;
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
                let draft_available = store.state.config.on_ambiguity == OnAmbiguity::Draft
                    && store.state.domain["current_candidate"]["valid"] == true;
                if draft_available {
                    store.state.last_observation["warning"] = json!(reason);
                    stop(store, Status::DraftNotVerified, &reason)?;
                } else {
                    stop(store, Status::ValidationFailed, &reason)?;
                }
                Ok(false)
            }
        }
    } else {
        let mut arguments = if matches!(operation, Operation::SurveySheet(_)) {
            json!({"phase1_only":store.state.config.limits.phase1_only})
        } else {
            operation.args()
        };
        if matches!(operation, Operation::ProposeSection(_)) && revision::active(store) {
            // A person asked to revise this section: the worker's keep rule
            // first requires its own ink error not to get worse.
            arguments["revision_target"] = json!(true);
        }
        let done = call_worker(store, operation.name(), arguments)?;
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
    // A sheet-only intake spec has no sections yet. Only the live draft model
    // reads stations and scale (phase 1); every other policy keeps the strict rule.
    if sheet_only(store) && !investigation_mode(store) {
        stop(store, Status::Blocked, "input:sheet_only_needs_live_draft")?;
        return Ok(false);
    }
    Ok(true)
}
/// The task's spec is a sheet-only intake (no declared sections before phase 1).
fn sheet_only(store: &Store) -> bool {
    store.state.domain["sheet_only"] == true
}
/// Advance automatic description/CAD work before asking the model. An absent
/// phase key keeps old workers and stored tasks on their legacy first-hull path.
fn prepare_investigation_phase(store: &mut Store) -> Result<bool> {
    if !investigation_mode(store) {
        return Ok(true);
    }
    if store.state.domain["description_phase"] == "survey" {
        if !call_worker(
            store,
            "survey_sheet",
            json!({"phase1_only":store.state.config.limits.phase1_only}),
        )? {
            return Ok(false);
        }
        if store.state.domain["description_phase"] == "survey" {
            stop(store, Status::Blocked, "sheet_survey_did_not_advance")?;
            return Ok(false);
        }
    }
    if description_pending(store) {
        return Ok(true);
    }
    if store.state.config.limits.phase1_only || store.state.domain["phase1_only"] == true {
        let complete = store.state.domain["description_phase"] == "complete"
            && store.state.domain["vessel_description"].is_object();
        stop(
            store,
            if complete {
                Status::Paused
            } else {
                Status::Blocked
            },
            if complete {
                "phase1_description_complete"
            } else {
                "phase1_description_unavailable"
            },
        )?;
        return Ok(false);
    }
    if store.state.domain["description_phase"].is_string()
        && !store.state.domain["vessel_description"].is_object()
    {
        stop(store, Status::Blocked, "vessel_description_missing")?;
        return Ok(false);
    }
    if !store
        .events
        .iter()
        .any(|event| event.kind == "first_hull_ready")
    {
        if !call_worker(store, "build_first_hull", json!({}))? {
            return Ok(false);
        }
        store.append("first_hull_ready", json!({"engineering_approved":false}))?;
        if store.state.domain["current_candidate"]["valid"] == true
            && !call_worker(store, "render_candidate", json!({"view":"body"}))?
        {
            return Ok(false);
        }
    }
    Ok(true)
}

pub fn run_loop(store: &mut Store, max_steps: Option<u64>) -> Result<()> {
    let mut steps = 0;
    loop {
        if worker::cancelled(&store.path) {
            return stop(store, Status::Cancelled, "operator_or_signal_cancelled");
        }
        // Complete Phase 1 and its pause even when its last model call used
        // the requested step budget; never build CAD in a Phase 1-only run.
        if !prepare_investigation_phase(store)? {
            return Ok(());
        }
        if max_steps.is_some_and(|n| steps >= n) {
            return stop(store, Status::Paused, "requested_step_boundary");
        }
        store.verify(false)?;
        if investigation_mode(store) && store.state.domain["last_valid_candidate"]["valid"] == true
        {
            let edits = store.state.domain["non_improving_edits"]
                .as_u64()
                .unwrap_or(0);
            if edits >= 6 {
                if store.events.iter().any(|e| e.kind == "soft_finish_hint") {
                    return stop(
                        store,
                        Status::DraftNotVerified,
                        "best_draft_after_non_improving_edits",
                    );
                }
                store.state.last_observation["finish_hint"] = json!("Several edits did not improve the drawing fit. Finish now; the best valid draft is preserved.");
                store.append("soft_finish_hint", json!({"non_improving_edits":edits}))?;
            }
        }
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
                        match live_decision(store) {
                            Ok(true) => (),
                            Ok(false) => return Ok(()),
                            Err(reason)
                                if ["task_storage_limit", "configured_deployment_budget"]
                                    .contains(&reason.as_str()) =>
                            {
                                return stop(store, Status::Blocked, &reason);
                            }
                            Err(reason) => return Err(reason),
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
            Ok(true) => {
                store.state.last_observation["normalization_note"] = json!("Oversized notes are truncated to 600 characters; numeric investigation arguments are clamped to tool bounds.");
            }
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
                if [
                    "unsnapped_or_unknown_candidate",
                    "unknown_or_unsupported_candidate",
                ]
                .contains(&reason.as_str())
                {
                    let checkpoint = validation::domain_checkpoint(&store.path)?;
                    let sid = choice.arguments["section_id"].as_str().unwrap_or("");
                    store.state.last_observation["current_candidate_catalog"] = json!({"section_id":sid,
                        "candidates":checkpoint["catalog"][sid]["candidates"].as_array().map(|candidates| candidates.iter().map(|c| json!({"candidate_id":c["candidate_id"],"hypothesis":c["hypothesis"],"selectable":c["selectable"]})).collect::<Vec<_>>()),
                        "hint":"Use one of these current IDs, or propose_section to author the section."});
                }
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
    "current_candidate":store.state.domain.get("current_candidate"),
    "last_valid_candidate":store.state.domain.get("last_valid_candidate"),
    "counters":store.state.counters,"head_sha256":store.head,
    "engineering_approved":false,"semantic_review":"required","pending":store.state.pending,"policy":store.state.config.policy,
    "models":store.state.config.models(),"current_model":store.state.current_model()})
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn stop_keeps_available_draft_for_every_terminal_reason() {
        for status in [
            Status::NoProgress,
            Status::Blocked,
            Status::Interrupted,
            Status::Cancelled,
            Status::ProviderFailed,
        ] {
            let (_tmp, mut store) = fixture();
            store.state.config.on_ambiguity = OnAmbiguity::Draft;
            store.state.domain["last_valid_candidate"] =
                json!({"draft":true,"valid":true,"path":"domain/builds/draft"});
            stop(&mut store, status, "test_stop").unwrap();
            assert_eq!(store.state.status, Status::DraftNotVerified);
            assert_eq!(store.state.termination_reason.as_deref(), Some("test_stop"));
        }
    }
    #[test]
    fn unchanged_draft_build_is_refused_even_after_build_revision_changes() {
        let (_tmp, mut store) = fixture();
        let choice = decision("build_draft", json!({}), "build");
        let key = util::hash_json(&json!({"generation":store.state.generation_id})).unwrap();
        store
            .append(
                "decision",
                json!({"decision":choice,"actor":"live_model","progress_key":key}),
            )
            .unwrap();
        store.state.revision_id = Some("r0009".into());
        store.state.domain["current_candidate"] = json!({"valid":false});
        assert!(refuse_repeated_investigation(&mut store, &choice).unwrap());
        assert_eq!(
            store.state.last_observation["status"],
            "repeated_action_refused"
        );
    }
    #[test]
    fn recall_view_contract_accepts_ids_and_refuses_paths() {
        let (_tmp, mut store) = fixture();
        store.state.config.on_ambiguity = OnAmbiguity::Draft;
        store.state.config.binary_sha256 =
            util::file_hash(&std::env::current_exe().unwrap()).unwrap();
        store
            .append(
                "worker_result",
                json!({"response":{"result":{"view":{"view_id":"view-existing"}}}}),
            )
            .unwrap();
        // The typed operation bounds IDs before any execution.
        let valid = decision("recall_view", json!({"view_id":"view-existing"}), "recall");
        assert_eq!(valid.operation().unwrap().name(), "recall_view");
        assert!(
            decision("recall_view", json!({"view_id":"../path"}), "recall")
                .operation()
                .is_err()
        );
    }
    #[test]
    fn missing_sections_prompt_is_once_only_and_allows_next_build() {
        let (_tmp, mut store) = fixture();
        store.state.domain["sections"] = json!([{"id":"s01"}]);
        util::atomic_json(
            &store.path.join("domain/state.json"),
            &json!({"catalog":{"s01":{"candidates":[]}},"selected":{}}),
            false,
        )
        .unwrap();
        let choice = decision("build_draft", json!({}), "build");
        let progress = util::hash_json(&json!({"generation":store.state.generation_id})).unwrap();
        store
            .append(
                "decision",
                json!({"decision":choice,"actor":"live_model","progress_key":progress}),
            )
            .unwrap();
        assert!(ask_to_fill_missing_once(&mut store).unwrap());
        assert_eq!(
            store.state.last_observation["missing_section_ids"],
            json!(["s01"])
        );
        assert!(!ask_to_fill_missing_once(&mut store).unwrap());
        assert!(!refuse_repeated_investigation(&mut store, &choice).unwrap());
    }
    #[test]
    fn recorded_decision_reason_is_visible_in_investigation() {
        let (_tmp, mut store) = fixture();
        store.append("decision", json!({"decision":{"tool":"read_region","arguments":{},"reason":"Tag 4 labels station 2"},"actor":"live_model"})).unwrap();
        let observed = investigation_observation(&store).unwrap();
        assert_eq!(
            observed["recent_history_newest_first"][0]["reason"],
            "Tag 4 labels station 2"
        );
    }
    #[test]
    fn investigation_keeps_last_eight_notes_as_unverified_claims() {
        let (_tmp, mut store) = fixture();
        for n in 0..10 {
            store.append("decision", json!({"decision":{"tool":"read_region","arguments":{},"reason":"read","notes":format!("label {n}")},"actor":"live_model"})).unwrap();
        }
        let observed = investigation_observation(&store).unwrap();
        let notes = observed["your_notes_newest_first"].as_array().unwrap();
        assert_eq!(notes.len(), 8);
        assert_eq!(notes[0]["claim"], "label 9");
        assert_eq!(notes[7]["claim"], "label 2");
        assert_eq!(notes[0]["verified"], false);
    }
    #[test]
    fn repeated_investigation_refuses_then_stops_but_progress_allows_retry() {
        let (_tmp, mut store) = fixture();
        let choice = decision(
            "read_region",
            json!({"region_px":[0,0,100,100],"subject":"labels"}),
            "read",
        );
        let key = investigation_progress_key(&store).unwrap();
        store
            .append(
                "decision",
                json!({"decision":choice,"actor":"live_model","progress_key":key}),
            )
            .unwrap();
        store.append("worker_result", json!({"response":{"result":{"status":"viewed","view":{"view_id":"view-earlier"}}}})).unwrap();
        store.state.domain["view_count"] = json!(2);
        // max_repeated_action is 3: a strong hint from the 3rd refusal, a stop at the 6th.
        for n in 1..=6 {
            assert!(refuse_repeated_investigation(&mut store, &choice).unwrap());
            assert_eq!(
                store.state.last_observation["status"],
                "repeated_action_refused"
            );
            assert_eq!(
                store.state.last_observation["earlier_result"]["view"]["view_id"],
                "view-earlier"
            );
            let strong_hint = store.state.last_observation["message"]
                .as_str()
                .unwrap()
                .contains("Pick a different tool now");
            assert_eq!(strong_hint, n >= 3);
            assert_eq!(store.state.status == Status::NoProgress, n == 6);
        }
        store.state.generation_id = Some("new-generation".into());
        assert!(!refuse_repeated_investigation(&mut store, &choice).unwrap());
    }
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
            fallback_models: vec![],
        };
        let store = Store::create(&tmp.path().join("task"), new_state(config)).unwrap();
        (tmp, store)
    }
    #[test]
    fn description_operations_are_bounded_and_draft_only() {
        let view = json!({"view_id":"fore-body","kind":"body_fore","region_px":[10,20,300,400]});
        for (name, arguments) in [
            ("survey_sheet", json!({})),
            ("describe_views", json!({"views":[view.clone()]})),
            (
                "describe_vessel",
                json!({"description":{"principal":{"beam":{"value":12.0,"source":"measured"}},"stations":[{"id":"s0","x_m":0.0}]}}),
            ),
        ] {
            let operation = decision(name, arguments.clone(), "contract test")
                .operation()
                .unwrap();
            assert_eq!(operation.name(), name);
            assert_eq!(operation.args(), arguments);
            assert!(operation.is_investigation());
            for policy in [OnAmbiguity::Abstain, OnAmbiguity::Draft] {
                assert_eq!(
                    tool_catalog(&policy)
                        .as_array()
                        .unwrap()
                        .iter()
                        .any(|tool| tool["name"] == name),
                    policy == OnAmbiguity::Draft
                );
            }
        }
        for (name, arguments) in [
            ("survey_sheet", json!({"phase1_only":true})),
            ("describe_views", json!({"views":[]})),
            (
                "describe_views",
                json!({"views":[view.clone(),view.clone()]}),
            ),
            (
                "describe_views",
                json!({"views":[{"view_id":"body","kind":"body","region_px":[20,0,10,100]}]}),
            ),
            (
                "describe_vessel",
                json!({"description":{"stations":vec![json!({});301]}}),
            ),
            (
                "describe_vessel",
                json!({"description":{"notes":"x".repeat(2001)}}),
            ),
        ] {
            assert!(
                decision(name, arguments, "bounds test")
                    .operation()
                    .is_err(),
                "{name}"
            );
        }
    }

    #[test]
    fn read_phase_catalog_does_not_distract_with_section_tools() {
        let (_tmp, mut store) = fixture();
        store.state.config.policy = Policy::Live;
        store.state.config.on_ambiguity = OnAmbiguity::Draft;
        store.state.domain = json!({"description_phase":"setups"});
        let catalog = phase_tool_catalog(&store);
        let names = catalog
            .as_array()
            .unwrap()
            .iter()
            .map(|t| t["name"].as_str().unwrap())
            .collect::<Vec<_>>();
        assert_eq!(names, vec!["propose_sheet_setup"]);
        store.state.domain["description_phase"] = json!("vessel");
        let catalog = phase_tool_catalog(&store);
        assert!(catalog
            .as_array()
            .unwrap()
            .iter()
            .any(|tool| tool["name"] == "describe_vessel"));
        assert!(catalog
            .as_array()
            .unwrap()
            .iter()
            .any(|tool| tool["name"] == "read_region"));
        assert_eq!(catalog.as_array().unwrap().len(), 2);
    }

    #[test]
    fn description_phases_route_tools_before_cad_and_pause_without_worker() {
        let (_tmp, mut store) = fixture();
        store.state.config.on_ambiguity = OnAmbiguity::Draft;
        store.state.config.limits.phase1_only = true;
        store.state.domain =
            json!({"description_phase":"views","sections":[],"current_candidate":null});
        store.state.last_observation = json!({"ok":true});
        for (phase, tool, arguments) in [
            (
                "views",
                "describe_views",
                json!({"views":[{"view_id":"body","kind":"body","region_px":[0,0,100,100]}]}),
            ),
            (
                "setups",
                "propose_sheet_setup",
                json!({"view":"body","region_px":[0,0,100,100],"pixels_per_metre":10,"grid_spacing_m":1,"evidence_view_id":"crop-body","scale_claim":"grid","reason":"read grid"}),
            ),
            (
                "vessel",
                "describe_vessel",
                json!({"description":{"stations":[]}}),
            ),
        ] {
            store.state.domain["description_phase"] = json!(phase);
            let operation = decision(tool, arguments, "route").operation().unwrap();
            assert!(
                description_instructions(&store.state.domain["description_phase"])
                    .contains(operation.name())
            );
            assert!(investigation_preparation(&store).unwrap().is_none());
            assert!(prepare_investigation_phase(&mut store).unwrap());
            assert!(!store
                .events
                .iter()
                .any(|event| event.kind == "first_hull_ready"));
        }
        store.state.domain["description_phase"] = json!("complete");
        store.state.domain["vessel_description"] = json!({"principal":{}});
        run_loop(&mut store, Some(0)).unwrap();
        assert_eq!(store.state.status, Status::Paused);
        assert_eq!(
            store.state.termination_reason.as_deref(),
            Some("phase1_description_complete")
        );
        assert!(!store
            .events
            .iter()
            .any(|event| event.kind == "worker_started" || event.kind == "first_hull_ready"));
        store.state.domain = json!({});
        assert!(!description_pending(&store));
    }

    #[test]
    fn sheet_only_intake_tells_the_model_to_declare_stations() {
        let (_tmp, mut store) = fixture();
        store.state.config.on_ambiguity = OnAmbiguity::Draft;
        store.state.domain =
            json!({"description_phase":"vessel","sheet_only":true,"described_views":[]});
        let observation = investigation_observation(&store).unwrap();
        assert_eq!(
            observation["sheet_only_instructions"],
            SHEET_ONLY_INSTRUCTIONS
        );
        store.state.domain["sheet_only"] = json!(false);
        let observation = investigation_observation(&store).unwrap();
        assert!(observation.get("sheet_only_instructions").is_none());
        assert!(!sheet_only(&store));
    }

    #[test]
    fn description_observation_keeps_specification_not_large_survey_inventory() {
        let (_tmp, mut store) = fixture();
        store.state.config.on_ambiguity = OnAmbiguity::Draft;
        let survey = json!({"declared":{"units":"m","stations":[{"id":"s0","x_m":0.0}]},"tiles":vec![json!({"pixels":"x".repeat(4000)});100]});
        store.state.domain = json!({"description_phase":"views","sheet_survey":survey,"described_views":[],"vessel_description":null});
        store.state.last_observation = json!({"ok":true,"sheet_survey":survey});
        let observation = investigation_observation(&store).unwrap();
        assert_eq!(observation["sheet_survey"]["declared"]["units"], "m");
        assert_eq!(
            observation["sheet_survey"]["declared"]["stations"][0]["id"],
            "s0"
        );
        assert_eq!(
            observation["sheet_survey"]["tiles"]
                .as_array()
                .unwrap()
                .len(),
            32
        );
        assert_eq!(
            observation["last_observation"]["sheet_survey"]["tiles"]
                .as_array()
                .unwrap()
                .len(),
            32
        );
        assert!(observation["description_instructions"]
            .as_str()
            .unwrap()
            .contains("describe_views"));
        assert!(
            util::json_bytes(&observation).unwrap().len()
                < store.state.config.limits.max_observation_bytes
        );
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
        investigation_receipt_fixture_for(GO_MODEL)
    }
    fn investigation_receipt_fixture_for(
        model: &str,
    ) -> (tempfile::TempDir, Store, Pending, Receipt, Vec<u8>) {
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
            payload: json!({"model":model,"messages":[{"role":"system","content":provider::INVESTIGATION_PROMPT}]}),
            attempt: 1,
            retry_of: None,
            purpose: provider::Purpose::Investigation,
        };
        util::atomic_json(&store.path.join(&pending.request_path), &input, false).unwrap();
        let decision = json!({"tool":"view_region","arguments":{"region_px":[0,0,400,300]},"reason":"Look at the body plan."});
        let transport = models::settings(model).unwrap().transport;
        let body = if transport == models::Transport::ClaudeSubscription {
            claude_cli_body(model, &decision, false)
        } else {
            util::json_bytes(&json!({"id":"completion-1","model":model,
            "choices":[{"finish_reason":"stop","message":{"content":decision.to_string()}}],
            "usage":{"prompt_tokens":30,"completion_tokens":5,"total_tokens":35,"cost":0.0,"opencode":{"billing_source":"go"}}}))
            .unwrap()
        };
        let mut receipt = Receipt {
            protocol: provider::PROTOCOL.into(),
            request_id: pending.id.clone(),
            state: RequestState::NotSent,
            endpoint: transport.endpoint().into(),
            requested_model: model.into(),
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
            vision: None,
        };
        provider::interpret_completion(&mut receipt, &body, "").unwrap();
        store.state.pending = Some(pending.clone());
        (tmp, store, pending, receipt, body)
    }
    /// The stream-json stdout of the `claude` CLI for one answer, or for a
    /// subscription usage-limit error.
    fn claude_cli_body(model: &str, answer: &Value, limit_reached: bool) -> Vec<u8> {
        let init = json!({"type":"system","subtype":"init","tools":["StructuredOutput"],
            "mcp_servers":[],"apiKeySource":"none","model":model});
        let result = if limit_reached {
            json!({"type":"result","subtype":"success","is_error":true,"api_error_status":null,
                "result":"You've hit your limit · resets 3pm","uuid":"result-limit",
                "usage":{"input_tokens":0,"output_tokens":0},"modelUsage":{}})
        } else {
            json!({"type":"result","subtype":"success","is_error":false,"api_error_status":null,
                "stop_reason":"tool_use","result":answer.to_string(),"structured_output":answer,
                "uuid":"result-1","total_cost_usd":0.0125,
                "usage":{"input_tokens":2,"cache_creation_input_tokens":20,"cache_read_input_tokens":8,"output_tokens":5},
                "modelUsage":{model:{"inputTokens":2,"outputTokens":5}}})
        };
        let mut bytes = vec![];
        for line in [init, result] {
            bytes.extend(util::json_bytes(&line).unwrap());
            bytes.push(b'\n');
        }
        bytes
    }
    #[test]
    fn claude_subscription_receipts_are_accepted_and_reread_from_the_body() {
        use crate::models::{CLAUDE_CLI_ENDPOINT, CLAUDE_SONNET_5_5};
        let (_tmp, mut store, pending, receipt, body) =
            investigation_receipt_fixture_for(CLAUDE_SONNET_5_5);
        use_models(&mut store, &crate::models::DEFAULT_MODELS);
        assert_eq!(receipt.state, RequestState::Completed);
        assert_eq!(receipt.endpoint, CLAUDE_CLI_ENDPOINT);
        assert_eq!(receipt.usage["prompt_tokens"], 30);
        assert_eq!(receipt.usage["total_tokens"], 35);
        assert_eq!(receipt.usage["list_cost"], 0.0125);
        assert_eq!(receipt.usage["billing_source"], "subscription");
        let applied = apply_forged(&mut store, &pending, &receipt, Some(&body))
            .unwrap()
            .unwrap();
        assert_eq!(applied.decision.unwrap().tool, "view_region");
        // An edited decision no longer matches the stored CLI output.
        let (_tmp, mut store, pending, mut receipt, body) =
            investigation_receipt_fixture_for(CLAUDE_SONNET_5_5);
        use_models(&mut store, &crate::models::DEFAULT_MODELS);
        receipt.decision.as_mut().unwrap().reason = "edited".into();
        assert_eq!(
            apply_forged(&mut store, &pending, &receipt, Some(&body)).unwrap_err(),
            "provider_receipt_body_mismatch"
        );
        // A Claude receipt that claims the OpenCode Go endpoint is refused.
        let (_tmp, mut store, pending, mut receipt, body) =
            investigation_receipt_fixture_for(CLAUDE_SONNET_5_5);
        use_models(&mut store, &crate::models::DEFAULT_MODELS);
        receipt.endpoint = GO_ENDPOINT.into();
        assert_eq!(
            apply_forged(&mut store, &pending, &receipt, Some(&body)).unwrap_err(),
            "provider_receipt_identity"
        );
    }
    #[test]
    fn a_subscription_usage_limit_moves_sonnet_to_crouton() {
        use crate::models::{CLAUDE_SONNET_5_5, CROUTON_ALPHA_FREE, DEFAULT_MODELS};
        let (_tmp, mut store, _pending, mut receipt, _body) =
            investigation_receipt_fixture_for(CLAUDE_SONNET_5_5);
        use_models(&mut store, &DEFAULT_MODELS);
        store.state.pending = None;
        receipt.decision = None;
        let limited = claude_cli_body(CLAUDE_SONNET_5_5, &json!({}), true);
        assert_eq!(
            provider::interpret_completion(&mut receipt, &limited, "").unwrap_err(),
            "provider_rate_limited"
        );
        receipt.error_code = Some("provider_rate_limited".into());
        assert!(models::rate_limited(&receipt));
        assert!(switch_model(&mut store, &receipt).unwrap());
        assert_eq!(store.state.current_model(), CROUTON_ALPHA_FREE);
        let event = store.events.last().unwrap();
        assert_eq!(event.kind, "model_switched");
        assert_eq!(event.payload["from"], CLAUDE_SONNET_5_5);
        assert_eq!(event.payload["to"], CROUTON_ALPHA_FREE);
        assert_eq!(event.payload["reason"], "provider_rate_limited");
        // Another CLI failure is not a reason to switch.
        let mut other = receipt.clone();
        other.error_code = Some("provider_cli_error".into());
        other.http_status = Some(500);
        assert!(!models::rate_limited(&other));
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
    fn use_models(store: &mut Store, models: &[&str]) {
        store.state.config.model = models[0].into();
        store.state.config.fallback_models = models[1..].iter().map(|m| m.to_string()).collect();
    }
    #[test]
    fn receipts_must_name_a_model_of_the_run() {
        use crate::models::{CROUTON_ALPHA_FREE, DEEPSEEK_V4_1_FLASH};
        // A Crouton receipt is accepted when Crouton is in the run's list.
        let (_tmp, mut store, pending, receipt, body) =
            investigation_receipt_fixture_for(CROUTON_ALPHA_FREE);
        use_models(&mut store, &[CROUTON_ALPHA_FREE, DEEPSEEK_V4_1_FLASH]);
        let applied = apply_forged(&mut store, &pending, &receipt, Some(&body)).unwrap();
        assert_eq!(
            applied.unwrap().returned_model.as_deref(),
            Some(CROUTON_ALPHA_FREE)
        );
        // The same receipt on a DeepSeek-only run is refused.
        let (_tmp, mut store, pending, receipt, body) =
            investigation_receipt_fixture_for(CROUTON_ALPHA_FREE);
        assert_eq!(store.state.config.models(), [DEEPSEEK_V4_1_FLASH]);
        let error = apply_forged(&mut store, &pending, &receipt, Some(&body)).unwrap_err();
        assert_eq!(error, "provider_receipt_identity");
        // A completion from another model than the requested one is refused.
        let (_tmp, _store, _pending, mut receipt, body) =
            investigation_receipt_fixture_for(CROUTON_ALPHA_FREE);
        let other = String::from_utf8(body)
            .unwrap()
            .replace(CROUTON_ALPHA_FREE, DEEPSEEK_V4_1_FLASH);
        let error = provider::interpret_completion(&mut receipt, other.as_bytes(), "").unwrap_err();
        assert_eq!(error, "provider_model_identity");
    }
    #[test]
    fn run_state_refuses_models_outside_the_allow_list() {
        let (_tmp, mut store) = fixture();
        for list in [
            ["claude-haiku-5-5"].as_slice(),
            &["gpt-6.1-sol"],
            &[GO_MODEL, GO_MODEL],
        ] {
            use_models(&mut store, list);
            assert_eq!(
                store.state.validate().unwrap_err(),
                "invalid_state_contract"
            );
        }
        use_models(&mut store, &[GO_MODEL]);
        store.state.active_model = Some(crate::models::CROUTON_ALPHA_FREE.into());
        assert_eq!(
            store.state.validate().unwrap_err(),
            "invalid_state_contract"
        );
    }
    #[test]
    fn rate_limit_moves_the_run_to_the_next_model_once() {
        use crate::models::{CROUTON_ALPHA_FREE, DEEPSEEK_V4_1_FLASH};
        let (_tmp, mut store, _pending, mut receipt, _body) =
            investigation_receipt_fixture_for(CROUTON_ALPHA_FREE);
        use_models(&mut store, &[CROUTON_ALPHA_FREE, DEEPSEEK_V4_1_FLASH]);
        store.state.pending = None;
        // Another failure (a server error) is not a reason to switch.
        receipt.state = RequestState::Failed;
        receipt.decision = None;
        receipt.returned_model = None;
        receipt.http_status = Some(500);
        receipt.error_code = Some("provider_http_failure".into());
        assert!(!models::rate_limited(&receipt));
        // HTTP 429 moves the run to DeepSeek and records the switch.
        receipt.http_status = Some(429);
        receipt.error_code = Some("provider_rate_limited".into());
        assert!(models::rate_limited(&receipt));
        assert!(switch_model(&mut store, &receipt).unwrap());
        assert_eq!(store.state.current_model(), DEEPSEEK_V4_1_FLASH);
        let event = store.events.last().unwrap();
        assert_eq!(event.kind, "model_switched");
        assert_eq!(event.payload["from"], CROUTON_ALPHA_FREE);
        assert_eq!(event.payload["to"], DEEPSEEK_V4_1_FLASH);
        assert_eq!(event.payload["reason"], "provider_rate_limited");
        assert_eq!(event.payload["http_status"], 429);
        assert_eq!(summary(&store)["current_model"], DEEPSEEK_V4_1_FLASH);
        // An exhausted usage window on the last model leaves nothing to switch to.
        receipt.requested_model = DEEPSEEK_V4_1_FLASH.into();
        receipt.state = RequestState::NotSent;
        receipt.http_status = None;
        receipt.error_code = Some("provider_all_credentials_unavailable".into());
        assert!(models::rate_limited(&receipt));
        assert!(!switch_model(&mut store, &receipt).unwrap());
        assert_eq!(store.state.current_model(), DEEPSEEK_V4_1_FLASH);
    }
}
