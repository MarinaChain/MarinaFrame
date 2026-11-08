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
    /// The model chose a traced line for a station (W17c).
    ModelChoice,
    /// The model wrote the curve of a section (W17c).
    ModelAuthored,
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
    /// Where the draft's curve for this section came from. Only in a draft build.
    pub source: Option<SectionSource>,
    pub candidates: Vec<CandidateView>,
}

/// Source label of one section of a draft build: `traced`, `repaired`,
/// `interpolated`, `ai_inferred`, `ai_corrected` or `omitted`.
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct SectionSource {
    pub label: String,
    /// The model's one-line basis, for the AI labels.
    pub basis: Option<String>,
}

/// How many sections of a draft carry one source label.
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
pub struct SourceCount {
    pub label: String,
    pub count: usize,
}

/// One live-model step: the tool it chose and the reason it gave.
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct ActivityStep {
    pub sequence: u64,
    pub tool: String,
    pub reason: String,
}

/// What the live model did in a run. Absent for a deterministic run.
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct ModelActivity {
    pub steps: Vec<ActivityStep>,
    pub requests: usize,
    pub prompt_tokens: u64,
    pub completion_tokens: u64,
    /// Sum of the list costs that receipts report, in USD.
    pub list_cost_usd: f64,
    /// False when a receipt reports no list cost; the sum is then a lower bound.
    pub list_cost_complete: bool,
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
    /// Sections per source label of the current draft build, in a fixed order.
    pub source_counts: Vec<SourceCount>,
    /// Warnings of the current draft build (repairs, fairing). Not errors.
    pub warnings: Vec<String>,
    pub activity: Option<ModelActivity>,
    pub evidence: Value,
    /// Whole-vessel parts (APP_SPEC "Whole-vessel parts"); None without whole-vessel output.
    #[serde(default)]
    pub components: Option<Vec<ComponentView>>,
    /// A person's sign-off of the parts ("usable as a starting model"); the run stays a draft.
    #[serde(default)]
    pub sign_off: Option<SignOffView>,
    /// The whole-vessel GLB for the 3D view, when the run has one.
    #[serde(default)]
    pub whole_vessel_model: Option<WholeVesselModel>,
}

/// A whole-vessel model file: task-relative path, size in bytes, and whether the app loads it.
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
pub struct WholeVesselModel {
    pub glb_path: String,
    pub bytes: u64,
    pub loadable: bool,
}

/// "Signed off by <name>, <date>: usable as a starting model". Not an approval.
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
pub struct SignOffView {
    pub name: String,
    pub time_ms: u64,
    pub statement: String,
}

/// One whole-vessel part: a ship-cad result component, a plain label and the person's review.
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct ComponentView {
    pub id: String,
    pub op: String,
    pub label: String,
    /// "measured_draft" or "draft_guess" (ship-cad); both are drafts.
    pub status: String,
    pub built: bool,
    pub reason: String,
    pub view: Option<String>,
    pub bbox_m: Option<ComponentBox>,
    pub volume_m3: Option<f64>,
    /// Relative to the task folder.
    pub step_path: Option<String>,
    pub arguments: Vec<ComponentArgument>,
    /// "open", "accepted" or "marked".
    pub review: String,
    /// What the person wants changed, when the review is "marked".
    #[serde(default)]
    pub review_note: Option<String>,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct ComponentBox {
    pub min: [f64; 3],
    pub max: [f64; 3],
}

/// One argument of a part with its source label ("traced", "ai_inferred" or "guessed").
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
pub struct ComponentArgument {
    pub name: String,
    pub value: Option<String>,
    pub source: String,
    pub basis: Option<String>,
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
    /// Let the AI (DeepSeek through OpenCode Go) read the drawing and build the
    /// draft. On by default (founder decision 2026-11-08: LLM-first). Without a
    /// key the app falls back to the deterministic draft and says so.
    #[serde(default = "ai_drafting_default")]
    pub ai_drafting: bool,
}

fn ai_drafting_default() -> bool {
    true
}

/// Whether new runs use the AI. `active` is false when AI drafting is off or no
/// model key was found; runs then use the deterministic draft.
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
pub struct AiStatus {
    pub enabled: bool,
    pub key_found: bool,
    pub active: bool,
    /// Where the app looks for keys (never the keys themselves).
    pub key_file: String,
}

/// One line of the setup check: is this part ready, and what to do when it is not.
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
pub struct SetupCheck {
    pub ok: bool,
    /// The path that was checked (empty when none is set).
    pub path: String,
    /// One plain sentence for people.
    pub message: String,
}

/// The welcome screen's setup check: AI key, CAD worker (Python) and runs folder.
/// Without a key the app still works with the deterministic draft.
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
pub struct SetupStatus {
    pub ai: AiStatus,
    pub worker: SetupCheck,
    pub runs_folder: SetupCheck,
}

/// Payload of the `task-changed` event.
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
pub struct TaskChanged {
    pub task: String,
    pub sequence: u64,
}
