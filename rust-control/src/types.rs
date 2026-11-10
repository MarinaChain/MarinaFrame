use crate::util::{self, Result};
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::collections::BTreeSet;

pub const CONTROL_VERSION: &str = "marinaframe.control.v1";
pub const WORKER_VERSION: &str = "marinaframe.worker.v1";
/// The default model (the desktop app's); `models` holds the allow-list.
pub const GO_MODEL: &str = crate::models::DEEPSEEK_V4_1_FLASH;
pub const GO_ENDPOINT: &str = "https://opencode.ai/inference/go/openai/v1/chat/completions";

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum Policy {
    Deterministic,
    Live,
}
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum Status {
    Ready,
    Running,
    /// A live worker has no new progress; a person can keep waiting or stop it.
    Stalled,
    Paused,
    AwaitingHumanReview,
    Abstained,
    Blocked,
    ValidationFailed,
    Interrupted,
    Cancelled,
    ProviderFailed,
    NoProgress,
    /// A best-effort draft exists with at least one open guess. It is never
    /// review-ready: finalization and `Store::verify` refuse open guesses.
    DraftNotVerified,
}
/// What a policy does when the source has no unique supported interpretation.
#[derive(Clone, Debug, Default, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum OnAmbiguity {
    /// Decline (abstain). Tasks created before drafts existed read as this.
    #[default]
    Abstain,
    /// Build a draft that records each ambiguous choice as an open guess.
    Draft,
}
impl OnAmbiguity {
    fn is_abstain(&self) -> bool {
        *self == Self::Abstain
    }
}
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum View {
    Body,
    Plan,
    Profile,
    Oblique,
}
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum FinishOutcome {
    CandidateReadyForReview,
    Abstain,
}

#[derive(Clone, Debug, Default, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Empty {}
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Inspect {
    #[serde(skip_serializing_if = "Option::is_none")]
    pub section_ids: Option<Vec<String>>,
}
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Selection {
    pub section_id: String,
    pub candidate_id: String,
}
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Select {
    pub selections: Vec<Selection>,
}
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Render {
    pub view: View,
}
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Finish {
    pub outcome: FinishOutcome,
    pub summary: String,
}

// ------------------------------------------------ model investigation tools
//
// The live model may look at any region at any zoom, trace inside a corridor
// that it draws on a view, claim station identities and sheet setups, and ask
// a person. Every argument is bounded here; the harness executes the tool and
// checks every claim. No argument is a line, a path, code, a gate or a review
// state: a traced line comes only from source ink.

/// Pixel rectangle [left, top, right, bottom] on the captured sheet.
pub type RegionPx = [u32; 4];
pub const MAX_SHEET_PX: u32 = 1_000_000;

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ViewRegion {
    pub region_px: RegionPx,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub max_side_px: Option<u32>,
}
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum ReadSubject {
    Labels,
    ScaleBar,
    Dimensions,
    TitleBlock,
}
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ReadRegion {
    pub region_px: RegionPx,
    pub subject: ReadSubject,
}
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct TraceCorridor {
    pub section_id: String,
    /// The view on which the corridor is drawn; points are in its pixels.
    pub view_id: String,
    pub path_px: Vec<[f64; 2]>,
    pub half_width_px: f64,
}
/// Ask the harness to trace every ink stroke of a section's panel (at
/// scanlines, or at one height) and show them with numbered tags.
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct EnumerateStrokes {
    pub section_id: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub height_m: Option<f64>,
}
/// A point on a curve in a view's pixels; the harness follows the ink stroke
/// through it and traces and verifies it like a corridor.
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct TraceFromPoint {
    pub section_id: String,
    pub view_id: String,
    pub point_px: [f64; 2],
}
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct AssignStation {
    pub section_id: String,
    pub candidate_id: String,
    pub label_view_id: String,
    /// What the model reads on the label view: a claim, not a fact.
    pub label_text: String,
    pub reason: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub comparison_id: Option<String>,
}
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum SheetView {
    Body,
    Plan,
    Profile,
}
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ProposeSheetSetup {
    pub view: SheetView,
    pub region_px: RegionPx,
    pub pixels_per_metre: f64,
    pub grid_spacing_m: f64,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub centreline_px: Option<f64>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub baseline_px: Option<f64>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub x_origin_px: Option<f64>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub x_direction: Option<i8>,
    pub evidence_view_id: String,
    pub scale_claim: String,
    pub reason: String,
}
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct CompareViews {
    pub section_id: String,
    pub candidate_id: String,
    pub setup_id: String,
    pub heights_m: Vec<f64>,
}
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct AskPerson {
    pub question: String,
}
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct RecallView {
    pub view_id: String,
}
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct DescribeViews {
    pub views: Vec<Value>,
}
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct DescribeVessel {
    pub description: Value,
}

