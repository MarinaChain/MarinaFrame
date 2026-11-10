//! The Sources tab: every file that was given to a run, read from the run's records, and a
//! picture of one page of it. Nothing here writes to the task folder.
//!
//! Records read:
//! - `domain/state.json` `sheet_review` (through `sheet_review::read`): one sheet per drawing
//!   page with its file in `domain/input/`; `history` keeps each replacement with the revision
//!   it left and the domain state before it (`previous_state`), which names the earlier file.
//! - `intake/intake.json` and `intake/sources/`: the files dropped for a run started from a
//!   drawing set, with the sheet type and scale the intake read for each page.
//! - `domain/input/submitted_spec.json` and the captured intake record: the spec inputs.
//!
//! The UI names a source only by its `id`. `read_source_page` lists the sources again and uses
//! the recorded location, checked by `artifact::guard_inside_task` (no `..`, no symlink, a
//! regular file inside the task). PDF and TIFF pages are rendered by the Python worker
//! (`vessel_reconstruction.intake render-page`), the same code that renders intake pages.
use crate::error::{AppError, AppResult};
use crate::{artifact, files, intake, sheet_review};
use base64::{engine::general_purpose::STANDARD, Engine};
use marinaframe_control::util;
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::path::Path;

/// The domain revision of a run's first inputs (`agent_tools.py` starts at revision 0).
const FIRST_REVISION: &str = "r0000";
/// Longest side of a list thumbnail and of the large page view, in pixels
/// (within the worker's `MIN_PREVIEW_SIDE`..`MAX_PREVIEW_SIDE`).
const THUMB_SIDE: u32 = 320;
const FULL_SIDE: u32 = 4096;
/// A PNG up to this size is sent as it is; a larger one is reduced by the worker.
const RAW_THUMB_MAX_BYTES: u64 = 1024 * 1024;
const RAW_FULL_MAX_BYTES: u64 = 16 * 1024 * 1024;
/// Spec inputs are shown as text up to this size.
const TEXT_MAX_BYTES: usize = 1024 * 1024;
/// The domain state saved before a sheet replacement (same bound as `files::read_domain`).
const PREVIOUS_STATE_MAX_BYTES: usize = 32 * 1024 * 1024;
/// Spec `input_mode` whose main drawing is an offset table (`schema.py`).
const TABLE_INPUT_MODE: &str = "offset_table_vision";

#[derive(Clone, Copy, Debug, Serialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum SourceKind {
    /// A raster drawing: PNG, TIFF or JPEG.
    Drawing,
    Pdf,
    /// An offset table drawing, or a table file.
    Table,
    /// A run spec or an intake record.
    Spec,
}

#[derive(Clone, Copy, Debug, Serialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum SourceStatus {
    /// The run uses this file now.
    Current,
    /// A person replaced it (Replace sheet); an earlier version.
    Replaced,
    /// The run recorded that this file could not be read.
    Unreadable,
}

/// What the records say about one page of a source file.
#[derive(Clone, Debug, Serialize, PartialEq)]
pub struct SourcePageFacts {
    /// Page of a PDF or frame of a TIFF, from 0.
    pub index: u32,
    /// The sheet type the intake read, for example "Lines plan".
    pub sheet_type: Option<String>,
    /// The scale printed on the sheet, for example "1:50".
    pub scale: Option<String>,
    pub width_px: Option<u32>,
    pub height_px: Option<u32>,
    pub dpi: Option<f64>,
    /// A person replaced this page with another file.
    pub replaced: bool,
}

