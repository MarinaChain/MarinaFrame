//! `prepare_intake` and the spec writer through the real Python worker.
//! Needs `MARINAFRAME_TEST_PYTHON`; the test skips itself when it is missing.
use marinaframe_app_core::intake::{self, Worker};
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
    let Ok(python) = std::env::var("MARINAFRAME_TEST_PYTHON") else {
        eprintln!("MARINAFRAME_TEST_PYTHON not set; skipping");
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
    let mut preview =
        intake::prepare_intake(&runs, &worker, &[png.to_string_lossy().into()], false).unwrap();
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
