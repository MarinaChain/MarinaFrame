//! Exports of a finished run (milestone M5).
//!
//! `export_run` runs the Python worker `python -m vessel_reconstruction.exports`
//! for one revision of a task. The worker always writes every export into a
//! staging folder; this module then moves the outputs the person chose into
//! `<task>/exports/<rNNNN>/` and deletes the staging folder. The manifest (file
//! list with SHA-256 hashes, `engineering_approved: false`) is always kept.
//!
//! Every export is a draft. Nothing here marks a file as approved or verified.
use crate::error::{AppError, AppResult};
use crate::intake::Worker;
use marinaframe_control::util;
use serde::{Deserialize, Serialize};
use std::ffi::OsStr;
use std::io::Read;
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::time::{Duration, Instant};

/// Folder inside the task that holds the exports, one subfolder per revision.
pub const EXPORTS_FOLDER: &str = "exports";
/// The outputs a person can choose, in display order. `tanks` (capacity plan and sounding
/// tables) and `structure` (steel tables and OCX file) need the run's tank model or structure
/// folder (`run_tables`); without them they are listed as not built.
pub const OUTPUTS: [&str; 10] = [
    "step",
    "iges",
    "3dm",
    "stl",
    "offsets",
    "hydrostatics",
    "report",
    "tanks",
    "structure",
    "package",
];
/// Kind of the manifest file. It is not a choice: every export keeps it.
pub const MANIFEST: &str = "manifest";
/// The stamp the worker writes into every export.
pub const STAMP: &str = "Draft hull model from MarinaFrame. Not approved for construction.";
/// Longest time one export may take. The PDF report and the mesh hydrostatics of a
/// large STL take tens of seconds; five minutes leaves a wide margin.
pub const EXPORT_TIMEOUT: Duration = Duration::from_secs(300);
/// How often the wait loop checks whether the worker has finished.
const POLL_INTERVAL: Duration = Duration::from_millis(100);
/// Most digits of a revision number (`r` + digits).
const REVISION_DIGITS_MAX: usize = 6;

/// One file in the exports folder.
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
pub struct ExportedFile {
    /// One of [`OUTPUTS`] or [`MANIFEST`].
    pub kind: String,
    /// File name, for example `Vessel_r0003_DRAFT_offsets.csv`.
    pub file: String,
    /// Absolute path, for "Show in Finder".
    pub path: String,
    pub bytes: u64,
}

/// What an export wrote, or what an exports folder holds.
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct ExportResult {
    /// Absolute path of `<task>/exports/<rNNNN>`.
    pub folder: String,
    /// Normalised revision, for example `r0003`.
    pub revision: String,
    pub files: Vec<ExportedFile>,
    /// Chosen outputs the build does not have (for example `stl` without a mesh).
    pub not_built: Vec<String>,
    pub stamp: String,
    /// Always false: engineering sign-off happens outside MarinaFrame.
    pub engineering_approved: bool,
}

/// `r3` and `r0003` are the same revision; the folder name is `r0003`.
pub fn normalise_revision(revision: &str) -> AppResult<String> {
    let digits = revision.strip_prefix('r').unwrap_or("");
    let valid = !digits.is_empty()
        && digits.len() <= REVISION_DIGITS_MAX
        && digits.bytes().all(|b| b.is_ascii_digit());
    let number: u64 = match digits.parse() {
        Ok(number) if valid => number,
        _ => {
            return Err(AppError::new(
                "export_revision",
                "This revision cannot be exported.",
            ))
        }
    };
    Ok(format!("r{number:04}"))
}

/// Check the chosen outputs: at least one, each known. Returns them in display order.
pub fn check_outputs(outputs: &[String]) -> AppResult<Vec<&'static str>> {
    if let Some(unknown) = outputs.iter().find(|o| !OUTPUTS.contains(&o.as_str())) {
        return Err(AppError::new(
            "export_outputs",
            &format!("Unknown export \"{unknown}\"."),
        ));
    }
    let chosen: Vec<&'static str> = OUTPUTS
        .into_iter()
        .filter(|kind| outputs.iter().any(|o| o == kind))
        .collect();
    if chosen.is_empty() {
        return Err(AppError::new(
            "export_outputs",
            "Choose at least one export.",
        ));
    }
    Ok(chosen)
}