#[derive(Clone, Debug, Serialize, PartialEq)]
pub struct SourceFile {
    /// Opaque name of the source for `read_source_page`.
    pub id: String,
    pub name: String,
    pub kind: SourceKind,
    /// What the file is to the run, in plain words ("Main drawing").
    pub role: String,
    pub status: SourceStatus,
    /// 1 for the file first given; a replacement counts up.
    pub version: u32,
    pub pages: Vec<SourcePageFacts>,
    pub size_bytes: Option<u64>,
    pub sha256: Option<String>,
    pub added_ms: Option<u64>,
    /// The first and last domain revision that used the file; `used_to` is null while in use.
    pub used_from: Option<String>,
    pub used_to: Option<String>,
    /// The `id` of the file that replaced this one.
    pub replaced_by: Option<String>,
    pub note: Option<String>,
    /// The file is in the task folder and can be shown.
    pub previewable: bool,
    /// Task-relative path from the records. Never sent to the UI, never taken from it.
    #[serde(skip)]
    location: Option<String>,
}

#[derive(Clone, Debug, Serialize, PartialEq)]
pub struct SourceList {
    pub sources: Vec<SourceFile>,
    /// The run's current domain revision, for example "r0003".
    pub revision: Option<String>,
}

/// `thumb` for the list, `full` for the large view.
#[derive(Clone, Copy, Debug, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum PreviewSize {
    Thumb,
    Full,
}

/// One page as an image (`base64`), or a spec input as `text`.
#[derive(Clone, Debug, Serialize, PartialEq)]
pub struct SourcePreview {
    pub mime: String,
    pub base64: Option<String>,
    pub text: Option<String>,
    /// Pixel size of the image sent (0 for text).
    pub width: u32,
    pub height: u32,
}

// ---------------------------------------------------------------- records

/// The records of one task that name its sources.
struct Records<'a> {
    task: &'a Path,
    review: Value,
    intake: Option<Value>,
    captured_spec: Option<Value>,
    submitted_spec: Option<Value>,
    created_ms: Option<u64>,
}

impl<'a> Records<'a> {
    fn read(task: &'a Path) -> Self {
        let submitted_spec = artifact::guard_inside_task(task, "domain/input/submitted_spec.json")
            .ok()
            .and_then(|path| util::read_bounded(&path, TEXT_MAX_BYTES).ok())
            .and_then(|bytes| serde_json::from_slice(&bytes).ok());
        Self {
            task,
            review: sheet_review::read(task),
            intake: files::read_intake_record(task),
            captured_spec: files::read_captured_spec(task),
            submitted_spec,
            created_ms: files::read_state(task).and_then(|state| state["created_ms"].as_u64()),
        }
    }

    fn intake_pages(&self) -> &[Value] {
        self.intake
            .as_ref()
            .and_then(|record| record["pages"].as_array())
            .map_or(&[], Vec::as_slice)
    }

    /// The intake page a sheet came from: the spec page for `source`, else the page of that id.
    fn intake_page_of(&self, sheet_id: &str) -> Option<&Value> {
        let intake = self.intake.as_ref()?;
        let page_id = if sheet_id == "source" {
            intake["spec_page_id"].as_str()?
        } else {
            sheet_id
        };
        self.intake_pages()
            .iter()
            .find(|page| page["page_id"] == page_id)
    }

    fn is_table_run(&self) -> bool {
        self.captured_spec
            .as_ref()
            .is_some_and(|spec| spec["input_mode"] == TABLE_INPUT_MODE)
    }
}

fn text(value: &Value) -> Option<String> {
    value.as_str().filter(|s| !s.is_empty()).map(String::from)
}

/// Opaque id of a source: a short hash of where the records put it.
fn source_id(key: &str) -> String {
    util::hash(key.as_bytes())[..16].to_string()
}

fn kind_of(name: &str) -> SourceKind {
    let extension = name.rsplit('.').next().unwrap_or("").to_ascii_lowercase();
    match extension.as_str() {
        "pdf" => SourceKind::Pdf,
        "csv" | "tsv" | "xls" | "xlsx" => SourceKind::Table,
        "json" | "toml" | "yaml" | "yml" => SourceKind::Spec,
        _ => SourceKind::Drawing,
    }
}

fn role_of(sheet_id: &str) -> &'static str {
    match sheet_id {
        "source" => "Main drawing",
        "station_reference" => "Station reference",
        _ => "Sheet",
    }
}

