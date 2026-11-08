// Tauri shell. Every command only translates arguments and errors; all logic is in
// `marinaframe-app-core`, which has no Tauri types.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use marinaframe_app_core::intake::IntakePreview;
use marinaframe_app_core::types::*;
use marinaframe_app_core::{AppError, AppPaths, AppResult, Backend};
use std::path::PathBuf;
use std::sync::Arc;
use std::time::Duration;
use tauri::{Emitter, Manager, State};

type Shared<'a> = State<'a, Arc<Backend>>;

/// Run blocking backend work off the UI thread.
async fn run<T: Send + 'static>(
    backend: Shared<'_>,
    work: impl FnOnce(&Backend) -> AppResult<T> + Send + 'static,
) -> Result<T, AppError> {
    let backend = backend.inner().clone();
    tauri::async_runtime::spawn_blocking(move || work(&backend))
        .await
        .map_err(|_| AppError::new("internal", "The app hit an internal error."))?
}

#[derive(serde::Serialize)]
struct Ok_ {
    ok: bool,
}
const OK: Ok_ = Ok_ { ok: true };

#[derive(serde::Serialize)]
struct Started {
    task: String,
}

#[tauri::command(rename_all = "snake_case")]
async fn list_tasks(backend: Shared<'_>) -> Result<Vec<TaskSummary>, AppError> {
    run(backend, |b| Ok(b.list_tasks())).await
}

#[tauri::command(rename_all = "snake_case")]
async fn get_task(backend: Shared<'_>, task: String) -> Result<TaskView, AppError> {
    run(backend, move |b| b.get_task(&task)).await
}

#[tauri::command(rename_all = "snake_case")]
async fn get_events(
    backend: Shared<'_>,
    task: String,
    after_sequence: u64,
) -> Result<Vec<EventView>, AppError> {
    run(backend, move |b| b.get_events(&task, after_sequence)).await
}

#[tauri::command(rename_all = "snake_case")]
async fn read_artifact(
    backend: Shared<'_>,
    task: String,
    path: String,
) -> Result<Artifact, AppError> {
    run(backend, move |b| b.read_artifact(&task, &path)).await
}

#[tauri::command(rename_all = "snake_case")]
async fn start_run(backend: Shared<'_>, spec_path: String) -> Result<Started, AppError> {
    run(backend, move |b| {
        b.start_run(&spec_path).map(|task| Started { task })
    })
    .await
}

/// Read a dropped drawing set (PDF, PNG, TIFF, JPEG) without a spec file.
#[tauri::command(rename_all = "snake_case")]
async fn prepare_intake(
    backend: Shared<'_>,
    files: Vec<String>,
) -> Result<IntakePreview, AppError> {
    run(backend, move |b| b.prepare_intake(&files)).await
}

/// Write the spec of the edited preview and start its run with the current AI setting.
#[tauri::command(rename_all = "snake_case")]
async fn start_intake_run(
    backend: Shared<'_>,
    preview: IntakePreview,
) -> Result<Started, AppError> {
    run(backend, move |b| {
        b.start_intake_run(&preview).map(|task| Started { task })
    })
    .await
}

#[tauri::command(rename_all = "snake_case")]
async fn cancel_task(backend: Shared<'_>, task: String) -> Result<Ok_, AppError> {
    run(backend, move |b| b.cancel_task(&task).map(|_| OK)).await
}

#[tauri::command(rename_all = "snake_case")]
async fn resume_task(backend: Shared<'_>, task: String) -> Result<Ok_, AppError> {
    run(backend, move |b| b.resume_task(&task).map(|_| OK)).await
}

#[tauri::command(rename_all = "snake_case")]
async fn choose_line(
    backend: Shared<'_>,
    task: String,
    section_id: String,
    candidate_id: String,
) -> Result<Ok_, AppError> {
    run(backend, move |b| {
        b.choose_line(&task, &section_id, &candidate_id).map(|_| OK)
    })
    .await
}

#[tauri::command(rename_all = "snake_case")]
async fn get_settings(backend: Shared<'_>) -> Result<Settings, AppError> {
    run(backend, |b| Ok(b.get_settings())).await
}

#[tauri::command(rename_all = "snake_case")]
async fn get_default_settings(backend: Shared<'_>) -> Result<Settings, AppError> {
    run(backend, |b| Ok(b.default_settings())).await
}

