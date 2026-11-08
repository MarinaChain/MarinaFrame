//! Live run steps: stage L1 of `docs/design/2026-11-08-b-live-agent.md`.
//!
//! `get_live_steps` turns the event ledger into compact steps for the live view and
//! for replay: one step per model decision or code operation, with a plain sentence,
//! where on the sheet it looked (source-page pixels), the tool result, and the build
//! or score it produced. The UI never sees raw events, receipts or host paths.
//!
//! Reading is incremental. Each task keeps its parsed state in a [`LiveStore`], so a
//! call parses only event files newer than the last call. A step can absorb later
//! events (its tool result arrives, a repeat count grows); its `last_sequence` then
//! grows and the next call returns it again. The UI replaces steps by `sequence`.
use crate::error::{AppError, AppResult};
use crate::files;
use serde::Serialize;
use std::collections::HashMap;
use std::path::{Path, PathBuf};
use std::sync::Mutex;

mod builder;
mod geometry;
#[cfg(test)]
mod tests;

use builder::TaskLive;

/// Tasks whose parsed state is kept. A person watches one or two runs at a time.
const MAX_CACHED_TASKS: usize = 16;

#[derive(Clone, Copy, Debug, Serialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum StepKind {
    Survey,
    Views,
    Vessel,
    Look,
    Read,
    Strokes,
    Trace,
    Corridor,
    Assign,
    ProposeSection,
    Build,
    Render,
    Score,
    Refused,
    RepeatCollapsed,
    Finish,
    System,
    /// A person's mark-and-revise request, and its result.
    Revise,
}

/// Who took the step: the live model, a person in the app, or deterministic code.
#[derive(Clone, Copy, Debug, Serialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum Actor {
    Model,
    Person,
    Code,
}

#[derive(Clone, Copy, Debug, Serialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum ResultState {
    /// Sent to the worker; no result yet.
    Working,
    Ok,
    /// The host checked the claim and refused it (with a reason).
    Refused,
    /// The step did not finish, or a build was blocked.
    Failed,
}

#[derive(Clone, Copy, Debug, Serialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum TargetKind {
    Section,
    View,
}

/// A chip under the step: a section (station) id or a view id.
#[derive(Clone, Debug, Serialize, PartialEq)]
pub struct Target {
    pub kind: TargetKind,
    pub id: String,
}

#[derive(Clone, Copy, Debug, Serialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum MarkShape {
    /// `points_px` = top-left and bottom-right corners.
    Box,
    /// `points_px` = one point (a model click).
    Point,
    Polyline,
    /// A polyline with `half_width_px` (a trace corridor).
    Band,
}

#[derive(Clone, Copy, Debug, Serialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum Tone {
    /// Where the model looks or clicks.
    Attention,
    /// A view family or region of the sheet.
    View,
    /// A section panel.
    Panel,
    /// An enumerated ink stroke (with `tag`).
    Stroke,
    /// A line the host accepted or the model chose.
    Accepted,
    /// A section curve the model drew.
    Authored,
    /// A refused click, corridor or claim; `label` holds the reason.
    Refused,
    /// A region a person marked for revision.
    Person,
}

/// A mark on the sheet. All points are in source-page pixels.
#[derive(Clone, Debug, Serialize, PartialEq)]
pub struct Mark {
    pub shape: MarkShape,
    pub tone: Tone,
    pub points_px: Vec<[f64; 2]>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub label: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub tag: Option<u64>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub candidate_id: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub half_width_px: Option<f64>,
}

/// The tool call of a step: which operation, how long it ran, and its result.
#[derive(Clone, Debug, Serialize, PartialEq)]
pub struct ToolCard {
    pub tool: String,
    /// From the worker request to its result; None while working or without a worker.
    pub duration_ms: Option<u64>,
    pub state: ResultState,
    /// One plain sentence: "Refused: the stroke is only 3 rows long", "6 strokes".
    pub text: String,
    /// Set for a model-drawn section: whether the build kept it (the fit improved).
    #[serde(skip_serializing_if = "Option::is_none")]
    pub kept: Option<bool>,
}

/// One section of a build, for the 3D view.
#[derive(Clone, Debug, Serialize, PartialEq)]
pub struct SectionCurve {
    pub id: String,
    pub x_m: f64,
    /// Half-breadth `y` and height `z` in metres (to the millimetre), keel to deck,
    /// resampled by arc length to 64 points. Empty in a step when an earlier step
    /// already carried this build's curves (`get_hull_sections` always has them).
    pub points_yz_m: Vec<[f64; 2]>,
    /// traced, repaired, interpolated, ai_inferred, ai_corrected (None in old builds).
    pub source_label: Option<String>,
    /// RMS distance of the built cut to the drawing's ink, from the latest score of
    /// this build. None until the build is scored.
    pub ink_rms_m: Option<f64>,
}

/// A build or a score of a build.
#[derive(Clone, Debug, Serialize, PartialEq)]
pub struct RevisionInfo {
    /// Controller revision id, for example `r0002`.
    pub id: Option<String>,
    /// Build folder relative to the task, for example `domain/builds/r0002-3e4f8941c54d`.
    pub path: Option<String>,
    /// Combined fit of the build (0 to 1, higher is better).
    pub fit: Option<f64>,
    pub sections: Vec<SectionCurve>,
}

