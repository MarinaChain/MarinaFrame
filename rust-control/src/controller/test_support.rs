//! Fixtures shared by the controller unit tests.
use super::new_state;
use crate::models;
use crate::provider::{self, ProviderInput, Receipt, RequestState};
use crate::store::Store;
use crate::types::*;
use crate::util;
use serde_json::{json, Value};

pub(super) fn fixture() -> (tempfile::TempDir, Store) {
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
        inspection_workers: None,
    };
    let store = Store::create(&tmp.path().join("task"), new_state(config)).unwrap();
    (tmp, store)
}

// ------------------------------------------- investigation receipts

/// A live draft-mode task with one pending investigation request, its
/// honest response body on disk and the honest receipt for it.
pub(super) fn investigation_receipt_fixture(
) -> (tempfile::TempDir, Store, Pending, Receipt, Vec<u8>) {
    investigation_receipt_fixture_for(GO_MODEL)
}
pub(super) fn investigation_receipt_fixture_for(
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
pub(super) fn claude_cli_body(model: &str, answer: &Value, limit_reached: bool) -> Vec<u8> {
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

pub(super) fn use_models(store: &mut Store, models: &[&str]) {
    store.state.config.model = models[0].into();
    store.state.config.fallback_models = models[1..].iter().map(|m| m.to_string()).collect();
}
