//! Rust validation and finalization matrix (see docs/RUST_VALIDATION_MATRIX.md).
//!
//! Rust owns the trust boundary: `validation::ready` must reject every stale,
//! altered, incomplete or contradictory piece of evidence by itself, without
//! relying on the Python worker's own cache checks.
//!
//! Fixtures use real geometry. `tests/rust_matrix_worker.py` runs the real
//! `rust_worker` and real `DomainTools`; no audit result is injected, so the
//! native audit re-imports the exported STEP. The passing drawing measures
//! 0.9 mm against a 1.1 mm tolerance. The failing fixture is a curved hull built
//! while the engine's CAD approximation bound is raised from 1 mm to 10 mm (see
//! the shim). Its exported STEP really deviates by about 8.5 mm, and the real,
//! unmodified audit reports the failure.
//!
//! Most tests call `validation::ready` directly on a copy of a validated task
//! and then change one thing on disk or in the observation. A few drive the real
//! controller finish path. Each prepared task is built once per test binary.
#![allow(dead_code)]
#[path = "../src/controller.rs"]
mod controller;
#[path = "../src/models.rs"]
mod models;
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
use std::sync::OnceLock;
use types::*;

const OTHER_HASH: &str = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef";

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
    repository().join("tests/rust_matrix_worker.py")
}

// ---------------------------------------------------------------- fixtures

/// Tests run one at a time. The controller takes a flock on `domain/lock` and
/// then immediately takes it again; a process spawned by another test thread in
/// between (fork before exec) would still hold the old file description and make
/// that second lock fail spuriously. A single controller process never spawns
/// concurrently with its own lock, so this is a test-harness artefact only.
static SERIAL: std::sync::Mutex<()> = std::sync::Mutex::new(());

fn serial() -> std::sync::MutexGuard<'static, ()> {
    SERIAL.lock().unwrap_or_else(|e| e.into_inner())
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
        std::fs::read_to_string(self.directory.path().join("matrix-audits.log"))
            .map(|log| log.lines().count())
            .unwrap_or(0)
    }
    fn events(&self, kind: &str) -> usize {
        self.store.events.iter().filter(|e| e.kind == kind).count()
    }
    fn mode(&self, mode: Value) {
        util::atomic_json(&self.directory.path().join("matrix-mode.json"), &mode, true).unwrap();
    }
    fn observation(&self) -> Value {
        self.store.state.last_observation.clone()
    }
}

fn decide_as(store: &mut store::Store, actor: &str, tool: &str, arguments: Value) {
    let decision: Decision = serde_json::from_value(
        json!({"tool": tool, "arguments": arguments, "reason": "Validation matrix regression."}),
    )
    .unwrap();
    if let Err(error) = controller::execute_decision(store, decision, actor) {
        panic!("{tool} failed: {error}; {}", store.state.last_observation);
    }
}

fn decide(store: &mut store::Store, tool: &str, arguments: Value) {
    decide_as(store, "deterministic_policy", tool, arguments);
}

fn validate(fixture: &mut Fixture) {
    decide(&mut fixture.store, "validate_candidate", json!({}));
}

fn finish(fixture: &mut Fixture) {
    decide(
        &mut fixture.store,
        "finish",
        json!({"outcome": "candidate_ready_for_review", "summary": "Review this candidate."}),
    );
}

/// A real task that is inspected, selected and natively built, not yet validated.
fn build_template(failing_fixture: bool) -> tempfile::TempDir {
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
    let mut made = std::process::Command::new(python());
    made.arg(shim()).arg("make-drawing").arg(&source);
    if failing_fixture {
        // A curved hull built with a loosened CAD bound: the real audit fails.
        made.arg("curved");
        util::atomic_json(
            &directory.path().join("matrix-mode.json"),
            &json!({"loose_cad_bound": true}),
            true,
        )
        .unwrap();
    }
    let made = made
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
        authorization_basis: "Validation matrix fixture; no transfer".into(),
        model: GO_MODEL.into(),
        fallback_models: vec![],
        binary_sha256: util::file_hash(&std::env::current_exe().unwrap()).unwrap(),
        on_ambiguity: OnAmbiguity::Abstain,
    };
    let task = directory.path().join("task");
    let mut store = store::Store::create(&task, controller::new_state(config)).unwrap();
    assert!(
        controller::initialize(&mut store).unwrap(),
        "initialisation failed"
    );
    // Renders are skipped: the deterministic finish path does not need them.
    loop {
        let next = controller::deterministic_decision(&store).unwrap();
        if ["render_candidate", "validate_candidate", "finish"].contains(&next.tool.as_str()) {
            break;
        }
        let tool = next.tool.clone();
        decide(&mut store, &tool, next.arguments);
        assert_eq!(store.state.last_observation["ok"], true, "{tool} failed");
    }
    drop(store); // release the controller lock before copies are opened
    directory
}

static PASSING_BUILT: OnceLock<tempfile::TempDir> = OnceLock::new();
static FAILING_BUILT: OnceLock<tempfile::TempDir> = OnceLock::new();

fn built(failing_fixture: bool) -> &'static Path {
    if failing_fixture {
        FAILING_BUILT.get_or_init(|| build_template(true)).path()
    } else {
        PASSING_BUILT.get_or_init(|| build_template(false)).path()
    }
}

fn copy_task(template: &Path) -> tempfile::TempDir {
    let directory = tempfile::tempdir().unwrap();
    let copied = std::process::Command::new("cp")
        .arg("-Rp")
        .arg(template.join("task"))
        .arg(directory.path().join("task"))
        .status()
        .unwrap();
    assert!(copied.success(), "prepared task copy failed");
    directory
}

/// A copy of a built, unvalidated task with the given worker mode.
fn fixture(failing_fixture: bool, mode: Value) -> Fixture {
    let directory = copy_task(built(failing_fixture));
    util::atomic_json(&directory.path().join("matrix-mode.json"), &mode, true).unwrap();
    let store = store::Store::open(&directory.path().join("task")).unwrap();
    Fixture { directory, store }
}

/// A validated task: the evidence `validation::ready` receives from the controller.
struct Validated {
    directory: tempfile::TempDir,
    observation: Value,
    domain: Value,
    context: Value,
    /// The audit identity the controller pinned at initialization.
    audit_pin: Option<String>,
}

impl Validated {
    fn root(&self) -> PathBuf {
        self.directory.path().join("task")
    }
}

fn validated_from(failing_fixture: bool) -> Validated {
    let mut fixture = fixture(failing_fixture, json!({}));
    validate(&mut fixture);
    let observation = fixture.observation();
    let domain = fixture.store.state.domain.clone();
    let context = observation["validation_context"].clone();
    let audit_pin = fixture.store.state.audit_implementation_sha256.clone();
    let Fixture { directory, store } = fixture;
    drop(store);
    Validated {
        directory,
        observation,
        domain,
        context,
        audit_pin,
    }
}

static PASSING: OnceLock<Validated> = OnceLock::new();
static FAILING: OnceLock<Validated> = OnceLock::new();

fn passing() -> &'static Validated {
    PASSING.get_or_init(|| validated_from(false))
}
fn failing() -> &'static Validated {
    FAILING.get_or_init(|| validated_from(true))
}

/// A private mutable copy of a validated task.
struct Copy {
    directory: tempfile::TempDir,
    observation: Value,
    domain: Value,
    context: Value,
    audit_pin: Option<String>,
}

