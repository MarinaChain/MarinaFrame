//! Tool-call validation and dispatch: the selection rules, draft builds
//! and the finalization of a submitted candidate.
use super::stops::{investigation_progress_key, refuse_repeated_investigation, stop};
use super::worker_call::call_worker;
use super::{finalization_point, investigation_mode, model_review, revision};
use crate::store::Store;
use crate::types::*;
use crate::util::{self, Result};
use crate::{validation, worker};
use serde_json::json;

fn known_section(store: &Store, section_id: &str) -> Result<()> {
    let sections = store.state.domain["sections"]
        .as_array()
        .ok_or("domain_sections_missing")?;
    if sections.iter().any(|s| s["id"] == section_id) {
        Ok(())
    } else {
        Err("unknown_section_id".into())
    }
}
fn validate_selection(store: &Store, operation: &Operation, actor: &str) -> Result<()> {
    if operation.is_investigation() && store.state.config.on_ambiguity != OnAmbiguity::Draft {
        return Err("investigation_requires_draft_mode".into());
    }
    let checkpoint = util::read_json(
        &util::safe_file(&store.path, "domain/state.json")?,
        32 * 1024 * 1024,
    )?;
    let policy = ["live_model", "deterministic_policy"].contains(&actor);
    match operation {
        Operation::SelectContours(x) => {
            for choice in &x.selections {
                // Selecting a guessed section resolves its guess. Only a
                // person may confirm or replace a guess, never a policy.
                if policy
                    && validation::open_guesses(&checkpoint)?
                        .iter()
                        .any(|g| g["section_id"] == choice.section_id.as_str())
                {
                    return Err("guess_requires_operator_confirmation".into());
                }
                let candidates = checkpoint["catalog"][&choice.section_id]["candidates"]
                    .as_array()
                    .ok_or("uninspected_section")?;
                if !candidates
                    .iter()
                    .any(|c| c["candidate_id"] == choice.candidate_id && c["selectable"] == true)
                {
                    return Err("unknown_or_unsupported_candidate".into());
                }
                let candidate = candidates
                    .iter()
                    .find(|c| c["candidate_id"] == choice.candidate_id)
                    .ok_or("candidate_missing")?;
                // A line the model traced is the model's choice: it enters
                // only as an open guess (assign_station), never as a policy
                // selection on the verified path.
                if policy && candidate["model_traced"] == true {
                    return Err("model_traced_candidate_requires_person".into());
                }
                if policy && candidate["non_grid_competing_components"].as_u64() != Some(0) {
                    return Err("source_ambiguity_requires_explicit_operator_selection".into());
                }
            }
        }
        Operation::AssignStation(x) => {
            known_section(store, &x.section_id)?;
            if checkpoint["selected"].get(&x.section_id).is_some() {
                return Err("section_already_selected".into());
            }
            let candidate = checkpoint["catalog"][&x.section_id]["candidates"]
                .as_array()
                .and_then(|c| {
                    c.iter()
                        .find(|c| c["candidate_id"] == x.candidate_id.as_str())
                })
                .ok_or("unsnapped_or_unknown_candidate")?;
            if !validation::snapped_candidate(candidate) {
                return Err("unsnapped_or_unknown_candidate".into());
            }
        }
        Operation::TraceCorridor(x) => known_section(store, &x.section_id)?,
        Operation::TraceFromPoint(x) => known_section(store, &x.section_id)?,
        Operation::EnumerateStrokes(x) => known_section(store, &x.section_id)?,
        Operation::CompareViews(x) => known_section(store, &x.section_id)?,
        Operation::ProposeSection(x) => known_section(store, &x.section_id)?,
        Operation::InspectSource(x) => {
            if let Some(ids) = &x.section_ids {
                let sections = store.state.domain["sections"]
                    .as_array()
                    .ok_or("domain_sections_missing")?;
                if ids
                    .iter()
                    .any(|id| !sections.iter().any(|s| s["id"] == *id))
                {
                    return Err("unknown_section_id".into());
                }
            }
        }
        _ => (),
    }
    Ok(())
}
/// With `--on-ambiguity draft`, a live-model abstention after full inspection
/// becomes a draft, the same as the deterministic policy. An abstention before
/// full inspection, or after a build exists, stays an abstention.
fn live_abstention_becomes_draft(store: &Store, actor: &str) -> bool {
    let d = &store.state.domain;
    actor == "live_model"
        && store.state.config.on_ambiguity == OnAmbiguity::Draft
        && d["catalog_ready"] == true
        && d["current_candidate"].is_null()
        && d["input_errors"].as_array().is_none_or(Vec::is_empty)
}

