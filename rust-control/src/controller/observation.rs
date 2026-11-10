//! The observation that the live model receives: the task state, the
//! last tool result and the bounded recent history.
use super::investigation_mode;
use crate::store::Store;
use crate::util::{self, Result};
use serde_json::{json, Value};
use std::collections::BTreeMap;

/// The investigating model's observation: a compact task state (one line per
/// section), the last tool result and the recent history. Full evidence stays
/// in the task; the model asks for more with the tools.
pub(super) fn description_pending(store: &Store) -> bool {
    investigation_mode(store)
        && store.state.domain["description_phase"]
            .as_str()
            .is_some_and(|phase| phase != "complete")
}

/// Added to the description instructions when the spec is a sheet-only intake:
/// the harness declares the sections from this reading before the first hull.
const SHEET_ONLY_INSTRUCTIONS: &str = "This sheet came from intake with NO declared stations or calibration. The survey's intake_regions are code-measured view regions in ORIGINAL sheet pixels (label body_plan, profile, half_breadth, title_block); use their region_px boxes, corrected only where you see an error, never 0-1000 coordinates. Your reading declares the sections: the harness builds one section per station you list, on the body view and setup you give. In describe_views give the body plan its own kind (body, or body_fore/body_aft halves) and, for separate station panels, panels in reading order; give each non-body view its own family_id. In propose_sheet_setup for the body read pixels_per_metre from labelled grid lines (pixel distance between two labelled lines divided by their metre difference), and give centreline_px and baseline_px. In describe_vessel list EVERY station drawn in the body plan in order as {id, x_m, side}: x_m in metres from the aft end forward, read from the profile/plan station marks and LOA; when positions are not printed, space stations evenly over LOA and say so in a note; the hull ends (x 0 and LOA) are stations only when the body plan draws a curve for them, because the harness makes the ends from the profile outline; side 'fore' or 'aft' only for halves of an overlaid body plan. The two halves of one overlaid body plan share one centreline: describe them as one body view (or body_aft and body_fore), never as two panels. Give loa, beam and depth when readable. Missing values become labelled guesses, never a stop.";

/// Said while a sheet-only task reads the sheet again (best of N readings,
/// `first_hull_tools.READINGS`).
const SECOND_READING_NOTE: &str = "Repeat reading: the best first hull so far is built and kept as the draft. Read the sheet again as an independent check with the listed tool (describe_views, then propose_sheet_setup, then describe_vessel); the reading whose first hull fits the drawing best is kept. The earlier reading's views, setups, stations and notes are hidden on purpose: read every value again from the pixels and the title block, not from memory. Section edits (propose_section), build_draft and finish are offered again after the last reading's describe_vessel.";

/// Index of the first event that a repeat reading's observation shows: the
/// event after the one that opened the reading (its result has
/// `next_reading`). Zero when no repeat reading is open.
///
/// A repeat reading that saw the earlier reading's history, notes and
/// description copied it: 11 of 15 second readings of the Sonnet repeat
/// rounds gave the same setup, so best of two had one hull to choose from
/// (docs/HULL_SELECTION.md).
fn repeat_reading_start(store: &Store) -> usize {
    if store.state.domain["repeat_reading"] != true || !description_pending(store) {
        return 0;
    }
    store
        .events
        .iter()
        .rposition(|event| event.payload["response"]["result"]["next_reading"].is_object())
        .map_or(0, |index| index + 1)
}

/// Fields of the result that opened a repeat reading which state the earlier
/// reading's setup (stations, sections, fits); the reading must not copy them.
const EARLIER_READING_KEYS: [&str; 4] = [
    "materialized_sections",
    "candidate",
    "description",
    "warnings",
];