fn last_segment(path: &str) -> &str {
    path.rsplit(['/', '\\']).next().unwrap_or(path)
}

/// The facts of one intake page: its index, size, dpi and the sheet type and scale read.
fn intake_page_facts(page: &Value) -> SourcePageFacts {
    let sheet = &page["sheet"];
    SourcePageFacts {
        index: page["page_index"].as_u64().unwrap_or(0) as u32,
        sheet_type: text(&sheet["type_label"]),
        scale: text(&sheet["scale"]["main_text"]),
        width_px: page["width_px"].as_u64().map(|n| n as u32),
        height_px: page["height_px"].as_u64().map(|n| n as u32),
        dpi: page["dpi"].as_f64(),
        replaced: false,
    }
}

// ---------------------------------------------------------------- sheet versions

/// One recorded version of a sheet: its file in `domain/input/` and the revisions that used it.
struct SheetVersion {
    file: Option<String>,
    sha256: Option<String>,
    added_ms: Option<u64>,
    used_from: Option<String>,
    used_to: Option<String>,
}

/// The file a sheet had before a replacement, from the domain state saved with it.
fn previous_file(task: &Path, entry: &Value, sheet_id: &str) -> Option<String> {
    let saved = entry["previous_state"].as_str()?;
    let path = artifact::guard_inside_task(task, &format!("domain/{saved}")).ok()?;
    let state: Value =
        serde_json::from_slice(&util::read_bounded(&path, PREVIOUS_STATE_MAX_BYTES).ok()?).ok()?;
    let from_review = state["sheet_review"]["sheets"]
        .as_array()
        .and_then(|sheets| sheets.iter().find(|sheet| sheet["id"] == sheet_id))
        .and_then(|sheet| text(&sheet["file"]));
    from_review.or_else(|| text(&state["sources"][sheet_id]["file"]))
}

/// Every version of a sheet, oldest first; the last is the one in use.
fn sheet_versions(records: &Records, sheet: &Value) -> Vec<SheetVersion> {
    let sheet_id = sheet["id"].as_str().unwrap_or_default();
    let entries: Vec<&Value> = records.review["history"]
        .as_array()
        .map(|history| {
            history
                .iter()
                .filter(|entry| entry["sheet_id"] == sheet_id)
                .collect()
        })
        .unwrap_or_default();
    // Version n starts with replacement n - 1 (or with the run) and ends with replacement n.
    let started = |n: usize| match n {
        0 => (records.created_ms, Some(FIRST_REVISION.to_string())),
        _ => (
            entries[n - 1]["time_ms"].as_u64(),
            text(&entries[n - 1]["revision_id"]),
        ),
    };
    let mut versions: Vec<SheetVersion> = entries
        .iter()
        .enumerate()
        .map(|(n, entry)| {
            let (added_ms, used_from) = started(n);
            SheetVersion {
                file: previous_file(records.task, entry, sheet_id),
                sha256: text(&entry["previous_sha256"]),
                added_ms,
                used_from,
                used_to: text(&entry["previous_revision_id"]),
            }
        })
        .collect();
    let (added_ms, used_from) = started(entries.len());
    versions.push(SheetVersion {
        file: text(&sheet["file"]),
        sha256: text(&sheet["sha256"]),
        added_ms,
        used_from,
        used_to: None,
    });
    versions
}

// ---------------------------------------------------------------- the list

