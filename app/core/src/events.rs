//! Plain-language timeline built from the event ledger (`events/*.json`).
//!
//! Some ledger events carry no news for a person (step started, decision staged).
//! They produce no timeline line, so sequence numbers in the result have gaps.
use crate::files;
use crate::types::{EventKind, EventView};
use serde_json::Value;
use std::path::Path;

#[cfg(test)]
mod tests;

/// Events with a sequence number above `after_sequence`.
pub fn get_events(task: &Path, after_sequence: u64) -> Vec<EventView> {
    files::event_files(task)
        .into_iter()
        .filter(|(sequence, _)| *sequence > after_sequence)
        .filter_map(|(sequence, path)| {
            let event = files::read_event(&path)?;
            let (text, kind) = describe(&event)?;
            Some(EventView {
                sequence,
                time_ms: event["time_ms"].as_u64().unwrap_or(0),
                text,
                kind,
            })
        })
        .collect()
}

fn section_phrase(ids: Option<&Vec<Value>>, none: &str) -> String {
    match ids {
        Some(ids) if ids.len() == 1 => format!("section {}", ids[0].as_str().unwrap_or("?")),
        Some(ids) if !ids.is_empty() && ids.len() <= 3 => format!(
            "sections {}",
            ids.iter()
                .filter_map(Value::as_str)
                .collect::<Vec<_>>()
                .join(", ")
        ),
        Some(ids) if !ids.is_empty() => format!("{} sections", ids.len()),
        _ => none.to_string(),
    }
}

fn describe_decision(payload: &Value) -> Option<(String, EventKind)> {
    let decision = &payload["decision"];
    let arguments = &decision["arguments"];
    let by_person = matches!(
        payload["actor"].as_str(),
        Some("human_operator" | "assistant_operator")
    );
    let you = |plain: &str, personal: &str| if by_person { personal } else { plain }.to_string();
    match decision["tool"].as_str()? {
        "inspect_source" => Some((
            format!(
                "Read {}",
                section_phrase(arguments["section_ids"].as_array(), "the next sections")
            ),
            EventKind::Read,
        )),
        "select_contours" => {
            let picks = arguments["selections"].as_array();
            let ids: Vec<Value> = picks
                .map(|p| p.iter().map(|s| s["section_id"].clone()).collect())
                .unwrap_or_default();
            let place = section_phrase(Some(&ids), "the sections");
            Some((
                if by_person {
                    format!("You picked a line on {place}")
                } else {
                    format!("Picked lines on {place}")
                },
                EventKind::Choose,
            ))
        }
        "build_provisional" => Some((
            you("Built 3D model", "You rebuilt the 3D model"),
            EventKind::Build,
        )),
        "render_candidate" => Some((
            format!(
                "Rendered the {} view of the model",
                arguments["view"].as_str().unwrap_or("model")
            ),
            EventKind::Render,
        )),
        "validate_candidate" => Some(("Checked against the drawing".into(), EventKind::Check)),
        "finish" if arguments["outcome"] == "abstain" => Some((
            format!(
                "Declined: {}",
                arguments["summary"]
                    .as_str()
                    .unwrap_or("not enough evidence")
            ),
            EventKind::Finish,
        )),
        _ => None,
    }
}

fn describe(event: &Value) -> Option<(String, EventKind)> {
    let payload = &event["payload"];
    let status_after = event["state_after"]["status"].as_str().unwrap_or("");
    match event["kind"].as_str()? {
        "task_created" => Some(("Run created".into(), EventKind::Other)),
        "decision" => describe_decision(payload),
        "worker_result" if payload["response"]["execution_state"] != "completed" => {
            Some(("A step did not finish".into(), EventKind::Other))
        }
        "candidate_ready_for_human_review" => Some(("Ready for review".into(), EventKind::Finish)),
        "finalization_rejected" => Some((
            "Not ready: the model has not looked at the current views".into(),
            EventKind::Finish,
        )),
        "operation_rejected" => Some((
            format!(
                "Stopped: {}",
                plain_reason(payload["reason"].as_str().unwrap_or(""))
            ),
            EventKind::Other,
        )),
        "task_terminated" => match status_after {
            "cancelled" => Some(("Cancelled".into(), EventKind::Finish)),
            "paused" => Some(("Paused".into(), EventKind::Other)),
            "abstained" | "awaiting_human_review" => None,
            _ => Some((
                format!(
                    "Stopped: {}",
                    plain_reason(payload["reason"].as_str().unwrap_or(""))
                ),
                EventKind::Finish,
            )),
        },
        "task_resumed" => Some(("Resumed".into(), EventKind::Other)),
        "cancellation_acknowledged" => Some(("Cancel request cleared".into(), EventKind::Other)),
        "provider_result" | "provider_reconciled" => {
            let tool = payload["receipt"]["decision"]["tool"].as_str();
            Some((
                match tool {
                    Some(tool) => format!("Model answered: {}", tool.replace('_', " ")),
                    None => "Model answered without a usable choice".into(),
                },
                EventKind::Model,
            ))
        }
        "provider_not_sent" => Some(("Model request was not sent".into(), EventKind::Model)),
        "provider_outcome_unknown" => Some((
            "Model request ended without an answer".into(),
            EventKind::Model,
        )),
        _ => None,
    }
}

/// Plain text for a controller stop reason. Unknown reasons are shown with
/// underscores turned into spaces.
pub fn plain_reason(reason: &str) -> String {
    let known = match reason {
        "requested_step_boundary" => "paused at a step boundary",
        "operator_action_completed" => "your change was applied",
        "operator_or_signal_cancelled" | "cancelled_after_model_receipt" => "cancelled",
        "source_ambiguity_requires_explicit_operator_selection" => {
            "two or more lines fit equally well, so a person has to pick one"
        }
        "repeated_identical_action_without_generation_progress" => {
            "the same step kept repeating without progress"
        }
        "domain_integrity_or_input_error" => "the drawing or spec could not be used",
        "provider_worker_not_started" => "the model request could not start",
        "provider_transmission_or_completion_unknown" => {
            "the model request ended without a known result"
        }
        "unknown_or_unsupported_candidate" => "that line cannot be chosen",
        _ => "",
    };
    if !known.is_empty() {
        return known.into();
    }
    if let Some(kind) = reason.strip_prefix("input:") {
        return format!("the spec has a problem ({})", kind.replace('_', " "));
    }
    if reason.contains(' ') {
        return reason.into();
    }
    reason.replace('_', " ")
}
