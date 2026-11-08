use crate::util::{self, Result};
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::collections::BTreeSet;

pub const CONTROL_VERSION: &str = "marinaframe.control.v1";
pub const WORKER_VERSION: &str = "marinaframe.worker.v1";
pub const GO_MODEL: &str = "deepseek-v4.1-flash";
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

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct OperationalLimits {
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
    #[serde(default, skip_serializing_if = "is_zero")]
    pub investigation_temperature: f64,
    pub max_requests: Option<u64>,
    pub max_total_tokens: Option<u64>,
    pub max_spend_usd: Option<f64>,
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
            worker_wall_seconds: 210,
            request_wall_seconds: 90,
            worker_memory_bytes: 5 * 1024 * 1024 * 1024,
            worker_cpu_seconds: 180,
            task_disk_bytes: 2 * 1024 * 1024 * 1024,
            max_output_tokens_per_request: 2048,
            max_observation_bytes: 96_000,
            max_images_per_request: 4,
            max_image_bytes: 196_608,
            max_repeated_action: 3,
            investigation_thinking: false,
            investigation_temperature: 0.0,
            max_requests: None,
            max_total_tokens: None,
            max_spend_usd: None,
        }
    }
}
impl OperationalLimits {
    pub fn validate(&self) -> Result<()> {
        if !(1..=900).contains(&self.worker_wall_seconds)
            || !(1..=180).contains(&self.request_wall_seconds)
            || !(256 * 1024 * 1024..=8 * 1024 * 1024 * 1024).contains(&self.worker_memory_bytes)
            || !(1..=600).contains(&self.worker_cpu_seconds)
            || !(32 * 1024 * 1024..=8 * 1024 * 1024 * 1024).contains(&self.task_disk_bytes)
            || !(16..=8192).contains(&self.max_output_tokens_per_request)
            || !(4096..=196_608).contains(&self.max_observation_bytes)
            || self.max_images_per_request > 6
            || !(1024..=1_048_576).contains(&self.max_image_bytes)
            || !(1..=8).contains(&self.max_repeated_action)
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
    pub model: String,
    pub binary_sha256: String,
    /// Not serialized when `abstain`, so the hashes of older ledger events and
    /// their configurations stay unchanged.
    #[serde(default, skip_serializing_if = "OnAmbiguity::is_abstain")]
    pub on_ambiguity: OnAmbiguity,
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
}
impl State {
    pub fn validate(&self) -> Result<()> {
        if self.schema_version != CONTROL_VERSION
            || self.engineering_approved
            || !util::valid_id(&self.task_id, 128)
            || self.config.model != GO_MODEL
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
        assert!(serialized.get("investigation_thinking").is_none());
        assert!(serialized.get("investigation_temperature").is_none());
        let old: OperationalLimits = serde_json::from_value(serialized.clone()).unwrap();
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
            investigation_thinking: true,
            investigation_temperature: 0.5,
            ..OperationalLimits::default()
        };
        enabled.validate().unwrap();
        let roundtrip: OperationalLimits =
            serde_json::from_value(serde_json::to_value(enabled).unwrap()).unwrap();
        assert!(roundtrip.investigation_thinking);
        assert_eq!(roundtrip.investigation_temperature, 0.5);
    }
    #[test]
    fn campaign_has_no_aggregate_caps_but_finite_worker_limits() {
        let l = OperationalLimits::default();
        l.validate().unwrap();
        assert_eq!(l.max_requests, None);
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