impl Copy {
    fn of(source: &Validated) -> Copy {
        Copy {
            directory: copy_task(source.directory.path()),
            observation: source.observation.clone(),
            domain: source.domain.clone(),
            context: source.context.clone(),
            audit_pin: source.audit_pin.clone(),
        }
    }
    fn root(&self) -> PathBuf {
        self.directory.path().join("task")
    }
    fn ready(&self) -> util::Result<validation::Contract> {
        validation::ready(
            &self.root(),
            &self.observation,
            &self.domain,
            &self.context,
            self.audit_pin.as_deref(),
        )
    }
    /// Relative path of the evidence file of this kind.
    fn evidence(&self, kind: &str) -> String {
        self.observation["validation"]["contract"]["evidence"]
            .as_array()
            .unwrap()
            .iter()
            .find(|e| e["kind"] == kind)
            .unwrap_or_else(|| panic!("no {kind} evidence"))["path"]
            .as_str()
            .unwrap()
            .to_string()
    }
    fn file(&self, relative: &str) -> PathBuf {
        self.root().join(relative)
    }
    fn run_directory(&self) -> String {
        self.domain["current_candidate"]["path"]
            .as_str()
            .unwrap()
            .to_string()
    }
}

/// Replace a file's bytes. Copies keep read-only modes, so loosen them first.
fn rewrite(path: &Path, change: impl FnOnce(Vec<u8>) -> Vec<u8>) {
    let bytes = std::fs::read(path).unwrap();
    let mut mode = std::fs::metadata(path).unwrap().permissions();
    mode.set_mode(0o644);
    std::fs::set_permissions(path, mode).unwrap();
    std::fs::write(path, change(bytes)).unwrap();
}

fn append_byte(path: &Path) {
    rewrite(path, |mut bytes| {
        bytes.push(b'\n');
        bytes
    });
}

/// Change one byte and keep the file size, so only a content hash can notice.
fn flip_byte(path: &Path) {
    rewrite(path, |mut bytes| {
        let middle = bytes.len() / 2;
        bytes[middle] ^= 0x01;
        bytes
    });
}

fn edit_json(path: &Path, change: impl FnOnce(&mut Value)) {
    rewrite(path, |bytes| {
        let mut value: Value = serde_json::from_slice(&bytes).unwrap();
        change(&mut value);
        serde_json::to_vec_pretty(&value).unwrap()
    });
}

/// Set a value; a missing last key of an existing object is added.
fn set(value: &mut Value, pointer: &str, new: Value) {
    if let Some(slot) = value.pointer_mut(pointer) {
        *slot = new;
        return;
    }
    let (parent, key) = pointer.rsplit_once('/').unwrap();
    value
        .pointer_mut(parent)
        .and_then(Value::as_object_mut)
        .unwrap_or_else(|| panic!("no object at {parent}"))
        .insert(key.to_string(), new);
}

fn remove(value: &mut Value, pointer: &str) {
    let (parent, key) = pointer.rsplit_once('/').unwrap();
    value
        .pointer_mut(parent)
        .unwrap_or_else(|| panic!("no {parent}"))
        .as_object_mut()
        .unwrap()
        .remove(key)
        .unwrap_or_else(|| panic!("no {pointer}"));
}

/// Collect every mismatch so one run shows all weak spots.
#[derive(Default)]
struct Cases {
    failures: Vec<String>,
    count: usize,
}

impl Cases {
    fn expect_error(
        &mut self,
        label: &str,
        outcome: util::Result<validation::Contract>,
        code: &str,
    ) {
        self.count += 1;
        match outcome {
            Ok(_) => self
                .failures
                .push(format!("{label}: accepted (expected {code})")),
            Err(actual) if actual != code => self
                .failures
                .push(format!("{label}: rejected as {actual} (expected {code})")),
            Err(_) => (),
        }
    }
    fn finish(self) {
        assert!(self.count > 0);
        assert!(
            self.failures.is_empty(),
            "{} of {} cases wrong:\n{}",
            self.failures.len(),
            self.count,
            self.failures.join("\n")
        );
    }
}

fn assert_not_review_ready(fixture: &Fixture) {
    assert_eq!(fixture.events("candidate_ready_for_human_review"), 0);
    assert_ne!(fixture.store.state.status, Status::AwaitingHumanReview);
}

// ------------------------------------------------------ controls (baseline)

#[test]
#[ignore = "real CAD (slow): run with make test-full"]
fn control_real_passing_evidence_is_accepted_and_failing_is_not_ready() {
    let _serial = serial();
    let pass = passing();
    assert_eq!(pass.observation["ok"], true);
    let copy = Copy::of(pass);
    let contract = copy.ready().expect("the untouched real pass must be ready");
    assert_eq!(contract.outcome, validation::Check::Passed);
    assert!(contract.measurements.max_section_distance_m <= 0.0011);

    let fail = failing();
    assert_eq!(fail.observation["ok"], false);
    assert_eq!(fail.observation["status"], "validation_failed");
    let copy = Copy::of(fail);
    let contract = validation::assess(&copy.root(), &copy.observation, &copy.domain, &copy.context)
        .expect("a real failure is well-formed evidence");
    assert_eq!(contract.outcome, validation::Check::Failed);
    assert_eq!(contract.checks.trace_fidelity, validation::Check::Failed);
    assert!(contract.measurements.max_section_distance_m > 0.0011);
    assert_eq!(copy.ready().unwrap_err(), "candidate_validation_failed");
}

// ------------------------------------------- artifacts changed on disk

