//! The controller pins the audit implementation identity (docs/RUST_VALIDATION_MATRIX.md, row 4d).
//!
//! The pin comes from the initialize receipt. Every later receipt must repeat it and
//! `validation::ready` requires the validation contract to carry it. A worker that
//! reports a different, well-formed identity consistently must not reach review.
//!
//! Tasks run the real worker protocol, real geometry and the real native audit through
//! `tests/rust_audit_identity_worker.py`, which only adds identity faults.
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
use std::sync::{Mutex, MutexGuard, OnceLock};
use types::*;

/// A well-formed identity that is not the real one.
const OTHER_IDENTITY: &str = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef";

fn repository() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .unwrap()
        .to_path_buf()
}

/// Python with the project's dependencies: MARINAFRAME_TEST_PYTHON, the local .venv, or python3.
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
    repository().join("tests/rust_audit_identity_worker.py")
}

/// Tests run one at a time: see the note on `SERIAL` in validation_matrix.rs.
static SERIAL: Mutex<()> = Mutex::new(());

fn serial() -> MutexGuard<'static, ()> {
    SERIAL.lock().unwrap_or_else(|e| e.into_inner())
}

struct Fixture {
    directory: tempfile::TempDir,
    store: store::Store,
}

impl Fixture {
    fn mode(&self, mode: Value) {
        util::atomic_json(&self.directory.path().join("audit-mode.json"), &mode, true).unwrap();
    }
    fn reopen(self) -> Fixture {
        let task = self.directory.path().join("task");
        let Fixture { directory, store } = self;
        drop(store);
        Fixture {
            store: store::Store::open(&task).unwrap(),
            directory,
        }
    }
    fn pin(&self) -> String {
        self.store
            .state
            .audit_implementation_sha256
            .clone()
            .expect("the task has an audit pin")
    }
}

fn decision(tool: &str, arguments: Value) -> Decision {
    serde_json::from_value(
        json!({"tool": tool, "arguments": arguments, "reason": "Audit identity regression."}),
    )
    .unwrap()
}

fn try_decide(store: &mut store::Store, tool: &str, arguments: Value) -> util::Result<bool> {
    controller::execute_decision(store, decision(tool, arguments), "deterministic_policy")
}

fn decide(store: &mut store::Store, tool: &str, arguments: Value) {
    if let Err(error) = try_decide(store, tool, arguments) {
        panic!("{tool} failed: {error}; {}", store.state.last_observation);
    }
}

fn finish(store: &mut store::Store) -> util::Result<bool> {
    try_decide(
        store,
        "finish",
        json!({"outcome": "candidate_ready_for_review", "summary": "Review this candidate."}),
    )
}

/// Build the template task. `omit_identity` makes the initialize worker report no audit
/// identity, like a worker that predates the pin: the task then has no pin.
fn build_template(omit_identity: bool) -> tempfile::TempDir {
    let directory = tempfile::tempdir().unwrap();
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
    if omit_identity {
        util::atomic_json(
            &directory.path().join("audit-mode.json"),
            &json!({"omit_audit_identity": true}),
            true,
        )
        .unwrap();
    }
    let config = Config {
        worker_python: wrapper.to_string_lossy().into_owned(),
        worker_source: Some(repository().join("src").to_string_lossy().into_owned()),
        source_spec: source.join("spec.json").to_string_lossy().into_owned(),
        policy: Policy::Deterministic,
        limits: OperationalLimits::default(),
        provider_transfer_authorized: false,
        authorization_basis: "Audit identity fixture; no transfer".into(),
        model: GO_MODEL.into(),
        binary_sha256: util::file_hash(&std::env::current_exe().unwrap()).unwrap(),
        on_ambiguity: OnAmbiguity::Abstain,
    };
    let task = directory.path().join("task");
    let mut store = store::Store::create(&task, controller::new_state(config)).unwrap();
    assert!(
        controller::initialize(&mut store).unwrap(),
        "initialisation failed"
    );
    // Inspect, select and build; the deterministic finish path needs no render.
    loop {
        let next = controller::deterministic_decision(&store).unwrap();
        if ["render_candidate", "validate_candidate", "finish"].contains(&next.tool.as_str()) {
            break;
        }
        let tool = next.tool.clone();
        decide(&mut store, &tool, next.arguments);
        assert_eq!(store.state.last_observation["ok"], true, "{tool} failed");
    }
    if omit_identity {
        // The omission was only for initialization; later receipts report it again.
        std::fs::remove_file(directory.path().join("audit-mode.json")).unwrap();
    }
    drop(store);
    directory
}

