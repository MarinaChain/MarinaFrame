//! `prepare_intake` and the spec writer through the real Python worker.
//! Needs `MARINAFRAME_TEST_PYTHON`; local runs skip when it is missing; CI requires it.
mod support;

use marinaframe_app_core::intake::{self, Worker};
use marinaframe_app_core::worker_run::UNCANCELLABLE;
use std::path::{Path, PathBuf};
use std::process::Command;

fn repo_src() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("../../src")
        .canonicalize()
        .unwrap()
}

/// A white 600 x 400 PNG with two drawn boxes, at 150 dpi.
fn make_png(python: &str, path: &Path) {
    let script = "import sys; from PIL import Image, ImageDraw\n\
        im = Image.new('RGB', (600, 400), 'white'); d = ImageDraw.Draw(im)\n\
        d.rectangle([40, 40, 260, 300], outline='black', width=3)\n\
        d.line([300, 200, 580, 120], fill='black', width=3)\n\
        im.save(sys.argv[1], dpi=(150, 150))";
    let made = Command::new(python)
        .args(["-c", script])
        .arg(path)
        .status()
        .unwrap();
    assert!(made.success());
}

#[test]
fn prepare_then_write_a_sheet_only_spec() {
    let Some(python) = support::worker_python() else {
        return;
    };
    let tmp = tempfile::tempdir().unwrap();
    let png = tmp.path().join("sheet.png");
    make_png(&python, &png);
    let src = repo_src();
    let worker = Worker {
        python: &python,
        source: Some(&src),
    };
    let runs = tmp.path().join("runs");
    let mut preview = intake::prepare_intake(
        &runs,
        &worker,
        &[png.to_string_lossy().into()],
        false,
        &UNCANCELLABLE,
    )
    .unwrap();
    assert!(preview.intake_id.starts_with("intake-"));
    assert_eq!(preview.pages.len(), 1);
    let page = &preview.pages[0];
    assert_eq!((page.width_px, page.height_px), (600, 400));
    assert_eq!(page.dpi, Some(150.0));
    assert!(!page.regions.is_empty());
    assert!(!page.thumbnail_png_base64.is_empty());
    let codes: Vec<&str> = page.warnings.iter().map(|w| w.code.as_str()).collect();
    assert!(codes.contains(&"low_dpi"), "{codes:?}");
    assert!(preview.warnings.iter().any(|w| w.code == "ai_off"));

    // The person relabels the first region and names the vessel.
    preview.pages[0].regions[0].label = "body_plan".into();
    preview.particulars.vessel_name = "Survey launch 24 m".into();
    preview.particulars.beam_m = Some(7.2);
    let inputs = intake::write_run_inputs(&runs, &worker, &preview).unwrap();
    let spec: serde_json::Value =
        serde_json::from_slice(&std::fs::read(inputs.join("spec.json")).unwrap()).unwrap();
    assert_eq!(spec["sections"], serde_json::json!([]));
    assert_eq!(spec["vessel_id"], "survey-launch-24-m");
    assert_eq!(spec["constraints"]["beam_m"], 7.2);
    assert!(inputs
        .join(spec["source"]["file"].as_str().unwrap())
        .is_file());
    assert!(inputs.join("intake.json").is_file());

    let task = tmp.path().join("task");
    std::fs::create_dir(&task).unwrap();
    intake::copy_inputs_to_task(&inputs, &task).unwrap();
    assert!(task.join("intake/spec.json").is_file());
    assert!(task.join("intake/sources/sheet.png").is_file());
}

/// The Sources tab shows page 2 of a dropped PDF through the worker's page renderer.
#[test]
fn a_dropped_pdf_page_is_rendered_for_the_sources_tab() {
    use base64::{engine::general_purpose::STANDARD, Engine};
    use marinaframe_app_core::sources::{self, PreviewSize, SourceKind};
    let Some(python) = support::worker_python() else {
        return;
    };
    let tmp = tempfile::tempdir().unwrap();
    let task = tmp.path().join("task");
    std::fs::create_dir_all(task.join("intake/sources")).unwrap();
    // A4 landscape then A4 portrait, in points.
    let script = "import sys, fitz\n\
        doc = fitz.open(); doc.new_page(width=842, height=595)\n\
        page = doc.new_page(width=595, height=842); page.insert_text((72, 72), 'Sheet 2')\n\
        doc.save(sys.argv[1])";
    let pdf = task.join("intake/sources/set.pdf");
    assert!(Command::new(&python)
        .args(["-c", script])
        .arg(&pdf)
        .status()
        .unwrap()
        .success());
    std::fs::write(
        task.join("intake/intake.json"),
        r#"{"spec_page_id": "p1", "pages": [
            {"page_id": "p1", "file_name": "set.pdf", "page_index": 0, "source_file": "sources/set.pdf"},
            {"page_id": "p2", "file_name": "set.pdf", "page_index": 1, "source_file": "sources/set.pdf"}]}"#,
    )
    .unwrap();
    let list = sources::list_sources(&task).unwrap();
    let set = &list.sources[0];
    assert_eq!((set.kind, set.pages.len()), (SourceKind::Pdf, 2));

    let src = repo_src();
    let worker = Worker {
        python: &python,
        source: Some(&src),
    };
    let full = sources::read_source_page(&task, &worker, &set.id, 1, PreviewSize::Full).unwrap();
    assert_eq!(full.mime, "image/png");
    // Portrait page at the worker's highest render resolution (300 dpi: 842 pt is 3508 px).
    assert!(
        full.height > full.width && (3400..=4096).contains(&full.height),
        "{} x {}",
        full.width,
        full.height
    );
    let bytes = STANDARD.decode(full.base64.unwrap()).unwrap();
    assert!(bytes.starts_with(b"\x89PNG"));
    let thumb = sources::read_source_page(&task, &worker, &set.id, 0, PreviewSize::Thumb).unwrap();
    assert!(thumb.width > thumb.height && thumb.width <= 320);
}
