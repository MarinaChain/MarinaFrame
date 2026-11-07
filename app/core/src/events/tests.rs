use super::*;
use serde_json::json;

fn write(task: &Path, sequence: u64, kind: &str, payload: Value, status: &str) {
    let event = json!({"sequence":sequence,"kind":kind,"time_ms":1000 + sequence,"payload":payload,
        "state_after":{"status":status}});
    std::fs::write(
        task.join(format!("events/{sequence:08}.json")),
        event.to_string(),
    )
    .unwrap();
}

#[test]
fn timeline_uses_plain_text_skips_noise_and_returns_only_newer_events() {
    let tmp = tempfile::tempdir().unwrap();
    let task = tmp.path();
    std::fs::create_dir(task.join("events")).unwrap();
    let decision = |tool: &str, arguments: Value, actor: &str| json!({"actor":actor,"decision":{"tool":tool,"arguments":arguments,"reason":"r"}});
    write(task, 1, "task_created", json!({}), "ready");
    write(task, 2, "worker_intent", json!({}), "running");
    write(
        task,
        3,
        "decision",
        decision("inspect_source", json!({}), "deterministic_policy"),
        "running",
    );
    write(
        task,
        4,
        "decision",
        decision(
            "select_contours",
            json!({"selections":[{"section_id":"s0","candidate_id":"c"}]}),
            "human_operator",
        ),
        "running",
    );
    write(
        task,
        5,
        "decision",
        decision(
            "render_candidate",
            json!({"view":"body"}),
            "deterministic_policy",
        ),
        "running",
    );
    write(
        task,
        6,
        "decision",
        decision(
            "finish",
            json!({"outcome":"abstain","summary":"two lines fit"}),
            "deterministic_policy",
        ),
        "running",
    );
    write(
        task,
        7,
        "task_terminated",
        json!({"reason":"x"}),
        "abstained",
    );
    let all = get_events(task, 0);
    let texts: Vec<_> = all
        .iter()
        .map(|e| (e.sequence, e.text.as_str(), e.kind))
        .collect();
    assert_eq!(
        texts,
        vec![
            (1, "Run created", EventKind::Other),
            (3, "Read the next sections", EventKind::Read),
            (4, "You picked a line on section s0", EventKind::Choose),
            (5, "Rendered the body view of the model", EventKind::Render),
            (6, "Declined: two lines fit", EventKind::Finish),
        ]
    );
    assert_eq!(all[0].time_ms, 1001);
    assert_eq!(get_events(task, 4).len(), 2);
    assert!(get_events(task, 7).is_empty());
}
