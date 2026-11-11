"""Data gates of the web demo build (scripts/build_web_demo.py)."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest
from PIL import Image

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "build_web_demo.py"
spec = importlib.util.spec_from_file_location("build_web_demo", SCRIPT)
build = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build)


def write_selection(tmp_path: Path, runs: list[dict]) -> Path:
    path = tmp_path / "runs.json"
    path.write_text(json.dumps({"runs": runs}))
    return path


def entry(**fields) -> dict:
    return {"slug": "demo-hull", "name": "Demo", "licence": "synthetic", "source": "test", "drawing_sha256": ["a" * 64], **fields}


def test_selection_accepts_allowed_licences(tmp_path):
    assert build.load_selection(write_selection(tmp_path, [entry()]))[0]["slug"] == "demo-hull"


@pytest.mark.parametrize("bad", [
    entry(licence="research-only"),
    entry(licence=None),
    entry(slug="Demo Hull"),
    entry(slug="davis-truth"),
    entry(slug="sealed-case-3"),
])
def test_selection_refuses_unknown_licences_bad_slugs_and_forbidden_names(tmp_path, bad):
    with pytest.raises(build.BuildError):
        build.load_selection(write_selection(tmp_path, [bad]))


def test_generated_example_licence_goes_with_concept_runs_only(tmp_path):
    concept = entry(licence="generated-example", concept=True)
    assert build.load_selection(write_selection(tmp_path, [concept]))[0]["concept"] is True
    for bad in [entry(licence="generated-example"), entry(licence="synthetic", concept=True)]:
        with pytest.raises(build.BuildError):
            build.load_selection(write_selection(tmp_path, [bad]))


def test_selection_refuses_a_run_named_twice(tmp_path):
    with pytest.raises(build.BuildError):
        build.load_selection(write_selection(tmp_path, [entry(), entry()]))


def write_sources(data: Path, sources: list[dict]) -> None:
    folder = data / "runs" / "demo-hull"
    folder.mkdir(parents=True)
    (folder / "sources.json").write_text(json.dumps({"sources": sources}))


def test_sources_must_be_listed_drawings(tmp_path):
    write_sources(tmp_path, [
        {"name": "sheet.tif", "kind": "drawing", "sha256": "a" * 64},
        {"name": "spec.json", "kind": "spec", "sha256": "f" * 64},
    ])
    assert len(build.check_sources(tmp_path, entry())) == 2


@pytest.mark.parametrize("source", [
    {"name": "other.tif", "kind": "drawing", "sha256": "b" * 64},
    {"name": "plan.pdf", "kind": "pdf", "sha256": None},
    {"name": "truth.json", "kind": "spec", "sha256": "f" * 64},
])
def test_sources_refuse_unlisted_drawings_and_truth_names(tmp_path, source):
    write_sources(tmp_path, [source])
    with pytest.raises(build.BuildError):
        build.check_sources(tmp_path, entry())


def test_files_refuse_local_paths_forbidden_names_and_links(tmp_path):
    (tmp_path / "ok.json").write_text('{"task": "/MarinaFrame/runs/demo-hull"}')
    assert build.check_files(tmp_path) > 0
    for name, text in [
        ("leak.json", '{"path": "/Users/someone/runs/x"}'),
        ("holdout_value.json", "{}"),
        ("appendage_score.json", "{}"),
        ("notes.json", '{"file": "work/holdout/x/Truth.json"}'),
    ]:
        bad = tmp_path / name
        bad.write_text(text)
        with pytest.raises(build.BuildError):
            build.check_files(tmp_path)
        bad.unlink()
    (tmp_path / "link.json").symlink_to(tmp_path / "ok.json")
    with pytest.raises(build.BuildError):
        build.check_files(tmp_path)


def test_large_images_are_scaled_down_and_recorded(tmp_path):
    Image.new("L", (build.MAX_IMAGE_EDGE_PX * 2, 100), 255).save(tmp_path / "big.png")
    Image.new("L", (300, 200), 255).save(tmp_path / "small.png")
    changed = build.downscale_images(tmp_path)
    assert changed == [{
        "file": "big.png",
        "original_px": [build.MAX_IMAGE_EDGE_PX * 2, 100],
        "shown_px": [build.MAX_IMAGE_EDGE_PX, 50],
    }]
    with Image.open(tmp_path / "big.png") as image:
        assert image.size == (build.MAX_IMAGE_EDGE_PX, 50)
