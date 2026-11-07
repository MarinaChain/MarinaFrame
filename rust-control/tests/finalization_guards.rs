//! Rust ports of the Python Harness finalization guards (0.3 cached-failure defect).
//!
//! Each test drives the real Rust finish path (`execute_decision`, the domain
//! guard, cancellation checks and `validation::ready`) over the real Python
//! worker protocol. Only the native audit is a controlled double:
//! `tests/rust_controlled_worker.py` runs `rust_worker` with
//! `ControlledValidationDomain`. No hull is measured here.
//!
//! The Python Harness deadline variants have no counterpart: the Rust
//! controller has no task wall-clock deadline.
#![allow(dead_code)]
#[path = "../src/controller.rs"]
mod controller;
#[path = "../src/provider.rs"]
mod provider;
#[path = "../src/store.rs"]
mod store;
#[path = "../src/types.rs"]
mod types;
#[path = "../src/util.rs"]
mod util;
#[path = "../src/validation.rs"]
mod validation;
#[path = "../src/worker.rs"]
mod worker;

use serde_json::{json, Value};
use std::os::unix::fs::PermissionsExt;
use std::path::{Path, PathBuf};
use std::sync::Mutex;
use types::*;

/// Audit error that passes trace fidelity (limit 0.0011 m in the fixture).
const PASSING_MAXIMUM_M: f64 = 0.0005;
/// Audit error that fails trace fidelity.
const FAILING_MAXIMUM_M: f64 = 0.01;

/// The finalization hook and its plan are process-global, so tests run one at a time.
static SERIAL: Mutex<()> = Mutex::new(());
static PLAN: Mutex<Option<Plan>> = Mutex::new(None);
static OBSERVED: Mutex<Vec<Value>> = Mutex::new(Vec::new());

#[derive(Clone, Copy)]
enum Action {
    SelectRaceCandidate,
    Cancel,
}

#[derive(Clone, Copy)]
struct Plan {
    point: &'static str,
    action: Action,
}

fn repository() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .unwrap()
        .to_path_buf()
}

/// Python with the project's dependencies: MARINAFRAME_TEST_PYTHON, the local
/// .venv, or python3 from PATH (CI installs the locked wheels globally).
fn python() -> String {
    if let Ok(path) = std::env::var("MARINAFRAME_TEST_PYTHON") {
        return path;
    }
    let venv = repository().join(".venv/bin/python");
    if venv.is_file() {
        return venv.to_string_lossy().into_owned();
    }
    "python3".into()
}

fn shim() -> PathBuf {
    repository().join("tests/rust_controlled_worker.py")
}

fn hook(task: &Path, point: &str) {
    let plan = *PLAN.lock().unwrap();
    let Some(plan) = plan.filter(|p| p.point == point) else {
        return;
    };
    match plan.action {
        Action::Cancel => {
            std::fs::write(task.join("cancel.request"), b"controlled cancellation\n").unwrap()
        }
        Action::SelectRaceCandidate => {
            let output = std::process::Command::new(python())
                .arg(shim())
                .arg("select-race")
                .arg(task)
                .env("PYTHONPATH", repository().join("src"))
                .output()
                .unwrap();
            let observed: Value = serde_json::from_slice(&output.stdout).unwrap_or_else(|_| {
                panic!(
                    "select-race failed: {}",
                    String::from_utf8_lossy(&output.stderr)
                )
            });
            OBSERVED.lock().unwrap().push(observed);
        }
    }
}

struct Fixture {
    directory: tempfile::TempDir,
    store: store::Store,
}

impl Fixture {
    fn task(&self) -> PathBuf {
        self.directory.path().join("task")
    }
    fn audits(&self) -> usize {
        std::fs::read_to_string(self.directory.path().join("controlled-audits.log"))
            .map(|log| log.lines().count())
            .unwrap_or(0)
    }
    fn events(&self, kind: &str) -> usize {
        self.store.events.iter().filter(|e| e.kind == kind).count()
    }
}

fn write_mode(directory: &Path, mode: Value) {
    util::atomic_json(&directory.join("controlled-mode.json"), &mode, true).unwrap();
}

/// One real prepared task (inspected, selected and natively built), made once
/// per test run and copied for each test. A static is never dropped, so this
/// one temporary directory stays behind after the run.
static TEMPLATE: std::sync::OnceLock<tempfile::TempDir> = std::sync::OnceLock::new();

