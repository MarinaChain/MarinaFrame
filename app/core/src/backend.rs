//! The whole app backend as plain functions. A transport (the Tauri shell today,
//! an HTTP server later) only translates arguments, calls one method and returns
//! the result or the `AppError`. Nothing here depends on a transport.
use crate::actions::{self, ActionRegistry};
use crate::batch::{self, BatchPlan, BatchQueue, DrawingSet, QueueState, QueueView};
use crate::error::{AppError, AppResult};
use crate::export::{self, ExportResult};
use crate::live::{HullSections, LiveSteps, LiveStore};
use crate::storage::{self, AppPaths};
use crate::types::*;
use crate::view::{self, ViewContext};
use crate::{artifact, events, files, intake, model_keys, parts, sample, signoff};
use marinaframe_control::util;
use std::collections::HashMap;
use std::path::{Path, PathBuf};
use std::sync::Arc;

pub struct Backend {
    paths: AppPaths,
    registry: ActionRegistry,
    binary_sha256: Option<String>,
    worker_source: Option<PathBuf>,
    datasets_root: Option<PathBuf>,
    live: LiveStore,
    /// Drawing sets waiting for a run (design plan M6).
    batch: BatchQueue,
    /// One pump at a time, so two callers cannot both see the same free slots.
    pump_lock: std::sync::Mutex<()>,
}

impl Backend {
    /// `worker_source` is an optional `PYTHONPATH` for the Python worker (development
    /// checkouts). `datasets_root` is the folder whose subfolders `list_datasets` shows.
    pub fn new(
        paths: AppPaths,
        worker_source: Option<PathBuf>,
        datasets_root: Option<PathBuf>,
    ) -> Self {
        let binary_sha256 = std::env::current_exe()
            .ok()
            .and_then(|exe| util::file_hash(&exe).ok());
        let batch = BatchQueue::load(&paths);
        Self {
            batch,
            pump_lock: std::sync::Mutex::new(()),
            paths,
            registry: ActionRegistry::default(),
            binary_sha256,
            worker_source,
            datasets_root,
            live: LiveStore::default(),
        }
    }

    fn runs_folder(&self) -> PathBuf {
        PathBuf::from(storage::get_settings(&self.paths).runs_folder)
    }
    fn task_path(&self, task: &str) -> AppResult<PathBuf> {
        files::resolve_task(&self.runs_folder(), task)
    }

    pub fn list_tasks(&self) -> Vec<TaskSummary> {
        view::list_tasks(&self.runs_folder())
    }

    pub fn get_task(&self, task: &str) -> AppResult<TaskView> {
        let path = self.task_path(task)?;
        let context = ViewContext {
            dismissed_notices: storage::dismissed_notices(&self.paths),
            binary_sha256: self.binary_sha256.clone(),
            action_error: self.registry.last_error(&path),
            part_reviews: parts::reviews_of(&self.paths, &path),
            sign_off: signoff::sign_off_of(&self.paths, &path),
        };
        Ok(view::get_task(&path, &context)?)
    }

    /// Save a person's review of one whole-vessel part ("accepted", "marked" with a note, or "open").
    pub fn review_component(
        &self,
        task: &str,
        component_id: &str,
        decision: &str,
        note: Option<&str>,
    ) -> AppResult<()> {
        let path = self.task_path(task)?;
        parts::review_component(&self.paths, &path, component_id, decision, note)?;
        // A part open again means the parts are no longer all reviewed: the sign-off ends.
        if decision == "open" {
            signoff::withdraw(&self.paths, &path)?;
        }
        Ok(())
    }

    /// Record a person's sign-off of a run's parts: "usable as a starting model". The run
    /// stays a draft. `name` empty withdraws the sign-off.
    pub fn sign_off(&self, task: &str, name: &str) -> AppResult<Option<SignOffView>> {
        let path = self.task_path(task)?;
        if name.trim().is_empty() {
            signoff::withdraw(&self.paths, &path)?;
            return Ok(None);
        }
        signoff::sign_off(&self.paths, &path, name, util::now_ms()).map(Some)
    }

