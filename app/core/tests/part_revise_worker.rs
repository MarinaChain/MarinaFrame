//! Re-run one whole-vessel part from a mark through the real Python worker
//! (`vessel_reconstruction.part_revise`) and the real ship-cad build, with a scripted model at
//! the provider level: the replies get the checks and receipts of the provider path, and no
//! model request is made. Then undo, re-run again and keep.
//! Needs `MARINAFRAME_TEST_PYTHON` and macOS (the ship-cad sandbox).
//! Local runs may omit the worker Python; CI requires it. Other platforms skip.
mod support;

use marinaframe_app_core::actions::ActionRegistry;
use marinaframe_app_core::intake::Worker;
use marinaframe_app_core::part_revise::{self, ModelChoice, Replies, REVISE_STALL_PERIOD};
use marinaframe_app_core::{parts, AppPaths};
use serde_json::json;
use std::path::{Path, PathBuf};

fn repo_root() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("../..")
        .canonicalize()
        .unwrap()
}

const SQUARE: [[f64; 2]; 4] = [[14.0, -3.5], [21.0, -3.5], [21.0, 3.5], [14.0, 3.5]];

/// A drawing in millimetres with a profile and a plan of one deckhouse (written by ezdxf).
const MAKE_DXF: &str = "import sys, ezdxf
d = ezdxf.new(); m = d.modelspace()
m.add_lwpolyline([(14000, 59000), (21000, 59000), (21000, 61500), (14000, 61500)], close=True)
m.add_lwpolyline([(14000, 16500), (21000, 16500), (21000, 23500), (14000, 23500)], close=True)
d.saveas(sys.argv[1])";

fn make_task(python: &str, root: &Path) -> PathBuf {
    let task = root.join("task");
    let folder = task.join("whole_vessel");
    std::fs::create_dir_all(&folder).unwrap();
    let made = std::process::Command::new(python)
        .args(["-c", MAKE_DXF])
        .arg(task.join("ga.dxf"))
        .status()
        .unwrap();
    assert!(made.success());
    let view = |kind: &str, bounds: [f64; 4], origin: [f64; 2]| {
        json!({"kind": kind, "file": "ga.dxf", "bounds": bounds, "origin": origin,
               "metres_per_unit": 0.001, "layers": null})
    };
    let views = json!({"schema": "whole-vessel-views/v1", "views": {
        "profile": view("profile", [0.0, 45000.0, 40000.0, 65000.0], [0.0, 50000.0]),
        "plan_adeck": view("plan", [0.0, 14000.0, 40000.0, 26000.0], [0.0, 20000.0])}});
    std::fs::write(folder.join("views.json"), views.to_string()).unwrap();
    let execution = json!({"exit_code": 0, "result": {"engineering_approved": false, "components": [
        {"id": "wheelhouse", "op": "deckhouse", "label": "Wheelhouse", "built": true,
         "status": "draft_guess", "geometry": {"outline": SQUARE, "height": [9.0, 11.5]},
         "source_labels": {"outline": "guessed", "height": "traced"},
         "provenance": {"outline": {"source": "guessed", "basis": "tier-2 breadth"}},
         "bbox_m": {"min": [14.0, -3.5, 9.0], "max": [21.0, 3.5, 11.5]}, "volume_m3": 122.5}]}});
    std::fs::write(folder.join("execution.json"), execution.to_string()).unwrap();
    std::fs::write(folder.join("wheelhouse.step"), "old").unwrap();
    task
}

fn reply(half_breadth: f64) -> String {
    let inline = |value: serde_json::Value| json!({"value": value, "source": "ai_inferred", "basis": "scripted test reply"});
    let outline = json!([
        [14.0, -half_breadth],
        [21.0, -half_breadth],
        [21.0, half_breadth],
        [14.0, half_breadth]
    ]);
    json!({"schema": "ship-cad/v1", "components": [{"id": "wheelhouse", "op": "deckhouse",
        "source": {"view": "plan", "region": "wheelhouse", "method": "closed_outline"},
        "args": {"outline": inline(outline), "height": inline(json!([9.0, 11.5]))}}]})
    .to_string()
}

