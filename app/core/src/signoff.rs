//! A person's sign-off of a run's whole-vessel parts: "Signed off by <name>, <date>: usable
//! as a starting model". It is a record of a person's judgement, not a status change: the run
//! and every file stay drafts and `engineering_approved` stays false. Kept in the app config
//! folder (`signoffs.json`), never in the run folder.
use crate::error::{AppError, AppResult};
use crate::parts::{self, PartReview};
use crate::storage::{self, AppPaths};
use crate::types::SignOffView;
use std::collections::{BTreeMap, HashMap};
use std::path::Path;

const SIGNOFFS_FILE: &str = "signoffs.json";
/// Longest name on a sign-off.
pub const MAX_NAME_CHARS: usize = 80;
/// The fixed words of a sign-off (founder wording, 2026-11-09).
pub const STATEMENT: &str = "usable as a starting model";

type AllSignOffs = BTreeMap<String, SignOffView>;

fn all(paths: &AppPaths) -> AllSignOffs {
    storage::read_config_json(paths, SIGNOFFS_FILE).unwrap_or_default()
}

fn key(task: &Path) -> String {
    task.to_string_lossy().into_owned()
}

/// The sign-off of one task, if any.
pub fn sign_off_of(paths: &AppPaths, task: &Path) -> Option<SignOffView> {
    all(paths).remove(&key(task))
}

/// Record a sign-off. Every part must be reviewed (accepted or marked) first.
pub fn sign_off(paths: &AppPaths, task: &Path, name: &str, now_ms: u64) -> AppResult<SignOffView> {
    let name = name.trim();
    if name.is_empty()
        || name.chars().count() > MAX_NAME_CHARS
        || name.chars().any(char::is_control)
    {
        return Err(AppError::new(
            "sign_off_name",
            "Type your name (1 to 80 characters).",
        ));
    }
    let reviews: HashMap<String, PartReview> = parts::reviews_of(paths, task);
    let parts = parts::read_components(task, &reviews)
        .ok_or_else(|| AppError::new("sign_off_no_parts", "This run has no parts to sign off."))?;
    let open = parts.iter().filter(|p| p.review == "open").count();
    if open > 0 {
        return Err(AppError::new(
            "sign_off_open_parts",
            &format!("Review every part first: {open} still open."),
        ));
    }
    let record = SignOffView {
        name: name.to_string(),
        time_ms: now_ms,
        statement: STATEMENT.to_string(),
    };
    let mut records = all(paths);
    records.insert(key(task), record.clone());
    storage::write_config_json(paths, SIGNOFFS_FILE, &records)?;
    Ok(record)
}

/// Withdraw a sign-off (no error when there is none).
pub fn withdraw(paths: &AppPaths, task: &Path) -> AppResult<()> {
    let mut records = all(paths);
    if records.remove(&key(task)).is_some() {
        storage::write_config_json(paths, SIGNOFFS_FILE, &records)?;
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    fn setup(tmp: &tempfile::TempDir) -> (AppPaths, std::path::PathBuf) {
        let task = tmp.path().join("task");
        std::fs::create_dir_all(task.join("whole_vessel")).unwrap();
        let execution = json!({"result": {"components": [
            {"id": "deck", "op": "deck", "status": "measured_draft", "built": true, "reason": "",
             "source_labels": {}, "bbox_m": {"min": [0, 0, 0], "max": [1, 1, 1]}},
            {"id": "house", "op": "deckhouse", "status": "draft_guess", "built": true, "reason": "",
             "source_labels": {}, "bbox_m": {"min": [0, 0, 1], "max": [1, 1, 2]}}]}});
        std::fs::write(task.join(parts::EXECUTION_FILE), execution.to_string()).unwrap();
        let paths = AppPaths {
            config_dir: tmp.path().join("config"),
            data_dir: tmp.path().join("data"),
            repo_root: None,
        };
        (paths, task)
    }

    #[test]
    fn sign_off_needs_a_name_and_every_part_reviewed() {
        let tmp = tempfile::tempdir().unwrap();
        let (paths, task) = setup(&tmp);
        assert!(sign_off(&paths, &task, "  ", 1).is_err());
        let open = sign_off(&paths, &task, "Ada Lovelace", 1).unwrap_err();
        assert_eq!(open.code, "sign_off_open_parts");
        parts::review_component(&paths, &task, "deck", "accepted", None).unwrap();
        parts::review_component(&paths, &task, "house", "marked", Some("Too long by 0.5 m"))
            .unwrap();
        let record = sign_off(&paths, &task, " Ada Lovelace ", 42).unwrap();
        assert_eq!(
            (
                record.name.as_str(),
                record.time_ms,
                record.statement.as_str()
            ),
            ("Ada Lovelace", 42, STATEMENT)
        );
        assert_eq!(sign_off_of(&paths, &task), Some(record));
        withdraw(&paths, &task).unwrap();
        assert!(sign_off_of(&paths, &task).is_none());
    }
}
