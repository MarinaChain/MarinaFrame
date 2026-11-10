//! Re-run one whole-vessel part from the person's mark, then keep or undo the new revision
//! (APP_SPEC "Whole-vessel parts"). The work is done by the Python worker
//! `python -m vessel_reconstruction.part_revise`: it crops the run's drawings around the part,
//! asks the model with the mark note, rebuilds only that part and rewrites its entry in
//! `<task>/whole_vessel/execution.json`. This module checks the request, runs the worker with
//! the progress watchdog (arguments only, no shell) and returns the part as the app shows it.
use crate::actions::ActionRegistry;
use crate::error::{AppError, AppResult};
use crate::intake::Worker;
use crate::parts::{self, PartReview};
use crate::storage::AppPaths;
use crate::types::ComponentView;
use crate::worker_run::{Supervision, WorkerWords, UNCANCELLABLE};
use marinaframe_control::provider::credentials::CREDENTIAL_VARIABLES;
use marinaframe_control::supervised;
use std::collections::HashMap;
use std::ffi::OsStr;
use std::path::{Path, PathBuf};
use std::time::Duration;

/// A re-run with no progress report for this long is stopped. The worker reports each model
/// request and each part build; one model request may run up to the worker's
/// `REQUEST_TIMEOUT_S` (300 s) with no report, so the period is twice that. There is no
/// limit on the total time: the sandboxed part build keeps its own caps inside the worker.
pub const REVISE_STALL_PERIOD: Duration = Duration::from_secs(2 * 300);
/// How part-worker errors are named.
const PART_WORDS: WorkerWords = WorkerWords {
    code: "part_revise",
    name: "The re-run",
    after_stop: " The old part stays.",
};

/// How the worker reaches the model.
pub enum Model {
    /// A key from the app's key lookup (`model_keys`). It goes into the worker's
    /// environment only: never into an argument, a log or an error.
    Key(String),
    /// Scripted replies (a JSON list of strings) for tests: no model request is made.
    Scripted(PathBuf),
}

enum Action<'a> {
    Revise { note: &'a str, model: &'a Model },
    Keep,
    Undo,
}

/// Re-run `component_id` from its saved mark note. Refused without a mark note and while
/// another action runs on the run. Returns the part with its new revision.
pub fn revise_part(
    registry: &ActionRegistry,
    paths: &AppPaths,
    task: &Path,
    component_id: &str,
    worker: &Worker,
    model: &Model,
    stall_period: Duration,
) -> AppResult<ComponentView> {
    let reviews = parts::reviews_of(paths, task);
    let note = match reviews.get(component_id) {
        Some(PartReview {
            decision,
            note: Some(note),
        }) if decision == "marked" && !note.trim().is_empty() => note.clone(),
        _ => {
            return Err(AppError::new(
                "revise_needs_mark",
                "Mark the part and say what to change first.",
            ))
        }
    };
    let _guard = registry.begin(task)?;
    run_worker(
        worker,
        task,
        component_id,
        Action::Revise { note: &note, model },
        stall_period,
    )?;
    part_view(task, component_id, &reviews)
}

/// Keep the new revision of a part. Its mark has been acted on, so the review opens again
/// (the person reviews the new part); any sign-off of the parts ends.
pub fn keep_revision(
    registry: &ActionRegistry,
    paths: &AppPaths,
    task: &Path,
    component_id: &str,
    worker: &Worker,
) -> AppResult<ComponentView> {
    let _guard = registry.begin(task)?;
    run_worker(
        worker,
        task,
        component_id,
        Action::Keep,
        supervised::DEFAULT_STALL_PERIOD,
    )?;
    parts::review_component(paths, task, component_id, "open", None)?;
    part_view(task, component_id, &parts::reviews_of(paths, task))
}

/// Undo the new revision: the previous entry and STEP come back; the mark stays.
pub fn undo_revision(
    registry: &ActionRegistry,
    paths: &AppPaths,
    task: &Path,
    component_id: &str,
    worker: &Worker,
) -> AppResult<ComponentView> {
    let _guard = registry.begin(task)?;
    run_worker(
        worker,
        task,
        component_id,
        Action::Undo,
        supervised::DEFAULT_STALL_PERIOD,
    )?;
    part_view(task, component_id, &parts::reviews_of(paths, task))
}

fn part_view(
    task: &Path,
    component_id: &str,
    reviews: &HashMap<String, PartReview>,
) -> AppResult<ComponentView> {
    parts::read_components(task, reviews)
        .and_then(|list| list.into_iter().find(|p| p.id == component_id))
        .ok_or_else(|| AppError::new("component_not_found", "This run has no such part."))
}

