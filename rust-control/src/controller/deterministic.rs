//! The deterministic policy and the harness preparation of a live
//! investigation.
use super::investigation_mode;
use super::observation::description_pending;
use crate::store::Store;
use crate::types::*;
use crate::util::Result;
use crate::validation;
use serde_json::{json, Value};

/// Harness preparation of a live investigation: the deterministic inspection
/// of every section and the unique source-supported selections, exactly as
/// the deterministic draft policy makes them. No model call is spent on it.
pub(super) fn investigation_preparation(store: &Store) -> Result<Option<Decision>> {
    if !investigation_mode(store)
        || description_pending(store)
        || store.state.last_observation["ok"] == false
    {
        return Ok(None);
    }
    let d = &store.state.domain;
    if d["input_errors"].as_array().is_some_and(|a| !a.is_empty()) {
        return Ok(None);
    }
    let prepared = deterministic_decision(store)?;
    Ok(["inspect_source", "select_contours"]
        .contains(&prepared.tool.as_str())
        .then_some(prepared))
}
pub(super) fn decision(tool: &str, arguments: Value, reason: &str) -> Decision {
    Decision {
        tool: tool.into(),
        arguments,
        reason: reason.into(),
        notes: None,
    }
}
/// Inspect the next uninspected sections, named explicitly.
///
/// The Python domain inspects a CPU-bounded prefix of the named sections, so a
/// large drawing needs more calls than `max_repeated_action` allows for one
/// identical action. Naming the sections makes each call that inspects new
/// sections a different action; a call that inspects nothing new repeats the
/// same names and still stops at the repeat limit.
fn inspect_next(sections: &[Value]) -> Decision {
    let ids = sections
        .iter()
        .filter(|s| s["inspected"] != true && s["catalog_available"] != true)
        .filter_map(|s| s["id"].as_str())
        .take(12)
        .collect::<Vec<_>>();
    let arguments = if ids.is_empty() {
        json!({})
    } else {
        json!({"section_ids":ids})
    };
    decision(
        "inspect_source",
        arguments,
        "Inspect the next source regions and retain alternatives.",
    )
}
pub fn deterministic_decision(store: &Store) -> Result<Decision> {
    let d = &store.state.domain;
    let last = &store.state.last_observation;
    let abstain = |reason: &str| {
        decision(
            "finish",
            json!({"outcome":"abstain","summary":reason}),
            "Deterministic source-grammar comparison; no model inference.",
        )
    };
    if d["input_errors"].as_array().is_some_and(|a| !a.is_empty()) {
        return Ok(abstain(
            "Invalid source specification or calibration; inspect the recorded input errors.",
        ));
    }
    if last["ok"] == false {
        let code = last["error_code"]
            .as_str()
            .unwrap_or("source_or_geometry_operation_failed");
        return Ok(abstain(&format!(
            "The deterministic operation failed: {code}. Preserved evidence requires review."
        )));
    }
    let sections = d["sections"].as_array().ok_or("domain_sections_missing")?;
    let selected = sections
        .iter()
        .filter(|s| s["selected_candidate_id"].is_string())
        .filter_map(|s| s["id"].as_str())
        .collect::<std::collections::BTreeSet<_>>();
    if store.state.config.on_ambiguity == OnAmbiguity::Draft {
        return deterministic_draft_mode(store, sections, &selected);
    }
    let inspected = last["sections"]
        .as_array()
        .or(d["inspected_sections"].as_array());
    let mut selections = vec![];
    if let Some(items) = inspected {
        for s in items {
            let id = s["section_id"]
                .as_str()
                .ok_or("inspected_section_identity")?;
            if selected.contains(id) {
                continue;
            }
            let candidates = s["candidates"]
                .as_array()
                .ok_or("candidate_inventory")?
                .iter()
                .filter(|c| c["selectable"] == true)
                .collect::<Vec<_>>();
            let chosen = s["grid_evidence"]["unique_non_grid_candidate_id"]
                .as_str()
                .or_else(|| {
                    if candidates.len() == 1 {
                        candidates[0]["candidate_id"].as_str()
                    } else {
                        None
                    }
                });
            let Some(chosen) = chosen else {
                return Ok(abstain("The source has multiple or no supported contour interpretations. An explicit source-backed selection is required."));
            };
            selections.push(json!({"section_id":id,"candidate_id":chosen}));
        }
    }
    if !selections.is_empty() {
        return Ok(decision(
            "select_contours",
            json!({"selections":selections}),
            "Unique source-grammar hypothesis; semantic identity remains unapproved.",
        ));
    }
    if d["catalog_ready"] != true {
        return Ok(inspect_next(sections));
    }
    if selected.len() < sections.len() {
        let ids = sections
            .iter()
            .filter_map(|s| s["id"].as_str())
            .filter(|id| !selected.contains(id))
            .take(12)
            .collect::<Vec<_>>();
        return Ok(decision(
            "inspect_source",
            json!({"section_ids":ids}),
            "Inspect the remaining unselected sections.",
        ));
    }
    deterministic_build_to_finish(store)
}

