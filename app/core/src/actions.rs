//! Actions that change a task. Each one calls the same controller functions as the
//! CLI on a background thread, so every controller check applies. One action runs
//! per task at a time. The controller also holds its own lock on the task folder.
use crate::error::{AppError, AppResult};
use marinaframe_control::controller::{self, Intervention};
use marinaframe_control::store::Store;
use marinaframe_control::types::{
    Config, Decision, OnAmbiguity, OperationalLimits, Policy, GO_MODEL,
};
use marinaframe_control::util;
use serde_json::json;
use std::collections::{HashMap, HashSet};
use std::path::{Path, PathBuf};
use std::sync::{mpsc, Arc, Mutex};

/// Tracks which tasks have a running action and the last failure of a background action.
#[derive(Clone, Default)]
pub struct ActionRegistry {
    inner: Arc<Mutex<RegistryState>>,
}
#[derive(Default)]
struct RegistryState {
    busy: HashSet<PathBuf>,
    errors: HashMap<PathBuf, String>,
}

/// Held while an action runs. Dropping it frees the task for the next action.
pub struct ActionGuard {
    registry: ActionRegistry,
    task: PathBuf,
}
impl Drop for ActionGuard {
    fn drop(&mut self) {
        if let Ok(mut state) = self.registry.inner.lock() {
            state.busy.remove(&self.task);
        }
    }
}

impl ActionRegistry {
    pub fn begin(&self, task: &Path) -> AppResult<ActionGuard> {
        let mut state = self
            .inner
            .lock()
            .map_err(|_| AppError::from_code("registry_poisoned"))?;
        if !state.busy.insert(task.to_path_buf()) {
            return Err(AppError::from_code("action_in_progress"));
        }
        state.errors.remove(task);
        Ok(ActionGuard {
            registry: self.clone(),
            task: task.to_path_buf(),
        })
    }
    pub fn is_busy(&self, task: &Path) -> bool {
        self.inner.lock().is_ok_and(|s| s.busy.contains(task))
    }
    /// Plain-language failure of the last background action on `task`, if any.
    pub fn last_error(&self, task: &Path) -> Option<String> {
        self.inner.lock().ok()?.errors.get(task).cloned()
    }
    fn record_error(&self, task: &Path, message: String) {
        if let Ok(mut state) = self.inner.lock() {
            state.errors.insert(task.to_path_buf(), message);
        }
    }
}

/// Run `work` on a background thread with the task's store. `open` runs on that
/// thread too; its error comes back to the caller before this function returns,
/// so a busy task or a changed binary shows at once. Later failures are recorded
/// in the registry and shown as a notice.
fn spawn_with_store(
    registry: &ActionRegistry,
    task: &Path,
    open: impl FnOnce() -> Result<Store, String> + Send + 'static,
    work: impl FnOnce(Store) -> Result<(), String> + Send + 'static,
) -> AppResult<()> {
    let guard = registry.begin(task)?;
    let registry = registry.clone();
    let task = task.to_path_buf();
    let (opened_tx, opened_rx) = mpsc::channel();
    std::thread::Builder::new()
        .name("marinaframe-action".into())
        .spawn(move || {
            let _guard = guard;
            let store = match open() {
                Ok(store) => {
                    let _ = opened_tx.send(Ok(()));
                    store
                }
                Err(code) => {
                    let _ = opened_tx.send(Err(code));
                    return;
                }
            };
            if let Err(code) = work(store) {
                registry.record_error(&task, AppError::from_code(code).message);
            }
        })
        .map_err(|_| AppError::new("thread_start", "The action could not start."))?;
    match opened_rx.recv() {
        Ok(Ok(())) => Ok(()),
        Ok(Err(code)) => Err(AppError::from_code(code)),
        Err(_) => Err(AppError::new("thread_start", "The action could not start.")),
    }
}

/// Why an AI run may send the drawing to the model. The person enabled AI
/// drafting in Settings; the founder made AI drafting the default (2026-11-08).
pub const AI_DRAFTING_BASIS: &str =
    "AI drafting is enabled in MarinaFrame settings: the drawing goes to DeepSeek through OpenCode Go to build a draft.";

/// Configuration of a run started from the app: always draft on ambiguity (a draft
/// is never review-ready). With `use_model` the AI reads the drawing (live policy,
/// founder decision 2026-11-08: LLM-first); without it the deterministic draft runs,
/// which the sealed head-to-head (v2) picked over abstain. The CLI default stays `abstain`.
fn app_run_config(
    worker_python: String,
    worker_source: Option<String>,
    source_spec: String,
    binary_sha256: String,
    use_model: bool,
) -> Config {
    Config {
        worker_python,
        worker_source,
        source_spec,
        policy: if use_model {
            Policy::Live
        } else {
            Policy::Deterministic
        },
        limits: OperationalLimits::default(),
        provider_transfer_authorized: use_model,
        authorization_basis: if use_model {
            AI_DRAFTING_BASIS.into()
        } else {
            String::new()
        },
        model: GO_MODEL.into(),
        binary_sha256,
        on_ambiguity: OnAmbiguity::Draft,
    }
}

