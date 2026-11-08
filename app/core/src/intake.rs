//! Intake of a dropped drawing set (no spec file for the person).
//!
//! `prepare_intake` asks the Python worker (`vessel_reconstruction.intake prepare`)
//! to render every page, read its size and dpi and propose view regions. The UI
//! shows the preview and lets the person relabel regions, skip pages and type
//! particulars. `start_intake_run` sends the edited preview back to the worker
//! (`intake write-spec`), which copies the sources and writes a sheet-only
//! `spec.json` and `intake.json`; then the run starts like any other run
//! (`actions::start_run`) and the inputs are copied into the task's `intake/`
//! folder so that the run stays reproducible.
//!
//! The intake sets live in `<runs folder>/intake-sets/<intake_id>/`. That folder
//! has no task state, so the run list skips it.
use crate::error::{AppError, AppResult};
use marinaframe_control::util;
use serde::{Deserialize, Serialize};
use std::path::{Path, PathBuf};
use std::process::Command;

/// Folder under the runs folder that holds intake sets.
pub const INTAKE_SETS: &str = "intake-sets";
/// File types the intake reads.
pub const ACCEPTED_EXTENSIONS: [&str; 6] = ["pdf", "png", "tif", "tiff", "jpg", "jpeg"];
/// Most files in one dropped set.
pub const MAX_FILES: usize = 32;
/// The view labels a region can have (`skip` is not a label: pages are skipped).
pub const VIEW_LABELS: [&str; 5] = [
    "body_plan",
    "half_breadth",
    "profile",
    "title_block",
    "other",
];

/// One proposed (or edited) view region of a page, in page pixels.
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct IntakeRegion {
    pub region_id: String,
    /// One of [`VIEW_LABELS`].
    pub label: String,
    /// 0..1; how sure the code is of the label. A person's edit keeps the number.
    pub confidence: f64,
    /// `[left, top, right, bottom]` in page pixels.
    pub region_px: [i64; 4],
    #[serde(default)]
    pub evidence: String,
}

/// A plain-language warning, such as `low_dpi` ("Scan 150 dpi: ...").
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct IntakeWarning {
    pub code: String,
    pub message: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub file: Option<String>,
}

/// One page of the set: a PDF page or one raster frame.
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct IntakePage {
    pub page_id: String,
    /// Absolute path of the dropped file.
    pub file: String,
    pub file_name: String,
    /// `pdf` or `raster`.
    pub kind: String,
    /// Page of a PDF or frame of a TIFF, from 0.
    pub page_index: u32,
    /// Render dpi of a PDF page, or the dpi the raster file states; null when unknown.
    pub dpi: Option<f64>,
    /// `pdf_render`, `file_metadata` or `unknown`.
    pub dpi_source: String,
    pub width_px: u32,
    pub height_px: u32,
    /// A small PNG of the page, base64; `thumbnail_scale` maps page pixels to it.
    pub thumbnail_png_base64: String,
    pub thumbnail_scale: f64,
    pub regions: Vec<IntakeRegion>,
    pub warnings: Vec<IntakeWarning>,
    /// The person removed this page (for example a cover page).
    #[serde(default)]
    pub skip: bool,
}

/// What the person knows about the vessel. Every field is optional.
#[derive(Clone, Debug, Default, Serialize, Deserialize, PartialEq)]
pub struct Particulars {
    #[serde(default)]
    pub vessel_name: String,
    #[serde(default)]
    pub loa_m: Option<f64>,
    #[serde(default)]
    pub lpp_m: Option<f64>,
    #[serde(default)]
    pub beam_m: Option<f64>,
    #[serde(default)]
    pub depth_m: Option<f64>,
    #[serde(default)]
    pub draft_m: Option<f64>,
    /// As written on the sheet, for example "1:50".
    #[serde(default)]
    pub scale: Option<String>,
}

