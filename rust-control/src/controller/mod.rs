//! The authoritative controller: it stages each decision (live model or
//! deterministic policy), validates and dispatches it, and records every
//! worker and provider receipt in the task ledger.
//!
//! - `lifecycle`: initialization, the run loop and resume.
//! - `deterministic` and `live`: the two decision policies.
//! - `dispatch`: tool-call validation, draft builds and finalization.
//! - `worker_call` and `provider_receipt`: admission and receipt checks.
//! - `observation`, `images` and `catalog`: what the live model receives.
//! - `stops`: task stops and the no-progress guards.
use crate::store::Store;
use crate::types::*;
use crate::util::{self, Result};
use crate::worker;
use serde_json::{json, Value};
use std::collections::BTreeMap;

#[path = "../model_review.rs"]
pub mod model_review;
#[path = "../revision.rs"]
pub mod revision;
#[path = "../transcript.rs"]
pub mod transcript;

mod catalog;
mod deterministic;
mod dispatch;
mod images;
mod lifecycle;
mod live;
mod observation;
mod provider_receipt;
mod stops;
#[cfg(test)]
mod test_support;
mod worker_call;

// The integration tests compile this module by path and use only part of it.
#[allow(unused_imports)]
pub use self::{
    catalog::tool_catalog,
    deterministic::deterministic_decision,
    dispatch::execute_decision,
    lifecycle::{initialize, resume, run_loop},
    live::model_output_refused,
    worker_call::call_worker,
};

use stops::stop;
use worker_call::current_binary;
// The revision pass (`revision.rs`) also reaches these through `super::`.
use dispatch::build_draft;
use live::live_decision;

/// Test-only hook into finalization. It runs at "after_predicate" (current
/// contract passed, domain guard held) and "before_commit" (review-ready state
/// set, not yet committed). Tests use it for the interleavings that the Python
/// tests reached by monkeypatching. Release builds contain no hook.
#[cfg(test)]
pub type FinalizationHook = fn(&std::path::Path, &str);

#[cfg(test)]
#[allow(dead_code)]
pub static FINALIZATION_HOOK: std::sync::Mutex<Option<FinalizationHook>> =
    std::sync::Mutex::new(None);

#[cfg(test)]
fn finalization_point(task: &std::path::Path, point: &str) {
    let hook = *FINALIZATION_HOOK.lock().unwrap_or_else(|e| e.into_inner());
    if let Some(hook) = hook {
        hook(task, point);
    }
}

#[cfg(not(test))]
fn finalization_point(_task: &std::path::Path, _point: &str) {}

pub fn new_state(config: Config) -> State {
    State {
        schema_version: CONTROL_VERSION.into(),
        task_id: format!("task-{}", util::nonce()),
        status: Status::Ready,
        termination_reason: None,
        config,
        counters: Counters::default(),
        source_manifest_sha256: None,
        domain_checkpoint_sha256: None,
        worker_implementation_sha256: None,
        audit_implementation_sha256: None,
        generation_id: None,
        revision_id: None,
        pending: None,
        staged_decision: None,
        domain: json!({}),
        last_observation: json!({}),
        engineering_approved: false,
        action_fingerprints: BTreeMap::new(),
        created_ms: util::now_ms(),
        active_model: None,
    }
}

/// The live model investigates in draft mode: it has the investigation tools,
/// its own prompt, and accepted claims become open guesses.
fn investigation_mode(store: &Store) -> bool {
    store.state.config.policy == Policy::Live
        && store.state.config.on_ambiguity == OnAmbiguity::Draft
}

#[derive(serde::Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Intervention {
    pub schema_version: String,
    pub task_id: String,
    pub expected_head_sha256: String,
    pub expected_generation_id: String,
    pub expected_revision_id: String,
    pub decision: Decision,
}
pub fn intervene(store: &mut Store, input: Intervention, actor: &str, note: &str) -> Result<()> {
    current_binary(store)?;
    store.verify(false)?;
    if !["human_operator", "assistant_operator"].contains(&actor) || note.chars().count() > 512 {
        return Err("intervention_actor_or_note".into());
    }
    if input.schema_version != "marinaframe.intervention.v1"
        || input.task_id != store.state.task_id
        || Some(&input.expected_head_sha256) != store.head.as_ref()
        || Some(&input.expected_generation_id) != store.state.generation_id.as_ref()
        || Some(&input.expected_revision_id) != store.state.revision_id.as_ref()
    {
        return Err("stale_or_foreign_intervention".into());
    }
    if store.state.pending.is_some() || worker::cancelled(&store.path) {
        return Err("intervention_requires_reconciled_uncancelled_state".into());
    }
    input.decision.operation()?;
    store.state.counters.operator_actions += 1;
    store.state.staged_decision = None;
    store.state.status = Status::Running;
    store.state.termination_reason = None;
    store.append("operator_intervention",json!({"actor":actor,"note":note,"decision":input.decision,"previous_head":input.expected_head_sha256,"semantic_identity_certified":false,"engineering_approved":false}))?;
    if execute_decision(store, input.decision, actor)? {
        stop(store, Status::Paused, "operator_action_completed")?;
    }
    Ok(())
}

pub fn summary(store: &Store) -> Value {
    json!({"schema_version":CONTROL_VERSION,"controller":"rust","task_id":store.state.task_id,"status":store.state.status,
    "termination_reason":store.state.termination_reason,"generation_id":store.state.generation_id,"revision_id":store.state.revision_id,
    "current_candidate":store.state.domain.get("current_candidate"),
    "last_valid_candidate":store.state.domain.get("last_valid_candidate"),
    "counters":store.state.counters,"head_sha256":store.head,
    "engineering_approved":false,"semantic_review":"required","pending":store.state.pending,"policy":store.state.config.policy,
    "models":store.state.config.models(),"current_model":store.state.current_model()})
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::controller::test_support::*;
    #[test]
    fn run_state_refuses_models_outside_the_allow_list() {
        let (_tmp, mut store) = fixture();
        for list in [
            ["claude-haiku-5-5"].as_slice(),
            &["gpt-6.1-sol"],
            &[GO_MODEL, GO_MODEL],
        ] {
            use_models(&mut store, list);
            assert_eq!(
                store.state.validate().unwrap_err(),
                "invalid_state_contract"
            );
        }
        use_models(&mut store, &[GO_MODEL]);
        store.state.active_model = Some(crate::models::CROUTON_ALPHA_FREE.into());
        assert_eq!(
            store.state.validate().unwrap_err(),
            "invalid_state_contract"
        );
    }
}
