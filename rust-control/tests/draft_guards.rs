//! Draft guards: a best-effort draft is never review-ready while a guess is open.
//!
//! Fixtures use real geometry. `tests/rust_draft_worker.py` runs the real
//! `rust_worker` and real `DomainTools` on a drawing whose section s0 has two
//! lines (`tests/draft_fixture.py`). The deterministic policy with
//! `on_ambiguity = draft` selects s1 and s2, guesses s0 and builds a real draft
//! STEP. Each test copies that task and then tries to reach review readiness
//! through the finish path, the cache, a restart, a forged ledger, a forged
//! guess list or a permissive envelope. The last test resolves the guess as an
//! operator and shows that the ordinary verified path then runs unchanged.
use marinaframe_control::controller;
use marinaframe_control::store;
use marinaframe_control::types;
use marinaframe_control::util;
use marinaframe_control::validation;

use serde_json::{json, Value};
use std::os::unix::fs::PermissionsExt;
use std::path::{Path, PathBuf};
use std::sync::OnceLock;
use types::*;

fn repository() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .unwrap()
        .to_path_buf()
}

/// Python with the project's dependencies: MARINAFRAME_TEST_PYTHON, the local
/// .venv, or python3 from PATH.
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
    repository().join("tests/rust_draft_worker.py")
}

/// The controller locks `domain/lock` twice in a row; a process forked by a
/// parallel test thread in between could hold it. Tests therefore run serially
/// (see docs/RUST_VALIDATION_MATRIX.md).
static SERIAL: std::sync::Mutex<()> = std::sync::Mutex::new(());

fn serial() -> std::sync::MutexGuard<'static, ()> {
    SERIAL.lock().unwrap_or_else(|e| e.into_inner())
}

fn config(directory: &Path, on_ambiguity: OnAmbiguity) -> Config {
    let wrapper = directory.join("worker-python");
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
    let source = directory.join("source");
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
    Config {
        worker_python: wrapper.to_string_lossy().into_owned(),
        worker_source: Some(repository().join("src").to_string_lossy().into_owned()),
        source_spec: source.join("spec.json").to_string_lossy().into_owned(),
        policy: Policy::Deterministic,
        limits: OperationalLimits::default(),
        provider_transfer_authorized: false,
        authorization_basis: "Draft guard fixture; no transfer".into(),
        model: GO_MODEL.into(),
        fallback_models: vec![],
        inspection_workers: None,
        binary_sha256: util::file_hash(&std::env::current_exe().unwrap()).unwrap(),
        on_ambiguity,
    }
}

/// A fresh task run by the deterministic policy until it stops.
fn run_deterministic(directory: &Path, on_ambiguity: OnAmbiguity) -> store::Store {
    let config = config(directory, on_ambiguity);
    let mut store =
        store::Store::create(&directory.join("task"), controller::new_state(config)).unwrap();
    assert!(controller::initialize(&mut store).unwrap());
    controller::run_loop(&mut store, Some(40)).unwrap();
    store
}

static DRAFT_BUILT: OnceLock<tempfile::TempDir> = OnceLock::new();

fn draft_template() -> &'static Path {
    DRAFT_BUILT
        .get_or_init(|| {
            let directory = tempfile::tempdir().unwrap();
            let store = run_deterministic(directory.path(), OnAmbiguity::Draft);
            assert_eq!(
                store.state.status,
                Status::DraftNotVerified,
                "{:?} {}",
                store.state.termination_reason,
                store.state.last_observation
            );
            drop(store); // release the controller lock before copies are opened
            directory
        })
        .path()
}

struct Fixture {
    directory: tempfile::TempDir,
    store: store::Store,
}

impl Fixture {
    fn task(&self) -> PathBuf {
        self.directory.path().join("task")
    }
    /// Restart: release the controller lock and open the task again from disk.
    fn reopen(self) -> Self {
        let Fixture { directory, store } = self;
        drop(store);
        let store = store::Store::open(&directory.path().join("task")).unwrap();
        Fixture { directory, store }
    }
    fn worker_calls(&self, operation: &str) -> usize {
        self.store
            .events
            .iter()
            .filter(|e| e.kind == "worker_intent" && e.payload["operation"] == operation)
            .count()
    }
}

