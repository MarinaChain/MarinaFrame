//! "Mark and revise": a person marks part of the drawing (a box, a lasso, a
//! station range or picked sections) and says what to fix. The controller
//! records the request as a `human_operator` action and runs a short focused
//! pass: the live model sees the instruction, a crop of the marked region and
//! the current curves of the sections in range, and answers with
//! `propose_section` edits for those sections only. The worker's keep rule
//! judges each edit (kept only when the combined fit improves). A person may
//! keep a not-kept edit anyway; that is recorded as operator-forced and never
//! as an engineering approval.
use super::{build_draft, call_worker, current_binary, execute_decision, investigation_mode, stop};
use crate::store::Store;
use crate::types::*;
use crate::util::{self, Result};
use crate::{validation, worker};
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};

pub const REQUEST_SCHEMA: &str = "marinaframe.revision_request.v1";
pub const REQUESTED_EVENT: &str = "operator_revision_requested";
pub const RESULT_EVENT: &str = "operator_revision_result";
pub const FORCED_EVENT: &str = "operator_revision_forced";

const MAX_INSTRUCTION_CHARS: usize = 500;
const MAX_TARGET_SECTIONS: usize = 12;
const MAX_LASSO_POINTS: usize = 64;
/// Largest sheet coordinate accepted, in pixels (a 600 dpi A0 sheet is ~28000 px).
const MAX_SHEET_PX: f64 = 100_000.0;
/// Most section edits in one focused pass.
const MAX_EDITS: usize = 3;
/// Model answers that are not a usable edit, allowed beyond the edits themselves.
const SPARE_ATTEMPTS: usize = 2;
/// Space around the marked region in the crop, in sheet pixels.
const CROP_MARGIN_PX: f64 = 24.0;
/// Points of each current curve shown to the model.
const CURVE_POINTS: usize = 24;

/// Where the person marked: a box or a lasso on the drawing, in sheet pixels.
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct Region {
    /// `[left, top, right, bottom]`.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub page_px_box: Option<[f64; 4]>,
    /// A closed freehand outline, `[x, y]` points.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub lasso_px: Option<Vec<[f64; 2]>>,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct RevisionRequest {
    pub schema_version: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub region: Option<Region>,
    /// `[from, to]` station positions in metres (a pick in the 3D view).
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub station_range_m: Option<[f64; 2]>,
    pub instruction: String,
    #[serde(default)]
    pub target_section_ids: Vec<String>,
}

fn valid_px(value: f64) -> bool {
    value.is_finite() && (0.0..=MAX_SHEET_PX).contains(&value)
}

impl Region {
    /// The bounding box of the mark, `[left, top, right, bottom]`.
    fn bounds(&self) -> Option<[f64; 4]> {
        if let Some(b) = self.page_px_box {
            return Some(b);
        }
        let points = self.lasso_px.as_ref()?;
        let xs = points.iter().map(|p| p[0]);
        let ys = points.iter().map(|p| p[1]);
        Some([
            xs.clone().fold(f64::INFINITY, f64::min),
            ys.clone().fold(f64::INFINITY, f64::min),
            xs.fold(f64::NEG_INFINITY, f64::max),
            ys.fold(f64::NEG_INFINITY, f64::max),
        ])
    }

    fn check(&self) -> Result<()> {
        if self.page_px_box.is_some() == self.lasso_px.is_some() {
            return Err("revision_region_needs_one_box_or_lasso".into());
        }
        if let Some([left, top, right, bottom]) = self.page_px_box {
            if ![left, top, right, bottom].into_iter().all(valid_px)
                || left >= right
                || top >= bottom
            {
                return Err("revision_region_box".into());
            }
        }
        if let Some(points) = &self.lasso_px {
            if !(3..=MAX_LASSO_POINTS).contains(&points.len())
                || !points.iter().flatten().all(|v| valid_px(*v))
            {
                return Err("revision_region_lasso".into());
            }
        }
        Ok(())
    }
}