#[test]
fn re_run_a_marked_part_then_undo_and_keep() {
    let Some(python) = support::worker_python() else {
        return;
    };
    if !cfg!(target_os = "macos") {
        eprintln!("the ship-cad worker needs the macOS sandbox; skipping");
        return;
    }
    let tmp = tempfile::tempdir().unwrap();
    let task = make_task(&python, tmp.path());
    let src = repo_root().join("src");
    let worker = Worker {
        python: &python,
        source: Some(&src),
    };
    let paths = AppPaths {
        config_dir: tmp.path().join("config"),
        data_dir: tmp.path().join("data"),
        repo_root: None,
    };
    let registry = ActionRegistry::default();
    let replies = tmp.path().join("replies.json");
    // The first reply is not JSON: it is refused with a typed error and the model is asked again.
    std::fs::write(&replies, json!(["not json", reply(0.5)]).to_string()).unwrap();
    // The model comes from this configuration, not from the worker.
    let model = ModelChoice::new(
        vec!["deepseek-v4.1-flash".into()],
        Replies::Scripted(replies.clone()),
    );
    // The note starts with "-": it must stay the note, not become an option.
    parts::review_component(
        &paths,
        &task,
        "wheelhouse",
        "marked",
        Some("-Make it 1 m wide"),
    )
    .unwrap();

    let part = part_revise::revise_part(
        &registry,
        &paths,
        &task,
        "wheelhouse",
        &worker,
        &model,
        REVISE_STALL_PERIOD,
    )
    .unwrap();
    assert_eq!(
        (
            part.revision,
            part.revision_note.as_deref(),
            part.revision_pending
        ),
        (1, Some("-Make it 1 m wide"), true)
    );
    assert_eq!(part.bbox_m.as_ref().unwrap().max[1], 0.5);
    let outline = part.changes.iter().find(|c| c.name == "outline").unwrap();
    assert_eq!(
        (
            outline.before_source.as_deref(),
            outline.after_source.as_deref()
        ),
        (Some("guessed"), Some("ai_inferred"))
    );
    assert!(part.changes.iter().any(|c| c.name == "volume"));
    assert_eq!(part.review, "marked"); // the mark stays until Keep
    let folder = task.join("whole_vessel");
    assert_eq!(
        std::fs::read_to_string(folder.join("wheelhouse.r0.step")).unwrap(),
        "old"
    );
    let record: serde_json::Value =
        serde_json::from_slice(&std::fs::read(task.join(parts::EXECUTION_FILE)).unwrap()).unwrap();
    assert_eq!(record["result"]["engineering_approved"], json!(false));
    let receipts = record["result"]["components"][0]["revision_receipts"]
        .as_array()
        .unwrap();
    assert_eq!(receipts.len(), 2);
    assert_eq!(receipts[0]["error_code"], "part_program_invalid_json");
    assert!(receipts
        .iter()
        .all(|r| r["requested_model"] == "deepseek-v4.1-flash"));

    let part = part_revise::undo_revision(&registry, &paths, &task, "wheelhouse", &worker).unwrap();
    assert_eq!((part.revision, part.revision_pending), (0, false));
    assert_eq!(part.bbox_m.as_ref().unwrap().max[1], 3.5);
    assert_eq!(
        std::fs::read_to_string(folder.join("wheelhouse.step")).unwrap(),
        "old"
    );

    std::fs::write(&replies, json!([reply(1.0)]).to_string()).unwrap();
    let part = part_revise::revise_part(
        &registry,
        &paths,
        &task,
        "wheelhouse",
        &worker,
        &model,
        REVISE_STALL_PERIOD,
    )
    .unwrap();
    assert_eq!(
        (part.revision, part.bbox_m.as_ref().unwrap().max[1]),
        (1, 1.0)
    );
    let part = part_revise::keep_revision(&registry, &paths, &task, "wheelhouse", &worker).unwrap();
    assert_eq!(
        (part.revision, part.revision_pending, part.review.as_str()),
        (1, false, "open")
    );
    // Nothing is left to undo once kept; the worker says so plainly.
    let refused =
        part_revise::undo_revision(&registry, &paths, &task, "wheelhouse", &worker).unwrap_err();
    assert!(
        refused.message.contains("no new revision"),
        "{}",
        refused.message
    );
    assert!(!registry.is_busy(&task));
}
