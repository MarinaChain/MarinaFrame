//! Errors returned to the UI: `{ code, message }` with a plain-language message.
use serde::{Deserialize, Serialize};

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
pub struct AppError {
    pub code: String,
    pub message: String,
}

pub type AppResult<T> = Result<T, AppError>;

impl AppError {
    pub fn new(code: &str, message: &str) -> Self {
        Self {
            code: code.into(),
            message: message.into(),
        }
    }
    /// Wrap an error code from the controller or the file helpers.
    pub fn from_code(code: impl Into<String>) -> Self {
        let code = code.into();
        let message = plain_message(&code);
        Self { code, message }
    }
}
impl From<String> for AppError {
    fn from(code: String) -> Self {
        Self::from_code(code)
    }
}
impl From<&str> for AppError {
    fn from(code: &str) -> Self {
        Self::from_code(code)
    }
}
impl std::fmt::Display for AppError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{}", self.message)
    }
}

/// Plain-language text for the codes that people can reach from the app.
/// Other codes keep their code in the text so that a report can name them.
pub fn plain_message(code: &str) -> String {
    let text = match code {
        "task_already_running" => "This run is busy with another action.",
        "task_missing" | "invalid_task_root" | "task_not_found" => "This run cannot be found.",
        "controller_binary_changed" => {
            "This run was made with a different build of MarinaFrame. Start a new run to continue."
        }
        "stale_or_foreign_intervention" => "The run changed in the meantime. Try again.",
        "intervention_requires_reconciled_uncancelled_state" => {
            "Clear the cancel request or let the pending step finish first."
        }
        "unknown_or_unsupported_candidate" => "That line cannot be chosen.",
        "uninspected_section" => "That section has not been read yet.",
        "source_spec_missing_or_symlink" => "The spec file was not found.",
        "worker_python_missing" => "Python was not found. Choose it in Settings.",
        "terminal_task_requires_explicit_source_backed_intervention" => {
            "This run is finished. Choose another line to change it."
        }
        "action_in_progress" => "Another action is already running on this run.",
        "live_runs_are_read_only" => "Runs that use the model can only be viewed in the app.",
        "unsafe_artifact_path"
        | "artifact_symlink"
        | "artifact_missing"
        | "artifact_not_regular" => "That file is not available.",
        "artifact_type_not_allowed" => "Only images and 3D models can be opened.",
        "artifact_too_large" => "That file is too large to open.",
        "invalid_settings" => "The settings are not valid.",
        "replacement_file_invalid" => {
            "The replacement could not be read with this page and scale. Choose a readable drawing."
        }
        "sheet_resume_pending" => "Resume the pending run action before replacing a sheet.",
        "not_built_yet" => "This run has no model to change yet.",
        "revision_instruction" => "Say what to fix in up to 500 characters.",
        "revision_needs_region_range_or_sections" => "Mark a region or pick a section first.",
        "revision_region_has_no_sections" | "revision_range_has_no_sections" => {
            "No section lies in the marked range."
        }
        "revision_requires_live_draft_run" => "Mark and revise needs a run that uses the model.",
        "revision_has_no_unkept_edit" => "Every edit of this revision is already kept.",
        "revision_already_forced" => "This revision was already kept.",
        _ => "",
    };
    if text.is_empty() {
        format!("The action could not be completed ({code}).")
    } else {
        text.into()
    }
}
