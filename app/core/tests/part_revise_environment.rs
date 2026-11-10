//! The part-revision Python worker never sees a model key: the model calls go through the
//! controller's provider worker. This test sets keys in the app's own environment and
//! records the environment that the worker gets. It is its own test binary because it
//! changes the process environment.
use marinaframe_app_core::actions::ActionRegistry;
use marinaframe_app_core::intake::Worker;
use marinaframe_app_core::part_revise::{self, ModelChoice, REVISE_STALL_PERIOD};
use marinaframe_app_core::{parts, AppPaths};
use serde_json::json;
use std::os::unix::fs::PermissionsExt;

/// Test values only; never real keys.
const KEYS: [(&str, &str); 3] = [
    ("ANTHROPIC_API_KEY", "test-anthropic-value"),
    ("OPENCODE_API_KEY", "test-opencode-value"),
    ("OPENCODE_API_KEY_2", "test-opencode-value-2"),
];

#[test]
fn the_part_worker_gets_no_model_key() {
    for (name, value) in KEYS {
        std::env::set_var(name, value);
    }
    let tmp = tempfile::tempdir().unwrap();
    let task = tmp.path().join("task");
    std::fs::create_dir_all(task.join("whole_vessel")).unwrap();
    let execution = json!({"result": {"engineering_approved": false, "components": [
        {"id": "wheelhouse", "op": "deckhouse", "built": true, "status": "draft_guess"}]}});
    std::fs::write(task.join(parts::EXECUTION_FILE), execution.to_string()).unwrap();
    let paths = AppPaths {
        config_dir: tmp.path().join("config"),
        data_dir: tmp.path().join("data"),
        repo_root: None,
    };
    parts::review_component(&paths, &task, "wheelhouse", "marked", Some("Lower it")).unwrap();
    // A stand-in worker: it writes its environment, then refuses as the real one can.
    let seen = tmp.path().join("environment.txt");
    let script = tmp.path().join("fake-python");
    std::fs::write(
        &script,
        format!(
            "#!/bin/sh\nenv > '{}'\necho '{{\"error\":\"stopped by the test\"}}' >&2\nexit 2\n",
            seen.display()
        ),
    )
    .unwrap();
    std::fs::set_permissions(&script, std::fs::Permissions::from_mode(0o755)).unwrap();
    let python = script.to_string_lossy().into_owned();
    let worker = Worker {
        python: &python,
        source: None,
    };
    let refused = part_revise::revise_part(
        &ActionRegistry::default(),
        &paths,
        &task,
        "wheelhouse",
        &worker,
        &ModelChoice::app(),
        REVISE_STALL_PERIOD,
    )
    .unwrap_err();
    assert_eq!(refused.message, "stopped by the test");
    let environment = std::fs::read_to_string(&seen).unwrap();
    assert!(environment.contains("MARINAFRAME_PROGRESS_PATH="));
    for (name, value) in KEYS {
        assert!(!environment.contains(name), "{name} reached the worker");
        assert!(
            !environment.contains(value),
            "a key value reached the worker"
        );
    }
}
