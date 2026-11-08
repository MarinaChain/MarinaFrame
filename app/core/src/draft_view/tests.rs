use super::*;
use serde_json::json;
use std::fs;

fn write_event(task: &Path, sequence: u64, kind: &str, payload: Value) {
    let event = json!({"sequence":sequence,"kind":kind,"time_ms":1,"payload":payload});
    fs::write(
        task.join(format!("events/{sequence:08}.json")),
        event.to_string(),
    )
    .unwrap();
}

fn record() -> Value {
    json!({
    "sections":[
        {"id":"s0","source_label":"traced"},
        {"id":"s1","source_label":"repaired"},
        {"id":"s2","source_label":"ai_inferred","evidence":{"authored_basis":"Blend of s1 and s3."},
         "warnings":["Fairing moved the curve by up to 0.020 m."]},
        {"id":"s3","source_label":"ai_corrected","evidence":{"authored_basis":"Trace crossed the grid."},"warnings":[]},
        {"id":"s4"}
    ],
    "gaps":[
        {"severity":"warning","kind":"draft_repaired","section_id":"s1","message":"Centreline breadth clamped."},
        {"severity":"warning","kind":"draft_repaired","section_id":"s1","message":"Centreline breadth clamped."},
        {"severity":"blocking","kind":"x","message":"Blocking is not listed."}
    ]})
}

#[test]
fn labels_basis_and_counts_follow_the_build_record() {
    let guesses = vec![
        ("s5".to_string(), GuessKind::BridgedGap),
        ("s6".to_string(), GuessKind::DroppedEnd),
        ("s2".to_string(), GuessKind::ModelAuthored),
    ];
    let sources = draft_sources(&record(), &guesses);
    let label = |id: &str| sources.by_section[id].label.as_str();
    assert_eq!(label("s0"), "traced");
    assert_eq!(label("s4"), "traced", "a section without a label is traced");
    assert_eq!(label("s2"), "ai_inferred");
    assert_eq!(label("s5"), "interpolated");
    assert_eq!(label("s6"), "omitted");
    assert_eq!(
        sources.by_section["s3"].basis.as_deref(),
        Some("Trace crossed the grid.")
    );
    assert_eq!(sources.by_section["s0"].basis, None);
    let counts: Vec<(&str, usize)> = sources
        .counts
        .iter()
        .map(|c| (c.label.as_str(), c.count))
        .collect();
    assert_eq!(
        counts,
        [
            ("traced", 2),
            ("repaired", 1),
            ("interpolated", 1),
            ("ai_inferred", 1),
            ("ai_corrected", 1),
            ("omitted", 1)
        ]
    );
}

#[test]
fn warnings_are_deduplicated_placed_and_leave_out_blocking_gaps() {
    let x: HashMap<String, f64> = [("s1".to_string(), 2.0), ("s2".to_string(), 4.0)].into();
    let warnings = draft_warnings(&record(), &x);
    assert_eq!(
        warnings,
        [
            "At 2.0 m: Centreline breadth clamped.",
            "At 4.0 m: Fairing moved the curve by up to 0.020 m."
        ]
    );
}

#[test]
fn only_a_draft_build_has_a_record() {
    let tmp = tempfile::tempdir().unwrap();
    let task = tmp.path();
    fs::create_dir_all(task.join("builds/b1")).unwrap();
    fs::write(task.join("builds/b1/result.json"), record().to_string()).unwrap();
    assert!(build_record(task, &json!({"path":"builds/b1","draft":true})).is_some());
    assert!(build_record(task, &json!({"path":"builds/b1"})).is_none());
    assert!(build_record(task, &json!({"path":"../x","draft":true})).is_none());
}

#[test]
fn activity_sums_live_steps_and_receipts_from_a_synthetic_event_folder() {
    let tmp = tempfile::tempdir().unwrap();
    let task = tmp.path();
    fs::create_dir(task.join("events")).unwrap();
    let decision = |actor: &str, tool: &str, reason: &str| json!({"actor":actor,"decision":{"tool":tool,"arguments":{},"reason":reason}});
    let receipt = |usage: Value| json!({"receipt":{"state":"completed","usage":usage}});
    write_event(task, 1, "task_created", json!({}));
    write_event(
        task,
        2,
        "decision",
        decision("deterministic_policy", "inspect_source", "policy"),
    );
    write_event(
        task,
        3,
        "decision",
        decision("live_model", "propose_section", "s2 has no ink."),
    );
    write_event(
        task,
        4,
        "provider_result",
        receipt(json!({"prompt_tokens":1000,"completion_tokens":50,"list_cost":0.002})),
    );
    write_event(
        task,
        5,
        "decision",
        decision("live_model", "build_draft", "All sections have a curve."),
    );
    write_event(
        task,
        6,
        "provider_reconciled",
        receipt(json!({"prompt_tokens":1500,"completion_tokens":70,"list_cost":0.003})),
    );
    write_event(task, 7, "provider_not_sent", json!({"request_id":"r"}));
    let activity = model_activity(task).unwrap();
    let steps: Vec<(u64, &str, &str)> = activity
        .steps
        .iter()
        .map(|s| (s.sequence, s.tool.as_str(), s.reason.as_str()))
        .collect();
    assert_eq!(
        steps,
        [
            (3, "propose section", "s2 has no ink."),
            (5, "build draft", "All sections have a curve.")
        ]
    );
    assert_eq!(activity.requests, 2);
    assert_eq!(
        (activity.prompt_tokens, activity.completion_tokens),
        (2500, 120)
    );
    assert!((activity.list_cost_usd - 0.005).abs() < 1e-12);
    assert!(activity.list_cost_complete);

    // A receipt without a list cost makes the total a lower bound, not zero.
    write_event(
        task,
        8,
        "provider_result",
        receipt(json!({"prompt_tokens":10})),
    );
    assert!(!model_activity(task).unwrap().list_cost_complete);
}

#[test]
fn a_deterministic_run_has_no_activity() {
    let tmp = tempfile::tempdir().unwrap();
    let task = tmp.path();
    fs::create_dir(task.join("events")).unwrap();
    write_event(
        task,
        1,
        "decision",
        json!({"actor":"deterministic_policy","decision":{"tool":"inspect_source","reason":"r"}}),
    );
    assert!(model_activity(task).is_none());
    assert!(model_activity(&task.join("missing")).is_none());
}