/// Result of `prepare_intake`; the argument of `start_intake_run` after edits.
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct IntakePreview {
    pub intake_id: String,
    pub pages: Vec<IntakePage>,
    /// Set-level warnings: an unreadable file, AI drafting off.
    pub warnings: Vec<IntakeWarning>,
    pub render_dpi: f64,
    #[serde(default)]
    pub particulars: Particulars,
    /// Whether the run will use the AI (it must, to read a set without a spec).
    #[serde(default)]
    pub ai_active: bool,
}

/// How to call the Python worker.
pub struct Worker<'a> {
    pub python: &'a str,
    /// `PYTHONPATH` for development checkouts.
    pub source: Option<&'a Path>,
}

impl Worker<'_> {
    /// Run `python -m vessel_reconstruction.intake <args>` and parse its JSON output.
    fn call(&self, args: &[&std::ffi::OsStr]) -> AppResult<serde_json::Value> {
        if self.python.is_empty() || !Path::new(self.python).is_file() {
            return Err(AppError::from_code("worker_python_missing"));
        }
        let mut command = Command::new(self.python);
        command
            .args(["-m", "vessel_reconstruction.intake"])
            .args(args);
        if let Some(source) = self.source {
            command.env("PYTHONPATH", source);
        }
        let output = command
            .output()
            .map_err(|_| AppError::new("intake_worker", "The drawing reader could not start."))?;
        let value: serde_json::Value = serde_json::from_slice(&output.stdout).map_err(|_| {
            AppError::new(
                "intake_worker",
                "The drawing reader gave no readable answer.",
            )
        })?;
        if !output.status.success() {
            let message = value["message"]
                .as_str()
                .unwrap_or("The drawings could not be read.");
            return Err(AppError::new("intake_worker", message));
        }
        Ok(value)
    }
}

/// Check the dropped files: regular, an accepted type, at most [`MAX_FILES`].
pub fn check_files(files: &[String]) -> AppResult<Vec<PathBuf>> {
    if files.is_empty() || files.len() > MAX_FILES {
        return Err(AppError::new(
            "intake_files",
            &format!("Drop 1 to {MAX_FILES} drawing files."),
        ));
    }
    files
        .iter()
        .map(|file| {
            let path = PathBuf::from(file);
            let accepted = path
                .extension()
                .and_then(|e| e.to_str())
                .is_some_and(|e| ACCEPTED_EXTENSIONS.contains(&e.to_ascii_lowercase().as_str()));
            if !accepted {
                return Err(AppError::new(
                    "intake_file_type",
                    "Only PDF, PNG, TIFF and JPEG drawings can be read.",
                ));
            }
            let regular = std::fs::symlink_metadata(&path).is_ok_and(|m| m.is_file());
            if !regular {
                return Err(AppError::new(
                    "intake_file_missing",
                    "A dropped file was not found.",
                ));
            }
            util::absolute(&path).map_err(AppError::from_code)
        })
        .collect()
}

fn valid_intake_id(id: &str) -> bool {
    id.starts_with("intake-") && util::valid_id(id, 64)
}

fn set_folder(runs_folder: &Path, intake_id: &str) -> AppResult<PathBuf> {
    if !valid_intake_id(intake_id) {
        return Err(AppError::new(
            "intake_unknown",
            "This drawing set is not known.",
        ));
    }
    Ok(runs_folder.join(INTAKE_SETS).join(intake_id))
}

/// Render and survey the dropped files. Never refuses a readable page.
pub fn prepare_intake(
    runs_folder: &Path,
    worker: &Worker,
    files: &[String],
    ai_active: bool,
) -> AppResult<IntakePreview> {
    let paths = check_files(files)?;
    let intake_id = format!("intake-{}", util::now_ms());
    let folder = set_folder(runs_folder, &intake_id)?;
    let prepare = folder.join("prepare");
    std::fs::create_dir_all(&prepare)
        .map_err(|_| AppError::new("runs_folder", "The runs folder could not be written."))?;
    let mut args: Vec<&std::ffi::OsStr> =
        vec!["prepare".as_ref(), "--out".as_ref(), prepare.as_os_str()];
    args.extend(paths.iter().map(|p| p.as_os_str()));
    let mut value = worker.call(&args)?;
    value["intake_id"] = intake_id.clone().into();
    value["ai_active"] = ai_active.into();
    let mut preview: IntakePreview = serde_json::from_value(value).map_err(|_| {
        AppError::new(
            "intake_worker",
            "The drawing reader gave an unknown answer.",
        )
    })?;
    if !ai_active {
        preview.warnings.push(IntakeWarning {
            code: "ai_off".into(),
            message: "AI drafting is off. A drawing set without a spec needs the AI to read stations and scale.".into(),
            file: None,
        });
    }
    Ok(preview)
}