impl RevisionRequest {
    /// Shape checks that need no task: the schema, the instruction and at least
    /// one way to say where.
    pub fn check(&self) -> Result<()> {
        if self.schema_version != REQUEST_SCHEMA {
            return Err("revision_request_schema".into());
        }
        let chars = self.instruction.trim().chars().count();
        if chars == 0
            || chars > MAX_INSTRUCTION_CHARS
            || self
                .instruction
                .chars()
                .any(|c| c.is_control() && c != '\n')
        {
            return Err("revision_instruction".into());
        }
        if self.region.is_none()
            && self.station_range_m.is_none()
            && self.target_section_ids.is_empty()
        {
            return Err("revision_needs_region_range_or_sections".into());
        }
        if let Some(region) = &self.region {
            region.check()?;
        }
        if let Some([from, to]) = self.station_range_m {
            if !from.is_finite() || !to.is_finite() || from > to {
                return Err("revision_station_range".into());
            }
        }
        let ids = &self.target_section_ids;
        if ids.len() > MAX_TARGET_SECTIONS
            || ids.iter().any(|id| !util::valid_section_id(id))
            || (1..ids.len()).any(|i| ids[..i].contains(&ids[i]))
        {
            return Err("revision_target_sections".into());
        }
        Ok(())
    }
}

/// The sections a request may edit and how many edits the pass makes. Named
/// sections and a station range are explicit: up to `MAX_EDITS` of them are
/// edited. A drawn region alone offers the sections whose panel it touches
/// (every section when it touches none) and the model edits the one it shows.
fn sections_in_range(domain: &Value, request: &RevisionRequest) -> Result<(Vec<String>, usize)> {
    let sections = domain["sections"]
        .as_array()
        .ok_or("domain_sections_missing")?;
    let id_of = |s: &Value| s["id"].as_str().map(String::from);
    for id in &request.target_section_ids {
        if !sections.iter().any(|s| s["id"] == id.as_str()) {
            return Err("unknown_section_id".into());
        }
    }
    let mut explicit = request.target_section_ids.clone();
    if let Some([from, to]) = request.station_range_m {
        for section in sections {
            let x = section["x_m"].as_f64().unwrap_or(f64::NAN);
            if (from..=to).contains(&x) {
                explicit.extend(id_of(section).filter(|id| !explicit.contains(id)));
            }
        }
    }
    if !explicit.is_empty() {
        let edits = explicit.len().min(MAX_EDITS);
        return Ok((explicit, edits));
    }
    if request.station_range_m.is_some() && request.region.is_none() {
        return Err("revision_range_has_no_sections".into());
    }
    let bounds = request
        .region
        .as_ref()
        .and_then(Region::bounds)
        .ok_or("revision_needs_region_range_or_sections")?;
    let touched = sections
        .iter()
        .filter(|s| {
            let roi = s["roi_px"]
                .as_array()
                .map(|r| r.iter().filter_map(Value::as_f64).collect::<Vec<_>>());
            roi.is_some_and(|r| {
                r.len() == 4
                    && r[0] < bounds[2]
                    && bounds[0] < r[2]
                    && r[1] < bounds[3]
                    && bounds[1] < r[3]
            })
        })
        .filter_map(id_of)
        .collect::<Vec<_>>();
    let offered = if touched.is_empty() {
        sections.iter().filter_map(id_of).collect()
    } else {
        touched
    };
    Ok((offered, 1))
}

