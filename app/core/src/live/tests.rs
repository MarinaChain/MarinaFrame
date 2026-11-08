use super::*;
use serde_json::{json, Value};
use std::fs;

/// A task folder written event by event, in the ledger's file format.
struct Ledger {
    dir: tempfile::TempDir,
    next: u64,
    time: u64,
}

impl Ledger {
    fn new() -> Self {
        let dir = tempfile::tempdir().unwrap();
        fs::create_dir_all(dir.path().join("events")).unwrap();
        let spec = json!({"sections": [
            {"id": "s01", "x_m": 10.0, "roi_px": [100, 100, 500, 500],
             "calibration": {"centerline_px": 120.0, "baseline_px": 480.0, "pixels_per_metre": 20.0}},
            {"id": "s02", "x_m": 20.0, "roi_px": [600, 100, 1000, 500]}
        ]});
        write(&dir.path().join("domain/input/spec.json"), &spec);
        Ledger {
            dir,
            next: 1,
            time: 1_000_000,
        }
    }

    fn task(&self) -> &Path {
        self.dir.path()
    }

    /// Append one event 500 ms after the previous one; returns its sequence.
    fn push(&mut self, kind: &str, payload: Value) -> u64 {
        let sequence = self.next;
        let event = json!({
            "kind": kind, "payload": payload, "sequence": sequence,
            "state_after": {"status": "running", "domain": {"large": "ignored"}},
            "time_ms": self.time,
        });
        write(
            &self.task().join(format!("events/{sequence:08}.json")),
            &event,
        );
        self.next += 1;
        self.time += 500;
        sequence
    }

    fn model_step(&mut self, tool: &str, arguments: Value, reason: &str) -> u64 {
        self.push("provider_intent", json!({"request_id": "r"}));
        self.push(
            "provider_result",
            json!({"receipt": {"usage": {"list_cost": 0.002}}}),
        );
        self.push(
            "decision",
            json!({"actor": "live_model", "decision": {
                "tool": tool, "arguments": arguments, "reason": reason, "notes": "plan"}}),
        )
    }

    fn worker(&mut self, operation: &str, result: Value) -> u64 {
        self.push("worker_intent", json!({"operation": operation}));
        self.push(
            "worker_result",
            json!({"operation": operation, "response": {
                "execution_state": "completed", "result": result,
                "domain": {"current_candidate": {"path": "domain/builds/r0001-abc", "revision_id": "r0001"}}}}),
        )
    }
}

fn write(path: &Path, value: &Value) {
    fs::create_dir_all(path.parent().unwrap()).unwrap();
    fs::write(path, value.to_string()).unwrap();
}

fn label_view() -> Value {
    json!({"status": "viewed", "ok": true, "view": {
        "view_id": "view-1", "crop_box_px": [100, 100, 500, 500],
        "view_px_per_source_px": [2.0, 2.0], "pixel_size": [800, 800]}})
}

