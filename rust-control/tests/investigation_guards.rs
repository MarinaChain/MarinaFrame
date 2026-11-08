//! Investigation guards: the live model investigates freely, but cannot select
//! an unsnapped or self-traced line, set a review status, change a gate or
//! confirm its own guess.
//!
//! `tests/rust_investigation_worker.py` runs the real `rust_worker` and real
//! `DomainTools` (with the investigation tools) on the draft fixture: section
//! s0 has two lines, s1 and s2 one each. The harness inspects and selects s1
//! and s2 as the deterministic draft policy does; then each test sends model
//! decisions (actor `live_model`) straight to `execute_decision`. No provider
//! call is made. Tests that build CAD are marked real CAD.
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
use types::*;

fn repository() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .unwrap()
        .to_path_buf()
}

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
    repository().join("tests/rust_investigation_worker.py")
}

/// The controller locks `domain/lock` twice in a row; tests run serially.
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
        policy: Policy::Live,
        limits: OperationalLimits::default(),
        provider_transfer_authorized: true,
        authorization_basis: "Investigation guard fixture; no provider call is made".into(),
        model: GO_MODEL.into(),
        binary_sha256: util::file_hash(&std::env::current_exe().unwrap()).unwrap(),
        on_ambiguity,
    }
}

fn decision(tool: &str, arguments: Value) -> Decision {
    Decision {
        tool: tool.into(),
        arguments,
        reason: "Investigation guard test.".into(),
        notes: None,
    }
}

static TEMPLATE: std::sync::OnceLock<tempfile::TempDir> = std::sync::OnceLock::new();

/// A live draft-mode task after the harness preparation: every section is
/// inspected and the unique lines of s1 and s2 are selected. Prepared once.
fn template() -> &'static Path {
    TEMPLATE
        .get_or_init(|| {
            let directory = tempfile::tempdir().unwrap();
            let config = config(directory.path(), OnAmbiguity::Draft);
            let mut store = store::Store::create(
                &directory.path().join("task"),
                controller::new_state(config),
            )
            .unwrap();
            assert!(controller::initialize(&mut store).unwrap());
            for _ in 0..2 {
                let prepared = controller::deterministic_decision(&store).unwrap();
                assert!(
                    ["inspect_source", "select_contours"].contains(&prepared.tool.as_str()),
                    "{prepared:?}"
                );
                assert!(
                    controller::execute_decision(&mut store, prepared, "deterministic_policy")
                        .unwrap()
                );
            }
            assert_eq!(store.state.domain["selected_count"], 2);
            drop(store); // release the controller lock before copies are opened
            directory
        })
        .path()
}

/// A private copy of the prepared task. `mode` tells the worker shim what to
/// forge (see tests/rust_investigation_worker.py).
fn prepared(mode: Value) -> (tempfile::TempDir, store::Store) {
    let directory = tempfile::tempdir().unwrap();
    let copied = std::process::Command::new("cp")
        .arg("-Rp")
        .arg(template().join("task"))
        .arg(directory.path().join("task"))
        .status()
        .unwrap();
    assert!(copied.success(), "prepared task copy failed");
    util::atomic_json(
        &directory.path().join("investigation-mode.json"),
        &mode,
        false,
    )
    .unwrap();
    let store = store::Store::open(&directory.path().join("task")).unwrap();
    (directory, store)
}

fn model(store: &mut store::Store, tool: &str, arguments: Value) -> util::Result<bool> {
    controller::execute_decision(store, decision(tool, arguments), "live_model")
}