/// Check the person's edits before they reach the worker.
pub fn check_preview(preview: &IntakePreview) -> AppResult<()> {
    if !preview.pages.iter().any(|p| !p.skip) {
        return Err(AppError::new(
            "intake_no_pages",
            "Every page is skipped. Keep at least one page.",
        ));
    }
    for page in &preview.pages {
        for region in &page.regions {
            let [left, top, right, bottom] = region.region_px;
            let inside = 0 <= left
                && left < right
                && right <= i64::from(page.width_px)
                && 0 <= top
                && top < bottom
                && bottom <= i64::from(page.height_px);
            if !VIEW_LABELS.contains(&region.label.as_str()) || !inside {
                return Err(AppError::new(
                    "intake_region",
                    "A view region has an unknown label or lies outside its page.",
                ));
            }
        }
    }
    Ok(())
}

/// Write the run inputs of an edited preview; returns the folder that holds
/// `spec.json`, `intake.json` and `sources/`.
pub fn write_run_inputs(
    runs_folder: &Path,
    worker: &Worker,
    preview: &IntakePreview,
) -> AppResult<PathBuf> {
    check_preview(preview)?;
    let folder = set_folder(runs_folder, &preview.intake_id)?;
    if !folder.is_dir() {
        return Err(AppError::new(
            "intake_unknown",
            "This drawing set is not known.",
        ));
    }
    let stamp = util::now_ms();
    let edited = folder.join(format!("preview-{stamp}.json"));
    let inputs = folder.join(format!("run-input-{stamp}"));
    util::atomic_json(&edited, preview, false).map_err(AppError::from_code)?;
    let value = worker.call(&[
        "write-spec".as_ref(),
        "--preview".as_ref(),
        edited.as_os_str(),
        "--out".as_ref(),
        inputs.as_os_str(),
    ])?;
    if value["spec_path"].as_str().is_none() {
        return Err(AppError::new(
            "intake_worker",
            "The run spec was not written.",
        ));
    }
    Ok(inputs)
}

/// Copy the run inputs into `<task>/intake/` (spec, intake record, all sources).
pub fn copy_inputs_to_task(inputs: &Path, task: &Path) -> AppResult<()> {
    copy_tree(inputs, &task.join("intake"), 0).map_err(|_| {
        AppError::new(
            "intake_copy",
            "The drawings could not be copied into the run.",
        )
    })
}

