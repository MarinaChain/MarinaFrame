//! End to end on a real draft: the app backend starts a run on an ambiguous drawing
//! (the app builds a draft), shows the guess, and a person confirms it with
//! `choose_line`; the controller then rebuilds, validates and reaches review.
//! Needs `MARINAFRAME_TEST_PYTHON`. Set `MARINAFRAME_DUMP_DIR` to also write the
//! views, events and artifacts as JSON and files (used to make UI screenshots).
mod support;

use marinaframe_app_core::types::*;
use marinaframe_app_core::{AppPaths, Backend};
use std::path::{Path, PathBuf};
use std::process::Command;

fn repo_root() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("../..")
        .canonicalize()
        .unwrap()
}

fn dump(backend: &Backend, task: &str, view: &TaskView, name: &str) {
    let Ok(dir) = std::env::var("MARINAFRAME_DUMP_DIR") else {
        return;
    };
    let dir = PathBuf::from(dir);
    std::fs::create_dir_all(&dir).unwrap();
    let events = backend.get_events(task, 0).unwrap();
    let both = serde_json::json!({"view": view, "events": events});
    std::fs::write(dir.join(format!("{name}.json")), both.to_string()).unwrap();
    if let Some(page) = &view.source_page {
        std::fs::copy(Path::new(task).join(&page.path), dir.join("page.png")).unwrap();
    }
    if let Some(model) = &view.model {
        let file = Path::new(&model.stl_path).file_name().unwrap();
        std::fs::copy(Path::new(task).join(&model.stl_path), dir.join(file)).unwrap();
    }
}

#[test]
#[ignore = "real CAD (slow): run with make test-full"]
fn draft_run_shows_its_guess_and_confirming_it_reaches_review() {
    let Some(python) = support::worker_python() else {
        return;
    };
    let repo = repo_root();
    let tmp = tempfile::tempdir().unwrap();
    let input = tmp.path().join("input");
    let made = Command::new(&python)
        .args(["tests/rust_draft_worker.py", "make-drawing"])
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
    // These tests cover the deterministic flow; never call the model.
    settings.ai_drafting = false;
    backend.set_settings(settings).unwrap();

    let task = backend
        .start_run(input.join("spec.json").to_str().unwrap())
        .unwrap();
    let draft = support::wait_until_idle(&backend, &task);
    dump(&backend, &task, &draft, "draft-before");

    // The ambiguous section is a guess; the others are chosen.
    assert_eq!(
        draft.summary.status,
        Status::Draft,
        "{:?} {:?} {:?}",
        draft.notices,
        draft.evidence["termination_reason"],
        backend.get_events(&task, 0).unwrap()
    );
    let guessed: Vec<&SectionView> = draft
        .sections
        .iter()
        .filter(|s| s.state == SectionState::Guessed)
        .collect();
    assert_eq!(guessed.len(), 1, "{:?}", draft.sections);
    let section = guessed[0];
    let guess = section.guess.as_ref().expect("guess");
    assert_eq!(guess.kind, GuessKind::BestCandidate);
    assert!(!guess.alternatives.is_empty() && guess.score.is_some());
    let kept = guess.chosen_candidate_id.clone().expect("guessed line");
    assert!(section.candidates.iter().any(|c| c.id == kept && c.chosen));
    let model = draft.model.clone().expect("draft model");
    assert!(
        model.stl_path.ends_with("model-draft.stl"),
        "{}",
        model.stl_path
    );
    assert_eq!(
        backend.read_artifact(&task, &model.stl_path).unwrap().mime,
        "model/stl"
    );
    let banner = draft
        .notices
        .iter()
        .find(|n| n.id == "draft-guesses:1")
        .expect("draft banner");
    assert!(banner.text.starts_with("Draft: 1 guess to check."));
    assert_eq!(draft.draft.as_ref().unwrap().guesses.len(), 1);
    let texts: Vec<String> = backend
        .get_events(&task, 0)
        .unwrap()
        .into_iter()
        .map(|e| e.text)
        .collect();
    assert!(
        texts.contains(&"Built a draft: 1 section guessed".to_string()),
        "{texts:?}"
    );

    // Confirm the guessed line. The controller rebuilds, renders and validates.
    backend.choose_line(&task, &section.id, &kept).unwrap();
    let after = support::wait_until_idle(&backend, &task);
    dump(&backend, &task, &after, "draft-after");
    assert_eq!(
        after.summary.status,
        Status::NeedsReview,
        "{:?}",
        after.notices
    );
    assert!(after.draft.is_none());
    assert!(after
        .sections
        .iter()
        .all(|s| s.state == SectionState::Chosen));
    assert!(after
        .model
        .as_ref()
        .unwrap()
        .stl_path
        .ends_with("/model.stl"));
    let last: Vec<String> = backend
        .get_events(&task, 0)
        .unwrap()
        .into_iter()
        .map(|e| e.text)
        .collect();
    assert!(
        last.iter()
            .any(|t| t.starts_with("You confirmed the line for")),
        "{last:?}"
    );
}