/// A view of section s0 and a corridor around its dark hull stroke
/// (x = 50 + 0.25 (210 - row), rows 30..210; see tests/draft_fixture.py).
fn view_and_trace(store: &mut store::Store) -> (String, String) {
    assert!(model(store, "view_region", json!({"region_px":[0,0,200,230]})).unwrap());
    let view = store.state.last_observation["view"].clone();
    let view_id = view["view_id"].as_str().unwrap().to_string();
    let scale = view["view_px_per_source_px"][0].as_f64().unwrap();
    let path = [25.0, 120.0, 215.0]
        .iter()
        .map(|row| json!([(50.0 + 0.25 * (210.0 - row)) * scale, row * scale]))
        .collect::<Vec<_>>();
    assert!(model(
        store,
        "trace_corridor",
        json!({"section_id":"s0","view_id":view_id,"path_px":path,"half_width_px":8.0 * scale})
    )
    .unwrap());
    let traced = &store.state.last_observation;
    assert_eq!(traced["ok"], true, "{traced}");
    (
        view_id,
        traced["candidate_id"].as_str().unwrap().to_string(),
    )
}

fn catalog_candidates(store: &store::Store, section: &str) -> Vec<Value> {
    validation::domain_checkpoint(&store.path).unwrap()["catalog"][section]["candidates"]
        .as_array()
        .unwrap()
        .clone()
}

#[test]
fn model_cannot_select_an_unsnapped_or_self_traced_line() {
    let _serial = serial();
    let (_directory, mut store) = prepared(json!({}));
    // An inspected line with a competing stroke: a model cannot select it.
    let ambiguous = catalog_candidates(&store, "s0")[0]["candidate_id"]
        .as_str()
        .unwrap()
        .to_string();
    assert_eq!(
        model(
            &mut store,
            "select_contours",
            json!({"selections":[{"section_id":"s0","candidate_id":ambiguous}]})
        )
        .unwrap_err(),
        "source_ambiguity_requires_explicit_operator_selection"
    );
    // A line the model traced is real ink, but it is still the model's choice.
    let (view_id, traced) = view_and_trace(&mut store);
    let candidate = catalog_candidates(&store, "s0")
        .into_iter()
        .find(|c| c["candidate_id"] == traced.as_str())
        .unwrap();
    assert_eq!(candidate["model_traced"], true);
    assert!(validation::snapped_candidate(&candidate));
    assert_eq!(
        model(
            &mut store,
            "select_contours",
            json!({"selections":[{"section_id":"s0","candidate_id":traced}]})
        )
        .unwrap_err(),
        "model_traced_candidate_requires_person"
    );
    // A corridor without ink gives no candidate: the refusal is an observation.
    let before = catalog_candidates(&store, "s0").len();
    assert!(model(
        &mut store,
        "trace_corridor",
        json!({"section_id":"s0","view_id":view_id,"path_px":[[20.0,100.0],[20.0,860.0]],"half_width_px":10.0})
    )
    .unwrap());
    assert_eq!(store.state.last_observation["ok"], false);
    assert_eq!(store.state.last_observation["status"], "proposal_refused");
    assert_eq!(catalog_candidates(&store, "s0").len(), before);
    // A candidate id that the harness never traced cannot be assigned.
    assert_eq!(
        model(
            &mut store,
            "assign_station",
            json!({"section_id":"s0","candidate_id":"trace-written-by-the-model","label_view_id":view_id,
                "label_text":"s0","reason":"A line the model claims."})
        )
        .unwrap_err(),
        "unsnapped_or_unknown_candidate"
    );
    // Free coordinates or extra fields never parse as a tool call.
    for (tool, arguments) in [
        (
            "assign_station",
            json!({"section_id":"s0","candidate_id":traced,"label_view_id":view_id,"label_text":"s0","reason":"x","points_yz_m":[[0.0,0.0],[1.0,1.0]]}),
        ),
        (
            "trace_corridor",
            json!({"section_id":"s0","view_id":view_id,"path_px":[[0.0,0.0]],"half_width_px":5.0}),
        ),
        (
            "trace_corridor",
            json!({"section_id":"s0","view_id":view_id,"path_px":[[0.0,0.0],[1.0,9000.0]],"half_width_px":5.0}),
        ),
        ("view_region", json!({"region_px":[10,10,5,5]})),
    ] {
        assert!(decision(tool, arguments).operation().is_err(), "{tool}");
    }
}

