//! Re-run one whole-vessel part from the person's mark, then keep or undo the new revision
//! (APP_SPEC "Whole-vessel parts").
//!
//! A re-run goes in turns. The Python worker `python -m vessel_reconstruction.part_revise`
//! (`--prepare`) checks the request and writes a vision request of the part: crops of the
//! run's drawings, the part's values and the note. This module sends that request through the
//! controller's supervised provider worker (`marinaframe_control::provider::vision`), as every
//! controller model call goes: the model comes from [`ModelChoice`], the budget is checked
//! before each call and each call writes a receipt. The reply is checked against the part
//! program schema (`provider::part_revision`). The worker (`--build`) then builds that program
//! with the model-written values in its Seatbelt sandbox; when it does not build, the model is
//! asked again with the reason. The Python worker never sees a model key.
use crate::actions::{ActionRegistry, AI_DRAFTING_BASIS};
use crate::error::{AppError, AppResult};
use crate::intake::Worker;
use crate::parts::{self, PartReview};
use crate::storage::AppPaths;
use crate::types::ComponentView;
use crate::worker_run::{Supervision, WorkerWords, UNCANCELLABLE};
use marinaframe_control::models::{self, DEFAULT_MODELS};
use marinaframe_control::provider::part_revision::PartProgram;
use marinaframe_control::provider::vision::{self, RequestManifest, Responder, Usage, VisionReply};
use marinaframe_control::provider::{ProviderInput, Receipt};
use marinaframe_control::supervised::{self, WorkerCommand};
use marinaframe_control::types::OperationalLimits;
use marinaframe_control::{controller, util};
use serde_json::{json, Value};
use std::cell::RefCell;
use std::collections::{HashMap, VecDeque};
use std::ffi::OsStr;
use std::path::{Path, PathBuf};
use std::time::Duration;

/// A worker stage with no progress report for this long is stopped. The build stage waits
/// on the sandboxed part build, which keeps its own caps and watchdog inside the worker.
/// There is no limit on the total time.
pub const REVISE_STALL_PERIOD: Duration = Duration::from_secs(2 * 300);
/// Model turns of one re-run: a reply that does not build goes back with the reason.
pub const MAX_TURNS: u32 = 3;
/// The budget of one re-run. Each turn may take up to three attempts (the provider path
/// retries transient failures), so nine requests cover three turns.
pub const MAX_REQUESTS: u64 = 9;
/// One request is about 20,000 tokens (three crops and the part's values).
pub const MAX_TOTAL_TOKENS: u64 = 250_000;
/// Observed spend in USD (OpenCode Go models; the Claude subscription costs 0 per call).
pub const MAX_SPEND_USD: f64 = 2.0;
/// The previous program goes back to the model with the reason; at most this many bytes,
/// so the request's task text stays within its 16 KiB limit.
const MAX_PREVIOUS_PROGRAM_BYTES: usize = 4096;
/// How part-worker errors are named.
const PART_WORDS: WorkerWords = WorkerWords {
    code: "part_revise",
    name: "The re-run",
    after_stop: " The old part stays.",
};

/// Who answers the re-run's model requests.
pub enum Replies {
    /// The model, through the controller's provider worker (the app's executable run as
    /// `provider-worker`; it loads the model keys itself).
    ProviderWorker,
    /// Scripted replies (a JSON list of strings) for tests. Each one is answered in the
    /// form of the chosen model's transport and goes through the same checks and receipts;
    /// no request is sent.
    Scripted(PathBuf),
}

/// The model configuration of a re-run: the ordered model list (a rate-limit answer moves
/// the re-run to the next model), the budget and who answers.
pub struct ModelChoice {
    pub models: Vec<String>,
    pub limits: OperationalLimits,
    pub replies: Replies,
}

impl ModelChoice {
    /// The app's models (the same ordered list as an app run, `actions::app_run_config`)
    /// with the re-run budget.
    pub fn app() -> Self {
        Self::new(
            DEFAULT_MODELS.iter().map(|m| m.to_string()).collect(),
            Replies::ProviderWorker,
        )
    }

    pub fn new(models: Vec<String>, replies: Replies) -> Self {
        Self {
            models,
            limits: budget(),
            replies,
        }
    }
}

