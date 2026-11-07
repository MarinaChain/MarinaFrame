//! Types of docs/APP_SPEC.md. Field names and shapes match the specification exactly.
use serde::{Deserialize, Serialize};
use serde_json::Value;

#[derive(Clone, Copy, Debug, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum Status {
    Running,
    NeedsReview,
    /// Controller status `draft_not_verified`: a best-effort build with open guesses.
    Draft,
    Declined,
    Failed,
    Cancelled,
    Paused,
    Blocked,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct TaskSummary {
    pub task: String,
    pub name: String,
    pub status: Status,
    pub policy: String,
    pub updated_ms: u64,
    pub sections: usize,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct SourcePage {
    pub path: String,
    pub width: u32,
    pub height: u32,
}

#[derive(Clone, Copy, Debug, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum SectionState {
    Chosen,
    /// The draft guessed this section; a person has not confirmed it.
    Guessed,
    Declined,
    NotRead,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct CandidateView {
    pub id: String,
    pub label: String,
    pub chosen: bool,
    pub selectable: bool,
    pub why: String,
    pub polyline_px: Vec<[f64; 2]>,
}

#[derive(Clone, Copy, Debug, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum GuessKind {
    BestCandidate,
    BridgedGap,
    DroppedEnd,
}

/// One choice a draft made without a person. `id` is the guess_id.
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct GuessView {
    pub id: String,
    pub kind: GuessKind,
    pub x_range_m: Option<[f64; 2]>,
    pub chosen_candidate_id: Option<String>,
    pub alternatives: Vec<String>,
    pub score: Option<f64>,
    pub reason: String,
}

#[derive(Clone, Copy, Debug, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum Resolution {
    Confirmed,
    Replaced,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct ResolvedGuessView {
    #[serde(flatten)]
    pub guess: GuessView,
    pub resolution: Resolution,
    pub resolved_candidate_id: String,
}

/// Present while the current build is a draft.
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct DraftView {
    pub status: String,
    pub guesses: Vec<GuessView>,
    pub resolved: Vec<ResolvedGuessView>,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct SectionView {
    pub id: String,
    pub x_m: f64,
    pub roi_px: [i64; 4],
    pub state: SectionState,
    pub reason: String,
    pub guess: Option<GuessView>,
    pub candidates: Vec<CandidateView>,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct ModelView {
    pub stl_path: String,
    pub length_m: f64,
    pub beam_m: f64,
    pub depth_m: f64,
    pub volume_m3: Option<f64>,
}

#[derive(Clone, Copy, Debug, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum CheckResult {
    Pass,
    Fail,
    NotRun,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct CheckView {
    pub name: String,
    pub value: String,
    pub limit: Option<String>,
    pub result: CheckResult,
}

#[derive(Clone, Copy, Debug, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum CallState {
    Completed,
    Failed,
    NotSent,
    Unknown,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct ProviderImage {
    pub path: String,
    pub label: String,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct ProviderCallView {
    pub id: String,
    pub state: CallState,
    pub images: Vec<ProviderImage>,
    pub answer: String,
    pub accepted: bool,
    pub prompt_tokens: Option<u64>,
    pub completion_tokens: Option<u64>,
    pub cost_usd: Option<f64>,
    pub key_slot: Option<u64>,
}

#[derive(Clone, Copy, Debug, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum Tone {
    Info,
    Warning,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct NoticeView {
    pub id: String,
    pub tone: Tone,
    pub text: String,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct TaskView {
    pub summary: TaskSummary,
    pub revision: Option<String>,
    pub source_page: Option<SourcePage>,
    pub sections: Vec<SectionView>,
    pub model: Option<ModelView>,
    pub checks: Vec<CheckView>,
    pub provider: Vec<ProviderCallView>,
    pub notices: Vec<NoticeView>,
    pub draft: Option<DraftView>,
    pub evidence: Value,
}

#[derive(Clone, Copy, Debug, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum EventKind {
    Read,
    Choose,
    Build,
    Render,
    Check,
    Model,
    Finish,
    Other,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct EventView {
    pub sequence: u64,
    pub time_ms: u64,
    pub text: String,
    pub kind: EventKind,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct Artifact {
    pub mime: String,
    pub base64: String,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct Dataset {
    pub name: String,
    pub path: String,
    pub bytes: u64,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum Theme {
    System,
    Light,
    Dark,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct Settings {
    pub runs_folder: String,
    pub worker_python: String,
    pub theme: Theme,
}

/// Payload of the `task-changed` event.
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
pub struct TaskChanged {
    pub task: String,
    pub sequence: u64,
}