#[test]
#[ignore = "real CAD (slow): run with make test-full"]
fn artifact_changes_on_disk_after_validation_are_rejected() {
    let _serial = serial();
    let pass = passing();
    let mut cases = Cases::default();
    let run = Copy::of(pass).run_directory();
    let audit = Copy::of(pass).evidence("step_reimport_validation");
    let receipt = Copy::of(pass).evidence("validation_worker_receipt");
    let image = Copy::of(pass).evidence("step_section_cut_comparison");
    let state = "domain/state.json".to_string();

    type Mutation<'a> = Box<dyn Fn(&Copy) + 'a>;
    let table: Vec<(String, Mutation, &str)> = vec![
        // STEP, manifest and result of the native run.
        (
            "STEP bytes changed".into(),
            Box::new(|c| append_byte(&c.file(&format!("{run}/model.step")))),
            "native_file_changed",
        ),
        (
            "STEP byte flipped, same size".into(),
            Box::new(|c| flip_byte(&c.file(&format!("{run}/model.step")))),
            "native_file_changed",
        ),
        (
            "run result byte flipped, same size".into(),
            Box::new(|c| flip_byte(&c.file(&format!("{run}/result.json")))),
            "native_file_changed",
        ),
        (
            "STEP missing".into(),
            Box::new(|c| std::fs::remove_file(c.file(&format!("{run}/model.step"))).unwrap()),
            "safe_file",
        ),
        (
            "run result changed".into(),
            Box::new(|c| append_byte(&c.file(&format!("{run}/result.json")))),
            "native_file_changed",
        ),
        (
            "run manifest missing".into(),
            Box::new(|c| std::fs::remove_file(c.file(&format!("{run}/manifest.json"))).unwrap()),
            "safe_file",
        ),
        (
            "unlisted file added to the run".into(),
            Box::new(|c| std::fs::write(c.file(&format!("{run}/extra.bin")), b"x").unwrap()),
            "native_inventory_mismatch",
        ),
        (
            "symlink added to the run".into(),
            Box::new(|c| {
                std::os::unix::fs::symlink("model.step", c.file(&format!("{run}/alias.step")))
                    .unwrap()
            }),
            "native_symlink",
        ),
        // STEP replaced and the manifest rewritten to match: the manifest hash
        // no longer equals the hash bound by the validation contract.
        (
            "STEP and manifest replaced consistently".into(),
            Box::new(|c| {
                let step = c.file(&format!("{run}/model.step"));
                append_byte(&step);
                let (hash, size) = (
                    util::file_hash(&step).unwrap(),
                    std::fs::metadata(&step).unwrap().len(),
                );
                edit_json(&c.file(&format!("{run}/manifest.json")), |m| {
                    m["files"]["model.step"] = json!({"sha256": hash, "size_bytes": size});
                });
            }),
            "validation_native_identity",
        ),
        // Raw audit, worker receipt and comparison renders.
        (
            "raw audit changed".into(),
            Box::new(|c| append_byte(&c.file(&audit))),
            "artifact_identity_mismatch",
        ),
        (
            "raw audit missing".into(),
            Box::new(|c| std::fs::remove_file(c.file(&audit)).unwrap()),
            "safe_file",
        ),
        (
            "worker receipt changed".into(),
            Box::new(|c| append_byte(&c.file(&receipt))),
            "artifact_identity_mismatch",
        ),
        (
            "worker receipt missing".into(),
            Box::new(|c| std::fs::remove_file(c.file(&receipt)).unwrap()),
            "safe_file",
        ),
        (
            "comparison render changed".into(),
            Box::new(|c| append_byte(&c.file(&image))),
            "artifact_identity_mismatch",
        ),
        (
            "comparison render missing".into(),
            Box::new(|c| std::fs::remove_file(c.file(&image)).unwrap()),
            "safe_file",
        ),
        // Inputs captured by the domain.
        (
            "calibration changed in the captured input spec".into(),
            Box::new(|c| {
                edit_json(&c.file("domain/input/spec.json"), |s| {
                    s["sections"][0]["calibration"]["pixels_per_metre"] = json!(61);
                })
            }),
            "input_spec_changed",
        ),
        (
            "captured source image changed".into(),
            Box::new(|c| append_byte(&c.file("domain/input/source.png"))),
            "source_changed",
        ),
        (
            "revision spec changed".into(),
            Box::new(|c| {
                let id = c.observation["validation"]["contract"]["binding"]["revision_id"]
                    .as_str()
                    .unwrap();
                append_byte(&c.file(&format!("domain/revisions/{id}/spec.json")))
            }),
            "validation_built_source_or_units",
        ),
        (
            "revision selection record changed".into(),
            Box::new(|c| {
                let id = c.observation["validation"]["contract"]["binding"]["revision_id"]
                    .as_str()
                    .unwrap();
                append_byte(&c.file(&format!("domain/revisions/{id}/selection.json")))
            }),
            "artifact_identity_mismatch",
        ),
        // Fields of the domain checkpoint.
        (
            "checkpoint selection changed".into(),
            Box::new(|c| {
                edit_json(&c.file(&state), |s| {
                    s["selected"]["s0"] = json!("a-different-source-choice")
                })
            }),
            "domain_identity_or_review_boundary",
        ),
        (
            "checkpoint revision changed".into(),
            Box::new(|c| edit_json(&c.file(&state), |s| s["revision"] = json!(2))),
            "domain_identity_or_review_boundary",
        ),
        (
            "checkpoint input binding changed".into(),
            Box::new(|c| {
                edit_json(&c.file(&state), |s| {
                    s["input_spec_sha256"] = json!(OTHER_HASH)
                })
            }),
            "input_spec_changed",
        ),
        (
            "checkpoint source hash changed".into(),
            Box::new(|c| {
                edit_json(&c.file(&state), |s| {
                    let sources = s["sources"].as_object_mut().unwrap();
                    let first = sources.keys().next().unwrap().clone();
                    sources.get_mut(&first).unwrap()["sha256"] = json!(OTHER_HASH);
                })
            }),
            "source_changed",
        ),
        (
            "checkpoint schema version changed".into(),
            Box::new(|c| {
                edit_json(&c.file(&state), |s| {
                    s["version"] = json!("source_bound_tools_v2")
                })
            }),
            "domain_schema",
        ),
    ];
    // Placeholder error code "safe_file" means any rejection of a missing path;
    // the exact text depends on the path helper, so look it up once.
    let missing = {
        let c = Copy::of(pass);
        std::fs::remove_file(c.file(&format!("{run}/model.step"))).unwrap();
        c.ready().unwrap_err()
    };
    for (label, mutate, code) in table {
        let copy = Copy::of(pass);
        copy.ready().expect("each copy starts valid");
        mutate(&copy);
        let code = if code == "safe_file" {
            missing.as_str()
        } else {
            code
        };
        cases.expect_error(&label, copy.ready(), code);
    }
    cases.finish();
}

// --------------------------------------- observation, contract and context

/// A change to the observation, the domain description and the context.
type Change = Box<dyn Fn(&mut Value, &mut Value, &mut Value)>;

fn replace_each(cases: &mut Cases, base: &Validated, table: Vec<(&str, Change, &str)>) {
    for (label, change, code) in table {
        let mut observation = base.observation.clone();
        let mut domain = base.domain.clone();
        let mut context = base.context.clone();
        change(&mut observation, &mut domain, &mut context);
        let outcome = validation::ready(
            &base.root(),
            &observation,
            &domain,
            &context,
            base.audit_pin.as_deref(),
        );
        cases.expect_error(label, outcome, code);
    }
}