/// The controller's limits with the re-run budget.
pub fn budget() -> OperationalLimits {
    OperationalLimits {
        max_requests: Some(MAX_REQUESTS),
        max_total_tokens: Some(MAX_TOTAL_TOKENS),
        max_spend_usd: Some(MAX_SPEND_USD),
        ..OperationalLimits::default()
    }
}

enum Action<'a> {
    Prepare { note: &'a str },
    Build { work: &'a Path, turn: u32 },
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
    model: &ModelChoice,
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
    models::check_list(&model.models.iter().map(String::as_str).collect::<Vec<_>>())?;
    let _guard = registry.begin(task)?;
    let prepared = run_worker(
        worker,
        task,
        component_id,
        Action::Prepare { note: &note },
        stall_period,
    )?;
    let work = work_folder(task, component_id, &prepared)?;
    let turns = Turns {
        worker,
        task,
        component_id,
        work: &work,
        stall_period,
    };
    turns.run(model)?;
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

/// The work folder the prepare stage made: inside this run's revisions folder.
fn work_folder(task: &Path, component_id: &str, prepared: &Value) -> AppResult<PathBuf> {
    let refused = || {
        AppError::new(
            "part_revise_worker",
            "The re-run could not be prepared. The old part stays.",
        )
    };
    let work = prepared["work"]
        .as_str()
        .and_then(|w| Path::new(w).canonicalize().ok())
        .ok_or_else(refused)?;
    let revisions = task
        .join("whole_vessel")
        .join("revisions")
        .canonicalize()
        .map_err(|_| refused())?;
    let name = work.file_name().and_then(OsStr::to_str).unwrap_or("");
    if work.parent() != Some(revisions.as_path()) || !name.starts_with(&format!("{component_id}-r"))
    {
        return Err(refused());
    }
    Ok(work)
}

/// The model turns of one prepared re-run.
struct Turns<'a> {
    worker: &'a Worker<'a>,
    task: &'a Path,
    component_id: &'a str,
    work: &'a Path,
    stall_period: Duration,
}

/// Why the next turn asks the model again.
struct Retry {
    /// The previous program, when it was well formed but did not build.
    program: Option<String>,
    /// What the model is told.
    problem: String,
    /// The refusal code when the reply did not match the part program form.
    form_error: Option<String>,
}

impl Retry {
    fn form(code: &str, problem: String) -> Self {
        Self {
            program: None,
            problem,
            form_error: Some(code.to_string()),
        }
    }
}

impl Turns<'_> {
    fn run(&self, model: &ModelChoice) -> AppResult<()> {
        let request = self.work.join("request");
        let (manifest, manifest_sha256, images) = vision::load_request(&request)?;
        let op = manifest.context["part"]["op"]
            .as_str()
            .unwrap_or_default()
            .to_string();
        let mut config =
            vision::standalone_config(AI_DRAFTING_BASIS, &request.join("request.json"))?;
        config.limits = model.limits.clone();
        config.model = model.models[0].clone();
        for folder in ["requests", "receipts"] {
            std::fs::create_dir_all(self.work.join(folder))
                .map_err(|_| AppError::from_code("part_revise_work_folder"))?;
        }
        let scripted = match &model.replies {
            Replies::ProviderWorker => None,
            Replies::Scripted(path) => Some(RefCell::new(scripted_replies(path)?)),
        };
        let answer = |input: &ProviderInput| -> Vec<u8> {
            let reply = scripted
                .as_ref()
                .and_then(|queue| queue.borrow_mut().pop_front())
                .unwrap_or_default();
            let model = input.payload["model"].as_str().unwrap_or_default();
            vision::recorded_body(model, &reply).unwrap_or_default()
        };
        let responder = if scripted.is_some() {
            Responder::Recorded(&answer)
        } else {
            Responder::ProviderWorker
        };
        let model_list: Vec<&str> = model.models.iter().map(String::as_str).collect();
        let mut usage = Usage::default();
        let mut summaries = vec![];
        let mut retry: Option<Retry> = None;
        let mut turn = 1;
        while turn <= MAX_TURNS {
            if usage.within_budget(&config.limits).is_err() {
                return Err(budget_used_up(&usage));
            }
            let template = vision::template(
                &config.model,
                &with_retry(&manifest, retry.as_ref()),
                &manifest_sha256,
                &images,
                "part_revision",
            )?;
            let sent = vision::send_with(self.work, "", &config, &template, &mut usage, responder)?;
            summaries.extend(sent.receipts.iter().map(receipt_summary));
            util::atomic_json(&self.work.join("receipts.json"), &summaries, true)?;
            if let Some(stop) = sent.stop {
                return Err(model_stopped(&stop));
            }
            let Some(VisionReply::PartRevision(program)) = sent.reply else {
                let last = sent
                    .receipts
                    .last()
                    .ok_or_else(|| model_stopped("provider_not_sent"))?;
                let code = last
                    .error_code
                    .clone()
                    .unwrap_or_else(|| "provider_failed".into());
                if models::rate_limited(last) {
                    if let Some(next) = models::next(&model_list, &config.model) {
                        config.model = next.to_string();
                        continue;
                    }
                }
                if !controller::model_output_refused(last) {
                    return Err(model_stopped(&code));
                }
                let problem = format!(
                    "Your reply did not match the response_schema ({code}). Reply with the complete program again."
                );
                retry = Some(Retry::form(&code, problem));
                turn += 1;
                continue;
            };
            if let Err(problem) = self.check_part(&program, &op) {
                retry = Some(Retry::form("part_program_wrong_part", problem));
                turn += 1;
                continue;
            }
            let text = String::from_utf8(util::json_bytes(&program)?).unwrap_or_default();
            util::atomic_json(
                &self.work.join(format!("program-{turn}.json")),
                &program,
                false,
            )?;
            let outcome = run_worker(
                self.worker,
                self.task,
                self.component_id,
                Action::Build {
                    work: self.work,
                    turn,
                },
                self.stall_period,
            )?;
            if outcome["built"] == true {
                return Ok(());
            }
            let problem = outcome["problem"]
                .as_str()
                .unwrap_or("not built")
                .to_string();
            retry = Some(Retry {
                program: Some(text),
                problem: format!(
                    "Not built: {problem}. Reply with the complete program again, in the same form."
                ),
                form_error: None,
            });
            turn += 1;
        }
        Err(match retry {
            Some(Retry {
                form_error: Some(code),
                ..
            }) => AppError::new(
                "part_revise_model_reply",
                &format!(
                    "The model reply did not match the part program form ({code}). The old part stays."
                ),
            ),
            Some(retry) => not_rebuilt(&retry.problem),
            None => not_rebuilt("no model turn was made"),
        })
    }

    /// The reply must be the marked part with its own operation.
    fn check_part(&self, program: &PartProgram, op: &str) -> Result<(), String> {
        let component = program.component();
        if component.id != self.component_id || component.op != op {
            return Err(format!(
                "The program must have exactly the component {} with op {op} (part_program_wrong_part). Reply with the complete program again.",
                self.component_id
            ));
        }
        Ok(())
    }
}

