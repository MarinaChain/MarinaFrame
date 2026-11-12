//! How a run first shows when it opens, kept in the run folder (`presentation.json`), so a
//! copied run opens the same way on any Mac: on its whole vessel, with the section lines off or
//! the hull see-through, and with a line about its drawings. A concept-preview run (a made-up
//! vessel, `config.policy` "concept_preview") always carries its label, with or without the file.
//! The person can change every view switch afterwards; nothing here changes the run.
use marinaframe_control::util;
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::path::Path;

pub const PRESENTATION_FILE: &str = "presentation.json";
const SCHEMA: &str = "marinaframe.presentation.v1";
const MAX_FILE_BYTES: usize = 16 * 1024;
/// Longest note or credit line shown on the run pages.
const MAX_LINE_CHARS: usize = 300;
/// The policy of a run made by the concept-preview generator (`benchmarks/concept_launch`).
const CONCEPT_POLICY: &str = "concept_preview";

/// The first view of a run. The UI reads the same fields from the web demo's manifest.
#[derive(Clone, Debug, Default, Serialize, Deserialize, PartialEq)]
pub struct RunPresentation {
    /// A made-up vessel and drawings: every page says so.
    pub concept: bool,
    /// Who made the drawings and under what terms, shown on every page.
    pub credit: Option<String>,
    /// A short note about the run, shown on every page.
    pub note: Option<String>,
    /// Open on the whole-vessel model, when the run has one.
    pub whole_vessel_first: bool,
    /// Start with the Section lines switch on.
    pub section_lines: bool,
    /// Start with See-through hull on.
    pub see_through: bool,
}

#[derive(Deserialize)]
struct PresentationFile {
    schema: String,
    #[serde(default)]
    credit: Option<String>,
    #[serde(default)]
    note: Option<String>,
    #[serde(default)]
    whole_vessel_first: bool,
    #[serde(default = "shown")]
    section_lines: bool,
    #[serde(default)]
    see_through: bool,
}

fn shown() -> bool {
    true
}

fn line(text: Option<String>) -> Option<String> {
    text.map(|t| t.trim().to_string()).filter(|t| {
        !t.is_empty() && t.chars().count() <= MAX_LINE_CHARS && !t.chars().any(char::is_control)
    })
}

/// The run's presentation, or None for a run with no file that is not a concept preview.
/// A file with another schema, or one that does not parse, counts as no file.
pub fn read(task: &Path, state: &Value) -> Option<RunPresentation> {
    let concept = state["config"]["policy"] == CONCEPT_POLICY;
    let file = crate::artifact::guard_inside_task(task, PRESENTATION_FILE)
        .ok()
        .and_then(|path| util::read_bounded(&path, MAX_FILE_BYTES).ok())
        .and_then(|bytes| serde_json::from_slice::<PresentationFile>(&bytes).ok())
        .filter(|file| file.schema == SCHEMA);
    match file {
        Some(file) => Some(RunPresentation {
            concept,
            credit: line(file.credit),
            note: line(file.note),
            whole_vessel_first: file.whole_vessel_first,
            section_lines: file.section_lines,
            see_through: file.see_through,
        }),
        None if concept => Some(RunPresentation {
            concept,
            section_lines: true,
            ..RunPresentation::default()
        }),
        None => None,
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    fn task_with(file: Option<Value>) -> tempfile::TempDir {
        let tmp = tempfile::tempdir().unwrap();
        if let Some(file) = file {
            std::fs::write(tmp.path().join(PRESENTATION_FILE), file.to_string()).unwrap();
        }
        tmp
    }

    #[test]
    fn the_run_file_sets_the_first_view() {
        let tmp = task_with(Some(json!({"schema": SCHEMA, "whole_vessel_first": true,
            "section_lines": false, "credit": " Drawings: NTNU. ", "note": "bad\u{7}line"})));
        let shown = read(tmp.path(), &json!({"config": {"policy": "deterministic"}})).unwrap();
        assert_eq!(
            shown,
            RunPresentation {
                concept: false,
                credit: Some("Drawings: NTNU.".into()),
                note: None,
                whole_vessel_first: true,
                section_lines: false,
                see_through: false,
            }
        );
    }

    #[test]
    fn a_concept_run_is_always_labelled_and_other_runs_need_the_file() {
        let concept = json!({"config": {"policy": CONCEPT_POLICY}});
        let plain = json!({"config": {"policy": "deterministic"}});
        let none = task_with(None);
        assert!(read(none.path(), &concept).unwrap().concept);
        assert!(read(none.path(), &concept).unwrap().section_lines);
        assert!(read(none.path(), &plain).is_none());
        let see_through = task_with(Some(
            json!({"schema": SCHEMA, "whole_vessel_first": true, "see_through": true}),
        ));
        let shown = read(see_through.path(), &concept).unwrap();
        assert!(shown.concept && shown.see_through && shown.section_lines);
        let other = task_with(Some(json!({"schema": "other", "see_through": true})));
        assert!(read(other.path(), &plain).is_none());
    }
}