/// The files dropped at intake (`intake/sources/`), one per file with all its recorded pages.
fn dropped_files(records: &Records) -> Vec<SourceFile> {
    let spec_page = records
        .intake
        .as_ref()
        .and_then(|record| text(&record["spec_page_id"]));
    let mut dropped: Vec<SourceFile> = vec![];
    for page in records.intake_pages() {
        let Some(relative) = text(&page["source_file"]) else {
            continue;
        };
        let location = format!("intake/{relative}");
        let facts = intake_page_facts(page);
        if let Some(file) = dropped
            .iter_mut()
            .find(|file| file.location.as_deref() == Some(location.as_str()))
        {
            file.pages.push(facts);
            continue;
        }
        let name = text(&page["file_name"]).unwrap_or_else(|| last_segment(&relative).into());
        let holds_spec_page =
            spec_page.is_some() && page["page_id"].as_str() == spec_page.as_deref();
        let kind = if holds_spec_page && records.is_table_run() {
            SourceKind::Table
        } else {
            kind_of(&name)
        };
        dropped.push(SourceFile {
            id: source_id(&location),
            kind,
            name,
            role: if holds_spec_page {
                "Main drawing"
            } else {
                "Sheet"
            }
            .into(),
            status: SourceStatus::Current,
            version: 1,
            pages: vec![facts],
            size_bytes: None,
            sha256: None,
            added_ms: records.created_ms,
            used_from: Some(FIRST_REVISION.into()),
            used_to: None,
            replaced_by: None,
            note: None,
            previewable: false,
            location: Some(location),
        });
    }
    dropped
}

/// A sheet version that is a file in `domain/input/` (a spec-run drawing or a replacement).
fn captured_file(
    records: &Records,
    sheet: &Value,
    version: &SheetVersion,
    number: u32,
) -> SourceFile {
    let sheet_id = sheet["id"].as_str().unwrap_or_default();
    let label = text(&sheet["label"]).unwrap_or_else(|| sheet_id.replace('_', " "));
    let location = version
        .file
        .as_ref()
        .map(|file| format!("domain/input/{file}"));
    let (name, role) = if number == 1 {
        // The name the spec gave the file; the copy in the task is renamed (`source.png`).
        let given = records
            .submitted_spec
            .as_ref()
            .and_then(|spec| text(&spec[sheet_id]["file"]))
            .map(|file| last_segment(&file).to_string());
        (
            given.unwrap_or(label.clone()),
            role_of(sheet_id).to_string(),
        )
    } else {
        (
            format!("{label}, version {number}"),
            format!("Replacement for {label}"),
        )
    };
    // A replacement is always page 0; a spec names the PDF page it reads.
    let page_index = match number {
        1 => records
            .captured_spec
            .as_ref()
            .and_then(|spec| spec[sheet_id]["page_index"].as_u64())
            .or_else(|| sheet["page_index"].as_u64())
            .unwrap_or(0),
        _ => 0,
    };
    let mut kind = kind_of(version.file.as_deref().unwrap_or(&name));
    if sheet_id == "source" && records.is_table_run() {
        kind = SourceKind::Table;
    }
    SourceFile {
        id: source_id(
            location
                .as_deref()
                .unwrap_or(&format!("missing:{sheet_id}")),
        ),
        name,
        kind,
        role,
        status: SourceStatus::Current,
        version: number,
        pages: vec![SourcePageFacts {
            index: page_index as u32,
            sheet_type: None,
            scale: None,
            width_px: None,
            height_px: None,
            dpi: None,
            replaced: false,
        }],
        size_bytes: None,
        sha256: version.sha256.clone(),
        added_ms: version.added_ms,
        used_from: version.used_from.clone(),
        used_to: version.used_to.clone(),
        replaced_by: None,
        note: None,
        previewable: false,
        location,
    }
}

