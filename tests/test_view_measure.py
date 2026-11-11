"""Whole-vessel view measurement (W19b): predict-then-measure in body plan, plan and profile."""
from __future__ import annotations

import numpy as np
import pytest

from vessel_reconstruction.view_measure import (ScanContext, Sheet, VesselTable, measure_point, measure_views,
                                                profile_ends, views_from_spec)
from vessel_reconstruction.whole_vessel_score import score_table

# Synthetic sheet, drawn supersampled like the benchmark factory. Profile and plan share one
# scale; the body plan is drawn larger, so neighbouring stations stay apart.
PPM = 20.0
BODY_PPM = 40.0
SUPERSAMPLE = 4
LENGTH_M, KEEL_M, TOP_M, HALF_BEAM_M = 100.0, 0.5, 9.0, 6.0
STATIONS_M = [10.0 * k for k in range(1, 10)]
WATERLINES_M = [1.5, 3.5, 5.5]
PROFILE = {"x_origin_px": 60.0, "baseline_px": 230.0}
PLAN = {"x_origin_px": 60.0, "centerline_px": 400.0}
BODY = {"centerline_px": 2400.0, "baseline_px": 400.0}
BODY_ROI = [2120, 20, 2680, 410]
SHEET_PX = (2700, 420)
VIEWS = {
    "profile": {"view_id": "profile", "kind": "profile", "roi_px": [40, 20, 2120, 240],
                "calibration": {"pixels_per_metre": PPM, **PROFILE}},
    "half_breadth_plan": {"view_id": "plan", "kind": "half_breadth_plan", "roi_px": [40, 260, 2120, 410],
                          "calibration": {"pixels_per_metre": PPM, **PLAN}},
}


def breadth(x):
    """Top half-breadth of the synthetic hull at x."""
    return HALF_BEAM_M * np.sin(np.pi * x / LENGTH_M)


def station_curve(x, samples=80):
    """Section at x: y = b(x) * eta^0.35 from the keel to the top (a full, round-bilged section)."""
    z = np.linspace(KEEL_M, TOP_M, samples)
    return np.column_stack([breadth(x) * ((z - KEEL_M) / (TOP_M - KEEL_M)) ** 0.35, z])


def stem(z):
    return 96.0 + 0.3 * z


STERN_X_M = 4.0


def known_table() -> VesselTable:
    levels = np.linspace(KEEL_M, TOP_M, 30)
    return VesselTable.from_rows([f"s{k + 1:02d}" for k in range(9)], STATIONS_M,
                                 [station_curve(x) for x in STATIONS_M], WATERLINES_M,
                                 stem_xz_m=np.column_stack([stem(levels), levels]),
                                 stern_xz_m=np.column_stack([np.full(len(levels), STERN_X_M), levels]))


def body_views() -> dict:
    panels = {}
    centre = BODY["centerline_px"]
    for k, x in enumerate(STATIONS_M):
        side = 1 if x > 50 else -1  # aft stations mirrored to the left of the centreline
        left, right = (BODY_ROI[0], centre + 2) if side < 0 else (centre - 2, BODY_ROI[2])
        panels[f"s{k + 1:02d}"] = {"roi_px": [left, BODY_ROI[1], right, BODY_ROI[3]],
                                   "calibration": {"pixels_per_metre": BODY_PPM, **BODY}, "side": side}
    return {"view_id": "body", "kind": "body_plan", "roi_px": BODY_ROI, "panels": panels}


