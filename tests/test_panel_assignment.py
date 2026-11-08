"""Shared-panel station assignment: one stroke per station by nesting order (overlay body plans).

Synthetic strokes and a synthetic pixel drawing; no reference geometry is used.
"""
from __future__ import annotations

import json

import numpy as np
from PIL import Image, ImageDraw

from vessel_reconstruction import investigation as inv
from vessel_reconstruction import panel_assignment as pa
from vessel_reconstruction.draft import DRAFT_STATUS, check_draft, make_guesses

CENTRE, TOP, BOTTOM, PPM = 20, 30, 210, 60.0
ROWS = np.arange(TOP, BOTTOM + 1)


def _section(sid, x, roi=(10, 20, 250, 220)):
    return {"id": sid, "x_m": float(x), "roi_px": list(roi), "z_min_m": 0.0, "z_max_m": 3.0,
            "calibration": {"centerline_px": CENTRE, "baseline_px": BOTTOM, "pixels_per_metre": PPM}}


def _hull_x(rows, width):
    """A hull-like half section of the given maximum half-breadth in px."""
    share = (BOTTOM - np.asarray(rows, dtype=float)) / (BOTTOM - TOP)
    return CENTRE + width * (1 - (1 - share) ** 4)


def _stroke(cid, width, likeness=0.9, kind="candidate_stroke", rows=ROWS):
    return {"candidate_id": cid, "rows": rows, "xs": _hull_x(rows, width), "hull_likeness": likeness, "kind": kind}


# Aft half (x 10..30) in this panel, forward half (x 50..70) in another one.
AFT = [_section("s1", 10), _section("s2", 20), _section("s3", 30)]
FORE = [_section(sid, x, roi=(300, 20, 540, 220)) for sid, x in (("s5", 50), ("s6", 60), ("s7", 70))]


def test_each_station_gets_its_own_stroke_by_nesting_order():
    strokes = [_stroke("narrow", 60), _stroke("wide", 180), _stroke("middle", 120)]
    result = pa.assign_panel(AFT, AFT + FORE, strokes)
    # The station nearest the other half (midship side) is outermost.
    assert {sid: r["candidate_id"] for sid, r in result.items()} == {"s3": "wide", "s2": "middle", "s1": "narrow"}
    assert all(r["station_order_basis"] == "other_half_forward" for r in result.values())
    assert all(0 < r["confidence"] <= 1 and not r["warnings"] for r in result.values())
    assert all(r["candidate_id"] not in r["alternatives"] for r in result.values())


def test_forward_half_is_ordered_from_the_aft_side():
    strokes = [_stroke("narrow", 60), _stroke("wide", 180), _stroke("middle", 120)]
    result = pa.assign_panel(FORE, AFT + FORE, strokes)
    assert {sid: r["candidate_id"] for sid, r in result.items()} == {"s5": "wide", "s6": "middle", "s7": "narrow"}


def test_rulers_and_weak_strokes_are_skipped_when_enough_hull_strokes_exist():
    strokes = [_stroke("ruler", 200, likeness=0.05, kind="straight_grid_line"), _stroke("narrow", 60),
               _stroke("noise", 90, likeness=0.05), _stroke("middle", 120), _stroke("wide", 180)]
    result = pa.assign_panel(AFT, AFT + FORE, strokes)
    assert [result[s]["candidate_id"] for s in ("s3", "s2", "s1")] == ["wide", "middle", "narrow"]


def test_too_few_strokes_still_give_a_guess_with_a_warning():
    result = pa.assign_panel(AFT, AFT + FORE, [_stroke("wide", 180), _stroke("narrow", 60)])
    assert set(result) == {"s1", "s2", "s3"}
    shared = [r for r in result.values() if any(w.startswith("fewer_strokes_than_stations") for w in r["warnings"])]
    assert len(shared) == 2 and all(r["confidence"] < 0.5 for r in shared)
    assert pa.assign_panel(AFT, AFT + FORE, []) == {}


def test_a_near_tie_lowers_confidence_and_lists_the_rival():
    strokes = [_stroke("a", 180), _stroke("b", 150, likeness=0.89), _stroke("c", 120), _stroke("d", 60)]
    result = pa.assign_panel(AFT, AFT + FORE, strokes)
    near = [r for r in result.values() if any(w.startswith("near_tie") for w in r["warnings"])]
    assert near and all(r["alternatives"] for r in near)


def test_an_existing_choice_pins_its_station():
    strokes = [_stroke("narrow", 60), _stroke("wide", 180), _stroke("middle", 120), _stroke("inner", 30)]
    result = pa.assign_panel(AFT, AFT + FORE, strokes, pinned={"s1": "inner"})
    assert result["s1"]["candidate_id"] == "inner" and result["s1"]["confidence"] == 1.0
    assert len({r["candidate_id"] for r in result.values()}) == 3


