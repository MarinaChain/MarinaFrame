//! Plain-language timeline built from the event ledger (`events/*.json`).
//!
//! Some ledger events carry no news for a person (step started, decision staged).
//! They produce no timeline line, so sequence numbers in the result have gaps.
use crate::files;
use crate::types::{EventKind, EventView};
use serde_json::Value;
use std::collections::HashMap;
use std::path::Path;

#[cfg(test)]
mod tests;

/// What earlier events and the spec tell a later event: which sections a draft
/// guessed (with the guessed candidate) and where each section sits.
#[derive(Default)]
struct Context {
    /// Section id -> candidate the draft guessed, while the guess is open.
    guessed: HashMap<String, Option<String>>,
    x_m: HashMap<String, f64>,
}

impl Context {
    fn for_task(task: &Path) -> Self {
        let x_m = files::read_captured_spec(task)
            .and_then(|spec| {
                spec["sections"].as_array().map(|list| {
                    list.iter()
                        .filter_map(|s| Some((s["id"].as_str()?.to_string(), s["x_m"].as_f64()?)))
                        .collect()
                })
            })
            .unwrap_or_default();
        Context {
            guessed: HashMap::new(),
            x_m,
        }
    }

    /// "2.0 m" when the spec says where the section sits, None when not.
    fn station(&self, section_id: &str) -> Option<String> {
        self.x_m.get(section_id).map(|x| format!("{x:.1} m"))
    }

    /// Update the open guesses after an event.
    fn observe(&mut self, event: &Value) {
        let payload = &event["payload"];
        match event["kind"].as_str() {
            Some("draft_built") => {
                self.guessed = payload["guesses"]
                    .as_array()
                    .map(|list| {
                        list.iter()
                            .filter_map(|g| {
                                Some((
                                    g["section_id"].as_str()?.to_string(),
                                    g["chosen_candidate_id"].as_str().map(String::from),
                                ))
                            })
                            .collect()
                    })
                    .unwrap_or_default();
            }
            Some("decision") if payload["decision"]["tool"] == "select_contours" => {
                for pick in payload["decision"]["arguments"]["selections"]
                    .as_array()
                    .into_iter()
                    .flatten()
                {
                    if let Some(id) = pick["section_id"].as_str() {
                        self.guessed.remove(id);
                    }
                }
            }
            _ => {}
        }
    }
}

/// Events with a sequence number above `after_sequence`.
pub fn get_events(task: &Path, after_sequence: u64) -> Vec<EventView> {
    let listed = files::event_files(task);
    if !listed
        .iter()
        .any(|(sequence, _)| *sequence > after_sequence)
    {
        return vec![];
    }
    // Earlier events are read too: a later line can depend on a draft's guesses.
    let mut context = Context::for_task(task);
    let mut views = vec![];
    for (sequence, path) in listed {
        let Some(event) = files::read_event(&path) else {
            continue;
        };
        if sequence > after_sequence {
            if let Some((text, kind)) = describe(&event, &context) {
                views.push(EventView {
                    sequence,
                    time_ms: event["time_ms"].as_u64().unwrap_or(0),
                    text,
                    kind,
                });
            }
        }
        context.observe(&event);
    }
    views
}

/// "You confirmed the line for 4.0 m" when a person picks the guessed line of a
/// draft; "You picked another line for 4.0 m" when they pick a different one.
/// None when none of the sections was guessed.
fn describe_guess_resolution(arguments: &Value, context: &Context) -> Option<String> {
    let mut confirmed = vec![];
    let mut replaced = vec![];
    for pick in arguments["selections"].as_array()? {
        let section = pick["section_id"].as_str()?;
        let Some(guessed) = context.guessed.get(section) else {
            continue;
        };
        let Some(place) = context.station(section) else {
            continue;
        };
        if guessed.as_deref() == pick["candidate_id"].as_str() {
            confirmed.push(place);
        } else {
            replaced.push(place);
        }
    }
    let mut parts = vec![];
    if !confirmed.is_empty() {
        parts.push(format!(
            "You confirmed the line for {}",
            confirmed.join(", ")
        ));
    }
    if !replaced.is_empty() {
        parts.push(format!(
            "You picked another line for {}",
            replaced.join(", ")
        ));
    }
    (!parts.is_empty()).then(|| parts.join("; "))
}