static PINNED: OnceLock<tempfile::TempDir> = OnceLock::new();
static UNPINNED: OnceLock<tempfile::TempDir> = OnceLock::new();

/// A private copy of a built, not yet validated task.
fn fixture(unpinned: bool) -> Fixture {
    let template = if unpinned {
        UNPINNED.get_or_init(|| build_template(true)).path()
    } else {
        PINNED.get_or_init(|| build_template(false)).path()
    };
    let directory = tempfile::tempdir().unwrap();
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

fn assert_not_review_ready(fixture: &Fixture) {
    assert!(!fixture
        .store
        .events
        .iter()
        .any(|e| e.kind == "candidate_ready_for_human_review"));
    assert_ne!(fixture.store.state.status, Status::AwaitingHumanReview);
}

fn assert_refused(outcome: util::Result<bool>, code: &str) {
    assert_eq!(
        outcome.expect_err("the worker receipt must be refused"),
        code
    );
}

// ------------------------------------------------------------------ tests

#[test]
#[ignore = "real CAD (slow): run with make test-full"]
fn unchanged_identity_is_pinned_at_initialize_and_finalizes() {
    let _serial = serial();
    let mut fixture = fixture(false);
    let pin = fixture.pin();
    assert!(util::valid_hash(&pin));
    decide(&mut fixture.store, "validate_candidate", json!({}));
    assert_eq!(fixture.store.state.last_observation["ok"], true);
    finish(&mut fixture.store).unwrap();
    assert_eq!(fixture.store.state.status, Status::AwaitingHumanReview);
    assert_eq!(
        fixture.store.state.domain["validation"]["contract"]["binding"]
            ["audit_implementation_sha256"],
        pin.as_str(),
        "the contract carries the pinned identity"
    );
    assert_eq!(fixture.pin(), pin, "the pin never moves");
    // A new controller process reads the pin from the ledger and verifies the task.
    let fixture = fixture.reopen();
    assert_eq!(fixture.pin(), pin);
    fixture.store.verify(false).unwrap();
}

#[test]
#[ignore = "real CAD (slow): run with make test-full"]
fn consistent_but_different_audit_identity_cannot_reach_review() {
    let _serial = serial();
    let mut fixture = fixture(false);
    // Result, contract and context all name another implementation, consistently.
    fixture.mode(json!({"consistent_audit_identity": OTHER_IDENTITY}));
    assert_refused(
        try_decide(&mut fixture.store, "validate_candidate", json!({})),
        "audit_implementation_changed",
    );
    assert_not_review_ready(&fixture);
    assert_eq!(fixture.pin().len(), 64);
    assert_ne!(fixture.pin(), OTHER_IDENTITY);
}

#[test]
#[ignore = "real CAD (slow): run with make test-full"]
fn consistent_different_identity_fails_the_finalization_predicate_itself() {
    let _serial = serial();
    // The receipt check is skipped here: the validated evidence is honest and only
    // the pin the predicate receives is different, as if the worker had lied from the start.
    let mut fixture = fixture(false);
    let pin = fixture.pin();
    decide(&mut fixture.store, "validate_candidate", json!({}));
    let observation = fixture.store.state.last_observation.clone();
    let domain = fixture.store.state.domain.clone();
    let context = observation["validation_context"].clone();
    let root = fixture.directory.path().join("task");
    validation::ready(&root, &observation, &domain, &context, Some(&pin))
        .expect("the honest evidence is ready under the real pin");
    assert_eq!(
        validation::ready(&root, &observation, &domain, &context, Some(OTHER_IDENTITY))
            .unwrap_err(),
        "audit_implementation_mismatch"
    );
    assert_eq!(
        validation::ready(&root, &observation, &domain, &context, None).unwrap_err(),
        "audit_implementation_unpinned"
    );
}

#[test]
#[ignore = "real CAD (slow): run with make test-full"]
fn result_identity_alone_changing_is_refused() {
    let _serial = serial();
    // The contract is honest; only the identity the worker reports in its result differs.
    let mut fixture = fixture(false);
    fixture.mode(json!({"report_audit_identity": OTHER_IDENTITY}));
    assert_refused(
        try_decide(&mut fixture.store, "validate_candidate", json!({})),
        "audit_implementation_changed",
    );
    assert_not_review_ready(&fixture);
}

#[test]
#[ignore = "real CAD (slow): run with make test-full"]
fn dropping_the_identity_after_the_pin_is_refused() {
    let _serial = serial();
    let mut fixture = fixture(false);
    fixture.mode(json!({"omit_audit_identity": true}));
    assert_refused(
        try_decide(&mut fixture.store, "validate_candidate", json!({})),
        "audit_implementation_missing",
    );
    assert_not_review_ready(&fixture);
}

#[test]
#[ignore = "real CAD (slow): run with make test-full"]
fn changed_worker_implementation_mid_task_is_refused() {
    let _serial = serial();
    let mut fixture = fixture(false);
    let pinned_worker = fixture.store.state.worker_implementation_sha256.clone();
    assert!(pinned_worker.is_some());
    fixture.mode(json!({"envelope_worker_identity": OTHER_IDENTITY}));
    assert_refused(
        try_decide(&mut fixture.store, "validate_candidate", json!({})),
        "worker_implementation_changed",
    );
    assert_eq!(
        fixture.store.state.worker_implementation_sha256,
        pinned_worker
    );
    assert_not_review_ready(&fixture);
}

#[test]
#[ignore = "real CAD (slow): run with make test-full"]
fn task_without_a_pin_fails_closed_at_finalization() {
    let _serial = serial();
    // The initialize worker reported no audit identity, as an old worker would. Later
    // honest receipts do not create a pin, because the worker would then choose it.
    let mut fixture = fixture(true);
    assert_eq!(fixture.store.state.audit_implementation_sha256, None);
    decide(&mut fixture.store, "validate_candidate", json!({}));
    assert_eq!(fixture.store.state.last_observation["ok"], true);
    assert_eq!(fixture.store.state.audit_implementation_sha256, None);
    finish(&mut fixture.store).unwrap();
    assert_eq!(fixture.store.state.status, Status::ValidationFailed);
    assert_eq!(
        fixture.store.state.termination_reason.as_deref(),
        Some("audit_implementation_unpinned")
    );
    assert_not_review_ready(&fixture);
}

#[test]
#[ignore = "real CAD (slow): run with make test-full"]
fn old_state_without_the_field_reads_and_serializes_unchanged() {
    let state = controller::new_state(Config {
        worker_python: "/not/executed".into(),
        worker_source: None,
        source_spec: "/not/used".into(),
        policy: Policy::Deterministic,
        limits: OperationalLimits::default(),
        provider_transfer_authorized: false,
        authorization_basis: String::new(),
        model: GO_MODEL.into(),
        binary_sha256: "a".repeat(64),
        on_ambiguity: OnAmbiguity::Abstain,
    });
    let encoded = serde_json::to_value(&state).unwrap();
    assert!(
        encoded.get("audit_implementation_sha256").is_none(),
        "an absent pin is not written, so old ledger hashes stay valid"
    );
    let old: State = serde_json::from_value(encoded.clone()).unwrap();
    old.validate().unwrap();
    assert_eq!(serde_json::to_value(&old).unwrap(), encoded);
    let mut pinned = state;
    pinned.audit_implementation_sha256 = Some("not-a-hash".into());
    assert_eq!(pinned.validate().unwrap_err(), "invalid_state_hash");
}