/// Kind of an export file from its name suffix, or `None` for other files.
pub fn kind_of_file(name: &str) -> Option<&'static str> {
    const SUFFIXES: [(&str, &str); 10] = [
        ("_model.step", "step"),
        ("_model.iges", "iges"),
        ("_model.3dm", "3dm"),
        ("_model.stl", "stl"),
        ("_offsets.csv", "offsets"),
        ("_hydrostatics.json", "hydrostatics"),
        ("_hydrostatics.csv", "hydrostatics"),
        ("_report.pdf", "report"),
        ("_package.zip", "package"),
        ("_manifest.json", MANIFEST),
    ];
    if name.contains(['/', '\\']) || name.starts_with('.') {
        return None;
    }
    // A sounding table first: a tank id can end like another kind ("_sounding_offsets.csv").
    let tank_table = (name.contains("_DRAFT_sounding_") && name.ends_with(".csv"))
        || name.ends_with("_capacity_plan.csv");
    if tank_table {
        return Some("tanks");
    }
    if crate::run_tables::structure_role(name).is_some() {
        return Some("structure");
    }
    SUFFIXES
        .iter()
        .find(|(suffix, _)| name.ends_with(suffix))
        .map(|(_, kind)| *kind)
}

/// Manifest role names that the worker lists in `not_built`, as output kinds.
fn not_built_kind(role: &str) -> Option<&'static str> {
    match role {
        "step_model" => Some("step"),
        "iges_model" => Some("iges"),
        "rhino_model" => Some("3dm"),
        "stl_mesh" => Some("stl"),
        _ => None,
    }
}

/// Chosen `tanks` or `structure` outputs the run has no input for.
fn missing_run_tables(task: &Path, chosen: &[&str]) -> Vec<String> {
    let mut missing = vec![];
    if chosen.contains(&"tanks") && crate::run_tables::tank_model_path(task).is_none() {
        missing.push("tanks".to_string());
    }
    if chosen.contains(&"structure") && crate::run_tables::structure_files(task).is_empty() {
        missing.push("structure".to_string());
    }
    missing
}

fn exports_folder(task: &Path, revision: &str) -> PathBuf {
    task.join(EXPORTS_FOLDER).join(revision)
}

fn write_error() -> AppError {
    AppError::new(
        "export_write",
        "The export files could not be written into the run folder.",
    )
}

/// Run the exports worker for `revision` and keep the chosen `outputs`.
pub fn export_run(
    task: &Path,
    worker: &Worker,
    revision: &str,
    outputs: &[String],
    timeout: Duration,
) -> AppResult<ExportResult> {
    let chosen = check_outputs(outputs)?;
    let revision = normalise_revision(revision)?;
    let exports = task.join(EXPORTS_FOLDER);
    let staging = exports.join(format!(".staging-{}-{}", revision, util::now_ms()));
    std::fs::create_dir_all(&staging).map_err(|_| write_error())?;
    let outcome = run_worker(worker, task, &revision, &staging, timeout).and_then(|manifest| {
        keep_chosen(
            &staging,
            &exports_folder(task, &revision),
            &chosen,
            &manifest,
        )
    });
    // The staging folder is ours alone; remove it whether the export worked or not.
    let _ = std::fs::remove_dir_all(&staging);
    let mut not_built = outcome?;
    not_built.extend(missing_run_tables(task, &chosen));
    let mut result = list_exports(task, &revision)?;
    result.not_built = not_built;
    Ok(result)
}

