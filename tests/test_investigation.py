"""Model investigation tools: views, corridor traces, assignments and sheet setups.

Every model proposal is checked by deterministic code. A refused proposal is an
observation (ok false, status proposal_refused), never a domain error. A traced
line is real ink re-read by the engine; an accepted assignment is an open
model_choice guess. No CAD is built here.
"""
from __future__ import annotations

import copy
import json

import numpy as np
from PIL import Image, ImageDraw

from draft_fixture import draft_drawing
from vessel_reconstruction import investigation as inv
from vessel_reconstruction.agent_tools import DomainTools
from vessel_reconstruction.draft import check_draft, check_guess, make_guesses


def _domain(tmp_path, spec_path):
    task = tmp_path / "task"
    task.mkdir()
    domain = DomainTools(task, spec_path)
    assert domain.execute("inspect_source", {})["ok"]
    return domain


def _view(domain, region):
    observed = domain.execute("view_region", {"region_px": region})
    assert observed["ok"], observed
    return observed["view"]


def _trace(domain, view, section_id, points_source, half_width_source):
    scale = view["view_px_per_source_px"][0]
    left, top = view["crop_box_px"][:2]
    path = [[(x - left) * scale, (y - top) * scale] for x, y in points_source]
    return domain.execute("trace_corridor", {"section_id": section_id, "view_id": view["view_id"],
                                             "path_px": path, "half_width_px": half_width_source * scale})


def _hull_s0(row):  # tests/draft_fixture.py: the dark stroke of section s0
    return 50 + .25 * (210 - row)


def shared_panel_drawing(directory):
    """One half body plan with two station curves; three sections share the panel."""
    directory.mkdir(parents=True)
    image = Image.new("RGB", (260, 240), "white")
    draw = ImageDraw.Draw(image)
    for offset in (40, 110):
        draw.line([(20 + offset + .3 * (210 - row), row) for row in range(30, 211)], fill=(15,) * 3, width=3)
    image.save(directory / "drawing.png")
    sections = [{"id": sid, "x_m": float(i), "roi_px": [10, 20, 250, 220],
                 "calibration": {"centerline_px": 20, "baseline_px": 210, "pixels_per_metre": 60},
                 "z_min_m": 0., "z_max_m": 3., "evidence": "Shared-panel test fixture."}
                for i, sid in enumerate(("a", "b", "c"))]
    spec = {"schema_version": "1.0", "vessel_id": "shared-panel", "units": "m", "symmetry": "port_starboard",
            "symmetry_evidence": "Fixture.", "end_closure": "flat_at_terminal_stations",
            "source": {"file": "drawing.png"}, "sections": sections}
    (directory / "spec.json").write_text(json.dumps(spec))
    return directory / "spec.json"


def test_view_is_bounded_and_records_its_mapping(tmp_path):
    spec, _ = draft_drawing(tmp_path / "src")
    domain = _domain(tmp_path, spec)
    sent = [a for a in domain.state["inspection_artifacts"] if a.get("model_eligible")]
    assert sent and all(a.get("crop_box_px") for a in sent)
    view = _view(domain, [0, 0, 200, 230])
    assert view["crop_box_px"] == [0, 0, 200, 230]
    assert view["view_px_per_source_px"] == [4.0, 4.0]  # small regions are enlarged at most 4x
    width, height = view["pixel_size"]
    assert width * height <= inv.MAX_VIEW_PIXELS and max(width, height) <= inv.MAX_VIEW_SIDE_PX
    artifact = domain.execute("view_region", {"region_px": [0, 0, 5000, 5000]})["artifacts"][0]
    assert artifact["model_eligible"] is True and artifact["bytes"] <= inv.MAX_VIEW_BYTES
    assert artifact["crop_box_px"] == [0, 0, 600, 230]  # clipped to the sheet
    outside = domain.execute("view_region", {"region_px": [900, 900, 1000, 1000]})
    assert outside["ok"] is False and outside["error_code"] == "region_outside_sheet"