/// A copy of the prepared task; its worker calls use `mode`.
fn fixture(mode: Value) -> Fixture {
    let template = TEMPLATE.get_or_init(prepare_template).path();
    let directory = tempfile::tempdir().unwrap();
    write_mode(directory.path(), mode);
    let copied = std::process::Command::new("cp")
        .arg("-Rp")
        .arg(template.join("task"))
        .arg(directory.path().join("task"))
        .status()
        .unwrap();
    assert!(copied.success(), "prepared task copy failed");
    let store = store::Store::open(&directory.path().join("task")).unwrap();
    Fixture { directory, store }
}

fn prepare_template() -> tempfile::TempDir {
    let directory = tempfile::tempdir().unwrap();
    write_mode(directory.path(), json!({"maximum": PASSING_MAXIMUM_M}));
    let wrapper = directory.path().join("worker-python");
    std::fs::write(
        &wrapper,
        format!(
            "#!/bin/sh\nexec '{}' '{}' \"$@\"\n",
            python(),
            shim().display()
        ),
    )
    .unwrap();
    std::fs::set_permissions(&wrapper, std::fs::Permissions::from_mode(0o700)).unwrap();
    let source = directory.path().join("source");
    let made = std::process::Command::new(python())
        .arg(shim())
        .arg("make-drawing")
        .arg(&source)
        .env("PYTHONPATH", repository().join("src"))
        .output()
        .unwrap();
    assert!(
        made.status.success(),
        "{}",
        String::from_utf8_lossy(&made.stderr)
    );
    let config = Config {
        worker_python: wrapper.to_string_lossy().into_owned(),
        worker_source: Some(repository().join("src").to_string_lossy().into_owned()),
        source_spec: source.join("spec.json").to_string_lossy().into_owned(),
        policy: Policy::Deterministic,
        limits: OperationalLimits::default(),
        provider_transfer_authorized: false,
        authorization_basis: "Controlled finalization-guard fixture; no transfer".into(),
        model: GO_MODEL.into(),
        binary_sha256: util::file_hash(&std::env::current_exe().unwrap()).unwrap(),
        on_ambiguity: OnAmbiguity::Abstain,
    };
    let task = directory.path().join("task");
    let mut store = store::Store::create(&task, controller::new_state(config)).unwrap();
    assert!(
        controller::initialize(&mut store).unwrap(),
        "controlled initialisation failed"
    );
    let mut fixture = Fixture { directory, store };
    // Real inspection, selection and native build. Renders are skipped: the
    // deterministic finish path does not require them, and they are slow.
    loop {
        let next = controller::deterministic_decision(&fixture.store).unwrap();
        if ["render_candidate", "validate_candidate", "finish"].contains(&next.tool.as_str()) {
            break;
        }
        let tool = next.tool.clone();
        decide(&mut fixture, &tool, next.arguments);
        assert_eq!(
            fixture.store.state.last_observation["ok"], true,
            "{tool} failed"
        );
    }
    assert_eq!(fixture.audits(), 0);
    let Fixture { directory, store } = fixture;
    drop(store); // release the controller lock before copies are opened
    directory
}

fn decide(fixture: &mut Fixture, tool: &str, arguments: Value) {
    let decision: Decision = serde_json::from_value(
        json!({"tool": tool, "arguments": arguments, "reason": "Controlled finalization regression."}),
    )
    .unwrap();
    if let Err(error) =
        controller::execute_decision(&mut fixture.store, decision, "deterministic_policy")
    {
        panic!(
            "{tool} decision failed: {error}; observation: {}",
            fixture.store.state.last_observation
        );
    }
}

fn validate(fixture: &mut Fixture) {
    decide(fixture, "validate_candidate", json!({}));
}

fn finish(fixture: &mut Fixture) {
    decide(
        fixture,
        "finish",
        json!({"outcome": "candidate_ready_for_review", "summary": "Review this candidate."}),
    );
}

fn assert_not_review_ready(fixture: &Fixture) {
    assert_eq!(fixture.events("candidate_ready_for_human_review"), 0);
    assert_ne!(fixture.store.state.status, Status::AwaitingHumanReview);
}

fn with_plan(plan: Option<Plan>) {
    *PLAN.lock().unwrap() = plan;
    OBSERVED.lock().unwrap().clear();
    *controller::FINALIZATION_HOOK.lock().unwrap() =
        plan.map(|_| hook as controller::FinalizationHook);
}

#[test]
#[ignore = "real CAD (slow): run with make test-full"]
fn failed_audit_stays_failed_when_cached_and_finished() {
    let _serial = SERIAL.lock().unwrap_or_else(|e| e.into_inner());
    with_plan(None);
    let mut fixture = fixture(json!({"maximum": FAILING_MAXIMUM_M}));
    validate(&mut fixture);
    assert_eq!(fixture.store.state.last_observation["ok"], false);
    finish(&mut fixture);
    assert_eq!(
        fixture.audits(),
        1,
        "finish must reuse the cached failed audit"
    );
    assert_eq!(fixture.store.state.status, Status::ValidationFailed);
    assert_not_review_ready(&fixture);
}

