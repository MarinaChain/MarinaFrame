//! The checks that adopt a provider receipt for a decision request.
use super::investigation_mode;
use super::stops::stop;
use crate::provider::{self, ProviderInput, Receipt, RequestState};
use crate::store::{self, Store};
use crate::types::*;
use crate::util::{self, Result};
use crate::worker;
use serde_json::{json, Value};

/// The decision purpose of this task: investigation in live draft mode.
pub(super) fn decision_purpose(store: &Store) -> provider::Purpose {
    if investigation_mode(store) {
        provider::Purpose::Investigation
    } else {
        provider::Purpose::ModelDecision
    }
}
pub(super) fn apply_provider(
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

#[cfg(test)]
mod tests {
    use super::*;
    use crate::controller::test_support::*;
    use crate::provider::ImageReceipt;
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
}