def test_trace_is_snapped_to_ink_and_refused_without_ink(tmp_path):
    spec, _ = draft_drawing(tmp_path / "src")
    domain = _domain(tmp_path, spec)
    view = _view(domain, [0, 0, 200, 230])
    # A corridor drawn 6 px off the stroke still returns the stroke itself.
    traced = _trace(domain, view, "s0", [(_hull_s0(y) + 6, y) for y in (25, 120, 215)], 10)
    assert traced["ok"], traced
    candidate = next(c for c in domain.state["catalog"]["s0"]["candidates"]
                     if c["candidate_id"] == traced["candidate_id"])
    assert candidate["model_traced"] is True and candidate["snap"]["passed"] is True
    anchors = candidate["contour_selection"]["anchors_px"]
    assert all(abs(x - _hull_s0(y)) <= 1.5 for x, y in anchors)  # on the ink, not on the corridor
    assert candidate["contour_selection"]["half_width_px"] == inv.SNAPPED_HALF_WIDTH_PX
    count = len(domain.state["catalog"]["s0"]["candidates"])
    empty = _trace(domain, view, "s0", [(120, 25), (120, 215)], 3)
    assert empty["ok"] is False and empty["status"] == "proposal_refused"
    assert empty["error_code"] in ("no_ink_in_corridor", "insufficient_ink_support")
    assert len(domain.state["catalog"]["s0"]["candidates"]) == count
    again = _trace(domain, view, "s0", [(_hull_s0(y), y) for y in (25, 215)], 8)
    assert again["candidate_id"] == traced["candidate_id"] and again["new_candidate"] is False


def test_a_clicked_point_is_followed_along_its_own_stroke(tmp_path):
    domain = _domain(tmp_path, shared_panel_drawing(tmp_path / "src"))
    view = _view(domain, [0, 0, 260, 240])
    scale = view["view_px_per_source_px"][0]

    def click(x, y):
        return domain.execute("trace_from_point", {"section_id": "a", "view_id": view["view_id"],
                                                   "point_px": [x * scale, y * scale]})

    # The second curve, clicked 2 px beside its ink: the first curve is not taken.
    traced = click(130 + .3 * (210 - 120) + 2, 120)
    assert traced["ok"], traced
    candidate = next(c for c in domain.state["catalog"]["a"]["candidates"]
                     if c["candidate_id"] == traced["candidate_id"])
    assert candidate["generated_by"] == ["trace_from_point"] and candidate["snap"]["passed"] is True
    assert all(abs(x - (130 + .3 * (210 - y))) <= 1.5 for x, y in candidate["contour_selection"]["anchors_px"])
    blank = click(240, 60)
    assert blank["ok"] is False and blank["error_code"] == "no_ink_at_point"
    assert blank["view"]["kind"] == "refused_point"


def test_enumerated_strokes_are_tagged_shared_by_the_panel_and_never_best_guesses(tmp_path):
    domain = _domain(tmp_path, shared_panel_drawing(tmp_path / "src"))
    enumerated = domain.execute("enumerate_strokes", {"section_id": "a"})
    assert enumerated["ok"], enumerated
    assert enumerated["panel_section_ids"] == ["a", "b", "c"]
    # Both curves carry a tag: inspected lines keep their own ids, other strokes are traced.
    tags = enumerated["strokes"]
    assert len(tags) >= 2 and [s["tag"] for s in tags] == list(range(1, len(tags) + 1))
    catalog_a = {c["candidate_id"] for c in domain.state["catalog"]["a"]["candidates"]}
    assert {s["candidate_id"] for s in tags} <= catalog_a
    assert enumerated["view"]["kind"] == "enumerated_strokes"
    # A stroke traced here is shared by every section of the panel ...
    view = _view(domain, [0, 0, 260, 240])
    _trace(domain, view, "a", [(60 + .3 * (210 - y), y) for y in (25, 215)], 12)
    domain.state["catalog"]["a"]["candidates"] = [c for c in domain.state["catalog"]["a"]["candidates"]
                                                  if not c.get("model_traced")]
    for sid in ("a", "b", "c"):
        domain.state["catalog"][sid]["candidates"] = []
    domain._save()
    again = domain.execute("enumerate_strokes", {"section_id": "a"})
    new = [s["candidate_id"] for s in again["strokes"] if not s.get("known_candidate")]
    assert len(new) == 2
    for sid in ("b", "c"):
        assert set(new) <= {c["candidate_id"] for c in domain.state["catalog"][sid]["candidates"]}
    # ... and never a best-score guess.
    guesses = make_guesses(domain.spec["sections"], domain.state["selected"], domain.state["catalog"], {})
    assert all(g["chosen_candidate_id"] not in new for g in guesses)