fn ask_to_fill_missing_once(store: &mut Store) -> Result<bool> {
    if store
        .events
        .iter()
        .any(|e| e.kind == "missing_sections_hint")
    {
        return Ok(false);
    }
    let checkpoint = validation::domain_checkpoint(&store.path)?;
    let missing = store.state.domain["sections"]
        .as_array()
        .map(|sections| {
            sections
                .iter()
                .filter(|s| {
                    let id = s["id"].as_str().unwrap_or("");
                    !checkpoint["selected"][id].is_string()
                        && !checkpoint["model_choices"][id]["candidate_id"].is_string()
                        && !checkpoint["authored_sections"][id]["candidate_id"].is_string()
                        && checkpoint["catalog"][id]["candidates"]
                            .as_array()
                            .is_none_or(|c| {
                                !c.iter()
                                    .any(|c| c["selectable"] == true && c["model_traced"] != true)
                            })
                })
                .map(|s| s["id"].clone())
                .collect::<Vec<_>>()
        })
        .unwrap_or_default();
    if missing.is_empty() {
        return Ok(false);
    }
    store.state.staged_decision = None;
    store.state.last_observation = json!({"ok":true,"status":"fill_missing_sections",
        "missing_section_ids":missing,"message":"Before building, use propose_section to fill these missing sections. This is a one-time suggestion; build_draft again to keep the current gaps.",
        "engineering_approved":false,"human_semantic_review_required":true});
    store.append("missing_sections_hint", json!({"section_ids":missing}))?;
    Ok(true)
}

/// Build a best-effort draft. When it has open guesses, the task stops at
/// `draft_not_verified`; a person resolves each guess with an operator
/// `select_contours`, and then the ordinary verified path runs. An
/// investigating model's own rebuild (`stop_when_built` false) does not stop:
/// the model inspects the draft and revises it, and its submission stops.
pub(super) fn build_draft(store: &mut Store, stop_when_built: bool) -> Result<bool> {
    if store.state.config.on_ambiguity != OnAmbiguity::Draft {
        return Err("draft_mode_disabled".into());
    }
    if !call_worker(store, "build_draft", json!({}))? {
        return Ok(false);
    }
    let checkpoint = validation::domain_checkpoint(&store.path)?;
    let guesses = validation::open_guesses(&checkpoint)?.to_vec();
    let candidate = store.state.domain["current_candidate"].clone();
    if store.state.last_observation["ok"] != true || guesses.is_empty() {
        // A failed draft build is handled like any failed build; without
        // guesses the build is an ordinary candidate on the verified path.
        return Ok(true);
    }
    if candidate["draft"] != true || candidate["valid"] != true {
        return Err("draft_candidate_contract".into());
    }
    store.append(
        "draft_built",
        json!({"status":"draft_not_verified","guesses":guesses,"candidate":candidate,
            "verified":false,"engineering_approved":false}),
    )?;
    if !stop_when_built {
        return Ok(true);
    }
    stop(
        store,
        Status::DraftNotVerified,
        "draft_built_with_open_guesses",
    )?;
    Ok(false)
}
fn live_visual_coverage(store: &Store, step_hash: &str) -> bool {
    let mut views = std::collections::BTreeSet::new();
    for event in &store.events {
        if !["provider_result", "provider_reconciled"].contains(&event.kind.as_str()) {
            continue;
        }
        let r = &event.payload["receipt"];
        if r["state"] != "completed"
            || r["evidence_mode"] != "live"
            || !r["returned_model"]
                .as_str()
                .is_some_and(|m| store.state.config.models().contains(&m))
        {
            continue;
        }
        if let Some(images) = r["images"].as_array() {
            for image in images {
                if image["pixels_attached"] == true
                    && image["generation_id"].as_str() == store.state.generation_id.as_deref()
                    && image["revision_id"].as_str() == store.state.revision_id.as_deref()
                    && image["step_sha256"] == step_hash
                {
                    if let Some(v) = image["view"].as_str() {
                        views.insert(v.to_string());
                    }
                }
            }
        }
    }
    views.contains("body") && views.contains("oblique")
}