/// Description claims stay flexible, but cannot carry unbounded model output.
fn bounded_description(value: &Value, depth: usize) -> bool {
    if depth > 10 {
        return false;
    }
    match value {
        Value::Null | Value::Bool(_) => true,
        Value::Number(n) => n.as_f64().is_some_and(f64::is_finite),
        Value::String(s) => s.chars().count() <= 2000 && !s.chars().any(char::is_control),
        Value::Array(values) => {
            values.len() <= 300 && values.iter().all(|v| bounded_description(v, depth + 1))
        }
        Value::Object(values) => {
            values.len() <= 64
                && values.iter().all(|(key, value)| {
                    bounded_text(key, 64) && bounded_description(value, depth + 1)
                })
        }
    }
}
/// `propose_section`: a section shape the model writes (draft mode).
#[path = "authoring.rs"]
pub mod authoring;

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(tag = "tool", content = "arguments", rename_all = "snake_case")]
pub enum Operation {
    InspectSource(Inspect),
    SelectContours(Select),
    BuildProvisional(Empty),
    BuildDraft(Empty),
    RenderCandidate(Render),
    ValidateCandidate(Empty),
    Finish(Finish),
    ViewRegion(ViewRegion),
    ReadRegion(ReadRegion),
    TraceCorridor(TraceCorridor),
    TraceFromPoint(TraceFromPoint),
    EnumerateStrokes(EnumerateStrokes),
    AssignStation(AssignStation),
    ProposeSheetSetup(ProposeSheetSetup),
    CompareViews(CompareViews),
    AskPerson(AskPerson),
    RecallView(RecallView),
    SurveySheet(Empty),
    DescribeViews(DescribeViews),
    DescribeVessel(DescribeVessel),
    ProposeSection(authoring::ProposeSection),
}
fn bounded_text(text: &str, chars: usize) -> bool {
    let count = text.chars().count();
    (1..=chars).contains(&count) && text.len() <= 4 * chars && !text.chars().any(char::is_control)
}
fn finite_in(value: f64, low: f64, high: f64) -> bool {
    value.is_finite() && (low..=high).contains(&value)
}
fn valid_region(region: &RegionPx) -> bool {
    region.iter().all(|v| *v <= MAX_SHEET_PX) && region[2] > region[0] && region[3] > region[1]
}
impl Operation {
    pub fn name(&self) -> &'static str {
        match self {
            Self::InspectSource(_) => "inspect_source",
            Self::SelectContours(_) => "select_contours",
            Self::BuildProvisional(_) => "build_provisional",
            Self::BuildDraft(_) => "build_draft",
            Self::RenderCandidate(_) => "render_candidate",
            Self::ValidateCandidate(_) => "validate_candidate",
            Self::Finish(_) => "finish",
            Self::ViewRegion(_) => "view_region",
            Self::ReadRegion(_) => "read_region",
            Self::TraceCorridor(_) => "trace_corridor",
            Self::TraceFromPoint(_) => "trace_from_point",
            Self::EnumerateStrokes(_) => "enumerate_strokes",
            Self::AssignStation(_) => "assign_station",
            Self::ProposeSheetSetup(_) => "propose_sheet_setup",
            Self::CompareViews(_) => "compare_views",
            Self::AskPerson(_) => "ask_person",
            Self::RecallView(_) => "recall_view",
            Self::SurveySheet(_) => "survey_sheet",
            Self::DescribeViews(_) => "describe_views",
            Self::DescribeVessel(_) => "describe_vessel",
            Self::ProposeSection(_) => "propose_section",
        }
    }
    /// The model investigation tools. They exist only in draft mode, where an
    /// accepted model claim is an open guess that a person must confirm.
    pub fn is_investigation(&self) -> bool {
        matches!(
            self,
            Self::ViewRegion(_)
                | Self::ReadRegion(_)
                | Self::TraceCorridor(_)
                | Self::TraceFromPoint(_)
                | Self::EnumerateStrokes(_)
                | Self::AssignStation(_)
                | Self::ProposeSheetSetup(_)
                | Self::CompareViews(_)
                | Self::AskPerson(_)
                | Self::RecallView(_)
                | Self::SurveySheet(_)
                | Self::DescribeViews(_)
                | Self::DescribeVessel(_)
                | Self::ProposeSection(_)
        )
    }
    /// The section a tool acts on, if any.
    pub fn section_id(&self) -> Option<&str> {
        match self {
            Self::TraceCorridor(x) => Some(&x.section_id),
            Self::TraceFromPoint(x) => Some(&x.section_id),
            Self::EnumerateStrokes(x) => Some(&x.section_id),
            Self::AssignStation(x) => Some(&x.section_id),
            Self::CompareViews(x) => Some(&x.section_id),
            Self::ProposeSection(x) => Some(&x.section_id),
            _ => None,
        }
    }
    fn validate_investigation(&self) -> Result<()> {
        let id = |s: &str| util::valid_id(s, 64);
        let ok = match self {
            Self::ViewRegion(x) => {
                valid_region(&x.region_px)
                    && x.max_side_px.is_none_or(|n| (256..=1024).contains(&n))
            }
            Self::ReadRegion(x) => valid_region(&x.region_px),
            Self::TraceCorridor(x) => {
                util::valid_section_id(&x.section_id)
                    && id(&x.view_id)
                    && (2..=24).contains(&x.path_px.len())
                    && x.path_px
                        .iter()
                        .all(|p| p.iter().all(|v| finite_in(*v, 0., 4096.)))
                    && finite_in(x.half_width_px, 1., 64.)
            }
            Self::EnumerateStrokes(x) => {
                util::valid_section_id(&x.section_id)
                    && x.height_m.is_none_or(|h| finite_in(h, -100., 1000.))
            }
            Self::TraceFromPoint(x) => {
                util::valid_section_id(&x.section_id)
                    && id(&x.view_id)
                    && x.point_px.iter().all(|v| finite_in(*v, 0., 4096.))
            }
            Self::AssignStation(x) => {
                util::valid_section_id(&x.section_id)
                    && id(&x.candidate_id)
                    && id(&x.label_view_id)
                    && bounded_text(&x.label_text, 64)
                    && bounded_text(&x.reason, 300)
                    && x.comparison_id.as_deref().is_none_or(id)
            }
            Self::ProposeSheetSetup(x) => {
                valid_region(&x.region_px)
                    && finite_in(x.pixels_per_metre, 1e-3, 1e5)
                    && finite_in(x.grid_spacing_m, 1e-3, 100.)
                    && [x.centreline_px, x.baseline_px, x.x_origin_px]
                        .iter()
                        .flatten()
                        .all(|v| finite_in(*v, 0., MAX_SHEET_PX as f64))
                    && x.x_direction.is_none_or(|d| d == 1 || d == -1)
                    && id(&x.evidence_view_id)
                    && bounded_text(&x.scale_claim, 128)
                    && bounded_text(&x.reason, 300)
            }
            Self::CompareViews(x) => {
                util::valid_section_id(&x.section_id)
                    && id(&x.candidate_id)
                    && id(&x.setup_id)
                    && (1..=12).contains(&x.heights_m.len())
                    && x.heights_m.iter().all(|h| finite_in(*h, -100., 1000.))
            }
            Self::AskPerson(x) => bounded_text(&x.question, 512),
            Self::RecallView(x) => id(&x.view_id),
            Self::DescribeViews(x) => {
                let mut seen = BTreeSet::new();
                (1..=32).contains(&x.views.len())
                    && x.views.iter().all(|view| {
                        view.is_object()
                            && bounded_description(view, 0)
                            && view["view_id"]
                                .as_str()
                                .is_some_and(|s| id(s) && seen.insert(s))
                            && view["kind"].as_str().is_some_and(|kind| {
                                [
                                    "body",
                                    "body_fore",
                                    "body_aft",
                                    "plan",
                                    "profile",
                                    "title_block",
                                    "offsets_table",
                                    "other",
                                ]
                                .contains(&kind)
                            })
                            && serde_json::from_value::<RegionPx>(view["region_px"].clone())
                                .is_ok_and(|region| valid_region(&region))
                    })
                    && serde_json::to_vec(&x.views).is_ok_and(|bytes| bytes.len() <= 32_768)
            }
            Self::DescribeVessel(x) => {
                bounded_description(&x.description, 0)
                    && serde_json::to_vec(&x.description).is_ok_and(|bytes| bytes.len() <= 65_536)
            }
            Self::ProposeSection(x) => x.valid(),
            _ => true,
        };
        if ok {
            Ok(())
        } else {
            Err("investigation_argument_bounds".into())
        }
    }
    pub fn args(&self) -> Value {
        serde_json::to_value(self).unwrap()["arguments"].clone()
    }
    pub fn validate(&self) -> Result<()> {
        match self {
            Self::InspectSource(x) => {
                if let Some(ids) = &x.section_ids {
                    let mut seen = BTreeSet::new();
                    if ids.is_empty()
                        || ids.len() > 300
                        || ids
                            .iter()
                            .any(|s| !util::valid_section_id(s) || !seen.insert(s))
                    {
                        return Err("invalid_section_ids".into());
                    }
                }
            }
            Self::SelectContours(x) => {
                let mut seen = BTreeSet::new();
                if x.selections.is_empty()
                    || x.selections.len() > 300
                    || x.selections.iter().any(|s| {
                        !util::valid_section_id(&s.section_id)
                            || !util::valid_id(&s.candidate_id, 64)
                            || !seen.insert(&s.section_id)
                    })
                {
                    return Err("invalid_selection_ids".into());
                }
            }
            Self::Finish(x) if x.summary.len() > 2048 || x.summary.chars().count() > 512 => {
                return Err("summary_limit".into());
            }
            _ => (),
        }
        self.validate_investigation()
    }
}

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Decision {
    pub tool: String,
    pub arguments: Value,
    pub reason: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub notes: Option<String>,
}
impl Decision {
    pub fn normalize(&mut self) {
        self.reason = self.reason.chars().take(512).collect();
        self.notes = self
            .notes
            .as_ref()
            .map(|text| text.chars().take(600).collect());
        fn clamp(value: &mut Value, low: f64, high: f64, integer: bool) {
            if let Some(number) = value.as_f64() {
                let number = number.clamp(low, high);
                *value = if integer {
                    json!(number.round() as i64)
                } else {
                    json!(number)
                };
            }
        }
        for (key, low, high, integer) in [
            ("max_side_px", 256., 1024., true),
            ("half_width_px", 1., 64., false),
            ("height_m", -100., 1000., false),
            ("pixels_per_metre", 0.001, 100000., false),
            ("grid_spacing_m", 0.001, 100., false),
            ("centreline_px", 0., 1000000., false),
            ("baseline_px", 0., 1000000., false),
            ("x_origin_px", 0., 1000000., false),
            ("fullness", 0.5, 1.5, false),
            ("beam_m", 0.001, 1000., false),
            ("draft_m", 0.001, 1000., false),
            ("bilge_radius_m", 0., 1000., false),
            ("deadrise_deg", 0., 60., false),
        ] {
            if let Some(value) = self.arguments.get_mut(key) {
                clamp(value, low, high, integer);
            }
        }
        for key in ["point_px", "heights_m", "region_px"] {
            if let Some(values) = self.arguments[key].as_array_mut() {
                for value in values {
                    clamp(
                        value,
                        if key == "heights_m" { -100. } else { 0. },
                        if key == "region_px" {
                            1000000.
                        } else if key == "heights_m" {
                            1000.
                        } else {
                            4096.
                        },
                        key == "region_px",
                    );
                }
            }
        }
        for key in ["path_px", "offsets_m"] {
            if let Some(points) = self.arguments[key].as_array_mut() {
                for point in points {
                    if let Some(values) = point.as_array_mut() {
                        for value in values {
                            clamp(
                                value,
                                if key == "offsets_m" { -1000. } else { 0. },
                                if key == "offsets_m" { 1000. } else { 4096. },
                                false,
                            );
                        }
                    }
                }
            }
        }
        if let Some(number) = self.arguments["x_direction"].as_f64() {
            self.arguments["x_direction"] = json!(if number <= 0. { -1 } else { 1 });
        }
        if let Some(rect) = self.arguments["region_px"].as_array_mut() {
            if rect.len() == 4 && rect.iter().all(Value::is_number) {
                for (low, high) in [(0, 2), (1, 3)] {
                    if rect[high].as_i64() <= rect[low].as_i64() {
                        let start = rect[low].as_i64().unwrap().min(999999);
                        rect[low] = json!(start);
                        rect[high] = json!(start + 1);
                    }
                }
            }
        }
        if let Some(text) = self.arguments["reason"].as_str() {
            self.arguments["reason"] = json!(text.chars().take(300).collect::<String>());
        }
        if let Some(object) = self.arguments.as_object_mut() {
            object.retain(|_, value| !value.is_null());
        }
    }
    pub fn operation(&self) -> Result<Operation> {
        if self.reason.chars().count() > 512 || self.reason.len() > 2048 {
            return Err("reason_limit".into());
        }
        if self
            .notes
            .as_ref()
            .is_some_and(|notes| notes.chars().count() > 600 || notes.len() > 2400)
        {
            return Err("notes_limit".into());
        }
        let op: Operation =
            serde_json::from_value(json!({"tool":self.tool,"arguments":self.arguments}))
                .map_err(|_| "operation_contract")?;
        op.validate()?;
        Ok(op)
    }
}