/// The crop shown to the model: the mark with a margin, or the panels of the
/// sections in range when nothing was drawn.
fn crop_box(domain: &Value, request: &RevisionRequest, sections: &[String]) -> Option<[i64; 4]> {
    let bounds = request
        .region
        .as_ref()
        .and_then(Region::bounds)
        .or_else(|| {
            let rois = domain["sections"].as_array()?.iter().filter(|s| {
                s["id"]
                    .as_str()
                    .is_some_and(|id| sections.iter().any(|t| t == id))
            });
            rois.filter_map(|s| {
                let r = s["roi_px"].as_array()?;
                Some([
                    r.first()?.as_f64()?,
                    r.get(1)?.as_f64()?,
                    r.get(2)?.as_f64()?,
                    r.get(3)?.as_f64()?,
                ])
            })
            .reduce(|a, b| {
                [
                    a[0].min(b[0]),
                    a[1].min(b[1]),
                    a[2].max(b[2]),
                    a[3].max(b[3]),
                ]
            })
        })?;
    Some([
        (bounds[0] - CROP_MARGIN_PX).max(0.0).floor() as i64,
        (bounds[1] - CROP_MARGIN_PX).max(0.0).floor() as i64,
        (bounds[2] + CROP_MARGIN_PX).ceil() as i64,
        (bounds[3] + CROP_MARGIN_PX).ceil() as i64,
    ])
}

/// The current curve of each section in range, thinned to `CURVE_POINTS`
/// points in the order `propose_section` takes (`[height_m, half_breadth_m]`;
/// the vessel table stores `[y, z]`), with its ink fit when scored.
fn current_sections(checkpoint: &Value, sections: &[String]) -> Vec<Value> {
    let rows = checkpoint["vessel_table"]["stations"].as_array();
    sections
        .iter()
        .map(|id| {
            let row = rows.and_then(|rows| rows.iter().find(|r| r["id"] == id.as_str()));
            let points = row.and_then(|r| r["points_yz_m"].as_array()).map(|points| {
                let step = points.len().div_ceil(CURVE_POINTS).max(1);
                points
                    .iter()
                    .step_by(step)
                    .filter_map(|p| Some([p.get(1)?.as_f64()?, p.get(0)?.as_f64()?]))
                    .map(|[z, y]| {
                        json!([(z * 1000.0).round() / 1000.0, (y * 1000.0).round() / 1000.0])
                    })
                    .collect::<Vec<_>>()
            });
            json!({"section_id":id,"x_m":row.map(|r| r["x_m"].clone()),
                "current_offsets_m":points,"offsets_order":"[height_m, half_breadth_m]",
                "ink_fit":checkpoint["fit_score"]["station_ink_fit"][id.as_str()].clone()})
        })
        .collect()
}

/// What the model is told before each edit. While it is in the last
/// observation, the model is offered `propose_section` only.
fn brief(request: &RevisionRequest, remaining: &[String], current: &[Value]) -> Value {
    json!({"from":"human_operator","instruction":request.instruction,
        "region":request.region,"station_range_m":request.station_range_m,
        "sections_you_may_edit":remaining,
        "current_sections":current.iter().filter(|s| remaining.iter().any(|id| s["section_id"] == id.as_str())).collect::<Vec<_>>(),
        "what_to_do":"A person marked this part of the drawing (the newest image is a crop of it) and asked for the change above. Answer with propose_section for ONE section you may edit, following the drawn ink. Prefer form half_breadths with 5-24 [height_m, half_breadth_m] offsets that change the current shape as asked. The edit is kept only if the drawing fit improves.",
        "engineering_approved":false})
}

/// The revision context in the last observation, if a pass is running.
pub fn active(store: &Store) -> bool {
    store.state.last_observation["operator_revision"].is_object()
}

fn fit_change(before: &Value, after: &Value) -> Value {
    match (before.as_f64(), after.as_f64()) {
        (Some(b), Some(a)) => json!(((a - b) * 1e4).round() / 1e4),
        _ => Value::Null,
    }
}