/// Start a run of `spec_path` in draft mode. The task folder is created inside
/// `runs_folder`. With `use_model` the AI reads the drawing and builds the draft
/// (live policy); without it the deterministic draft runs.
pub fn start_run(
    registry: &ActionRegistry,
    runs_folder: &Path,
    worker_python: &str,
    worker_source: Option<&Path>,
    spec_path: &str,
    use_model: bool,
) -> AppResult<String> {
    let source = util::absolute(Path::new(spec_path))?;
    if !source.is_file() || source.is_symlink() {
        return Err(AppError::from_code("source_spec_missing_or_symlink"));
    }
    let python = util::absolute(Path::new(worker_python))
        .map_err(|_| AppError::from_code("worker_python_missing"))?;
    if worker_python.is_empty() || !python.is_file() {
        return Err(AppError::from_code("worker_python_missing"));
    }
    let worker_source = worker_source
        .map(|p| util::absolute(p).map(|p| p.to_string_lossy().into_owned()))
        .transpose()?;
    let config = app_run_config(
        python.to_string_lossy().into_owned(),
        worker_source,
        source.to_string_lossy().into_owned(),
        util::file_hash(&std::env::current_exe().map_err(|_| "binary_path")?)?,
        use_model,
    );
    let stem = source
        .file_stem()
        .and_then(|s| s.to_str())
        .map(|s| {
            s.chars()
                .filter(|c| c.is_ascii_alphanumeric() || *c == '-' || *c == '_')
                .collect::<String>()
        })
        .filter(|s| !s.is_empty())
        .unwrap_or_else(|| "run".into());
    let task = runs_folder.join(format!("{stem}-{}", util::now_ms()));
    let location = task.clone();
    spawn_with_store(
        registry,
        &task,
        move || Store::create(&location, controller::new_state(config)),
        |mut store| {
            if controller::initialize(&mut store)? {
                controller::run_loop(&mut store, None)?;
            }
            Ok(())
        },
    )?;
    Ok(task.to_string_lossy().into_owned())
}

/// Ask a running task to stop, as `marinaframe cancel` does. This takes no lock.
pub fn cancel_task(task: &Path) -> AppResult<()> {
    let request = task.join("cancel.request");
    if !request.exists() {
        util::atomic_json(
            &request,
            &json!({"schema_version":"marinaframe.cancel.v1","requested_ms":util::now_ms()}),
            false,
        )?;
    }
    Ok(())
}

/// Continue a paused, interrupted or cancelled task. A cancel request is cleared first.
pub fn resume_task(registry: &ActionRegistry, task: &Path) -> AppResult<()> {
    let location = task.to_path_buf();
    let clear_cancel = task.join("cancel.request").exists();
    spawn_with_store(
        registry,
        task,
        move || Store::open(&location),
        move |mut store| controller::resume(&mut store, false, clear_cancel, None),
    )
}

/// Pick `candidate_id` for `section_id` as an operator, then rebuild, render and
/// validate through the controller's deterministic loop.
pub fn choose_line(
    registry: &ActionRegistry,
    task: &Path,
    section_id: &str,
    candidate_id: &str,
) -> AppResult<()> {
    let location = task.to_path_buf();
    let selection = json!({"selections":[{"section_id":section_id,"candidate_id":candidate_id}]});
    spawn_with_store(
        registry,
        task,
        move || {
            let store = Store::open(&location)?;
            if store.state.config.policy != Policy::Deterministic {
                return Err("live_runs_are_read_only".into());
            }
            Ok(store)
        },
        move |mut store| {
            let bound =
                |value: &Option<String>| value.clone().ok_or_else(|| "not_built_yet".to_string());
            let intervention = Intervention {
                schema_version: "marinaframe.intervention.v1".into(),
                task_id: store.state.task_id.clone(),
                expected_head_sha256: bound(&store.head)?,
                expected_generation_id: bound(&store.state.generation_id)?,
                expected_revision_id: bound(&store.state.revision_id)?,
                decision: Decision {
                    tool: "select_contours".into(),
                    arguments: selection,
                    reason: "Line chosen by a person in the app.".into(),
                    notes: None,
                },
            };
            controller::intervene(
                &mut store,
                intervention,
                "human_operator",
                "Line chosen in the app",
            )?;
            controller::resume(&mut store, false, false, None)
        },
    )
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn app_runs_use_the_model_in_draft_mode_or_the_deterministic_draft() {
        let ai = app_run_config("python".into(), None, "spec.json".into(), String::new(), true);
        assert_eq!(ai.on_ambiguity, OnAmbiguity::Draft);
        assert_eq!(ai.policy, Policy::Live);
        assert!(ai.provider_transfer_authorized);
        assert_eq!(ai.authorization_basis, AI_DRAFTING_BASIS);
        let fallback = app_run_config("python".into(), None, "spec.json".into(), String::new(), false);
        assert_eq!(fallback.on_ambiguity, OnAmbiguity::Draft);
        assert_eq!(fallback.policy, Policy::Deterministic);
        assert!(!fallback.provider_transfer_authorized);
    }
}