fn copy_tree(from: &Path, to: &Path, depth: usize) -> std::io::Result<()> {
    std::fs::create_dir_all(to)?;
    for entry in std::fs::read_dir(from)? {
        let entry = entry?;
        let kind = entry.file_type()?;
        if kind.is_file() {
            std::fs::copy(entry.path(), to.join(entry.file_name()))?;
        } else if kind.is_dir() && depth < 2 {
            copy_tree(&entry.path(), &to.join(entry.file_name()), depth + 1)?;
        }
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn page() -> IntakePage {
        IntakePage {
            page_id: "p1".into(),
            file: "/tmp/a.pdf".into(),
            file_name: "a.pdf".into(),
            kind: "pdf".into(),
            page_index: 0,
            dpi: Some(200.0),
            dpi_source: "pdf_render".into(),
            width_px: 100,
            height_px: 50,
            thumbnail_png_base64: String::new(),
            thumbnail_scale: 1.0,
            regions: vec![IntakeRegion {
                region_id: "r1".into(),
                label: "body_plan".into(),
                confidence: 0.5,
                region_px: [0, 0, 100, 50],
                evidence: String::new(),
            }],
            warnings: vec![],
            skip: false,
        }
    }

    #[test]
    fn worker_preview_json_reads_with_extra_fields() {
        let raw = r#"{"schema":"marinaframe.intake.preview/1","intake_id":"intake-1","render_dpi":200,
            "warnings":[{"code":"unreadable_file","file":"/x.png","message":"x.png could not be read"}],
            "particulars":{},"engineering_approved":false,"pages":[{"page_id":"p1","file":"/a.png",
            "file_name":"a.png","kind":"raster","page_index":0,"dpi":null,"dpi_source":"unknown",
            "width_px":10,"height_px":10,"thumbnail_png_base64":"","thumbnail_scale":1,
            "regions":[{"region_id":"r1","label":"other","confidence":0.1,"region_px":[0,0,10,10],
            "evidence":"no separate ink groups","aspect":1.0}],
            "warnings":[{"code":"dpi_unknown","message":"The file does not say its resolution."}],"skip":false}]}"#;
        let preview: IntakePreview = serde_json::from_str(raw).unwrap();
        assert_eq!(preview.pages[0].dpi, None);
        assert_eq!(preview.pages[0].regions[0].label, "other");
        assert_eq!(preview.warnings[0].file.as_deref(), Some("/x.png"));
        assert!(!preview.ai_active);
        let back = serde_json::to_value(&preview).unwrap();
        for key in [
            "intake_id",
            "pages",
            "warnings",
            "render_dpi",
            "particulars",
            "ai_active",
        ] {
            assert!(back.get(key).is_some(), "{key}");
        }
        assert_eq!(back["particulars"]["vessel_name"], "");
    }

    #[test]
    fn files_must_exist_and_have_a_drawing_type() {
        let tmp = tempfile::tempdir().unwrap();
        let text = tmp.path().join("notes.txt");
        std::fs::write(&text, "x").unwrap();
        let png = tmp.path().join("sheet.PNG");
        std::fs::write(&png, "x").unwrap();
        assert_eq!(
            check_files(&[text.to_string_lossy().into()])
                .unwrap_err()
                .code,
            "intake_file_type"
        );
        let missing = tmp.path().join("gone.pdf").to_string_lossy().into_owned();
        assert_eq!(
            check_files(&[missing]).unwrap_err().code,
            "intake_file_missing"
        );
        assert_eq!(check_files(&[]).unwrap_err().code, "intake_files");
        assert_eq!(
            check_files(&[png.to_string_lossy().into()]).unwrap().len(),
            1
        );
    }

    #[test]
    fn edits_are_checked_before_the_worker_runs() {
        let mut preview = IntakePreview {
            intake_id: "intake-1".into(),
            pages: vec![page()],
            warnings: vec![],
            render_dpi: 200.0,
            particulars: Particulars::default(),
            ai_active: true,
        };
        assert!(check_preview(&preview).is_ok());
        preview.pages[0].regions[0].label = "deck".into();
        assert_eq!(check_preview(&preview).unwrap_err().code, "intake_region");
        preview.pages[0].regions[0].label = "profile".into();
        preview.pages[0].regions[0].region_px = [0, 0, 101, 50];
        assert_eq!(check_preview(&preview).unwrap_err().code, "intake_region");
        preview.pages[0].skip = true;
        assert_eq!(check_preview(&preview).unwrap_err().code, "intake_no_pages");
    }

    #[test]
    fn intake_ids_cannot_leave_the_intake_folder() {
        let runs = Path::new("/runs");
        assert!(set_folder(runs, "../x").is_err());
        assert!(set_folder(runs, "intake-../../x").is_err());
        assert_eq!(
            set_folder(runs, "intake-12").unwrap(),
            Path::new("/runs/intake-sets/intake-12")
        );
    }

    #[test]
    fn missing_python_is_a_plain_error() {
        let worker = Worker {
            python: "",
            source: None,
        };
        let tmp = tempfile::tempdir().unwrap();
        let png = tmp.path().join("a.png");
        std::fs::write(&png, "x").unwrap();
        let error =
            prepare_intake(tmp.path(), &worker, &[png.to_string_lossy().into()], true).unwrap_err();
        assert_eq!(error.code, "worker_python_missing");
    }
}
