//! Author-separated adversaries for receipt reconciliation and state recovery.
//! The fixtures are explicit protocol doubles. No network, model or CAD runs.
#![allow(dead_code)]

#[path = "../src/controller.rs"]
mod controller;
#[path = "../src/provider.rs"]
mod provider;
#[path = "../src/store.rs"]
mod store;
#[path = "../src/types.rs"]
mod types;
#[path = "../src/util.rs"]
mod util;
#[path = "../src/validation.rs"]
mod validation;
#[path = "../src/worker.rs"]
mod worker;

use provider::{ProviderInput, Receipt, RequestState};
use serde_json::{json, Value};
use types::*;

fn controlled_config() -> Config {
    Config {
        worker_python: "/fixture/must-not-execute".into(),
        worker_source: None,
        source_spec: "/fixture/not-a-real-drawing".into(),
        policy: Policy::Live,
        limits: OperationalLimits::default(),
        provider_transfer_authorized: true,
        authorization_basis: "Explicit no-network protocol fixture".into(),
        model: GO_MODEL.into(),
        binary_sha256: util::file_hash(&std::env::current_exe().unwrap()).unwrap(),
        on_ambiguity: OnAmbiguity::Abstain,
    }
}

fn provider_fixture() -> (tempfile::TempDir, store::Store, Pending, Receipt) {
    let directory = tempfile::tempdir().unwrap();
    let mut state = controller::new_state(controlled_config());
    state.status = Status::Blocked; // Resume stops after reconciliation, before any worker.
    state.source_manifest_sha256 = Some("a".repeat(64));
    state.generation_id = Some(format!("generation-{}", "b".repeat(24)));
    state.revision_id = Some("r0001".into());
    let mut store = store::Store::create(&directory.path().join("task"), state).unwrap();
    let pending = Pending {
        kind: "provider".into(),
        id: "request-controlled".into(),
        operation: "model_decision".into(),
        response_path: "receipts/provider.json".into(),
        request_path: "requests/provider.json".into(),
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
        payload: json!({"model": GO_MODEL, "messages": [{"role":"system", "content":provider::SYSTEM_PROMPT}], "fixture":"not transmitted"}),
        attempt: 1,
        retry_of: None,
        purpose: Default::default(),
    };
    util::atomic_json(&store.path.join(&pending.request_path), &input, false).unwrap();
    store.state.pending = Some(pending.clone());
    store.state.counters.requests_intended = 1;
    store.append("controlled_provider_intent", json!({"request":store::artifact(&store.path, &pending.request_path, "provider_request").unwrap()})).unwrap();
    let receipt = Receipt {
        protocol: provider::PROTOCOL.into(),
        request_id: pending.id.clone(),
        state: RequestState::Completed,
        endpoint: GO_ENDPOINT.into(),
        requested_model: GO_MODEL.into(),
        returned_model: Some(GO_MODEL.into()),
        completion_id: Some("controlled-completion".into()),
        provider_request_id: Some("controlled-receipt".into()),
        http_status: Some(200),
        response_sha256: Some("d".repeat(64)),
        request_sha256: util::hash_json(&input.payload).unwrap(),
        prompt_sha256: util::hash(provider::SYSTEM_PROMPT.as_bytes()),
        source_manifest_sha256: input.source_manifest_sha256,
        generation_id: input.generation_id,
        revision_id: input.revision_id,
        observation_sha256: input.observation_sha256,
        images: vec![],
        usage: json!({"prompt_tokens":3,"completion_tokens":5,"total_tokens":8}),
        observed_cost_usd: None,
        latency_seconds: 0.01,
        decision: Some(Decision {
            tool: "finish".into(),
            arguments: json!({"outcome":"abstain","summary":"Protocol fixture only."}),
            reason: "Controlled receipt.".into(),
        }),
        error_code: None,
        attempt: 1,
        retry_of: None,
        retry_after_seconds: None,
        aggregate_request_cap: None,
        aggregate_token_cap: None,
        aggregate_spend_cap: None,
        evidence_mode: "live".into(),
        credential_selection: None,
        purpose: Default::default(),
        transcription: None,
    };
    (directory, store, pending, receipt)
}

fn reconcile(store: &mut store::Store, pending: &Pending, receipt: &Receipt) -> util::Result<()> {
    util::atomic_json(&store.path.join(&pending.response_path), receipt, false).unwrap();
    controller::resume(store, false, false, Some(0))
}

#[test]
fn receipt_baseline_and_missing_cost_remain_explicit() {
    let (_directory, mut store, pending, receipt) = provider_fixture();
    assert_eq!(
        reconcile(&mut store, &pending, &receipt).unwrap_err(),
        "terminal_task_requires_explicit_source_backed_intervention"
    );
    assert_eq!(store.state.counters.requests_completed, 1);
    assert_eq!(store.state.counters.requests_without_cost, 1);
    assert_eq!(store.state.counters.observed_cost_usd, 0.0);
    assert!(store.state.pending.is_none());
}