/// A private copy of the deterministic draft task. Its configuration still
/// names the template's worker wrapper and drawing, which stay unchanged.
fn draft_fixture() -> Fixture {
    let directory = tempfile::tempdir().unwrap();
    let copied = std::process::Command::new("cp")
        .arg("-Rp")
        .arg(draft_template().join("task"))
        .arg(directory.path().join("task"))
        .status()
        .unwrap();
    assert!(copied.success(), "prepared task copy failed");
    let store = store::Store::open(&directory.path().join("task")).unwrap();
    Fixture { directory, store }
}

fn decision(tool: &str, arguments: Value) -> Decision {
    serde_json::from_value(
        json!({"tool": tool, "arguments": arguments, "reason": "Draft guard regression."}),
    )
    .unwrap()
}

fn finish_for_review(store: &mut store::Store, actor: &str) -> Result<bool, String> {
    controller::execute_decision(
        store,
        decision(
            "finish",
            json!({"outcome": "candidate_ready_for_review", "summary": "Review this candidate."}),
        ),
        actor,
    )
}

fn checkpoint(task: &Path) -> Value {
    validation::domain_checkpoint(task).unwrap()
}

/// Rewrite the domain checkpoint and commit a consistent ledger event, as a
/// forger with write access to the whole task folder would.
fn forge_checkpoint(fixture: &mut Fixture, change: impl FnOnce(&mut Value)) {
    let path = fixture.task().join("domain/state.json");
    let mut state = checkpoint(&fixture.task());
    change(&mut state);
    util::atomic_json(&path, &state, true).unwrap();
    fixture.store.state.domain_checkpoint_sha256 = Some(util::file_hash(&path).unwrap());
    fixture
        .store
        .append("forged_checkpoint", json!({}))
        .unwrap();
}

// ------------------------------------------------------------------ tests

#[test]
#[ignore = "real CAD (slow): run with make test-full"]
fn deterministic_policy_builds_a_tagged_draft_instead_of_abstaining() {
    let _serial = serial();
    let fixture = draft_fixture();
    let state = &fixture.store.state;
    assert_eq!(state.status, Status::DraftNotVerified);
    assert_eq!(
        state.termination_reason.as_deref(),
        Some("draft_built_with_open_guesses")
    );
    assert!(!state.engineering_approved);
    let guesses = validation::open_guesses(&checkpoint(&fixture.task()))
        .unwrap()
        .to_vec();
    assert_eq!(guesses.len(), 1, "{guesses:?}");
    assert_eq!(guesses[0]["section_id"], "s0");
    assert_eq!(guesses[0]["kind"], "best_candidate");
    assert!(!guesses[0]["alternatives"].as_array().unwrap().is_empty());
    assert_eq!(state.domain["open_guesses"], json!(guesses));
    let built = fixture
        .store
        .events
        .iter()
        .find(|e| e.kind == "draft_built")
        .expect("draft_built event");
    assert_eq!(built.payload["guesses"], json!(guesses));
    assert_eq!(built.payload["verified"], false);
    let candidate = &state.domain["current_candidate"];
    assert_eq!(candidate["draft"], true);
    let run = fixture.task().join(candidate["path"].as_str().unwrap());
    assert!(run.join("model-draft.step").is_file());
    assert!(run.join("model-draft.stl").is_file());
    assert!(!run.join("model.step").exists());
    let record = util::read_json(&run.join("result.json"), 32 * 1024 * 1024).unwrap();
    assert_eq!(record["draft"]["status"], "draft_not_verified");
    assert_eq!(record["draft"]["guesses"], json!(guesses));
    assert!(record["identity"]["draft_sha256"].is_string());
    // The draft task itself is consistent; it is just not review-ready.
    assert_eq!(fixture.store.verify(false).unwrap()["valid"], true);

    // Control: the same drawing with the abstain policy declines.
    let directory = tempfile::tempdir().unwrap();
    let abstained = run_deterministic(directory.path(), OnAmbiguity::Abstain);
    assert_eq!(abstained.state.status, Status::Abstained);
    assert!(abstained.state.domain["current_candidate"].is_null());
}