#[test]
#[ignore = "real CAD (slow): run with make test-full"]
fn envelope_types_and_contract_identities_are_exact() {
    let _serial = serial();
    let mut cases = Cases::default();
    let table: Vec<(&str, Change, &str)> = vec![
        // The envelope flag and status are exact values, not truthy ones.
        (
            "ok is the string true",
            Box::new(|o, _, _| o["ok"] = json!("true")),
            "candidate_validation_failed",
        ),
        (
            "ok is the number one",
            Box::new(|o, _, _| o["ok"] = json!(1)),
            "candidate_validation_failed",
        ),
        (
            "ok is null",
            Box::new(|o, _, _| o["ok"] = json!(null)),
            "candidate_validation_failed",
        ),
        (
            "ok is missing",
            Box::new(|o, _, _| remove(o, "/ok")),
            "candidate_validation_failed",
        ),
        (
            "status is not the review status",
            Box::new(|o, _, _| o["status"] = json!("validated")),
            "candidate_validation_failed",
        ),
        // Review boundary flags.
        (
            "observation approves engineering",
            Box::new(|o, _, _| o["engineering_approved"] = json!(true)),
            "observation_review_boundary",
        ),
        (
            "approval flag is the number zero",
            Box::new(|o, _, _| o["engineering_approved"] = json!(0)),
            "observation_review_boundary",
        ),
        (
            "semantic review flag is a string",
            Box::new(|o, _, _| o["human_semantic_review_required"] = json!("true")),
            "observation_review_boundary",
        ),
        (
            "semantic review flag is missing",
            Box::new(|o, _, _| remove(o, "/human_semantic_review_required")),
            "observation_review_boundary",
        ),
        (
            "identity is certified",
            Box::new(|o, _, _| o["validation"]["identity_certified"] = json!(true)),
            "audit_truth_or_review_boundary",
        ),
        // Unknown and missing fields.
        (
            "validation has an unknown field",
            Box::new(|o, _, _| o["validation"]["extra"] = json!(true)),
            "missing_or_unknown_fields",
        ),
        (
            "validation lacks sampled sections",
            Box::new(|o, _, _| remove(o, "/validation/sampled_sections")),
            "missing_or_unknown_fields",
        ),
        (
            "validation is null",
            Box::new(|o, _, _| o["validation"] = json!(null)),
            "required_object",
        ),
        (
            "contract is null",
            Box::new(|o, _, _| o["validation"]["contract"] = json!(null)),
            "validation_typed_schema",
        ),
        (
            "contract has an unknown field",
            Box::new(|o, _, _| o["validation"]["contract"]["extra"] = json!(1)),
            "validation_typed_schema",
        ),
        (
            "contract lacks its binding",
            Box::new(|o, _, _| remove(o, "/validation/contract/binding")),
            "validation_typed_schema",
        ),
        // Unknown schema and mismatched identities.
        (
            "unknown contract schema",
            Box::new(|o, _, _| {
                o["validation"]["contract"]["schema_version"] = json!("marinaframe.validation.v2")
            }),
            "validation_contract_or_boundary",
        ),
        (
            "unknown audit contract version",
            Box::new(|o, _, _| {
                o["validation"]["contract"]["audit_contract_version"] =
                    json!("step_source_sections_v2")
            }),
            "validation_contract_or_boundary",
        ),
        (
            "distance tolerance loosened",
            Box::new(|o, _, _| {
                o["validation"]["contract"]["tolerances"]["max_section_distance_m"] = json!(0.5)
            }),
            "validation_contract_or_boundary",
        ),
        (
            "metric tolerance loosened",
            Box::new(|o, _, _| {
                o["validation"]["contract"]["tolerances"]["max_relative_metric_error"] =
                    json!(0.001)
            }),
            "validation_contract_or_boundary",
        ),
        (
            "tolerance is a string",
            Box::new(|o, _, _| {
                o["validation"]["contract"]["tolerances"]["max_section_distance_m"] =
                    json!("0.0011")
            }),
            "validation_typed_schema",
        ),
        (
            "STEP unit changed",
            Box::new(|o, _, _| o["validation"]["contract"]["units"]["step"] = json!("m")),
            "validation_contract_or_boundary",
        ),
        (
            "contract approves engineering",
            Box::new(|o, _, _| o["validation"]["contract"]["engineering_approved"] = json!(true)),
            "validation_contract_or_boundary",
        ),
        (
            "contract approval is the number zero",
            Box::new(|o, _, _| o["validation"]["contract"]["engineering_approved"] = json!(0)),
            "validation_typed_schema",
        ),
        (
            "semantic review waived",
            Box::new(|o, _, _| o["validation"]["contract"]["semantic_review"] = json!("approved")),
            "validation_contract_or_boundary",
        ),
        (
            "worker execution not succeeded",
            Box::new(|o, _, _| {
                o["validation"]["contract"]["checks"]["worker_execution"] = json!("interrupted")
            }),
            "validation_contract_or_boundary",
        ),
        (
            "artifact integrity check failed",
            Box::new(|o, _, _| {
                o["validation"]["contract"]["checks"]["artifact_integrity"] = json!("failed")
            }),
            "validation_contract_or_boundary",
        ),
        (
            "check is a Boolean",
            Box::new(|o, _, _| {
                o["validation"]["contract"]["checks"]["trace_fidelity"] = json!(true)
            }),
            "validation_typed_schema",
        ),
        (
            "outcome contradicts its checks",
            Box::new(|o, _, _| o["validation"]["contract"]["outcome"] = json!("failed")),
            "contradictory_validation",
        ),
        (
            "trace check contradicts its measurement",
            Box::new(|o, _, _| {
                o["validation"]["contract"]["checks"]["trace_fidelity"] = json!("failed")
            }),
            "contradictory_validation",
        ),
        (
            "measurement is null",
            Box::new(|o, _, _| {
                o["validation"]["contract"]["measurements"]["max_section_distance_m"] = json!(null)
            }),
            "validation_typed_schema",
        ),
        (
            "measurement is negative",
            Box::new(|o, _, _| {
                o["validation"]["contract"]["measurements"]["max_section_distance_m"] = json!(-1.0)
            }),
            "validation_measurement_type",
        ),
        (
            "measurement is a string",
            Box::new(|o, _, _| {
                o["validation"]["contract"]["measurements"]["relative_metric_error"] = json!("0")
            }),
            "validation_typed_schema",
        ),
        (
            "measurement over tolerance with a pass",
            Box::new(|o, _, _| {
                o["validation"]["contract"]["measurements"]["max_section_distance_m"] = json!(0.8)
            }),
            "contradictory_validation",
        ),
        (
            "section count is a Boolean",
            Box::new(|o, _, _| {
                o["validation"]["contract"]["sampling"]["total_section_count"] = json!(true)
            }),
            "validation_typed_schema",
        ),
        (
            "sampling policy changed",
            Box::new(|o, _, _| {
                o["validation"]["contract"]["sampling"]["policy"] = json!("all_sections")
            }),
            "validation_sampling",
        ),
        (
            "binding hash is malformed",
            Box::new(|o, _, _| {
                o["validation"]["contract"]["binding"]["audit_implementation_sha256"] = json!("abc")
            }),
            "validation_hash",
        ),
        (
            "binding hash has the wrong type",
            Box::new(|o, _, _| o["validation"]["contract"]["binding"]["step_sha256"] = json!(7)),
            "validation_typed_schema",
        ),
        (
            "evidence inventory is too small",
            Box::new(|o, _, _| o["validation"]["contract"]["evidence"] = json!([])),
            "validation_evidence_inventory",
        ),
    ];
    replace_each(&mut cases, passing(), table);
    cases.finish();
}