#[test]
fn model_cannot_set_review_status_change_gates_or_run_code() {
    let _serial = serial();
    for (tool, arguments) in [
        (
            "set_review_status",
            json!({"status":"awaiting_human_review"}),
        ),
        ("approve", json!({})),
        ("set_tolerance", json!({"trace_tolerance_mm":50})),
        (
            "change_gate",
            json!({"gate":"geometry_checks_passed","value":true}),
        ),
        ("run_code", json!({"code":"import os"})),
        ("write_file", json!({"path":"domain/state.json"})),
        ("finish", json!({"outcome":"approved","summary":"x"})),
        (
            "finish",
            json!({"outcome":"candidate_ready_for_review","summary":"x","engineering_approved":true}),
        ),
        (
            "view_region",
            json!({"region_px":[0,0,10,10],"path":"/etc/passwd"}),
        ),
        (
            "propose_sheet_setup",
            json!({"view":"body","region_px":[0,0,200,230],"pixels_per_metre":60.0,"grid_spacing_m":0.5,
            "evidence_view_id":"v","scale_claim":"x","reason":"x","tolerance":1.0}),
        ),
    ] {
        assert!(decision(tool, arguments).operation().is_err(), "{tool}");
    }
    // With an open model choice, readiness is refused before any other check.
    let (_directory, mut store) = prepared(json!({}));
    let (view_id, traced) = view_and_trace(&mut store);
    assert!(model(
        &mut store,
        "assign_station",
        json!({"section_id":"s0","candidate_id":traced,"label_view_id":view_id,"label_text":"s0","reason":"Labelled s0 curve."})
    )
    .unwrap());
    assert_eq!(store.state.last_observation["ok"], true);
    let open = validation::open_guesses(&validation::domain_checkpoint(&store.path).unwrap())
        .unwrap()
        .to_vec();
    assert_eq!(open.len(), 1);
    assert_eq!(open[0]["kind"], "model_choice");
    assert_eq!(open[0]["verifier_evidence"]["passed"], true);
    assert_eq!(
        validation::ready(
            &store.path,
            &store.state.last_observation,
            &store.state.domain,
            &json!({}),
            store.state.audit_implementation_sha256.as_deref()
        )
        .unwrap_err(),
        "draft_guesses_open"
    );
    assert!(!store.state.engineering_approved);
}

#[test]
fn forged_worker_review_claims_are_not_adopted() {
    let _serial = serial();
    for mode in [
        json!({"forge_review":true}),
        json!({"forge_review_required":true}),
    ] {
        let (_directory, mut store) = prepared(mode);
        let generation = store.state.generation_id.clone();
        let domain = store.state.domain.clone();
        assert_eq!(
            model(
                &mut store,
                "view_region",
                json!({"region_px":[0,0,200,230]})
            )
            .unwrap_err(),
            "worker_result_review_contract"
        );
        assert_eq!(store.state.domain, domain);
        assert_eq!(store.state.generation_id, generation);
        assert!(!store.state.engineering_approved);
        assert_ne!(store.state.status, Status::AwaitingHumanReview);
    }
}

