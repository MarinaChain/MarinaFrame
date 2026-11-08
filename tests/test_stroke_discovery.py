"""Stroke discovery on degraded drawings: tracking, linking, ruler tags, ranking, noise budget.

All drawings are synthetic pixel fixtures; no reference geometry is used.
"""
from __future__ import annotations

import json

import numpy as np
import pytest
from PIL import Image, ImageDraw

from vessel_reconstruction import investigation as inv
from vessel_reconstruction.ingest import (DrawingError, _candidate_evidence, _extract_one, _read_image,
                                          _reduce_to_run_budget, MAX_ROW_CANDIDATES)

CENTRE, TOP, BOTTOM, PPM = 20, 30, 210, 60.0


def _spec(directory, width=260, section_ids=("a",)):
    """One panel; several sections may share it (an overlaid body plan)."""
    sections = [{"id": sid, "x_m": float(index), "roi_px": [10, 20, width - 10, 220],
                 "calibration": {"centerline_px": CENTRE, "baseline_px": BOTTOM, "pixels_per_metre": PPM},
                 "z_min_m": 0.0, "z_max_m": 3.0, "evidence": "Stroke discovery fixture."}
                for index, sid in enumerate(section_ids)]
    spec = {"schema_version": "1.0", "vessel_id": "strokes", "units": "m", "symmetry": "port_starboard",
            "symmetry_evidence": "Fixture.", "end_closure": "flat_at_terminal_stations",
            "source": {"file": "drawing.png"}, "sections": sections}
    (directory / "spec.json").write_text(json.dumps(spec))
    return spec


def _load(directory):
    spec = json.loads((directory / "spec.json").read_text())
    image, details = _read_image(spec["source"], directory)
    inv._FOREGROUND_CACHE.clear()
    return image, details, spec["sections"][0]


def _hull_x(row):
    """A hull-like section: keel at the centreline, a flat bottom, a round bilge, a wall side."""
    share = (BOTTOM - row) / (BOTTOM - TOP)
    return CENTRE + 150 * (1 - (1 - share) ** 6)


def _hull_drawing(directory, *, grid=True, section_ids=("a",)):
    image = Image.new("RGB", (260, 240), "white")
    draw = ImageDraw.Draw(image)
    if grid:  # Vertical grid lines, drawn slightly off vertical as on a scan.
        for x in range(CENTRE + 40, CENTRE + 200, 40):
            draw.line((x, TOP, x + 3, BOTTOM), fill=(120,) * 3, width=2)
    rows = np.linspace(TOP, BOTTOM, 2000)
    draw.line([(_hull_x(r), r) for r in rows], fill=(15,) * 3, width=3)
    image.save(directory / "drawing.png")
    return _spec(directory, section_ids=section_ids)


def test_tracking_follows_a_flat_bottom_across_rulers(tmp_path):
    _hull_drawing(tmp_path)
    image, _, section = _load(tmp_path)
    # A seed on the bilge: the track crosses the grid lines, runs along the
    # flat bottom to the keel and up the wall side to the top.
    followed = inv.follow_stroke_2d(image, section, (_hull_x(150), 150))
    assert followed[:, 0].max() - followed[:, 0].min() >= 0.9 * (BOTTOM - TOP)
    assert followed[:, 1].min() <= CENTRE + 6


def test_enumeration_ranks_the_hull_first_and_rulers_last_with_coverage(tmp_path):
    _hull_drawing(tmp_path)
    image, details, section = _load(tmp_path)
    strokes, _ = inv.enumerate_strokes(image, section, "drawing.png", details, None, [])
    kinds = [s["kind"] for s in strokes]
    assert kinds[0] == "candidate_stroke"
    assert strokes[0]["z_coverage_fraction"] >= 0.9 and strokes[0]["hull_likeness"] > 0.5
    rows = np.arange(strokes[0]["trace_rows_px"][0], strokes[0]["trace_rows_px"][1] + 1)
    assert np.all(np.abs(np.asarray(strokes[0]["trace_xs_px"]) - _hull_x(rows)) <= 4)
    # Grid lines stay available, tagged, and after every curve.
    grid = [i for i, kind in enumerate(kinds) if kind == "straight_grid_line"]
    assert len(grid) >= 3
    assert grid == list(range(len(kinds) - len(grid), len(kinds)))