fn run_worker(
    worker: &Worker,
    task: &Path,
    component_id: &str,
    action: Action,
    stall_period: Duration,
) -> AppResult<()> {
    // The shared worker environment holds no model key; only the key given here is added.
    let mut command = worker.module_command("vessel_reconstruction.part_revise")?;
    command
        .args([OsStr::new("--task"), task.as_os_str()])
        .args(["--part", component_id]);
    match action {
        Action::Revise { note, model } => {
            // One argument: a note that starts with "-" stays the note.
            command.arg(format!("--note={note}"));
            match model {
                Model::Key(key) => {
                    command.env(CREDENTIAL_VARIABLES[0], key);
                }
                Model::Scripted(replies) => {
                    command.args([OsStr::new("--replies"), replies.as_os_str()]);
                }
            }
        }
        Action::Keep => {
            command.arg("--keep");
        }
        Action::Undo => {
            command.arg("--undo");
        }
    }
    let supervision = Supervision {
        stall_period,
        ..UNCANCELLABLE
    };
    let finished = worker.run_supervised(&mut command, &supervision, &PART_WORDS)?;
    if finished.status.success() {
        return Ok(());
    }
    // The worker writes {"error": "..."} for a refusal it explains; anything else is generic.
    let reason = serde_json::from_slice::<serde_json::Value>(&finished.stderr)
        .ok()
        .and_then(|value| value["error"].as_str().map(String::from));
    Err(AppError::new(
        "part_revise_worker",
        &reason
            .unwrap_or_else(|| "The part worker stopped with an error. The old part stays.".into()),
    ))
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    fn setup(tmp: &tempfile::TempDir) -> (AppPaths, PathBuf) {
        let task = tmp.path().join("task");
        std::fs::create_dir_all(task.join("whole_vessel")).unwrap();
        let execution = json!({"result": {"engineering_approved": false, "components": [
            {"id": "wheelhouse", "op": "deckhouse", "status": "draft_guess", "built": true,
             "source_labels": {"height": "traced"}, "geometry": {"height": [9.0, 11.5]},
             "provenance": {}}]}});
        std::fs::write(task.join(parts::EXECUTION_FILE), execution.to_string()).unwrap();
        let paths = AppPaths {
            config_dir: tmp.path().join("config"),
            data_dir: tmp.path().join("data"),
            repo_root: None,
        };
        (paths, task)
    }

    /// A worker that must never start: the checks refuse before it.
    const NO_PYTHON: Worker = Worker {
        python: "/no/such/python",
        source: None,
    };

    /// One real re-run with the model, through the app path (key from `model_keys`, the real
    /// worker). Never on a committed folder: copy a run first; drawings may be licensed.
    /// `MARINAFRAME_TEST_PYTHON=<python> MARINAFRAME_REVISE_TASK=<task copy>
    /// MARINAFRAME_REVISE_PART=<id> MARINAFRAME_REVISE_NOTE=<note> cargo test -- --ignored real_re_run`
    #[test]
    #[ignore]
    fn a_real_re_run_with_the_model() {
        let (Ok(python), Ok(task), Ok(part), Ok(note)) = (
            std::env::var("MARINAFRAME_TEST_PYTHON"),
            std::env::var("MARINAFRAME_REVISE_TASK"),
            std::env::var("MARINAFRAME_REVISE_PART"),
            std::env::var("MARINAFRAME_REVISE_NOTE"),
        ) else {
            return;
        };
        let task = PathBuf::from(task);
        let tmp = tempfile::tempdir().unwrap();
        let paths = AppPaths {
            config_dir: tmp.path().join("config"),
            data_dir: tmp.path().join("data"),
            repo_root: None,
        };
        parts::review_component(&paths, &task, &part, "marked", Some(&note)).unwrap();
        let (_, key) = crate::model_keys::configured_keys()
            .1
            .into_iter()
            .next()
            .expect("a model key");
        let src = Path::new(env!("CARGO_MANIFEST_DIR")).join("../../src");
        let worker = Worker {
            python: &python,
            source: Some(&src),
        };
        let started = std::time::Instant::now();
        let view = revise_part(
            &ActionRegistry::default(),
            &paths,
            &task,
            &part,
            &worker,
            &Model::Key(key),
            REVISE_STALL_PERIOD,
        )
        .unwrap();
        eprintln!(
            "revision {} in {:.0} s; changes: {}",
            view.revision,
            started.elapsed().as_secs_f64(),
            serde_json::to_string(&view.changes).unwrap()
        );
        assert!(view.revision_pending);
    }

    #[test]
    fn a_re_run_needs_a_mark_note() {
        let tmp = tempfile::tempdir().unwrap();
        let (paths, task) = setup(&tmp);
        let registry = ActionRegistry::default();
        let model = Model::Scripted(tmp.path().join("replies.json"));
        let refused = revise_part(
            &registry,
            &paths,
            &task,
            "wheelhouse",
            &NO_PYTHON,
            &model,
            REVISE_STALL_PERIOD,
        )
        .unwrap_err();
        assert_eq!(refused.code, "revise_needs_mark");
        parts::review_component(&paths, &task, "wheelhouse", "accepted", None).unwrap();
        let refused = revise_part(
            &registry,
            &paths,
            &task,
            "wheelhouse",
            &NO_PYTHON,
            &model,
            REVISE_STALL_PERIOD,
        )
        .unwrap_err();
        assert_eq!(refused.code, "revise_needs_mark");
    }

    #[test]
    fn a_re_run_waits_for_another_action_on_the_run() {
        let tmp = tempfile::tempdir().unwrap();
        let (paths, task) = setup(&tmp);
        parts::review_component(&paths, &task, "wheelhouse", "marked", Some("Lower it")).unwrap();
        let registry = ActionRegistry::default();
        let _other = registry.begin(&task).unwrap();
        let model = Model::Scripted(tmp.path().join("replies.json"));
        let refused = revise_part(
            &registry,
            &paths,
            &task,
            "wheelhouse",
            &NO_PYTHON,
            &model,
            REVISE_STALL_PERIOD,
        )
        .unwrap_err();
        assert_eq!(refused.code, "action_in_progress");
        for refused in [
            keep_revision(&registry, &paths, &task, "wheelhouse", &NO_PYTHON),
            undo_revision(&registry, &paths, &task, "wheelhouse", &NO_PYTHON),
        ] {
            assert_eq!(refused.unwrap_err().code, "action_in_progress");
        }
    }

    #[test]
    fn a_missing_worker_python_is_said_plainly_and_frees_the_run() {
        let tmp = tempfile::tempdir().unwrap();
        let (paths, task) = setup(&tmp);
        parts::review_component(&paths, &task, "wheelhouse", "marked", Some("Lower it")).unwrap();
        let registry = ActionRegistry::default();
        let model = Model::Key("not-a-real-key".into());
        let refused = revise_part(
            &registry,
            &paths,
            &task,
            "wheelhouse",
            &NO_PYTHON,
            &model,
            REVISE_STALL_PERIOD,
        )
        .unwrap_err();
        assert_eq!(refused.code, "worker_python_missing");
        assert!(!refused.message.contains("not-a-real-key"));
        assert!(!registry.is_busy(&task));
    }

    /// A re-run's entry as the worker writes it: the change list says what differs.
    #[test]
    fn a_new_revision_shows_what_changed_until_kept() {
        let tmp = tempfile::tempdir().unwrap();
        let (_, task) = setup(&tmp);
        let previous = json!({"id": "wheelhouse", "op": "deckhouse", "status": "draft_guess",
            "built": true, "source_labels": {"height": "traced", "outline": "guessed"},
            "geometry": {"height": [9.0, 11.5], "outline": [[0, 0], [1, 0], [1, 1], [0, 1]]},
            "provenance": {}, "volume_m3": 130.9});
        let mut entry = json!({"id": "wheelhouse", "op": "deckhouse", "status": "draft_guess",
            "built": true, "source_labels": {"height": "ai_inferred", "outline": "guessed"},
            "geometry": {"height": [9.0, 11.0], "outline": [[0, 0], [1, 0], [1, 1], [0, 1]]},
            "provenance": {}, "volume_m3": 100.0, "revision": 1, "revision_note": "Lower the roof",
            "revision_kept": false, "revision_history": [previous]});
        let write = |entry: &serde_json::Value| {
            let record = json!({"result": {"components": [entry]}});
            std::fs::write(task.join(parts::EXECUTION_FILE), record.to_string()).unwrap();
        };
        write(&entry);
        let part = part_view(&task, "wheelhouse", &HashMap::new()).unwrap();
        assert_eq!(
            (
                part.revision,
                part.revision_note.as_deref(),
                part.revision_pending
            ),
            (1, Some("Lower the roof"), true)
        );
        let names: Vec<&str> = part.changes.iter().map(|c| c.name.as_str()).collect();
        assert_eq!(names, ["height", "volume"]);
        let height = &part.changes[0];
        assert_eq!(
            (
                height.before.as_deref(),
                height.after.as_deref(),
                height.before_source.as_deref(),
                height.after_source.as_deref()
            ),
            (
                Some("9.000 to 11.500 m"),
                Some("9.000 to 11.000 m"),
                Some("traced"),
                Some("ai_inferred")
            )
        );
        entry["revision_kept"] = json!(true);
        write(&entry);
        let part = part_view(&task, "wheelhouse", &HashMap::new()).unwrap();
        assert!(!part.revision_pending && part.revision == 1 && !part.changes.is_empty());
    }
}