#[test]
fn model_cannot_confirm_its_own_guess_but_a_person_can() {
    let _serial = serial();
    let (_directory, mut store) = prepared(json!({}));
    let (view_id, traced) = view_and_trace(&mut store);
    assert!(model(
        &mut store,
        "assign_station",
        json!({"section_id":"s0","candidate_id":traced,"label_view_id":view_id,"label_text":"s0","reason":"Labelled s0 curve."})
    )
    .unwrap());
    for actor in ["live_model", "deterministic_policy"] {
        assert_eq!(
            controller::execute_decision(
                &mut store,
                decision(
                    "select_contours",
                    json!({"selections":[{"section_id":"s0","candidate_id":traced}]})
                ),
                actor
            )
            .unwrap_err(),
            "guess_requires_operator_confirmation"
        );
    }
    // Restart does not let the model replace a guess with a selected alternative.
    let task = store.path.clone();
    drop(store);
    let mut store = store::Store::open(&task).unwrap();
    let alternative = catalog_candidates(&store, "s0")
        .into_iter()
        .find(|c| c["candidate_id"] != traced.as_str() && c["selectable"] == true)
        .unwrap()["candidate_id"]
        .as_str()
        .unwrap()
        .to_string();
    assert_eq!(
        model(
            &mut store,
            "select_contours",
            json!({"selections":[{"section_id":"s0","candidate_id":alternative}]})
        )
        .unwrap_err(),
        "guess_requires_operator_confirmation"
    );
    let checkpoint = validation::domain_checkpoint(&store.path).unwrap();
    assert_eq!(checkpoint["guesses"][0]["chosen_candidate_id"], traced);
    assert_eq!(checkpoint["guesses"][0]["status"], "open");
    // The model may revise its own guess (it stays a guess) ...
    assert!(model(
        &mut store,
        "assign_station",
        json!({"section_id":"s0","candidate_id":traced,"label_view_id":view_id,"label_text":"s0","reason":"Revised reason."})
    )
    .unwrap());
    assert_eq!(store.state.last_observation["ok"], true);
    // ... but only a person confirms it.
    assert!(controller::execute_decision(
        &mut store,
        decision(
            "select_contours",
            json!({"selections":[{"section_id":"s0","candidate_id":traced}]})
        ),
        "human_operator"
    )
    .unwrap());
    let checkpoint = validation::domain_checkpoint(&store.path).unwrap();
    assert!(validation::open_guesses(&checkpoint).unwrap().is_empty());
    assert_eq!(checkpoint["resolved_guesses"][0]["resolution"], "confirmed");
}

#[test]
fn a_selected_section_is_closed_to_the_model() {
    let _serial = serial();
    let (_directory, mut store) = prepared(json!({}));
    let (view_id, traced) = view_and_trace(&mut store);
    assert!(model(
        &mut store,
        "assign_station",
        json!({"section_id":"s0","candidate_id":traced,"label_view_id":view_id,"label_text":"s0","reason":"Labelled s0 curve."})
    )
    .unwrap());
    // s1 is selected; its section is closed to the model.
    let s1 = store.state.domain["sections"][1]["selected_candidate_id"]
        .as_str()
        .unwrap()
        .to_string();
    assert_eq!(
        model(
            &mut store,
            "assign_station",
            json!({"section_id":"s1","candidate_id":s1,"label_view_id":view_id,"label_text":"s1","reason":"x"})
        )
        .unwrap_err(),
        "section_already_selected"
    );
}

#[test]
fn worker_forged_unsnapped_model_choice_is_refused() {
    let _serial = serial();
    let (_directory, mut store) = prepared(json!({"forge_unsnapped":true}));
    let (view_id, traced) = view_and_trace(&mut store);
    assert_eq!(
        model(
            &mut store,
            "assign_station",
            json!({"section_id":"s0","candidate_id":traced,"label_view_id":view_id,"label_text":"s0","reason":"Labelled s0 curve."})
        )
        .unwrap_err(),
        "draft_guess_not_snapped_to_ink"
    );
}

#[test]
fn worker_forged_verifier_evidence_is_refused() {
    let _serial = serial();
    let (_directory, mut store) = prepared(json!({"forge_evidence":true}));
    let (view_id, traced) = view_and_trace(&mut store);
    assert_eq!(
        model(
            &mut store,
            "assign_station",
            json!({"section_id":"s0","candidate_id":traced,"label_view_id":view_id,"label_text":"s0","reason":"Labelled s0 curve."})
        )
        .unwrap_err(),
        "draft_guess_contract"
    );
}

#[test]
fn investigation_tools_exist_only_in_draft_mode() {
    let _serial = serial();
    let directory = tempfile::tempdir().unwrap();
    let config = config(directory.path(), OnAmbiguity::Abstain);
    let mut store = store::Store::create(
        &directory.path().join("task"),
        controller::new_state(config),
    )
    .unwrap();
    assert!(controller::initialize(&mut store).unwrap());
    assert_eq!(
        model(
            &mut store,
            "view_region",
            json!({"region_px":[0,0,200,230]})
        )
        .unwrap_err(),
        "investigation_requires_draft_mode"
    );
    let names = controller::tool_catalog(&OnAmbiguity::Abstain)
        .as_array()
        .unwrap()
        .iter()
        .map(|t| t["name"].as_str().unwrap().to_string())
        .collect::<Vec<_>>();
    assert!(!names.contains(&"trace_corridor".to_string()));
}