/// Move the chosen files (and the manifest) from `staging` into `folder`.
/// Returns the chosen outputs the build does not have.
fn keep_chosen(
    staging: &Path,
    folder: &Path,
    chosen: &[&str],
    manifest: &serde_json::Value,
) -> AppResult<Vec<String>> {
    std::fs::create_dir_all(folder).map_err(|_| write_error())?;
    let entries = std::fs::read_dir(staging).map_err(|_| write_error())?;
    for entry in entries.filter_map(Result::ok) {
        let name = entry.file_name();
        let Some(kind) = name.to_str().and_then(kind_of_file) else {
            continue;
        };
        let regular = entry.file_type().is_ok_and(|t| t.is_file());
        if regular && (kind == MANIFEST || chosen.contains(&kind)) {
            std::fs::rename(entry.path(), folder.join(&name)).map_err(|_| write_error())?;
        }
    }
    let not_built = manifest["not_built"]
        .as_array()
        .into_iter()
        .flatten()
        .filter_map(|role| not_built_kind(role.as_str()?))
        .filter(|kind| chosen.contains(kind))
        .map(String::from)
        .collect();
    Ok(not_built)
}

/// Files already exported for `revision` (an empty list when there are none).
pub fn list_exports(task: &Path, revision: &str) -> AppResult<ExportResult> {
    let revision = normalise_revision(revision)?;
    let folder = exports_folder(task, &revision);
    let mut files: Vec<ExportedFile> = std::fs::read_dir(&folder)
        .into_iter()
        .flatten()
        .filter_map(Result::ok)
        .filter_map(|entry| {
            let file = entry.file_name().into_string().ok()?;
            let kind = kind_of_file(&file)?;
            let meta = std::fs::symlink_metadata(entry.path()).ok()?;
            meta.is_file().then(|| ExportedFile {
                kind: kind.into(),
                path: entry.path().to_string_lossy().into_owned(),
                bytes: meta.len(),
                file,
            })
        })
        .collect();
    let order = |kind: &str| {
        OUTPUTS
            .iter()
            .position(|k| *k == kind)
            .unwrap_or(OUTPUTS.len())
    };
    files.sort_by(|a, b| {
        order(&a.kind)
            .cmp(&order(&b.kind))
            .then(a.file.cmp(&b.file))
    });
    Ok(ExportResult {
        folder: folder.to_string_lossy().into_owned(),
        revision,
        files,
        not_built: vec![],
        stamp: STAMP.into(),
        engineering_approved: false,
    })
}

/// Run `python -m vessel_reconstruction.exports` and return its manifest.
/// Paths go to the worker as separate arguments; no shell is involved.
fn run_worker(
    worker: &Worker,
    task: &Path,
    revision: &str,
    out: &Path,
    timeout: Duration,
) -> AppResult<serde_json::Value> {
    if worker.python.is_empty() || !Path::new(worker.python).is_file() {
        return Err(AppError::from_code("worker_python_missing"));
    }
    let mut command = Command::new(worker.python);
    command
        .args(["-m", "vessel_reconstruction.exports"])
        .args([OsStr::new("--task"), task.as_os_str()])
        .args(["--revision", revision])
        .args([OsStr::new("--out"), out.as_os_str()])
        .args(run_table_arguments(task))
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped());
    if let Some(source) = worker.source {
        command.env("PYTHONPATH", source);
    }
    let child = command
        .spawn()
        .map_err(|_| AppError::new("export_worker", "The export worker could not start."))?;
    let Some(finished) = wait_bounded(child, timeout) else {
        return Err(AppError::new(
            "export_timeout",
            &format!(
                "The export took longer than {} s and was stopped.",
                timeout.as_secs()
            ),
        ));
    };
    if !finished.success {
        let reason: Option<String> = serde_json::from_slice::<serde_json::Value>(&finished.stderr)
            .ok()
            .and_then(|value| value["error"].as_str().map(String::from));
        let message = match reason {
            Some(reason) => format!("This revision could not be exported: {reason}."),
            None => "The export worker stopped with an error.".into(),
        };
        return Err(AppError::new("export_worker", &message));
    }
    serde_json::from_slice(&finished.stdout).map_err(|_| {
        AppError::new(
            "export_worker",
            "The export worker gave no readable answer.",
        )
    })
}