#[test]
fn a_refused_corridor_maps_to_sheet_pixels_and_turns_amber() {
    let mut ledger = Ledger::new();
    ledger.push("task_created", json!({}));
    ledger.model_step(
        "read_region",
        json!({"region_px": [100, 100, 500, 500], "subject": "labels"}),
        "Read the station labels.",
    );
    ledger.worker("read_region", label_view());
    let corridor = ledger.model_step(
        "trace_corridor",
        json!({"section_id": "s01", "view_id": "view-1", "half_width_px": 10,
               "path_px": [[0, 0], [200, 400]]}),
        "Trace the s01 ink.",
    );
    ledger.worker(
        "trace_corridor",
        json!({"status": "proposal_refused", "ok": false, "error_code": "no_ink_in_corridor",
               "message": "Ink on 30 of 214 corridor rows."}),
    );

    let store = LiveStore::default();
    let live = store.steps(ledger.task(), 0);
    assert_eq!(live.steps[0].kind, StepKind::System);
    let read = &live.steps[1];
    assert_eq!(read.kind, StepKind::Read);
    assert_eq!(read.title, "Read the labels");
    assert_eq!(read.text, "Read the station labels.");
    assert_eq!(read.attention_px, Some([100.0, 100.0, 500.0, 500.0]));
    assert_eq!(read.model_ms, Some(500));
    assert_eq!(read.cost_usd, Some(0.002));

    let step = live.steps.iter().find(|s| s.sequence == corridor).unwrap();
    assert_eq!(step.kind, StepKind::Refused);
    assert_eq!(step.notes.as_deref(), Some("plan"));
    let band = &step.marks[0];
    assert_eq!(band.shape, MarkShape::Band);
    assert_eq!(band.tone, Tone::Refused);
    // View pixels / 2 + crop origin.
    assert_eq!(band.points_px, vec![[100.0, 100.0], [200.0, 300.0]]);
    assert_eq!(band.half_width_px, Some(5.0));
    assert_eq!(
        band.label.as_deref(),
        Some("Refused: Ink on 30 of 214 corridor rows.")
    );
    let card = step.tool.as_ref().unwrap();
    assert_eq!(card.state, ResultState::Refused);
    assert_eq!(card.duration_ms, Some(500));
    assert_eq!(step.targets[0].id, "s01");
    assert_eq!(step.targets[1].id, "view-1");
    assert!(live.finished.eq(&false) && live.in_flight.is_none());
}

#[test]
fn reads_only_new_events_and_resends_steps_that_changed() {
    let mut ledger = Ledger::new();
    ledger.push("task_created", json!({}));
    let decision = ledger.model_step(
        "enumerate_strokes",
        json!({"section_id": "s01"}),
        "List the strokes.",
    );
    ledger.push("worker_intent", json!({"operation": "enumerate_strokes"}));

    let store = LiveStore::default();
    let first = store.steps(ledger.task(), 0);
    let working = first.steps.last().unwrap();
    assert_eq!(working.sequence, decision);
    assert_eq!(working.tool.as_ref().unwrap().state, ResultState::Working);
    assert_eq!(working.attention_px, Some([100.0, 100.0, 500.0, 500.0]));
    let in_flight = first.in_flight.unwrap();
    assert_eq!(in_flight.kind, InFlightKind::Worker);
    assert_eq!(in_flight.operation.as_deref(), Some("enumerate_strokes"));

    // An event already read is never parsed again: corrupt it to prove it.
    fs::write(ledger.task().join("events/00000001.json"), "not json").unwrap();
    ledger.push(
        "worker_result",
        json!({"operation": "enumerate_strokes", "response": {"execution_state": "completed",
            "result": {"status": "strokes_enumerated", "section_id": "s01", "strokes": [
                {"tag": 1, "candidate_id": "trace-a", "top_end_px": [200, 120], "bottom_end_px": [210, 480]},
                {"tag": 2, "candidate_id": "trace-b", "top_end_px": [300, 120], "bottom_end_px": [310, 480]}]}}}),
    );
    let next = store.steps(ledger.task(), first.last_sequence);
    assert_eq!(next.steps.len(), 1, "only the step that changed");
    let done = &next.steps[0];
    assert_eq!(done.sequence, decision);
    assert_eq!(done.title, "Listed 2 strokes in the s01 panel");
    assert_eq!(done.marks.len(), 2);
    assert_eq!(done.marks[1].tag, Some(2));
    assert_eq!(
        done.marks[1].points_px,
        vec![[300.0, 120.0], [310.0, 480.0]]
    );
    assert_eq!(done.marks[1].tone, Tone::Stroke);
    assert_eq!(next.last_sequence, ledger.next - 1);
    assert!(next.in_flight.is_none());
    // The first call's steps are still there for a full read.
    assert_eq!(store.steps(ledger.task(), 0).steps[0].title, "Run started");
}