pub(super) fn description_instructions(phase: &Value) -> &'static str {
    match phase.as_str() {
        Some("survey") => "The harness surveys the sheet first; do not build CAD.",
        Some("views") => "Read the attached whole sheet and survey. Call describe_views with named view bounds in ORIGINAL sheet pixels from the survey sheet size, not normalized 0-1000 coordinates or resized attachment pixels. Convert visual positions using the sheet width/height. Same-scale body panels are ONE view family: name one body bounding box and optional panels with per-panel region_px/centreline_px/baseline_px. You may include shared setup pixels_per_metre/grid_spacing_m from declared calibration; otherwise one setup call serves every body panel. Include the title_block for legible dimensions. For a 2590-pixel wide sheet, the rightmost quarter is near x=1940..2590, NOT x=750..1000. The whole-sheet ruler is normalized; multiply x by sheet_width/1000 and y by sheet_height/1000. Copy title text into dimension_text only after reading a legible crop. Do not trace sections or build CAD yet.",
        Some("setups") => "Call propose_sheet_setup once for description_next_view. Use its actual crop view_id as evidence_view_id and its sheet region_px. Map body_fore/body_aft to body. Read scale, grid spacing and datums; label inferences. The result attaches the next view crop. Do not build CAD yet.",
        Some("vessel") => "Before describe_vessel, inspect the title crop. If it shows geometry or is unreadable, call read_region with subject=title_block and corrected ORIGINAL sheet-pixel region_px; do not guess text from the thumbnail. On a three-view sheet the title is normally below the body plan at right. Transcribe exact labelled lines into dimension_text, e.g. LOA ... m LWL ... m BEAM ... m DEPTH ... m DRAFT (DWL) ... m. Read digits carefully: LOA is not LWL; DRAFT is not a grid interval. Prefer printed values with source=title_block over pixel extents. Then call describe_vessel. Use the survey declared specification, measured sheet_setups and source pixels for principal dimensions, station identities/positions, waterlines, buttocks, ends, deck and form. Keep principal dimensions supplied by declared specification bounds as source=spec (including depth from declared z_max); retain measured discrepancies as warnings, not replacements. Measure beam and other undeclared dimensions from hull ink and the measured grid, not grid extents. A body-only drawing does not supply loa/lpp/draft: use {value:null,source:ai_inferred,note:not on sheet}, not invented numbers. In three-view drawings read LOA/BEAM/DEPTH/DRAFT directly from the attached title_block; keep title_block values rather than mistaking LWL for LOA. Use declared station IDs/x_m unless a clear measured correction exists. Label each dimension source (spec, title_block, measured, ai_inferred); do not confuse grid extents with hull extents. Keep doubtful fields explicit; warnings are advisory. Do not build CAD yet.",
        _ => "The vessel description is complete. The harness builds the first hull unless this is a Phase 1-only run.",
    }
}

/// Surveys can contain tile and stroke inventories. Send only a bounded sample
/// beside declared specification data; the full survey stays in the checkpoint.
fn compact_survey(value: &Value, depth: usize) -> Value {
    if depth >= 10 {
        return Value::Null;
    }
    match value {
        Value::Array(items) => Value::Array(
            items
                .iter()
                .take(300)
                .map(|v| compact_survey(v, depth + 1))
                .collect(),
        ),
        Value::Object(items) => Value::Object(
            items
                .iter()
                .filter(|(key, _)| !["artifacts", "ink_components"].contains(&key.as_str()))
                .take(32)
                .map(|(key, value)| {
                    let limit = match key.as_str() {
                        "strokes" => 6,
                        "tiles" => 32,
                        "grid_families" | "positions_px" => 128,
                        _ => 300,
                    };
                    let bounded = if let Some(items) = value.as_array() {
                        Value::Array(items.iter().take(limit).cloned().collect())
                    } else {
                        value.clone()
                    };
                    (key.clone(), compact_survey(&bounded, depth + 1))
                })
                .collect(),
        ),
        Value::String(text) => Value::String(text.chars().take(512).collect()),
        _ => value.clone(),
    }
}

/// Observation fields that change rarely within a task (on a new reading or
/// phase). They go first in the request, so that a cached prefix covers them.
const STABLE_OBSERVATION_KEYS: [&str; 9] = [
    "task_id",
    "current_policy",
    "engineering_approved",
    "source_truth",
    "notes_warning",
    "sheet_only_instructions",
    "sheet_survey",
    "described_views",
    "vessel_description",
];
/// Split an observation into its stable fields and the rest.
pub(super) fn split_stable_context(observation: &Value) -> (Value, Value) {
    let mut current = observation.clone();
    let mut stable = serde_json::Map::new();
    if let Some(object) = current.as_object_mut() {
        for key in STABLE_OBSERVATION_KEYS {
            if let Some(value) = object.remove(key) {
                stable.insert(key.into(), value);
            }
        }
    }
    (Value::Object(stable), current)
}