/// One edit's outcome, from the worker observation that followed it.
fn edit_outcome(section_id: &str, proposal: &Value, observation: &Value) -> Value {
    let comparison = &observation["fit_comparison"];
    let kept = observation["ok"] == true && observation["status"] != "kept_previous_curve";
    json!({"section_id":section_id,"kept":kept,"status":observation["status"],
        "error_code":observation["error_code"],"reason":comparison["reason"].as_str().or(observation["message"].as_str()),
        "fit_before":comparison["fit_before"],"fit_after":comparison["fit_after"],
        "fit_change":fit_change(&comparison["fit_before"], &comparison["fit_after"]),
        "proposal":proposal})
}

fn rebuild_if_built(store: &mut Store, edited: bool) -> Result<bool> {
    let built = ["current_candidate", "last_valid_candidate"]
        .iter()
        .any(|key| store.state.domain[*key]["valid"] == true);
    if !edited || !built {
        return Ok(false);
    }
    build_draft(store, false)?;
    Ok(store.state.last_observation["ok"] == true)
}

/// End a pass: a finished draft stays a finished draft, anything else pauses.
fn end_pass(store: &mut Store, finished_draft: bool, reason: &str) -> Result<()> {
    if store.state.status != Status::Running {
        return Ok(());
    }
    store.state.last_observation["operator_revision"] = Value::Null;
    let status = if finished_draft {
        Status::DraftNotVerified
    } else {
        Status::Paused
    };
    stop(store, status, reason)
}

fn ready_for_operator_action(store: &mut Store) -> Result<()> {
    current_binary(store)?;
    store.verify(false)?;
    if !investigation_mode(store) {
        return Err("revision_requires_live_draft_run".into());
    }
    if store.state.pending.is_some() || worker::cancelled(&store.path) {
        return Err("intervention_requires_reconciled_uncancelled_state".into());
    }
    if store.state.domain_checkpoint_sha256.is_none() {
        return Err("not_built_yet".into());
    }
    Ok(())
}

/// Run one focused pass with the live model. Returns the result event payload.
pub fn revise(store: &mut Store, request: RevisionRequest) -> Result<Value> {
    revise_with(store, request, &mut super::live_decision)
}

/// `revise` with the model call passed in. `decide` stages the model's next
/// decision in `store.state.staged_decision` and returns false when the run
/// stopped (as `live_decision` does); tests pass a scripted model.
pub fn revise_with(
    store: &mut Store,
    request: RevisionRequest,
    decide: &mut dyn FnMut(&mut Store) -> Result<bool>,
) -> Result<Value> {
    request.check()?;
    ready_for_operator_action(store)?;
    let (offered, edits) = sections_in_range(&store.state.domain, &request)?;
    let finished_draft = store.state.status == Status::DraftNotVerified;
    let revision_id = format!("revision-{}", &util::nonce()[..12]);
    store.state.counters.operator_actions += 1;
    store.state.staged_decision = None;
    store.state.status = Status::Running;
    store.state.termination_reason = None;
    store.append(
        REQUESTED_EVENT,
        json!({"actor":"human_operator","revision_id":revision_id,"request":request,
            "sections":offered,"edits":edits,"engineering_approved":false}),
    )?;
    let pass = focused_pass(store, &request, offered, edits, decide);
    // Whatever happened, the model is offered all its tools again afterwards.
    store.state.last_observation["operator_revision"] = Value::Null;
    let (outcomes, rebuilt) = match pass {
        Ok(done) => done,
        Err(reason) => {
            store.append(
                RESULT_EVENT,
                json!({"revision_id":revision_id,"outcome":"stopped","error_code":reason,
                    "edits":[],"operator_forced":false,"engineering_approved":false}),
            )?;
            return Err(reason);
        }
    };
    let result = summarise(&revision_id, &request.instruction, outcomes, rebuilt);
    store.append(RESULT_EVENT, result.clone())?;
    end_pass(store, finished_draft, "operator_revision_completed")?;
    Ok(result)
}