/// Drawings: the dropped files and every sheet version, earlier versions marked replaced.
fn drawing_sources(records: &Records) -> Vec<SourceFile> {
    let mut sources = dropped_files(records);
    let mut replacements = vec![];
    let sheets = records.review["sheets"]
        .as_array()
        .cloned()
        .unwrap_or_default();
    for sheet in &sheets {
        let sheet_id = sheet["id"].as_str().unwrap_or_default();
        let versions = sheet_versions(records, sheet);
        let in_use = versions.len() - 1;
        let unreadable = sheet["status"] == "unreadable";
        let reason = text(&sheet["reason"]);
        // The dropped file this sheet's first version came from, if the run has an intake.
        let dropped_page = records.intake_page_of(sheet_id).and_then(|page| {
            let location = format!("intake/{}", text(&page["source_file"])?);
            let index = page["page_index"].as_u64().unwrap_or(0) as u32;
            let file = sources
                .iter()
                .position(|file| file.location.as_deref() == Some(location.as_str()))?;
            Some((file, index))
        });
        let mut chain: Vec<SourceFile> = vec![];
        for (n, version) in versions.iter().enumerate() {
            if n == 0 && dropped_page.is_some() {
                continue; // The dropped file stands for the first version.
            }
            let mut file = captured_file(records, sheet, version, n as u32 + 1);
            if n < in_use {
                file.status = SourceStatus::Replaced;
            } else if unreadable {
                file.status = SourceStatus::Unreadable;
                file.note = reason.clone();
            }
            chain.push(file);
        }
        // Link each version to the one that replaced it.
        for n in 1..chain.len() {
            chain[n - 1].replaced_by = Some(chain[n].id.clone());
        }
        if let Some((index, page_index)) = dropped_page {
            let first_later = chain.first().map(|file| file.id.clone());
            let dropped = &mut sources[index];
            if let Some(page) = dropped.pages.iter_mut().find(|p| p.index == page_index) {
                page.replaced = first_later.is_some();
            }
            if first_later.is_some() && dropped.pages.iter().all(|page| page.replaced) {
                dropped.status = SourceStatus::Replaced;
                dropped.used_to = versions[0].used_to.clone();
                dropped.replaced_by = first_later;
            } else if first_later.is_none() && unreadable {
                dropped.note = reason.clone();
                if dropped.pages.len() == 1 {
                    dropped.status = SourceStatus::Unreadable;
                }
            }
        }
        replacements.extend(chain);
    }
    sources.extend(replacements);
    sources
}

/// The run spec as given and the drawing-set record.
fn spec_inputs(records: &Records) -> Vec<SourceFile> {
    let from_intake = records.intake.is_some();
    let record = ["domain/input/intake.json", "intake/intake.json"]
        .into_iter()
        .find(|location| records.task.join(location).is_file());
    let mut inputs = vec![(
        "domain/input/submitted_spec.json",
        "spec.json",
        if from_intake {
            "Run spec written from the drawing set"
        } else {
            "Run spec as given"
        },
    )];
    if let Some(location) = record {
        inputs.push((location, "intake.json", "Drawing set record"));
    }
    inputs
        .into_iter()
        .filter(|(location, _, _)| records.task.join(location).is_file())
        .map(|(location, name, role)| SourceFile {
            id: source_id(location),
            name: name.into(),
            kind: SourceKind::Spec,
            role: role.into(),
            status: SourceStatus::Current,
            version: 1,
            pages: vec![],
            size_bytes: None,
            sha256: None,
            added_ms: records.created_ms,
            used_from: Some(FIRST_REVISION.into()),
            used_to: None,
            replaced_by: None,
            note: None,
            previewable: false,
            location: Some(location.into()),
        })
        .collect()
}

/// Size, hash and whether the file can be shown. A location outside the task, through a
/// symlink or not a regular file is never read.
fn add_file_facts(task: &Path, source: &mut SourceFile) {
    let Some(location) = source.location.as_deref() else {
        source
            .note
            .get_or_insert_with(|| "This file is not in the run folder.".into());
        return;
    };
    match artifact::guard_inside_task(task, location) {
        Ok(path) => {
            source.size_bytes = std::fs::metadata(&path).ok().map(|meta| meta.len());
            if source.sha256.is_none() {
                source.sha256 = util::file_hash(&path).ok();
            }
            if source.kind != SourceKind::Spec && source.pages.len() == 1 {
                let page = &mut source.pages[0];
                if page.width_px.is_none() {
                    if let Some((width, height)) = files::png_size(&path) {
                        page.width_px = Some(width);
                        page.height_px = Some(height);
                    }
                }
            }
            source.previewable = true;
        }
        Err(_) => {
            source.note = Some("This file is not in the run folder.".into());
        }
    }
}