#[test]
#[ignore = "real CAD (slow): run with make test-full"]
fn submitting_an_investigated_draft_stops_at_draft_not_verified() {
    let _serial = serial();
    let (_directory, mut store) = prepared(json!({}));
    let (view_id, traced) = view_and_trace(&mut store);
    assert!(model(
        &mut store,
        "assign_station",
        json!({"section_id":"s0","candidate_id":traced,"label_view_id":view_id,"label_text":"s0","reason":"Labelled s0 curve."})
    )
    .unwrap());
    // Finish without a STEP first builds and submits a real draft.
    assert!(!model(
        &mut store,
        "finish",
        json!({"outcome":"candidate_ready_for_review","summary":"Build and submit."})
    )
    .unwrap());
    assert_eq!(store.state.domain["current_candidate"]["valid"], true);
    assert!(store
        .events
        .iter()
        .any(|event| event.kind == "submission_builds_draft"));
    // The model's own rebuild does not stop; it may render and revise.
    assert!(model(&mut store, "build_draft", json!({})).unwrap());
    assert_eq!(store.state.domain["current_candidate"]["draft"], true);
    assert!(model(&mut store, "render_candidate", json!({"view":"body"})).unwrap());
    // Submitting it ends at draft_not_verified, never review-ready.
    assert!(!model(
        &mut store,
        "finish",
        json!({"outcome":"candidate_ready_for_review","summary":"Submitted."})
    )
    .unwrap());
    assert_eq!(store.state.status, Status::DraftNotVerified);
    assert_eq!(
        store.state.termination_reason.as_deref(),
        Some("open_guesses_block_review")
    );
    assert!(store.verify(false).is_ok());
    assert!(!store.state.engineering_approved);
}

// ---- Mark and revise (src/revision.rs) ----
// The scripted model below stages each answer as `live_decision` would; the
// worker shim's `keep_rule` mode answers as the whole-vessel keep rule would.

use controller::revision;

fn revision_request(value: Value) -> revision::RevisionRequest {
    serde_json::from_value(value).unwrap()
}

fn s0_offsets() -> Value {
    json!({"section_id":"s0","form":"half_breadths","basis":"Follow the marked ink.",
        "offsets_m":[[0.0,0.0],[0.5,0.6],[1.0,0.9],[1.5,1.0],[2.0,1.0]]})
}

/// A scripted model: each call stages the next answer and checks that the
/// person's instruction reaches the model.
fn scripted(answers: Vec<Decision>) -> impl FnMut(&mut store::Store) -> util::Result<bool> {
    let mut answers = answers.into_iter();
    move |store| {
        assert!(revision::active(store));
        let brief = &store.state.last_observation["operator_revision"];
        assert_eq!(brief["instruction"], "Too full at the bilge");
        assert_eq!(brief["from"], "human_operator");
        store.state.staged_decision = answers.next();
        Ok(true)
    }
}

fn revise_s0(store: &mut store::Store, answers: Vec<Decision>) -> util::Result<Value> {
    let request = revision_request(json!({"schema_version":revision::REQUEST_SCHEMA,
        "instruction":"Too full at the bilge","target_section_ids":["s0"]}));
    revision::revise_with(store, request, &mut scripted(answers))
}

fn events_of<'a>(store: &'a store::Store, kind: &str) -> Vec<&'a Value> {
    store
        .events
        .iter()
        .filter(|e| e.kind == kind)
        .map(|e| &e.payload)
        .collect()
}