/// Show the crop, ask the model for up to `edits` section edits in range, let
/// the worker's keep rule judge each, and rebuild the draft when one was kept.
fn focused_pass(
    store: &mut Store,
    request: &RevisionRequest,
    offered: Vec<String>,
    edits: usize,
    decide: &mut dyn FnMut(&mut Store) -> Result<bool>,
) -> Result<(Vec<Value>, bool)> {
    if let Some(region_px) = crop_box(&store.state.domain, request, &offered) {
        // The crop goes to the model with its next request (newest view first).
        let arguments = json!({"region_px":region_px,"max_side_px":1024});
        if !call_worker(store, "view_region", arguments)? {
            return Err("revision_crop_failed".into());
        }
    }
    let current = current_sections(&validation::domain_checkpoint(&store.path)?, &offered);
    let mut remaining = offered;
    let mut outcomes = vec![];
    let mut attempts = 0;
    while outcomes.len() < edits
        && attempts < edits + SPARE_ATTEMPTS
        && store.state.status == Status::Running
    {
        attempts += 1;
        store.state.last_observation["operator_revision"] = brief(request, &remaining, &current);
        if !decide(store)? {
            break;
        }
        let Some(choice) = store.state.staged_decision.clone() else {
            continue; // an unusable answer became an observation; ask again
        };
        let section = choice.arguments["section_id"]
            .as_str()
            .unwrap_or("")
            .to_string();
        let refusal = if choice.tool != "propose_section" || !remaining.contains(&section) {
            Some("revision_requires_propose_section_in_range".to_string())
        } else {
            execute_decision(store, choice.clone(), "live_model").err()
        };
        if let Some(reason) = refusal {
            store.state.staged_decision = None;
            store.state.last_observation = json!({"ok":false,"status":"proposal_refused","error_code":reason,
                "message":"Answer with propose_section for one of sections_you_may_edit.",
                "engineering_approved":false,"human_semantic_review_required":true});
            store.append(
                "operation_rejected",
                json!({"reason":reason,"actor":"live_model","decision":choice}),
            )?;
            continue;
        }
        if store.state.last_observation["ok"] != true {
            continue; // the host refused the shape; the model may try again
        }
        outcomes.push(edit_outcome(
            &section,
            &choice.arguments,
            &store.state.last_observation,
        ));
        remaining.retain(|id| id != &section);
    }
    let kept = outcomes.iter().any(|o| o["kept"] == true);
    let rebuilt = rebuild_if_built(store, kept)?;
    Ok((outcomes, rebuilt))
}

fn summarise(revision_id: &str, instruction: &str, edits: Vec<Value>, rebuilt: bool) -> Value {
    let kept = edits.iter().filter(|e| e["kept"] == true).count();
    let first = edits.iter().find_map(|e| e["fit_before"].as_f64());
    let last_kept = edits
        .iter()
        .rev()
        .filter(|e| e["kept"] == true)
        .find_map(|e| e["fit_after"].as_f64());
    let fit_after = if kept > 0 { last_kept } else { first };
    let outcome = match (kept, edits.len()) {
        (_, 0) => "no_edit",
        (k, n) if k == n => "kept",
        (0, _) => "not_kept",
        _ => "partly_kept",
    };
    // For a not-kept edit: how the proposal changed the fit (negative = worse).
    let not_kept_change = edits
        .iter()
        .find(|e| e["kept"] == false)
        .map(|e| e["fit_change"].clone());
    json!({"revision_id":revision_id,"instruction":instruction,"outcome":outcome,
        "not_kept_fit_change":not_kept_change,"kept_count":kept,"edit_count":edits.len(),"edits":edits,
        "fit_before":first,"fit_after":fit_after,"fit_change":fit_change(&json!(first), &json!(fit_after)),
        "rebuilt":rebuilt,"operator_forced":false,"engineering_approved":false})
}