/// The request of a turn: the prepared task text plus, after the first turn, why the model is
/// asked again.
fn with_retry(manifest: &RequestManifest, retry: Option<&Retry>) -> RequestManifest {
    let mut manifest = manifest.clone();
    if let Some(retry) = retry {
        let context = manifest
            .context
            .as_object_mut()
            .expect("checked by load_request");
        context.insert("retry_reason".into(), json!(retry.problem));
        if let Some(program) = retry
            .program
            .as_ref()
            .filter(|p| p.len() <= MAX_PREVIOUS_PROGRAM_BYTES)
        {
            context.insert("previous_program".into(), json!(program));
        }
    }
    manifest
}

fn scripted_replies(path: &Path) -> AppResult<VecDeque<String>> {
    let bytes = util::read_bounded(path, 1024 * 1024)?;
    let replies: Vec<String> = serde_json::from_slice(&bytes)
        .map_err(|_| AppError::from_code("part_revise_scripted_replies"))?;
    Ok(replies.into())
}

/// One line of `revision_receipts`: which model answered and what it cost. The full receipt
/// stays in the work folder (`receipts/<request_id>.json`). Never holds a key.
fn receipt_summary(receipt: &Receipt) -> Value {
    json!({"request_id": receipt.request_id, "state": receipt.state,
           "requested_model": receipt.requested_model, "returned_model": receipt.returned_model,
           "request_sha256": receipt.request_sha256, "response_sha256": receipt.response_sha256,
           "usage": receipt.usage, "latency_seconds": receipt.latency_seconds,
           "error_code": receipt.error_code, "evidence_mode": receipt.evidence_mode,
           "receipt": format!("receipts/{}.json", receipt.request_id)})
}

