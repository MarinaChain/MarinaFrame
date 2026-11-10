//! `export_run` through the real Python exports worker, on the trimmed real
//! fixture `tests/fixtures/exports/shipd-1-00679-L0` (no CAD files).
//! Needs `MARINAFRAME_TEST_PYTHON`; the test skips itself when it is missing.
use marinaframe_app_core::export::{self, EXPORT_TIMEOUT};
use marinaframe_app_core::intake::Worker;
use std::path::{Path, PathBuf};

fn repo_root() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("../..")
        .canonicalize()
        .unwrap()
}

fn copy_tree(from: &Path, to: &Path) {
    std::fs::create_dir_all(to).unwrap();
    for entry in std::fs::read_dir(from).unwrap() {
        let entry = entry.unwrap();
        let target = to.join(entry.file_name());
        if entry.file_type().unwrap().is_dir() {
            copy_tree(&entry.path(), &target);
        } else {
            std::fs::copy(entry.path(), target).unwrap();
        }
    }
}

#[test]
fn export_a_draft_revision_with_the_real_worker() {
    let Ok(python) = std::env::var("MARINAFRAME_TEST_PYTHON") else {
        eprintln!("MARINAFRAME_TEST_PYTHON not set; skipping");
        return;
    };
    let root = repo_root();
    let tmp = tempfile::tempdir().unwrap();
    let task = tmp.path().join("task");
    copy_tree(
        &root.join("tests/fixtures/exports/shipd-1-00679-L0/task"),
        &task,
    );
    let src = root.join("src");
    let worker = Worker {
        python: &python,
        source: Some(&src),
    };
    let outputs: Vec<String> = export::OUTPUTS.iter().map(|o| o.to_string()).collect();

    let result = export::export_run(&task, &worker, "r3", &outputs, EXPORT_TIMEOUT).unwrap();

    let kinds: Vec<&str> = result.files.iter().map(|f| f.kind.as_str()).collect();
    assert_eq!(
        kinds,
        [
            "offsets",
            "hydrostatics",
            "hydrostatics",
            "report",
            "package",
            "manifest"
        ]
    );
    // The fixture has no CAD files, no tank tables and no structure (steel/OCX) files.
    assert_eq!(
        result.not_built,
        ["step", "iges", "3dm", "stl", "tanks", "structure"]
    );
    assert!(result.files.iter().all(|f| f.bytes > 0));
    assert!(!result.engineering_approved);
    let manifest = result.files.iter().find(|f| f.kind == "manifest").unwrap();
    let manifest: serde_json::Value =
        serde_json::from_slice(&std::fs::read(&manifest.path).unwrap()).unwrap();
    assert_eq!(manifest["engineering_approved"], false);
    assert_eq!(manifest["revision"], "r0003");
}