def test_slightly_slanted_long_ruler_is_a_straight_line_but_a_short_one_is_not():
    section = {"calibration": {"pixels_per_metre": 60}, "z_min_m": 0, "z_max_m": 3}
    assert inv.stroke_kind([30, 210], np.linspace(80, 84, 181), section) == "straight_grid_line"
    assert inv.stroke_kind([30, 120], np.linspace(80, 82, 91), section) == "straight_grid_line"
    assert inv.stroke_kind([30, 210], np.linspace(80, 95, 181), section) == "candidate_stroke"
    assert inv.stroke_kind([30, 100], np.full(71, 80.), section) == "candidate_stroke"


def _broken_line(directory, lower_offset=0):
    """A slanted stroke broken by four blank rows; the lower piece may be shifted sideways."""
    image = Image.new("RGB", (260, 240), "white")
    draw = ImageDraw.Draw(image)
    draw.line([(CENTRE + 30 + .25 * (BOTTOM - r), r) for r in range(TOP, 116)], fill=(15,) * 3, width=3)
    draw.line([(CENTRE + 30 + lower_offset + .25 * (BOTTOM - r), r) for r in range(120, BOTTOM + 1)],
              fill=(15,) * 3, width=3)
    image.save(directory / "drawing.png")
    _spec(directory)


def _pieces(directory, lower_offset=0):
    image, details, section = _load(directory)

    def piece(first, last, offset):
        path = np.array([[CENTRE + 30 + offset + .25 * (BOTTOM - r), r] for r in (first, last)], dtype=float)
        return inv.trace_in_source_corridor(image, section, "drawing.png", details, path, 4.0)

    return image, details, section, [piece(TOP, 115, 0), piece(120, BOTTOM, lower_offset)]


def test_pieces_of_one_stroke_across_a_small_break_are_linked(tmp_path):
    _broken_line(tmp_path)
    image, details, section, pieces = _pieces(tmp_path)
    linked = inv.link_fragments(image, section, "drawing.png", details, pieces)
    assert len(linked) == 1 and linked[0]["linked_fragments"] == 2
    assert linked[0]["trace_rows_px"][1] - linked[0]["trace_rows_px"][0] >= 0.95 * (BOTTOM - TOP)
    assert inv.describe_stroke(linked[0], section)["z_coverage_fraction"] >= 0.95


def test_pieces_whose_ends_disagree_are_not_linked(tmp_path):
    _broken_line(tmp_path, lower_offset=15)
    image, details, section, pieces = _pieces(tmp_path, lower_offset=15)
    linked = inv.link_fragments(image, section, "drawing.png", details, pieces)
    assert len(linked) == 2 and not any("linked_fragments" in p for p in linked)


def _described(xs, first_row=TOP):
    section = {"calibration": {"pixels_per_metre": PPM, "centerline_px": CENTRE}, "z_min_m": 0.0, "z_max_m": 3.0}
    rows = [first_row, first_row + len(xs) - 1]
    z_range = [(BOTTOM - rows[1]) / PPM, (BOTTOM - rows[0]) / PPM]
    return inv.describe_stroke({"trace_rows_px": rows, "trace_xs_px": list(xs), "z_range_m": z_range}, section)