#[derive(Clone, Debug, Serialize, PartialEq)]
pub struct LiveStep {
    /// Sequence of the step's first event. The step's key.
    pub sequence: u64,
    /// Sequence of the newest event folded into the step.
    pub last_sequence: u64,
    /// Milliseconds since the run started (replay timing).
    pub time_ms: u64,
    pub kind: StepKind,
    pub actor: Actor,
    /// Short plain headline: "Listed 6 strokes in the s01 panel".
    pub title: String,
    /// The narration line: the model's `reason`, or plain text for a code step.
    pub text: String,
    /// The model's plan (`notes`), for a collapsed "Why".
    pub notes: Option<String>,
    pub targets: Vec<Target>,
    /// Where the camera goes: `[left, top, right, bottom]` in source-page pixels.
    pub attention_px: Option<[f64; 4]>,
    pub marks: Vec<Mark>,
    pub tool: Option<ToolCard>,
    pub revision: Option<RevisionInfo>,
    /// Images the step produced, as task-relative paths for `read_artifact`.
    pub images: Vec<String>,
    /// Time the model took to answer before this decision.
    pub model_ms: Option<u64>,
    pub cost_usd: Option<f64>,
    /// For `repeat_collapsed`: the `sequence` of the step that was repeated.
    pub repeat_of: Option<u64>,
    /// How many times the step happened (repeats and identical system lines).
    pub count: u32,
    /// Set on the result step of a mark-and-revise pass.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub mark_revision: Option<MarkRevision>,
}

/// The result of a person's mark-and-revise pass (`docs/APP_SPEC.md`, "Mark and revise").
#[derive(Clone, Debug, Serialize, PartialEq)]
pub struct MarkRevision {
    pub revision_id: String,
    /// kept, partly_kept, not_kept, no_edit or stopped.
    pub outcome: String,
    /// Change of the combined fit by the kept edits.
    pub fit_change: Option<f64>,
    /// How the first not-kept edit would have changed the fit (negative = worse).
    pub not_kept_fit_change: Option<f64>,
    /// A not-kept edit exists and nobody has kept it anyway yet.
    pub can_keep_anyway: bool,
    /// A person kept the not-kept edits anyway (never an engineering approval).
    pub operator_forced: bool,
}

#[derive(Clone, Copy, Debug, Serialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum InFlightKind {
    /// A model request without an answer yet.
    Model,
    /// A worker operation without a result yet.
    Worker,
}

#[derive(Clone, Debug, Serialize, PartialEq)]
pub struct InFlight {
    pub kind: InFlightKind,
    pub operation: Option<String>,
    pub since_ms: u64,
}

#[derive(Clone, Debug, Serialize, PartialEq)]
pub struct LiveSteps {
    /// Steps that are new or changed after `after_sequence`, oldest first.
    pub steps: Vec<LiveStep>,
    /// The newest event read. Pass it as `after_sequence` next time.
    pub last_sequence: u64,
    /// Wall-clock time of the first event (milliseconds since the epoch).
    pub started_ms: u64,
    /// Time of the newest event, relative to `started_ms`.
    pub elapsed_ms: u64,
    pub in_flight: Option<InFlight>,
    /// True after the run stopped (review, draft, declined, cancelled or failed).
    pub finished: bool,
}

#[derive(Clone, Debug, Serialize, PartialEq)]
pub struct HullSections {
    pub revision: Option<String>,
    pub path: String,
    pub sections: Vec<SectionCurve>,
}

/// Parsed live state per task folder. Shared by all calls of one backend.
#[derive(Default)]
pub struct LiveStore {
    tasks: Mutex<HashMap<PathBuf, TaskLive>>,
}

impl LiveStore {
    /// Steps that are new or changed after `after_sequence` (0 for all).
    pub fn steps(&self, task: &Path, after_sequence: u64) -> LiveSteps {
        let mut tasks = self.tasks.lock().unwrap_or_else(|e| e.into_inner());
        if !tasks.contains_key(task) && tasks.len() >= MAX_CACHED_TASKS {
            let oldest = tasks
                .iter()
                .min_by_key(|(_, live)| live.last_used())
                .map(|(path, _)| path.clone());
            if let Some(path) = oldest {
                tasks.remove(&path);
            }
        }
        let live = tasks
            .entry(task.to_path_buf())
            .or_insert_with(|| TaskLive::new(task));
        live.refresh(task);
        live.snapshot(after_sequence)
    }

    /// Section curves of one build. `revision` is a revision id (`r0002`) or the
    /// build path a step gave (`domain/builds/r0002-3e4f8941c54d`).
    pub fn hull_sections(&self, task: &Path, revision: &str) -> AppResult<HullSections> {
        let not_found = || AppError::new("revision_not_found", "That build cannot be found.");
        let known = self
            .tasks
            .lock()
            .unwrap_or_else(|e| e.into_inner())
            .get(task)
            .and_then(|live| live.build_path(revision));
        let (id, path) = match known {
            Some(path) => (Some(revision.to_string()), path),
            None => build_from_domain(task, revision).ok_or_else(not_found)?,
        };
        let sections = geometry::build_sections(task, &path);
        if sections.is_empty() {
            return Err(not_found());
        }
        let id = id.filter(|id| !id.contains('/'));
        Ok(HullSections {
            revision: id,
            path,
            sections,
        })
    }
}

/// Look a build up in the worker catalog (`domain/state.json` `builds`) by
/// revision id or path.
fn build_from_domain(task: &Path, revision: &str) -> Option<(Option<String>, String)> {
    let domain = files::read_domain(task)?;
    let build = domain["builds"].as_array()?.iter().rev().find(|build| {
        build["revision_id"] == revision || build["path"].as_str() == Some(revision)
    })?;
    Some((
        build["revision_id"].as_str().map(String::from),
        build["path"].as_str()?.to_string(),
    ))
}