#[test]
fn repeated_steps_collapse_with_a_count() {
    let mut ledger = Ledger::new();
    let arguments = json!({"section_id": "s01"});
    let first = ledger.model_step("enumerate_strokes", arguments.clone(), "List strokes.");
    ledger.worker(
        "enumerate_strokes",
        json!({"status": "strokes_enumerated", "strokes": []}),
    );
    ledger.model_step(
        "read_region",
        json!({"region_px": [100, 100, 500, 500], "subject": "labels"}),
        "Read.",
    );
    ledger.worker("read_region", label_view());
    // The same loop twice more, then the controller refuses a fourth time.
    for _ in 0..2 {
        ledger.model_step(
            "enumerate_strokes",
            arguments.clone(),
            "List strokes again.",
        );
        ledger.worker(
            "enumerate_strokes",
            json!({"status": "strokes_enumerated", "strokes": []}),
        );
        ledger.model_step(
            "read_region",
            json!({"region_px": [100, 100, 500, 500], "subject": "labels"}),
            "Read again.",
        );
        ledger.worker("read_region", label_view());
    }
    ledger.push(
        "repeated_action_refused",
        json!({"earlier_decision_event_id": first, "decision": {"tool": "enumerate_strokes",
               "arguments": arguments, "reason": "List strokes once more."}}),
    );

    let steps = LiveStore::default().steps(ledger.task(), 0).steps;
    let kinds: Vec<StepKind> = steps.iter().map(|s| s.kind).collect();
    assert_eq!(
        kinds,
        vec![
            StepKind::Strokes,
            StepKind::Read,
            StepKind::RepeatCollapsed,
            StepKind::RepeatCollapsed
        ]
    );
    let strokes_again = &steps[2];
    assert_eq!(strokes_again.repeat_of, Some(first));
    assert_eq!(strokes_again.count, 4);
    assert_eq!(
        strokes_again.title,
        "Listed 0 strokes in the s01 panel (4 times)"
    );
    let card = strokes_again.tool.as_ref().unwrap();
    assert_eq!(card.state, ResultState::Refused);
    assert_eq!(card.text, "Same step again, refused");
    assert_eq!(steps[3].count, 3);
}

#[test]
fn a_declined_build_closes_and_the_next_build_is_not_a_repeat() {
    let mut ledger = Ledger::new();
    write_build(ledger.task(), "r0002-def");
    let declined = ledger.model_step("build_draft", json!({}), "Build now.");
    ledger.push(
        "missing_sections_hint",
        json!({"section_ids": ["s01", "s02"]}),
    );
    let built = ledger.model_step("build_draft", json!({}), "Build now.");
    ledger.worker(
        "build_draft",
        json!({"status": "review_required", "ok": true, "candidate": {
            "path": "domain/builds/r0002-def", "revision_id": "r0002", "combined_fit": 0.5}}),
    );
    let steps = LiveStore::default().steps(ledger.task(), 0).steps;
    assert_eq!(steps.len(), 2);
    assert_eq!(steps[0].sequence, declined);
    assert_eq!(steps[0].kind, StepKind::Refused);
    let card = steps[0].tool.as_ref().unwrap();
    assert_eq!(card.text, "Not run: 2 sections have no line yet");
    assert_eq!(steps[1].sequence, built);
    assert_eq!(steps[1].kind, StepKind::Build);
    assert_eq!(
        steps[1].revision.as_ref().unwrap().id.as_deref(),
        Some("r0002")
    );
}

fn write_build(task: &Path, folder: &str) {
    let curve: Vec<[f64; 2]> = (0..=200)
        .map(|i| [i as f64 / 50.0, i as f64 / 20.0])
        .collect();
    write(
        &task.join(format!("domain/builds/{folder}/result.json")),
        &json!({"sections": [
            {"id": "s01", "x_m": 10.0, "points_yz_m": curve, "source_label": "traced"},
            {"id": "s02", "x_m": 20.0, "points_yz_m": [[0.0, 0.0], [1.0, 5.0]], "source_label": "ai_inferred"}
        ]}),
    );
}

