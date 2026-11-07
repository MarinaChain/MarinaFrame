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
        Ok(())
    }
}

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Decision {
    pub tool: String,
    pub arguments: Value,
    pub reason: String,
}
impl Decision {
    pub fn operation(&self) -> Result<Operation> {
        if self.reason.chars().count() > 512 || self.reason.len() > 2048 {
            return Err("reason_limit".into());
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
    pub max_requests: Option<u64>,
    pub max_total_tokens: Option<u64>,
    pub max_spend_usd: Option<f64>,
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
