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
    let spec = json!({"sections":[
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
