//! Multi-piece stations through the controller: a compound of region solids
//! reaches human review only through the v2 region audit.
//!
//! `tests/rust_region_worker.py` runs the real `rust_worker` and real
//! `DomainTools` on `tests/region_fixture.py` (three stations, each a bulb, a
//! hull and a skeg; four solids). The deterministic policy inspects the
//! declared pieces, builds, renders and validates. The tests then show that
//! the Rust predicate binds the audit contract version and the engine's
//! solids to the run: a v1-shaped claim or another solid inventory is refused.
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
    repository().join("tests/rust_region_worker.py")
}

fn config(directory: &Path) -> Config {
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
        authorization_basis: "Region pipeline fixture; no transfer".into(),
        model: GO_MODEL.into(),
        fallback_models: vec![],
        inspection_workers: None,
        binary_sha256: util::file_hash(&std::env::current_exe().unwrap()).unwrap(),
        on_ambiguity: OnAmbiguity::Abstain,
    }
}

/// One deterministic run, shared by the tests; each test only reads it.
static REVIEWED: OnceLock<(tempfile::TempDir, Value, Value, String)> = OnceLock::new();

fn reviewed() -> &'static (tempfile::TempDir, Value, Value, String) {
    REVIEWED.get_or_init(|| {
        let directory = tempfile::tempdir().unwrap();
        let mut store = store::Store::create(
            &directory.path().join("task"),
            controller::new_state(config(directory.path())),
        )
        .unwrap();
        assert!(controller::initialize(&mut store).unwrap());
        controller::run_loop(&mut store, Some(40)).unwrap();
        assert_eq!(
            store.state.status,
            Status::AwaitingHumanReview,
            "{:?} {}",
            store.state.termination_reason,
            store.state.last_observation
        );
        let observation = store.state.last_observation.clone();
        let domain = store.state.domain.clone();
        let pin = store.state.audit_implementation_sha256.clone().unwrap();
        drop(store);
        (directory, observation, domain, pin)
    })
}

fn ready(change: impl FnOnce(&mut Value, &mut Value)) -> Result<(), String> {
    let (directory, observation, domain, pin) = reviewed();
    let mut observation = observation.clone();
    let mut context = observation["validation_context"].clone();
    change(&mut observation, &mut context);
    validation::ready(
        &directory.path().join("task"),
        &observation,
        domain,
        &context,
        Some(pin),
    )
    .map(|_| ())
    .map_err(|e| e.to_string())
}

#[test]
#[ignore = "real CAD (slow): run with make test-full"]
fn region_compound_reaches_review_through_the_v2_audit() {
    let (_, observation, _, _) = reviewed();
    let validation = &observation["validation"];
    assert_eq!(
        validation["contract"]["audit_contract_version"],
        "step_source_regions_v2"
    );
    assert_eq!(validation["contract"]["outcome"], "passed");
    assert_eq!(validation["geometry_audit"]["solid_count"], 4);
    assert_eq!(
        observation["validation_context"]["regions"]["solid_count"],
        4
    );
    ready(|_, _| {}).expect("the honest region evidence is ready for review");
}

#[test]
#[ignore = "real CAD (slow): run with make test-full"]
fn region_run_without_its_region_context_is_refused() {
    // Without "regions" the context claims a single-solid (v1) run.
    let refused = ready(|_, context| {
        context.as_object_mut().unwrap().remove("regions");
    })
    .unwrap_err();
    assert_eq!(refused, "audit_contract_version_not_current_run");
}

#[test]
#[ignore = "real CAD (slow): run with make test-full"]
fn region_context_with_another_solid_inventory_is_refused() {
    let refused = ready(|_, context| {
        context["regions"]["solid_volumes_m3"][0] = json!(1.0);
    })
    .unwrap_err();
    assert_eq!(refused, "context_regions_not_current_run");
}

#[test]
#[ignore = "real CAD (slow): run with make test-full"]
fn region_contract_claimed_as_v1_is_refused() {
    let refused = ready(|observation, _| {
        observation["validation"]["contract"]["audit_contract_version"] =
            json!("step_source_sections_v1");
    })
    .unwrap_err();
    assert_eq!(refused, "audit_contract_version_not_current_run");
}
