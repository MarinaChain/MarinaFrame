//! Exports of a finished run (milestone M5).
//!
//! `export_run` runs the Python worker `python -m vessel_reconstruction.exports`
//! for one revision of a task. The worker always writes every export into a
//! staging folder; this module then moves the outputs the person chose into
//! `<task>/exports/<rNNNN>/` and deletes the staging folder. The manifest (file
//! list with SHA-256 hashes, `engineering_approved: false`) is always kept.
//!
//! Every export is a draft. Nothing here marks a file as approved or verified.
mod generations;

use crate::error::{AppError, AppResult};
use crate::intake::Worker;
use crate::worker_run::{Supervision, WorkerWords, UNCANCELLABLE};
use marinaframe_control::{supervised, util};
use serde::{Deserialize, Serialize};
use std::ffi::OsStr;
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};
use std::time::Duration;

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
/// An export with no progress report for this long is stopped. The worker reports
/// each stage (3D files, offsets, hydrostatics, tables, report, CAD models); there
/// is no limit on the total time.
pub const EXPORT_STALL_PERIOD: Duration = supervised::DEFAULT_STALL_PERIOD;
/// File the app writes into the export folder before the worker runs: a picture of its 3D view
/// for page 1 of the PDF report (the worker reads it when it is there). It is an input, not an output:
/// it is not listed, moved or packed.
pub const VIEWER_CAPTURE_FILE: &str = "viewer_capture.png";
/// The first bytes of every PNG file.
const PNG_SIGNATURE: [u8; 8] = [0x89, b'P', b'N', b'G', 0x0d, 0x0a, 0x1a, 0x0a];
/// Largest picture of the 3D view that is accepted (bytes). A 1600 x 1000 picture is well under 1 MB.
pub const VIEWER_CAPTURE_MAX_BYTES: usize = 12 * 1024 * 1024;
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
    /// Format outcomes and plain failure reasons from the package manifest.
    pub format_results: serde_json::Value,
    /// Task display models omitted from this package and their reasons.
    #[serde(default)]
    pub display_omissions: Vec<serde_json::Value>,
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
    stall_period: Duration,
) -> AppResult<ExportResult> {
    export_run_with_capture(task, worker, revision, outputs, stall_period, None)
}

/// True for bytes that look like a PNG file of an accepted size.
pub fn is_viewer_capture(bytes: &[u8]) -> bool {
    bytes.len() <= VIEWER_CAPTURE_MAX_BYTES && bytes.starts_with(&PNG_SIGNATURE)
}

/// As [`export_run`], with the picture of the app's 3D view (PNG bytes). The picture goes into the
/// staging folder before the worker runs, which puts it on page 1 of the report. Bytes that are not
/// a PNG, or are too large, are left out: the report is complete without the picture.
pub fn export_run_with_capture(
    task: &Path,
    worker: &Worker,
    revision: &str,
    outputs: &[String],
    stall_period: Duration,
    viewer_capture: Option<&[u8]>,
) -> AppResult<ExportResult> {
    let chosen = check_outputs(outputs)?;
    let revision = normalise_revision(revision)?;
    let exports = task.join(EXPORTS_FOLDER);
    let staging = exports.join(format!(".staging-{}-{}", revision, util::now_ms()));
    std::fs::create_dir_all(&staging).map_err(|_| write_error())?;
    if let Some(bytes) = viewer_capture.filter(|bytes| is_viewer_capture(bytes)) {
        std::fs::write(staging.join(VIEWER_CAPTURE_FILE), bytes).map_err(|_| write_error())?;
    }
    let outcome =
        run_worker(worker, task, &revision, &staging, stall_period).and_then(|manifest| {
            let published_staging = generations::resolve(&staging)?;
            let not_built = keep_chosen(
                &published_staging,
                &exports_folder(task, &revision),
                &chosen,
                &manifest,
            )?;
            Ok((
                not_built,
                manifest
                    .get("format_results")
                    .cloned()
                    .unwrap_or_else(|| serde_json::json!({})),
                manifest
                    .get("display_omissions")
                    .and_then(serde_json::Value::as_array)
                    .cloned()
                    .unwrap_or_default(),
            ))
        });
    // The staging folder is ours alone; remove it whether the export worked or not.
    let _ = std::fs::remove_dir_all(&staging);
    let (mut not_built, format_results, display_omissions) = outcome?;
    not_built.extend(missing_run_tables(task, &chosen));
    let mut result = list_exports(task, &revision)?;
    result.not_built = not_built;
    result.format_results = format_results;
    result.display_omissions = display_omissions;
    Ok(result)
}

