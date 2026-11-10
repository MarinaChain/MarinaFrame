"""Best-effort drafts: guess records, draft-tagged exports, deterministic guesses."""
from __future__ import annotations

import copy
import json
import shutil

import numpy as np
import pytest

from draft_fixture import draft_drawing
from vessel_reconstruction.agent_tools import DomainTools
from vessel_reconstruction.draft import DRAFT_STATUS, check_draft, make_guesses
from vessel_reconstruction.run_record import seal_run, verify_run
from vessel_reconstruction.schema import validate_spec


def _candidate(cid, *, rows=1.0, support=1.0, contrast=0.9, competing=0):
    return {"candidate_id": cid, "selectable": True, "non_grid_competing_components": competing,
            "source_support": {"observed_row_fraction": rows, "long_component_support_fraction": support,
                               "mean_trace_contrast": contrast}}


SECTIONS = [{"id": f"s{i}", "x_m": float(x)} for i, x in enumerate((0, 1, 17.5, 20, 30))]


def test_draft_repairs_pinch_and_interpolates_missing_station_without_changing_input():
    from vessel_reconstruction.draft import prepare_draft_sections
    measured = [{"id": "a", "x_m": 0., "points_yz_m": [[1., 0.], [1., 1.], [0., 2.], [1., 3.], [1., 4.]], "coverage": 1., "evidence": {}},
                {"id": "c", "x_m": 2., "points_yz_m": [[2., z] for z in range(5)], "coverage": 1., "evidence": {}}]
    original = copy.deepcopy(measured)
    declared = [{"id": sid, "x_m": float(i)} for i, sid in enumerate("abc")]
    prepared, warnings = prepare_draft_sections(measured, declared)
    assert measured == original
    assert [s["id"] for s in prepared] == ["a", "b", "c"]
    assert min(y for y, z in prepared[0]["points_yz_m"]) == .001
    assert prepared[1]["coverage"] == 0
    assert {w["section_id"] for w in warnings} == {"a", "b"}
    assert all(w["severity"] == "warning" for w in warnings)


def test_guesses_take_the_best_line_and_bridge_or_drop_unreadable_stations():
    catalog = {"s0": {"candidates": []},
               "s1": {"candidates": [_candidate("faint", contrast=.2), _candidate("outer", contrast=.95)]},
               "s2": {"candidates": [_candidate("only", competing=3)]},
               "s3": {"candidates": []},
               "s4": {"candidates": [_candidate("selected")]}}
    guesses = make_guesses(SECTIONS, {"s4": "selected"}, catalog)
    by_section = {g["section_id"]: g for g in guesses}
    assert [g["section_id"] for g in guesses] == ["s0", "s1", "s2", "s3"]
    assert all(check_draft({"status": DRAFT_STATUS, "guesses": [g]}) for g in guesses)
    best = by_section["s1"]
    assert best["kind"] == "best_candidate" and best["chosen_candidate_id"] == "outer"
    assert best["alternatives"] == ["faint"] and best["score"] == .95
    assert best["reason"] == "2 lines found; took the best-supported one (score 0.95)."
    assert by_section["s2"]["reason"].startswith("One line found, but 3 other strokes compete")
    bridge = by_section["s3"]
    assert bridge["kind"] == "bridged_gap" and bridge["x_range_m"] == [17.5, 30.0]
    assert bridge["reason"] == "No readable line at x=20 m; smoothed across x=17.5 to 30 m."
    end = by_section["s0"]
    assert end["kind"] == "dropped_end" and end["x_range_m"] == [0.0, 1.0]
    assert end["chosen_candidate_id"] is None and end["score"] is None
    assert "the draft stops at x=1 m" in end["reason"]
    # Identical inputs give identical guesses and identifiers.
    assert make_guesses(SECTIONS, {"s4": "selected"}, copy.deepcopy(catalog)) == guesses


