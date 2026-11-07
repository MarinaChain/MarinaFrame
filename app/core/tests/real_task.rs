//! End to end on a real task: start a deterministic run through the backend, read
//! the live view, pick another line, and check dismissed notices.
//! Needs `MARINAFRAME_TEST_PYTHON` (a Python with the worker dependencies). The
//! test skips itself when the variable is missing.
use marinaframe_app_core::types::*;
use marinaframe_app_core::{AppPaths, Backend};
use std::path::{Path, PathBuf};
use std::process::Command;
use std::time::{Duration, Instant};

fn repo_root() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("../..")
        .canonicalize()
        .unwrap()
}

fn wait_until_idle(backend: &Backend, task: &str) -> TaskView {
    let start = Instant::now();
    loop {
        let view = backend.get_task(task).unwrap();
        // A finished action leaves the status at needs_review, declined, failed, paused ...
        if !backend.is_busy(task) {
            return view;
        }
        assert!(
            start.elapsed() < Duration::from_secs(240),
            "run did not finish"
        );
        std::thread::sleep(Duration::from_millis(300));
    }
}

#[test]
fn run_read_choose_and_dismiss() {
    let Ok(python) = std::env::var("MARINAFRAME_TEST_PYTHON") else {
        eprintln!("MARINAFRAME_TEST_PYTHON not set; skipping");
        return;
    };
    let repo = repo_root();
    let tmp = tempfile::tempdir().unwrap();
    let input = tmp.path().join("input");
    let made = Command::new(&python)
        .args(["examples/make_agent_example.py", "--out"])
        .arg(&input)
        .env("PYTHONPATH", repo.join("src"))
        .current_dir(&repo)
        .status()
        .unwrap();
    assert!(made.success());

    let paths = AppPaths {
        config_dir: tmp.path().join("config"),
        data_dir: tmp.path().join("data"),
        repo_root: None,
    };
    let backend = Backend::new(paths, Some(repo.join("src")), None);
    let mut settings = backend.get_settings();
    settings.worker_python = python;
    backend.set_settings(settings).unwrap();
    let mut watcher = backend.watcher();
    assert!(backend.poll_changes(&mut watcher).is_empty());

    let task = backend
        .start_run(input.join("spec.json").to_str().unwrap())
        .unwrap();
    assert!(backend
        .poll_changes(&mut watcher)
        .iter()
        .any(|c| c.task == task));
    assert_eq!(backend.list_tasks().len(), 1);

    let view = wait_until_idle(&backend, &task);
    assert_eq!(view.summary.status, Status::NeedsReview);
    assert_eq!(view.summary.policy, "deterministic");
    assert_eq!(view.sections.len(), 3);
    assert!(view
        .sections
        .iter()
        .all(|s| s.state == SectionState::Chosen));
    assert!(view
        .sections
        .iter()
        .all(|s| s.candidates.iter().any(|c| c.chosen)));
    let polyline_lengths: Vec<usize> = view.sections[0]
        .candidates
        .iter()
        .map(|c| c.polyline_px.len())
        .collect();
    assert!(
        polyline_lengths.iter().all(|n| *n > 2),
        "{polyline_lengths:?}"
    );
    let page = view.source_page.clone().expect("source page");
    assert_eq!((page.width, page.height), (600, 230));
    let model = view.model.clone().expect("model");
    assert!(model.length_m > 3.9 && model.volume_m3.is_some());
    assert!(
        view.checks.iter().all(|c| c.result == CheckResult::Pass),
        "{:?}",
        view.checks
    );
    assert!(view.provider.is_empty());
    assert!(view.notices.iter().any(|n| n.id == "engineering-approval"));
    assert_eq!(view.evidence["engineering_approved"], false);

    let events = backend.get_events(&task, 0).unwrap();
    assert!(events.iter().any(|e| e.kind == EventKind::Build));
    assert!(events
        .iter()
        .any(|e| e.kind == EventKind::Finish && e.text == "Ready for review"));
    let last = events.last().unwrap().sequence;
    assert!(backend.get_events(&task, last).unwrap().is_empty());

    assert_eq!(
        backend.read_artifact(&task, &model.stl_path).unwrap().mime,
        "model/stl"
    );
    assert_eq!(
        backend.read_artifact(&task, &page.path).unwrap().mime,
        "image/png"
    );
    assert!(backend.read_artifact(&task, "../input/spec.json").is_err());
    assert!(backend.get_task(tmp.path().to_str().unwrap()).is_err());

    // Notices stay dismissed for a new backend on the same config folder.
    backend.dismiss_notice("engineering-approval").unwrap();
    let paths = AppPaths {
        config_dir: tmp.path().join("config"),
        data_dir: tmp.path().join("data"),
        repo_root: None,
    };
    let restarted = Backend::new(paths, Some(repo.join("src")), None);
    assert!(restarted
        .get_task(&task)
        .unwrap()
        .notices
        .iter()
        .all(|n| n.id != "engineering-approval"));
    restarted.reset_notices().unwrap();
    assert!(restarted
        .get_task(&task)
        .unwrap()
        .notices
        .iter()
        .any(|n| n.id == "engineering-approval"));

    // Pick another line on the first section; the controller rebuilds and re-validates.
    let section = &view.sections[0];
    let other = section
        .candidates
        .iter()
        .find(|c| !c.chosen && c.selectable)
        .expect("alternative");
    backend.choose_line(&task, &section.id, &other.id).unwrap();
    let after = wait_until_idle(&backend, &task);
    let picked = after.sections[0]
        .candidates
        .iter()
        .find(|c| c.chosen)
        .map(|c| c.id.clone());
    assert_eq!(
        picked.as_deref(),
        Some(other.id.as_str()),
        "status {:?}",
        after.summary.status
    );
    assert_ne!(after.revision, view.revision);
    assert!(backend
        .get_events(&task, last)
        .unwrap()
        .iter()
        .any(|e| e.text.starts_with("You picked")));
}
