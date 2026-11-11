//! The task lifecycle: initialization, the run loop and resume.
use super::deterministic::{deterministic_decision, investigation_preparation};
use super::dispatch::execute_decision;
use super::investigation_mode;
use super::live::live_decision;
use super::observation::description_pending;
use super::provider_receipt::apply_provider;
use super::stops::{
    consecutive_refusals, decisions_without_progress, refusal_hint, refusal_limit, stop,
    NO_PROGRESS_DECISIONS, PROPOSAL_REFUSALS,
};
use super::worker_call::{apply_worker, call_worker, current_binary};
use crate::provider::RequestState;
use crate::store::Store;
use crate::types::*;
use crate::util::{self, Result};
use crate::{validation, worker};
use serde_json::json;

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
    // A sheet-only intake spec has no sections yet. Only the live draft model
    // reads stations and scale (phase 1); every other policy keeps the strict rule.
    if sheet_only(store) && !investigation_mode(store) {
        stop(store, Status::Blocked, "input:sheet_only_needs_live_draft")?;
        return Ok(false);
    }
    Ok(true)
}
/// The task's spec is a sheet-only intake (no declared sections before phase 1).
pub(super) fn sheet_only(store: &Store) -> bool {
    store.state.domain["sheet_only"] == true
}
/// Advance automatic description/CAD work before asking the model. An absent
/// phase key keeps old workers and stored tasks on their legacy first-hull path.
fn prepare_investigation_phase(store: &mut Store) -> Result<bool> {
    if !investigation_mode(store) {
        return Ok(true);
    }
    if store.state.domain["description_phase"] == "survey" {
        if !call_worker(
            store,
            "survey_sheet",
            json!({"phase1_only":store.state.config.limits.phase1_only}),
        )? {
            return Ok(false);
        }
        if store.state.domain["description_phase"] == "survey" {
            stop(store, Status::Blocked, "sheet_survey_did_not_advance")?;
            return Ok(false);
        }
    }
    if description_pending(store) {
        return Ok(true);
    }
    if store.state.config.limits.phase1_only || store.state.domain["phase1_only"] == true {
        let complete = store.state.domain["description_phase"] == "complete"
            && store.state.domain["vessel_description"].is_object();
        stop(
            store,
            if complete {
                Status::Paused
            } else {
                Status::Blocked
            },
            if complete {
                "phase1_description_complete"
            } else {
                "phase1_description_unavailable"
            },
        )?;
        return Ok(false);
    }
    if store.state.domain["description_phase"].is_string()
        && !store.state.domain["vessel_description"].is_object()
    {
        stop(store, Status::Blocked, "vessel_description_missing")?;
        return Ok(false);
    }
    if !store
        .events
        .iter()
        .any(|event| event.kind == "first_hull_ready")
    {
        if !call_worker(store, "build_first_hull", json!({}))? {
            return Ok(false);
        }
        store.append("first_hull_ready", json!({"engineering_approved":false}))?;
        if store.state.domain["current_candidate"]["valid"] == true
            && !call_worker(store, "render_candidate", json!({"view":"body"}))?
        {
            return Ok(false);
        }
    }
    Ok(true)
}