/// Keep the not-kept edits of a revision anyway. The worker applies each
/// proposal without the keep rule; the ledger records it as operator-forced.
pub fn force_keep(store: &mut Store, revision_id: &str) -> Result<Value> {
    ready_for_operator_action(store)?;
    let result = store
        .events
        .iter()
        .rev()
        .find(|e| e.kind == RESULT_EVENT && e.payload["revision_id"] == revision_id)
        .map(|e| e.payload.clone())
        .ok_or("unknown_revision")?;
    if store
        .events
        .iter()
        .any(|e| e.kind == FORCED_EVENT && e.payload["revision_id"] == revision_id)
    {
        return Err("revision_already_forced".into());
    }
    let unkept = result["edits"]
        .as_array()
        .into_iter()
        .flatten()
        .filter(|e| e["kept"] == false && e["proposal"].is_object())
        .cloned()
        .collect::<Vec<_>>();
    if unkept.is_empty() {
        return Err("revision_has_no_unkept_edit".into());
    }
    let finished_draft = store.state.status == Status::DraftNotVerified;
    store.state.counters.operator_actions += 1;
    store.state.status = Status::Running;
    store.state.termination_reason = None;
    let mut forced = vec![];
    for edit in unkept {
        let mut arguments = edit["proposal"].clone();
        arguments["operator_force_keep"] = json!(true);
        if !call_worker(store, "propose_section", arguments)? {
            break;
        }
        let observation = &store.state.last_observation;
        forced.push(json!({"section_id":edit["section_id"],"applied":observation["ok"] == true,
            "fit_before":observation["fit_comparison"]["fit_before"],"fit_after":observation["fit_comparison"]["fit_after"]}));
    }
    let applied = forced.iter().any(|f| f["applied"] == true);
    let rebuilt = rebuild_if_built(store, applied)?;
    let payload = json!({"actor":"human_operator","revision_id":revision_id,"edits":forced,
        "rebuilt":rebuilt,"operator_forced":true,"engineering_approved":false});
    store.append(FORCED_EVENT, payload.clone())?;
    end_pass(store, finished_draft, "operator_revision_forced")?;
    Ok(payload)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn request(value: Value) -> Result<RevisionRequest> {
        let request: RevisionRequest =
            serde_json::from_value(value).map_err(|_| "revision_request_shape".to_string())?;
        request.check()?;
        Ok(request)
    }

    #[test]
    fn requests_need_an_instruction_and_a_place() {
        let good = [
            json!({"schema_version":REQUEST_SCHEMA,"instruction":"Too full at the bilge.","region":{"page_px_box":[10,20,200,300]}}),
            json!({"schema_version":REQUEST_SCHEMA,"instruction":"Follow ink","region":{"lasso_px":[[0,0],[50,0],[25,40]]}}),
            json!({"schema_version":REQUEST_SCHEMA,"instruction":"Smoother","station_range_m":[2.0,6.0]}),
            json!({"schema_version":REQUEST_SCHEMA,"instruction":"Wrong line","target_section_ids":["s1","s2"]}),
        ];
        for value in good {
            assert!(request(value.clone()).is_ok(), "{value}");
        }
        let bad = [
            (
                json!({"schema_version":"other","instruction":"x","target_section_ids":["s1"]}),
                "revision_request_schema",
            ),
            (
                json!({"schema_version":REQUEST_SCHEMA,"instruction":"  ","target_section_ids":["s1"]}),
                "revision_instruction",
            ),
            (
                json!({"schema_version":REQUEST_SCHEMA,"instruction":"x".repeat(501),"target_section_ids":["s1"]}),
                "revision_instruction",
            ),
            (
                json!({"schema_version":REQUEST_SCHEMA,"instruction":"Too full"}),
                "revision_needs_region_range_or_sections",
            ),
            (
                json!({"schema_version":REQUEST_SCHEMA,"instruction":"x","region":{"page_px_box":[200,20,10,300]}}),
                "revision_region_box",
            ),
            (
                json!({"schema_version":REQUEST_SCHEMA,"instruction":"x","region":{}}),
                "revision_region_needs_one_box_or_lasso",
            ),
            (
                json!({"schema_version":REQUEST_SCHEMA,"instruction":"x","region":{"lasso_px":[[0,0],[1,1]]}}),
                "revision_region_lasso",
            ),
            (
                json!({"schema_version":REQUEST_SCHEMA,"instruction":"x","station_range_m":[6.0,2.0]}),
                "revision_station_range",
            ),
            (
                json!({"schema_version":REQUEST_SCHEMA,"instruction":"x","target_section_ids":["s1","s1"]}),
                "revision_target_sections",
            ),
            (
                json!({"schema_version":REQUEST_SCHEMA,"instruction":"x","target_section_ids":["s1"],"path":"/etc"}),
                "revision_request_shape",
            ),
        ];
        for (value, code) in bad {
            assert_eq!(request(value.clone()).unwrap_err(), code, "{value}");
        }
    }

    #[test]
    fn explicit_sections_are_edited_and_a_region_offers_the_panels_it_touches() {
        let domain = json!({"sections":[
            {"id":"s0","x_m":0.0,"roi_px":[0,0,100,100]},
            {"id":"s1","x_m":2.0,"roi_px":[100,0,200,100]},
            {"id":"s2","x_m":4.0,"roi_px":[200,0,300,100]}]});
        let parse = |v: Value| request(v).unwrap();
        let named = parse(
            json!({"schema_version":REQUEST_SCHEMA,"instruction":"x","target_section_ids":["s2"],"station_range_m":[0.0,2.0]}),
        );
        assert_eq!(
            sections_in_range(&domain, &named).unwrap(),
            (vec!["s2".into(), "s0".into(), "s1".into()], 3)
        );
        let boxed = parse(
            json!({"schema_version":REQUEST_SCHEMA,"instruction":"x","region":{"page_px_box":[150,10,180,90]}}),
        );
        assert_eq!(
            sections_in_range(&domain, &boxed).unwrap(),
            (vec!["s1".into()], 1)
        );
        let outside = parse(
            json!({"schema_version":REQUEST_SCHEMA,"instruction":"x","region":{"page_px_box":[150,500,180,900]}}),
        );
        assert_eq!(sections_in_range(&domain, &outside).unwrap().0.len(), 3);
        let unknown = parse(
            json!({"schema_version":REQUEST_SCHEMA,"instruction":"x","target_section_ids":["s9"]}),
        );
        assert_eq!(
            sections_in_range(&domain, &unknown).unwrap_err(),
            "unknown_section_id"
        );
        assert_eq!(crop_box(&domain, &boxed, &[]).unwrap(), [126, 0, 204, 114]);
        assert_eq!(
            crop_box(&domain, &named, &["s1".into()]).unwrap(),
            [76, 0, 224, 124]
        );
    }

    #[test]
    fn the_summary_reports_kept_and_not_kept_fit_changes() {
        let kept = json!({"section_id":"s1","kept":true,"fit_before":0.8,"fit_after":0.83});
        let worse = json!({"section_id":"s1","kept":false,"fit_before":0.8,"fit_after":0.78});
        let result = summarise("revision-1", "x", vec![kept], false);
        assert_eq!(
            (result["outcome"].as_str(), result["fit_change"].as_f64()),
            (Some("kept"), Some(0.03))
        );
        let result = summarise("revision-1", "x", vec![worse.clone()], false);
        assert_eq!(
            (result["outcome"].as_str(), result["fit_change"].as_f64()),
            (Some("not_kept"), Some(0.0))
        );
        assert_eq!(
            edit_outcome(
                "s1",
                &json!({}),
                &json!({"ok":true,"status":"kept_previous_curve",
            "fit_comparison":{"keep":false,"fit_before":0.8,"fit_after":0.78}})
            )["fit_change"],
            -0.02
        );
        assert_eq!(result["engineering_approved"], false);
    }
}