#[test]
#[ignore = "real CAD (slow): run with make test-full"]
fn stale_generation_revision_and_binding_mismatches_are_rejected() {
    let _serial = serial();
    let mut cases = Cases::default();
    let table: Vec<(&str, Change, &str)> = vec![
        // Observation and contract disagree with the current domain.
        (
            "observation generation is stale",
            Box::new(|o, _, _| o["generation_id"] = json!("generation-ffffffffffffffffffffffff")),
            "stale_validation",
        ),
        (
            "observation revision is stale",
            Box::new(|o, _, _| o["revision_id"] = json!("r0099")),
            "stale_validation",
        ),
        (
            "validation revision is stale",
            Box::new(|o, _, _| o["validation"]["revision_id"] = json!("r0099")),
            "stale_validation",
        ),
        (
            "contract generation is stale",
            Box::new(|o, _, _| {
                o["validation"]["contract"]["binding"]["generation_id"] =
                    json!("generation-ffffffffffffffffffffffff")
            }),
            "stale_validation",
        ),
        (
            "contract revision is stale",
            Box::new(|o, _, _| {
                o["validation"]["contract"]["binding"]["revision_id"] = json!("r0002")
            }),
            "stale_validation",
        ),
        // The domain moved on (a later selection) while the old evidence stayed.
        (
            "domain generation moved",
            Box::new(|_, d, _| d["generation_id"] = json!("generation-ffffffffffffffffffffffff")),
            "domain_identity_or_review_boundary",
        ),
        (
            "domain revision moved",
            Box::new(|_, d, _| d["revision_id"] = json!("r0002")),
            "domain_identity_or_review_boundary",
        ),
        (
            "domain source manifest moved",
            Box::new(|_, d, _| d["source_manifest_sha256"] = json!(OTHER_HASH)),
            "domain_identity_or_review_boundary",
        ),
        (
            "domain has no valid candidate",
            Box::new(|_, d, _| d["current_candidate"]["valid"] = json!(false)),
            "validation_candidate_mismatch",
        ),
        (
            "domain candidate is another run",
            Box::new(|_, d, _| d["current_candidate"]["run_id"] = json!("00000000000000000000")),
            "validation_candidate_mismatch",
        ),
        (
            "domain candidate is another generation",
            Box::new(|_, d, _| {
                d["current_candidate"]["generation_id"] =
                    json!("generation-ffffffffffffffffffffffff")
            }),
            "validation_candidate_mismatch",
        ),
        // Contract binding differs from the context built from current files.
        (
            "binding STEP hash differs from the context",
            Box::new(|o, _, _| {
                o["validation"]["contract"]["binding"]["step_sha256"] = json!(OTHER_HASH)
            }),
            "validation_context_changed",
        ),
        (
            "binding calibration hash differs from the context",
            Box::new(|o, _, _| {
                o["validation"]["contract"]["binding"]["input_spec_sha256"] = json!(OTHER_HASH)
            }),
            "validation_context_changed",
        ),
        (
            "binding selection hash differs from the context",
            Box::new(|o, _, _| {
                o["validation"]["contract"]["binding"]["selection_sha256"] = json!(OTHER_HASH)
            }),
            "validation_context_changed",
        ),
        (
            "binding audit implementation differs from the context",
            Box::new(|o, _, _| {
                o["validation"]["contract"]["binding"]["audit_implementation_sha256"] =
                    json!(OTHER_HASH)
            }),
            "validation_context_changed",
        ),
        (
            "binding run differs from the context",
            Box::new(|o, _, _| {
                o["validation"]["contract"]["binding"]["run_id"] = json!("00000000000000000000")
            }),
            "validation_context_changed",
        ),
        (
            "context sampling differs from the contract",
            Box::new(|_, _, c| c["sampling"]["section_ids"] = json!(["s0", "s1"])),
            "validation_context_changed",
        ),
        // The context and the contract agree, but not with the files on disk.
        (
            "binding and context agree on another calibration",
            Box::new(|o, _, c| {
                o["validation"]["contract"]["binding"]["input_spec_sha256"] = json!(OTHER_HASH);
                c["binding"]["input_spec_sha256"] = json!(OTHER_HASH);
            }),
            "validation_source_or_selection",
        ),
        (
            "binding and context agree on another selection",
            Box::new(|o, _, c| {
                o["validation"]["contract"]["binding"]["selection_sha256"] = json!(OTHER_HASH);
                c["binding"]["selection_sha256"] = json!(OTHER_HASH);
            }),
            "validation_source_or_selection",
        ),
        (
            "binding and context agree on another source manifest",
            Box::new(|o, _, c| {
                o["validation"]["contract"]["binding"]["source_manifest_sha256"] =
                    json!(OTHER_HASH);
                c["binding"]["source_manifest_sha256"] = json!(OTHER_HASH);
            }),
            "validation_source_or_selection",
        ),
        (
            "binding and context agree on another STEP",
            Box::new(|o, _, c| {
                o["validation"]["contract"]["binding"]["step_sha256"] = json!(OTHER_HASH);
                c["binding"]["step_sha256"] = json!(OTHER_HASH);
            }),
            "validation_native_identity",
        ),
        (
            "binding and context agree on another run result",
            Box::new(|o, _, c| {
                o["validation"]["contract"]["binding"]["run_result_sha256"] = json!(OTHER_HASH);
                c["binding"]["run_result_sha256"] = json!(OTHER_HASH);
            }),
            "validation_native_identity",
        ),
        (
            "binding and context agree on another revision spec",
            Box::new(|o, _, c| {
                o["validation"]["contract"]["binding"]["revision_spec_sha256"] = json!(OTHER_HASH);
                c["binding"]["revision_spec_sha256"] = json!(OTHER_HASH);
            }),
            "validation_built_source_or_units",
        ),
        // The context itself is complete, exact and current.
        (
            "context lacks section info",
            Box::new(|_, _, c| remove(c, "/section_info")),
            "missing_or_unknown_fields",
        ),
        (
            "context has an unknown field",
            Box::new(|_, _, c| c["extra"] = json!(1)),
            "missing_or_unknown_fields",
        ),
        (
            "context is null",
            Box::new(|_, _, c| *c = json!(null)),
            "required_object",
        ),
        (
            "context evidence lost an entry",
            Box::new(|_, _, c| {
                c["evidence"].as_array_mut().unwrap().pop();
            }),
            "context_evidence_not_current_files",
        ),
        (
            "context metrics changed",
            Box::new(|_, _, c| c["engine_metrics"]["length_m"] = json!(99.0)),
            "context_metrics_not_current_run",
        ),
        (
            "context section info changed",
            Box::new(|_, _, c| c["section_info"]["s0"]["pixels_per_metre"] = json!(61.0)),
            "context_section_info_not_current_run",
        ),
    ];
    replace_each(&mut cases, passing(), table);
    cases.finish();
}

// ------------------------------------------- consistent forgeries of the audit

/// Refresh the hash, size and id that the observation and contract hold for one
/// evidence file after the file changed.
fn refresh_references(root: &Path, observation: &mut Value, kind: &str) {
    let path = observation["validation"]["contract"]["evidence"]
        .as_array()
        .unwrap()
        .iter()
        .find(|e| e["kind"] == kind)
        .unwrap()["path"]
        .as_str()
        .unwrap()
        .to_string();
    let fresh = store::artifact(root, &path, kind).unwrap();
    let sha = fresh["sha256"].as_str().unwrap().to_string();
    for e in observation["validation"]["contract"]["evidence"]
        .as_array_mut()
        .unwrap()
    {
        if e["kind"] == kind {
            e["sha256"] = fresh["sha256"].clone();
            e["bytes"] = fresh["bytes"].clone();
        }
    }
    for a in observation["validation"]["artifacts"]
        .as_array_mut()
        .unwrap()
    {
        if a["kind"] == kind {
            a["sha256"] = fresh["sha256"].clone();
            a["bytes"] = fresh["bytes"].clone();
            a["id"] = json!(format!("artifact-{}", &sha[..24]));
        }
    }
}

/// Rewrite the raw audit file so that EVERY copy of it agrees: the file, the
/// worker receipt, the cached observation, and all recorded hashes, sizes and
/// ids. Only the semantic content differs from what the worker measured.
fn forge_audit(copy: &mut Copy, edit: impl Fn(&mut Value)) {
    let audit_path = copy.file(&copy.evidence("step_reimport_validation"));
    let receipt_path = copy.file(&copy.evidence("validation_worker_receipt"));
    let old: Value = serde_json::from_slice(&std::fs::read(&audit_path).unwrap()).unwrap();
    let mut audit = old.clone();
    edit(&mut audit);
    edit_json(&audit_path, |v| *v = audit.clone());
    edit_json(&receipt_path, |v| v["validation"] = audit.clone());
    let validation = copy.observation["validation"].as_object_mut().unwrap();
    for key in old.as_object().unwrap().keys() {
        validation.remove(key);
    }
    for (key, value) in audit.as_object().unwrap() {
        validation.insert(key.clone(), value.clone());
    }
    let root = copy.root();
    refresh_references(&root, &mut copy.observation, "step_reimport_validation");
    refresh_references(&root, &mut copy.observation, "validation_worker_receipt");
}