/// The largest arguments (JSON bytes) that one history entry repeats. Larger
/// arguments (describe_views, describe_vessel) are already in the observation
/// as described_views and vessel_description.
const HISTORY_ARGUMENTS_BYTES: usize = 800;
fn bounded_history_arguments(arguments: &Value) -> Value {
    match util::json_bytes(arguments) {
        Ok(bytes) if bytes.len() <= HISTORY_ARGUMENTS_BYTES => arguments.clone(),
        Ok(bytes) => json!(format!(
            "(omitted: {} bytes; the result is in the current observation)",
            bytes.len()
        )),
        Err(_) => Value::Null,
    }
}

fn investigation_observation(store: &Store) -> Result<Value> {
    let d = &store.state.domain;
    let guesses = d["open_guesses"]
        .as_array()
        .map(|g| {
            g.iter()
                .filter_map(|g| Some((g["section_id"].as_str()?, g)))
                .collect::<BTreeMap<_, _>>()
        })
        .unwrap_or_default();
    let sections = d["sections"].as_array().map(|s| {
        s.iter()
            .map(|s| {
                let guess = s["id"].as_str().and_then(|id| guesses.get(id));
                json!({"id":s["id"],"x_m":s["x_m"],"panel_roi_px":s["roi_px"],"inspected":s["inspected"],
                    "selected_candidate_id":s["selected_candidate_id"],
                    "catalog_available":s["catalog_available"],"inspection_failure":s["inspection_failure"],
                    "guess":guess.map(|g| json!({"kind":g["kind"],"chosen_candidate_id":g["chosen_candidate_id"]}))})
            })
            .collect::<Vec<_>>()
    });
    // Keep the latest tagged strokes of each panel across later label views.
    // Otherwise the model sees pixels but loses the candidate ids to assign.
    let mut panels = vec![];
    let mut seen_panels = std::collections::BTreeSet::new();
    for event in store.events.iter().rev() {
        let result = &event.payload["response"]["result"];
        if result["status"] == "strokes_enumerated" {
            let key = util::hash_json(&result["panel_section_ids"])?;
            if seen_panels.insert(key) {
                panels.push(json!({"panel_section_ids":result["panel_section_ids"],
                    "strokes":result["strokes"], "view":result["view"]}));
            }
        }
    }
    let candidate = &d["current_candidate"];
    // A repeat reading sees only its own events (repeat_reading_start).
    let reading_events = &store.events[repeat_reading_start(store)..];
    let history = reading_events
        .iter()
        .rev()
        .filter(|e| {
            ["decision", "operation_rejected", "model_output_rejected"].contains(&e.kind.as_str())
        })
        .take(12)
        .map(|e| {
            json!({"kind":e.kind,"tool":e.payload["decision"]["tool"],
                "arguments":bounded_history_arguments(&e.payload["decision"]["arguments"]),
                "reason":e.payload["decision"].get("reason").unwrap_or(&e.payload["reason"])})
        })
        .collect::<Vec<_>>();
    let notes = reading_events
        .iter()
        .rev()
        .filter(|event| event.kind == "decision" && event.payload["actor"] == "live_model")
        .filter_map(|event| {
            event.payload["decision"]["notes"]
                .as_str()
                .map(|claim| json!({"claim":claim,"verified":false,"source":"model_claim"}))
        })
        .take(8)
        .collect::<Vec<_>>();
    let mut value = json!({"task_id":store.state.task_id,
        "your_notes_newest_first":notes,
        "notes_warning":"Unverified model claims, not measurements or certified station identities.",
        "sections":sections,"catalog_ready":d["catalog_ready"],"selected_count":d["selected_count"],
        "open_guess_count":guesses.len(),"model_choice_section_ids":d["model_choice_section_ids"],
        "sheet_setup_ids":d["sheet_setup_ids"],"rendered_views":d["rendered_views"],
        "current_draft":if candidate.is_null(){Value::Null}else{json!({"valid":candidate["valid"],"draft":candidate["draft"],"status":candidate["status"]})},
        "last_observation":store.state.last_observation,"recent_history_newest_first":history,
        "retained_stroke_panels":panels,"omitted_stroke_panel_ids":[],
        "current_policy":"live_investigation","engineering_approved":false,
        "source_truth":"source evidence and deployment-available checks only; no evaluator references"});
    if d["description_phase"].is_string() {
        value["description_phase"] = d["description_phase"].clone();
        value["description_instructions"] =
            json!(description_instructions(&d["description_phase"]));
        if d["sheet_only"] == true && description_pending(store) {
            value["sheet_only_instructions"] = json!(SHEET_ONLY_INSTRUCTIONS);
            if d["last_valid_candidate"].is_object() {
                // Sonnet 5.5 live (round 7ac5e2b): during the second reading it
                // tried finish or propose_section, which this phase does not list.
                value["reading_note"] = json!(SECOND_READING_NOTE);
            }
        }
        let repeat_reading = repeat_reading_start(store) > 0;
        value["description_next_view"] = d["description_next_view"].clone();
        value["described_views"] = d["described_views"].clone();
        value["sheet_setups"] = json!(d["sheet_setups"].as_array().map(|setups| setups
            .iter()
            .take(32)
            .map(|setup| {
                let mut summary = serde_json::Map::new();
                for key in [
                    "view_id",
                    "view",
                    "region_px",
                    "pixels_per_metre",
                    "centreline_px",
                    "baseline_px",
                    "x_origin_px",
                    "x_direction",
                    "grid_spacing_m",
                    "datum_snaps",
                    "warnings",
                ] {
                    if let Some(value) = setup.get(key) {
                        summary.insert(key.into(), compact_survey(value, 0));
                    }
                }
                Value::Object(summary)
            })
            .collect::<Vec<_>>()));
        // The kept reading's description stays in the task state for the
        // setup comparison; a repeat reading reads the sheet without it.
        value["vessel_description"] = if repeat_reading {
            Value::Null
        } else {
            d["vessel_description"].clone()
        };
        if repeat_reading {
            if let Some(last) = value["last_observation"].as_object_mut() {
                if last.contains_key("next_reading") {
                    for key in EARLIER_READING_KEYS {
                        last.remove(key);
                    }
                }
            }
        }
        value["phase1_only"] =
            json!(store.state.config.limits.phase1_only || d["phase1_only"] == true);
        // The survey serves the reading of the views. Once the vessel is
        // described, the description and setups carry what was read from it
        // (about 11 kB of every later request in the Sonnet round 217660c).
        if description_pending(store) {
            value["sheet_survey"] = compact_survey(&d["sheet_survey"], 0);
        }
        if let Some(last) = value["last_observation"].as_object_mut() {
            for key in ["sheet_survey", "survey"] {
                if let Some(survey) = last.get_mut(key) {
                    *survey = compact_survey(survey, 0);
                }
            }
        }
    }
    // Images are attached separately. Their artifact inventories can be large;
    // omit them before reducing tool evidence such as tags and view mappings.
    if let Some(last) = value["last_observation"].as_object_mut() {
        last.remove("artifacts");
    }
    let limit = store.state.config.limits.max_observation_bytes;
    while util::json_bytes(&value)?.len() > limit
        && !value["retained_stroke_panels"]
            .as_array()
            .unwrap()
            .is_empty()
    {
        let removed = value["retained_stroke_panels"]
            .as_array_mut()
            .unwrap()
            .pop()
            .unwrap();
        value["omitted_stroke_panel_ids"]
            .as_array_mut()
            .unwrap()
            .push(removed["panel_section_ids"].clone());
    }
    if util::json_bytes(&value)?.len() > limit {
        // A large inspection result keeps its section and candidate ids only.
        let last = &store.state.last_observation;
        let reduced = last["sections"].as_array().map(|sections| {
            sections
                .iter()
                .map(|s| json!({"section_id":s["section_id"],"candidates":s["candidates"].as_array().map(|c| c.iter().map(|c| json!({"candidate_id":c["candidate_id"],"hypothesis":c["hypothesis"],"selectable":c["selectable"],"non_grid_competing_components":c["non_grid_competing_components"]})).collect::<Vec<_>>())}))
                .collect::<Vec<_>>()
        });
        value["last_observation"] = json!({"ok":last["ok"],"status":last["status"],"error_code":last["error_code"],
            "message":last["message"],"sections":reduced,"truncated_for_size":true});
    }
    if util::json_bytes(&value)?.len() > limit {
        return Err("observation_size_limit".into());
    }
    Ok(value)
}
pub(super) fn model_observation(store: &Store) -> Result<Value> {
    if investigation_mode(store) {
        return investigation_observation(store);
    }
    let history=store.events.iter().rev().filter(|e|["decision","worker_result","worker_reconciled","operator_intervention"].contains(&e.kind.as_str())).take(10).map(|e|json!({"sequence":e.sequence,"kind":e.kind,"decision":e.payload.get("decision"),"operation":e.payload.get("operation"),"status":e.payload["response"]["result"]["status"],"error_code":e.payload["response"]["result"]["error_code"]})).collect::<Vec<_>>();
    let previous_failure=store.events.iter().rev().find(|e|["provider_result","provider_reconciled"].contains(&e.kind.as_str())&&e.payload["receipt"]["state"]=="failed")
        .map(|e|json!({"request_id":e.payload["receipt"]["request_id"],"error_code":e.payload["receipt"]["error_code"],"automatic_retry":false}));
    // Source evidence is persistent task memory, not just the immediately last
    // tool result. In particular an existing-candidate continuation must retain
    // the same alternatives and endpoint witnesses shown during inspection.
    let mut source_memory = BTreeMap::<String, Value>::new();
    if !store.state.last_observation["sections"].is_array() {
        for event in store.events.iter().rev() {
            if let Some(sections) = event.payload["response"]["result"]["sections"].as_array() {
                for section in sections {
                    if let Some(id) = section["section_id"].as_str() {
                        if source_memory.len() < 12 && !source_memory.contains_key(id) {
                            source_memory.insert(id.to_string(), section.clone());
                        }
                    }
                }
            }
        }
    }
    let mut value = json!({"task_id":store.state.task_id,"domain":store.state.domain,"last_observation":store.state.last_observation,"previous_failed_provider_attempt":previous_failure,
        "retained_source_observations":source_memory.values().cloned().collect::<Vec<_>>(),"omitted_source_observation_ids":[],
        "recent_history_newest_first":history,"current_policy":"live","engineering_approved":false,"source_truth":"source evidence and deployment-available checks only; no evaluator references"});
    while util::json_bytes(&value)?.len() > store.state.config.limits.max_observation_bytes
        && !value["retained_source_observations"]
            .as_array()
            .unwrap()
            .is_empty()
    {
        let removed = value["retained_source_observations"]
            .as_array_mut()
            .unwrap()
            .pop()
            .unwrap();
        value["omitted_source_observation_ids"]
            .as_array_mut()
            .unwrap()
            .push(removed["section_id"].clone());
    }
    if util::json_bytes(&value)?.len() > store.state.config.limits.max_observation_bytes {
        return Err("observation_size_limit".into());
    }
    Ok(value)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::controller::lifecycle::sheet_only;
    use crate::controller::test_support::*;
    use crate::types::OnAmbiguity;
    #[test]
    fn recorded_decision_reason_is_visible_in_investigation() {
        let (_tmp, mut store) = fixture();
        store.append("decision", json!({"decision":{"tool":"read_region","arguments":{},"reason":"Tag 4 labels station 2"},"actor":"live_model"})).unwrap();
        let observed = investigation_observation(&store).unwrap();
        assert_eq!(
            observed["recent_history_newest_first"][0]["reason"],
            "Tag 4 labels station 2"
        );
    }
    #[test]
    fn investigation_keeps_last_eight_notes_as_unverified_claims() {
        let (_tmp, mut store) = fixture();
        for n in 0..10 {
            store.append("decision", json!({"decision":{"tool":"read_region","arguments":{},"reason":"read","notes":format!("label {n}")},"actor":"live_model"})).unwrap();
        }
        let observed = investigation_observation(&store).unwrap();
        let notes = observed["your_notes_newest_first"].as_array().unwrap();
        assert_eq!(notes.len(), 8);
        assert_eq!(notes[0]["claim"], "label 9");
        assert_eq!(notes[7]["claim"], "label 2");
        assert_eq!(notes[0]["verified"], false);
    }

    #[test]
    fn sheet_only_intake_tells_the_model_to_declare_stations() {
        let (_tmp, mut store) = fixture();
        store.state.config.on_ambiguity = OnAmbiguity::Draft;
        store.state.domain =
            json!({"description_phase":"vessel","sheet_only":true,"described_views":[]});
        let observation = investigation_observation(&store).unwrap();
        assert_eq!(
            observation["sheet_only_instructions"],
            SHEET_ONLY_INSTRUCTIONS
        );
        store.state.domain["sheet_only"] = json!(false);
        let observation = investigation_observation(&store).unwrap();
        assert!(observation.get("sheet_only_instructions").is_none());
        assert!(!sheet_only(&store));
    }

    #[test]
    fn repeat_reading_hides_the_earlier_reading() {
        let (_tmp, mut store) = fixture();
        store.state.config.on_ambiguity = OnAmbiguity::Draft;
        let decision = |tool: &str, notes: &str| json!({"actor":"live_model","decision":{"tool":tool,"arguments":{},"reason":"r","notes":notes}});
        store
            .append(
                "decision",
                decision("describe_vessel", "first reading: 10 m stations"),
            )
            .unwrap();
        store
            .append(
                "worker_result",
                json!({"response":{"result":{"ok":true,
            "next_reading":{"reading":2,"of":2}}}}),
            )
            .unwrap();
        store
            .append("decision", decision("describe_views", "second reading"))
            .unwrap();
        store.state.last_observation = json!({"ok":true,"next_reading":{"reading":2},
            "materialized_sections":[{"id":"1","x_m":10.0}],"message":"Reading 2 of 2"});
        store.state.domain = json!({"description_phase":"views","sheet_only":true,"described_views":[],
            "repeat_reading":true,"last_valid_candidate":{"valid":true},
            "vessel_description":{"stations":[{"id":"1","x_m":10.0}]}});
        let observation = investigation_observation(&store).unwrap();
        let notes = observation["your_notes_newest_first"].as_array().unwrap();
        assert_eq!(notes.len(), 1);
        assert_eq!(notes[0]["claim"], "second reading");
        assert_eq!(
            observation["recent_history_newest_first"]
                .as_array()
                .unwrap()
                .len(),
            1
        );
        assert!(observation["vessel_description"].is_null());
        assert!(observation["last_observation"]
            .get("materialized_sections")
            .is_none());
        assert_eq!(observation["last_observation"]["message"], "Reading 2 of 2");
        // Once the reading is described, the whole task is shown again.
        store.state.domain["repeat_reading"] = json!(false);
        let observation = investigation_observation(&store).unwrap();
        assert_eq!(
            observation["your_notes_newest_first"]
                .as_array()
                .unwrap()
                .len(),
            2
        );
        assert!(observation["vessel_description"].is_object());
    }

    #[test]
    fn description_observation_keeps_specification_not_large_survey_inventory() {
        let (_tmp, mut store) = fixture();
        store.state.config.on_ambiguity = OnAmbiguity::Draft;
        let survey = json!({"declared":{"units":"m","stations":[{"id":"s0","x_m":0.0}]},"tiles":vec![json!({"pixels":"x".repeat(4000)});100]});
        store.state.domain = json!({"description_phase":"views","sheet_survey":survey,"described_views":[],"vessel_description":null});
        store.state.last_observation = json!({"ok":true,"sheet_survey":survey});
        let observation = investigation_observation(&store).unwrap();
        assert_eq!(observation["sheet_survey"]["declared"]["units"], "m");
        assert_eq!(
            observation["sheet_survey"]["declared"]["stations"][0]["id"],
            "s0"
        );
        assert_eq!(
            observation["sheet_survey"]["tiles"]
                .as_array()
                .unwrap()
                .len(),
            32
        );
        assert_eq!(
            observation["last_observation"]["sheet_survey"]["tiles"]
                .as_array()
                .unwrap()
                .len(),
            32
        );
        assert!(observation["description_instructions"]
            .as_str()
            .unwrap()
            .contains("describe_views"));
        assert!(
            util::json_bytes(&observation).unwrap().len()
                < store.state.config.limits.max_observation_bytes
        );
    }

    #[test]
    fn source_witnesses_survive_later_build_observations() {
        let (_tmp, mut store) = fixture();
        let source = json!({"section_id":"s0","source_sha256":"x","candidates":[{"candidate_id":"a","endpoint_evidence":{"centroid_alternative_id":"b","source_supported":true}}]});
        store
            .append(
                "worker_result",
                json!({"response":{"result":{"sections":[source.clone()]}}}),
            )
            .unwrap();
        store.state.last_observation = json!({"ok":true,"status":"review_required"});
        let observation = model_observation(&store).unwrap();
        assert_eq!(observation["retained_source_observations"][0], source);
        assert!(observation.get("reference_geometry").is_none());
    }

    #[test]
    fn enumeration_tags_survive_a_later_label_view() {
        let (_tmp, mut store) = fixture();
        store.state.config.on_ambiguity = OnAmbiguity::Draft;
        store
            .append(
                "worker_result",
                json!({"operation":"enumerate_strokes","response":{"result":{
            "ok":true,"status":"strokes_enumerated","panel_section_ids":["s0","s1"],
            "strokes":[{"tag":1,"candidate_id":"trace-1"}],"view":{"view_id":"view-1"}}}}),
            )
            .unwrap();
        store.state.last_observation = json!({"ok":true,"status":"viewed"});
        let observed = investigation_observation(&store).unwrap();
        assert_eq!(
            observed["retained_stroke_panels"][0]["strokes"][0]["candidate_id"],
            "trace-1"
        );
    }
    #[test]
    fn old_panel_memory_cannot_exhaust_the_observation_budget() {
        let (_tmp, mut store) = fixture();
        store.state.config.on_ambiguity = OnAmbiguity::Draft;
        for i in 0..30 {
            store
                .append(
                    "worker_result",
                    json!({"response":{"result":{
                "status":"strokes_enumerated","panel_section_ids":[format!("s{i}")],
                "strokes":[{"tag":1,"candidate_id":format!("trace-{i}"),"detail":"x".repeat(4000)}],
                "view":{"view_id":format!("view-{i}")}}}}),
                )
                .unwrap();
        }
        store.state.last_observation = json!({"ok":true,"status":"viewed"});
        let observed = investigation_observation(&store).unwrap();
        assert!(
            util::json_bytes(&observed).unwrap().len()
                <= store.state.config.limits.max_observation_bytes
        );
        assert_eq!(
            observed["retained_stroke_panels"][0]["view"]["view_id"],
            "view-29"
        );
        assert!(!observed["omitted_stroke_panel_ids"]
            .as_array()
            .unwrap()
            .is_empty());
    }
    #[test]
    fn large_enumeration_preserves_tags_and_view_mapping() {
        let (_tmp, mut store) = fixture();
        store.state.config.on_ambiguity = OnAmbiguity::Draft;
        store.state.last_observation = json!({"ok":true,"status":"strokes_enumerated",
            "section_id":"s0", "strokes":[{"tag":1,"candidate_id":"trace-1"}],
            "view":{"view_id":"view-1","crop_box_px":[0,0,400,300],"view_px_per_source_px":[1,1]},
            "artifacts":[{"id":"image-1","padding":"x".repeat(100_000)}]});
        let observed = investigation_observation(&store).unwrap();
        assert_eq!(
            observed["last_observation"]["strokes"][0]["candidate_id"],
            "trace-1"
        );
        assert_eq!(observed["last_observation"]["view"]["view_id"], "view-1");
    }
}