fn budget_used_up(usage: &Usage) -> AppError {
    AppError::new(
        "part_revise_budget",
        &format!(
            "The model budget of this re-run is used up ({} requests, {} tokens). The old part stays.",
            usage.requests_intended,
            usage.prompt_tokens + usage.completion_tokens
        ),
    )
}

fn model_stopped(code: &str) -> AppError {
    AppError::new(
        "part_revise_model",
        &format!("The model request did not complete ({code}). The old part stays."),
    )
}

fn not_rebuilt(problem: &str) -> AppError {
    let problem: String = problem.chars().take(200).collect();
    AppError::new(
        "part_revise_worker",
        &format!("The part was not rebuilt ({problem}); the old part stays."),
    )
}

fn run_worker(
    worker: &Worker,
    task: &Path,
    component_id: &str,
    action: Action,
    stall_period: Duration,
) -> AppResult<Value> {
    // The shared worker environment holds no model key; none is added here.
    let mut command: WorkerCommand = worker.module_command("vessel_reconstruction.part_revise")?;
    command
        .args([OsStr::new("--task"), task.as_os_str()])
        .args(["--part", component_id]);
    match action {
        Action::Prepare { note } => {
            // One argument: a note that starts with "-" stays the note.
            command.arg("--prepare").arg(format!("--note={note}"));
        }
        Action::Build { work, turn } => {
            command
                .args(["--build", &turn.to_string()])
                .args([OsStr::new("--work"), work.as_os_str()]);
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
        return serde_json::from_slice(&finished.stdout).map_err(|_| {
            AppError::new(
                "part_revise_worker",
                "The part worker gave no result. The old part stays.",
            )
        });
    }
    // The worker writes {"error": "..."} for a refusal it explains; anything else is generic.
    let reason = serde_json::from_slice::<Value>(&finished.stderr)
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

    /// One real re-run with the model, through the app path (the app's models through the
    /// provider worker, the real Python worker). The provider worker is this test binary run
    /// as `provider-worker`, which it is not; run it from the app build instead. Never on a
    /// committed folder: copy a run first; drawings may be licensed.
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
            &ModelChoice::app(),
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
        let model = ModelChoice::new(
            vec![models::DEEPSEEK_V4_1_FLASH.into()],
            Replies::Scripted(tmp.path().join("replies.json")),
        );
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
        let model = ModelChoice::new(
            vec![models::DEEPSEEK_V4_1_FLASH.into()],
            Replies::Scripted(tmp.path().join("replies.json")),
        );
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
        let model = ModelChoice::app();
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
    // ------------------------------------------------------------ model turns

    /// A PNG header (`provider::check_png` reads only the header).
    fn tiny_png() -> Vec<u8> {
        let mut png = b"\x89PNG\r\n\x1a\n\x00\x00\x00\x0dIHDR".to_vec();
        png.extend(8u32.to_be_bytes());
        png.extend(8u32.to_be_bytes());
        png.extend([8, 0, 0, 0, 0, 0, 0, 0, 0]);
        png
    }

    /// A prepared re-run as the Python `--prepare` stage leaves it.
    fn prepared_work(task: &Path) -> PathBuf {
        let work = task.join("whole_vessel/revisions/wheelhouse-r1-test");
        let request = work.join("request");
        std::fs::create_dir_all(&request).unwrap();
        let png = tiny_png();
        std::fs::write(request.join("1-plan.png"), &png).unwrap();
        let manifest = json!({"schema_version": vision::REQUEST_VERSION, "purpose": "part_revision",
            "source_sha256": "a".repeat(64), "engineering_approved": false,
            "context": {"part": {"id": "wheelhouse", "label": "Wheelhouse", "op": "deckhouse"},
                        "note": "Make it 1 m wide"},
            "images": [{"image_id": "image-1", "file": "1-plan.png", "sha256": util::hash(&png),
                        "bytes": png.len(), "width": 8, "height": 8, "view": "plan",
                        "crop_box_px": [0, 0, 8, 8]}]});
        std::fs::write(request.join("request.json"), manifest.to_string()).unwrap();
        work
    }

    /// A stand-in for the Python worker: `--prepare` names the prepared work folder and
    /// `--build` says the part built. Each call is logged.
    fn fake_worker(tmp: &Path, work: &Path) -> (String, PathBuf) {
        use std::os::unix::fs::PermissionsExt;
        let calls = tmp.join("calls.txt");
        let script = tmp.join("fake-python");
        let text = format!(
            "#!/bin/sh\necho \"$*\" >> '{calls}'\ncase \"$*\" in\n  *--prepare*) echo '{{\"work\":\"{work}\"}}' ;;\n  *--build*) echo '{{\"built\":true}}' ;;\nesac\n",
            calls = calls.display(),
            work = work.display()
        );
        std::fs::write(&script, text).unwrap();
        std::fs::set_permissions(&script, std::fs::Permissions::from_mode(0o755)).unwrap();
        (script.to_string_lossy().into_owned(), calls)
    }

    fn reply(id: &str) -> String {
        let inline =
            |value: Value| json!({"value": value, "source": "ai_inferred", "basis": "the note"});
        json!({"schema": "ship-cad/v1", "components": [{"id": id, "op": "deckhouse",
            "source": {"view": "plan", "region": "wheelhouse", "method": "closed_outline"},
            "args": {"outline": inline(json!([[14, -0.5], [21, -0.5], [21, 0.5], [14, 0.5]])),
                     "height": inline(json!([9.0, 11.5]))}}]})
        .to_string()
    }

    struct Revised {
        result: AppResult<ComponentView>,
        work: PathBuf,
        calls: String,
        _tmp: tempfile::TempDir,
    }

    /// One re-run with scripted replies, the fake worker and `models` with `limits`.
    fn revise_with(
        replies: &[String],
        models: &[&str],
        limits: Option<OperationalLimits>,
    ) -> Revised {
        let tmp = tempfile::tempdir().unwrap();
        let (paths, task) = setup(&tmp);
        parts::review_component(
            &paths,
            &task,
            "wheelhouse",
            "marked",
            Some("Make it 1 m wide"),
        )
        .unwrap();
        let work = prepared_work(&task);
        let (python, calls) = fake_worker(tmp.path(), &work);
        let replies_path = tmp.path().join("replies.json");
        std::fs::write(&replies_path, serde_json::to_vec(replies).unwrap()).unwrap();
        let mut model = ModelChoice::new(
            models.iter().map(|m| m.to_string()).collect(),
            Replies::Scripted(replies_path),
        );
        if let Some(limits) = limits {
            model.limits = limits;
        }
        let worker = Worker {
            python: &python,
            source: None,
        };
        let result = revise_part(
            &ActionRegistry::default(),
            &paths,
            &task,
            "wheelhouse",
            &worker,
            &model,
            REVISE_STALL_PERIOD,
        );
        let calls = std::fs::read_to_string(calls).unwrap_or_default();
        Revised {
            result,
            work,
            calls,
            _tmp: tmp,
        }
    }

    /// The receipts in call order (the order of the summaries in `receipts.json`).
    fn receipts(work: &Path) -> Vec<Receipt> {
        let summaries: Vec<Value> =
            serde_json::from_slice(&std::fs::read(work.join("receipts.json")).unwrap()).unwrap();
        assert_eq!(
            summaries.len(),
            std::fs::read_dir(work.join("receipts")).unwrap().count()
        );
        summaries
            .iter()
            .map(|summary| {
                let path = work.join(summary["receipt"].as_str().unwrap());
                serde_json::from_slice(&std::fs::read(path).unwrap()).unwrap()
            })
            .collect()
    }

    #[test]
    fn the_model_comes_from_the_configuration() {
        assert_eq!(ModelChoice::app().models, DEFAULT_MODELS);
        for model in [
            models::DEEPSEEK_V4_1_FLASH,
            models::CROUTON_ALPHA_FREE,
            models::CLAUDE_SONNET_5_5,
        ] {
            let revised = revise_with(&[reply("wheelhouse")], &[model], None);
            revised.result.unwrap();
            let receipts = receipts(&revised.work);
            assert_eq!(receipts.len(), 1);
            assert_eq!(receipts[0].requested_model, model);
            assert_eq!(receipts[0].endpoint, models::endpoint(model).unwrap());
        }
        let refused = revise_with(&[reply("wheelhouse")], &["claude-opus-5-5"], None);
        assert_eq!(refused.result.unwrap_err().code, "model_not_allowed");
    }

    #[test]
    fn each_model_call_writes_a_receipt_and_its_summary() {
        let revised = revise_with(
            &["not json".into(), reply("wheelhouse")],
            &[models::DEEPSEEK_V4_1_FLASH],
            None,
        );
        revised.result.unwrap();
        let receipts = receipts(&revised.work);
        assert_eq!(receipts.len(), 2);
        assert_eq!(
            receipts[0].error_code.as_deref(),
            Some("part_program_invalid_json")
        );
        assert!(receipts[1].vision.is_some() && receipts[1].error_code.is_none());
        for receipt in &receipts {
            assert_eq!(receipt.requested_model, models::DEEPSEEK_V4_1_FLASH);
            assert!(util::valid_hash(&receipt.request_sha256));
            assert!(receipt
                .response_sha256
                .as_deref()
                .is_some_and(util::valid_hash));
            assert_eq!(receipt.usage["prompt_tokens"], 1000);
        }
        assert_eq!(
            std::fs::read_dir(revised.work.join("requests"))
                .unwrap()
                .count(),
            2
        );
        let summaries: Vec<Value> =
            serde_json::from_slice(&std::fs::read(revised.work.join("receipts.json")).unwrap())
                .unwrap();
        assert_eq!(summaries.len(), 2);
        assert_eq!(summaries[1]["request_id"], json!(receipts[1].request_id));
        // Only the valid program was built.
        assert_eq!(revised.calls.matches("--build").count(), 1);
        assert!(
            revised.work.join("program-2.json").is_file()
                && !revised.work.join("program-1.json").exists()
        );
    }

    #[test]
    fn invalid_model_output_is_a_typed_error_and_nothing_is_built() {
        let revised = revise_with(
            &[
                "not json".into(),
                "{\"schema\":\"ship-cad/v1\"}".into(),
                reply("other_part"),
            ],
            &[models::CLAUDE_SONNET_5_5],
            None,
        );
        let error = revised.result.unwrap_err();
        assert_eq!(error.code, "part_revise_model_reply");
        assert!(
            error.message.contains("part_program_wrong_part"),
            "{}",
            error.message
        );
        let codes: Vec<Option<String>> = receipts(&revised.work)
            .into_iter()
            .map(|r| r.error_code)
            .collect();
        assert_eq!(
            codes,
            [
                Some("part_program_invalid_json".into()),
                Some("part_program_invalid_json".into()),
                None
            ]
        );
        assert!(!revised.calls.contains("--build"));
    }

    #[test]
    fn a_used_up_budget_stops_the_re_run_with_a_clear_message() {
        let limits = OperationalLimits {
            max_requests: Some(1),
            ..budget()
        };
        let revised = revise_with(
            &["not json".into(), reply("wheelhouse")],
            &[models::DEEPSEEK_V4_1_FLASH],
            Some(limits),
        );
        let error = revised.result.unwrap_err();
        assert_eq!(error.code, "part_revise_budget");
        assert!(
            error
                .message
                .contains("budget of this re-run is used up (1 requests"),
            "{}",
            error.message
        );
        assert_eq!(receipts(&revised.work).len(), 1);
        let tokens = OperationalLimits {
            max_total_tokens: Some(1100),
            ..budget()
        };
        let revised = revise_with(
            &["not json".into(), reply("wheelhouse")],
            &[models::DEEPSEEK_V4_1_FLASH],
            Some(tokens),
        );
        assert_eq!(revised.result.unwrap_err().code, "part_revise_budget");
        assert!(!revised.calls.contains("--build"));
    }
}
