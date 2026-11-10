//! The live policy: one model decision request with retries, model
//! switches and the feedback for a refused tool call.
use super::catalog::{phase_tool_catalog, tool_catalog};
use super::images::collect_images;
use super::investigation_mode;
use super::observation::{model_observation, split_stable_context};
use super::provider_receipt::{apply_provider, decision_purpose};
use super::stops::{consecutive_refusals, refusal_limit, stop};
use super::transcript;
use super::worker_call::{budget_admission, current_binary, source_spec};
use crate::provider::{self, ProviderInput, Receipt, RequestState};
use crate::store::{self, Store};
use crate::types::*;
use crate::util::{self, Result};
use crate::{models, worker};
use serde_json::{json, Value};
use std::time::{Duration, Instant};

pub(super) fn live_decision(store: &mut Store) -> Result<bool> {
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
pub fn model_output_refused(receipt: &Receipt) -> bool {
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

#[cfg(test)]
mod tests {
    use super::*;
    use crate::controller::summary;
    use crate::controller::test_support::*;
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