def test_foreground_cache_does_not_reuse_a_released_image_id(tmp_path, monkeypatch):
    spec = json.loads(shared_panel_drawing(tmp_path / "src").read_text())
    section = spec["sections"][0]
    image = np.asarray(Image.open(tmp_path / "src" / "drawing.png").convert("RGB"))
    # NumPy allocations can reuse an object's id after a tool call releases it.
    monkeypatch.setattr(inv, "id", lambda _: 1, raising=False)
    inv._FOREGROUND_CACHE.clear()
    assert inv.window_foreground(image, section)[0].any()
    blank = np.full_like(image, 255)
    assert not inv.window_foreground(blank, section)[0].any()


def test_enumeration_keeps_new_tags_assignable_after_many_calls(tmp_path, monkeypatch):
    domain = _domain(tmp_path, shared_panel_drawing(tmp_path / "src"))
    for entry in domain.state["catalog"].values():
        entry["candidates"] = []
    domain._save()
    # Simulate a panel whose previous calls filled the old aggregate catalog cap.
    monkeypatch.setattr("vessel_reconstruction.investigation_tools.MAX_ENUMERATED_PER_SECTION", 0,
                        raising=False)
    result = domain.execute("enumerate_strokes", {"section_id": "a"})
    assert result["ok"], result
    assert len(result["strokes"]) == 2
    for sid in ("a", "b", "c"):
        ids = {c["candidate_id"] for c in domain.state["catalog"][sid]["candidates"]}
        assert {s["candidate_id"] for s in result["strokes"]} <= ids


def test_a_short_fragment_or_unknown_view_is_refused(tmp_path):
    spec, _ = draft_drawing(tmp_path / "src")
    domain = _domain(tmp_path, spec)
    view = _view(domain, [0, 0, 200, 230])
    short = _trace(domain, view, "s0", [(_hull_s0(y), y) for y in (180, 210)], 6)
    assert short["ok"] is False
    unknown = domain.execute("trace_corridor", {"section_id": "s0", "view_id": "view-unknown",
                                                "path_px": [[1, 1], [1, 50]], "half_width_px": 4})
    assert unknown["error_code"] == "unknown_view"
    bounds = domain.execute("trace_corridor", {"section_id": "s0", "view_id": view["view_id"],
                                               "path_px": [[1, 1]], "half_width_px": 4})
    assert bounds["status"] == "rejected" and bounds["error_code"] == "invalid_tool_arguments"