#[test]
#[ignore = "real CAD (slow): run with make test-full"]
fn finish_on_a_draft_never_reaches_review_cached_repeated_or_after_restart() {
    let _serial = serial();
    // At most three identical finishes: a fourth trips the controller's
    // repeated-action guard (no_progress), which is also not review-ready.
    let mut fixture = draft_fixture();
    assert_eq!(
        finish_for_review(&mut fixture.store, "deterministic_policy"),
        Ok(false)
    );
    assert_eq!(fixture.store.state.status, Status::DraftNotVerified);
    assert_eq!(
        fixture.store.state.termination_reason.as_deref(),
        Some("open_guesses_block_review")
    );
    // The finish path never asks the worker to validate a draft.
    assert_eq!(fixture.worker_calls("validate_candidate"), 0);
    // An explicit validation is refused by the worker and caches nothing.
    controller::execute_decision(
        &mut fixture.store,
        decision("validate_candidate", json!({})),
        "human_operator",
    )
    .unwrap();
    assert_eq!(fixture.store.state.last_observation["ok"], false);
    assert!(fixture.store.state.domain["validation"].is_null());
    assert_eq!(
        finish_for_review(&mut fixture.store, "human_operator"),
        Ok(false)
    );
    assert_eq!(fixture.store.state.status, Status::DraftNotVerified);
    // Restart: the reopened task is still a draft, and resume does not continue it.
    let mut fixture = fixture.reopen();
    assert_eq!(fixture.store.state.status, Status::DraftNotVerified);
    assert_eq!(
        controller::resume(&mut fixture.store, false, false, None).unwrap_err(),
        "terminal_task_requires_explicit_source_backed_intervention"
    );
    assert_eq!(
        finish_for_review(&mut fixture.store, "human_operator"),
        Ok(false)
    );
    assert_eq!(fixture.store.state.status, Status::DraftNotVerified);
    assert!(fixture
        .store
        .events
        .iter()
        .all(|e| e.kind != "candidate_ready_for_human_review"));
}

#[test]
#[ignore = "real CAD (slow): run with make test-full"]
fn permissive_envelope_cannot_make_a_draft_ready() {
    let _serial = serial();
    let mut fixture = draft_fixture();
    let task = fixture.task();
    let pin = fixture.store.state.audit_implementation_sha256.clone();
    // An envelope that claims a passed validation, with any context.
    let mut envelope = fixture.store.state.last_observation.clone();
    envelope["ok"] = json!(true);
    envelope["status"] = json!("validated_review_required");
    let domain = fixture.store.state.domain.clone();
    let ready = |domain: &Value| {
        validation::ready(&task, &envelope, domain, &json!({}), pin.as_deref()).unwrap_err()
    };
    assert_eq!(ready(&domain), "draft_guesses_open");
    // Same, through the legacy (unpinned) path that Store::verify can take.
    assert_eq!(
        validation::ready_legacy_unpinned(&task, &envelope, &domain, &json!({})).unwrap_err(),
        "draft_guesses_open"
    );
    // The guesses removed from the checkpoint: the candidate is still a draft.
    forge_checkpoint(&mut fixture, |state| {
        state.as_object_mut().unwrap().remove("guesses");
    });
    assert_eq!(ready(&domain), "draft_candidate_not_verifiable");
    // The candidate's draft flag also removed: its run record is still a draft.
    let mut unflagged = domain.clone();
    unflagged["current_candidate"]["draft"] = json!(false);
    assert_eq!(ready(&unflagged), "draft_build_not_verifiable");
}

#[test]
#[ignore = "real CAD (slow): run with make test-full"]
fn forged_review_status_fails_store_verify() {
    let _serial = serial();
    let mut fixture = draft_fixture();
    fixture.store.state.status = Status::AwaitingHumanReview;
    fixture.store.state.termination_reason = Some("forged".into());
    fixture
        .store
        .append("candidate_ready_for_human_review", json!({"forged": true}))
        .unwrap();
    let fixture = fixture.reopen();
    assert_eq!(
        fixture.store.verify(false).unwrap_err(),
        "draft_guesses_open"
    );
}