    pub fn get_events(&self, task: &str, after_sequence: u64) -> AppResult<Vec<EventView>> {
        Ok(events::get_events(&self.task_path(task)?, after_sequence))
    }

    /// Live steps that are new or changed after `after_sequence` (see `live`).
    pub fn get_live_steps(&self, task: &str, after_sequence: u64) -> AppResult<LiveSteps> {
        Ok(self.live.steps(&self.task_path(task)?, after_sequence))
    }

    /// Section curves of one build for the 3D view.
    pub fn get_hull_sections(&self, task: &str, revision: &str) -> AppResult<HullSections> {
        self.live.hull_sections(&self.task_path(task)?, revision)
    }

    pub fn read_artifact(&self, task: &str, path: &str) -> AppResult<Artifact> {
        artifact::read_artifact(&self.task_path(task)?, path)
    }

    pub fn start_run(&self, spec_path: &str) -> AppResult<String> {
        let settings = storage::get_settings(&self.paths);
        let runs = PathBuf::from(&settings.runs_folder);
        std::fs::create_dir_all(&runs)
            .map_err(|_| AppError::new("runs_folder", "The runs folder could not be created."))?;
        actions::start_run(
            &self.registry,
            &runs,
            &settings.worker_python,
            self.worker_source.as_deref(),
            spec_path,
            self.ai_status().active,
        )
    }

    /// Start the built-in sample vessel (core/sample): a deterministic run, so a first-time
    /// user sees a whole run with no model key and no cost.
    pub fn start_sample_run(&self) -> AppResult<String> {
        let settings = storage::get_settings(&self.paths);
        let runs = PathBuf::from(&settings.runs_folder);
        let spec = sample::write_sample(&runs)?;
        actions::start_run(
            &self.registry,
            &runs,
            &settings.worker_python,
            self.worker_source.as_deref(),
            &spec.to_string_lossy(),
            false,
        )
    }

    fn intake_worker<'a>(&'a self, settings: &'a Settings) -> intake::Worker<'a> {
        intake::Worker {
            python: &settings.worker_python,
            source: self.worker_source.as_deref(),
        }
    }

    /// Read a dropped drawing set: pages, thumbnails, proposed view labels, warnings.
    pub fn prepare_intake(&self, files: &[String]) -> AppResult<intake::IntakePreview> {
        let settings = storage::get_settings(&self.paths);
        intake::prepare_intake(
            Path::new(&settings.runs_folder),
            &self.intake_worker(&settings),
            files,
            self.ai_status().active,
        )
    }

    /// Write the spec of an edited intake preview, start its run with the current
    /// AI setting and copy the inputs into the task's `intake/` folder.
    pub fn start_intake_run(&self, preview: &intake::IntakePreview) -> AppResult<String> {
        let settings = storage::get_settings(&self.paths);
        let runs = PathBuf::from(&settings.runs_folder);
        let inputs = intake::write_run_inputs(&runs, &self.intake_worker(&settings), preview)?;
        let spec = inputs.join("spec.json");
        let task = self.start_run(&spec.to_string_lossy())?;
        intake::copy_inputs_to_task(&inputs, Path::new(&task))?;
        Ok(task)
    }

    /// Write the chosen exports of one revision into `<task>/exports/<rNNNN>/`.
    /// Refused while an action runs on the task, so the build cannot change meanwhile.
    pub fn export_run(
        &self,
        task: &str,
        revision: &str,
        outputs: &[String],
    ) -> AppResult<ExportResult> {
        let path = self.task_path(task)?;
        if self.registry.is_busy(&path) {
            return Err(AppError::from_code("action_in_progress"));
        }
        let settings = storage::get_settings(&self.paths);
        export::export_run(
            &path,
            &self.intake_worker(&settings),
            revision,
            outputs,
            export::EXPORT_TIMEOUT,
        )
    }

    /// Files already exported for one revision.
    pub fn list_exports(&self, task: &str, revision: &str) -> AppResult<ExportResult> {
        export::list_exports(&self.task_path(task)?, revision)
    }