#[test]
fn builds_and_scores_carry_section_curves() {
    let mut ledger = Ledger::new();
    write_build(ledger.task(), "r0001-abc");
    let build = ledger.worker(
        "build_first_hull",
        json!({"status": "first_hull_built", "ok": true, "candidate": {
            "path": "domain/builds/r0001-abc", "revision_id": "r0001", "combined_fit": 0.81}}),
    );
    ledger.model_step("render_candidate", json!({"view": "body"}), "Compare.");
    ledger.worker(
        "render_candidate",
        json!({"status": "rendered", "rendered_revision_id": "r0001", "fit_score": {
            "combined_fit": 0.81, "station_ink_fit": {"s01": {"rms_m": 0.123456}}}}),
    );
    ledger.model_step(
        "propose_section",
        json!({"section_id": "s01", "form": "blend"}),
        "s01 has no usable trace.",
    );
    ledger.worker(
        "propose_section",
        json!({"status": "kept_previous_curve", "section_id": "s01",
               "curve_summary_yz_m": [[0.0, 0.0], [2.0, 4.0]],
               "fit_comparison": {"fit_before": 0.81, "fit_after": 0.8, "keep": false}}),
    );

    let store = LiveStore::default();
    let steps = store.steps(ledger.task(), 0).steps;
    let built = steps.iter().find(|s| s.last_sequence == build).unwrap();
    assert_eq!(built.kind, StepKind::Build);
    assert_eq!(built.actor, Actor::Code);
    let revision = built.revision.as_ref().unwrap();
    assert_eq!(revision.id.as_deref(), Some("r0001"));
    assert_eq!(revision.fit, Some(0.81));
    assert_eq!(revision.sections[0].points_yz_m.len(), 64);
    assert_eq!(revision.sections[0].points_yz_m[63], [4.0, 10.0]);
    assert_eq!(
        revision.sections[1].source_label.as_deref(),
        Some("ai_inferred")
    );

    let score = steps.iter().find(|s| s.kind == StepKind::Score).unwrap();
    let scored = score.revision.as_ref().unwrap();
    assert_eq!(scored.path.as_deref(), Some("domain/builds/r0001-abc"));
    assert_eq!(scored.sections[0].ink_rms_m, Some(0.1235));
    assert_eq!(scored.sections[1].ink_rms_m, None);
    // The build step already carried these curves.
    assert!(scored.sections[0].points_yz_m.is_empty());
    assert_eq!(score.tool.as_ref().unwrap().text, "Fit 0.8100");

    let proposed = steps.last().unwrap();
    assert_eq!(proposed.kind, StepKind::ProposeSection);
    let card = proposed.tool.as_ref().unwrap();
    assert_eq!(card.kept, Some(false));
    assert_eq!(card.text, "Not kept: fit 0.8100 to 0.8000");
    // Calibration of s01: centre 120, baseline 480, 20 px per metre.
    let drawn = &proposed.marks[0];
    assert_eq!(drawn.tone, Tone::Authored);
    assert_eq!(drawn.points_px, vec![[120.0, 480.0], [160.0, 400.0]]);

    let hull = store.hull_sections(ledger.task(), "r0001").unwrap();
    assert_eq!(hull.path, "domain/builds/r0001-abc");
    assert_eq!(hull.sections.len(), 2);
    let by_path = store
        .hull_sections(ledger.task(), "domain/builds/r0001-abc")
        .unwrap();
    assert_eq!(by_path.sections, hull.sections);
    assert_eq!(
        store
            .hull_sections(ledger.task(), "r0009")
            .unwrap_err()
            .code,
        "revision_not_found"
    );
    assert!(store
        .hull_sections(ledger.task(), "domain/builds/../../etc")
        .is_err());
}

#[test]
fn hull_sections_fall_back_to_the_worker_catalog() {
    let ledger = Ledger::new();
    write_build(ledger.task(), "first-xyz");
    write(
        &ledger.task().join("domain/state.json"),
        &json!({"builds": [{"revision_id": "r0000", "path": "domain/builds/first-xyz"}]}),
    );
    let hull = LiveStore::default()
        .hull_sections(ledger.task(), "r0000")
        .unwrap();
    assert_eq!(hull.revision.as_deref(), Some("r0000"));
    assert_eq!(hull.path, "domain/builds/first-xyz");
}

