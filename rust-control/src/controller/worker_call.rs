//! Worker calls: admission (binary identity and budgets), the durable
//! worker intent, and the checks that adopt a worker receipt.
use super::stops::{stop, stop_with_message};
use crate::store::{self, Store};
use crate::types::*;
use crate::util::{self, Result};
use crate::{validation, worker};
use serde_json::{json, Value};
use std::path::PathBuf;

pub(super) fn source_spec(store: &Store) -> PathBuf {
    let captured = store.path.join("domain/input/spec.json");
    if captured.exists() {
        captured
    } else {
        PathBuf::from(&store.state.config.source_spec)
    }
}
pub(super) fn budget_admission(store: &Store) -> Result<()> {
    let l = &store.state.config.limits;
    let c = &store.state.counters;
    if store::directory_size(&store.path)? >= l.task_disk_bytes {
        return Err("task_storage_limit".into());
    }
    if l.max_requests.is_some_and(|n| c.requests_intended >= n)
        || l.max_total_tokens
            .is_some_and(|n| c.prompt_tokens + c.completion_tokens >= n)
        || l.max_spend_usd.is_some_and(|n| c.observed_cost_usd >= n)
    {
        return Err("configured_deployment_budget".into());
    }
    Ok(())
}
pub(super) fn current_binary(store: &Store) -> Result<()> {
    if util::file_hash(&std::env::current_exe().map_err(|_| "binary_path")?)?
        != store.state.config.binary_sha256
    {
        return Err("controller_binary_changed".into());
    }
    Ok(())
}
pub fn call_worker(store: &mut Store, operation: &str, arguments: Value) -> Result<bool> {
    current_binary(store)?;
    store.verify(false)?;
    budget_admission(store)?;
    let id = format!("worker-{}", util::nonce());
    let pending = Pending {
        kind: "worker".into(),
        id: id.clone(),
        operation: operation.into(),
        response_path: format!("receipts/{id}.json"),
        request_path: format!("requests/{id}.json"),
        domain_before: store.state.domain_checkpoint_sha256.clone(),
        started_ms: util::now_ms(),
    };
    let request = json!({"protocol":WORKER_VERSION,"request_id":id,"operation":operation,"arguments":arguments,
        "expected_domain_sha256":store.state.domain_checkpoint_sha256,"expected_worker_sha256":store.state.worker_implementation_sha256});
    util::atomic_json(&store.path.join(&pending.request_path), &request, false)?;
    store.state.pending = Some(pending.clone());
    store.state.staged_decision = None;
    store.state.status = Status::Running;
    if !["initialize", "observe"].contains(&operation) {
        store.state.counters.operations += 1;
    }
    if ["build_provisional", "build_draft"].contains(&operation) {
        store.state.counters.builds += 1;
    }
    store.append("worker_intent",json!({"operation":operation,"request":store::artifact(&store.path,&pending.request_path,"worker_request")?}))?;
    let root = store.path.clone();
    let config = store.state.config.clone();
    let outcome = worker::run_with_progress(
        &root,
        &config,
        &pending,
        &util::json_bytes(&request)?,
        &source_spec(store),
        |stalled, progress| {
            store.state.status = if stalled {
                Status::Stalled
            } else {
                Status::Running
            };
            let stage = progress.map_or(operation, |p| p.stage.as_str());
            let message = if stalled {
                format!(
                    "No progress at {stage} for {} min. Keep waiting or stop this step.",
                    worker::NO_PROGRESS_SECONDS / 60
                )
            } else {
                format!("Continuing: {stage}.")
            };
            eprintln!("{message}");
            store.append(
                if stalled {
                    "worker_stalled"
                } else {
                    "worker_continued"
                },
                json!({"operation":operation,"stage":stage,"message":message}),
            )
        },
    )?;
    // A worker can finish while the person is considering the stalled prompt.
    store.state.status = Status::Running;
    if !outcome.spawned {
        store.state.pending = None;
        store.append(
            "worker_not_started",
            json!({"operation":operation,"supervision":outcome}),
        )?;
        stop(
            store,
            if matches!(outcome.state, worker::ProcessState::Cancelled) {
                Status::Cancelled
            } else {
                Status::Interrupted
            },
            "worker_not_started",
        )?;
        return Ok(false);
    }
    if store.path.join(&pending.response_path).is_file() {
        let success = apply_worker(store, &pending, json!(outcome), false)?;
        if success && !matches!(outcome.state, worker::ProcessState::Exited) {
            stop_with_message(
                store,
                if matches!(outcome.state, worker::ProcessState::Cancelled) {
                    Status::Cancelled
                } else {
                    Status::Interrupted
                },
                "worker_supervision_limit",
                outcome.message.as_deref(),
            )?;
            return Ok(false);
        }
        Ok(success)
    } else {
        let status = if matches!(outcome.state, worker::ProcessState::Cancelled) {
            Status::Cancelled
        } else {
            Status::Interrupted
        };
        // Keep the durable pending intent: changed/unreceipted domain state is
        // never adopted merely because a STEP file exists.
        let reason = if matches!(outcome.state, worker::ProcessState::TimedOut) {
            "worker_absolute_safety_cap"
        } else {
            "worker_receipt_missing"
        };
        stop_with_message(store, status, reason, outcome.message.as_deref())?;
        Ok(false)
    }
}
/// The controller, not the worker, decides which audit implementation is
/// acceptable: the identity from the initialize receipt becomes the task's pin
/// and every later receipt must repeat it. A task without a pin (created before
/// the pin existed, or initialized by a worker that reports none) gets no pin
/// later and cannot finalize; see `validation::ready`.
fn reconcile_audit_identity(
    pinned: Option<&str>,
    operation: &str,
    result: &Value,
) -> Result<Option<String>> {
    let reported = match result.get("audit_implementation_sha256") {
        None if pinned.is_some() => return Err("audit_implementation_missing".into()),
        None => return Ok(None),
        Some(value) => value
            .as_str()
            .filter(|hash| util::valid_hash(hash))
            .ok_or("audit_implementation_format")?,
    };
    match pinned {
        Some(pin) if pin == reported => Ok(Some(pin.into())),
        Some(_) => Err("audit_implementation_changed".into()),
        None if operation == "initialize" => Ok(Some(reported.into())),
        None => Ok(None),
    }
}
pub(super) fn apply_worker(
    store: &mut Store,
    pending: &Pending,
    supervision: Value,
    reconciled: bool,
) -> Result<bool> {
    let path = util::safe_file(&store.path, &pending.response_path)?;
    let response: WorkerResponse = util::parse(
        &util::read_bounded(&path, 2 * 1024 * 1024)?,
        2 * 1024 * 1024,
    )?;
    response.validate(&pending.id, &pending.operation)?;
    if response.execution_state == "completed"
        && !reconciled
        && supervision["state"] == "exited"
        && supervision["exit_code"] != 0
    {
        return Err("worker_exit_receipt_contradiction".into());
    }
    if store
        .state
        .worker_implementation_sha256
        .as_ref()
        .is_some_and(|h| h != &response.implementation_sha256)
    {
        return Err("worker_implementation_changed".into());
    }
    if response.execution_state != "completed" {
        store.append("worker_failure_receipt",json!({"receipt":store::artifact(&store.path,&pending.response_path,"worker_receipt")?,"response":response,"supervision":supervision}))?;
        stop_with_message(
            store,
            if response.execution_state == "cancelled" {
                Status::Cancelled
            } else {
                Status::Blocked
            },
            response.error_code.as_deref().unwrap_or("worker_failed"),
            supervision["message"].as_str(),
        )?;
        return Ok(false);
    }
    let _domain_guard = worker::domain_guard(&store.path)?;
    let domain = response.domain.clone().ok_or("worker_domain_missing")?;
    let result = response.result.clone().ok_or("worker_result_missing")?;
    if result["ok"].as_bool().is_none()
        || result["engineering_approved"] != false
        || result["human_semantic_review_required"] != true
    {
        return Err("worker_result_review_contract".into());
    }
    let audit_pin = reconcile_audit_identity(
        store.state.audit_implementation_sha256.as_deref(),
        &pending.operation,
        &result,
    )?;
    let checkpoint = util::file_hash(&util::safe_file(&store.path, "domain/state.json")?)?;
    if response.domain_checkpoint_sha256.as_deref() != Some(&checkpoint) {
        return Err("worker_checkpoint_not_current".into());
    }
    store::verify_domain_identity(&store.path, &domain)?;
    store::verify_artifact_values(&store.path, &result, &mut 0)?;
    // Only this person action can publish a new source manifest.
    if pending.operation != "replace_sheet"
        && store
            .state
            .source_manifest_sha256
            .as_deref()
            .is_some_and(|h| Some(h) != domain["source_manifest_sha256"].as_str())
    {
        return Err("worker_source_changed".into());
    }
    if pending.operation == "validate_candidate" && result.get("validation").is_some() {
        validation::assess(&store.path, &result, &domain, &result["validation_context"])?;
    }
    if pending.operation == "render_candidate" && result["ok"] == true {
        let candidate = &domain["current_candidate"];
        if result["stale_candidate"] != true {
            if result["rendered_generation_id"] != domain["generation_id"]
                || result["rendered_revision_id"] != domain["revision_id"]
                || candidate["valid"] != true
            {
                return Err("render_candidate_mismatch".into());
            }
            // A draft build tags its export name (run_record.py).
            let step_name = if candidate["draft"] == true {
                "model-draft.step"
            } else {
                "model.step"
            };
            let step = util::safe_file(
                &store.path,
                &format!(
                    "{}/{step_name}",
                    candidate["path"].as_str().ok_or("render_candidate_path")?
                ),
            )?;
            if result["geometry_audit"]["source"] != "independently_reimported_exported_STEP"
                || result["geometry_audit"]["step_sha256"] != util::file_hash(&step)?
            {
                return Err("render_step_identity".into());
            }
        }
    }
    store.state.domain_checkpoint_sha256 = Some(checkpoint);
    store.state.worker_implementation_sha256 = Some(response.implementation_sha256.clone());
    store.state.audit_implementation_sha256 = audit_pin;
    store.state.source_manifest_sha256 =
        domain["source_manifest_sha256"].as_str().map(String::from);
    store.state.generation_id = domain["generation_id"].as_str().map(String::from);
    store.state.revision_id = domain["revision_id"].as_str().map(String::from);
    store.state.domain = domain;
    store.state.last_observation = result;
    store.state.pending = None;
    store.state.status = Status::Running;
    store.state.termination_reason = None;
    store.append(if reconciled{"worker_reconciled"}else{"worker_result"},json!({"operation":pending.operation,"response":response,"receipt":store::artifact(&store.path,&pending.response_path,"worker_receipt")?,"supervision":supervision}))?;
    if worker::cancelled(&store.path) {
        stop_with_message(
            store,
            Status::Cancelled,
            "cancelled_after_worker_receipt",
            supervision["message"].as_str(),
        )?;
        return Ok(false);
    }
    Ok(true)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::controller::test_support::*;
    #[test]
    fn worker_limit_reason_keeps_stage_and_duration() {
        let (_tmp, mut store) = fixture();
        let message =
            "The worker reached the configured safety time limit at Making the mesh after 5.5 min.";
        let pending = Pending {
            kind: "worker".into(),
            id: "worker-limit".into(),
            operation: "observe".into(),
            response_path: "receipts/worker-limit.json".into(),
            request_path: "requests/worker-limit.json".into(),
            domain_before: None,
            started_ms: 0,
        };
        let response = json!({
            "protocol":WORKER_VERSION, "request_id":pending.id, "operation":pending.operation,
            "execution_state":"cancelled", "implementation_sha256":"a".repeat(64),
            "error_code":"worker_cancelled", "resources":{
                "wall_seconds":330.0, "worker_cpu_seconds":1.0, "children_cpu_seconds":1.0,
                "worker_peak_rss_kib":1, "children_peak_rss_kib":1,
                "rss_interpretation":"separate process maxima; not summed process-tree peak"
            }
        });
        util::atomic_json(&store.path.join(&pending.response_path), &response, false).unwrap();
        assert!(!apply_worker(
            &mut store,
            &pending,
            json!({"state":"timed_out", "message":message}),
            false
        )
        .unwrap());
        assert_eq!(store.state.termination_reason.as_deref(), Some(message));
    }
}