    /// Show an exported file (or the exports folder) in Finder.
    pub fn reveal_export(&self, task: &str, path: &str) -> AppResult<()> {
        let target = export::check_reveal_path(&self.task_path(task)?, path)?;
        export::reveal(&target)
    }

    /// Whether new runs use the AI, and why not when they do not.
    pub fn ai_status(&self) -> AiStatus {
        let enabled = storage::get_settings(&self.paths).ai_drafting;
        let (key_source, keys) = model_keys::configured_keys();
        AiStatus {
            enabled,
            key_found: key_source.is_some(),
            active: enabled && key_source.is_some(),
            key_count: keys.len(),
            key_file: model_keys::key_file()
                .map(|p| p.to_string_lossy().into_owned())
                .unwrap_or_default(),
        }
    }

    // ---------------------------------------------------------------- batch queue

    /// Group dropped files and folders into drawing sets (reads names only).
    pub fn plan_batch(&self, paths: &[String]) -> BatchPlan {
        batch::plan_batch(paths)
    }

    /// The waiting sets, the slot limit and how many runs run now.
    pub fn get_queue(&self) -> QueueView {
        let running = view::list_tasks(&self.runs_folder())
            .iter()
            .filter(|t| t.status == Status::Running)
            .count()
            + self.batch.starting_count();
        let held = (!self.ai_status().active
            && self
                .batch
                .snapshot()
                .iter()
                .any(|s| s.state == QueueState::Waiting))
        .then(|| "Waiting sets start when AI drafting is on and a model key is found.".to_string());
        QueueView {
            slots: batch::native_slots(),
            running,
            waiting: self.batch.snapshot(),
            held,
        }
    }

    /// Add sets to the end of the queue. The pump starts them as slots free up.
    pub fn queue_batch(self: &Arc<Self>, sets: &[DrawingSet]) -> AppResult<QueueView> {
        if sets.is_empty() {
            return Err(AppError::new(
                "intake_files",
                "Choose at least one drawing set.",
            ));
        }
        self.batch.add(&self.paths, sets, util::now_ms())?;
        self.pump_batch();
        Ok(self.get_queue())
    }

    pub fn remove_queued(&self, id: &str) -> AppResult<QueueView> {
        self.batch.remove(&self.paths, id)?;
        Ok(self.get_queue())
    }

    pub fn move_queued(&self, id: &str, delta: i64) -> AppResult<QueueView> {
        self.batch.move_set(&self.paths, id, delta)?;
        Ok(self.get_queue())
    }

    /// Start waiting sets while fewer runs than the slot limit are running. Cheap when
    /// nothing waits; the watcher calls it every round. Each start runs on its own thread
    /// (reading a set renders its pages), so this never blocks the caller.
    pub fn pump_batch(self: &Arc<Self>) {
        let waiting = self.batch.snapshot();
        if !waiting.iter().any(|s| s.state == QueueState::Waiting) || !self.ai_status().active {
            return;
        }
        let Ok(_pumping) = self.pump_lock.try_lock() else {
            return;
        };
        let queue = self.get_queue();
        let free = queue.slots.saturating_sub(queue.running);
        for set in self.batch.take_for_start(&self.paths, free) {
            let backend = Arc::clone(self);
            let spawned = std::thread::Builder::new()
                .name("marinaframe-batch-start".into())
                .spawn(move || {
                    let result = backend
                        .start_queued(&set)
                        .map(|_| ())
                        .map_err(|e| e.message);
                    backend.batch.finish(&backend.paths, &set.id, result);
                });
            if spawned.is_err() {
                return;
            }
        }
    }

    /// Read one queued set and start its run with the proposed labels and its name.
    fn start_queued(&self, set: &batch::QueuedSet) -> AppResult<String> {
        let mut preview = self.prepare_intake(&set.files)?;
        if preview.particulars.vessel_name.trim().is_empty() {
            preview.particulars.vessel_name = set.name.clone();
        }
        self.start_intake_run(&preview)
    }

