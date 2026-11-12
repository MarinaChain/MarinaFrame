//! Whole-vessel parts of a run (APP_SPEC "Whole-vessel parts"). The ship-cad worker writes
//! `<task>/whole_vessel/execution.json` (`src/vessel_reconstruction/ship_cad.py`); each entry of
//! `result.components` becomes one `ComponentView`. The person's review of a part is kept in
//! the run folder (`review/part_reviews.json`), apart from the controller's records, so it
//! moves with the run when the folder is copied.
use crate::error::{AppError, AppResult};
use crate::storage::{self, AppPaths};
use crate::types::{
    ComponentArgument, ComponentBox, ComponentChange, ComponentView, PartDisplay, WholeVesselModel,
};
use serde_json::Value;
use std::collections::{BTreeMap, HashMap};
use std::path::Path;

/// The ship-cad worker output inside a task folder.
pub const EXECUTION_FILE: &str = "whole_vessel/execution.json";
const EXECUTION_MAX_BYTES: usize = 8 * 1024 * 1024;
const REVIEWS_FILE: &str = "part_reviews.json";
/// The run's folder for a person's records (part reviews). The controller never writes here.
pub const RUN_REVIEWS_FOLDER: &str = "review";
/// Largest reviews file read (a few hundred parts with 500-character notes).
const RUN_REVIEWS_MAX_BYTES: usize = 1024 * 1024;
/// Review decisions a person can save.
pub const DECISIONS: [&str; 3] = ["accepted", "marked", "open"];
/// Longest note of a marked part (the same limit as a Mark and revise instruction).
pub const MAX_NOTE_CHARS: usize = 500;

/// "house_t1" -> "House t1": a plain label from a ship-cad id.
fn label_of(id: &str) -> String {
    let words = id.replace(['_', '-'], " ");
    let mut chars = words.trim().chars();
    match chars.next() {
        Some(first) => first.to_uppercase().chain(chars).collect(),
        None => id.to_string(),
    }
}

/// A short text for a ship-cad argument value: a number in metres, a range, or a polygon's
/// point count with its extent (so a changed outline shows what changed).
fn value_text(value: &Value) -> Option<String> {
    match value {
        Value::Number(n) => n.as_f64().map(|v| format!("{v:.3} m")),
        Value::Array(items) if items.len() == 2 && items.iter().all(Value::is_number) => {
            let a = items[0].as_f64()?;
            let b = items[1].as_f64()?;
            Some(format!("{a:.3} to {b:.3} m"))
        }
        Value::Array(items) if items.iter().all(Value::is_array) => {
            Some(match polygon_extent(items) {
                Some([a0, a1, b0, b1]) => format!(
                    "{} points, {a0:.2} to {a1:.2} m by {b0:.2} to {b1:.2} m",
                    items.len()
                ),
                None => format!("{} points", items.len()),
            })
        }
        Value::String(text) => Some(text.clone()),
        _ => None,
    }
}

/// [first low, first high, second low, second high] of [[a, b], ...] points (x and y for a
/// plan outline, x and z for an appendage), or None when a point is not two numbers.
fn polygon_extent(points: &[Value]) -> Option<[f64; 4]> {
    let mut extent = [
        f64::INFINITY,
        f64::NEG_INFINITY,
        f64::INFINITY,
        f64::NEG_INFINITY,
    ];
    for point in points {
        let pair = point.as_array().filter(|p| p.len() == 2)?;
        let (a, b) = (pair[0].as_f64()?, pair[1].as_f64()?);
        extent = [
            extent[0].min(a),
            extent[1].max(a),
            extent[2].min(b),
            extent[3].max(b),
        ];
    }
    (!points.is_empty()).then_some(extent)
}

fn point(value: &Value) -> Option<[f64; 3]> {
    let items = value.as_array()?;
    if items.len() != 3 {
        return None;
    }
    Some([items[0].as_f64()?, items[1].as_f64()?, items[2].as_f64()?])
}

/// The evidence of one argument. ship-cad keys `provenance` by the argument for a value given
/// inline and by the measurement or guess name otherwise; the worker names those
/// `<region>_<argument>` (`benchmarks/gunnerus/whole_vessel.py`), so a unique key ending in
/// `_<argument>` is that argument's record.
fn provenance_of<'a>(entry: &'a Value, argument: &str) -> Option<&'a Value> {
    let provenance = entry["provenance"].as_object()?;
    if let Some(record) = provenance.get(argument) {
        return Some(record);
    }
    let suffix = format!("_{argument}");
    let mut matches = provenance.iter().filter(|(key, _)| key.ends_with(&suffix));
    match (matches.next(), matches.next()) {
        (Some((_, record)), None) => Some(record),
        _ => None,
    }
}

