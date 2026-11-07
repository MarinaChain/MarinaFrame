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
            (4, "You picked lines", EventKind::Choose),
            (5, "Rendered the body view of the model", EventKind::Render),
            (6, "Declined: two lines fit", EventKind::Finish),
        ]
    );
    assert_eq!(all[0].time_ms, 1001);
    assert_eq!(get_events(task, 4).len(), 2);
    assert!(get_events(task, 7).is_empty());
}

#[test]
fn draft_timeline_says_how_many_sections_were_guessed_and_what_you_confirmed() {
    let tmp = tempfile::tempdir().unwrap();
    let task = tmp.path();
    std::fs::create_dir_all(task.join("domain/input")).unwrap();
    std::fs::create_dir(task.join("events")).unwrap();
    std::fs::write(
        task.join("domain/input/spec.json"),
        json!({"sections":[{"id":"s0","x_m":0.0},{"id":"s2","x_m":4.0}]}).to_string(),
    )
    .unwrap();
    let guesses = json!([
        {"section_id":"s0","chosen_candidate_id":"a"},
        {"section_id":"s2","chosen_candidate_id":"b"},
        {"section_id":"s9","chosen_candidate_id":null}]);
    write(
        task,
        1,
        "draft_built",
        json!({"guesses":guesses}),
        "running",
    );
    write(
        task,
        2,
        "task_terminated",
        json!({"reason":"draft_built_with_open_guesses"}),
        "draft_not_verified",
    );
    let picks = json!({"actor":"human_operator","decision":{"tool":"select_contours","arguments":{"selections":[
        {"section_id":"s2","candidate_id":"b"},{"section_id":"s0","candidate_id":"other"}]},"reason":"r"}});
    write(task, 3, "decision", picks, "running");
    // Already resolved: a later pick on s2 is an ordinary pick.
    let again = json!({"actor":"human_operator","decision":{"tool":"select_contours","arguments":{"selections":[
        {"section_id":"s2","candidate_id":"b"}]},"reason":"r"}});
    write(task, 4, "decision", again, "running");
    let texts: Vec<String> = get_events(task, 0).into_iter().map(|e| e.text).collect();
    assert_eq!(
        texts,
        vec![
            "Built a draft: 3 sections guessed",
            "You confirmed the line for 4.0 m; You picked another line for 0.0 m",
            "You picked the line at 4.0 m",
        ]
    );
    // Reading only the newer events gives the same lines.
    assert_eq!(get_events(task, 2).len(), 2);
    assert_eq!(get_events(task, 2)[0].text, texts[1]);
}

#[test]
fn timeline_picks_and_reads_show_station_positions_not_section_ids() {
    let tmp = tempfile::tempdir().unwrap();
    let task = tmp.path();
    std::fs::create_dir_all(task.join("domain/input")).unwrap();
    std::fs::create_dir(task.join("events")).unwrap();
    let sections: Vec<_> = (0..12)
        .map(|i| json!({"id":format!("s{i}"),"x_m":i as f64 * 2.0}))
        .collect();
    std::fs::write(
        task.join("domain/input/spec.json"),
        json!({"sections":sections}).to_string(),
    )
    .unwrap();
    let pick = |ids: &[&str]| {
        json!({"actor":"human_operator","decision":{"tool":"select_contours","arguments":{"selections":
            ids.iter().map(|id| json!({"section_id":id,"candidate_id":"c"})).collect::<Vec<_>>()
        },"reason":"r"}})
    };
    write(task, 1, "decision", pick(&["s1"]), "running");
    write(task, 2, "decision", pick(&["s0", "s1", "s2"]), "running");
    let many: Vec<String> = (0..12).map(|i| format!("s{i}")).collect();
    let many: Vec<&str> = many.iter().map(String::as_str).collect();
    write(task, 3, "decision", pick(&many), "running");
    write(
        task,
        4,
        "decision",
        json!({"actor":"deterministic_policy","decision":{"tool":"inspect_source",
            "arguments":{"section_ids":["s0","s1","s2"]},"reason":"r"}}),
        "running",
    );
    let texts: Vec<String> = get_events(task, 0).into_iter().map(|e| e.text).collect();
    assert_eq!(
        texts,
        vec![
            "You picked the line at 2.0 m",
            "You picked lines at 0.0 m, 2.0 m and 4.0 m",
            "You picked lines at 12 stations",
            "Read the sections at 0.0 m, 2.0 m and 4.0 m",
        ]
    );
    // No raw section id reaches the timeline.
    assert!(texts
        .iter()
        .all(|t| !(0..12).any(|i| t.contains(&format!("s{i}")))));
}