#[test]
fn a_revision_records_the_request_and_keeps_an_improving_edit() {
    let _serial = serial();
    let (_directory, mut store) = prepared(json!({"keep_rule":"improve"}));
    let result = revise_s0(&mut store, vec![decision("propose_section", s0_offsets())]).unwrap();
    assert_eq!(result["outcome"], "kept");
    assert_eq!(result["fit_change"], 0.03);
    assert_eq!(result["edits"][0]["section_id"], "s0");
    assert_eq!(result["engineering_approved"], false);
    let requested = events_of(&store, revision::REQUESTED_EVENT);
    assert_eq!(requested.len(), 1);
    assert_eq!(requested[0]["actor"], "human_operator");
    assert_eq!(requested[0]["sections"], json!(["s0"]));
    // The crop of the marked section was made before the model answered.
    assert!(store
        .events
        .iter()
        .any(|e| e.kind == "worker_intent" && e.payload["operation"] == "view_region"));
    assert_eq!(events_of(&store, revision::RESULT_EVENT).len(), 1);
    assert_eq!(store.state.status, Status::Paused);
    assert!(!revision::active(&store));
    assert_eq!(store.state.counters.operator_actions, 1);
    store.verify(false).unwrap();
}

#[test]
fn a_revision_refuses_an_edit_outside_its_range_and_asks_again() {
    let _serial = serial();
    let (_directory, mut store) = prepared(json!({"keep_rule":"improve"}));
    let outside = json!({"section_id":"s1","form":"blend","basis":"Wrong section."});
    let result = revise_s0(
        &mut store,
        vec![
            decision("propose_section", outside),
            decision("view_region", json!({"region_px":[0,0,10,10]})),
            decision("propose_section", s0_offsets()),
        ],
    )
    .unwrap();
    assert_eq!(result["edit_count"], 1);
    assert_eq!(result["outcome"], "kept");
    let refused = events_of(&store, "operation_rejected");
    assert_eq!(refused.len(), 2);
    assert!(refused
        .iter()
        .all(|e| e["reason"] == "revision_requires_propose_section_in_range"));
}

#[test]
fn a_not_kept_revision_can_be_kept_anyway_by_a_person() {
    let _serial = serial();
    let (_directory, mut store) = prepared(json!({"keep_rule":"reject"}));
    let result = revise_s0(&mut store, vec![decision("propose_section", s0_offsets())]).unwrap();
    assert_eq!(result["outcome"], "not_kept");
    assert_eq!(result["not_kept_fit_change"], -0.02);
    assert_eq!(result["edits"][0]["kept"], false);
    let revision_id = result["revision_id"].as_str().unwrap().to_string();
    let forced = revision::force_keep(&mut store, &revision_id).unwrap();
    assert_eq!(forced["operator_forced"], true);
    assert_eq!(forced["engineering_approved"], false);
    assert_eq!(forced["edits"][0]["applied"], true);
    let recorded = events_of(&store, revision::FORCED_EVENT);
    assert_eq!(recorded[0]["actor"], "human_operator");
    assert!(!store.state.engineering_approved);
    assert_eq!(
        revision::force_keep(&mut store, &revision_id).unwrap_err(),
        "revision_already_forced"
    );
    assert_eq!(
        revision::force_keep(&mut store, "revision-unknown").unwrap_err(),
        "unknown_revision"
    );
    store.verify(false).unwrap();
}

#[test]
fn an_invalid_revision_request_changes_nothing() {
    let _serial = serial();
    let (_directory, mut store) = prepared(json!({}));
    let before = store.events.len();
    for (value, code) in [
        (
            json!({"schema_version":revision::REQUEST_SCHEMA,"instruction":"Smoother","target_section_ids":["s9"]}),
            "unknown_section_id",
        ),
        (
            json!({"schema_version":revision::REQUEST_SCHEMA,"instruction":"","target_section_ids":["s0"]}),
            "revision_instruction",
        ),
        (
            json!({"schema_version":revision::REQUEST_SCHEMA,"instruction":"Smoother","station_range_m":[90.0,99.0]}),
            "revision_range_has_no_sections",
        ),
    ] {
        let error =
            revision::revise_with(&mut store, revision_request(value), &mut scripted(vec![]))
                .unwrap_err();
        assert_eq!(error, code);
    }
    assert_eq!(store.events.len(), before);
}
