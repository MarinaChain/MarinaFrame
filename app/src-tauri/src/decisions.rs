//! Design decisions in a sidecar file beside the records (interim until schema 1.2).
//!
//! File: `<runs folder>/designs/decisions/<project design_id>.json`, schema tag
//! `marinaframe.design_decisions.v0`. Entries carry the schema 1.1 decision fields plus
//! `discipline`. The file is append-only: a new decision never edits or removes an old one.
//! See `docs/design/2026-11-14-decision-discipline-proposal.md`.
use crate::designs;
use serde::Deserialize;
use serde_json::{json, Value};
use std::{
    fs,
    path::{Path, PathBuf},
    time::{SystemTime, UNIX_EPOCH},
};

const SCHEMA: &str = "marinaframe.design_decisions.v0";
const ACTIONS: [&str; 3] = ["accepted", "deferred", "rejected"];
const DISCIPLINES: [&str; 5] = [
    "basic_design",
    "structure",
    "machinery",
    "outfitting",
    "accommodation",
];
/// Limits keep one entry readable in the log and stop accidental pastes of whole documents.
const MAX_REASON_CHARS: usize = 2000;
const MAX_DESIGNER_CHARS: usize = 80;

/// What the UI sends. The backend sets `id`, `recorded_at` and `status`.
#[derive(Deserialize)]
pub struct NewDecision {
    pub candidate_id: String,
    pub action: String,
    pub discipline: String,
    pub reason: String,
    pub designer_id: String,
}

/// The project ID becomes a file name, so it must be one plain path component.
fn sidecar_path(runs: &Path, project_id: &str) -> Result<PathBuf, String> {
    let plain = !project_id.is_empty()
        && !project_id.starts_with('.')
        && project_id
            .chars()
            .all(|c| c.is_ascii_alphanumeric() || matches!(c, '-' | '_' | '.'));
    if !plain {
        return Err("The project ID cannot be used as a decision file name.".into());
    }
    Ok(runs
        .join("designs")
        .join("decisions")
        .join(format!("{project_id}.json")))
}

fn read_entries(path: &Path) -> Result<Vec<Value>, String> {
    if !path.exists() {
        return Ok(vec![]);
    }
    if !fs::symlink_metadata(path)
        .map_err(|e| e.to_string())?
        .file_type()
        .is_file()
    {
        return Err("The decision file must be a regular file, not a symbolic link.".into());
    }
    let file: Value = serde_json::from_str(&fs::read_to_string(path).map_err(|e| e.to_string())?)
        .map_err(|e| format!("The decision file is not valid JSON: {e}"))?;
    if file["schema"] != SCHEMA {
        return Err(format!("The decision file is not {SCHEMA}."));
    }
    file["decisions"]
        .as_array()
        .cloned()
        .ok_or_else(|| "The decision file has no decisions list.".into())
}

/// All decisions of a project, oldest first. A project with no file has no decisions.
pub fn list(runs: &Path, project_id: &str) -> Result<Vec<Value>, String> {
    read_entries(&sidecar_path(runs, project_id)?)
}

fn required_text(value: &str, field: &str, max_chars: usize) -> Result<String, String> {
    let text = value.trim();
    if text.is_empty() {
        return Err(format!("The {field} is required."));
    }
    if text.chars().count() > max_chars {
        return Err(format!(
            "The {field} is longer than {max_chars} characters."
        ));
    }
    Ok(text.to_string())
}

/// Append one decision after checking that the candidate is a direct child of the project.
pub fn append(runs: &Path, project_id: &str, decision: NewDecision) -> Result<Value, String> {
    let path = sidecar_path(runs, project_id)?;
    if !ACTIONS.contains(&decision.action.as_str()) {
        return Err("The action must be accepted, deferred or rejected.".into());
    }
    if !DISCIPLINES.contains(&decision.discipline.as_str()) {
        return Err("The discipline is not known.".into());
    }
    let reason = required_text(&decision.reason, "reason", MAX_REASON_CHARS)?;
    let designer_id = required_text(&decision.designer_id, "reviewer name", MAX_DESIGNER_CHARS)?;
    designs::open(runs, project_id)?;
    let candidate = designs::open(runs, &decision.candidate_id)?;
    if candidate["lineage"]["parent_design_id"] != project_id {
        return Err("The candidate is not a design of this project.".into());
    }

    let mut entries = read_entries(&path)?;
    let now = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_err(|e| e.to_string())?;
    let entry = json!({
        "id": format!("decision-{}-{}", now.as_millis(), entries.len() + 1),
        "candidate_id": decision.candidate_id,
        "action": decision.action,
        "discipline": decision.discipline,
        "reason": reason,
        "designer_id": designer_id,
        "recorded_at": utc_timestamp(now.as_secs()),
        // Every decision is a draft record of a person's choice; the app never approves.
        "status": "draft",
    });
    entries.push(entry.clone());

    let folder = path.parent().expect("sidecar path has a folder");
    fs::create_dir_all(folder).map_err(|e| e.to_string())?;
    let text = serde_json::to_string_pretty(
        &json!({ "schema": SCHEMA, "project_id": project_id, "decisions": entries }),
    )
    .map_err(|e| e.to_string())?;
    // Write a temporary file, then rename, so a crash cannot leave a half-written log.
    let temporary = folder.join(format!(".{project_id}.json.tmp"));
    fs::write(&temporary, text).map_err(|e| e.to_string())?;
    fs::rename(&temporary, &path).map_err(|e| e.to_string())?;
    Ok(entry)
}