@pytest.mark.parametrize("change", [
    lambda d: d.update(status="verified"),
    lambda d: d.update(guesses=[]),
    lambda d: d.update(extra=True),
    lambda d: d["guesses"][0].update(status="resolved"),
    lambda d: d["guesses"][0].update(kind="certain"),
    lambda d: d["guesses"][0].update(score=1.5),
    lambda d: d["guesses"][0].update(reason=""),
    lambda d: d["guesses"][0].pop("alternatives"),
    lambda d: d["guesses"][1].update(x_range_m=[25.0, 30.0]),
    lambda d: d["guesses"][1].update(chosen_candidate_id="c"),
    lambda d: d["guesses"].append(copy.deepcopy(d["guesses"][0])),
])
def test_draft_record_shape_is_strict(change):
    catalog = {"s1": {"candidates": [_candidate("a"), _candidate("b")]}, "s3": {"candidates": []}}
    draft = {"status": DRAFT_STATUS,
             "guesses": make_guesses(SECTIONS, {"s0": "x", "s2": "y", "s4": "z"}, catalog)}
    assert check_draft(draft)
    change(draft)
    assert not check_draft(draft)


def test_schema_accepts_only_a_well_formed_draft(tmp_path):
    path, spec = draft_drawing(tmp_path)
    catalog = {"s0": {"candidates": [_candidate("a"), _candidate("b")]}}
    spec["draft"] = {"status": DRAFT_STATUS,
                     "guesses": make_guesses(spec["sections"], {"s1": "x", "s2": "y"}, catalog)}
    assert validate_spec(spec, path.parent) == []
    spec["draft"]["status"] = "verified"
    assert [g["kind"] for g in validate_spec(spec, path.parent)] == ["invalid_draft"]


def test_deterministic_guesses_on_an_ambiguous_drawing(tmp_path):
    """Two independent tasks on one ambiguous drawing make the same guesses."""
    path, _ = draft_drawing(tmp_path / "input", count=4, blank=("s2",))
    results = []
    for name in ("first", "second"):
        tools = DomainTools(tmp_path / name, path)
        observed = tools.execute("inspect_source", {})
        assert observed["ok"], observed
        unique = [{"section_id": s["section_id"], "candidate_id": s["grid_evidence"]["unique_non_grid_candidate_id"]}
                  for s in observed["sections"] if s["grid_evidence"].get("unique_non_grid_candidate_id")]
        assert sorted(u["section_id"] for u in unique) == ["s1", "s3"]
        assert tools.execute("select_contours", {"selections": unique})["ok"]
        results.append((make_guesses(tools.spec["sections"], tools.state["selected"], tools.state["catalog"]),
                        tools))
    (guesses, tools), (again, _) = results
    assert guesses == again
    assert [(g["section_id"], g["kind"]) for g in guesses] == [("s0", "best_candidate"), ("s2", "bridged_gap")]
    chosen = next(c for c in tools.state["catalog"]["s0"]["candidates"]
                  if c["candidate_id"] == guesses[0]["chosen_candidate_id"])
    # The dark hull stroke (slanted, x 50..94 px from the left edge), not a faint vertical line.
    anchors = np.asarray(chosen["contour_selection"]["anchors_px"])
    assert anchors[:, 0].min() < 60 < 90 < anchors[:, 0].max()
    assert guesses[1]["x_range_m"] == [2.0, 6.0]


