//! Whole-vessel parts of a run (APP_SPEC "Whole-vessel parts"). The ship-cad worker writes
//! `<task>/whole_vessel/execution.json` (`src/vessel_reconstruction/ship_cad.py`); each entry of
//! `result.components` becomes one `ComponentView`. The person's review of a part is app
//! state, kept in the app config folder (`part_reviews.json`), never in the run folder.
use crate::error::{AppError, AppResult};
use crate::storage::{self, AppPaths};
use crate::types::{ComponentArgument, ComponentBox, ComponentView, WholeVesselModel};
use serde_json::Value;
use std::collections::{BTreeMap, HashMap};
use std::path::Path;

/// The ship-cad worker output inside a task folder.
pub const EXECUTION_FILE: &str = "whole_vessel/execution.json";
const EXECUTION_MAX_BYTES: usize = 8 * 1024 * 1024;
const REVIEWS_FILE: &str = "part_reviews.json";
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

/// A short text for a ship-cad argument value: a number in metres, a range, or a point count.
fn value_text(value: &Value) -> Option<String> {
    match value {
        Value::Number(n) => n.as_f64().map(|v| format!("{v:.3} m")),
        Value::Array(items) if items.len() == 2 && items.iter().all(Value::is_number) => {
            let a = items[0].as_f64()?;
            let b = items[1].as_f64()?;
            Some(format!("{a:.3} to {b:.3} m"))
        }
        Value::Array(items) if items.iter().all(Value::is_array) => {
            Some(format!("{} points", items.len()))
        }
        Value::String(text) => Some(text.clone()),
        _ => None,
    }
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

fn component_view(entry: &Value, reviews: &HashMap<String, PartReview>) -> Option<ComponentView> {
    let id = entry["id"].as_str()?.to_string();
    let built = entry["built"].as_bool().unwrap_or(false);
    let labels = entry["source_labels"].as_object();
    let arguments = labels
        .map(|labels| {
            labels
                .iter()
                .filter_map(|(name, label)| argument_view(entry, name, label.as_str()?))
                .collect()
        })
        .unwrap_or_default();
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
    Some(
        entries
            .iter()
            .filter_map(|entry| component_view(entry, reviews))
            .collect(),
    )
}

/// A person's review of one part. "marked" carries what the person wants changed.
#[derive(Clone, Debug, Default, PartialEq, Eq, serde::Serialize, serde::Deserialize)]
pub struct PartReview {
    pub decision: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub note: Option<String>,
}

type AllReviews = BTreeMap<String, BTreeMap<String, PartReview>>;

fn all_reviews(paths: &AppPaths) -> AllReviews {
    storage::read_config_json(paths, REVIEWS_FILE).unwrap_or_default()
}

/// The saved reviews of one task: component id -> review.
pub fn reviews_of(paths: &AppPaths, task: &Path) -> HashMap<String, PartReview> {
    all_reviews(paths)
        .remove(&task.to_string_lossy().into_owned())
        .map(|m| m.into_iter().collect())
        .unwrap_or_default()
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
        .is_some_and(|parts| parts.iter().any(|p| p.id == component_id));
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
    let mut reviews = all_reviews(paths);
    reviews
        .entry(task.to_string_lossy().into_owned())
        .or_default()
        .insert(component_id.to_string(), review);
    storage::write_config_json(paths, REVIEWS_FILE, &reviews)
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
            {"id": "rudder", "label": "Rudder blade", "op": "appendage", "status": "draft_guess", "built": false,
             "reason": "ValueError: no view", "source": {"view": "profile", "region": "r2", "method": "label"},
             "source_labels": {}, "geometry": null, "provenance": {}}
        ]}});
        std::fs::write(task.join(EXECUTION_FILE), execution.to_string()).unwrap();
        task
    }

    #[test]
    fn worker_components_become_part_views() {
        let tmp = tempfile::tempdir().unwrap();
        let task = task_with_parts(&tmp);
        let parts = read_components(&task, &HashMap::new()).unwrap();
        assert_eq!(parts.len(), 2);
        let deck = &parts[0];
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
            Some("3 points")
        );
        let rudder = &parts[1];
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
        assert_eq!(outline.value.as_deref(), Some("4 points"));
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