fn argument_view(entry: &Value, name: &str, source: &str) -> Option<ComponentArgument> {
    let record = provenance_of(entry, name);
    let value = value_text(&entry["geometry"][name])
        .or_else(|| record.and_then(|r| value_text(&r["value"])));
    // A guess or an inline value says why; a measurement says where it was read.
    let basis = record
        .and_then(|r| r["basis"].as_str().map(String::from))
        .or_else(|| {
            let r = record?;
            let view = r["view"].as_str()?;
            let method = r["method"].as_str().unwrap_or("").replace('_', " ");
            Some(if method.is_empty() {
                format!("Read from the {view}")
            } else {
                format!("Read from the {view} ({method})")
            })
        });
    Some(ComponentArgument {
        name: name.to_string(),
        value,
        source: source.to_string(),
        basis,
    })
}

fn arguments_of(entry: &Value) -> Vec<ComponentArgument> {
    entry["source_labels"]
        .as_object()
        .map(|labels| {
            labels
                .iter()
                .filter_map(|(name, label)| argument_view(entry, name, label.as_str()?))
                .collect()
        })
        .unwrap_or_default()
}

fn volume_text(entry: &Value) -> Option<String> {
    entry["volume_m3"].as_f64().map(|v| format!("{v:.2} m³"))
}

/// What the last re-run from a mark changed: the entry against the previous one
/// (`revision_history`, written by `vessel_reconstruction.part_revise`). Values that did not
/// change are left out; the volume is the last row.
fn changes_of(entry: &Value, arguments: &[ComponentArgument]) -> Vec<ComponentChange> {
    let Some(previous) = entry["revision_history"].as_array().and_then(|h| h.last()) else {
        return vec![];
    };
    let before = arguments_of(previous);
    let mut names: Vec<&str> = before.iter().map(|a| a.name.as_str()).collect();
    for argument in arguments {
        if !names.contains(&argument.name.as_str()) {
            names.push(&argument.name);
        }
    }
    let find = |list: &[ComponentArgument], name: &str| -> (Option<String>, Option<String>) {
        list.iter()
            .find(|a| a.name == name)
            .map(|a| (a.value.clone(), Some(a.source.clone())))
            .unwrap_or_default()
    };
    let mut changes: Vec<ComponentChange> = names
        .into_iter()
        .filter_map(|name| {
            let (before, before_source) = find(&before, name);
            let (after, after_source) = find(arguments, name);
            (before != after || before_source != after_source).then(|| ComponentChange {
                name: name.to_string(),
                before,
                after,
                before_source,
                after_source,
            })
        })
        .collect();
    let (before, after) = (volume_text(previous), volume_text(entry));
    if before != after {
        changes.push(ComponentChange {
            name: "volume".into(),
            before,
            after,
            before_source: None,
            after_source: None,
        });
    }
    changes
}

/// True when the entry keeps the previous revision (needed for Undo).
fn has_previous(entry: &Value) -> bool {
    entry["revision_history"]
        .as_array()
        .is_some_and(|history| !history.is_empty())
}

/// Most points of one sketch polygon the app accepts (a tank outline has a few hundred).
const MAX_OUTLINE_POINTS: usize = 4000;

/// Polygons [[a, b], ...] of the worker's `display` entry; a polygon with a point that is not two
/// finite numbers, or with too few or too many points, is left out.
fn polygons(value: &Value) -> Vec<Vec<[f64; 2]>> {
    let Some(items) = value.as_array() else {
        return vec![];
    };
    items
        .iter()
        .filter_map(|polygon| {
            let points = polygon.as_array()?;
            if points.len() < 3 || points.len() > MAX_OUTLINE_POINTS {
                return None;
            }
            points
                .iter()
                .map(|point| {
                    let pair = point.as_array().filter(|p| p.len() == 2)?;
                    let (a, b) = (pair[0].as_f64()?, pair[1].as_f64()?);
                    (a.is_finite() && b.is_finite()).then_some([a, b])
                })
                .collect()
        })
        .collect()
}