pub fn execute_decision(store: &mut Store, choice: Decision, actor: &str) -> Result<bool> {
    let operation = choice.operation()?;
    store.verify(false)?;
    validate_selection(store, &operation, actor)?;
    let investigating = actor == "live_model" && investigation_mode(store);
    if investigating && refuse_repeated_investigation(store, &choice)? {
        return Ok(store.state.status == Status::Running);
    }
    let progress_key = if investigating && choice.tool == "build_draft" {
        Some(util::hash_json(
            &json!({"generation":store.state.generation_id}),
        )?)
    } else {
        investigating
            .then(|| investigation_progress_key(store))
            .transpose()?
    };
    let fingerprint =
        util::hash_json(&json!({"operation":operation,"generation_id":store.state.generation_id}))?;
    let repeats = store
        .state
        .action_fingerprints
        .entry(fingerprint)
        .or_default();
    *repeats += 1;
    if !investigating && *repeats > store.state.config.limits.max_repeated_action {
        stop(
            store,
            Status::NoProgress,
            "repeated_identical_action_without_generation_progress",
        )?;
        return Ok(false);
    }
    store.append(
        "decision",
        json!({"decision":choice,"actor":actor,"live_inference":actor=="live_model","progress_key":progress_key}),
    )?;
    if let Operation::RecallView(recall) = &operation {
        let known = store
            .events
            .iter()
            .any(|event| event.payload["response"]["result"]["view"]["view_id"] == recall.view_id);
        store.state.staged_decision = None;
        store.state.last_observation = if known {
            json!({"ok":true,"status":"view_recalled","recalled_view_id":recall.view_id,"engineering_approved":false,"human_semantic_review_required":true})
        } else {
            json!({"ok":false,"status":"proposal_refused","error_code":"unknown_view","message":"Recall a view_id returned by this task.","engineering_approved":false,"human_semantic_review_required":true})
        };
        store.append(
            "view_recalled",
            json!({"view_id":recall.view_id,"known":known}),
        )?;
        return Ok(true);
    }
    if let Operation::BuildDraft(_) = operation {
        if actor == "live_model" && ask_to_fill_missing_once(store)? {
            return Ok(true);
        }
        let investigating = actor == "live_model" && investigation_mode(store);
        return build_draft(store, !investigating);
    }
    if let Operation::AskPerson(ask) = &operation {
        store.state.staged_decision = None;
        store.append(
            "person_requested",
            json!({"actor":actor,"question":ask.question,"engineering_approved":false}),
        )?;
        stop(store, Status::Paused, "model_asked_person")?;
        return Ok(false);
    }
    if let Operation::Finish(finish) = &operation {
        // The investigating model submits its draft: when its latest choices
        // are not built yet, the harness builds the draft first. With open
        // guesses that build stops at draft_not_verified.
        if store.state.config.on_ambiguity == OnAmbiguity::Draft
            && finish.outcome == FinishOutcome::CandidateReadyForReview
            && store.state.domain["current_candidate"]["valid"] != true
            && store.state.domain["catalog_ready"] == true
        {
            store.state.staged_decision = None;
            store.append("submission_builds_draft", json!({"actor":actor}))?;
            return build_draft(store, true);
        }
    }
    if let Operation::Finish(finish) = operation {
        store.state.staged_decision = None;
        if finish.outcome == FinishOutcome::Abstain {
            if live_abstention_becomes_draft(store, actor) {
                store.append(
                    "abstention_replaced_by_draft",
                    json!({"actor":actor,"summary":finish.summary,"policy":"on_ambiguity_draft"}),
                )?;
                return build_draft(store, true);
            }
            stop(store, Status::Abstained, &finish.summary)?;
            return Ok(false);
        }
        // Open guesses make the task a draft: it is never validated or
        // finalized for review. `validation::ready` refuses it independently.
        if !validation::open_guesses(&validation::domain_checkpoint(&store.path)?)?.is_empty() {
            if store.state.domain["current_candidate"]["valid"] == true
                || store.state.domain["last_valid_candidate"]["valid"] == true
            {
                stop(store, Status::DraftNotVerified, "open_guesses_block_review")?;
                return Ok(false);
            }
            // A failed build's existing feedback remains actionable; do not
            // claim a delivered draft when no STEP has been made.
            return Ok(true);
        }
        if !call_worker(store, "validate_candidate", json!({}))? {
            return Ok(false);
        }
        let _domain_guard = worker::domain_guard(&store.path)?;
        store.verify(false)?;
        if worker::cancelled(&store.path) {
            stop(store, Status::Cancelled, "cancelled_before_finalization")?;
            return Ok(false);
        }
        match validation::ready(
            &store.path,
            &store.state.last_observation,
            &store.state.domain,
            &store.state.last_observation["validation_context"],
            store.state.audit_implementation_sha256.as_deref(),
        ) {
            Ok(contract) => {
                finalization_point(&store.path, "after_predicate");
                if store.state.config.policy == Policy::Live
                    && !live_visual_coverage(store, &contract.binding.step_sha256)
                {
                    store.state.last_observation = json!({"ok":false,"status":"rejected","error_code":"current_step_body_and_oblique_pixels_not_observed_by_model","engineering_approved":false,"human_semantic_review_required":true});
                    store.append("finalization_rejected",json!({"reason":"current_step_body_and_oblique_pixels_not_observed_by_model"}))?;
                    return Ok(true);
                }
                // The vision model can only add a blocking finding here; no veto changes nothing.
                if let Some(veto) = model_review::veto(store, &contract.binding.step_sha256)? {
                    store.state.last_observation = json!({"ok":false,"status":"rejected","error_code":"model_review_veto","model_review":veto,"engineering_approved":false,"human_semantic_review_required":true});
                    let status = if store.state.config.on_ambiguity == OnAmbiguity::Draft {
                        store.state.last_observation["status"] = json!("draft_warning");
                        store.state.last_observation["message"] = json!(
                            "Model review findings remain warnings on this unverified draft."
                        );
                        Status::DraftNotVerified
                    } else {
                        Status::ValidationFailed
                    };
                    stop(store, status, "model_review_veto")?;
                    return Ok(false);
                }
                store.state.status = Status::AwaitingHumanReview;
                store.state.termination_reason = Some(finish.summary);
                finalization_point(&store.path, "before_commit");
                if worker::cancelled(&store.path) {
                    stop(
                        store,
                        Status::Cancelled,
                        "cancelled_before_finalization_commit",
                    )?;
                    return Ok(false);
                }
                store.append("candidate_ready_for_human_review",json!({"validation_binding":contract.binding,"geometry_audit_passed":true,"semantic_review":"required","engineering_approved":false}))?;
                Ok(false)
            }
            Err(reason) => {
                let draft_available = store.state.config.on_ambiguity == OnAmbiguity::Draft
                    && store.state.domain["current_candidate"]["valid"] == true;
                if draft_available {
                    store.state.last_observation["warning"] = json!(reason);
                    stop(store, Status::DraftNotVerified, &reason)?;
                } else {
                    stop(store, Status::ValidationFailed, &reason)?;
                }
                Ok(false)
            }
        }
    } else {
        let mut arguments = if matches!(operation, Operation::SurveySheet(_)) {
            json!({"phase1_only":store.state.config.limits.phase1_only})
        } else {
            operation.args()
        };
        if matches!(operation, Operation::ProposeSection(_)) && revision::active(store) {
            // A person asked to revise this section: the worker's keep rule
            // first requires its own ink error not to get worse.
            arguments["revision_target"] = json!(true);
        }
        let done = call_worker(store, operation.name(), arguments)?;
        if done
            && store.state.last_observation["ok"] == false
            && store.state.last_observation["error_code"] == "domain_integrity_or_input_error"
        {
            stop(store, Status::Blocked, "domain_integrity_or_input_error")?;
            return Ok(false);
        }
        Ok(done)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::controller::catalog::tool_catalog;
    use crate::controller::deterministic::decision;
    use crate::controller::test_support::*;
    use serde_json::Value;
    #[test]
    fn recall_view_contract_accepts_ids_and_refuses_paths() {
        let (_tmp, mut store) = fixture();
        store.state.config.on_ambiguity = OnAmbiguity::Draft;
        store.state.config.binary_sha256 =
            util::file_hash(&std::env::current_exe().unwrap()).unwrap();
        store
            .append(
                "worker_result",
                json!({"response":{"result":{"view":{"view_id":"view-existing"}}}}),
            )
            .unwrap();
        // The typed operation bounds IDs before any execution.
        let valid = decision("recall_view", json!({"view_id":"view-existing"}), "recall");
        assert_eq!(valid.operation().unwrap().name(), "recall_view");
        assert!(
            decision("recall_view", json!({"view_id":"../path"}), "recall")
                .operation()
                .is_err()
        );
    }
    #[test]
    fn missing_sections_prompt_is_once_only_and_allows_next_build() {
        let (_tmp, mut store) = fixture();
        store.state.domain["sections"] = json!([{"id":"s01"}]);
        util::atomic_json(
            &store.path.join("domain/state.json"),
            &json!({"catalog":{"s01":{"candidates":[]}},"selected":{}}),
            false,
        )
        .unwrap();
        let choice = decision("build_draft", json!({}), "build");
        let progress = util::hash_json(&json!({"generation":store.state.generation_id})).unwrap();
        store
            .append(
                "decision",
                json!({"decision":choice,"actor":"live_model","progress_key":progress}),
            )
            .unwrap();
        assert!(ask_to_fill_missing_once(&mut store).unwrap());
        assert_eq!(
            store.state.last_observation["missing_section_ids"],
            json!(["s01"])
        );
        assert!(!ask_to_fill_missing_once(&mut store).unwrap());
        assert!(!refuse_repeated_investigation(&mut store, &choice).unwrap());
    }

    #[test]
    fn model_cannot_erase_a_retained_competing_stroke() {
        let (_tmp, store) = fixture();
        let operation = Operation::SelectContours(Select {
            selections: vec![Selection {
                section_id: "frame 1".into(),
                candidate_id: "contour-test".into(),
            }],
        });
        util::atomic_json(&store.path.join("domain/state.json"),&json!({"catalog":{"frame 1":{"candidates":[{"candidate_id":"contour-test","selectable":true,"non_grid_competing_components":1}]}}}),false).unwrap();
        assert_eq!(
            validate_selection(&store, &operation, "live_model").unwrap_err(),
            "source_ambiguity_requires_explicit_operator_selection"
        );
        assert!(validate_selection(&store, &operation, "deterministic_policy").is_err());
        assert!(validate_selection(&store, &operation, "assistant_operator").is_ok());
        assert!(validate_selection(&store, &operation, "human_operator").is_ok());
    }
    #[test]
    fn only_an_operator_can_resolve_an_open_guess() {
        let (_tmp, store) = fixture();
        let operation = Operation::SelectContours(Select {
            selections: vec![Selection {
                section_id: "s0".into(),
                candidate_id: "contour-test".into(),
            }],
        });
        util::atomic_json(
            &store.path.join("domain/state.json"),
            &json!({"catalog":{"s0":{"candidates":[{"candidate_id":"contour-test","selectable":true,"non_grid_competing_components":0}]}},
                "guesses":[{"section_id":"s0","chosen_candidate_id":"contour-test"}]}),
            false,
        )
        .unwrap();
        for policy in ["live_model", "deterministic_policy"] {
            assert_eq!(
                validate_selection(&store, &operation, policy).unwrap_err(),
                "guess_requires_operator_confirmation"
            );
        }
        for operator in ["human_operator", "assistant_operator"] {
            assert!(validate_selection(&store, &operation, operator).is_ok());
        }
    }

    #[test]
    fn abstain_mode_refuses_a_draft_build() {
        let (_tmp, mut store) = fixture();
        assert_eq!(
            build_draft(&mut store, true).unwrap_err(),
            "draft_mode_disabled"
        );
    }

    #[test]
    fn investigation_tools_require_draft_mode_and_are_bounded() {
        let (_tmp, store) = fixture();
        let view = Operation::ViewRegion(ViewRegion {
            region_px: [0, 0, 10, 10],
            max_side_px: None,
        });
        assert_eq!(
            validate_selection(&store, &view, "live_model").unwrap_err(),
            "investigation_requires_draft_mode"
        );
        let names = |catalog: Value| {
            catalog
                .as_array()
                .unwrap()
                .iter()
                .map(|t| t["name"].as_str().unwrap().to_string())
                .collect::<Vec<_>>()
        };
        let draft = names(tool_catalog(&OnAmbiguity::Draft));
        for tool in [
            "view_region",
            "trace_corridor",
            "assign_station",
            "ask_person",
        ] {
            assert!(draft.contains(&tool.to_string()));
            assert!(!names(tool_catalog(&OnAmbiguity::Abstain)).contains(&tool.to_string()));
        }
    }
    #[test]
    fn a_model_can_assign_only_snapped_ink() {
        let (_tmp, mut store) = fixture();
        store.state.config.on_ambiguity = OnAmbiguity::Draft;
        store.state.domain = json!({"sections":[{"id":"s0"}]});
        let snapped = json!({"candidate_id":"c","selectable":true,"source_support":{"observed_row_fraction":0.97},
            "contour_selection":{"anchors_px":[[1.0,0.0],[2.0,9.0]],"half_width_px":2.75}});
        let assign = Operation::AssignStation(AssignStation {
            section_id: "s0".into(),
            candidate_id: "c".into(),
            label_view_id: "view-1".into(),
            label_text: "0".into(),
            reason: "Label 0.".into(),
            comparison_id: None,
        });
        let write = |candidate: &Value| {
            util::atomic_json(
                &store.path.join("domain/state.json"),
                &json!({"selected":{},"catalog":{"s0":{"candidates":[candidate]}}}),
                true,
            )
            .unwrap()
        };
        write(&snapped);
        assert!(validate_selection(&store, &assign, "live_model").is_ok());
        let mut unsnapped: Vec<Value> = vec![];
        for (key, value) in [
            ("selectable", json!(false)),
            ("source_support", json!({"observed_row_fraction":0.6})),
            ("contour_selection", Value::Null),
            ("model_traced", json!(true)),
        ] {
            let mut candidate = snapped.clone();
            candidate[key] = value;
            unsnapped.push(candidate);
        }
        for candidate in unsnapped {
            write(&candidate);
            assert_eq!(
                validate_selection(&store, &assign, "live_model").unwrap_err(),
                "unsnapped_or_unknown_candidate",
                "{candidate}"
            );
        }
    }
}