def test_assignment_is_an_open_model_choice_and_ink_is_used_once(tmp_path):
    domain = _domain(tmp_path, shared_panel_drawing(tmp_path / "src"))
    view = _view(domain, [0, 0, 260, 240])
    first = _trace(domain, view, "a", [(60 + .3 * (210 - y), y) for y in (25, 215)], 12)
    assert first["ok"], first
    claim = {"label_view_id": view["view_id"], "label_text": "1", "reason": "Label 1 at the curve end."}
    assigned = domain.execute("assign_station", {"section_id": "a", "candidate_id": first["candidate_id"], **claim})
    assert assigned["ok"], assigned
    guess = domain.open_guesses[0]
    assert guess["kind"] == "model_choice" and guess["status"] == "open"
    assert guess["verifier_evidence"]["passed"] is True and guess["verifier_evidence"]["identity_certified"] is False
    assert guess["reason"] == "Label 1 at the curve end." and check_guess(guess)
    # The same ink, traced again in section b, cannot become a second station.
    same = _trace(domain, view, "b", [(60 + .3 * (210 - y), y) for y in (25, 215)], 12)
    refused = domain.execute("assign_station", {"section_id": "b", "candidate_id": same["candidate_id"], **claim})
    assert refused["ok"] is False and refused["error_code"] == "ink_already_assigned"
    other = _trace(domain, view, "b", [(130 + .3 * (210 - y), y) for y in (25, 215)], 12)
    accepted = domain.execute("assign_station", {"section_id": "b", "candidate_id": other["candidate_id"], **claim})
    assert accepted["ok"], accepted
    missing_view = domain.execute("assign_station", {"section_id": "c", "candidate_id": other["candidate_id"],
                                                     **{**claim, "label_view_id": "view-never-made"}})
    assert missing_view["ok"] is False


def test_a_draft_keeps_model_choices_and_is_well_formed(tmp_path):
    domain = _domain(tmp_path, shared_panel_drawing(tmp_path / "src"))
    view = _view(domain, [0, 0, 260, 240])
    traced = _trace(domain, view, "a", [(60 + .3 * (210 - y), y) for y in (25, 215)], 12)
    domain.execute("assign_station", {"section_id": "a", "candidate_id": traced["candidate_id"],
                                      "label_view_id": view["view_id"], "label_text": "1", "reason": "Label 1."})
    sections = domain.spec["sections"]
    guesses = make_guesses(sections, domain.state["selected"], domain.state["catalog"],
                           domain.state["model_choices"])
    by_section = {g["section_id"]: g for g in guesses}
    assert by_section["a"]["kind"] == "model_choice"
    assert by_section["a"]["chosen_candidate_id"] == traced["candidate_id"]
    assert by_section["b"]["kind"] != "model_choice"
    assert check_draft({"status": "draft_not_verified", "guesses": guesses})
    forged = copy.deepcopy(by_section["a"])
    forged["verifier_evidence"]["passed"] = False
    assert not check_guess(forged)
    extra = copy.deepcopy(by_section["b"])
    extra["verifier_evidence"] = by_section["a"]["verifier_evidence"]
    assert not check_guess(extra)


def test_sheet_setup_is_checked_against_grid_datum_and_declared_calibration(tmp_path):
    spec, _ = draft_drawing(tmp_path / "src")
    domain = _domain(tmp_path, spec)
    view = _view(domain, [0, 0, 200, 230])
    base = {"view": "body", "region_px": [0, 0, 200, 230], "pixels_per_metre": 60, "grid_spacing_m": 0.5,
            "centreline_px": 20, "baseline_px": 210, "evidence_view_id": view["view_id"],
            "scale_claim": "grid every 0.5 m", "reason": "Grid read on the view."}
    accepted = domain.execute("propose_sheet_setup", base)
    assert accepted["ok"], accepted
    assert accepted["setup"]["verifier_evidence"]["measured_grid_spacing_px"]["horizontal_lines"] == 30.0
    for change, code in (({"pixels_per_metre": 70}, "scale_disagrees_with_grid"),
                         ({"centreline_px": 35}, "datum_not_on_a_drawn_line"),
                         ({"baseline_px": 180, "centreline_px": 20}, "disagrees_with_declared_calibration")):
        refused = domain.execute("propose_sheet_setup", {**base, **change})
        assert refused["ok"] is False and refused["error_code"] == code, (change, refused)


def test_grid_spacing_tolerates_missing_and_extra_lines():
    assert inv.grid_spacing([0, 30, 60, 120, 150]) == 30.0
    assert inv.grid_spacing([0, 30, 37, 60, 90]) == 30.0
    assert inv.grid_spacing([0, 30]) is None