    /// OpenCode Go usage per key slot, read now (Settings, on demand only).
    pub fn model_usage(&self) -> crate::model_usage::ModelUsage {
        crate::model_usage::check_usage()
    }

    /// The setup check of the welcome screen. Only file-system checks: it starts no process.
    pub fn setup_status(&self) -> SetupStatus {
        let settings = storage::get_settings(&self.paths);
        SetupStatus {
            ai: self.ai_status(),
            worker: check_worker_python(&settings.worker_python),
            runs_folder: check_runs_folder(&settings.runs_folder),
        }
    }

    /// True while a background action runs on the task.
    pub fn is_busy(&self, task: &str) -> bool {
        self.task_path(task)
            .is_ok_and(|path| self.registry.is_busy(&path))
    }

    pub fn cancel_task(&self, task: &str) -> AppResult<()> {
        actions::cancel_task(&self.task_path(task)?)
    }

    pub fn resume_task(&self, task: &str) -> AppResult<()> {
        actions::resume_task(&self.registry, &self.task_path(task)?)
    }

    pub fn choose_line(&self, task: &str, section_id: &str, candidate_id: &str) -> AppResult<()> {
        actions::choose_line(
            &self.registry,
            &self.task_path(task)?,
            section_id,
            candidate_id,
        )
    }

    /// Mark and revise: one focused model pass on a marked region.
    pub fn revise_region(&self, task: &str, request: serde_json::Value) -> AppResult<()> {
        actions::revise_region(&self.registry, &self.task_path(task)?, request)
    }

    pub fn force_keep_revision(&self, task: &str, revision_id: &str) -> AppResult<()> {
        actions::force_keep_revision(&self.registry, &self.task_path(task)?, revision_id)
    }

    pub fn get_settings(&self) -> Settings {
        storage::get_settings(&self.paths)
    }
    /// The settings a fresh install starts with (default runs folder, repo `.venv`
    /// Python when found). The UI offers them as one-click choices.
    pub fn default_settings(&self) -> Settings {
        self.paths.default_settings()
    }
    pub fn set_settings(&self, settings: Settings) -> AppResult<Settings> {
        storage::set_settings(&self.paths, settings)
    }
    pub fn dismiss_notice(&self, id: &str) -> AppResult<()> {
        storage::dismiss_notice(&self.paths, id)
    }
    pub fn reset_notices(&self) -> AppResult<()> {
        storage::reset_notices(&self.paths)
    }

    pub fn list_datasets(&self) -> Vec<Dataset> {
        self.datasets_root
            .as_deref()
            .map(list_datasets)
            .unwrap_or_default()
    }

    /// A watcher for `task-changed` notifications. Call `poll` every 500 ms.
    pub fn watcher(&self) -> TaskWatcher {
        TaskWatcher::default()
    }
    /// One watch round: returns a `TaskChanged` for every task whose event count is new.
    pub fn poll_changes(&self, watcher: &mut TaskWatcher) -> Vec<TaskChanged> {
        watcher.poll(&self.runs_folder())
    }
}

/// Remembers the last event count of each task. The first round only records counts.
#[derive(Default)]
pub struct TaskWatcher {
    seen: HashMap<String, u64>,
    primed: bool,
}
impl TaskWatcher {
    pub fn poll(&mut self, runs_folder: &Path) -> Vec<TaskChanged> {
        let mut changed = vec![];
        let mut now = HashMap::new();
        for summary in view::list_tasks(runs_folder) {
            let sequence = files::event_count(Path::new(&summary.task));
            if self.primed && self.seen.get(&summary.task) != Some(&sequence) {
                changed.push(TaskChanged {
                    task: summary.task.clone(),
                    sequence,
                });
            }
            now.insert(summary.task, sequence);
        }
        self.seen = now;
        self.primed = true;
        changed
    }
}

fn setup_check(ok: bool, path: &str, message: &str) -> SetupCheck {
    SetupCheck {
        ok,
        path: path.to_string(),
        message: message.to_string(),
    }
}