def render(stations=None, *, grid=True) -> np.ndarray:
    """The three views of the synthetic hull (or of the given station curves), as a grey image."""
    from PIL import Image, ImageDraw
    big = Image.new("L", (SHEET_PX[0] * SUPERSAMPLE, SHEET_PX[1] * SUPERSAMPLE), 255)
    draw = ImageDraw.Draw(big)

    def line(points, tone=0, width=3):
        scaled = [(px * SUPERSAMPLE, py * SUPERSAMPLE) for px, py in points]
        draw.line(scaled, fill=tone, width=width * SUPERSAMPLE, joint="curve")
        radius = width * SUPERSAMPLE / 2
        for px, py in (scaled[0], scaled[-1]):  # round pen ends, as the benchmark factory draws
            draw.ellipse((px - radius, py - radius, px + radius, py + radius), fill=tone)

    def profile_px(x, z):
        return PROFILE["x_origin_px"] + x * PPM, PROFILE["baseline_px"] - z * PPM

    def plan_px(x, y):
        return PLAN["x_origin_px"] + x * PPM, PLAN["centerline_px"] - y * PPM

    if grid:
        for x in STATIONS_M:  # station lines through profile and plan, lighter than the hull
            line([profile_px(x, 0), profile_px(x, TOP_M + 1)], tone=200, width=1)
            line([plan_px(x, 0), plan_px(x, HALF_BEAM_M + 1)], tone=200, width=1)
        for z in WATERLINES_M:
            line([profile_px(0, z), profile_px(LENGTH_M, z)], tone=200, width=1)
            row = BODY["baseline_px"] - z * BODY_PPM
            line([(BODY_ROI[0], row), (BODY_ROI[2], row)], tone=200, width=1)
    # Profile: keel, top, stem and stern.
    xs = np.linspace(STERN_X_M, stem(KEEL_M), 200)
    line([profile_px(x, KEEL_M) for x in xs])
    line([profile_px(x, TOP_M) for x in np.linspace(STERN_X_M, stem(TOP_M), 200)])
    line([profile_px(stem(z), z) for z in np.linspace(KEEL_M, TOP_M, 50)])
    line([profile_px(STERN_X_M, z) for z in np.linspace(KEEL_M, TOP_M, 50)])
    # Plan: waterlines and the deck line, between the end stations.
    xs = np.linspace(STATIONS_M[0] - 4, STATIONS_M[-1] + 4, 300)
    for z in WATERLINES_M + [TOP_M]:
        eta = ((z - KEEL_M) / (TOP_M - KEEL_M)) ** 0.35
        line([plan_px(x, breadth(x) * eta) for x in xs])
    # Body plan: aft stations mirrored to the left of the centreline.
    curves = stations if stations is not None else {x: station_curve(x) for x in STATIONS_M}
    for x, curve in curves.items():
        side = 1 if x > 50 else -1
        line([(BODY["centerline_px"] + side * y * BODY_PPM, BODY["baseline_px"] - z * BODY_PPM) for y, z in curve])
    small = big.resize(SHEET_PX, Image.LANCZOS)
    return np.asarray(small, dtype=float)


def test_synthetic_three_view_measures_a_known_table_within_one_pixel(tmp_path):
    table, image = known_table(), render()
    views = {**VIEWS, "body_plan": body_views()}
    cells = measure_views(table, views, image, half_beam_m=HALF_BEAM_M)
    measured = [c for c in cells if c["status"] == "measured"]
    by_view = {view: [c for c in measured if c["view"] == view] for view in views}
    assert all(by_view.values())
    assert {c["target"] for c in by_view["profile"]} == {"keel", "top", "stem", "stern"}
    assert {c["target"] for c in by_view["half_breadth_plan"]} == {"waterline", "deck"}
    assert not [c for c in cells if c["status"] == "no_ink" or c["target"] == "ink_unexplained"]
    worst = max(abs(c["residual_px"]) for c in measured)
    assert worst <= 1.0, sorted((abs(c["residual_px"]), c["view"], c["target"]) for c in measured)[-5:]
    board = score_table(table, views, image, out=tmp_path, half_beam_m=HALF_BEAM_M)
    assert board["mode"] == "three_view" and board["combined_fit"] > 0.95
    assert (tmp_path / "view-overlay-half_breadth_plan.png").exists()
    assert (tmp_path / "whole-vessel-scoreboard.json").exists()


