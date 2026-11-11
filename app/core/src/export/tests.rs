use super::*;
use std::os::unix::fs::PermissionsExt;
use std::time::Instant;

const STEM: &str = "Box_r0003_DRAFT";

#[test]
fn listed_package_reports_display_omissions() {
    let root = tempfile::tempdir().unwrap();
    let folder = exports_folder(root.path(), "r0003");
    std::fs::create_dir_all(&folder).unwrap();
    std::fs::write(folder.join(format!("{STEM}_manifest.json")),
        r#"{"display_omissions":[{"file":"tanks.glb","reason":"display model belongs to revision 'r0002'"}]}"#).unwrap();
    let result = list_exports(root.path(), "r3").unwrap();
    assert_eq!(result.display_omissions[0]["file"], "tanks.glb");
    assert!(result.display_omissions[0]["reason"]
        .as_str()
        .unwrap()
        .contains("r0002"));
}

#[test]
fn failed_format_removes_an_old_file_and_keeps_other_outputs() {
    let root = tempfile::tempdir().unwrap();
    let staging = root.path().join("stage");
    let folder = root.path().join("exports");
    std::fs::create_dir_all(&staging).unwrap();
    std::fs::create_dir_all(&folder).unwrap();
    std::fs::write(folder.join(format!("{STEM}_model.iges")), b"old").unwrap();
    std::fs::write(staging.join(format!("{STEM}_model.step")), b"new").unwrap();
    let manifest = serde_json::json!({"not_built": ["iges_model"],
        "format_results": {"iges": {"status": "failed", "reason": "writer failed"}}});
    let missing = keep_chosen(&staging, &folder, &["step", "iges"], &manifest).unwrap();
    assert_eq!(missing, ["iges"]);
    assert!(!folder.join(format!("{STEM}_model.iges")).exists());
    assert!(folder.join(format!("{STEM}_model.step")).is_file());
}

#[test]
fn failed_ocx_removes_old_ocx_but_keeps_steel_tables() {
    let root = tempfile::tempdir().unwrap();
    let staging = root.path().join("stage");
    let folder = root.path().join("exports");
    std::fs::create_dir_all(&staging).unwrap();
    std::fs::create_dir_all(&folder).unwrap();
    let ocx = folder.join(format!("{STEM}_block.3docx"));
    let steel = folder.join(format!("{STEM}_block_steel_members.csv"));
    std::fs::write(&ocx, b"old").unwrap();
    std::fs::write(&steel, b"steel").unwrap();
    let manifest = serde_json::json!({"format_results": {"ocx": {"status": "failed", "reason": "writer failed"}}});
    keep_chosen(&staging, &folder, &["structure"], &manifest).unwrap();
    assert!(!ocx.exists());
    assert!(steel.exists());
}

/// A stand-in for Python: a shell script that writes the files of a full export
/// (no STL, like a build without a mesh) and prints a manifest.
fn fake_worker(dir: &Path, body: &str) -> PathBuf {
    let script = dir.join("python");
    std::fs::write(&script, format!("#!/bin/sh\n{body}\n")).unwrap();
    std::fs::set_permissions(&script, std::fs::Permissions::from_mode(0o755)).unwrap();
    script
}

fn full_export_script() -> String {
    let files = [
        "offsets.csv",
        "hydrostatics.json",
        "hydrostatics.csv",
        "report.pdf",
        "model.step",
        "model.iges",
        "model.3dm",
        "manifest.json",
        "package.zip",
    ];
    let writes: Vec<String> = files
        .iter()
        .map(|f| format!("printf 'abc' > \"$out/{STEM}_{f}\""))
        .collect();
    format!(
        "out=''\nwhile [ $# -gt 0 ]; do [ \"$1\" = --out ] && out=\"$2\"; shift; done\n{}\n\
         echo '{{\"revision\":\"r0003\",\"not_built\":[\"stl_mesh\"],\"engineering_approved\":false}}'",
        writes.join("\n")
    )
}

fn kinds(result: &ExportResult) -> Vec<&str> {
    result.files.iter().map(|f| f.kind.as_str()).collect()
}

#[test]
fn revisions_are_normalised_and_checked() {
    assert_eq!(normalise_revision("r3").unwrap(), "r0003");
    assert_eq!(normalise_revision("r0003").unwrap(), "r0003");
    assert_eq!(normalise_revision("r12345").unwrap(), "r12345");
    for bad in ["", "r", "3", "r-1", "r../x", "r1234567", "R3"] {
        assert_eq!(
            normalise_revision(bad).unwrap_err().code,
            "export_revision",
            "{bad}"
        );
    }
}

#[test]
fn outputs_must_be_known_and_not_empty() {
    assert_eq!(check_outputs(&[]).unwrap_err().code, "export_outputs");
    assert_eq!(
        check_outputs(&["dxf".into()]).unwrap_err().code,
        "export_outputs"
    );
    let chosen = check_outputs(&["package".into(), "step".into(), "step".into()]).unwrap();
    assert_eq!(chosen, ["step", "package"]);
}

#[test]
fn file_kinds_come_from_the_name_suffix() {
    assert_eq!(kind_of_file("V_r0001_DRAFT_model.iges"), Some("iges"));
    assert_eq!(kind_of_file("V_r0001_DRAFT_model.3dm"), Some("3dm"));
    assert_eq!(kind_of_file("V_r0001_DRAFT_offsets.csv"), Some("offsets"));
    assert_eq!(
        kind_of_file("V_r0001_DRAFT_hydrostatics.csv"),
        Some("hydrostatics")
    );
    assert_eq!(kind_of_file("V_r0001_DRAFT_model.stl"), Some("stl"));
    assert_eq!(kind_of_file("V_r0001_DRAFT_manifest.json"), Some(MANIFEST));
    assert_eq!(kind_of_file("notes.txt"), None);
    assert_eq!(kind_of_file(".staging-x_report.pdf"), None);
    assert_eq!(kind_of_file("a/b_report.pdf"), None);
}

#[test]
fn new_cad_outputs_are_selected_moved_and_listed_like_step() {
    let tmp = tempfile::tempdir().unwrap();
    let python = fake_worker(tmp.path(), &full_export_script());
    let python = python.to_string_lossy();
    let worker = Worker {
        python: &python,
        source: None,
    };
    let result = export_run(
        tmp.path(),
        &worker,
        "r3",
        &["3dm".into(), "iges".into()],
        EXPORT_STALL_PERIOD,
    )
    .unwrap();
    assert_eq!(kinds(&result), ["iges", "3dm", MANIFEST]);
    assert!(result.not_built.is_empty());
    assert_eq!(
        kinds(&list_exports(tmp.path(), "r3").unwrap()),
        ["iges", "3dm", MANIFEST]
    );
    assert!(result
        .files
        .iter()
        .all(|file| Path::new(&file.path).is_file()));
    assert!(!Path::new(&result.folder)
        .join(format!("{STEM}_model.step"))
        .exists());
}

#[test]
fn missing_new_cad_files_are_reported_as_output_kinds() {
    let tmp = tempfile::tempdir().unwrap();
    let script = full_export_script()
        .replace(&format!("printf 'abc' > \"$out/{STEM}_model.iges\""), "")
        .replace(&format!("printf 'abc' > \"$out/{STEM}_model.3dm\""), "")
        .replace(
            "[\"stl_mesh\"]",
            "[\"iges_model\",\"rhino_model\",\"stl_mesh\"]",
        );
    let python = fake_worker(tmp.path(), &script);
    let python = python.to_string_lossy();
    let worker = Worker {
        python: &python,
        source: None,
    };
    let result = export_run(
        tmp.path(),
        &worker,
        "r3",
        &["iges".into(), "3dm".into()],
        EXPORT_STALL_PERIOD,
    )
    .unwrap();
    assert_eq!(result.not_built, ["iges", "3dm"]);
    assert_eq!(kinds(&result), [MANIFEST]);
}

#[test]
fn only_the_chosen_outputs_and_the_manifest_are_kept() {
    let tmp = tempfile::tempdir().unwrap();
    let task = tmp.path().join("task");
    std::fs::create_dir(&task).unwrap();
    let python = fake_worker(tmp.path(), &full_export_script());
    let python = python.to_string_lossy();
    let worker = Worker {
        python: &python,
        source: None,
    };
    let outputs = ["offsets".to_string(), "stl".into(), "report".into()];

    let result = export_run(&task, &worker, "r3", &outputs, EXPORT_STALL_PERIOD).unwrap();

    assert_eq!(result.revision, "r0003");
    assert_eq!(kinds(&result), ["offsets", "report", MANIFEST]);
    assert_eq!(result.not_built, ["stl"]);
    assert!(!result.engineering_approved);
    assert!(result.files.iter().all(|f| f.bytes == 3));
    let folder = task.join("exports/r0003");
    assert_eq!(Path::new(&result.folder), folder);
    assert!(folder.join(format!("{STEM}_offsets.csv")).is_file());
    assert!(!folder.join(format!("{STEM}_package.zip")).exists());
    // The staging folder is gone.
    let left: Vec<_> = std::fs::read_dir(task.join("exports")).unwrap().collect();
    assert_eq!(left.len(), 1);

    // A later export adds to the folder; the listing shows everything.
    export_run(
        &task,
        &worker,
        "r0003",
        &["package".into()],
        EXPORT_STALL_PERIOD,
    )
    .unwrap();
    let listed = list_exports(&task, "r3").unwrap();
    assert_eq!(kinds(&listed), ["offsets", "report", "package", MANIFEST]);
}

#[test]
fn a_worker_refusal_is_a_plain_error() {
    let tmp = tempfile::tempdir().unwrap();
    let python = fake_worker(
        tmp.path(),
        "echo '{\"error\": \"no valid build for revision r0009\"}' >&2\nexit 2",
    );
    let python = python.to_string_lossy();
    let worker = Worker {
        python: &python,
        source: None,
    };
    let error = export_run(
        tmp.path(),
        &worker,
        "r9",
        &["report".into()],
        EXPORT_STALL_PERIOD,
    )
    .unwrap_err();
    assert_eq!(error.code, "export_worker");
    assert!(
        error.message.contains("no valid build"),
        "{}",
        error.message
    );
    assert!(list_exports(tmp.path(), "r9").unwrap().files.is_empty());
}

#[test]
fn a_worker_without_progress_is_stopped() {
    let tmp = tempfile::tempdir().unwrap();
    let python = fake_worker(tmp.path(), "exec sleep 30");
    let python = python.to_string_lossy();
    let worker = Worker {
        python: &python,
        source: None,
    };
    let started = Instant::now();
    let error = export_run(
        tmp.path(),
        &worker,
        "r1",
        &["report".into()],
        Duration::from_millis(300),
    )
    .unwrap_err();
    assert_eq!(error.code, "export_stalled");
    assert!(
        error.message.contains("min without progress"),
        "{}",
        error.message
    );
    assert!(started.elapsed() < Duration::from_secs(10));
    let left: Vec<_> = std::fs::read_dir(tmp.path().join("exports"))
        .unwrap()
        .collect();
    assert!(left.is_empty(), "staging folder left behind");
}

#[test]
fn missing_python_is_a_plain_error() {
    let tmp = tempfile::tempdir().unwrap();
    let worker = Worker {
        python: "",
        source: None,
    };
    let error = export_run(
        tmp.path(),
        &worker,
        "r1",
        &["report".into()],
        EXPORT_STALL_PERIOD,
    )
    .unwrap_err();
    assert_eq!(error.code, "worker_python_missing");
}

#[test]
fn reveal_accepts_only_paths_inside_the_exports_folder() {
    let tmp = tempfile::tempdir().unwrap();
    let task = tmp.path().join("task");
    let folder = task.join("exports/r0001");
    std::fs::create_dir_all(&folder).unwrap();
    let file = folder.join("V_r0001_DRAFT_report.pdf");
    std::fs::write(&file, "x").unwrap();
    std::fs::write(task.join("state.json"), "{}").unwrap();
    assert!(check_reveal_path(&task, &file.to_string_lossy()).is_ok());
    assert!(check_reveal_path(&task, &folder.to_string_lossy()).is_ok());
    for outside in [
        task.join("state.json"),
        folder.join("../../state.json"),
        tmp.path().join("missing.pdf"),
    ] {
        let error = check_reveal_path(&task, &outside.to_string_lossy()).unwrap_err();
        assert_eq!(error.code, "export_reveal");
    }
}

#[test]
fn tank_and_structure_files_have_their_own_kinds() {
    assert_eq!(
        kind_of_file("V_r0001_DRAFT_capacity_plan.csv"),
        Some("tanks")
    );
    assert_eq!(
        kind_of_file("V_r0001_DRAFT_sounding_db1.csv"),
        Some("tanks")
    );
    assert_eq!(
        kind_of_file("V_r0001_DRAFT_sounding_offsets.csv"),
        Some("tanks")
    );
    assert_eq!(
        kind_of_file("V_r0001_DRAFT_b_DRAFT_steel_members.csv"),
        Some("structure")
    );
    assert_eq!(
        kind_of_file("V_r0001_DRAFT_b_DRAFT.3docx"),
        Some("structure")
    );
}

#[test]
fn the_tank_model_and_structure_folder_go_to_the_worker() {
    let tmp = tempfile::tempdir().unwrap();
    let task = tmp.path().join("task");
    std::fs::create_dir_all(task.join("structure")).unwrap();
    std::fs::write(task.join("tanks.npz"), "npz").unwrap();
    std::fs::write(task.join("structure/b_DRAFT_steel_totals.csv"), "x").unwrap();
    let args_file = tmp.path().join("args.txt");
    let script = format!(
        "printf '%s\\n' \"$@\" > \"{}\"\n{}",
        args_file.display(),
        full_export_script().replace(
            "printf 'abc' > \"$out/{STEM}_package.zip\"".replace("{STEM}", STEM).as_str(),
            &format!(
                "printf 'abc' > \"$out/{STEM}_package.zip\"\nprintf 'abc' > \"$out/{STEM}_capacity_plan.csv\"\n\
                 printf 'abc' > \"$out/{STEM}_sounding_db1.csv\"\n\
                 printf 'abc' > \"$out/{STEM}_b_DRAFT_steel_totals.csv\""
            )
        )
    );
    let python = fake_worker(tmp.path(), &script);
    let python = python.to_string_lossy();
    let worker = Worker {
        python: &python,
        source: None,
    };
    let outputs = ["tanks".to_string(), "structure".into()];

    let result = export_run(&task, &worker, "r3", &outputs, EXPORT_STALL_PERIOD).unwrap();

    assert_eq!(kinds(&result), ["tanks", "tanks", "structure", MANIFEST]);
    assert!(result.not_built.is_empty());
    let args = std::fs::read_to_string(&args_file).unwrap();
    assert!(args.contains(&format!("--tanks\n{}", task.join("tanks.npz").display())));
    assert!(args.contains(&format!(
        "--structure\n{}",
        task.join("structure").display()
    )));
}

#[test]
fn tanks_and_structure_without_their_inputs_are_not_built() {
    let tmp = tempfile::tempdir().unwrap();
    let task = tmp.path().join("task");
    std::fs::create_dir(&task).unwrap();
    let python = fake_worker(tmp.path(), &full_export_script());
    let python = python.to_string_lossy();
    let worker = Worker {
        python: &python,
        source: None,
    };
    let outputs = ["tanks".to_string(), "structure".into(), "offsets".into()];
    let result = export_run(&task, &worker, "r3", &outputs, EXPORT_STALL_PERIOD).unwrap();
    assert_eq!(result.not_built, ["tanks", "structure"]);
    assert_eq!(kinds(&result), ["offsets", MANIFEST]);
}

/// A worker that writes a report whose text says whether the app's 3D view picture was in the
/// folder it was given, and copies that picture next to it so a test can see its bytes.
fn capture_aware_script() -> String {
    full_export_script().replace(
        &format!("printf 'abc' > \"$out/{STEM}_report.pdf\""),
        &format!(
            "if [ -f \"$out/{VIEWER_CAPTURE_FILE}\" ]; then cp \"$out/{VIEWER_CAPTURE_FILE}\" \"$out/{STEM}_report.pdf\"; \
             else printf 'no-picture' > \"$out/{STEM}_report.pdf\"; fi"
        ),
    )
}

fn report_bytes(result: &ExportResult) -> Vec<u8> {
    let report = result.files.iter().find(|f| f.kind == "report").unwrap();
    std::fs::read(&report.path).unwrap()
}

fn png_like() -> Vec<u8> {
    let mut bytes = PNG_SIGNATURE.to_vec();
    bytes.extend_from_slice(b"picture");
    bytes
}

fn run_with_capture(capture: Option<&[u8]>) -> (tempfile::TempDir, ExportResult) {
    let tmp = tempfile::tempdir().unwrap();
    let python = fake_worker(tmp.path(), &capture_aware_script());
    let python = python.to_string_lossy();
    let worker = Worker {
        python: &python,
        source: None,
    };
    let result = export_run_with_capture(
        tmp.path(),
        &worker,
        "r3",
        &["report".into()],
        EXPORT_STALL_PERIOD,
        capture,
    )
    .unwrap();
    (tmp, result)
}

#[test]
fn the_3d_view_picture_is_in_the_worker_folder_before_the_worker_runs() {
    let picture = png_like();
    let (_tmp, result) = run_with_capture(Some(&picture));
    assert_eq!(report_bytes(&result), picture);
}

#[test]
fn the_picture_is_an_input_and_is_not_listed_or_kept() {
    let (tmp, result) = run_with_capture(Some(&png_like()));
    assert_eq!(kinds(&result), ["report", MANIFEST]);
    assert!(!Path::new(&result.folder).join(VIEWER_CAPTURE_FILE).exists());
    let exports = tmp.path().join(EXPORTS_FOLDER);
    let left: Vec<_> = std::fs::read_dir(&exports)
        .unwrap()
        .filter_map(Result::ok)
        .map(|e| e.file_name().to_string_lossy().into_owned())
        .collect();
    assert_eq!(left, ["r0003"], "no staging folder is left behind");
}

#[test]
fn without_a_picture_the_export_works_as_before() {
    let (_tmp, result) = run_with_capture(None);
    assert_eq!(report_bytes(&result), b"no-picture");
    assert_eq!(kinds(&result), ["report", MANIFEST]);
}

#[test]
fn bytes_that_are_not_a_png_or_are_too_large_are_left_out() {
    let (_tmp, result) = run_with_capture(Some(b"not a picture"));
    assert_eq!(report_bytes(&result), b"no-picture");
    let mut too_large = PNG_SIGNATURE.to_vec();
    too_large.resize(VIEWER_CAPTURE_MAX_BYTES + 1, 0);
    assert!(!is_viewer_capture(&too_large));
    let (_tmp, result) = run_with_capture(Some(&too_large));
    assert_eq!(report_bytes(&result), b"no-picture");
}