/// The sketch outlines of a built part, or None when the worker wrote none.
fn display_of(entry: &Value, built: bool) -> Option<PartDisplay> {
    let display = entry.get("display").filter(|d| d.is_object() && built)?;
    let view = PartDisplay {
        profile_m: polygons(&display["profile_m"]),
        plan_m: polygons(&display["plan_m"]),
        content_class: display["content_class"].as_str().map(String::from),
    };
    (!view.profile_m.is_empty() || !view.plan_m.is_empty()).then_some(view)
}

fn component_view(entry: &Value, reviews: &HashMap<String, PartReview>) -> Option<ComponentView> {
    let id = entry["id"].as_str()?.to_string();
    let built = entry["built"].as_bool().unwrap_or(false);
    let arguments = arguments_of(entry);
    let revision = entry["revision"]
        .as_u64()
        .and_then(|r| u32::try_from(r).ok())
        .unwrap_or(0);
    let changes = if revision > 0 {
        changes_of(entry, &arguments)
    } else {
        vec![]
    };
    let bbox_m = match (
        point(&entry["bbox_m"]["min"]),
        point(&entry["bbox_m"]["max"]),
    ) {
        (Some(min), Some(max)) if built => Some(ComponentBox { min, max }),
        _ => None,
    };
    Some(ComponentView {
        // The worker may give a label ("Deckhouse tier 1"); else one is made from the id.
        label: entry["label"]
            .as_str()
            .map(String::from)
            .unwrap_or_else(|| label_of(&id)),
        op: entry["op"].as_str().unwrap_or("other").to_string(),
        status: entry["status"]
            .as_str()
            .unwrap_or("draft_guess")
            .to_string(),
        built,
        reason: entry["reason"].as_str().unwrap_or("").to_string(),
        view: entry["source"]["view"].as_str().map(String::from),
        bbox_m,
        volume_m3: entry["volume_m3"].as_f64().filter(|_| built),
        step_path: built.then(|| format!("whole_vessel/{id}.step")),
        arguments,
        review: reviews
            .get(&id)
            .map(|r| r.decision.clone())
            .unwrap_or_else(|| "open".into()),
        review_note: reviews.get(&id).and_then(|r| r.note.clone()),
        revision,
        revision_note: entry["revision_note"].as_str().map(String::from),
        revision_pending: revision > 0
            && !entry["revision_kept"].as_bool().unwrap_or(false)
            && has_previous(entry),
        changes,
        display: display_of(entry, built),
        source_record: crate::source_record::checked(&entry["source_record"]),
        id,
    })
}

/// Where a whole-vessel run puts its tessellated model (one node per part, named by id).
pub const WHOLE_VESSEL_GLB: [&str; 2] = [
    "whole-vessel-draft.glb",
    "whole_vessel/whole-vessel-draft.glb",
];

/// The whole-vessel GLB of a run, if there is one: its path, size and whether the app can
/// load it. STEP files are never loaded into the 3D view (a hull STEP can be 150 MB); a GLB
/// above `artifact::MAX_GLB_BYTES` is listed but not loaded, and the UI says so.
pub fn whole_vessel_model(task: &Path) -> Option<WholeVesselModel> {
    WHOLE_VESSEL_GLB.iter().find_map(|relative| {
        let meta = std::fs::symlink_metadata(task.join(relative)).ok()?;
        if !meta.is_file() {
            return None;
        }
        Some(WholeVesselModel {
            glb_path: (*relative).to_string(),
            bytes: meta.len(),
            loadable: meta.len() <= crate::artifact::MAX_GLB_BYTES as u64,
        })
    })
}

/// The parts of a run, or None when the run has no whole-vessel output.
pub fn read_components(
    task: &Path,
    reviews: &HashMap<String, PartReview>,
) -> Option<Vec<ComponentView>> {
    let bytes =
        marinaframe_control::util::read_bounded(&task.join(EXECUTION_FILE), EXECUTION_MAX_BYTES)
            .ok()?;
    let execution: Value = serde_json::from_slice(&bytes).ok()?;
    let entries = execution["result"]["components"].as_array()?;
    let added_sheets = crate::sources::added_sheet_entries(task);
    let mut refreshed = crate::source_record::run_records(task, "components");
    Some(
        entries
            .iter()
            .filter_map(|entry| component_view(entry, reviews))
            .map(|mut part| {
                if part.source_record.is_none() {
                    part.source_record = refreshed.remove(&part.id);
                }
                if let Some(record) = part.source_record.as_mut() {
                    place_on_added_sheets(record, &part.id, &added_sheets);
                }
                part
            })
            .collect(),
    )
}