/// Worker arguments for the run's tank model and structure folder, when the run has them.
fn run_table_arguments(task: &Path) -> Vec<std::ffi::OsString> {
    let mut arguments = vec![];
    if let Some(model) = crate::run_tables::tank_model_path(task) {
        arguments.extend(["--tanks".into(), model.into_os_string()]);
    }
    if !crate::run_tables::structure_files(task).is_empty() {
        let folder = task.join(crate::run_tables::STRUCTURE_FOLDER);
        arguments.extend(["--structure".into(), folder.into_os_string()]);
    }
    arguments
}

/// A worker process that finished in time: its exit status and output.
pub(crate) struct Finished {
    pub success: bool,
    pub stdout: Vec<u8>,
    pub stderr: Vec<u8>,
}

/// Wait for `child` at most `timeout`; kill it when the time is up (None). The pipes are
/// read on their own threads so that a full pipe cannot block the worker.
pub(crate) fn wait_bounded(mut child: Child, timeout: Duration) -> Option<Finished> {
    let read_pipe = |pipe: Option<Box<dyn Read + Send>>| {
        std::thread::spawn(move || {
            let mut bytes = vec![];
            if let Some(mut pipe) = pipe {
                let _ = pipe.read_to_end(&mut bytes);
            }
            bytes
        })
    };
    let stdout = read_pipe(
        child
            .stdout
            .take()
            .map(|p| Box::new(p) as Box<dyn Read + Send>),
    );
    let stderr = read_pipe(
        child
            .stderr
            .take()
            .map(|p| Box::new(p) as Box<dyn Read + Send>),
    );
    let deadline = Instant::now() + timeout;
    let status = loop {
        match child.try_wait() {
            Ok(Some(status)) => break status,
            Ok(None) if Instant::now() < deadline => std::thread::sleep(POLL_INTERVAL),
            _ => {
                let _ = child.kill();
                let _ = child.wait();
                return None;
            }
        }
    };
    Some(Finished {
        success: status.success(),
        stdout: stdout.join().unwrap_or_default(),
        stderr: stderr.join().unwrap_or_default(),
    })
}

/// Check that `path` is a file or folder inside `<task>/exports/`; return it.
pub fn check_reveal_path(task: &Path, path: &str) -> AppResult<PathBuf> {
    let refused = || AppError::new("export_reveal", "That file is not in this run's exports.");
    let exports = std::fs::canonicalize(task.join(EXPORTS_FOLDER)).map_err(|_| refused())?;
    let target = std::fs::canonicalize(path).map_err(|_| refused())?;
    if target.starts_with(&exports) {
        Ok(target)
    } else {
        Err(refused())
    }
}

/// Show `path` in the system file manager (Finder on macOS). Does not wait for it.
pub fn reveal(path: &Path) -> AppResult<()> {
    let mut command = if cfg!(target_os = "macos") {
        let mut command = Command::new("open");
        command.arg("-R").arg(path);
        command
    } else if cfg!(target_os = "windows") {
        let mut select = std::ffi::OsString::from("/select,");
        select.push(path);
        let mut command = Command::new("explorer");
        command.arg(select);
        command
    } else {
        let folder = if path.is_dir() {
            path
        } else {
            path.parent().unwrap_or(path)
        };
        let mut command = Command::new("xdg-open");
        command.arg(folder);
        command
    };
    let mut child = command
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .spawn()
        .map_err(|_| AppError::new("export_reveal", "The folder could not be opened."))?;
    // Reap the file manager helper when it exits, so it leaves no zombie process.
    std::thread::spawn(move || child.wait());
    Ok(())
}

#[cfg(all(test, unix))]
mod tests;