def test_one_panel_without_other_halves_orders_by_distance_from_the_middle():
    sections = [_section(sid, x) for sid, x in (("a", 0), ("b", 50), ("c", 100))]
    result = pa.assign_panel(sections, sections, [_stroke("wide", 180), _stroke("mid", 120), _stroke("n", 60)])
    assert result["b"]["candidate_id"] == "wide"
    assert result["b"]["station_order_basis"] == "middle_of_station_list"


def _support(cid, *, panel=False):
    candidate = {"candidate_id": cid, "selectable": True, "non_grid_competing_components": 2,
                 "source_support": {"observed_row_fraction": 1.0, "long_component_support_fraction": 1.0,
                                    "mean_trace_contrast": 0.9 if cid != "best" else 0.95}}
    if panel:
        candidate["panel_stroke"] = True
    return candidate


def test_draft_guesses_follow_the_panel_recommendation():
    sections = [{"id": sid, "x_m": float(x)} for sid, x in (("s1", 10), ("s2", 20), ("s3", 30))]
    catalog = {}
    for sid, chosen in (("s1", "narrow"), ("s2", "middle"), ("s3", "best")):
        catalog[sid] = {"candidates": [_support("best"), _support("middle", panel=True), _support("narrow", panel=True)],
                        "recommended_station_assignment": {
                            "candidate_id": chosen, "confidence": 0.8, "alternatives": ["best"],
                            "nesting_rank": 1, "strokes_in_panel": 3, "expected_width_rank": 1, "warnings": []}}
    guesses = make_guesses(sections, {}, catalog)
    assert [g["chosen_candidate_id"] for g in guesses] == ["narrow", "middle", "best"]
    assert all(check_draft({"status": DRAFT_STATUS, "guesses": [g]}) for g in guesses)
    assert guesses[0]["alternatives"][0] == "best" and guesses[0]["reason"].startswith("Shared panel")
    # Without a recommendation a panel stroke never wins the best-score guess.
    for entry in catalog.values():
        del entry["recommended_station_assignment"]
    assert {g["chosen_candidate_id"] for g in make_guesses(sections, {}, catalog)} == {"best"}


def test_nested_drawing_gets_one_stroke_per_station(tmp_path):
    """Three nested hull curves in one panel shared by three stations.

    With no other panel, midship is the middle of the station list: s2 is
    outermost, then s1, then s3 (the farthest from x = 20 m on a tie).
    """
    from vessel_reconstruction.agent_tools import DomainTools
    source = tmp_path / "src"
    source.mkdir()
    image = Image.new("RGB", (260, 240), "white")
    draw = ImageDraw.Draw(image)
    rows = np.linspace(TOP, BOTTOM, 2000)
    widths = {"s1": 110, "s2": 160, "s3": 60}
    for width in widths.values():
        draw.line(list(zip(_hull_x(rows, width), rows)), fill=(15,) * 3, width=3)
    image.save(source / "drawing.png")
    sections = [{**_section(sid, x), "evidence": "Fixture."} for sid, x in (("s1", 10), ("s2", 20), ("s3", 30))]
    spec = {"schema_version": "1.0", "vessel_id": "nested", "units": "m", "symmetry": "port_starboard",
            "symmetry_evidence": "Fixture.", "end_closure": "flat_at_terminal_stations",
            "source": {"file": "drawing.png"}, "sections": sections}
    (source / "spec.json").write_text(json.dumps(spec))
    task = tmp_path / "task"
    task.mkdir()
    domain = DomainTools(task, source / "spec.json")
    assert domain.execute("inspect_source", {})["ok"]
    enumerated = domain.execute("enumerate_strokes", {"section_id": "s1"})
    hint = enumerated["recommended_station_assignment"]["stations"]
    assert len({hint[sid]["tag"] for sid in widths}) == 3
    # The draft path: one stroke per station, each on its own curve.
    domain._assign_shared_panels()
    catalog = domain.state["catalog"]
    assert all("recommended_station_assignment" in catalog[sid] for sid in widths)
    guesses = make_guesses(domain.spec["sections"], {}, catalog)
    assert len({g["chosen_candidate_id"] for g in guesses}) == 3
    for guess in guesses:
        chosen = next(c for c in catalog[guess["section_id"]]["candidates"]
                      if c["candidate_id"] == guess["chosen_candidate_id"])
        trace_rows, trace_xs = inv.dense_trace(chosen)
        middle = len(trace_rows) // 2
        expected = _hull_x(trace_rows[middle], widths[guess["section_id"]])
        assert abs(trace_xs[middle] - expected) <= 4, guess
    # Inspection now shows the recommendation as an added field.
    observed = domain.execute("inspect_source", {"section_ids": ["s1"]})
    assert observed["sections"][0]["recommended_station_assignment"]["candidate_id"] == guesses[0]["chosen_candidate_id"]