/// Move the chosen files (and the manifest) from `staging` into `folder`.
/// Returns the chosen outputs the build does not have.
#[cfg(not(windows))]
fn keep_chosen(
    staging: &Path,
    folder: &Path,
    chosen: &[&str],
    manifest: &serde_json::Value,
) -> AppResult<Vec<String>> {
    std::fs::create_dir_all(folder).map_err(|_| write_error())?;
    // A failed retry must not leave an earlier file looking like the new result.
    for entry in std::fs::read_dir(folder)
        .map_err(|_| write_error())?
        .flatten()
    {
        let name = entry.file_name();
        let Some(kind) = name.to_str().and_then(kind_of_file) else {
            continue;
        };
        let failed_ocx = kind == "structure"
            && name.to_str().is_some_and(|name| name.ends_with(".3docx"))
            && manifest["format_results"]["ocx"]["status"] == "failed";
        if chosen.contains(&kind)
            && (manifest["format_results"][kind]["status"] == "failed" || failed_ocx)
            && entry.file_type().is_ok_and(|file_type| file_type.is_file())
        {
            std::fs::remove_file(entry.path()).map_err(|_| write_error())?;
        }
    }
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

#[cfg(windows)]
fn keep_chosen(
    staging: &Path,
    folder: &Path,
    chosen: &[&str],
    manifest: &serde_json::Value,
) -> AppResult<Vec<String>> {
    let parent = folder.parent().ok_or_else(write_error)?;
    std::fs::create_dir_all(parent).map_err(|_| write_error())?;
    let stage = parent.join(format!(
        ".selection-{}-{}",
        std::process::id(),
        util::now_ms()
    ));
    std::fs::create_dir(&stage).map_err(|_| write_error())?;
    let result = (|| {
        let previous = generations::resolve(folder)?;
        for source in [&previous, staging] {
            if !source.exists() {
                continue;
            }
            for entry in std::fs::read_dir(source).map_err(|_| write_error())? {
                let entry = entry.map_err(|_| write_error())?;
                let name = entry.file_name();
                let Some(kind) = name.to_str().and_then(kind_of_file) else {
                    continue;
                };
                let metadata =
                    std::fs::symlink_metadata(entry.path()).map_err(|_| write_error())?;
                use std::os::windows::fs::MetadataExt;
                if !metadata.is_file()
                    || metadata.file_type().is_symlink()
                    || metadata.file_attributes() & 0x400 != 0
                {
                    return Err(write_error());
                }
                let fresh = source == staging;
                let failed_ocx = kind == "structure"
                    && name.to_str().is_some_and(|value| value.ends_with(".3docx"))
                    && manifest["format_results"]["ocx"]["status"] == "failed";
                if fresh && kind != MANIFEST && !chosen.contains(&kind) {
                    continue;
                }
                if !fresh
                    && chosen.contains(&kind)
                    && (manifest["format_results"][kind]["status"] == "failed" || failed_ocx)
                {
                    continue;
                }
                std::fs::copy(entry.path(), stage.join(name)).map_err(|_| write_error())?;
            }
        }
        generations::publish(folder, &stage)?;
        Ok(manifest["not_built"]
            .as_array()
            .into_iter()
            .flatten()
            .filter_map(|role| not_built_kind(role.as_str()?))
            .filter(|kind| chosen.contains(kind))
            .map(String::from)
            .collect())
    })();
    if stage.exists() {
        let _ = std::fs::remove_dir_all(stage);
    }
    result
}

/// Files already exported for `revision` (an empty list when there are none).
pub fn list_exports(task: &Path, revision: &str) -> AppResult<ExportResult> {
    let revision = normalise_revision(revision)?;
    let folder = generations::resolve(&exports_folder(task, &revision))?;
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
    let manifest = files
        .iter()
        .find(|file| file.kind == MANIFEST)
        .and_then(|file| std::fs::read(&file.path).ok())
        .and_then(|bytes| serde_json::from_slice::<serde_json::Value>(&bytes).ok())
        .unwrap_or_else(|| serde_json::json!({}));
    let format_results = manifest
        .get("format_results")
        .cloned()
        .unwrap_or_else(|| serde_json::json!({}));
    let display_omissions = manifest
        .get("display_omissions")
        .and_then(serde_json::Value::as_array)
        .cloned()
        .unwrap_or_default();
    Ok(ExportResult {
        folder: folder.to_string_lossy().into_owned(),
        revision,
        files,
        not_built: vec![],
        format_results,
        display_omissions,
        stamp: STAMP.into(),
        engineering_approved: false,
    })
}

/// How export errors are named.
const EXPORT_WORDS: WorkerWords = WorkerWords {
    code: "export",
    name: "The export",
    after_stop: "",
};

/// Run `python -m vessel_reconstruction.exports` and return its manifest.
/// Paths go to the worker as separate arguments; no shell is involved.
fn run_worker(
    worker: &Worker,
    task: &Path,
    revision: &str,
    out: &Path,
    stall_period: Duration,
) -> AppResult<serde_json::Value> {
    let mut command = worker.module_command("vessel_reconstruction.exports")?;
    command
        .args([OsStr::new("--task"), task.as_os_str()])
        .args(["--revision", revision])
        .args([OsStr::new("--out"), out.as_os_str()])
        .args(run_table_arguments(task));
    let supervision = Supervision {
        stall_period,
        ..UNCANCELLABLE
    };
    let finished = worker.run_supervised(&mut command, &supervision, &EXPORT_WORDS)?;
    if !finished.status.success() {
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