#[test]
#[ignore = "real CAD (slow): run with make test-full"]
fn restart_finalization_does_not_promote_failed_cache() {
    let _serial = SERIAL.lock().unwrap_or_else(|e| e.into_inner());
    with_plan(None);
    let mut fixture = fixture(json!({"maximum": FAILING_MAXIMUM_M}));
    validate(&mut fixture);
    let task = fixture.task();
    let Fixture { directory, store } = fixture;
    drop(store); // releases the controller lock, as a process exit would
                 // A fresh audit would now pass. The cached failure must still govern.
    write_mode(directory.path(), json!({"maximum": 0.0}));
    let mut fixture = Fixture {
        store: store::Store::open(&task).unwrap(),
        directory,
    };
    finish(&mut fixture);
    assert_eq!(fixture.audits(), 1, "restart must not run a new audit");
    assert_eq!(fixture.store.state.status, Status::ValidationFailed);
    assert_not_review_ready(&fixture);
}

#[test]
#[ignore = "real CAD (slow): run with make test-full"]
fn permissive_envelope_cannot_override_failed_contract() {
    let _serial = SERIAL.lock().unwrap_or_else(|e| e.into_inner());
    with_plan(None);
    let mut fixture = fixture(json!({"maximum": FAILING_MAXIMUM_M, "permissive": true}));
    validate(&mut fixture);
    assert_eq!(
        fixture.store.state.last_observation["ok"], true,
        "the fixture must present a permissive envelope"
    );
    finish(&mut fixture);
    assert_eq!(fixture.store.state.status, Status::ValidationFailed);
    assert_not_review_ready(&fixture);
}

fn selection_is_excluded_inside_finalization(point: &'static str) {
    let _serial = SERIAL.lock().unwrap_or_else(|e| e.into_inner());
    with_plan(None);
    let mut fixture = fixture(json!({"maximum": PASSING_MAXIMUM_M, "race_candidate": true}));
    validate(&mut fixture);
    assert_eq!(fixture.store.state.last_observation["ok"], true);
    let before = std::fs::read(fixture.task().join("domain/state.json")).unwrap();
    let identity = (
        fixture.store.state.generation_id.clone(),
        fixture.store.state.revision_id.clone(),
    );
    with_plan(Some(Plan {
        point,
        action: Action::SelectRaceCandidate,
    }));
    finish(&mut fixture);
    let observed = OBSERVED.lock().unwrap().clone();
    with_plan(None);
    assert_eq!(
        observed.len(),
        1,
        "the {point} interleaving was not exercised"
    );
    assert_eq!(
        observed[0]["ok"], false,
        "a selection committed during finalization"
    );
    assert_eq!(
        std::fs::read(fixture.task().join("domain/state.json")).unwrap(),
        before,
        "the domain checkpoint changed during finalization"
    );
    assert_eq!(
        (
            fixture.store.state.generation_id.clone(),
            fixture.store.state.revision_id.clone()
        ),
        identity
    );
    assert_eq!(fixture.store.state.status, Status::AwaitingHumanReview);
    assert_eq!(fixture.events("candidate_ready_for_human_review"), 1);
}

#[test]
#[ignore = "real CAD (slow): run with make test-full"]
fn selection_is_excluded_after_the_passing_predicate() {
    selection_is_excluded_inside_finalization("after_predicate");
}

#[test]
#[ignore = "real CAD (slow): run with make test-full"]
fn selection_is_excluded_until_the_review_ready_commit() {
    selection_is_excluded_inside_finalization("before_commit");
}

#[test]
#[ignore = "real CAD (slow): run with make test-full"]
fn cancellation_after_passing_predicate_prevents_review_ready_commit() {
    let _serial = SERIAL.lock().unwrap_or_else(|e| e.into_inner());
    with_plan(None);
    let mut fixture = fixture(json!({"maximum": PASSING_MAXIMUM_M}));
    validate(&mut fixture);
    assert_eq!(fixture.store.state.last_observation["ok"], true);
    with_plan(Some(Plan {
        point: "after_predicate",
        action: Action::Cancel,
    }));
    finish(&mut fixture);
    with_plan(None);
    assert_eq!(fixture.store.state.status, Status::Cancelled);
    assert_not_review_ready(&fixture);
}