#[test]
fn text_never_carries_host_paths_or_receipt_bodies() {
    let mut ledger = Ledger::new();
    ledger.push(
        "provider_result",
        json!({"receipt": {"endpoint": "https://example.invalid/v1", "usage": {"list_cost": 0.01},
               "credential_selection": {"slot": 1}}}),
    );
    ledger.push(
        "decision",
        json!({"actor": "live_model", "decision": {"tool": "view_region",
            "arguments": {"region_px": [0, 0, 10, 10]},
            "reason": "Open /Users/someone/runs/task/source.png and C:\\temp\\x.png now."}}),
    );
    ledger.worker(
        "view_region",
        json!({"status": "proposal_refused", "message": "Missing (/home/a/b.json).",
               "artifacts": [
                   {"kind": "model_observation", "mime_type": "image/png", "path": "domain/views/a.png"},
                   {"kind": "model_observation", "mime_type": "image/png", "path": "/etc/passwd.png"},
                   {"kind": "model_observation", "mime_type": "image/png", "path": "domain/../x.png"}]}),
    );
    let live = LiveStore::default().steps(ledger.task(), 0);
    let text = serde_json::to_string(&live).unwrap();
    for leaked in [
        "/Users/",
        "/home/",
        "C:\\",
        "example.invalid",
        "credential",
        "/etc/",
    ] {
        assert!(!text.contains(leaked), "{leaked} leaked: {text}");
    }
    let step = live.steps.last().unwrap();
    assert_eq!(step.text, "Open [path] and [path] now.");
    assert_eq!(step.images, vec!["domain/views/a.png"]);
    assert_eq!(step.cost_usd, Some(0.01));
}

#[test]
fn terminating_ends_the_run_and_resuming_reopens_it() {
    let mut ledger = Ledger::new();
    ledger.push("task_created", json!({}));
    ledger.push("context_compacted", json!({}));
    ledger.push("context_compacted", json!({}));
    let event = json!({"kind": "task_terminated",
        "payload": {"reason": "repeated_identical_action_without_generation_progress"},
        "state_after": {"status": "draft_not_verified"}, "time_ms": 2_000_000});
    write(&ledger.task().join("events/00000004.json"), &event);
    let store = LiveStore::default();
    let live = store.steps(ledger.task(), 0);
    assert!(live.finished);
    assert_eq!(live.elapsed_ms, 1_000_000);
    let compacted = &live.steps[1];
    assert_eq!(compacted.count, 2);
    let finish = live.steps.last().unwrap();
    assert_eq!(finish.kind, StepKind::Finish);
    assert_eq!(finish.title, "Stopped with a draft to check");
    assert_eq!(finish.text, "The same step kept repeating without progress");
    write(
        &ledger.task().join("events/00000005.json"),
        &json!({"kind": "task_resumed", "payload": {}, "time_ms": 2_000_500}),
    );
    assert!(!store.steps(ledger.task(), 4).finished);
}

#[test]
fn a_replaced_ledger_is_read_from_the_start() {
    let mut ledger = Ledger::new();
    for _ in 0..3 {
        ledger.push("context_compacted", json!({}));
    }
    let store = LiveStore::default();
    assert_eq!(store.steps(ledger.task(), 0).steps[0].count, 3);
    fs::remove_dir_all(ledger.task().join("events")).unwrap();
    fs::create_dir_all(ledger.task().join("events")).unwrap();
    ledger.next = 1;
    ledger.push("task_created", json!({}));
    let fresh = store.steps(ledger.task(), 0);
    assert_eq!(fresh.steps.len(), 1);
    assert_eq!(fresh.steps[0].title, "Run started");
}

fn fixture_task() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR")).join("tests/fixtures/live-shipd/task")
}