/// Upper bound for one model request's output tokens (thinking needs room for reasoning).
pub const MAX_OUTPUT_TOKENS_PER_REQUEST: u64 = 32_768;
/// Upper bound for one model request's wall time (thinking requests are slow).
pub const MAX_REQUEST_WALL_SECONDS: u64 = 600;

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct OperationalLimits {
    /// Optional absolute safety cap in seconds. Zero (default) disables it.
    /// No-progress supervision remains active regardless of this cap.
    pub worker_wall_seconds: u64,
    pub request_wall_seconds: u64,
    pub worker_memory_bytes: u64,
    pub worker_cpu_seconds: u64,
    pub task_disk_bytes: u64,
    pub max_output_tokens_per_request: u64,
    pub max_observation_bytes: usize,
    pub max_images_per_request: usize,
    pub max_image_bytes: usize,
    pub max_repeated_action: u64,
    #[serde(default, skip_serializing_if = "is_false")]
    pub investigation_thinking: bool,
    #[serde(default, skip_serializing_if = "is_false")]
    pub investigation_conversation: bool,
    #[serde(default, skip_serializing_if = "is_false")]
    pub phase1_only: bool,
    #[serde(
        default = "default_context_tokens",
        skip_serializing_if = "is_default_context_tokens"
    )]
    pub max_context_tokens: u64,
    #[serde(default, skip_serializing_if = "is_zero")]
    pub investigation_temperature: f64,
    pub max_requests: Option<u64>,
    pub max_total_tokens: Option<u64>,
    pub max_spend_usd: Option<f64>,
}
fn default_context_tokens() -> u64 {
    // DeepSeek V4.1 Flash takes about 128k tokens; keep headroom for the reply and the estimate.
    100_000
}
fn is_default_context_tokens(value: &u64) -> bool {
    *value == default_context_tokens()
}
fn is_false(value: &bool) -> bool {
    !value
}
fn is_zero(value: &f64) -> bool {
    *value == 0.0
}

