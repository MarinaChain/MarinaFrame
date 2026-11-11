"""Afterbody curves drawn left of the centreline (overlay body plans) and mixed panel traces.

Reproduces the dtmb5415-3v-L0 app run: the aft stations took ink right of the
centreline (a bulb inside the aft panel's overlap), several stations shared
one stroke, and a whole-panel trace that jumps between curves was given to a
station. All drawings are synthetic pixel fixtures; no reference geometry is used.
"""
from __future__ import annotations

import json

import numpy as np
from PIL import Image, ImageDraw

from vessel_reconstruction import investigation as inv
from vessel_reconstruction import panel_assignment as pa
from vessel_reconstruction.draft import make_guesses
from vessel_reconstruction.ingest import _extract_one, _read_image, drawn_left_of_centreline

CENTRE, TOP, BOTTOM, PPM = 250, 30, 210, 60.0
ROWS = np.linspace(TOP, BOTTOM, 2000)
# Aft panel: mostly left of the centreline, overlapping it by 30 px as materialize does.
AFT_ROI = [20, 20, 280, 220]
WIDTHS = {"s1": 60, "s2": 110, "s3": 160}


def _half_breadth_px(rows, width):
    """A hull-like half section of the given maximum half-breadth in px."""
    share = (BOTTOM - np.asarray(rows, dtype=float)) / (BOTTOM - TOP)
    return width * (1 - (1 - share) ** 4)


def _section(sid, x, roi=AFT_ROI):
    return {"id": sid, "x_m": float(x), "roi_px": list(roi), "z_min_m": 0.0, "z_max_m": 3.0,
            "evidence": "Mirrored half fixture.",
            "calibration": {"centerline_px": CENTRE, "baseline_px": BOTTOM, "pixels_per_metre": PPM}}


def _overlay_drawing(directory):
    """Three nested afterbody curves left of the centreline and a short forebody bulb right of it."""
    image = Image.new("RGB", (300, 240), "white")
    draw = ImageDraw.Draw(image)
    for width in WIDTHS.values():
        draw.line(list(zip(CENTRE - _half_breadth_px(ROWS, width), ROWS)), fill=(15,) * 3, width=3)
    bulb_rows = np.linspace(120, BOTTOM, 400)
    draw.line(list(zip(CENTRE + 25 * np.sin(np.pi * (bulb_rows - 120) / 90), bulb_rows)), fill=(15,) * 3, width=3)
    image.save(directory / "drawing.png")
    sections = [_section(sid, x) for sid, x in (("s1", 10), ("s2", 20), ("s3", 30))]
    # A forebody station in its own panel, so the aft stations know where midship is.
    sections.append(_section("s5", 50, roi=[230, 20, 300, 220]))
    spec = {"schema_version": "1.0", "vessel_id": "mirrored", "units": "m", "symmetry": "port_starboard",
            "symmetry_evidence": "Fixture.", "end_closure": "flat_at_terminal_stations",
            "source": {"file": "drawing.png"}, "sections": sections}
    (directory / "spec.json").write_text(json.dumps(spec))
    return spec


def test_a_left_drawn_curve_is_traced_as_its_mirror(tmp_path):
    spec = _overlay_drawing(tmp_path)
    image, details = _read_image(spec["source"], tmp_path)
    section = spec["sections"][2]
    assert drawn_left_of_centreline(section) and not drawn_left_of_centreline(spec["sections"][3])
    rows = np.arange(TOP, BOTTOM + 1)
    anchors = [[float(CENTRE - _half_breadth_px(r, WIDTHS["s3"])), float(r)] for r in rows[::12]]
    assert anchors[-1][1] == BOTTOM
    selected = {**section, "contour_selection": {"anchors_px": anchors, "half_width_px": 3.0}}
    result, diagnostic = _extract_one(image, selected, "drawing.png", details, draft=True)
    points = np.asarray(result["points_yz_m"])
    expected = _half_breadth_px(BOTTOM - points[:, 1] * PPM, WIDTHS["s3"]) / PPM
    assert np.max(np.abs(points[:, 0] - expected)) <= 3 / PPM
    # Reported pixels stay in the source frame (left of the centreline).
    assert diagnostic["traced_mirrored_left_half"] is True
    assert result["evidence"]["roi_px"] == AFT_ROI
    assert result["evidence"]["contour_selection"]["anchors_px"][0][0] < CENTRE
    bounds = result["evidence"]["pixel_trace_bounds"]
    assert bounds[0] >= AFT_ROI[0] and bounds[2] <= CENTRE + 1


