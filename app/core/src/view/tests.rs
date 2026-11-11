use super::*;
use std::fs;

/// A task folder in the shape the controller writes it, trimmed to what the view reads.
fn fixture(status: &str) -> tempfile::TempDir {
    let tmp = tempfile::tempdir().unwrap();
    let task = tmp.path().join("task");
    fs::create_dir_all(task.join("domain/input")).unwrap();
    fs::create_dir_all(task.join("events")).unwrap();
    let state = json!({"head_sha256":"h","state":{
        "status":status,"termination_reason":"input:bad_spec","task_id":"t","generation_id":"g","revision_id":"r0001",
        "config":{"source_spec":"/x/ship/spec.json","policy":"deterministic","binary_sha256":"aa","model":"m"},
        "domain":{},"counters":{}}});
    fs::write(task.join("state.json"), state.to_string()).unwrap();
    let candidate = |id: &str, hypothesis: &str, x: f64| {
        json!({
        "candidate_id":id,"hypothesis":hypothesis,"selectable":true,
        "source_support":{"observed_row_fraction":1.0},"non_grid_competing_components":0,
        "contour_selection":{"anchors_px":[[x,30.0],[x,210.0]]}})
    };
    let domain = json!({"selected":{},"inspection_artifacts":[],"catalog":{"s0":{"candidates":[
        candidate("c1","grid_supported_contour_hypothesis",90.0),
        candidate("c2","retained_alternative_source_continuity",110.0)]}}});
    fs::write(task.join("domain/state.json"), domain.to_string()).unwrap();
    let spec = json!({"vessel_id":"ship","sections":[
        {"id":"s0","x_m":0.0,"roi_px":[10,20,195,220]},{"id":"s1","x_m":2.0,"roi_px":[210,20,395,220]}]});
    fs::write(task.join("domain/input/spec.json"), spec.to_string()).unwrap();
    tmp
}

#[test]
fn declined_task_shows_sections_candidates_and_plain_reasons() {
    let tmp = fixture("abstained");
    let view = get_task(&tmp.path().join("task"), &ViewContext::default()).unwrap();
    assert_eq!(view.summary.name, "ship");
    assert_eq!(view.summary.status, Status::Declined);
    assert_eq!(view.sections.len(), 2);
    let s0 = &view.sections[0];
    assert_eq!(s0.state, SectionState::Declined);
    assert_eq!(s0.reason, "Declined: two lines fit equally well.");
    assert_eq!(s0.roi_px, [10, 20, 195, 220]);
    assert_eq!(s0.candidates[0].label, "Main hull line");
    assert_eq!(s0.candidates[1].label, "Other line 1");
    // No evidence file: the anchors give a two-point line.
    assert_eq!(
        s0.candidates[1].polyline_px,
        vec![[110.0, 30.0], [110.0, 210.0]]
    );
    assert_eq!(view.sections[1].state, SectionState::NotRead);
    assert!(view.model.is_none() && view.source_page.is_none() && view.provider.is_empty());
    assert_eq!(view.checks.len(), 1);
    assert_eq!(view.checks[0].result, CheckResult::NotRun);
    assert_eq!(view.evidence["engineering_approved"], false);
}