/// Give the regions of a part's record that lie on an added sheet (`sources::ADDED_SHEETS_FILE`)
/// that sheet's page size, and on its `part_boxes.view` the part's box in pixels, when the
/// record has no box of its own. A record from a stage that read the DXF names the sheet but
/// no pixels; the added sheet is its picture.
fn place_on_added_sheets(record: &mut Value, part_id: &str, sheets: &[Value]) {
    for key in ["regions", "inputs"] {
        let Some(regions) = record[key].as_array_mut() else {
            continue;
        };
        for region in regions.iter_mut().filter(|r| r["box_px"].is_null()) {
            let Some(sheet) = sheets.iter().find(|s| s["name"] == region["sheet"]) else {
                continue;
            };
            let (Some(width), Some(height)) =
                (sheet["width_px"].as_u64(), sheet["height_px"].as_u64())
            else {
                continue;
            };
            region["page_px"] = serde_json::json!([width, height]);
            let boxes = &sheet["part_boxes"];
            let part_box = &boxes["boxes"][part_id];
            let is_box = part_box
                .as_array()
                .is_some_and(|items| items.len() == 4 && items.iter().all(Value::is_number));
            if is_box && boxes["view"] == region["view"] {
                region["box_px"] = part_box.clone();
            }
        }
    }
}

/// A person's review of one part. "marked" carries what the person wants changed.
#[derive(Clone, Debug, Default, PartialEq, Eq, serde::Serialize, serde::Deserialize)]
pub struct PartReview {
    pub decision: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub note: Option<String>,
}

type TaskReviews = BTreeMap<String, PartReview>;
/// The app config file of earlier versions: task folder path -> reviews.
type LegacyReviews = BTreeMap<String, TaskReviews>;

fn legacy_reviews(paths: &AppPaths) -> LegacyReviews {
    storage::read_config_json(paths, REVIEWS_FILE).unwrap_or_default()
}

fn legacy_key(task: &Path) -> String {
    task.to_string_lossy().into_owned()
}

/// The reviews file inside the run folder, or None when the record folder is a symlink.
fn run_reviews_path(task: &Path) -> Option<std::path::PathBuf> {
    let folder = task.join(RUN_REVIEWS_FOLDER);
    let linked = std::fs::symlink_metadata(&folder).is_ok_and(|m| m.file_type().is_symlink());
    (!linked).then(|| folder.join(REVIEWS_FILE))
}

/// The reviews saved in the run folder, or None when the run has no reviews file.
fn run_reviews(task: &Path) -> Option<TaskReviews> {
    let bytes =
        marinaframe_control::util::read_bounded(&run_reviews_path(task)?, RUN_REVIEWS_MAX_BYTES)
            .ok()?;
    serde_json::from_slice(&bytes).ok()
}

fn task_reviews(paths: &AppPaths, task: &Path) -> TaskReviews {
    // Re-export can add an empty portable record. Keep legacy decisions until
    // they are migrated by save_reviews; portable decisions win for the same id.
    let mut reviews = legacy_reviews(paths)
        .remove(&legacy_key(task))
        .unwrap_or_default();
    reviews.extend(run_reviews(task).unwrap_or_default());
    reviews
}

/// The saved reviews of one task: component id -> review. They are kept in the run folder
/// (`review/part_reviews.json`), so they move with a copied run. A run reviewed by an earlier
/// version has them in the app config, keyed by the run folder's path; they are read from
/// there until the next review moves them into the run.
pub fn reviews_of(paths: &AppPaths, task: &Path) -> HashMap<String, PartReview> {
    task_reviews(paths, task).into_iter().collect()
}

/// Write the reviews into the run folder, then drop the task's entry from the app config.
/// The config entry goes only after the run file is written, so no review is lost.
fn save_reviews(paths: &AppPaths, task: &Path, reviews: &TaskReviews) -> AppResult<()> {
    let not_saved = || AppError::new("review_write", "The review could not be saved.");
    let path = run_reviews_path(task).ok_or_else(not_saved)?;
    std::fs::create_dir_all(task.join(RUN_REVIEWS_FOLDER)).map_err(|_| not_saved())?;
    marinaframe_control::util::atomic_json(&path, reviews, true).map_err(|_| not_saved())?;
    let mut legacy = legacy_reviews(paths);
    if legacy.remove(&legacy_key(task)).is_some() {
        storage::write_config_json(paths, REVIEWS_FILE, &legacy)?;
    }
    Ok(())
}

