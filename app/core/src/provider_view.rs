//! Model (provider) requests of a task, read from the event ledger.
use crate::artifact::guard_artifact_path;
use crate::files;
use crate::types::{CallState, ProviderCallView, ProviderImage};
use marinaframe_control::util;
use serde_json::Value;
use std::path::Path;

/// Ledger event kinds that record one provider request outcome.
const PROVIDER_KINDS: [&str; 4] = [
    "provider_result",
    "provider_reconciled",
    "provider_not_sent",
    "provider_outcome_unknown",
];

pub fn provider_calls(task: &Path) -> Vec<ProviderCallView> {
    files::event_files(task)
        .into_iter()
        .filter_map(|(_, path)| {
            // Event files are compact JSON with sorted keys. This check avoids
            // parsing the large events that have nothing to do with the model.
            let bytes = util::read_bounded(&path, 4 * 1024 * 1024).ok()?;
            if !bytes.windows(17).any(|w| w == b"\"kind\":\"provider_") {
                return None;
            }
            let event: Value = serde_json::from_slice(&bytes).ok()?;
            call_from_event(task, &event)
        })
        .collect()
}

fn image_label(image: &Value) -> String {
    let kind = image["evidence_kind"].as_str().unwrap_or("image");
    let view = image["view"].as_str();
    match (kind, view) {
        (_, Some(view)) => format!("{} view of the model", capitalize(view)),
        (kind, None) if kind.contains("source") => "Source drawing".into(),
        (kind, None) => capitalize(&kind.replace('_', " ")),
    }
}

fn capitalize(text: &str) -> String {
    let mut chars = text.chars();
    chars
        .next()
        .map(|c| c.to_uppercase().collect::<String>() + chars.as_str())
        .unwrap_or_default()
}

fn call_from_event(task: &Path, event: &Value) -> Option<ProviderCallView> {
    let kind = event["kind"].as_str()?;
    if !PROVIDER_KINDS.contains(&kind) {
        return None;
    }
    let payload = &event["payload"];
    let empty = |id: &str, state: CallState| ProviderCallView {
        id: id.into(),
        state,
        images: vec![],
        answer: String::new(),
        accepted: false,
        prompt_tokens: None,
        completion_tokens: None,
        cost_usd: None,
        key_slot: None,
    };
    match kind {
        "provider_not_sent" => Some(empty(payload["request_id"].as_str()?, CallState::NotSent)),
        "provider_outcome_unknown" => {
            Some(empty(payload["request_id"].as_str()?, CallState::Unknown))
        }
        _ => {
            let receipt = &payload["receipt"];
            let state = match receipt["state"].as_str()? {
                "completed" => CallState::Completed,
                "failed" => CallState::Failed,
                "not_sent" => CallState::NotSent,
                _ => CallState::Unknown,
            };
            let decision = receipt["decision"].as_object();
            let answer = match decision {
                Some(d) => format!(
                    "{}: {}",
                    d.get("tool")
                        .and_then(Value::as_str)
                        .unwrap_or("?")
                        .replace('_', " "),
                    d.get("reason").and_then(Value::as_str).unwrap_or("")
                ),
                None => receipt["error_code"]
                    .as_str()
                    .map(|code| format!("No usable answer ({})", code.replace('_', " ")))
                    .unwrap_or_default(),
            };
            let images = receipt["images"]
                .as_array()
                .map(|list| {
                    list.iter()
                        .filter(|i| i["pixels_attached"] == true)
                        .filter_map(|i| {
                            let path = i["path"].as_str()?;
                            guard_artifact_path(task, path).ok()?;
                            Some(ProviderImage {
                                path: path.into(),
                                label: image_label(i),
                            })
                        })
                        .collect()
                })
                .unwrap_or_default();
            Some(ProviderCallView {
                id: receipt["request_id"].as_str()?.into(),
                state,
                images,
                answer,
                accepted: state == CallState::Completed && decision.is_some(),
                prompt_tokens: receipt["usage"]["prompt_tokens"].as_u64(),
                completion_tokens: receipt["usage"]["completion_tokens"].as_u64(),
                cost_usd: receipt["observed_cost_usd"].as_f64(),
                key_slot: receipt["credential_selection"]["slot"].as_u64(),
            })
        }
    }
}