/// "2026-11-14T08:15:00Z" from Unix seconds (UTC), without a date library.
fn utc_timestamp(unix_seconds: u64) -> String {
    const SECONDS_PER_DAY: u64 = 86_400;
    let days = (unix_seconds / SECONDS_PER_DAY) as i64;
    let second_of_day = unix_seconds % SECONDS_PER_DAY;
    let (year, month, day) = civil_from_days(days);
    format!(
        "{year:04}-{month:02}-{day:02}T{:02}:{:02}:{:02}Z",
        second_of_day / 3600,
        second_of_day % 3600 / 60,
        second_of_day % 60
    )
}

/// Proleptic Gregorian date from days since 1970-01-01 (H. Hinnant's public-domain algorithm).
fn civil_from_days(days: i64) -> (i64, u32, u32) {
    let shifted = days + 719_468; // days from 0000-03-01 to 1970-01-01
    let era = shifted.div_euclid(146_097); // 146 097 days in a 400-year cycle
    let day_of_era = shifted.rem_euclid(146_097);
    let year_of_era =
        (day_of_era - day_of_era / 1460 + day_of_era / 36_524 - day_of_era / 146_096) / 365;
    let day_of_year = day_of_era - (365 * year_of_era + year_of_era / 4 - year_of_era / 100);
    let month_index = (5 * day_of_year + 2) / 153; // March = 0
    let day = (day_of_year - (153 * month_index + 2) / 5 + 1) as u32;
    let month = if month_index < 10 {
        month_index + 3
    } else {
        month_index - 9
    } as u32;
    let year = year_of_era + era * 400 + i64::from(month <= 2);
    (year, month, day)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn folder() -> PathBuf {
        let folder = std::env::temp_dir().join(format!(
            "marinaframe-decisions-{}-{}",
            std::process::id(),
            SystemTime::now()
                .duration_since(UNIX_EPOCH)
                .unwrap()
                .as_nanos()
        ));
        fs::create_dir_all(folder.join("designs")).unwrap();
        fs::write(
            folder.join("designs/parent.json"),
            include_str!("../../ui/mock/files/designs/kvlcc2.json"),
        )
        .unwrap();
        fs::write(
            folder.join("designs/candidate-a.json"),
            include_str!("../../ui/mock/files/designs/kvlcc2-candidate-a.json"),
        )
        .unwrap();
        folder
    }

    fn decision(action: &str) -> NewDecision {
        NewDecision {
            candidate_id: "synthetic-kvlcc2-candidate-a".into(),
            action: action.into(),
            discipline: "structure".into(),
            reason: "  Synthetic test reason.  ".into(),
            designer_id: "Test reviewer".into(),
        }
    }

    #[test]
    fn timestamps_are_utc_iso() {
        assert_eq!(utc_timestamp(0), "1970-01-01T00:00:00Z");
        assert_eq!(utc_timestamp(951_782_400), "2000-02-29T00:00:00Z");
        assert_eq!(utc_timestamp(1_794_644_100), "2026-11-14T08:15:00Z");
    }

    #[test]
    fn appends_in_order_and_keeps_history() {
        let runs = folder();
        assert!(list(&runs, "public-kvlcc2-example").unwrap().is_empty());
        let first = append(&runs, "public-kvlcc2-example", decision("deferred")).unwrap();
        append(&runs, "public-kvlcc2-example", decision("accepted")).unwrap();
        let entries = list(&runs, "public-kvlcc2-example").unwrap();
        assert_eq!(entries.len(), 2);
        assert_eq!(entries[0], first);
        assert_eq!(entries[0]["reason"], "Synthetic test reason.");
        assert_eq!(entries[1]["action"], "accepted");
        assert_eq!(entries[1]["status"], "draft");
        fs::remove_dir_all(runs).unwrap();
    }

    #[test]
    fn rejects_bad_input_without_writing() {
        let runs = folder();
        let project = "public-kvlcc2-example";
        assert!(append(&runs, project, decision("approved")).is_err());
        let mut no_reason = decision("accepted");
        no_reason.reason = "   ".into();
        assert!(append(&runs, project, no_reason).is_err());
        let mut bad_discipline = decision("accepted");
        bad_discipline.discipline = "sales".into();
        assert!(append(&runs, project, bad_discipline).is_err());
        let mut not_child = decision("accepted");
        not_child.candidate_id = project.into();
        assert!(append(&runs, project, not_child).is_err());
        assert!(list(&runs, "../escape").is_err());
        assert!(append(&runs, "missing-project", decision("accepted")).is_err());
        assert!(list(&runs, project).unwrap().is_empty());
        fs::remove_dir_all(runs).unwrap();
    }
}