def test_a_wrong_station_shows_in_its_body_row_and_in_the_plan_waterlines():
    good = known_table()
    image = render()
    views = {**VIEWS, "body_plan": body_views()}
    rows = [station_curve(x) for x in STATIONS_M]
    rows[6] = rows[6] - [0.5, 0.0]  # s07 0.5 m (8 % of B/2) too narrow
    bad = VesselTable.from_rows(good.station_ids, STATIONS_M, rows, WATERLINES_M,
                                stem_xz_m=good.stem_xz_m, stern_xz_m=good.stern_xz_m)
    board_good = score_table(good, views, image, half_beam_m=HALF_BEAM_M)
    board_bad = score_table(bad, views, image, half_beam_m=HALF_BEAM_M)
    assert board_bad["combined_fit"] < board_good["combined_fit"] - 0.02
    groups = {(g["view"], g["group"]): g for g in board_bad["groups"]}
    assert groups[("body_plan", "s07")]["rms_m"] > 0.2 > 0.05 > groups[("body_plan", "s03")]["rms_m"]
    plan_s07 = [c["residual_m"] for c in board_bad["cells"] if c["view"] == "half_breadth_plan"
                and c.get("station_id") == "s07" and c["target"] == "waterline"]
    assert min(plan_s07) < -0.2  # the table is narrower than the drawn waterlines at s07


def _lines_image(columns, height=60, width=200):
    image = np.full((height, width), 255.0)
    for column in columns:
        image[:, column] = 0.0
    return image


def test_predict_then_measure_takes_the_nearest_of_three_competing_runs_without_refusing():
    image = _lines_image([100, 104, 108])
    context = ScanContext(Sheet(image), half_beam_m=10.0)
    scan = measure_point(context, [0, 0, 200, 60], "row", 30.0, 104.2, ppm=10.0)
    assert scan["status"] == "measured"
    assert scan["measured_px"] == pytest.approx(104.5)  # pixel 104 covers [104, 105)
    assert scan["competing_runs"] == 2
    # Far from every run: still measured (a miss, scored), never refused.
    far = measure_point(context, [0, 0, 200, 60], "row", 30.0, 160.0, ppm=10.0)
    assert far["status"] == "measured" and far["beyond_search"] and far["measured_px"] == pytest.approx(108.5)
    # No ink on the whole scan line: a gap.
    empty = ScanContext(Sheet(np.full((60, 200), 255.0)), half_beam_m=10.0)
    assert measure_point(empty, [0, 0, 200, 60], "row", 30.0, 100.0, ppm=10.0)["status"] == "no_ink"


def test_section_top_beyond_the_drawn_end_is_measured_in_the_body_plan():
    curves = {x: station_curve(x) for x in STATIONS_M}
    curves[70.0] = curves[70.0][curves[70.0][:, 1] <= 7.0]  # s07 drawn only up to z 7 m
    image = render(curves)
    cells = measure_views(known_table(), {"body_plan": body_views()}, image, half_beam_m=HALF_BEAM_M)
    tops = {c["station_id"]: c for c in cells if c["target"] == "top"}
    assert tops["s07"]["residual_m"] > 1.0 and tops["s07"]["confidence"] == 1.0
    assert abs(tops["s06"]["residual_px"]) <= 1.0


def test_overlay_station_reusing_a_neighbours_stroke_leaves_unexplained_ink():
    image = render()
    rows = [station_curve(x) for x in STATIONS_M]
    rows[8] = rows[7].copy()  # s09 copies s08's curve; s09's own drawn curve is then unexplained
    table = VesselTable.from_rows([f"s{k + 1:02d}" for k in range(9)], STATIONS_M, rows, WATERLINES_M)
    cells = measure_views(table, {"body_plan": body_views()}, image, half_beam_m=HALF_BEAM_M)
    unexplained = [c for c in cells if c["target"] == "ink_unexplained"]
    assert unexplained and {c["station_id"] for c in unexplained} <= {"s08", "s09"}
    clean = measure_views(known_table(), {"body_plan": body_views()}, image, half_beam_m=HALF_BEAM_M)
    assert not [c for c in clean if c["target"] == "ink_unexplained"]