/// Real events of a live run (shipd-1-03915, sealed head-to-head), slimmed and
/// scrubbed of host paths.
#[test]
fn real_ledger_gives_strokes_reads_clicks_and_corridors() {
    let live = LiveStore::default().steps(&fixture_task(), 0);
    let step = |sequence: u64| {
        live.steps
            .iter()
            .find(|s| s.sequence == sequence)
            .unwrap_or_else(|| panic!("no step {sequence}"))
    };

    let strokes = step(20);
    assert_eq!(strokes.kind, StepKind::Strokes);
    assert_eq!(strokes.actor, Actor::Model);
    assert_eq!(strokes.title, "Listed 6 strokes in the s01 panel");
    assert!(strokes
        .text
        .starts_with("Station 1 is the only unresolved section"));
    let tags: Vec<u64> = strokes.marks.iter().filter_map(|m| m.tag).collect();
    assert_eq!(tags, vec![1, 2, 3, 4, 5, 6]);
    // Tag 3 is a catalog candidate: its polyline comes from the catalog anchors.
    assert!(strokes.marks[2].points_px.len() > 2);
    assert_eq!(strokes.attention_px, Some([90.0, 120.0, 650.0, 524.0]));
    assert_eq!(strokes.images.len(), 1);

    let read = step(25);
    assert_eq!(read.kind, StepKind::Read);
    assert_eq!(read.attention_px, Some([90.0, 120.0, 650.0, 524.0]));
    assert_eq!(read.tool.as_ref().unwrap().text, "Saw a 1024 x 738 px view");

    // The enumerate and read loop ran three times: one line each for the repeats.
    let repeats: Vec<&LiveStep> = live
        .steps
        .iter()
        .filter(|s| s.kind == StepKind::RepeatCollapsed)
        .collect();
    assert_eq!(repeats[0].repeat_of, Some(20));
    assert_eq!(repeats[0].count, 3);
    assert_eq!(repeats[1].repeat_of, Some(25));
    assert_eq!(repeats[1].count, 3);

    let click = step(65);
    assert_eq!(click.kind, StepKind::Refused);
    let point = &click.marks[0];
    assert_eq!(point.shape, MarkShape::Point);
    assert_eq!(point.tone, Tone::Refused);
    // view-a85d130d0444c9b6: crop [90, 120, 650, 524] at 1.8286 x 1.8267 view px.
    assert_eq!(point.points_px, vec![[363.4, 207.6]]);
    assert_eq!(
        point.label.as_deref(),
        Some("Refused: The stroke at the point is followed for only 3 rows.")
    );
    let clicked_again = live.steps.iter().find(|s| s.repeat_of == Some(65)).unwrap();
    assert_eq!(clicked_again.count, 2);

    let corridor = step(85);
    assert_eq!(corridor.kind, StepKind::Refused);
    assert_eq!(corridor.marks[0].shape, MarkShape::Band);
    assert_eq!(corridor.marks[0].points_px.len(), 10);

    let assign = step(55);
    assert_eq!(assign.kind, StepKind::Assign);
    assert_eq!(
        assign.title,
        "Claimed a line is s01 (\"BODY PLAN STATION 1\")"
    );
    assert_eq!(assign.marks[0].tone, Tone::Accepted);
    assert_eq!(
        assign.tool.as_ref().unwrap().text,
        "Accepted as a guess for a person to confirm"
    );

    let last = live.steps.last().unwrap();
    assert_eq!(last.kind, StepKind::Finish);
    assert!(live.finished);
    let text = serde_json::to_string(&live).unwrap();
    assert!(!text.contains("/Users/") && !text.contains("receipts/"));
}

/// Print the steps of a real run: `MARINAFRAME_LIVE_TASK=<task folder>
/// cargo test -p marinaframe-app-core print_live_steps -- --ignored --nocapture`.
#[test]
#[ignore = "manual: prints the live steps of the task in MARINAFRAME_LIVE_TASK"]
fn print_live_steps() {
    let Ok(task) = std::env::var("MARINAFRAME_LIVE_TASK") else {
        return;
    };
    let started = std::time::Instant::now();
    let store = LiveStore::default();
    let live = store.steps(Path::new(&task), 0);
    let first_ms = started.elapsed().as_millis();
    let started = std::time::Instant::now();
    let again = store.steps(Path::new(&task), live.last_sequence);
    let text = serde_json::to_string_pretty(&live).unwrap();
    println!("{text}");
    eprintln!(
        "steps {} bytes {} first call {first_ms} ms, next call {} ms ({} steps)",
        live.steps.len(),
        serde_json::to_string(&live).unwrap().len(),
        started.elapsed().as_millis(),
        again.steps.len()
    );
}
