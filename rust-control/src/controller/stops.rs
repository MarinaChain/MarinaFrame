//! Task stops and the no-progress guards: refusal counting, the repeat
//! guard of the investigating model and the hints for refused proposals.
use crate::store::Store;
use crate::types::*;
use crate::util::{self, Result};
use serde_json::json;

pub(super) fn stop(store: &mut Store, status: Status, reason: &str) -> Result<()> {
    stop_with_message(store, status, reason, None)
}

pub(super) fn stop_with_message(
    store: &mut Store,
    status: Status,
    reason: &str,
    message: Option<&str>,
) -> Result<()> {
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
    store.state.termination_reason = Some(message.unwrap_or(reason).into());
    store.append(
        "task_terminated",
        json!({"reason":reason,"message":message,"engineering_approved":false}),
    )
}

/// Refused proposals and refused outputs since the model's last accepted action.
pub(super) fn consecutive_refusals(store: &Store) -> u64 {
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
pub(super) fn refusal_limit(store: &Store) -> u64 {
    2 * store.state.config.limits.max_repeated_action
}
/// Model decisions allowed without progress. Progress is a change of the
/// generation (an assignment or a selection) or a build. This is a
/// no-progress stop, not an aggregate cap: any number of decisions is allowed
/// while the model makes progress.
pub(super) const NO_PROGRESS_DECISIONS: usize = 40;
pub(super) fn decisions_without_progress(store: &Store) -> usize {
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
pub(super) const PROPOSAL_REFUSALS: [&str; 13] = [
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
pub(super) fn refusal_hint(code: &str) -> &'static str {
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

/// Evidence changes, unlike new crops, permit a previously used action again.
pub(super) fn investigation_progress_key(store: &Store) -> Result<String> {
    let domain = &store.state.domain;
    util::hash_json(&json!({"generation":store.state.generation_id,
        "revision":store.state.revision_id,"sections":domain["sections"],
        "catalog":domain["inspected_sections"],"guesses":domain["open_guesses"],
        "setups":domain["sheet_setup_ids"],"candidate":domain["current_candidate"],
        "description_phase":domain["description_phase"],"described_views":domain["described_views"],
        "description_next_view":domain["description_next_view"],"vessel_description":domain["vessel_description"]}))
}

pub(super) fn refuse_repeated_investigation(store: &mut Store, choice: &Decision) -> Result<bool> {
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

#[cfg(test)]
mod tests {
    use super::*;
    use crate::controller::deterministic::decision;
    use crate::controller::test_support::*;
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
}