def test_missing_station_scores_zero_and_body_only_mode_reports_fairness():
    image = render()
    rows = [station_curve(x) for x in STATIONS_M]
    rows[4] = None
    table = VesselTable.from_rows([f"s{k + 1:02d}" for k in range(9)], STATIONS_M, rows, WATERLINES_M)
    board = score_table(table, {"body_plan": body_views()}, image, half_beam_m=HALF_BEAM_M)
    assert board["mode"] == "body_only" and board["table_missing_cells"] == len(WATERLINES_M)
    assert board["worst"][0].startswith("s05 body: not in the table")
    assert board["fairness"]["status"] == "checked"
    full = score_table(known_table(), {"body_plan": body_views()}, image, half_beam_m=HALF_BEAM_M)
    assert board["combined_fit"] < full["combined_fit"]


def test_views_from_a_body_plan_spec_use_each_sections_side():
    spec = {"sections": [
        {"id": "s01", "x_m": 10.0, "roi_px": [0, 0, 100, 100],
         "calibration": {"centerline_px": 90.0, "baseline_px": 95.0, "pixels_per_metre": 10.0}},
        {"id": "s09", "x_m": 90.0, "roi_px": [80, 0, 200, 100],
         "calibration": {"centerline_px": 90.0, "baseline_px": 95.0, "pixels_per_metre": 10.0}}]}
    panels = views_from_spec(spec)["body_plan"]["panels"]
    assert panels["s01"]["side"] == -1 and panels["s09"]["side"] == 1


def test_profile_ends_are_the_outline_crossings_at_each_height():
    outline = [np.array([[10.0, 0.0], [90.0, 0.0], [95.0, 10.0], [5.0, 10.0], [10.0, 0.0]])]
    stern, stem_line = profile_ends(outline, [0.0, 5.0, 10.0])
    assert stern[:, 0] == pytest.approx([10.0, 7.5, 5.0])
    assert stem_line[:, 0] == pytest.approx([90.0, 92.5, 95.0])


def test_a_station_moved_onto_a_neighbours_ink_scores_worse_than_left_off_the_ink():
    """W18d 00679: s08 moved onto another station's line scored as a perfect fit although truth got worse."""
    image = render()
    ids = [f"s{k + 1:02d}" for k in range(9)]
    off_ink = [station_curve(x) for x in STATIONS_M]
    off_ink[7] = off_ink[7] * [0.95, 1.0]  # s08 5 % too narrow: off the ink, but in station order
    on_wrong_ink = [station_curve(x) for x in STATIONS_M]
    on_wrong_ink[7] = station_curve(STATIONS_M[5])  # s08 on s06's line: perfect ink, wrong station
    views = {"body_plan": body_views()}
    narrow = score_table(VesselTable.from_rows(ids, STATIONS_M, off_ink, WATERLINES_M), views, image,
                         half_beam_m=HALF_BEAM_M)
    swapped = score_table(VesselTable.from_rows(ids, STATIONS_M, on_wrong_ink, WATERLINES_M), views, image,
                          half_beam_m=HALF_BEAM_M)
    assert swapped["combined_fit"] < narrow["combined_fit"]
    flagged = [c for c in swapped["cells"] if c.get("station_id") == "s08" and c.get("order_residual_m")]
    assert flagged and all(c["order_residual_m"] > 0 for c in flagged)


def test_stations_with_slightly_different_calibrations_still_share_their_panel():
    """W19b2: each station's calibration has its own small read error; the panel must not split up."""
    image = render()
    views = body_views()
    for k, panel in enumerate(views["panels"].values()):
        panel["calibration"] = {**panel["calibration"], "centerline_px": BODY["centerline_px"] + 0.6 * (k % 3) - 0.6}
    cells = measure_views(known_table(), {"body_plan": views}, image, half_beam_m=HALF_BEAM_M)
    assert not [c for c in cells if c["target"] == "ink_unexplained"]