@pytest.mark.cad
def test_draft_build_records_guesses_and_tags_exports(tmp_path):
    path, _ = draft_drawing(tmp_path / "input", count=4, blank=("s2",))
    tools = DomainTools(tmp_path / "task", path)
    observed = tools.execute("inspect_source", {})
    unique = [{"section_id": s["section_id"], "candidate_id": s["grid_evidence"]["unique_non_grid_candidate_id"]}
              for s in observed["sections"] if s["grid_evidence"].get("unique_non_grid_candidate_id")]
    tools.execute("select_contours", {"selections": unique})
    verified_generation = tools.generation_id
    built = tools.execute("build_draft", {})
    assert built["ok"], built
    guesses = built["draft"]["guesses"]
    assert [g["section_id"] for g in guesses] == ["s0", "s2"]
    assert tools.generation_id != verified_generation  # open guesses are part of the identity
    candidate = built["candidate"]
    assert candidate["draft"] is True and not candidate["engineering_approved"]
    run = tmp_path / "task" / candidate["path"]
    assert verify_run(run)["valid"]
    record = json.loads((run / "result.json").read_text())
    assert record["draft"] == {"status": DRAFT_STATUS, "guesses": guesses}
    assert record["exports"]["step"] == "model-draft.step" and record["exports"]["stl"] == "model-draft.stl"
    assert record["exports"]["iges"] == "model-draft.iges" and record["exports"]["iges_units"] == "mm"
    assert (run / "model-draft.iges").is_file() and not (run / "model.iges").exists()
    assert (run / "model-draft.step").is_file() and not (run / "model.step").exists()
    assert "draft_sha256" in record["identity"]
    # The unreadable station is left out; the loft spans x = 2 .. 6 m.
    assert [s["id"] for s in record["sections"]] == ["s0", "s1", "s3"]
    revision = tools.root / "revisions" / tools.revision_id
    assert json.loads((revision / "selection.json").read_text())["guesses"] == guesses
    # A draft cannot be validated.
    refused = tools.execute("validate_candidate", {})
    assert not refused["ok"] and "draft" in refused["message"]
    # A record that hides its draft origin does not verify, even when resealed.
    forged = tmp_path / "forged"
    shutil.copytree(run, forged)
    result = json.loads((forged / "result.json").read_text())
    del result["draft"]
    (forged / "manifest.json").unlink()
    seal_run(forged, result)
    assert not verify_run(forged)["valid"]
    # A person confirms the guessed line: that guess is resolved, the bridge stays open.
    tools.execute("select_contours", {"selections": [
        {"section_id": "s0", "candidate_id": guesses[0]["chosen_candidate_id"]}]})
    assert [g["section_id"] for g in tools.open_guesses] == ["s2"]
    history = tools.state["resolved_guesses"]
    assert history[0]["resolution"] == "confirmed" and history[0]["status"] == "resolved"
    assert tools.describe()["open_guesses"] == tools.open_guesses


@pytest.mark.cad
def test_draft_pinch_and_missing_station_make_renderable_step_but_strict_blocks(tmp_path, monkeypatch):
    from vessel_reconstruction import ingest
    from vessel_reconstruction.pipeline import reconstruct
    from vessel_reconstruction.schema import gap
    path, spec = draft_drawing(tmp_path / "input", count=4)
    # Exercise real CAD and publication, with deterministic measured defect input.
    sections = [{"id": s["id"], "x_m": s["x_m"],
                 "points_yz_m": [[1., 0.], [1., 1.], [0. if i == 1 else 1., 2.], [1., 3.], [1., 4.]],
                 "coverage": 1., "confidence": .5, "evidence": {}}
                for i, s in enumerate(spec["sections"]) if i != 2]
    monkeypatch.setattr(ingest, "extract_sections", lambda *args: {"sections": copy.deepcopy(sections),
        "gaps": [gap("unreliable_curve", "Fragmented curve.", "s2")]})
    strict = reconstruct(path, tmp_path / "strict")
    assert strict["status"] == "blocked" and not strict["exports"]
    spec["draft"] = {"status": DRAFT_STATUS, "guesses": make_guesses(spec["sections"], {}, {})}
    path.write_text(json.dumps(spec))
    draft = reconstruct(path, tmp_path / "draft")
    assert draft["status"] == "review_required", draft["gaps"]
    assert draft["exports"]["step"] == "model-draft.step"
    assert {g["kind"] for g in draft["gaps"]} >= {"draft_repaired", "draft_interpolated"}
    assert all(g["severity"] == "warning" for g in draft["gaps"])
    assert verify_run(tmp_path / "draft")["valid"]
    from vessel_reconstruction.agent_render_worker import render_step
    render_dir = tmp_path / "render"
    render_dir.mkdir()
    rendered = render_step(tmp_path / "draft", "body", render_dir)
    assert rendered["geometry_audit"]["valid_shape"]


