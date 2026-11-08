//! Bounded investigation conversation projected from the existing task ledger.
use crate::store::Event;
use crate::types::State;
use crate::util::{self, Result};
use serde_json::{json, Value};

pub struct Transcript {
    pub messages: Vec<Value>,
    pub steps_total: usize,
    pub steps_kept: usize,
    pub estimated_tokens: u64,
    pub summary: Option<Value>,
}

fn safe_text(text: &str) -> String {
    text.split_whitespace()
        .map(|word| {
            if [
                "/Users/",
                "/home/",
                "/private/",
                "/tmp/",
                "domain/",
                "sk-",
                "OPENCODE_API_KEY",
            ]
            .iter()
            .any(|marker| word.contains(marker))
            {
                "[redacted]"
            } else {
                word
            }
        })
        .collect::<Vec<_>>()
        .join(" ")
}

fn safe_value(value: &Value) -> Value {
    match value {
        Value::Object(object) => Value::Object(
            object
                .iter()
                .filter(|(key, _)| {
                    ![
                        "path",
                        "artifacts",
                        "resources",
                        "source_file",
                        "source_truth",
                    ]
                    .contains(&key.as_str())
                        && !key.contains("sha256")
                        && !key.starts_with("truth")
                        && !key.starts_with("expected_")
                        && !key.starts_with("reference_")
                })
                .map(|(key, value)| (key.clone(), safe_value(value)))
                .collect(),
        ),
        Value::Array(array) => Value::Array(array.iter().map(safe_value).collect()),
        Value::String(text) => json!(safe_text(text)),
        _ => value.clone(),
    }
}

/// Only short operational fields enter historical tool results.
pub fn compact_result(result: &Value) -> Value {
    let mut compact = serde_json::Map::new();
    for key in [
        "ok",
        "status",
        "error_code",
        "message",
        "candidate_id",
        "section_id",
        "panel_section_ids",
        "selected_count",
        "remaining_count",
        "useful_next_actions",
    ] {
        if let Some(value) = result.get(key) {
            let value = if let Some(text) = value.as_str() {
                json!(text.chars().take(300).collect::<String>())
            } else {
                value.clone()
            };
            compact.insert(key.into(), value);
        }
    }
    if let Some(view) = result.get("view") {
        compact.insert(
            "view".into(),
            json!({"view_id":view["view_id"],"kind":view["kind"],
            "crop_box_px":view["crop_box_px"],"pixel_size":view["pixel_size"]}),
        );
    }
    if let Some(strokes) = result["strokes"].as_array() {
        compact.insert("stroke_count".into(), json!(strokes.len()));
        compact.insert(
            "grid_line_count".into(),
            json!(strokes
                .iter()
                .filter(|s| s["kind"] == "straight_grid_line")
                .count()),
        );
    }
    if result.get("earlier_result").is_some() {
        compact.insert(
            "earlier_view_id".into(),
            result["earlier_result"]["view"]["view_id"].clone(),
        );
    }
    safe_value(&Value::Object(compact))
}

pub fn estimate(messages: &[Value], images: usize) -> Result<u64> {
    // Image bytes are excluded: their fixed allowance is counted separately.
    let mut bytes = 0;
    for message in messages {
        if let Some(text) = message["content"].as_str() {
            bytes += text.len();
        } else if let Some(parts) = message["content"].as_array() {
            for part in parts {
                bytes += part["text"].as_str().map(str::len).unwrap_or(0);
            }
        }
    }
    Ok(bytes.div_ceil(3) as u64 + 800 * images as u64)
}