def test_hull_likeness_prefers_a_smooth_full_curve():
    rows = np.arange(TOP, BOTTOM + 1)
    hull = _described(_hull_x(rows))
    fragment = _described(_hull_x(rows[:90]))
    zigzag = _described(np.where((rows // 10) % 2, CENTRE + 40, CENTRE + 120).astype(float))
    ruler = _described(np.full(len(rows), CENTRE + 80.0))
    assert hull["z_coverage_fraction"] == 1.0 and fragment["z_coverage_fraction"] == pytest.approx(0.5, abs=0.02)
    assert hull["hull_likeness"] > fragment["hull_likeness"]
    assert hull["hull_likeness"] > 2 * zigzag["hull_likeness"]
    assert ruler["kind"] == "straight_grid_line" and hull["hull_likeness"] > 5 * ruler["hull_likeness"]
    assert hull["hull_likeness_factors"]["reaches_keel"] is True


def _speckled_mask():
    mask = np.zeros((60, 460), dtype=bool)
    mask[:, 200:203] = True  # one sustained stroke
    for row in range(0, 60, 6):  # 3x3 specks, more than the row budget on each band
        for column in range(0, 460, 6):
            if not 196 <= column <= 206:
                mask[row:row + 3, column:column + 3] = True
    return mask


def test_noise_over_the_run_budget_is_removed_not_refused():
    mask = _speckled_mask()
    assert max(len(np.flatnonzero(np.diff(np.r_[0, row.astype(int)]) == 1)) for row in mask) > MAX_ROW_CANDIDATES
    reduced, record = _reduce_to_run_budget(mask)
    assert record["removed_component_count"] > 0 and record["warning"]
    assert reduced[:, 200:203].all() and reduced.sum() == 60 * 3
    evidence = _candidate_evidence(mask, mask.astype(float) * 200, np.arange(60.), np.full(60, 201.), 0.0,
                                   (0, 0), 3.0, None)
    assert evidence["evidence_complexity_reduction"]["warning"]
    unchanged, none = _reduce_to_run_budget(mask[:, 190:215])
    assert none is None and unchanged is not None


def _speckled_drawing(directory):
    image = Image.new("RGB", (480, 240), "white")
    draw = ImageDraw.Draw(image)
    for row in range(TOP, BOTTOM, 7):
        for column in range(CENTRE + 6, 470, 6):
            draw.rectangle((column, row, column + 2, row + 2), fill=(90,) * 3)
    draw.line([(CENTRE + 60 + .5 * (BOTTOM - r), r) for r in range(TOP, BOTTOM + 1)], fill=(10,) * 3, width=3)
    image.save(directory / "drawing.png")
    _spec(directory, width=480)


def test_a_noisy_panel_still_yields_a_verified_trace_with_a_warning(tmp_path):
    _speckled_drawing(tmp_path)
    image, details, section = _load(tmp_path)
    # A strict unselected reading keeps refusing (removed specks could hide a rival).
    with pytest.raises(DrawingError) as refused:
        _extract_one(image, section, "drawing.png", details)
    assert refused.value.kind == "resource_limit"
    # A selected corridor (what tracing verifies) and a draft reading proceed, with a warning.
    path = np.array([[CENTRE + 60 + .5 * (BOTTOM - r), r] for r in (TOP, BOTTOM)], dtype=float)
    traced = inv.trace_in_source_corridor(image, section, "drawing.png", details, path, 4.0)
    assert traced["warnings"] and "Noise specks" in traced["warnings"][0]
    result, _ = _extract_one(image, section, "drawing.png", details, draft=True)
    assert any("Noise specks" in w for w in result["warnings"])


def test_enumeration_tags_carry_coverage_and_rank(tmp_path):
    from vessel_reconstruction.agent_tools import DomainTools
    source = tmp_path / "src"
    source.mkdir()
    _hull_drawing(source, section_ids=("a", "b", "c"))
    task = tmp_path / "task"
    task.mkdir()
    domain = DomainTools(task, source / "spec.json")
    inspected = domain.execute("inspect_source", {})
    assert "a" in domain.state["catalog"], json.dumps(inspected)[:3000]
    result = domain.execute("enumerate_strokes", {"section_id": "a"})
    assert result["ok"], result
    tags = result["strokes"]
    assert [t["tag"] for t in tags] == list(range(1, len(tags) + 1))
    assert tags[0]["kind"] == "candidate_stroke" and tags[0]["z_coverage_fraction"] >= 0.9
    assert all("hull_likeness" in t for t in tags)
    rulers = [t["kind"] == "straight_grid_line" for t in tags]
    assert rulers == sorted(rulers) and any(rulers)  # rulers kept, and last
    likeness = [t["hull_likeness"] for t in tags if t["kind"] != "straight_grid_line"]
    assert likeness == sorted(likeness, reverse=True)
