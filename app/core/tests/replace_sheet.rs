mod support;

use marinaframe_app_core::{actions::ActionRegistry, sheet_review};
use serde_json::json;

#[test]
fn replacement_requires_a_known_sheet_before_starting_a_worker() {
    let tmp = tempfile::tempdir().unwrap();
    std::fs::create_dir(tmp.path().join("domain")).unwrap();
    std::fs::write(
        tmp.path().join("domain/state.json"),
        json!({"sheet_review": {
            "sheets": [{"id":"source"}], "outputs":[], "requests":[], "history":[]
        }})
        .to_string(),
    )
    .unwrap();
    let png = tmp.path().join("new.png");
    std::fs::write(&png, b"placeholder").unwrap();
    let error =
        sheet_review::replace_sheet(&ActionRegistry::default(), tmp.path(), "unknown", &png)
            .unwrap_err();
    assert_eq!(error.code, "sheet_not_found");
    assert!(!tmp.path().join("sheet-inbox").exists());
}

#[test]
fn sheet_review_survives_a_read_and_keeps_request_ownership() {
    let tmp = tempfile::tempdir().unwrap();
    std::fs::create_dir(tmp.path().join("domain")).unwrap();
    let review = json!({"sheets":[{"id":"source","status":"unreadable","reason":"Too faint"}],
        "outputs":[{"id":"hull-read","status":"failed","sheet_ids":["source"]}],
        "requests":[{"status":"open","who":"Yard","sheet_id":"source","output_id":"hull-read"}],
        "history":[]});
    std::fs::write(
        tmp.path().join("domain/state.json"),
        json!({"sheet_review":review}).to_string(),
    )
    .unwrap();
    assert_eq!(sheet_review::read(tmp.path()), review);
}

#[test]
fn real_worker_replaces_one_unreadable_extra_sheet_without_a_hull_rebuild() {
    use marinaframe_control::{controller, store::Store, types::*, util};
    use std::{
        path::Path,
        process::Command,
        time::{Duration, Instant},
    };
    let repo = Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("../..")
        .canonicalize()
        .unwrap();
    let Some(python) = support::worker_python() else {
        return;
    };
    assert!(
        Path::new(&python).is_file(),
        "MARINAFRAME_TEST_PYTHON is not a file"
    );
    let tmp = tempfile::tempdir().unwrap();
    let inputs = tmp.path().join("inputs");
    let script = r#"
import sys, json
from pathlib import Path
from PIL import Image
from vessel_reconstruction.intake import prepare, write_spec
root=Path(sys.argv[1]); root.mkdir()
Image.new('RGB',(300,240),'white').save(root/'good.png')
(root/'bad.png').write_bytes(b'broken')
preview=prepare([root/'good.png',root/'bad.png'],root/'set')
write_spec(preview,root/'set')
(root/'set/sheet_review_preview.json').write_text(json.dumps({'warnings':preview['warnings']}))
"#;
    assert!(Command::new(&python)
        .args(["-c", script])
        .arg(&inputs)
        .env("PYTHONPATH", repo.join("src"))
        .status()
        .unwrap()
        .success());
    let task = tmp.path().join("task");
    let config = Config {
        worker_python: python,
        worker_source: Some(repo.join("src").to_string_lossy().into_owned()),
        source_spec: inputs.join("set/spec.json").to_string_lossy().into_owned(),
        policy: Policy::Deterministic,
        limits: OperationalLimits::default(),
        provider_transfer_authorized: false,
        authorization_basis: String::new(),
        model: marinaframe_control::models::DEFAULT_MODELS[0].into(),
        binary_sha256: util::file_hash(&std::env::current_exe().unwrap()).unwrap(),
        on_ambiguity: OnAmbiguity::Draft,
        fallback_models: vec![],
    };
    let mut store = Store::create(&task, controller::new_state(config)).unwrap();
    assert!(controller::call_worker(&mut store, "initialize", json!({})).unwrap());
    let source_manifest = store.state.source_manifest_sha256.clone();
    drop(store);
    let review = sheet_review::read(&task);
    let bad = review["sheets"]
        .as_array()
        .unwrap()
        .iter()
        .find(|s| s["status"] == "unreadable")
        .unwrap();
    let registry = ActionRegistry::default();
    sheet_review::replace_sheet(
        &registry,
        &task,
        bad["id"].as_str().unwrap(),
        &inputs.join("good.png"),
    )
    .unwrap();
    let deadline = Instant::now() + Duration::from_secs(90);
    while registry.is_busy(&task) && Instant::now() < deadline {
        std::thread::sleep(Duration::from_millis(20));
    }
    assert!(!registry.is_busy(&task), "replacement timed out");
    assert_eq!(registry.last_error(&task), None);
    let store = Store::open(&task).unwrap();
    store.verify(false).unwrap();
    assert_eq!(store.state.source_manifest_sha256, source_manifest);
    assert_eq!(store.state.status, Status::DraftNotVerified);
    assert!(!store.state.engineering_approved);
    let review = sheet_review::read(&task);
    assert_eq!(review["requests"][0]["status"], "answered");
    assert_eq!(review["history"][0]["stages"], json!(["sheet_read"]));
    assert_eq!(review["history"][0]["status"], "draft");
    assert!(task.join("domain/input/spec.json").is_file());
    drop(store);

    // A primary-sheet replacement is the one person action permitted to change
    // the source manifest. It must still pass the controller's identity checks.
    std::fs::write(task.join("cancel.request"), b"{}").unwrap();
    sheet_review::replace_sheet(&registry, &task, "source", &inputs.join("good.png")).unwrap();
    let deadline = Instant::now() + Duration::from_secs(660);
    while registry.is_busy(&task) && Instant::now() < deadline {
        std::thread::sleep(Duration::from_millis(20));
    }
    assert!(!registry.is_busy(&task), "primary replacement timed out");
    assert_eq!(registry.last_error(&task), None);
    assert!(!task.join("cancel.request").exists());
    let store = Store::open(&task).unwrap();
    store.verify(false).unwrap();
    assert_ne!(store.state.source_manifest_sha256, source_manifest);
    assert!(!store.state.engineering_approved);
    let review = sheet_review::read(&task);
    assert_eq!(review["history"][1]["sheet_id"], "source");
    assert!(task.join("domain/input/spec.json").is_file());
}

#[test]
fn older_runs_still_show_their_source_sheet() {
    let tmp = tempfile::tempdir().unwrap();
    std::fs::create_dir(tmp.path().join("domain")).unwrap();
    std::fs::write(
        tmp.path().join("domain/state.json"),
        json!({"sources": {
            "source":{"file":"source.png","sha256":"old-hash"}
        }})
        .to_string(),
    )
    .unwrap();
    assert_eq!(sheet_review::read(tmp.path())["sheets"][0]["id"], "source");
}