pub fn build(
    events: &[Event],
    state: &State,
    system: &str,
    observation: Value,
    tools: Value,
    current_content: Vec<Value>,
) -> Result<Transcript> {
    let observation = safe_value(&observation);
    let budget = state.config.limits.max_context_tokens;
    let image_count = current_content
        .iter()
        .filter(|part| part["type"] == "image_url")
        .count();
    let mut steps = Vec::new();
    for (index, event) in events.iter().enumerate() {
        if !["provider_result", "provider_reconciled"].contains(&event.kind.as_str()) {
            continue;
        }
        let receipt = &event.payload["receipt"];
        if receipt["state"] != "completed"
            || receipt["purpose"] != "investigation"
            || !receipt["decision"].is_object()
        {
            continue;
        }
        let next = events[index + 1..]
            .iter()
            .position(|e| e.kind == "provider_intent");
        let result = next
            .map(|offset| events[index + offset].state_after.last_observation.clone())
            .unwrap_or_else(|| state.last_observation.clone());
        steps.push((
            event.sequence,
            safe_value(&receipt["decision"]),
            compact_result(&result),
        ));
    }
    let total = steps.len();
    let mut keep = total.min(12);
    let mut summary = None;
    loop {
        let folded = total - keep;
        let mut header = json!({"task":"Investigate stations and produce an unverified CAD draft", "tools":tools});
        if folded > 0 {
            let record = steps[..folded].iter().rev().take(12).rev().map(|(seq, decision, result)|
                json!({"event":seq,"tool":decision["tool"],"arguments":decision["arguments"],"result":result})).collect::<Vec<_>>();
            let handoff = steps[..folded]
                .iter()
                .rev()
                .find_map(|(_, d, _)| d["notes"].as_str());
            let memory = json!({"author":"controller","folded_steps":folded,"recent_folded_steps":record,
                "model_handoff":{"author":"model","verified":false,"claim":handoff.map(safe_text)}});
            header["memory"] = memory.clone();
            summary = Some(memory);
        }
        let mut messages = vec![
            json!({"role":"system","content":system}),
            json!({"role":"user","content":String::from_utf8(util::json_bytes(&header)?).map_err(|_|"transcript_encoding")?}),
        ];
        for (offset, (_, decision, result)) in steps[folded..].iter().enumerate() {
            messages.push(json!({"role":"assistant","content":String::from_utf8(util::json_bytes(decision)?).map_err(|_|"transcript_encoding")?}));
            if offset + 1 < keep {
                messages.push(json!({"role":"user","content":String::from_utf8(util::json_bytes(result)?).map_err(|_|"transcript_encoding")?}));
            }
        }
        let progress = json!({"assigned":state.domain["model_choice_section_ids"],
            "selected_count":state.domain["selected_count"],"draft":state.domain["current_candidate"]["valid"],
            "model_steps":total,"engineering_approved":false});
        let mut content = vec![
            json!({"type":"text","text":format!("Progress: {progress}\nCurrent observation: {observation}")}),
        ];
        // The caller supplies image parts only; no old pixels enter the transcript.
        content.extend(
            current_content
                .iter()
                .filter(|part| part["type"] == "image_url")
                .cloned(),
        );
        if keep == 0 {
            let header = messages.pop().unwrap()["content"]
                .as_str()
                .unwrap()
                .to_owned();
            content.insert(0, json!({"type":"text","text":header}));
        }
        messages.push(json!({"role":"user","content":content}));
        let estimated = estimate(&messages, image_count)?;
        if estimated <= budget {
            return Ok(Transcript {
                messages,
                steps_total: total,
                steps_kept: keep,
                estimated_tokens: estimated,
                summary,
            });
        }
        if keep == 0 {
            return Err("context_budget_exceeded".into());
        }
        keep = if keep > 4 { 4 } else { keep - 1 };
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn compact_results_drop_paths_secrets_and_resources() {
        let value = compact_result(
            &json!({"ok":false,"status":"proposal_refused","error_code":"unknown_view",
            "path":"/Users/private/key","resources":{"secret":"sk-test"},"truth":42,"sha256":"secret"}),
        );
        assert_eq!(
            value,
            json!({"ok":false,"status":"proposal_refused","error_code":"unknown_view"})
        );
    }
    #[test]
    fn conversation_retains_refusal_and_current_observation_with_bounded_pairs() {
        use crate::controller::new_state;
        use crate::types::*;
        let config: Config = serde_json::from_value(json!({"worker_python":"/p","worker_source":null,"source_spec":"/s","policy":"live",
            "limits":OperationalLimits::default(),"provider_transfer_authorized":true,"authorization_basis":"test","model":GO_MODEL,"binary_sha256":"a".repeat(64)})).unwrap();
        let mut state = new_state(config);
        state.last_observation =
            json!({"status":"repeated_action_refused","error_code":"repeated_action_refused"});
        let events = (0..20).map(|n| Event { sequence:n, previous_sha256:None, kind:"provider_result".into(), time_ms:0,
            payload:json!({"receipt":{"state":"completed","purpose":"investigation","decision":{"tool":"read_region","arguments":{},"reason":"read","notes":format!("label {n}")}}}),
            state_after:state.clone(),event_sha256:"a".repeat(64)}).collect::<Vec<_>>();
        let transcript = build(
            &events,
            &state,
            "system",
            json!({"latest":"always here"}),
            json!([]),
            vec![],
        )
        .unwrap();
        assert_eq!(transcript.steps_total, 20);
        assert_eq!(transcript.steps_kept, 12);
        assert!(transcript.summary.is_some());
        assert!(transcript.estimated_tokens <= state.config.limits.max_context_tokens);
        let text = serde_json::to_string(&transcript.messages).unwrap();
        assert!(text.contains("repeated_action_refused") && text.contains("always here"));
        for (index, message) in transcript.messages.iter().enumerate().skip(1) {
            assert_eq!(
                message["role"],
                if index % 2 == 1 { "user" } else { "assistant" }
            );
        }
        let restored: Vec<Event> =
            serde_json::from_value(serde_json::to_value(&events).unwrap()).unwrap();
        assert_eq!(
            build(
                &restored,
                &state,
                "system",
                json!({"latest":"always here"}),
                json!([]),
                vec![]
            )
            .unwrap()
            .messages,
            transcript.messages
        );
        assert!(build(
            &events,
            &state,
            "system",
            json!({"large":"x".repeat(120000)}),
            json!([]),
            vec![]
        )
        .is_err());
    }
    #[test]
    fn image_payload_bytes_are_not_text_tokens() {
        let messages = vec![
            json!({"role":"user","content":[{"type":"text","text":"abc"},
            {"type":"image_url","image_url":{"url":"x".repeat(10000)}}]}),
        ];
        assert_eq!(estimate(&messages, 1).unwrap(), 801);
    }
}
