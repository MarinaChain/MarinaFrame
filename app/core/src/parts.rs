//! Whole-vessel parts of a run (APP_SPEC "Whole-vessel parts"). The ship-cad worker writes
//! `<task>/whole_vessel/execution.json` (`src/vessel_reconstruction/ship_cad.py`); each entry of
//! `result.components` becomes one `ComponentView`. The person's review of a part is app
//! state, kept in the app config folder (`part_reviews.json`), never in the run folder.
use crate::error::{AppError, AppResult};
use crate::storage::{self, AppPaths};
use crate::types::{ComponentArgument, ComponentBox, ComponentView};
use serde_json::Value;
use std::collections::{BTreeMap, HashMap};
use std::path::Path;

/// The ship-cad worker output inside a task folder.
pub const EXECUTION_FILE: &str = "whole_vessel/execution.json";
const EXECUTION_MAX_BYTES: usize = 8 * 1024 * 1024;
const REVIEWS_FILE: &str = "part_reviews.json";
/// Review decisions a person can save.
pub const DECISIONS: [&str; 2] = ["accepted", "open"];

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

fn component_view(entry: &Value, reviews: &HashMap<String, String>) -> Option<ComponentView> {
    let id = entry["id"].as_str()?.to_string();
    let built = entry["built"].as_bool().unwrap_or(false);
    let labels = entry["source_labels"].as_object();
    let arguments = labels
        .map(|labels| {
            labels
                .iter()
                .filter_map(|(name, label)| {
                    Some(ComponentArgument {
                        name: name.clone(),
                        value: value_text(&entry["geometry"][name]),
                        source: label.as_str()?.to_string(),
                        basis: entry["provenance"][name]["basis"]
                            .as_str()
                            .map(String::from),
                    })
                })
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
        label: label_of(&id),
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
        review: reviews.get(&id).cloned().unwrap_or_else(|| "open".into()),
        id,
    })
}

/// The parts of a run, or None when the run has no whole-vessel output.
pub fn read_components(
    task: &Path,
    reviews: &HashMap<String, String>,
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

type AllReviews = BTreeMap<String, BTreeMap<String, String>>;

fn all_reviews(paths: &AppPaths) -> AllReviews {
    storage::read_config_json(paths, REVIEWS_FILE).unwrap_or_default()
}

/// The saved reviews of one task: component id -> decision.
pub fn reviews_of(paths: &AppPaths, task: &Path) -> HashMap<String, String> {
    all_reviews(paths)
        .remove(&task.to_string_lossy().into_owned())
        .map(|m| m.into_iter().collect())
        .unwrap_or_default()
}

/// Save a person's review of one part.
pub fn review_component(
    paths: &AppPaths,
    task: &Path,
    component_id: &str,
    decision: &str,
) -> AppResult<()> {
    if !DECISIONS.contains(&decision) {
        return Err(AppError::new("review_decision", "Unknown review decision."));
    }
    let known = read_components(task, &HashMap::new())
        .is_some_and(|parts| parts.iter().any(|p| p.id == component_id));
    if !known {
        return Err(AppError::new(
            "component_not_found",
            "This run has no such part.",
        ));
    }
    let mut reviews = all_reviews(paths);
    reviews
        .entry(task.to_string_lossy().into_owned())
        .or_default()
        .insert(component_id.to_string(), decision.to_string());
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
            {"id": "rudder", "op": "appendage", "status": "draft_guess", "built": false,
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
        assert!(
            !rudder.built
                && rudder.bbox_m.is_none()
                && rudder.step_path.is_none()
                && rudder.volume_m3.is_none()
        );
        assert!(read_components(&tmp.path().join("none"), &HashMap::new()).is_none());
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
        review_component(&paths, &task, "aft_deck", "accepted").unwrap();
        assert_eq!(
            reviews_of(&paths, &task)
                .get("aft_deck")
                .map(String::as_str),
            Some("accepted")
        );
        let parts = read_components(&task, &reviews_of(&paths, &task)).unwrap();
        assert_eq!(parts[0].review, "accepted");
        assert!(review_component(&paths, &task, "aft_deck", "approved").is_err());
        assert!(review_component(&paths, &task, "no_such_part", "accepted").is_err());
    }
}