/// Station clause for the given sections: "at 2.0 m" for one, "at 0.0 m
/// and 2.0 m" for a few, "at 12 stations" for more. None when no section
/// has a position in the spec.
fn station_clause(context: &Context, ids: Option<&Vec<Value>>) -> Option<(usize, String)> {
    let stations: Vec<String> = ids
        .into_iter()
        .flatten()
        .filter_map(|id| id.as_str().and_then(|s| context.station(s)))
        .collect();
    let count = stations.len();
    let clause = match stations.as_slice() {
        [one] => format!("at {one}"),
        [a, b] => format!("at {a} and {b}"),
        [a, b, c] => format!("at {a}, {b} and {c}"),
        list if list.len() > 3 => format!("at {} stations", list.len()),
        _ => return None,
    };
    Some((count, clause))
}

fn describe_decision(payload: &Value, context: &Context) -> Option<(String, EventKind)> {
    let decision = &payload["decision"];
    let arguments = &decision["arguments"];
    let by_person = matches!(
        payload["actor"].as_str(),
        Some("human_operator" | "assistant_operator")
    );
    let you = |plain: &str, personal: &str| if by_person { personal } else { plain }.to_string();
    match decision["tool"].as_str()? {
        "inspect_source" => Some((
            match station_clause(context, arguments["section_ids"].as_array()) {
                Some((1, clause)) => format!("Read the section {clause}"),
                Some((_, clause)) => format!("Read the sections {clause}"),
                None => "Read the next sections".into(),
            },
            EventKind::Read,
        )),
        "select_contours" => {
            let picks = arguments["selections"].as_array();
            let ids: Vec<Value> = picks
                .map(|p| p.iter().map(|s| s["section_id"].clone()).collect())
                .unwrap_or_default();
            let place = match station_clause(context, Some(&ids)) {
                Some((1, clause)) => format!("the line {clause}"),
                Some((_, clause)) => format!("lines {clause}"),
                None => "lines".to_string(),
            };
            if by_person {
                if let Some(text) = describe_guess_resolution(arguments, context) {
                    return Some((text, EventKind::Choose));
                }
            }
            let verb = if by_person { "You picked" } else { "Picked" };
            Some((format!("{verb} {place}"), EventKind::Choose))
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

fn describe(event: &Value, context: &Context) -> Option<(String, EventKind)> {
    let payload = &event["payload"];
    let status_after = event["state_after"]["status"].as_str().unwrap_or("");
    match event["kind"].as_str()? {
        "task_created" => Some(("Run created".into(), EventKind::Other)),
        "worker_stalled" | "worker_continued" => {
            Some((payload["message"].as_str()?.into(), EventKind::Other))
        }
        "calibration_corrected" => Some((payload["message"].as_str()?.into(), EventKind::Build)),
        "decision" => describe_decision(payload, context),
        "draft_built" => {
            let count = payload["guesses"].as_array().map_or(0, Vec::len);
            Some((
                format!(
                    "Built a draft: {count} section{} guessed",
                    if count == 1 { "" } else { "s" }
                ),
                EventKind::Build,
            ))
        }
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
            // The draft_built line already said so.
            "abstained" | "awaiting_human_review" | "draft_not_verified" => None,
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
        "worker_absolute_safety_cap" => "the configured worker safety time limit was reached",
        "operator_action_completed" => "your change was applied",
        "operator_revision_completed" => "your marked revision is done",
        "operator_revision_forced" => "your kept edit was applied",
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