def _deck_traced_section():
    """A flared hull to a deck edge at z 8, a camber line to the centreline, then
    the centreline up to the panel top at z 12 (pixel 0.02 m), as in dtmb5415-L0."""
    hull = [[2. + .25 * z, z] for z in np.arange(0., 8.01, .5)]
    camber = [[2.5, 8.03], [0., 8.06]]
    centreline = [[0., z] for z in np.arange(8.5, 12.01, .5)]
    return hull + camber + centreline


def test_draft_top_closure_ends_at_the_hull_curve_not_the_panel_top():
    from vessel_reconstruction.draft import prepare_draft_sections
    declared = [{"id": sid, "x_m": float(i), "z_max_m": 12., "calibration": {"pixels_per_metre": 50.}}
                for i, sid in enumerate("abc")]
    measured = [{"id": sid, "x_m": float(i), "points_yz_m": _deck_traced_section(), "coverage": 1., "evidence": {}}
                for i, sid in enumerate("abc")]
    prepared, warnings = prepare_draft_sections(measured, declared)
    for section in prepared:
        # The section ends at the deck edge: no camber line, no centreline run.
        assert section["points_yz_m"] == _deck_traced_section()[:17]
        assert section["points_yz_m"][-1] == [4., 8.]
    assert {w["kind"] for w in warnings} == {"draft_top_trimmed"}
    assert all(w["severity"] == "warning" and "z 8.00 m" in w["message"] for w in warnings)


@pytest.mark.cad
def test_trimmed_top_closure_builds_a_verified_draft_solid(tmp_path, monkeypatch):
    from vessel_reconstruction import ingest
    from vessel_reconstruction.pipeline import reconstruct
    path, spec = draft_drawing(tmp_path / "input", count=4)
    # The fixture panel top is z 3 m; scale the dtmb5415-L0 shape into it.
    points = [[y / 4, z / 4] for y, z in _deck_traced_section()]
    sections = [{"id": s["id"], "x_m": s["x_m"], "points_yz_m": points, "coverage": 1., "confidence": .5,
                 "evidence": {}} for s in spec["sections"]]
    monkeypatch.setattr(ingest, "extract_sections", lambda *args: {"sections": copy.deepcopy(sections), "gaps": []})
    spec["draft"] = {"status": DRAFT_STATUS, "guesses": make_guesses(spec["sections"], {}, {})}
    path.write_text(json.dumps(spec))
    draft = reconstruct(path, tmp_path / "draft")
    assert draft["status"] == "review_required", draft["gaps"]
    assert {g["kind"] for g in draft["gaps"]} == {"draft_top_trimmed"}
    assert draft["metrics"]["depth_m"] == pytest.approx(2.)
    assert verify_run(tmp_path / "draft")["valid"]


@pytest.mark.parametrize("change", ["below_panel_top", "one_pixel_tip", "no_calibration", "wall_sided"])
def test_draft_top_closure_keeps_real_hull_tops(change):
    from vessel_reconstruction.draft import trim_top_closure
    points, z_max, pixel = _deck_traced_section(), 12., .02
    if change == "below_panel_top":
        z_max = 14.
    elif change == "one_pixel_tip":
        # A pointed section that meets the centreline in the top pixel row.
        points = [[5. - .4 * z, z] for z in np.arange(0., 12., .5)] + [[0., 11.99], [0., 12.]]
    elif change == "no_calibration":
        pixel = None
    else:
        # Constant breadth up to the panel top is kept: it may be real topsides.
        points = [[min(4., 2. + .25 * z), z] for z in np.arange(0., 12.01, .5)]
    assert trim_top_closure(points, .001, z_max, pixel) is None