#[test]
fn run_name_falls_back_to_the_task_folder_name() {
    let tmp = fixture("blocked");
    let task = tmp.path().join("task");
    fs::write(task.join("domain/input/spec.json"), r#"{"sections":[]}"#).unwrap();
    assert_eq!(run_name(&task), "task");
    fs::write(task.join("domain/input/spec.json"), r#"{"vessel_id":"  "}"#).unwrap();
    assert_eq!(run_name(&task), "task");
}

#[test]
fn run_name_prefers_the_vessel_name_typed_at_intake() {
    let tmp = fixture("running");
    let task = tmp.path().join("task");
    fs::write(
        task.join("domain/input/spec.json"),
        r#"{"vessel_id":"dtmb-5415-lines-plan"}"#,
    )
    .unwrap();
    assert_eq!(run_name(&task), "dtmb-5415-lines-plan");
    fs::create_dir_all(task.join("intake")).unwrap();
    fs::write(
        task.join("intake/intake.json"),
        r#"{"particulars":{"vessel_name":" DTMB 5415 "}}"#,
    )
    .unwrap();
    assert_eq!(run_name(&task), "DTMB 5415");
    // An empty typed name falls back to the spec.
    fs::write(
        task.join("intake/intake.json"),
        r#"{"particulars":{"vessel_name":""}}"#,
    )
    .unwrap();
    assert_eq!(run_name(&task), "dtmb-5415-lines-plan");
}

#[test]
fn blinded_benchmark_ids_read_as_names() {
    let tmp = fixture("running");
    let task = tmp.path().join("task");
    fs::write(
        task.join("domain/input/spec.json"),
        r#"{"vessel_id":"factory-70ed8f4700b0"}"#,
    )
    .unwrap();
    assert_eq!(run_name(&task), "Benchmark hull 70ed8f");
    // Not a hash: shown as it is.
    fs::write(
        task.join("domain/input/spec.json"),
        r#"{"vessel_id":"factory-box"}"#,
    )
    .unwrap();
    assert_eq!(run_name(&task), "factory-box");
}

#[test]
fn notices_are_filtered_and_explain_other_builds() {
    let tmp = fixture("blocked");
    let task = tmp.path().join("task");
    let mut context = ViewContext {
        binary_sha256: Some("bb".into()),
        ..Default::default()
    };
    let ids = |view: &TaskView| {
        view.notices
            .iter()
            .map(|n| n.id.clone())
            .collect::<Vec<_>>()
    };
    let all = get_task(&task, &context).unwrap();
    assert_eq!(
        ids(&all),
        vec![
            ENGINEERING_NOTICE_ID,
            "stopped:input:bad_spec",
            "other-build"
        ]
    );
    assert!(all.notices[1]
        .text
        .starts_with("Stopped: the spec has a problem"));
    context
        .dismissed_notices
        .insert(ENGINEERING_NOTICE_ID.into());
    context.action_error = Some("The action could not be completed (x).".into());
    assert_eq!(
        ids(&get_task(&task, &context).unwrap()),
        vec!["stopped:input:bad_spec", "other-build", "action-failed"]
    );
}

#[test]
fn list_finds_task_folders_and_skips_other_folders() {
    let tmp = fixture("running");
    let runs = tmp.path();
    fs::create_dir_all(runs.join("not-a-task")).unwrap();
    let tasks = list_tasks(runs);
    assert_eq!(tasks.len(), 1);
    assert_eq!(tasks[0].status, Status::Running);
}

#[test]
fn statuses_and_long_polylines_map_as_documented() {
    assert_eq!(map_status("awaiting_human_review"), Status::NeedsReview);
    assert_eq!(map_status("validation_failed"), Status::Failed);
    assert_eq!(map_status("interrupted"), Status::Paused);
    assert_eq!(map_status("no_progress"), Status::Blocked);
    let line: Vec<[f64; 2]> = (0..1000).map(|i| [i as f64, 0.0]).collect();
    let short = downsample(&line);
    assert_eq!(short.len(), MAX_POLYLINE_POINTS);
    assert_eq!(short[0], [0.0, 0.0]);
    assert_eq!(*short.last().unwrap(), [999.0, 0.0]);
}

/// A draft task: s0 has a guessed line (two candidates), s1 is a bridged gap,
/// and the build is a draft whose STL is `model-draft.stl`.
fn draft_fixture() -> tempfile::TempDir {
    let tmp = fixture("draft_not_verified");
    let task = tmp.path().join("task");
    let build = task.join("domain/builds/r0002-x");
    fs::create_dir_all(&build).unwrap();
    fs::write(build.join("model-draft.stl"), b"solid x\nendsolid x\n").unwrap();
    fs::write(
        build.join("result.json"),
        json!({"exports":{"stl":"model-draft.stl","step":"model-draft.step"},
            "sections":[{"id":"s0","source_label":"ai_corrected",
                "evidence":{"authored_basis":"Trace crossed the grid."},"warnings":["Fairing moved the curve."],
                "source_record":{"kind":"guessed","method":"Draft ai_corrected section from its drawn curve",
                    "inputs":[{"sheet":"lines.png","page":0,"view":"body plan","box_px":[1,2,30,40],"page_px":[100,80]}]}}],
            "gaps":[{"severity":"warning","kind":"draft_interpolated","section_id":"s1",
                "message":"Missing section interpolated."}]})
        .to_string(),
    )
    .unwrap();
    let guesses = json!([
        {"guess_id":"guess-a","section_id":"s0","kind":"best_candidate","x_m":0.0,"x_range_m":null,
         "chosen_candidate_id":"c1","alternatives":["c2"],"score":0.93,
         "reason":"2 lines found; took the best-supported one (score 0.93).","status":"open"},
        {"guess_id":"guess-b","section_id":"s1","kind":"bridged_gap","x_m":2.0,"x_range_m":[0.0,4.0],
         "chosen_candidate_id":null,"alternatives":[],"score":null,
         "reason":"No readable line at x=2 m; smoothed across x=0 to 4 m.","status":"open"}]);
    let state = json!({"head_sha256":"h","state":{
        "status":"draft_not_verified","termination_reason":"draft_built_with_open_guesses",
        "task_id":"t","generation_id":"g","revision_id":"r0002",
        "config":{"policy":"deterministic","binary_sha256":"aa"},
        "domain":{"open_guesses":guesses,"resolved_guesses":[
            {"guess_id":"guess-old","section_id":"s9","kind":"best_candidate","x_m":6.0,"x_range_m":null,
             "chosen_candidate_id":"k1","alternatives":["k2"],"score":0.8,"reason":"r","status":"resolved",
             "resolution":"replaced","resolved_candidate_id":"k2"}],
          "current_candidate":{"valid":true,"draft":true,"path":"domain/builds/r0002-x",
            "metrics":{"length_m":4.0,"beam_m":2.0,"depth_m":3.0,"volume_m3":10.0}}},"counters":{}}});
    fs::write(task.join("state.json"), state.to_string()).unwrap();
    tmp
}

#[test]
fn draft_task_shows_guessed_sections_draft_model_and_banner() {
    let tmp = draft_fixture();
    let view = get_task(&tmp.path().join("task"), &ViewContext::default()).unwrap();
    assert_eq!(view.summary.status, Status::Draft);
    // The model comes from exports.stl, not a fixed model.stl.
    let model = view.model.expect("draft model");
    assert!(
        model.stl_path.ends_with("/model-draft.stl"),
        "{}",
        model.stl_path
    );
    // s0: guessed line, marked chosen, with its alternatives.
    let s0 = &view.sections[0];
    assert_eq!(s0.state, SectionState::Guessed);
    assert_eq!(
        s0.reason,
        "2 lines found; took the best-supported one (score 0.93)."
    );
    let guess = s0.guess.as_ref().unwrap();
    assert_eq!(guess.kind, GuessKind::BestCandidate);
    assert_eq!(guess.score, Some(0.93));
    assert_eq!(guess.alternatives, vec!["c2".to_string()]);
    assert!(s0.candidates[0].chosen && !s0.candidates[1].chosen);
    // s1: bridged gap, nothing to pick.
    let s1 = &view.sections[1];
    assert_eq!(s1.state, SectionState::Guessed);
    assert_eq!(s1.guess.as_ref().unwrap().x_range_m, Some([0.0, 4.0]));
    assert!(s1.candidates.is_empty());
    // Where each section was read: s0 from its record; s1 has none (no source record).
    assert_eq!(s0.source_record.as_ref().unwrap()["kind"], "guessed");
    assert!(s1.source_record.is_none());
    // Source labels, counts and warnings of the draft build.
    let source = s0.source.as_ref().unwrap();
    assert_eq!(source.label, "ai_corrected");
    assert_eq!(source.basis.as_deref(), Some("Trace crossed the grid."));
    assert_eq!(s1.source.as_ref().unwrap().label, "interpolated");
    let counts: Vec<(&str, usize)> = view
        .source_counts
        .iter()
        .map(|c| (c.label.as_str(), c.count))
        .collect();
    assert_eq!(counts, [("interpolated", 1), ("ai_corrected", 1)]);
    assert_eq!(
        view.warnings,
        [
            "At 2.0 m: Missing section interpolated.",
            "At 0.0 m: Fairing moved the curve."
        ]
    );
    assert!(view.activity.is_none());
    // Draft view and banner.
    let draft = view.draft.expect("draft view");
    assert_eq!(draft.guesses.len(), 2);
    assert_eq!(draft.resolved.len(), 1);
    assert_eq!(draft.resolved[0].resolution, Resolution::Replaced);
    assert_eq!(draft.resolved[0].resolved_candidate_id, "k2");
    let banner = view
        .notices
        .iter()
        .find(|n| n.id == "draft-guesses:2")
        .unwrap();
    assert!(
        banner.text.starts_with("Draft: 2 guesses to check."),
        "{}",
        banner.text
    );
    assert_eq!(
        banner.text,
        "Draft: 2 guesses to check. 1 has a line to confirm or change. 1 has no readable line, so this run stays a draft."
    );
    assert_eq!(view.evidence["engineering_approved"], false);
}

#[test]
fn draft_banner_counts_and_dismissal_follow_the_open_guesses() {
    let tmp = draft_fixture();
    let task = tmp.path().join("task");
    let mut context = ViewContext::default();
    context.dismissed_notices.insert("draft-guesses:2".into());
    let view = get_task(&task, &context).unwrap();
    assert!(view
        .notices
        .iter()
        .all(|n| !n.id.starts_with("draft-guesses")));
    // The badge stays: the status is still a draft.
    assert_eq!(view.summary.status, Status::Draft);
    // A new count is a new notice id, so the banner returns.
    let mut state: Value =
        serde_json::from_slice(&fs::read(task.join("state.json")).unwrap()).unwrap();
    state["state"]["domain"]["open_guesses"]
        .as_array_mut()
        .unwrap()
        .pop();
    fs::write(task.join("state.json"), state.to_string()).unwrap();
    let view = get_task(&task, &context).unwrap();
    let banner = view
        .notices
        .iter()
        .find(|n| n.id == "draft-guesses:1")
        .unwrap();
    assert!(
        banner.text.starts_with("Draft: 1 guess to check."),
        "{}",
        banner.text
    );
    assert!(!banner.text.contains("stays a draft"));
}

#[test]
fn a_verified_task_has_no_draft_and_keeps_the_verified_model_name() {
    let tmp = fixture("awaiting_human_review");
    let view = get_task(&tmp.path().join("task"), &ViewContext::default()).unwrap();
    assert!(view.draft.is_none());
    assert!(view.sections.iter().all(|s| s.guess.is_none()));
    assert_eq!(map_status("draft_not_verified"), Status::Draft);
    assert_eq!(
        stl_file_name(&tmp.path().join("task"), "domain/builds/none"),
        "model.stl"
    );
}

/// A GA reading run (`ga_commercial.write_app_run`): no build, no sections, the GA as its page.
#[test]
fn a_ga_reading_run_opens_with_its_reading_and_page() {
    let tmp = tempfile::tempdir().unwrap();
    let task = tmp.path().join("task");
    fs::create_dir_all(task.join("domain")).unwrap();
    fs::create_dir_all(task.join("ga_reading")).unwrap();
    let state = json!({"state":{"task_id":"GA-X","status":"awaiting_human_review","kind":"ga_reading",
        "engineering_approved":false,"config":{"source_spec":"/GA-X/spec.json","policy":"deterministic","model":"claude-sonnet-5-5"}}});
    fs::write(task.join("state.json"), state.to_string()).unwrap();
    let domain =
        json!({"inspection_artifacts":[{"kind":"source_page","path":"ga_reading/X_GA.png"}]});
    fs::write(task.join("domain/state.json"), domain.to_string()).unwrap();
    fs::write(task.join("ga_reading/X_GA.png"), png_header(40, 20)).unwrap();
    let reading = json!({"schema":crate::ga_reading::SCHEMA,"engineering_approved":false,
        "particulars":{},"counts":{},"spaces":[]});
    fs::write(
        task.join(crate::ga_reading::READING_FILE),
        reading.to_string(),
    )
    .unwrap();
    let view = get_task(&task, &ViewContext::default()).unwrap();
    assert!(view.ga_reading.is_some());
    let page = view.source_page.unwrap();
    assert_eq!(
        (page.path.as_str(), page.width, page.height),
        ("ga_reading/X_GA.png", 40, 20)
    );
    assert!(view.model.is_none() && view.sections.is_empty());
}

/// A minimal PNG header of `width` x `height` (the view reads only its header).
fn png_header(width: u32, height: u32) -> Vec<u8> {
    let mut bytes = b"\x89PNG\r\n\x1a\n\0\0\0\rIHDR".to_vec();
    bytes.extend_from_slice(&width.to_be_bytes());
    bytes.extend_from_slice(&height.to_be_bytes());
    bytes.extend_from_slice(&[8, 0, 0, 0, 0, 0, 0, 0, 0]);
    bytes
}