/// Every source file of a run, from its records: drawings first, then spec inputs.
pub fn list_sources(task: &Path) -> AppResult<SourceList> {
    if std::fs::symlink_metadata(task)
        .map_or(true, |meta| !meta.is_dir() || meta.file_type().is_symlink())
    {
        return Err(AppError::from_code("invalid_task_root"));
    }
    let records = Records::read(task);
    let mut sources = drawing_sources(&records);
    sources.extend(spec_inputs(&records));
    for source in &mut sources {
        add_file_facts(task, source);
    }
    let revision = files::read_domain(task)
        .and_then(|domain| domain["revision"].as_u64())
        .map(|revision| format!("r{revision:04}"));
    Ok(SourceList { sources, revision })
}

// ---------------------------------------------------------------- one page

fn not_found() -> AppError {
    AppError::new("source_not_found", "This source file is not in the run.")
}

/// One page of a source as PNG, or a spec input as text. `source_id` comes from `list_sources`.
pub fn read_source_page(
    task: &Path,
    worker: &intake::Worker,
    source_id: &str,
    page: u32,
    size: PreviewSize,
) -> AppResult<SourcePreview> {
    let source = list_sources(task)?
        .sources
        .into_iter()
        .find(|source| source.id == source_id)
        .ok_or_else(not_found)?;
    let location = source.location.as_deref().ok_or_else(not_found)?;
    let path = artifact::guard_inside_task(task, location)?;
    if source.kind == SourceKind::Spec {
        let bytes = util::read_bounded(&path, TEXT_MAX_BYTES)
            .map_err(|_| AppError::new("source_too_large", "This file is too large to show."))?;
        let text = String::from_utf8(bytes)
            .map_err(|_| AppError::new("source_not_text", "This file is not plain text."))?;
        return Ok(SourcePreview {
            mime: "application/json".into(),
            base64: None,
            text: Some(text),
            width: 0,
            height: 0,
        });
    }
    if !source.pages.iter().any(|facts| facts.index == page) {
        return Err(AppError::new(
            "source_page_missing",
            "The run has no record of this page.",
        ));
    }
    let raw_limit = match size {
        PreviewSize::Thumb => RAW_THUMB_MAX_BYTES,
        PreviewSize::Full => RAW_FULL_MAX_BYTES,
    };
    let small_png = std::fs::metadata(&path).is_ok_and(|meta| meta.len() <= raw_limit);
    if let (true, Some((width, height))) = (small_png, files::png_size(&path)) {
        let bytes = util::read_bounded(&path, raw_limit as usize).map_err(AppError::from_code)?;
        return Ok(SourcePreview {
            mime: "image/png".into(),
            base64: Some(STANDARD.encode(bytes)),
            text: None,
            width,
            height,
        });
    }
    render_with_worker(worker, &path, page, size)
}

/// A PDF page, a TIFF frame or a large raster reduced by the worker's page renderer.
fn render_with_worker(
    worker: &intake::Worker,
    path: &Path,
    page: u32,
    size: PreviewSize,
) -> AppResult<SourcePreview> {
    let side = match size {
        PreviewSize::Thumb => THUMB_SIDE,
        PreviewSize::Full => FULL_SIDE,
    };
    let page_text = page.to_string();
    let side_text = side.to_string();
    let value = worker.call(&[
        "render-page".as_ref(),
        "--file".as_ref(),
        path.as_os_str(),
        "--page".as_ref(),
        page_text.as_ref(),
        "--max-side".as_ref(),
        side_text.as_ref(),
    ])?;
    let unreadable = || AppError::new("source_render", "This page could not be shown.");
    let base64 = text(&value["png_base64"]).ok_or_else(unreadable)?;
    Ok(SourcePreview {
        mime: "image/png".into(),
        base64: Some(base64),
        text: None,
        width: value["width_px"].as_u64().ok_or_else(unreadable)? as u32,
        height: value["height_px"].as_u64().ok_or_else(unreadable)? as u32,
    })
}

#[cfg(test)]
mod tests;
