use super::*;
use std::os::unix::fs::PermissionsExt;

const STEM: &str = "Box_r0003_DRAFT";

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

    let result = export_run(&task, &worker, "r3", &outputs, EXPORT_TIMEOUT).unwrap();

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
    export_run(&task, &worker, "r0003", &["package".into()], EXPORT_TIMEOUT).unwrap();
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
        EXPORT_TIMEOUT,
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
fn a_slow_worker_is_stopped() {
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
    assert_eq!(error.code, "export_timeout");
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
        EXPORT_TIMEOUT,
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

    let result = export_run(&task, &worker, "r3", &outputs, EXPORT_TIMEOUT).unwrap();

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
    let result = export_run(&task, &worker, "r3", &outputs, EXPORT_TIMEOUT).unwrap();
    assert_eq!(result.not_built, ["tanks", "structure"]);
    assert_eq!(kinds(&result), ["offsets", MANIFEST]);
}