#[test]
#[ignore = "real CAD (slow): run with make test-full"]
fn edited_or_removed_guesses_are_rejected() {
    let _serial = serial();
    // Edited: a guess reason rewritten in the checkpoint (consistent ledger).
    let mut fixture = draft_fixture();
    forge_checkpoint(&mut fixture, |state| {
        state["guesses"][0]["reason"] = json!("Confirmed by a person.");
    });
    assert_eq!(
        fixture.store.verify(false).unwrap_err(),
        "draft_guess_description_mismatch"
    );
    // Removed: the guess deleted from the checkpoint and from the description.
    let mut fixture = draft_fixture();
    fixture.store.state.domain["open_guesses"] = json!([]);
    forge_checkpoint(&mut fixture, |state| {
        state["guesses"] = json!([]);
    });
    assert_eq!(
        fixture.store.verify(false).unwrap_err(),
        "domain_identity_or_review_boundary"
    );
}

#[test]
#[ignore = "real CAD (slow): run with make test-full"]
fn worker_forged_guess_is_rejected_at_the_receipt() {
    let _serial = serial();
    let directory = tempfile::tempdir().unwrap();
    util::atomic_json(
        &directory.path().join("draft-mode.json"),
        &json!({"forge_guess": true}),
        true,
    )
    .unwrap();
    let store = run_deterministic(directory.path(), OnAmbiguity::Draft);
    assert_eq!(store.state.status, Status::Blocked);
    assert_eq!(
        store.state.termination_reason.as_deref(),
        Some("draft_guess_not_in_catalog")
    );
    assert!(store.events.iter().all(|e| e.kind != "draft_built"));
}

#[test]
#[ignore = "real CAD (slow): run with make test-full"]
fn a_policy_cannot_confirm_its_own_guess() {
    let _serial = serial();
    let mut fixture = draft_fixture();
    let guess = validation::open_guesses(&checkpoint(&fixture.task())).unwrap()[0].clone();
    let select = decision(
        "select_contours",
        json!({"selections": [{"section_id": guess["section_id"], "candidate_id": guess["chosen_candidate_id"]}]}),
    );
    for policy in ["deterministic_policy", "live_model"] {
        assert_eq!(
            controller::execute_decision(&mut fixture.store, select.clone(), policy).unwrap_err(),
            "guess_requires_operator_confirmation"
        );
    }
    assert_eq!(
        validation::open_guesses(&checkpoint(&fixture.task()))
            .unwrap()
            .len(),
        1
    );
}

#[test]
#[ignore = "real CAD (slow): run with make test-full"]
fn resolving_every_guess_then_follows_the_normal_verified_path() {
    let _serial = serial();
    let mut fixture = draft_fixture();
    let draft_generation = fixture.store.state.generation_id.clone().unwrap();
    let guess = validation::open_guesses(&checkpoint(&fixture.task())).unwrap()[0].clone();
    let intervention: controller::Intervention = serde_json::from_value(json!({
        "schema_version": "marinaframe.intervention.v1",
        "task_id": fixture.store.state.task_id,
        "expected_head_sha256": fixture.store.head,
        "expected_generation_id": draft_generation,
        "expected_revision_id": fixture.store.state.revision_id,
        "decision": {"tool": "select_contours", "reason": "The outer line is the hull.",
            "arguments": {"selections": [{"section_id": guess["section_id"], "candidate_id": guess["chosen_candidate_id"]}]}}
    }))
    .unwrap();
    controller::intervene(
        &mut fixture.store,
        intervention,
        "human_operator",
        "Confirmed the guessed line.",
    )
    .unwrap();
    assert_eq!(fixture.store.state.status, Status::Paused);
    let state = checkpoint(&fixture.task());
    assert!(validation::open_guesses(&state).unwrap().is_empty());
    assert_eq!(state["resolved_guesses"][0]["resolution"], "confirmed");
    assert_ne!(
        fixture.store.state.generation_id.as_deref(),
        Some(draft_generation.as_str())
    );
    controller::resume(&mut fixture.store, false, false, Some(40)).unwrap();
    assert_eq!(
        fixture.store.state.status,
        Status::AwaitingHumanReview,
        "{:?} {}",
        fixture.store.state.termination_reason,
        fixture.store.state.last_observation
    );
    let candidate = &fixture.store.state.domain["current_candidate"];
    assert_eq!(candidate["draft"], false);
    let run = fixture.task().join(candidate["path"].as_str().unwrap());
    assert!(run.join("model.step").is_file());
    assert!(!run.join("model-draft.step").exists());
    assert_eq!(fixture.store.verify(false).unwrap()["valid"], true);
    assert!(!fixture.store.state.engineering_approved);
}
