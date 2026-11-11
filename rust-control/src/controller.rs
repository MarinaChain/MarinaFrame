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
    if operation == "build_provisional" {
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
            let step = util::safe_file(
                &store.path,
                &format!(
                    "{}/model.step",
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
fn collect_images(store: &Store) -> Result<Vec<(ImageReceipt, String)>> {
    let mut found = BTreeMap::<String, BoundImage>::new();
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
    values.sort_by_key(|(seq, a, _, _, _)| (!a.get("view").is_some(), std::cmp::Reverse(*seq)));
    // Preserve at least one source observation beside current CAD observations.
    let mut chosen = vec![];
    if let Some(source) = values
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
        };
        images.push((meta, STANDARD.encode(bytes)));
    }
    Ok(images)
}
pub fn tool_catalog() -> Value {
    let empty = json!({"type":"object","properties":{},"additionalProperties":false});
    json!([
        {"name":"inspect_source","description":"Inspect source regions and preserved candidate alternatives; section_ids optional, at most12 sections per observation.","parameters":{"type":"object","properties":{"section_ids":{"type":"array","items":{"type":"string"}}},"additionalProperties":false}},
        {"name":"select_contours","description":"Choose already inspected candidate IDs; retains alternatives and invalidates previous validation and renders.","parameters":{"type":"object","properties":{"selections":{"type":"array","items":{"type":"object","properties":{"section_id":{"type":"string"},"candidate_id":{"type":"string"}},"required":["section_id","candidate_id"],"additionalProperties":false}}},"required":["selections"],"additionalProperties":false}},
        {"name":"build_provisional","description":"Build current source-supported selections with the trusted CAD engine.","parameters":empty},
        {"name":"render_candidate","description":"Reimport exported STEP and render view for visual inspection.","parameters":{"type":"object","properties":{"view":{"enum":["body","plan","profile","oblique"]}},"required":["view"],"additionalProperties":false}},
        {"name":"validate_candidate","description":"Audit current exported STEP against selected source traces; failures remain failures on cache hits.","parameters":empty},
        {"name":"finish","description":"Abstain or request human review after current passing validation and visual inspection; never engineering approval.","parameters":{"type":"object","properties":{"outcome":{"enum":["candidate_ready_for_review","abstain"]},"summary":{"type":"string","maxLength":512}},"required":["outcome","summary"],"additionalProperties":false}}
    ])
}
fn model_observation(store: &Store) -> Result<Value> {
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
        || receipt.source_manifest_sha256
            != store.state.source_manifest_sha256.as_deref().unwrap_or("")
        || receipt.generation_id != store.state.generation_id.as_deref().unwrap_or("")
        || receipt.revision_id != store.state.revision_id.as_deref().unwrap_or("")
    {
        return Err("provider_receipt_identity".into());
    }
    if receipt.request_sha256 != util::hash_json(&input.payload)?
        || receipt.prompt_sha256 != util::hash(provider::SYSTEM_PROMPT.as_bytes())
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
    let prompt = json!({"observation":observation,"tools":tool_catalog(),"images":metas});
    let mut content = vec![
        json!({"type":"text","text":String::from_utf8(util::json_bytes(&prompt)?).map_err(|_|"prompt_encoding")?}),
    ];
    for (_, pixels) in images {
        content.push(json!({"type":"image_url","image_url":{"url":format!("data:image/png;base64,{pixels}"),"detail":"original"}}));
    }
    let payload = json!({"model":GO_MODEL,"max_tokens":store.state.config.limits.max_output_tokens_per_request,"stream":false,"thinking":{"type":"disabled"},"temperature":0,
        "response_format":{"type":"json_object"},"messages":[{"role":"system","content":provider::SYSTEM_PROMPT},{"role":"user","content":content}]});
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

fn decision(tool: &str, arguments: Value, reason: &str) -> Decision {
    Decision {
        tool: tool.into(),
        arguments,
        reason: reason.into(),
    }
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
        return Ok(decision(
            "inspect_source",
            json!({}),
            "Inspect the next source regions and retain alternatives.",
        ));
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

fn validate_selection(store: &Store, operation: &Operation, actor: &str) -> Result<()> {
    let checkpoint = util::read_json(
        &util::safe_file(&store.path, "domain/state.json")?,
        32 * 1024 * 1024,
    )?;
    match operation {
        Operation::SelectContours(x) => {
            for choice in &x.selections {
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
                if ["live_model", "deterministic_policy"].contains(&actor)
                    && candidate["non_grid_competing_components"].as_u64() != Some(0)
                {
                    return Err("source_ambiguity_requires_explicit_operator_selection".into());
                }
            }
        }
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
    if let Operation::Finish(finish) = operation {
        store.state.staged_decision = None;
        if finish.outcome == FinishOutcome::Abstain {
            stop(store, Status::Abstained, &finish.summary)?;
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
        ) {
            Ok(contract) => {
                if store.state.config.policy == Policy::Live
                    && !live_visual_coverage(store, &contract.binding.step_sha256)
                {
                    store.state.last_observation = json!({"ok":false,"status":"rejected","error_code":"current_step_body_and_oblique_pixels_not_observed_by_model","engineering_approved":false,"human_semantic_review_required":true});
                    store.append("finalization_rejected",json!({"reason":"current_step_body_and_oblique_pixels_not_observed_by_model"}))?;
                    return Ok(true);
                }
                store.state.status = Status::AwaitingHumanReview;
                store.state.termination_reason = Some(finish.summary);
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
                    if !live_decision(store)? {
                        return Ok(());
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
        let actor = if store.state.config.policy == Policy::Live {
            "live_model"
        } else {
            "deterministic_policy"
        };
        match execute_decision(store, choice, actor) {
            Ok(true) => (),
            Ok(false) => return Ok(()),
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
}