/// The unique supported candidate of one inspected section, if any: the grid
/// grammar's unique proposal or the only selectable candidate. With `strict`,
/// the candidate must also have no non-grid competitor, which is what
/// `validate_selection` requires from a policy.
fn unique_choice(section: &Value, strict: bool) -> Option<&str> {
    let selectable = section["candidates"]
        .as_array()?
        .iter()
        .filter(|c| c["selectable"] == true)
        .collect::<Vec<_>>();
    let chosen = section["grid_evidence"]["unique_non_grid_candidate_id"]
        .as_str()
        .or_else(|| match selectable.as_slice() {
            [only] => only["candidate_id"].as_str(),
            _ => None,
        })?;
    if strict {
        let candidate = selectable.iter().find(|c| c["candidate_id"] == chosen)?;
        if candidate["non_grid_competing_components"].as_u64() != Some(0) {
            return None;
        }
    }
    Some(chosen)
}

/// Deterministic policy with `--on-ambiguity draft`. Unique supported lines are
/// selected exactly as in abstain mode. A section without one is not a reason
/// to stop: after full inspection, the policy asks for a draft, which records
/// each remaining choice as an open guess. Sections with an open guess are left
/// to a person. Once every section is selected, the ordinary verified path runs.
fn deterministic_draft_mode(
    store: &Store,
    sections: &[Value],
    selected: &std::collections::BTreeSet<&str>,
) -> Result<Decision> {
    let d = &store.state.domain;
    let guessed = d["open_guesses"]
        .as_array()
        .map(|guesses| {
            guesses
                .iter()
                .filter_map(|g| g["section_id"].as_str())
                .collect::<std::collections::BTreeSet<_>>()
        })
        .unwrap_or_default();
    let catalog_ready = d["catalog_ready"] == true;
    // After full inspection, read every section from the checkpoint catalog:
    // the domain description lists at most 12 inspected sections.
    let checkpoint = if catalog_ready {
        Some(validation::domain_checkpoint(&store.path)?)
    } else {
        None
    };
    let inspected: Vec<&Value> = match &checkpoint {
        Some(checkpoint) => sections
            .iter()
            .filter_map(|s| s["id"].as_str())
            .filter_map(|id| checkpoint["catalog"].get(id))
            .collect(),
        None => store.state.last_observation["sections"]
            .as_array()
            .or(d["inspected_sections"].as_array())
            .map(|items| items.iter().collect())
            .unwrap_or_default(),
    };
    let mut selections = vec![];
    for section in inspected {
        let id = section["section_id"]
            .as_str()
            .ok_or("inspected_section_identity")?;
        if selected.contains(id) || guessed.contains(id) {
            continue;
        }
        if let Some(chosen) = unique_choice(section, true) {
            selections.push(json!({"section_id":id,"candidate_id":chosen}));
        }
    }
    if !selections.is_empty() {
        return Ok(decision(
            "select_contours",
            json!({"selections":selections}),
            "Unique source-grammar hypothesis; semantic identity remains unapproved.",
        ));
    }
    if !catalog_ready {
        return Ok(inspect_next(sections));
    }
    if selected.len() < sections.len() {
        return Ok(decision(
            "build_draft",
            json!({}),
            "Some sections have no unique supported line; build a draft that records each choice as an open guess.",
        ));
    }
    deterministic_build_to_finish(store)
}

/// The verified path after every section is selected: build, render, validate,
/// finish. It is the same for both ambiguity policies.
fn deterministic_build_to_finish(store: &Store) -> Result<Decision> {
    let d = &store.state.domain;
    let abstain = |reason: &str| {
        decision(
            "finish",
            json!({"outcome":"abstain","summary":reason}),
            "Deterministic source-grammar comparison; no model inference.",
        )
    };
    if d["current_candidate"].is_null() {
        return Ok(decision(
            "build_provisional",
            json!({}),
            "Build the selected source traces with the trusted engine.",
        ));
    }
    if d["current_candidate"]["valid"] != true {
        return Ok(abstain("The current native build failed; the failure and any older candidate remain available for diagnosis."));
    }
    let rendered = d["rendered_views"].as_array().cloned().unwrap_or_default();
    for view in ["body", "oblique"] {
        if !rendered.iter().any(|v| v == view) {
            return Ok(decision(
                "render_candidate",
                json!({"view":view}),
                "Inspect a view reimported from the actual exported STEP.",
            ));
        }
    }
    if d["validation"].is_null() {
        return Ok(decision(
            "validate_candidate",
            json!({}),
            "Perform the current deterministic STEP and selected-source audit.",
        ));
    }
    Ok(decision(
        "finish",
        json!({"outcome":if d["validation"]["geometry_checks_passed"]==true{"candidate_ready_for_review"}else{"abstain"},"summary":"Deterministic sequence completed. All semantic and professional review remains outstanding."}),
        "Apply the authoritative current-candidate finalization predicate.",
    ))
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn inspect_next_names_the_next_uninspected_sections() {
        // 59 sections inspected 5 per call (Gunnerus) need 12 calls; each call
        // names other sections, so it is not one action repeated 12 times.
        let mut sections = (0..59)
            .map(|i| json!({"id":format!("s{i}"),"inspected":false}))
            .collect::<Vec<_>>();
        let first = inspect_next(&sections);
        assert_eq!(first.arguments["section_ids"][0], "s0");
        assert_eq!(first.arguments["section_ids"].as_array().unwrap().len(), 12);
        for section in sections.iter_mut().take(5) {
            section["inspected"] = json!(true);
        }
        let second = inspect_next(&sections);
        assert_eq!(second.arguments["section_ids"][0], "s5");
        assert_ne!(first.arguments, second.arguments);
        for section in sections.iter_mut() {
            section["inspected"] = json!(true);
        }
        assert_eq!(inspect_next(&sections).arguments, json!({}));
    }
}