/// Save a person's review of one part. "marked" needs a note (what to change, 1 to
/// `MAX_NOTE_CHARS` characters); the other decisions drop any note.
pub fn review_component(
    paths: &AppPaths,
    task: &Path,
    component_id: &str,
    decision: &str,
    note: Option<&str>,
) -> AppResult<()> {
    if !DECISIONS.contains(&decision) {
        return Err(AppError::new("review_decision", "Unknown review decision."));
    }
    let note = note.map(str::trim).filter(|n| !n.is_empty());
    if decision == "marked" {
        let fits = note.is_some_and(|n| {
            n.chars().count() <= MAX_NOTE_CHARS && !n.chars().any(char::is_control)
        });
        if !fits {
            return Err(AppError::new(
                "review_note",
                "Say what to change, in 1 to 500 characters.",
            ));
        }
    }
    let known = read_components(task, &HashMap::new())
        .is_some_and(|parts| parts.iter().any(|p| p.id == component_id))
        || (component_id == crate::body_plan_check::REVIEW_ID
            && crate::body_plan_check::exists(task));
    if !known {
        return Err(AppError::new(
            "component_not_found",
            "This run has no such part.",
        ));
    }
    let review = PartReview {
        decision: decision.to_string(),
        note: (decision == "marked").then(|| note.unwrap_or_default().to_string()),
    };
    let mut reviews = task_reviews(paths, task);
    reviews.insert(component_id.to_string(), review);
    save_reviews(paths, task, &reviews)
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    fn task_with_parts(tmp: &tempfile::TempDir) -> std::path::PathBuf {
        let task = tmp.path().join("task");
        std::fs::create_dir_all(task.join("whole_vessel")).unwrap();
        let execution = json!({"exit_code": 0, "result": {"engineering_approved": false, "components": [
            {"id": "aft_deck", "op": "deck", "status": "draft_guess", "built": true,
             "reason": "thickness: guessed: typical plate",
             "source": {"view": "profile", "region": "r1", "method": "label"},
             "source_labels": {"top": "traced", "thickness": "guessed", "outline": "traced"},
             "geometry": {"top": 3.4, "thickness": 0.01, "outline": [[0, 0], [1, 0], [1, 1]]},
             "provenance": {"thickness": {"source": "guessed", "basis": "typical plate"}},
             "bbox_m": {"min": [0, -3.6, 3.39], "max": [9, 3.6, 3.4]}, "volume_m3": 0.65},
            {"id": "tank_fw1", "label": "No 1 fresh water", "op": "tank", "status": "measured_draft", "built": true,
             "reason": "", "source": {"view": "plan", "region": "tank_fw1", "method": "reader"},
             "source_labels": {"outline": "traced"}, "geometry": {}, "provenance": {},
             "bbox_m": {"min": [4, -1.5, 0.2], "max": [7, 1.5, 1.4]}, "volume_m3": 4.2,
             "display": {"profile_m": [[[4, 0.2], [7, 0.2], [7, 1.4], [4, 1.4]], [[0, 0], [1, "x"], [2, 2]]],
                         "plan_m": [[[4, -1.5], [7, -1.2], [7, 1.2], [4, 1.5]]], "content_class": "fresh_water"}},
            {"id": "rudder", "label": "Rudder blade", "op": "appendage", "status": "draft_guess", "built": false,
             "reason": "ValueError: no view", "source": {"view": "profile", "region": "r2", "method": "label"},
             "source_labels": {}, "geometry": null, "provenance": {},
             "source_record": {"kind": "unknown", "reason": "The reader did not record the sheet."}}
        ]}});
        std::fs::write(task.join(EXECUTION_FILE), execution.to_string()).unwrap();
        task
    }

    #[test]
    fn worker_components_become_part_views() {
        let tmp = tempfile::tempdir().unwrap();
        let task = task_with_parts(&tmp);
        let parts = read_components(&task, &HashMap::new()).unwrap();
        assert_eq!(parts.len(), 3);
        let deck = &parts[0];
        assert!(deck.display.is_none());
        // A part without a record (an older run) has none; one with a record keeps it.
        assert!(deck.source_record.is_none());
        assert_eq!(parts[2].source_record.as_ref().unwrap()["kind"], "unknown");
        assert_eq!(
            (deck.label.as_str(), deck.op.as_str(), deck.review.as_str()),
            ("Aft deck", "deck", "open")
        );
        assert_eq!(deck.bbox_m.as_ref().unwrap().max, [9.0, 3.6, 3.4]);
        assert_eq!(
            deck.step_path.as_deref(),
            Some("whole_vessel/aft_deck.step")
        );
        let thickness = deck
            .arguments
            .iter()
            .find(|a| a.name == "thickness")
            .unwrap();
        assert_eq!(
            (
                thickness.source.as_str(),
                thickness.value.as_deref(),
                thickness.basis.as_deref()
            ),
            ("guessed", Some("0.010 m"), Some("typical plate"))
        );
        assert_eq!(
            deck.arguments
                .iter()
                .find(|a| a.name == "outline")
                .unwrap()
                .value
                .as_deref(),
            Some("3 points, 0.00 to 1.00 m by 0.00 to 1.00 m")
        );
        // A tank's sketch outlines; a polygon with a point that is not a number is left out.
        let tank = parts[1].display.as_ref().unwrap();
        assert_eq!(tank.profile_m.len(), 1);
        assert_eq!(tank.profile_m[0][2], [7.0, 1.4]);
        assert_eq!(tank.plan_m[0].len(), 4);
        assert_eq!(tank.content_class.as_deref(), Some("fresh_water"));
        let rudder = &parts[2];
        assert_eq!(rudder.label, "Rudder blade");
        assert!(
            !rudder.built
                && rudder.bbox_m.is_none()
                && rudder.step_path.is_none()
                && rudder.volume_m3.is_none()
        );
        assert!(read_components(&tmp.path().join("none"), &HashMap::new()).is_none());
    }

    /// `testdata/ship_cad_execution.json` is real ship-cad worker output (`ship_cad.execute`
    /// on a synthetic two-part program; no drawing data): the reader must take it as it is.
    #[test]
    fn real_worker_output_is_read() {
        let tmp = tempfile::tempdir().unwrap();
        let task = tmp.path().join("task");
        std::fs::create_dir_all(task.join("whole_vessel")).unwrap();
        std::fs::write(
            task.join(EXECUTION_FILE),
            include_str!("../testdata/ship_cad_execution.json"),
        )
        .unwrap();
        let parts = read_components(&task, &HashMap::new()).unwrap();
        assert_eq!(parts.len(), 2);
        let house = &parts[0];
        assert_eq!(
            (house.id.as_str(), house.status.as_str(), house.built),
            ("house_t1", "measured_draft", true)
        );
        assert_eq!(house.bbox_m.as_ref().unwrap().min, [9.0, -2.6, 3.4]);
        assert!((house.volume_m3.unwrap() - 99.84).abs() < 1e-6);
        let height = house.arguments.iter().find(|a| a.name == "height").unwrap();
        assert_eq!(height.value.as_deref(), Some("3.400 to 5.800 m"));
        assert_eq!(
            height.basis.as_deref(),
            Some("Read from the profile (parallel lines)")
        );
        let outline = house
            .arguments
            .iter()
            .find(|a| a.name == "outline")
            .unwrap();
        assert_eq!(
            outline.value.as_deref(),
            Some("4 points, 9.00 to 17.00 m by -2.60 to 2.60 m")
        );
        let mast = &parts[1];
        assert!(!mast.built && mast.arguments.is_empty() && mast.bbox_m.is_none());
        assert!(mast.reason.contains("missing or invalid measurement"));
    }

    #[test]
    fn a_whole_vessel_glb_is_listed_and_a_huge_one_is_not_loaded() {
        let tmp = tempfile::tempdir().unwrap();
        let task = tmp.path().join("task");
        std::fs::create_dir_all(&task).unwrap();
        assert!(whole_vessel_model(&task).is_none());
        let glb = std::fs::File::create(task.join(WHOLE_VESSEL_GLB[0])).unwrap();
        glb.set_len(1024).unwrap();
        let model = whole_vessel_model(&task).unwrap();
        assert_eq!(
            (model.glb_path.as_str(), model.bytes, model.loadable),
            ("whole-vessel-draft.glb", 1024, true)
        );
        // A sparse file: the size is checked from the metadata, nothing is read.
        glb.set_len(crate::artifact::MAX_GLB_BYTES as u64 + 1)
            .unwrap();
        assert!(!whole_vessel_model(&task).unwrap().loadable);
    }

    /// Reads a real whole-vessel run folder when one is named (never committed: drawings and
    /// their numbers may be licensed). `MARINAFRAME_PARTS_TASK=<task folder> cargo test -- --ignored`.
    #[test]
    #[ignore]
    fn a_real_whole_vessel_task_reads() {
        let Ok(task) = std::env::var("MARINAFRAME_PARTS_TASK") else {
            return;
        };
        let task = std::path::PathBuf::from(task);
        let parts = read_components(&task, &HashMap::new()).expect("whole_vessel/execution.json");
        assert!(!parts.is_empty());
        for part in &parts {
            assert!(!part.label.is_empty(), "{} has no label", part.id);
            if part.built {
                assert!(part.bbox_m.is_some(), "{} has no box", part.id);
                assert!(
                    part.step_path
                        .as_deref()
                        .is_some_and(|p| task.join(p).is_file()),
                    "{} has no STEP",
                    part.id
                );
            }
            for argument in &part.arguments {
                assert!(
                    argument.value.is_some(),
                    "{}.{} has no value",
                    part.id,
                    argument.name
                );
                assert!(
                    argument.basis.is_some(),
                    "{}.{} has no basis",
                    part.id,
                    argument.name
                );
            }
        }
        eprintln!(
            "{} parts read; model: {:?}",
            parts.len(),
            whole_vessel_model(&task).map(|m| (m.bytes, m.loadable))
        );
        // For a local UI check only: the parts as the app sees them, for the browser mock
        // (`?mockpartsfile`). The output path must be git-ignored; it holds the run's numbers.
        if let Ok(out) = std::env::var("MARINAFRAME_PARTS_OUT") {
            std::fs::write(out, serde_json::to_vec_pretty(&parts).unwrap()).unwrap();
        }
    }

    #[test]
    fn a_review_is_kept_per_task_and_part() {
        let tmp = tempfile::tempdir().unwrap();
        let task = task_with_parts(&tmp);
        let paths = AppPaths {
            config_dir: tmp.path().join("config"),
            data_dir: tmp.path().join("data"),
            repo_root: None,
        };
        review_component(&paths, &task, "aft_deck", "accepted", None).unwrap();
        let parts = read_components(&task, &reviews_of(&paths, &task)).unwrap();
        assert_eq!(
            (parts[0].review.as_str(), parts[0].review_note.as_deref()),
            ("accepted", None)
        );
        assert!(review_component(&paths, &task, "aft_deck", "approved", None).is_err());
        assert!(review_component(&paths, &task, "no_such_part", "accepted", None).is_err());
    }

    fn copy_folder(from: &Path, to: &Path) {
        std::fs::create_dir_all(to).unwrap();
        for entry in std::fs::read_dir(from).unwrap() {
            let entry = entry.unwrap();
            let target = to.join(entry.file_name());
            if entry.file_type().unwrap().is_dir() {
                copy_folder(&entry.path(), &target);
            } else {
                std::fs::copy(entry.path(), target).unwrap();
            }
        }
    }

    #[test]
    fn a_review_moves_with_a_copied_run() {
        let tmp = tempfile::tempdir().unwrap();
        let task = task_with_parts(&tmp);
        let paths = AppPaths {
            config_dir: tmp.path().join("config"),
            data_dir: tmp.path().join("data"),
            repo_root: None,
        };
        review_component(&paths, &task, "aft_deck", "marked", Some("Lower the deck")).unwrap();
        assert!(task.join("review/part_reviews.json").is_file());
        // Another Mac: a new config folder and the run in another place.
        let copy = tmp.path().join("elsewhere/task");
        copy_folder(&task, &copy);
        let other = AppPaths {
            config_dir: tmp.path().join("other-config"),
            data_dir: tmp.path().join("other-data"),
            repo_root: None,
        };
        let review = &reviews_of(&other, &copy)["aft_deck"];
        assert_eq!(
            (review.decision.as_str(), review.note.as_deref()),
            ("marked", Some("Lower the deck"))
        );
    }

    #[test]
    fn a_review_kept_in_the_app_config_is_read_and_moved_into_the_run() {
        let tmp = tempfile::tempdir().unwrap();
        let task = task_with_parts(&tmp);
        let paths = AppPaths {
            config_dir: tmp.path().join("config"),
            data_dir: tmp.path().join("data"),
            repo_root: None,
        };
        let other_task = "/elsewhere/other-run".to_string();
        let accepted = PartReview {
            decision: "accepted".into(),
            note: None,
        };
        let legacy: LegacyReviews = [
            (
                legacy_key(&task),
                [("aft_deck".to_string(), accepted.clone())].into(),
            ),
            (
                other_task.clone(),
                [("x".to_string(), accepted.clone())].into(),
            ),
        ]
        .into();
        storage::write_config_json(&paths, REVIEWS_FILE, &legacy).unwrap();
        // Read from the config while the run has no reviews file.
        assert_eq!(reviews_of(&paths, &task)["aft_deck"], accepted);
        assert!(!task.join("review").exists());
        // Re-export's empty portable record must not hide the earlier decisions.
        std::fs::create_dir(task.join("review")).unwrap();
        std::fs::write(task.join("review/part_reviews.json"), "{}").unwrap();
        assert_eq!(reviews_of(&paths, &task)["aft_deck"], accepted);
        // The next review keeps the earlier one, writes both into the run and drops the
        // task's config entry; another task's entry stays.
        review_component(&paths, &task, "tank_fw1", "accepted", None).unwrap();
        let in_run = run_reviews(&task).unwrap();
        assert_eq!(
            in_run.keys().collect::<Vec<_>>(),
            vec!["aft_deck", "tank_fw1"]
        );
        let left = legacy_reviews(&paths);
        assert!(!left.contains_key(&legacy_key(&task)));
        assert!(left.contains_key(&other_task));
    }

    #[test]
    fn records_on_an_added_sheet_get_its_page_and_the_part_box() {
        let tmp = tempfile::tempdir().unwrap();
        let task = task_with_parts(&tmp);
        let mut execution: Value =
            serde_json::from_slice(&std::fs::read(task.join(EXECUTION_FILE)).unwrap()).unwrap();
        let on_sheet = |view: &str| json!({"sheet": "cjob/Tank Rev0.dxf", "page": 0, "view": view, "box_px": null});
        execution["result"]["components"][1]["source_record"] = json!({"kind": "read",
            "regions": [on_sheet("plan"), on_sheet("profile"),
                {"sheet": "other.dxf", "page": 0, "view": "plan", "box_px": null}]});
        std::fs::write(task.join(EXECUTION_FILE), execution.to_string()).unwrap();
        std::fs::create_dir_all(task.join("sources")).unwrap();
        std::fs::write(
            task.join(crate::sources::ADDED_SHEETS_FILE),
            json!({"schema": "marinaframe.run-sheets.v1", "sheets": [
                {"name": "cjob/Tank Rev0.dxf", "file": "sources/sheets/tank.png",
                 "width_px": 400, "height_px": 200,
                 "part_boxes": {"view": "plan", "boxes": {"tank_fw1": [10, 20, 30, 40]}}}]})
            .to_string(),
        )
        .unwrap();
        let parts = read_components(&task, &HashMap::new()).unwrap();
        let record = parts[1].source_record.as_ref().unwrap();
        let regions = &record["regions"];
        assert_eq!(regions[0]["page_px"], json!([400, 200]));
        assert_eq!(regions[0]["box_px"], json!([10, 20, 30, 40]));
        // Another view of the same sheet: its page, no box. Another sheet: unchanged.
        assert_eq!(regions[1]["page_px"], json!([400, 200]));
        assert!(regions[1]["box_px"].is_null());
        assert!(regions[2].get("page_px").is_none());
        // The result is still a valid record.
        assert!(crate::source_record::checked(record).is_some());
    }

    #[test]
    fn a_marked_part_keeps_what_to_change() {
        let tmp = tempfile::tempdir().unwrap();
        let task = task_with_parts(&tmp);
        let paths = AppPaths {
            config_dir: tmp.path().join("config"),
            data_dir: tmp.path().join("data"),
            repo_root: None,
        };
        // A mark needs a note of 1 to 500 characters.
        assert!(review_component(&paths, &task, "aft_deck", "marked", None).is_err());
        assert!(review_component(&paths, &task, "aft_deck", "marked", Some("  ")).is_err());
        assert!(
            review_component(&paths, &task, "aft_deck", "marked", Some(&"x".repeat(501))).is_err()
        );
        review_component(
            &paths,
            &task,
            "aft_deck",
            "marked",
            Some(" Deck is 0.1 m too high "),
        )
        .unwrap();
        let parts = read_components(&task, &reviews_of(&paths, &task)).unwrap();
        assert_eq!(
            (parts[0].review.as_str(), parts[0].review_note.as_deref()),
            ("marked", Some("Deck is 0.1 m too high"))
        );
        // Opening it again drops the note.
        review_component(&paths, &task, "aft_deck", "open", Some("ignored")).unwrap();
        let parts = read_components(&task, &reviews_of(&paths, &task)).unwrap();
        assert_eq!(
            (parts[0].review.as_str(), parts[0].review_note.as_deref()),
            ("open", None)
        );
    }
}