/// The spec says the argument is `Settings`. Both `{ settings: {...} }` and the
/// three fields at the top level are accepted; missing fields keep their value.
#[tauri::command(rename_all = "snake_case")]
async fn set_settings(
    backend: Shared<'_>,
    settings: Option<Settings>,
    runs_folder: Option<String>,
    worker_python: Option<String>,
    theme: Option<Theme>,
    ai_drafting: Option<bool>,
) -> Result<Settings, AppError> {
    run(backend, move |b| {
        let next = settings.unwrap_or_else(|| {
            let current = b.get_settings();
            Settings {
                runs_folder: runs_folder.unwrap_or(current.runs_folder),
                worker_python: worker_python.unwrap_or(current.worker_python),
                theme: theme.unwrap_or(current.theme),
                ai_drafting: ai_drafting.unwrap_or(current.ai_drafting),
            }
        });
        b.set_settings(next)
    })
    .await
}

#[tauri::command(rename_all = "snake_case")]
async fn get_ai_status(backend: Shared<'_>) -> Result<AiStatus, AppError> {
    run(backend, move |b| Ok(b.ai_status())).await
}

#[tauri::command(rename_all = "snake_case")]
async fn dismiss_notice(backend: Shared<'_>, id: String) -> Result<Ok_, AppError> {
    run(backend, move |b| b.dismiss_notice(&id).map(|_| OK)).await
}

#[tauri::command(rename_all = "snake_case")]
async fn reset_notices(backend: Shared<'_>) -> Result<Ok_, AppError> {
    run(backend, |b| b.reset_notices().map(|_| OK)).await
}

#[tauri::command(rename_all = "snake_case")]
async fn list_datasets(backend: Shared<'_>) -> Result<Vec<Dataset>, AppError> {
    run(backend, |b| Ok(b.list_datasets())).await
}

/// Source checkout of a development build, used for the default Python and datasets.
fn development_checkout() -> Option<PathBuf> {
    let root = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../..");
    root.join("pyproject.toml")
        .is_file()
        .then(|| root.canonicalize().ok())
        .flatten()
}

/// The controller runs each model request in a child process of its own
/// executable (`<exe> provider-worker --response FILE --timeout SECONDS`). In the
/// desktop app that executable is the app, so handle that call before any window
/// or thread starts. Returns the process exit code when this was such a call.
fn run_provider_worker_if_asked() -> Option<i32> {
    let args: Vec<String> = std::env::args().skip(1).collect();
    if args.first().map(String::as_str) != Some("provider-worker") {
        return None;
    }
    let value = |flag: &str| {
        args.iter()
            .position(|a| a == flag)
            .and_then(|i| args.get(i + 1))
            .cloned()
    };
    let (Some(response), Some(timeout)) = (value("--response"), value("--timeout")) else {
        return Some(2);
    };
    let Ok(timeout) = timeout.parse::<u64>() else {
        return Some(2);
    };
    let finished =
        marinaframe_app_core::model_keys::run_provider_worker(&PathBuf::from(response), timeout);
    Some(if finished { 0 } else { 1 })
}

fn main() {
    if let Some(code) = run_provider_worker_if_asked() {
        std::process::exit(code);
    }
    tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .setup(|app| {
            let resolver = app.path();
            let repo_root = development_checkout();
            let paths = AppPaths {
                config_dir: resolver.app_config_dir()?,
                data_dir: resolver.app_data_dir()?,
                repo_root: repo_root.clone(),
            };
            // Development override for the Python worker's source folder.
            let worker_source = std::env::var_os("MARINAFRAME_WORKER_SOURCE").map(PathBuf::from);
            let datasets_root = repo_root.map(|root| root.join("work/sources"));
            let backend = Arc::new(Backend::new(paths, worker_source, datasets_root));

            // `task-changed`: poll the event counts of all tasks every 500 ms.
            let watcher_backend = backend.clone();
            let handle = app.handle().clone();
            std::thread::Builder::new()
                .name("marinaframe-watch".into())
                .spawn(move || {
                    let mut watcher = watcher_backend.watcher();
                    loop {
                        for change in watcher_backend.poll_changes(&mut watcher) {
                            let _ = handle.emit("task-changed", change);
                        }
                        std::thread::sleep(Duration::from_millis(500));
                    }
                })?;
            app.manage(backend);
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            list_tasks,
            get_task,
            get_events,
            read_artifact,
            start_run,
            prepare_intake,
            start_intake_run,
            cancel_task,
            resume_task,
            choose_line,
            get_settings,
            get_default_settings,
            set_settings,
            get_ai_status,
            dismiss_notice,
            reset_notices,
            list_datasets
        ])
        .run(tauri::generate_context!())
        .expect("the MarinaFrame window could not start");
}