#[test]
fn receipt_request_image_and_state_substitutions_are_rejected() {
    for case in [
        "request_hash",
        "prompt_hash",
        "observation_hash",
        "attempt",
        "retry",
        "images",
        "completed_http_error",
        "response_hash_missing",
        "decision_on_failed",
        "negative_latency",
    ] {
        let (_directory, mut store, pending, mut receipt) = provider_fixture();
        match case {
            "request_hash" => receipt.request_sha256 = "e".repeat(64),
            "prompt_hash" => receipt.prompt_sha256 = "e".repeat(64),
            "observation_hash" => receipt.observation_sha256 = "e".repeat(64),
            "attempt" => receipt.attempt = 2,
            "retry" => receipt.retry_of = Some("not-the-recorded-request".into()),
            "images" => receipt.images.push(provider::ImageReceipt {
                artifact_id: "not-transmitted".into(),
                path: "not-transmitted.png".into(),
                sha256: "e".repeat(64),
                bytes: 64,
                mime_type: "image/png".into(),
                evidence_kind: "step_reimport_render".into(),
                view: Some("body".into()),
                generation_id: Some(receipt.generation_id.clone()),
                revision_id: Some(receipt.revision_id.clone()),
                step_sha256: Some("f".repeat(64)),
                pixels_attached: true,
                crop_box_px: None,
                pixel_size: None,
            }),
            "completed_http_error" => receipt.http_status = Some(503),
            "response_hash_missing" => receipt.response_sha256 = None,
            "decision_on_failed" => receipt.state = RequestState::Failed,
            "negative_latency" => receipt.latency_seconds = -0.1,
            _ => unreachable!(),
        }
        let outcome = reconcile(&mut store, &pending, &receipt);
        assert!(outcome.is_err(), "{case}");
        assert_eq!(
            store.state.counters.requests_completed, 0,
            "{case}: malformed receipt adopted"
        );
        assert!(store.state.pending.is_some(), "{case}: pending intent lost");
    }
}

#[test]
fn receipt_cost_and_usage_must_match_the_observed_receipt() {
    for case in [
        "zero_without_cost",
        "cost_mismatch",
        "boolean_tokens",
        "inconsistent_tokens",
    ] {
        let (_directory, mut store, pending, mut receipt) = provider_fixture();
        match case {
            "zero_without_cost" => receipt.observed_cost_usd = Some(0.0),
            "cost_mismatch" => {
                receipt.usage["cost"] = json!(1.0);
                receipt.observed_cost_usd = Some(0.0);
            }
            "boolean_tokens" => receipt.usage["prompt_tokens"] = Value::Bool(true),
            "inconsistent_tokens" => receipt.usage["total_tokens"] = json!(1),
            _ => unreachable!(),
        }
        let _ = reconcile(&mut store, &pending, &receipt);
        assert_eq!(
            store.state.counters.requests_completed, 0,
            "{case}: inconsistent usage/cost adopted"
        );
        assert!(store.state.pending.is_some(), "{case}: pending intent lost");
    }
}

#[test]
fn missing_receipt_stays_unknown_and_requires_explicit_acknowledgement() {
    let (_directory, mut store, _pending, _receipt) = provider_fixture();
    controller::resume(&mut store, false, false, Some(0)).unwrap();
    assert_eq!(store.state.status, Status::Interrupted);
    assert_eq!(store.state.counters.requests_intended, 1);
    assert_eq!(store.state.counters.requests_unknown, 1);
    assert_eq!(store.state.counters.requests_without_cost, 1);
    assert!(store.state.pending.is_none());
    let error = controller::resume(&mut store, false, false, Some(0)).unwrap_err();
    assert_eq!(error, "explicit_unknown_outcome_acknowledgement_required");
    assert_eq!(store.state.counters.requests_intended, 1);
    assert_eq!(store.state.counters.requests_unknown, 1);
    assert!(!store
        .events
        .iter()
        .any(|e| e.kind == "unknown_provider_outcome_acknowledged"));
}

#[test]
fn checkpoint_cache_requires_explicit_committed_prefix_recovery() {
    let directory = tempfile::tempdir().unwrap();
    let task = directory.path().join("task");
    let mut store =
        store::Store::create(&task, controller::new_state(controlled_config())).unwrap();
    let first = std::fs::read(task.join("state.json")).unwrap();
    store.state.status = Status::Paused;
    store
        .append(
            "controlled_pause",
            json!({"reason":"checkpoint recovery fixture"}),
        )
        .unwrap();
    drop(store);
    std::fs::write(task.join("state.json"), first).unwrap();
    assert!(store::Store::open(&task).is_err());
    assert!(store::Store::recover_checkpoint(&task).unwrap()["recovered"] == true);
    let store = store::Store::open(&task).unwrap();
    assert_eq!(store.state.status, Status::Paused);
    assert_eq!(
        store.events.last().unwrap().kind,
        "checkpoint_recovered_from_committed_events"
    );
    assert!(store.verify(false).unwrap()["valid"] == true);
}

#[test]
fn worker_stalled_before_reading_large_request_remains_time_bounded() {
    use std::os::unix::fs::PermissionsExt;
    let directory = tempfile::tempdir().unwrap();
    let child = directory.path().join("nonreading-worker.py");
    std::fs::write(&child, "#!/usr/bin/python3\nimport time\ntime.sleep(30)\n").unwrap();
    std::fs::set_permissions(&child, std::fs::Permissions::from_mode(0o700)).unwrap();
    let mut config = controlled_config();
    config.worker_python = child.to_string_lossy().into_owned();
    config.limits.worker_wall_seconds = 1;
    let pending = Pending {
        kind: "worker".into(),
        id: "controlled-backpressure".into(),
        operation: "observe".into(),
        response_path: "unused-receipt.json".into(),
        request_path: "unused-request.json".into(),
        domain_before: None,
        started_ms: util::now_ms(),
    };
    let outcome = worker::run(
        directory.path(),
        &config,
        &pending,
        &vec![b'x'; 1024 * 1024],
        &directory.path().join("unused-spec.json"),
    )
    .unwrap();
    assert!(matches!(outcome.state, worker::ProcessState::TimedOut));
    assert!(
        outcome.spawned && outcome.wall_seconds < 5.0,
        "blocked stdin exceeded bounded process supervision: {outcome:?}"
    );
}
