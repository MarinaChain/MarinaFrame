//! Lock-free reads of a task folder. Nothing here takes the controller lock.
//!
//! The controller replaces `state.json`, `domain/state.json` and each event file
//! atomically (write to a temporary file, then rename), so a reader sees either
//! the old or the new file, never half a file. The number of event files is the
//! change signal.
use crate::error::{AppError, AppResult};
use marinaframe_control::util;
use serde_json::Value;
use std::fs;
use std::path::{Component, Path, PathBuf};

const STATE_MAX: usize = 4 * 1024 * 1024;
const DOMAIN_MAX: usize = 32 * 1024 * 1024;
const EVENT_MAX: usize = 4 * 1024 * 1024;

/// Accept only a real folder that sits directly inside the runs folder.
pub fn resolve_task(runs_folder: &Path, task: &str) -> AppResult<PathBuf> {
    let path = Path::new(task);
    let not_found = || AppError::from_code("task_not_found");
    if !path.is_absolute() || path.components().any(|c| matches!(c, Component::ParentDir)) {
        return Err(not_found());
    }
    let parent = path.parent().ok_or_else(not_found)?;
    let runs = fs::canonicalize(runs_folder).map_err(|_| not_found())?;
    let parent = fs::canonicalize(parent).map_err(|_| not_found())?;
    let meta = fs::symlink_metadata(path).map_err(|_| not_found())?;
    if parent != runs || meta.file_type().is_symlink() || !meta.is_dir() {
        return Err(not_found());
    }
    Ok(path.to_path_buf())
}

fn read_value(path: &Path, max: usize) -> Option<Value> {
    serde_json::from_slice(&util::read_bounded(path, max).ok()?).ok()
}

/// The `state` object of `state.json`.
pub fn read_state(task: &Path) -> Option<Value> {
    let mut wrapper = read_value(&task.join("state.json"), STATE_MAX)?;
    Some(wrapper.get_mut("state")?.take())
}

/// The head hash recorded next to the state.
pub fn read_head(task: &Path) -> Option<String> {
    read_value(&task.join("state.json"), STATE_MAX)?["head_sha256"]
        .as_str()
        .map(String::from)
}

/// `domain/state.json`, the worker's catalog of sections, candidates and builds.
pub fn read_domain(task: &Path) -> Option<Value> {
    read_value(&task.join("domain/state.json"), DOMAIN_MAX)
}

/// The intake record of a run started from a dropped drawing set
/// (`intake/intake.json`, copied in by `intake::copy_inputs_to_task`).
pub fn read_intake_record(task: &Path) -> Option<Value> {
    read_value(&task.join("intake/intake.json"), 4 * 1024 * 1024)
}

/// The spec the run captured at start (`domain/input/spec.json`).
pub fn read_captured_spec(task: &Path) -> Option<Value> {
    read_value(&task.join("domain/input/spec.json"), 8 * 1024 * 1024)
}

/// Sorted event files as `(sequence, path)`. Names are `00000001.json`.
pub fn event_files(task: &Path) -> Vec<(u64, PathBuf)> {
    let Ok(entries) = fs::read_dir(task.join("events")) else {
        return vec![];
    };
    let mut files: Vec<(u64, PathBuf)> = entries
        .filter_map(Result::ok)
        .filter_map(|entry| {
            let name = entry.file_name().into_string().ok()?;
            let sequence = name.strip_suffix(".json")?.parse::<u64>().ok()?;
            Some((sequence, entry.path()))
        })
        .collect();
    files.sort();
    files
}

/// Number of committed events. The newest sequence number is the change signal.
pub fn event_count(task: &Path) -> u64 {
    event_files(task).last().map(|(n, _)| *n).unwrap_or(0)
}

pub fn read_event(path: &Path) -> Option<Value> {
    read_value(path, EVENT_MAX)
}

/// Modification time of a file in milliseconds since the epoch.
pub fn modified_ms(path: &Path) -> u64 {
    fs::metadata(path)
        .and_then(|m| m.modified())
        .ok()
        .and_then(|t| t.duration_since(std::time::UNIX_EPOCH).ok())
        .map(|d| d.as_millis() as u64)
        .unwrap_or(0)
}

/// Pixel size from a PNG header.
pub fn png_size(path: &Path) -> Option<(u32, u32)> {
    use std::io::Read;
    let mut header = [0u8; 24];
    fs::File::open(path).ok()?.read_exact(&mut header).ok()?;
    if &header[..8] != b"\x89PNG\r\n\x1a\n" || &header[12..16] != b"IHDR" {
        return None;
    }
    let width = u32::from_be_bytes(header[16..20].try_into().ok()?);
    let height = u32::from_be_bytes(header[20..24].try_into().ok()?);
    Some((width, height))
}