/// The worker Python must be an absolute path to a file (the same rule as `start_run`).
pub fn check_worker_python(worker_python: &str) -> SetupCheck {
    if worker_python.is_empty() {
        return setup_check(false, "", "No Python is chosen for the CAD worker.");
    }
    let python = Path::new(worker_python);
    if python.is_absolute() && python.is_file() {
        setup_check(true, worker_python, "The CAD worker Python is found.")
    } else {
        setup_check(false, worker_python, "This Python was not found.")
    }
}

/// The runs folder may be missing: the first run makes it, if its parent exists.
pub fn check_runs_folder(runs_folder: &str) -> SetupCheck {
    let folder = Path::new(runs_folder);
    if !folder.is_absolute() {
        return setup_check(false, runs_folder, "The runs folder is not a full path.");
    }
    if folder.is_dir() {
        return setup_check(true, runs_folder, "Runs are saved here.");
    }
    if folder.exists() {
        return setup_check(false, runs_folder, "This path is a file, not a folder.");
    }
    if folder.parent().is_some_and(Path::is_dir) {
        setup_check(true, runs_folder, "The first run makes this folder.")
    } else {
        setup_check(
            false,
            runs_folder,
            "The folder above this one does not exist.",
        )
    }
}

/// Subfolders of `root` with their total size. Symlinks are skipped.
pub fn list_datasets(root: &Path) -> Vec<Dataset> {
    let Ok(entries) = std::fs::read_dir(root) else {
        return vec![];
    };
    let mut datasets: Vec<Dataset> = entries
        .filter_map(Result::ok)
        .filter(|e| e.file_type().is_ok_and(|t| t.is_dir()))
        .filter_map(|e| {
            Some(Dataset {
                name: e.file_name().into_string().ok()?,
                path: e.path().to_string_lossy().into_owned(),
                bytes: folder_bytes(&e.path(), 0),
            })
        })
        .collect();
    datasets.sort_by(|a, b| a.name.cmp(&b.name));
    datasets
}

fn folder_bytes(path: &Path, depth: usize) -> u64 {
    if depth > 8 {
        return 0;
    }
    let Ok(entries) = std::fs::read_dir(path) else {
        return 0;
    };
    entries
        .filter_map(Result::ok)
        .map(|e| match e.file_type() {
            Ok(t) if t.is_file() => e.metadata().map(|m| m.len()).unwrap_or(0),
            Ok(t) if t.is_dir() => folder_bytes(&e.path(), depth + 1),
            _ => 0,
        })
        .sum()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn ai_is_not_active_when_ai_drafting_is_off() {
        let tmp = tempfile::tempdir().unwrap();
        let paths = AppPaths {
            config_dir: tmp.path().join("config"),
            data_dir: tmp.path().join("data"),
            repo_root: None,
        };
        let backend = Backend::new(paths, None, None);
        let mut settings = backend.get_settings();
        settings.ai_drafting = false;
        backend.set_settings(settings).unwrap();
        let status = backend.ai_status();
        assert!(!status.enabled);
        assert!(!status.active);
        assert!(status.key_file.ends_with("opencode-go-keys.txt"));
    }

    #[test]
    fn setup_check_reads_the_worker_python_and_runs_folder() {
        let tmp = tempfile::tempdir().unwrap();
        let python = tmp.path().join("python3");
        std::fs::write(&python, "").unwrap();
        let path = |p: &Path| p.to_string_lossy().into_owned();

        assert!(!check_worker_python("").ok);
        assert!(!check_worker_python("python3").ok);
        assert!(check_worker_python(&path(&python)).ok);

        assert!(check_runs_folder(&path(tmp.path())).ok);
        assert!(check_runs_folder(&path(&tmp.path().join("runs"))).ok);
        assert!(!check_runs_folder(&path(&tmp.path().join("a/b"))).ok);
        assert!(!check_runs_folder(&path(&python)).ok);
        assert!(!check_runs_folder("runs").ok);
    }
}