pub fn run_loop(store: &mut Store, max_steps: Option<u64>) -> Result<()> {
    let mut steps = 0;
    loop {
        if worker::cancelled(&store.path) {
            return stop(store, Status::Cancelled, "operator_or_signal_cancelled");
        }
        // Complete Phase 1 and its pause even when its last model call used
        // the requested step budget; never build CAD in a Phase 1-only run.
        if !prepare_investigation_phase(store)? {
            return Ok(());
        }
        if max_steps.is_some_and(|n| steps >= n) {
            return stop(store, Status::Paused, "requested_step_boundary");
        }
        store.verify(false)?;
        if investigation_mode(store) && store.state.domain["last_valid_candidate"]["valid"] == true
        {
            let edits = store.state.domain["non_improving_edits"]
                .as_u64()
                .unwrap_or(0);
            if edits >= 6 {
                if store.events.iter().any(|e| e.kind == "soft_finish_hint") {
                    return stop(
                        store,
                        Status::DraftNotVerified,
                        "best_draft_after_non_improving_edits",
                    );
                }
                store.state.last_observation["finish_hint"] = json!("Several edits did not improve the drawing fit. Finish now; the best valid draft is preserved.");
                store.append("soft_finish_hint", json!({"non_improving_edits":edits}))?;
            }
        }
        let mut actor = if store.state.config.policy == Policy::Live {
            "live_model"
        } else {
            "deterministic_policy"
        };
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
                    if let Some(prepared) = investigation_preparation(store)? {
                        store.state.staged_decision = Some(prepared);
                        store.state.counters.policy_decisions += 1;
                        store.append(
                            "harness_preparation_staged",
                            json!({"live_inference":false}),
                        )?;
                        actor = "deterministic_policy";
                    } else {
                        if investigation_mode(store)
                            && decisions_without_progress(store) >= NO_PROGRESS_DECISIONS
                        {
                            return stop(
                                store,
                                Status::NoProgress,
                                "investigation_without_progress",
                            );
                        }
                        match live_decision(store) {
                            Ok(true) => (),
                            Ok(false) => return Ok(()),
                            Err(reason)
                                if ["task_storage_limit", "configured_deployment_budget"]
                                    .contains(&reason.as_str()) =>
                            {
                                return stop(store, Status::Blocked, &reason);
                            }
                            Err(reason) => return Err(reason),
                        }
                        if store.state.staged_decision.is_none() {
                            // A refused model output became an observation.
                            steps += 1;
                            continue;
                        }
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
        match execute_decision(store, choice.clone(), actor) {
            Ok(true) => {
                store.state.last_observation["normalization_note"] = json!("Oversized notes are truncated to 600 characters; numeric investigation arguments are clamped to tool bounds.");
            }
            Ok(false) => return Ok(()),
            Err(reason)
                if actor == "live_model"
                    && investigation_mode(store)
                    && PROPOSAL_REFUSALS.contains(&reason.as_str()) =>
            {
                // A refused model proposal is an observation for the model,
                // not a stop; repeated refusals end in a no-progress stop.
                store.state.staged_decision = None;
                store.state.last_observation = json!({"ok":false,"status":"proposal_refused","error_code":reason,
                    "refused_decision":choice,"what_you_can_do":refusal_hint(&reason),
                    "engineering_approved":false,"human_semantic_review_required":true});
                if [
                    "unsnapped_or_unknown_candidate",
                    "unknown_or_unsupported_candidate",
                ]
                .contains(&reason.as_str())
                {
                    let checkpoint = validation::domain_checkpoint(&store.path)?;
                    let sid = choice.arguments["section_id"].as_str().unwrap_or("");
                    store.state.last_observation["current_candidate_catalog"] = json!({"section_id":sid,
                        "candidates":checkpoint["catalog"][sid]["candidates"].as_array().map(|candidates| candidates.iter().map(|c| json!({"candidate_id":c["candidate_id"],"hypothesis":c["hypothesis"],"selectable":c["selectable"]})).collect::<Vec<_>>()),
                        "hint":"Use one of these current IDs, or propose_section to author the section."});
                }
                store.append(
                    "operation_rejected",
                    json!({"reason":reason,"actor":actor,"decision":choice}),
                )?;
                if consecutive_refusals(store) > refusal_limit(store) {
                    return stop(store, Status::NoProgress, "repeated_refused_proposals");
                }
            }
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
            | Status::DraftNotVerified
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

#[cfg(test)]
mod tests {
    use super::*;
    use crate::controller::deterministic::decision;
    use crate::controller::observation::description_instructions;
    use crate::controller::test_support::*;
    #[test]
    fn description_phases_route_tools_before_cad_and_pause_without_worker() {
        let (_tmp, mut store) = fixture();
        store.state.config.on_ambiguity = OnAmbiguity::Draft;
        store.state.config.limits.phase1_only = true;
        store.state.domain =
            json!({"description_phase":"views","sections":[],"current_candidate":null});
        store.state.last_observation = json!({"ok":true});
        for (phase, tool, arguments) in [
            (
                "views",
                "describe_views",
                json!({"views":[{"view_id":"body","kind":"body","region_px":[0,0,100,100]}]}),
            ),
            (
                "setups",
                "propose_sheet_setup",
                json!({"view":"body","region_px":[0,0,100,100],"pixels_per_metre":10,"grid_spacing_m":1,"evidence_view_id":"crop-body","scale_claim":"grid","reason":"read grid"}),
            ),
            (
                "vessel",
                "describe_vessel",
                json!({"description":{"stations":[]}}),
            ),
        ] {
            store.state.domain["description_phase"] = json!(phase);
            let operation = decision(tool, arguments, "route").operation().unwrap();
            assert!(
                description_instructions(&store.state.domain["description_phase"])
                    .contains(operation.name())
            );
            assert!(investigation_preparation(&store).unwrap().is_none());
            assert!(prepare_investigation_phase(&mut store).unwrap());
            assert!(!store
                .events
                .iter()
                .any(|event| event.kind == "first_hull_ready"));
        }
        store.state.domain["description_phase"] = json!("complete");
        store.state.domain["vessel_description"] = json!({"principal":{}});
        run_loop(&mut store, Some(0)).unwrap();
        assert_eq!(store.state.status, Status::Paused);
        assert_eq!(
            store.state.termination_reason.as_deref(),
            Some("phase1_description_complete")
        );
        assert!(!store
            .events
            .iter()
            .any(|event| event.kind == "worker_started" || event.kind == "first_hull_ready"));
        store.state.domain = json!({});
        assert!(!description_pending(&store));
    }
}