impl Default for OperationalLimits {
    fn default() -> Self {
        Self {
            worker_wall_seconds: 0,
            // Generous: thinking requests took up to 45 s and the old 90 s limit cut them off.
            request_wall_seconds: 300,
            worker_memory_bytes: 5 * 1024 * 1024 * 1024,
            worker_cpu_seconds: 480,
            task_disk_bytes: 2 * 1024 * 1024 * 1024,
            // Thinking spends output tokens on reasoning before the answer.
            max_output_tokens_per_request: 16_384,
            max_observation_bytes: 96_000,
            max_images_per_request: 4,
            max_image_bytes: 196_608,
            max_repeated_action: 3,
            investigation_thinking: false,
            investigation_conversation: false,
            phase1_only: false,
            max_context_tokens: default_context_tokens(),
            investigation_temperature: 0.0,
            max_requests: Some(80),
            max_total_tokens: None,
            max_spend_usd: None,
        }
    }
}
impl OperationalLimits {
    pub fn validate(&self) -> Result<()> {
        if !(1..=MAX_REQUEST_WALL_SECONDS).contains(&self.request_wall_seconds)
            || !(256 * 1024 * 1024..=8 * 1024 * 1024 * 1024).contains(&self.worker_memory_bytes)
            || !(1..=600).contains(&self.worker_cpu_seconds)
            || !(32 * 1024 * 1024..=8 * 1024 * 1024 * 1024).contains(&self.task_disk_bytes)
            || !(16..=MAX_OUTPUT_TOKENS_PER_REQUEST).contains(&self.max_output_tokens_per_request)
            || !(4096..=196_608).contains(&self.max_observation_bytes)
            || self.max_images_per_request > 6
            || !(1024..=1_048_576).contains(&self.max_image_bytes)
            || !(1..=8).contains(&self.max_repeated_action)
            || !(8_000..=120_000).contains(&self.max_context_tokens)
            || !self.investigation_temperature.is_finite()
            || !(0.0..=2.0).contains(&self.investigation_temperature)
            || self.max_spend_usd.is_some_and(|x| !x.is_finite() || x < 0.)
        {
            return Err("invalid_operational_limits".into());
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Config {
    pub worker_python: String,
    pub worker_source: Option<String>,
    pub source_spec: String,
    pub policy: Policy,
    pub limits: OperationalLimits,
    pub provider_transfer_authorized: bool,
    pub authorization_basis: String,
    /// The first model of the run's ordered model list.
    pub model: String,
    pub binary_sha256: String,
    /// Not serialized when `abstain`, so the hashes of older ledger events and
    /// their configurations stay unchanged.
    #[serde(default, skip_serializing_if = "OnAmbiguity::is_abstain")]
    pub on_ambiguity: OnAmbiguity,
    /// The models after `model`, used in order when OpenCode Go rate-limits
    /// the current one. Not serialized when empty, so older configurations
    /// keep their hashes.
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub fallback_models: Vec<String>,
}
impl Config {
    /// The ordered model list: `model`, then `fallback_models`.
    pub fn models(&self) -> Vec<&str> {
        std::iter::once(self.model.as_str())
            .chain(self.fallback_models.iter().map(String::as_str))
            .collect()
    }
}
#[derive(Clone, Debug, Default, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Counters {
    pub operations: u64,
    pub builds: u64,
    pub operator_actions: u64,
    pub policy_decisions: u64,
    pub requests_intended: u64,
    pub requests_completed: u64,
    pub requests_failed: u64,
    pub requests_unknown: u64,
    pub requests_not_sent: u64,
    pub prompt_tokens: u64,
    pub completion_tokens: u64,
    pub observed_cost_usd: f64,
    pub requests_without_cost: u64,
}
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Pending {
    pub kind: String,
    pub id: String,
    pub operation: String,
    pub response_path: String,
    pub request_path: String,
    pub domain_before: Option<String>,
    pub started_ms: u64,
}
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct State {
    pub schema_version: String,
    pub task_id: String,
    pub status: Status,
    pub termination_reason: Option<String>,
    pub config: Config,
    pub counters: Counters,
    pub source_manifest_sha256: Option<String>,
    pub domain_checkpoint_sha256: Option<String>,
    pub worker_implementation_sha256: Option<String>,
    /// Audit implementation identity pinned from the initialize receipt. Absent in
    /// tasks created before the pin existed (not serialized when absent, so the
    /// hashes of old ledger events stay valid); such tasks cannot finalize.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub audit_implementation_sha256: Option<String>,
    pub generation_id: Option<String>,
    pub revision_id: Option<String>,
    pub pending: Option<Pending>,
    pub staged_decision: Option<Decision>,
    pub domain: Value,
    pub last_observation: Value,
    pub engineering_approved: bool,
    pub action_fingerprints: std::collections::BTreeMap<String, u64>,
    pub created_ms: u64,
    /// The model in use after a rate-limit switch (`model_switched` event);
    /// absent while the run uses its first model.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub active_model: Option<String>,
}
impl State {
    /// The model the next request uses.
    pub fn current_model(&self) -> &str {
        self.active_model.as_deref().unwrap_or(&self.config.model)
    }
    pub fn validate(&self) -> Result<()> {
        if self.schema_version != CONTROL_VERSION
            || self.engineering_approved
            || !util::valid_id(&self.task_id, 128)
            || crate::models::check_list(&self.config.models()).is_err()
            || !self.config.models().contains(&self.current_model())
            || !util::valid_hash(&self.config.binary_sha256)
            || !self.counters.observed_cost_usd.is_finite()
            || self.counters.observed_cost_usd < 0.
        {
            return Err("invalid_state_contract".into());
        }
        self.config.limits.validate()?;
        for h in [
            &self.source_manifest_sha256,
            &self.domain_checkpoint_sha256,
            &self.worker_implementation_sha256,
            &self.audit_implementation_sha256,
        ]
        .into_iter()
        .flatten()
        {
            if !util::valid_hash(h) {
                return Err("invalid_state_hash".into());
            }
        }
        if self.pending.as_ref().is_some_and(|p| {
            !["worker", "provider"].contains(&p.kind.as_str()) || !util::valid_id(&p.id, 128)
        }) {
            return Err("invalid_pending_intent".into());
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct WorkerResources {
    pub wall_seconds: f64,
    pub worker_cpu_seconds: f64,
    pub children_cpu_seconds: f64,
    pub worker_peak_rss_kib: u64,
    pub children_peak_rss_kib: u64,
    pub rss_interpretation: String,
}
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct WorkerResponse {
    pub protocol: String,
    pub request_id: String,
    pub operation: String,
    pub execution_state: String,
    pub result: Option<Value>,
    pub domain: Option<Value>,
    pub domain_checkpoint_sha256: Option<String>,
    pub implementation_sha256: String,
    pub error_code: Option<String>,
    pub resources: WorkerResources,
}
impl WorkerResponse {
    pub fn validate(&self, id: &str, op: &str) -> Result<()> {
        if self.protocol != WORKER_VERSION
            || self.request_id != id
            || self.operation != op
            || !util::valid_hash(&self.implementation_sha256)
            || !["completed", "failed", "cancelled"].contains(&self.execution_state.as_str())
        {
            return Err("worker_response_identity".into());
        }
        if self.execution_state == "completed"
            && (self.result.is_none()
                || self.domain.is_none()
                || self.error_code.is_some()
                || !self
                    .domain_checkpoint_sha256
                    .as_deref()
                    .is_some_and(util::valid_hash))
        {
            return Err("worker_response_incomplete".into());
        }
        let r = &self.resources;
        if [r.wall_seconds, r.worker_cpu_seconds, r.children_cpu_seconds]
            .iter()
            .any(|n| !n.is_finite() || *n < 0.)
            || r.worker_peak_rss_kib == 0
            || r.worker_peak_rss_kib > 1 << 40
            || r.children_peak_rss_kib > 1 << 40
            || r.rss_interpretation != "separate process maxima; not summed process-tree peak"
        {
            return Err("worker_resource_contract".into());
        }
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn operations_reject_code_unknown_fields_units_and_duplicate_ids() {
        for v in [
            json!({"tool":"run_shell","arguments":{},"reason":"x"}),
            json!({"tool":"build_provisional","arguments":{"units":"mm"},"reason":"x"}),
            json!({"tool":"select_contours","arguments":{"selections":[{"section_id":"a","candidate_id":"b"},{"section_id":"a","candidate_id":"c"}]},"reason":"x"}),
            json!({"tool":"render_candidate","arguments":{"view":"body;rm"},"reason":"x"}),
        ] {
            let d: Decision = serde_json::from_value(v).unwrap();
            assert!(d.operation().is_err());
        }
    }
    #[test]
    fn normalization_keeps_oversized_notes_and_numeric_proposals_usable() {
        let mut d: Decision = serde_json::from_value(json!({"tool":"trace_from_point","arguments":{"section_id":"s1","view_id":"view-1","point_px":[-20,9000]},"reason":"r","notes":"é".repeat(700)})).unwrap();
        d.normalize();
        assert_eq!(d.notes.as_ref().unwrap().chars().count(), 600);
        assert_eq!(d.arguments["point_px"], json!([0.0, 4096.0]));
        assert!(d.operation().is_ok());
        let mut crop: Decision = serde_json::from_value(json!({"tool":"view_region","arguments":{"region_px":[-2,10,0,5],"max_side_px":9000},"reason":"r"})).unwrap();
        crop.normalize();
        assert!(crop.operation().is_ok());
        assert_eq!(crop.arguments["max_side_px"], 1024);
    }
    #[test]
    fn decision_notes_are_optional_bounded_and_backward_compatible() {
        let old = json!({"tool":"build_draft","arguments":{},"reason":"ready"});
        let decision: Decision = serde_json::from_value(old.clone()).unwrap();
        assert_eq!(serde_json::to_value(&decision).unwrap(), old);
        for (notes, accepted) in [
            ("a".repeat(600), true),
            ("é".repeat(600), true),
            ("a".repeat(601), false),
        ] {
            let decision: Decision = serde_json::from_value(
                json!({"tool":"build_draft","arguments":{},"reason":"ready","notes":notes}),
            )
            .unwrap();
            assert_eq!(decision.operation().is_ok(), accepted);
        }
    }
    #[test]
    fn investigation_settings_keep_old_limits_and_bound_temperature() {
        let defaults = OperationalLimits::default();
        let serialized = serde_json::to_value(&defaults).unwrap();
        assert!(serialized.get("phase1_only").is_none());
        assert!(serialized.get("investigation_thinking").is_none());
        assert!(serialized.get("investigation_temperature").is_none());
        let old: OperationalLimits = serde_json::from_value(serialized.clone()).unwrap();
        assert!(!old.phase1_only);
        assert!(!old.investigation_thinking);
        assert_eq!(old.investigation_temperature, 0.0);
        assert_eq!(serde_json::to_value(old).unwrap(), serialized);
        for temperature in [-1.0, 2.1, f64::INFINITY, f64::NAN] {
            let settings = OperationalLimits {
                investigation_temperature: temperature,
                ..OperationalLimits::default()
            };
            assert!(settings.validate().is_err());
        }
        let enabled = OperationalLimits {
            phase1_only: true,
            investigation_thinking: true,
            investigation_temperature: 0.5,
            ..OperationalLimits::default()
        };
        enabled.validate().unwrap();
        let roundtrip: OperationalLimits =
            serde_json::from_value(serde_json::to_value(enabled).unwrap()).unwrap();
        assert!(roundtrip.phase1_only);
        assert!(roundtrip.investigation_thinking);
        assert_eq!(roundtrip.investigation_temperature, 0.5);
    }
    #[test]
    fn campaign_has_no_aggregate_caps_but_finite_worker_limits() {
        let l = OperationalLimits::default();
        l.validate().unwrap();
        assert_eq!(l.max_requests, Some(80));
        assert_eq!(l.max_total_tokens, None);
        assert_eq!(l.max_spend_usd, None);
        let mut bad = l;
        bad.request_wall_seconds = 0;
        assert!(bad.validate().is_err());
    }
    #[test]
    fn ambiguity_policy_keeps_old_configurations_unchanged() {
        let old = json!({"worker_python":"/p","worker_source":null,"source_spec":"/s","policy":"deterministic",
            "limits":OperationalLimits::default(),"provider_transfer_authorized":false,"authorization_basis":"",
            "model":GO_MODEL,"binary_sha256":"a".repeat(64)});
        let config: Config = serde_json::from_value(old.clone()).unwrap();
        assert_eq!(config.on_ambiguity, OnAmbiguity::Abstain);
        // Re-serialized byte for byte, so old ledger hashes still verify.
        assert_eq!(serde_json::to_value(&config).unwrap(), old);
        let mut draft = config;
        draft.on_ambiguity = OnAmbiguity::Draft;
        assert_eq!(
            serde_json::to_value(&draft).unwrap()["on_ambiguity"],
            "draft"
        );
        assert_eq!(
            serde_json::to_value(Status::DraftNotVerified).unwrap(),
            "draft_not_verified"
        );
    }
}