def test_aft_stations_take_their_own_left_curves_not_the_bulb(tmp_path):
    from vessel_reconstruction.agent_tools import DomainTools
    source = tmp_path / "src"
    source.mkdir()
    _overlay_drawing(source)
    task = tmp_path / "task"
    task.mkdir()
    domain = DomainTools(task, source / "spec.json")
    assert domain.execute("inspect_source", {})["ok"]
    domain._assign_shared_panels()
    catalog = domain.state["catalog"]
    aft = [s for s in domain.spec["sections"] if s["id"] in WIDTHS]
    guesses = make_guesses(aft, {}, catalog)
    assert len({g["chosen_candidate_id"] for g in guesses}) == 3  # no stroke shared
    for guess in guesses:
        chosen = next(c for c in catalog[guess["section_id"]]["candidates"]
                      if c["candidate_id"] == guess["chosen_candidate_id"])
        rows, xs = inv.dense_trace(chosen)
        middle = len(rows) // 2
        assert xs[middle] < CENTRE  # the afterbody half, not the bulb
        expected = CENTRE - _half_breadth_px(rows[middle], WIDTHS[guess["section_id"]])
        assert abs(xs[middle] - expected) <= 4, guess


def test_left_strokes_nest_outwards_to_the_left():
    def stroke(cid, width):
        rows = np.arange(TOP, BOTTOM + 1)
        return {"candidate_id": cid, "rows": rows, "xs": CENTRE - _half_breadth_px(rows, width),
                "hull_likeness": 0.9, "kind": "candidate_stroke"}
    members = [_section(sid, x) for sid, x in (("s1", 10), ("s2", 20), ("s3", 30))]
    sections = members + [_section("s5", 50, roi=[230, 20, 300, 220])]
    result = pa.assign_panel(members, sections, [stroke("narrow", 60), stroke("wide", 160), stroke("middle", 110)])
    assert {sid: r["candidate_id"] for sid, r in result.items()} == {"s3": "wide", "s2": "middle", "s1": "narrow"}


def test_a_trace_that_jumps_between_two_curves_is_mixed():
    # An inspected line that jumps between two station curves brings no ink of its own and
    # leaves the panel pool; a distinct curve between them stays (strokes_with_own_ink).
    rows = np.arange(TOP, BOTTOM + 1)
    outer, inner = CENTRE + _half_breadth_px(rows, 160), CENTRE + _half_breadth_px(rows, 60)
    jumping = np.where(rows < (TOP + BOTTOM) / 2, outer, inner)

    def stroke(cid, xs, likeness):
        return {"candidate_id": cid, "rows": rows, "xs": xs, "hull_likeness": likeness, "kind": "candidate_stroke"}
    pool = [stroke("outer", outer, 0.6), stroke("inner", inner, 0.6), stroke("jumping", jumping, 0.9),
            stroke("own", CENTRE + _half_breadth_px(rows, 110), 0.5)]
    kept = [s["candidate_id"] for s in pa.strokes_with_own_ink(pool, [])]
    assert kept == ["outer", "inner", "own"]


def test_a_trace_stops_at_the_curve_top_below_its_station_label(tmp_path):
    """The station number touches the curve's top end; the label ink is not hull."""
    image = Image.new("RGB", (300, 240), "white")
    draw = ImageDraw.Draw(image)
    curve_top = 80
    rows = np.linspace(curve_top, BOTTOM, 2000)
    xs = CENTRE - _half_breadth_px(rows, WIDTHS["s3"])
    draw.line(list(zip(xs, rows)), fill=(15,) * 3, width=3)
    end_x = float(xs[0])
    # A thin, lighter numeral standing on the curve's end, as on the factory sheets.
    draw.line([(end_x - 1, curve_top - 1), (end_x - 3, curve_top - 16)], fill=(70,) * 3, width=1)
    draw.line([(end_x - 3, curve_top - 16), (end_x - 7, curve_top - 12)], fill=(70,) * 3, width=1)
    image.save(tmp_path / "drawing.png")
    section = _section("s3", 30)
    image, details = _read_image({"file": "drawing.png"}, tmp_path)
    inv._FOREGROUND_CACHE.clear()
    strokes, _ = inv.enumerate_strokes(image, section, "drawing.png", details, None, [])
    hull = max(strokes, key=lambda s: s["trace_rows_px"][1] - s["trace_rows_px"][0])
    assert curve_top - 2 <= hull["trace_rows_px"][0] <= curve_top + 3
    assert hull["support"]["label_rows_removed"] > 0