enum Edit {
    Set(&'static str, Value),
    Remove(&'static str),
    /// A section distance changed together with its pixel distance (60 px/m).
    SectionDistance(usize, f64),
}

fn apply(audit: &mut Value, edit: &Edit) {
    match edit {
        Edit::Set(pointer, value) => set(audit, pointer, value.clone()),
        Edit::Remove(pointer) => remove(audit, pointer),
        Edit::SectionDistance(index, metres) => {
            set(
                audit,
                &format!("/sampled_sections/{index}/max_m"),
                json!(metres),
            );
            set(
                audit,
                &format!("/sampled_sections/{index}/max_px"),
                json!(metres * 60.0),
            );
        }
    }
}

#[test]
#[ignore = "real CAD (slow): run with make test-full"]
fn consistently_forged_audit_content_is_rejected_by_type_and_semantics() {
    let _serial = serial();
    let pass = passing();
    // Control: rewriting the audit through the helper without a change stays valid,
    // so each rejection below comes from the edit and not from the helper.
    let mut control = Copy::of(pass);
    forge_audit(&mut control, |_| ());
    control
        .ready()
        .expect("the forging helper must preserve validity");

    let table: Vec<(&str, Edit, &str)> = vec![
        // Exact Boolean types.
        (
            "valid_shape is the number one",
            Edit::Set("/geometry_audit/valid_shape", json!(1)),
            "valid_shape_not_boolean",
        ),
        (
            "valid_shape is null",
            Edit::Set("/geometry_audit/valid_shape", json!(null)),
            "valid_shape_not_boolean",
        ),
        (
            "closed_shell is the string true",
            Edit::Set("/geometry_audit/closed_shell", json!("true")),
            "closed_shell_not_boolean",
        ),
        (
            "geometry_checks_passed is the number one",
            Edit::Set("/geometry_checks_passed", json!(1)),
            "audit_conclusion_contradiction",
        ),
        (
            "geometry_checks_passed is null",
            Edit::Set("/geometry_checks_passed", json!(null)),
            "audit_conclusion_contradiction",
        ),
        (
            "geometry_checks_passed is missing",
            Edit::Remove("/geometry_checks_passed"),
            "missing_or_unknown_fields",
        ),
        (
            "immutable_run_verified is the number one",
            Edit::Set("/immutable_run_verified", json!(1)),
            "audit_truth_or_review_boundary",
        ),
        (
            "immutable_run_verified is false",
            Edit::Set("/immutable_run_verified", json!(false)),
            "audit_truth_or_review_boundary",
        ),
        (
            "numeric reference truth was used",
            Edit::Set("/numeric_reference_truth_used", json!(true)),
            "audit_truth_or_review_boundary",
        ),
        (
            "audit approves engineering",
            Edit::Set("/engineering_approved", json!(true)),
            "audit_truth_or_review_boundary",
        ),
        // Exact numeric types.
        (
            "solid_count is a float",
            Edit::Set("/geometry_audit/solid_count", json!(1.0)),
            "integer_measurement_type",
        ),
        (
            "shell_count is null",
            Edit::Set("/geometry_audit/shell_count", json!(null)),
            "integer_measurement_type",
        ),
        (
            "solid_count is negative",
            Edit::Set("/geometry_audit/solid_count", json!(-1)),
            "integer_measurement_type",
        ),
        (
            "sampled count is a float",
            Edit::Set("/sampled_section_count", json!(3.0)),
            "sampled_section_coverage",
        ),
        (
            "total count is a string",
            Edit::Set("/total_section_count", json!("3")),
            "sampled_section_coverage",
        ),
        (
            "metric is a string",
            Edit::Set("/geometry_audit/metrics/length_m", json!("4")),
            "required_numeric_measurement",
        ),
        (
            "metric is null",
            Edit::Set("/geometry_audit/metrics/beam_m", json!(null)),
            "required_numeric_measurement",
        ),
        (
            "metric is negative",
            Edit::Set("/geometry_audit/metrics/volume_m3", json!(-1.0)),
            "negative_measurement",
        ),
        (
            "metric is zero",
            Edit::Set("/geometry_audit/metrics/depth_m", json!(0.0)),
            "nonpositive_geometry",
        ),
        (
            "relative error is null",
            Edit::Set("/geometry_audit/relative_metric_error", json!(null)),
            "required_numeric_measurement",
        ),
        (
            "relative error hides a metric difference",
            Edit::Set("/geometry_audit/metrics/beam_m", json!(2.0)),
            "metric_measurement_contradiction",
        ),
        (
            "section distance is null",
            Edit::Set("/sampled_sections/0/max_m", json!(null)),
            "required_numeric_measurement",
        ),
        (
            "section distance is a string",
            Edit::Set("/sampled_sections/1/max_m", json!("0.0")),
            "required_numeric_measurement",
        ),
        (
            "section distance is negative",
            Edit::Set("/sampled_sections/2/p95_m", json!(-0.1)),
            "negative_measurement",
        ),
        (
            "section sample count is a float",
            Edit::Set("/sampled_sections/0/sample_count", json!(10.5)),
            "sampled_section_identity",
        ),
        (
            "section edge count is null",
            Edit::Set("/sampled_sections/0/section_edges", json!(null)),
            "integer_measurement_type",
        ),
        (
            "section uncertainty is a string",
            Edit::Set(
                "/sampled_sections/0/source_measurement_uncertainty_m",
                json!("0.1"),
            ),
            "required_numeric_measurement",
        ),
        (
            "pixel distance contradicts the metre distance",
            Edit::Set("/sampled_sections/0/max_px", json!(1.0)),
            "section_measurement_contradiction",
        ),
        // Missing fields, unknown fields and unknown schema text.
        (
            "section lacks rms",
            Edit::Remove("/sampled_sections/1/rms_m"),
            "missing_or_unknown_fields",
        ),
        (
            "section has an unknown field",
            Edit::Set("/sampled_sections/0/extra", json!(1)),
            "missing_or_unknown_fields",
        ),
        (
            "geometry audit has an unknown field",
            Edit::Set("/geometry_audit/extra", json!(1)),
            "missing_or_unknown_fields",
        ),
        (
            "geometry audit lacks its metrics",
            Edit::Remove("/geometry_audit/metrics"),
            "missing_or_unknown_fields",
        ),
        (
            "metrics have an unknown field",
            Edit::Set("/geometry_audit/metrics/weight_kg", json!(1.0)),
            "missing_or_unknown_fields",
        ),
        (
            "distance contract is unknown",
            Edit::Set(
                "/sampled_sections/0/distance_type",
                json!("reference truth distance"),
            ),
            "unknown_distance_contract",
        ),
        (
            "unresolved semantics shortened",
            Edit::Set("/unresolved_semantics", json!(["contour identity"])),
            "audit_semantics_or_sampling_contract",
        ),
        (
            "sampling text changed",
            Edit::Set("/section_sampling", json!("all sections")),
            "audit_semantics_or_sampling_contract",
        ),
        // Identity of the measured STEP.
        (
            "audit measured another STEP",
            Edit::Set("/geometry_audit/step_sha256", json!(OTHER_HASH)),
            "audit_step_identity_or_units",
        ),
        (
            "audit source is not the re-imported STEP",
            Edit::Set("/geometry_audit/source", json!("engine_result")),
            "audit_step_identity_or_units",
        ),
        (
            "audit STEP unit changed",
            Edit::Set("/geometry_audit/step_units", json!("m")),
            "audit_step_identity_or_units",
        ),
        // Conclusions that do not follow from the measurements.
        (
            "two solids but the contract says CAD valid",
            Edit::Set("/geometry_audit/solid_count", json!(2)),
            "audit_conclusion_contradiction",
        ),
        (
            "open shell but the contract says CAD valid",
            Edit::Set("/geometry_audit/closed_shell", json!(false)),
            "audit_conclusion_contradiction",
        ),
        (
            "invalid shape but the contract says CAD valid",
            Edit::Set("/geometry_audit/valid_shape", json!(false)),
            "audit_conclusion_contradiction",
        ),
        (
            "section distance over tolerance but the contract says trace passed",
            Edit::SectionDistance(0, 0.01),
            "audit_conclusion_contradiction",
        ),
    ];
    let mut cases = Cases::default();
    for (label, edit, code) in &table {
        let mut copy = Copy::of(pass);
        forge_audit(&mut copy, |audit| apply(audit, edit));
        cases.expect_error(label, copy.ready(), code);
    }
    cases.finish();
}

#[test]
#[ignore = "real CAD (slow): run with make test-full"]
fn audit_receipt_and_resource_contract_is_exact() {
    let _serial = serial();
    let pass = passing();
    let mut control = Copy::of(pass);
    forge_receipt(&mut control, |_| ());
    control
        .ready()
        .expect("the receipt forging helper must preserve validity");
    let table: Vec<(&str, Edit, &str)> = vec![
        (
            "receipt validation differs from the raw audit",
            Edit::Set("/validation/geometry_checks_passed", json!(false)),
            "audit_receipt_disagrees",
        ),
        (
            "receipt has an unknown field",
            Edit::Set("/extra", json!(1)),
            "missing_or_unknown_fields",
        ),
        (
            "receipt resources lack the profile",
            Edit::Remove("/resources/resource_profile"),
            "missing_or_unknown_fields",
        ),
        (
            "unknown resource profile",
            Edit::Set("/resources/resource_profile", json!("none")),
            "audit_worker_resource_or_inventory_contract",
        ),
        (
            "wall time is null",
            Edit::Set("/resources/wall_seconds", json!(null)),
            "required_numeric_measurement",
        ),
        (
            "cpu time is negative",
            Edit::Set("/resources/cpu_seconds", json!(-1.0)),
            "negative_measurement",
        ),
        (
            "peak memory is a float",
            Edit::Set("/resources/peak_rss_kib", json!(1.5)),
            "integer_measurement_type",
        ),
        (
            "peak memory is zero",
            Edit::Set("/resources/peak_rss_kib", json!(0)),
            "integer_measurement_bound",
        ),
        (
            "receipt artifact inventory lost a file",
            Edit::Set("/artifacts", json!([])),
            "audit_worker_resource_or_inventory_contract",
        ),
    ];
    let mut cases = Cases::default();
    for (label, edit, code) in &table {
        let mut copy = Copy::of(pass);
        forge_receipt(&mut copy, |receipt| apply(receipt, edit));
        cases.expect_error(label, copy.ready(), code);
    }
    cases.finish();
}

/// Rewrite the worker receipt with consistent hashes.
fn forge_receipt(copy: &mut Copy, edit: impl Fn(&mut Value)) {
    let path = copy.file(&copy.evidence("validation_worker_receipt"));
    edit_json(&path, |receipt| edit(receipt));
    let root = copy.root();
    refresh_references(&root, &mut copy.observation, "validation_worker_receipt");
}

// -------------------------------------------- failure cannot become a pass

/// Swap the first two entries of this kind in a list.
fn swap_first_two(list: &mut Value, kind: &str) {
    let positions: Vec<usize> = list
        .as_array()
        .unwrap()
        .iter()
        .enumerate()
        .filter(|(_, item)| item["kind"] == kind)
        .map(|(index, _)| index)
        .collect();
    list.as_array_mut()
        .unwrap()
        .swap(positions[0], positions[1]);
}

#[test]
#[ignore = "real CAD (slow): run with make test-full"]
fn section_comparison_images_must_follow_the_sampling_order() {
    let _serial = serial();
    let kind = "step_section_cut_comparison";
    let mut copy = Copy::of(passing());
    // Every record agrees on the swapped order, so only the sampling order can object.
    swap_first_two(&mut copy.observation["validation"]["artifacts"], kind);
    swap_first_two(
        &mut copy.observation["validation"]["contract"]["evidence"],
        kind,
    );
    forge_receipt(&mut copy, |receipt| {
        swap_first_two(&mut receipt["artifacts"], kind)
    });
    assert_eq!(copy.ready().unwrap_err(), "section_artifact_order");
}

#[test]
#[ignore = "real CAD (slow): run with make test-full"]
fn failed_geometry_cannot_be_promoted_by_envelope_contract_or_cache_forgery() {
    let _serial = serial();
    let fail = failing();
    let mut cases = Cases::default();
    // 1. A permissive envelope over the failed nested evidence.
    let mut copy = Copy::of(fail);
    copy.observation["ok"] = json!(true);
    copy.observation["status"] = json!("validated_review_required");
    cases.expect_error(
        "permissive envelope",
        copy.ready(),
        "candidate_validation_failed",
    );
    // 2. The contract rewritten to pass, raw audit untouched on disk.
    let mut copy = Copy::of(fail);
    copy.observation["ok"] = json!(true);
    copy.observation["status"] = json!("validated_review_required");
    let contract = &mut copy.observation["validation"]["contract"];
    contract["outcome"] = json!("passed");
    contract["checks"]["trace_fidelity"] = json!("passed");
    contract["measurements"]["max_section_distance_m"] = json!(0.0);
    cases.expect_error(
        "contract rewritten to pass",
        copy.ready(),
        "audit_conclusion_contradiction",
    );
    // 3. Cached nested evidence and contract rewritten, raw audit file untouched.
    let mut copy = Copy::of(fail);
    copy.observation["ok"] = json!(true);
    copy.observation["status"] = json!("validated_review_required");
    copy.observation["validation"]["geometry_checks_passed"] = json!(true);
    for section in copy.observation["validation"]["sampled_sections"]
        .as_array_mut()
        .unwrap()
    {
        for key in ["max_m", "rms_m", "p95_m", "max_px"] {
            section[key] = json!(0.0);
        }
    }
    let contract = &mut copy.observation["validation"]["contract"];
    contract["outcome"] = json!("passed");
    contract["checks"]["trace_fidelity"] = json!("passed");
    contract["measurements"]["max_section_distance_m"] = json!(0.0);
    cases.expect_error(
        "cached evidence rewritten to pass",
        copy.ready(),
        "cached_raw_audit_disagrees",
    );
    // 4. The raw audit file rewritten to pass with every hash made consistent:
    //    the measured distances still contradict the claimed conclusion unless
    //    they are also rewritten, and rewriting them contradicts the contract.
    let mut copy = Copy::of(fail);
    copy.observation["ok"] = json!(true);
    copy.observation["status"] = json!("validated_review_required");
    forge_audit(&mut copy, |audit| {
        audit["geometry_checks_passed"] = json!(true)
    });
    cases.expect_error(
        "raw audit flag flipped consistently",
        copy.ready(),
        "audit_conclusion_contradiction",
    );
    cases.finish();
}

// ------------------------------------------------------------ real controller

/// A controller view of a private copy of a validated task, as after a restart.
fn reopened(source: &Validated, mode: Value) -> Fixture {
    let directory = copy_task(source.directory.path());
    util::atomic_json(&directory.path().join("matrix-mode.json"), &mode, true).unwrap();
    let store = store::Store::open(&directory.path().join("task")).unwrap();
    Fixture { directory, store }
}

#[test]
#[ignore = "real CAD (slow): run with make test-full"]
fn real_passing_candidate_reaches_review_on_valid_cached_evidence_without_a_new_audit() {
    let _serial = serial();
    let pass = passing();
    let mut fixture = reopened(pass, json!({}));
    assert_eq!(fixture.audits(), 0);
    finish(&mut fixture);
    assert_eq!(
        fixture.audits(),
        0,
        "valid cached evidence must not be re-audited"
    );
    let cached = fixture.observation();
    assert_eq!(
        cached["validation"], pass.observation["validation"],
        "cached evidence equals the fresh evidence"
    );
    assert_eq!(cached["reused"], true);
    assert_eq!(fixture.store.state.status, Status::AwaitingHumanReview);
    assert_eq!(fixture.events("candidate_ready_for_human_review"), 1);
    // The review-ready state is re-checked on every verification. A file that no
    // event references (so only the finalization predicate can notice it) makes
    // the stored task fail instead of staying ready.
    fixture
        .store
        .verify(false)
        .expect("untouched task verifies");
    let run = fixture.store.state.domain["current_candidate"]["path"]
        .as_str()
        .unwrap()
        .to_string();
    std::fs::write(fixture.task().join(format!("{run}/unlisted.bin")), b"x").unwrap();
    assert!(
        fixture.store.verify(false).is_err(),
        "a changed run must break the review-ready task"
    );
}

#[test]
#[ignore = "real CAD (slow): run with make test-full"]
fn real_failing_geometry_stays_failed_cached_and_after_restart() {
    let _serial = serial();
    let fail = failing();
    assert_eq!(fail.observation["ok"], false);
    assert_eq!(fail.observation["status"], "validation_failed");
    assert_eq!(
        fail.observation["validation"]["geometry_checks_passed"],
        false
    );
    let mut fixture = reopened(fail, json!({}));
    finish(&mut fixture);
    assert_eq!(
        fixture.audits(),
        0,
        "finish must reuse the cached failed audit"
    );
    assert_eq!(
        fixture.observation()["validation"],
        fail.observation["validation"],
        "failure equivalence between fresh and cached"
    );
    assert_eq!(fixture.store.state.status, Status::ValidationFailed);
    assert_not_review_ready(&fixture);
    // Restart: a new controller process opens the same task.
    let task = fixture.task();
    let Fixture { directory, store } = fixture;
    drop(store);
    let mut fixture = Fixture {
        store: store::Store::open(&task).unwrap(),
        directory,
    };
    let refused = controller::resume(&mut fixture.store, false, false, Some(4));
    assert!(
        refused.is_err(),
        "a failed task must not resume to a new finish"
    );
    assert_eq!(fixture.audits(), 0);
    assert_eq!(fixture.store.state.status, Status::ValidationFailed);
    assert_not_review_ready(&fixture);
}

fn interrupted_audit() -> Value {
    json!({"audit_outcome": {"state": "interrupted", "elapsed_seconds": 0.0}})
}

#[test]
#[ignore = "real CAD (slow): run with make test-full"]
fn interrupted_audit_is_not_cached_and_cannot_finish() {
    let _serial = serial();
    let mut fixture = fixture(false, interrupted_audit());
    validate(&mut fixture);
    assert_eq!(fixture.observation()["ok"], false);
    assert_eq!(
        fixture.observation()["error_code"],
        "validation_worker_failed"
    );
    let checkpoint: Value =
        util::read_json(&fixture.task().join("domain/state.json"), 32 << 20).unwrap();
    assert!(
        checkpoint["validation"].is_null(),
        "an interrupted audit must leave no cached validation"
    );
    finish(&mut fixture);
    assert_eq!(
        fixture.audits(),
        2,
        "finish asks for a new audit, not a cache"
    );
    assert_eq!(fixture.store.state.status, Status::ValidationFailed);
    assert_not_review_ready(&fixture);
}

#[test]
#[ignore = "real CAD (slow): run with make test-full"]
fn interrupted_audit_then_a_real_audit_can_still_pass() {
    let _serial = serial();
    let mut fixture = fixture(false, interrupted_audit());
    validate(&mut fixture);
    assert_eq!(fixture.observation()["ok"], false);
    fixture.mode(json!({}));
    validate(&mut fixture);
    assert_eq!(fixture.observation()["ok"], true);
    assert_eq!(fixture.audits(), 2);
    finish(&mut fixture);
    assert_eq!(fixture.audits(), 2);
    assert_eq!(fixture.store.state.status, Status::AwaitingHumanReview);
}

#[test]
#[ignore = "real CAD (slow): run with make test-full"]
fn cancellation_before_finish_prevents_review_ready() {
    let _serial = serial();
    let mut fixture = reopened(passing(), json!({}));
    std::fs::write(
        fixture.task().join("cancel.request"),
        b"controlled cancellation\n",
    )
    .unwrap();
    finish(&mut fixture);
    assert_eq!(fixture.store.state.status, Status::Cancelled);
    assert_not_review_ready(&fixture);
}

fn select(fixture: &mut Fixture, candidate: &str) {
    decide_as(
        &mut fixture.store,
        "operator",
        "select_contours",
        json!({"selections": [{"section_id": "s0", "candidate_id": candidate}]}),
    );
    assert_eq!(
        fixture.observation()["ok"],
        true,
        "selection of {candidate}"
    );
}

#[test]
#[ignore = "real CAD (slow): run with make test-full"]
fn selection_a_b_a_makes_the_old_validation_stale() {
    let _serial = serial();
    let pass = passing();
    let old = &pass.observation;
    let mut fixture = reopened(pass, json!({"alternative_candidate": true}));
    // The worker adds the alternative contour B while it inspects the source.
    decide(&mut fixture.store, "inspect_source", json!({}));
    let before = fixture.store.state.domain.clone();
    let original = before["sections"][0]["selected_candidate_id"]
        .as_str()
        .unwrap()
        .to_string();
    select(&mut fixture, "race-choice");
    select(&mut fixture, &original);
    let after = fixture.store.state.domain.clone();
    assert_eq!(
        after["sections"][0]["selected_candidate_id"],
        before["sections"][0]["selected_candidate_id"],
        "the selection is back to A"
    );
    assert_ne!(
        after["revision_id"], pass.domain["revision_id"],
        "A, B, A is a new revision"
    );
    // The earlier evidence names the earlier revision: Rust must call it stale
    // even though the selected content equals the earlier selected content.
    let stale = validation::ready(
        &fixture.task(),
        old,
        &after,
        &pass.context,
        pass.audit_pin.as_deref(),
    );
    assert_eq!(stale.unwrap_err(), "stale_validation");
    // The real finish path must not reach review without a new build and audit.
    finish(&mut fixture);
    assert_not_review_ready(&fixture);
    assert_eq!(fixture.audits(), 0, "there is no candidate to audit");
}

#[test]
#[ignore = "real CAD (slow): run with make test-full"]
fn stale_or_foreign_review_requests_are_refused() {
    let _serial = serial();
    let mut fixture = reopened(passing(), json!({}));
    let head = fixture.store.head.clone().unwrap();
    let generation = fixture.store.state.generation_id.clone().unwrap();
    let revision = fixture.store.state.revision_id.clone().unwrap();
    let task_id = fixture.store.state.task_id.clone();
    let request =
        |task: &str, head: &str, generation: &str, revision: &str| -> controller::Intervention {
            serde_json::from_value(json!({
                "schema_version": "marinaframe.intervention.v1",
                "task_id": task, "expected_head_sha256": head,
                "expected_generation_id": generation, "expected_revision_id": revision,
                "decision": {"tool": "finish", "reason": "Review request.",
                    "arguments": {"outcome": "candidate_ready_for_review", "summary": "Review."}}
            }))
            .unwrap()
        };
    let cases = [
        (
            "old head",
            request(&task_id, OTHER_HASH, &generation, &revision),
        ),
        (
            "old generation",
            request(
                &task_id,
                &head,
                "generation-ffffffffffffffffffffffff",
                &revision,
            ),
        ),
        (
            "old revision",
            request(&task_id, &head, &generation, "r0099"),
        ),
        (
            "foreign task",
            request("other-task", &head, &generation, &revision),
        ),
    ];
    let mut wrong = vec![];
    for (label, input) in cases {
        let outcome = controller::intervene(&mut fixture.store, input, "human_operator", "stale");
        if outcome != Err("stale_or_foreign_intervention".to_string()) {
            wrong.push(format!("{label}: {outcome:?}"));
        }
    }
    assert!(wrong.is_empty(), "requests not refused: {wrong:?}");
    assert_not_review_ready(&fixture);
    assert_eq!(
        fixture.store.head.as_ref(),
        Some(&head),
        "a refused request appends nothing"
    );
    // A current request is accepted, and the real predicate still decides.
    controller::intervene(
        &mut fixture.store,
        request(&task_id, &head, &generation, &revision),
        "human_operator",
        "current",
    )
    .unwrap();
    assert_eq!(fixture.store.state.status, Status::AwaitingHumanReview);
}
