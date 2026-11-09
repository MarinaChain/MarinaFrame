"""Whole-vessel combined fit, scoreboard and keep rule (W19b), and the view overlay drawing."""
from __future__ import annotations

import numpy as np
import pytest

from vessel_reconstruction.station_overlay import draw_view_overlay, ink_fit, residual_colour
from vessel_reconstruction.whole_vessel_score import cell_score, keep_edit, scoreboard

HALF_BEAM = 10.0  # 5 % of B/2 = 0.5 m (end of the steep part); 30 % of B/2 = 3 m scores 0


def _cell(view, target, residual, confidence=1.0, **ids):
    return {"view": view, "target": target, "status": "measured", "residual_m": residual,
            "residual_px": residual * 10, "confidence": confidence, "competing_runs": 0,
            "x_m": ids.pop("x_m", 10.0), "z_m": ids.pop("z_m", 2.0), **ids}


def test_cell_score_falls_steeply_to_five_percent_of_the_half_beam_then_slowly_to_thirty():
    assert cell_score(0.0, HALF_BEAM) == 1.0
    assert cell_score(-0.25, HALF_BEAM) == pytest.approx(0.8 * 0.5 + 0.2 * (1 - 0.25 / 3))
    assert cell_score(0.5, HALF_BEAM) == pytest.approx(0.2 * (1 - 0.5 / 3))
    # Past 5 % of B/2 a worse residual still scores lower (no saturation) ...
    assert cell_score(0.9, HALF_BEAM) > cell_score(1.8, HALF_BEAM) > 0.0
    # ... until 30 % of B/2.
    assert cell_score(3.0, HALF_BEAM) == 0.0


def test_combined_fit_weights_views_by_their_share_of_measured_cells_and_skips_gaps():
    cells = ([_cell("body_plan", "station", 0.0, station_id="s01", waterline_id=f"w{j}") for j in range(3)]
             + [_cell("half_breadth_plan", "waterline", 3.0, station_id="s01", waterline_id="w1")]
             + [{"view": "half_breadth_plan", "target": "waterline", "status": "no_ink", "station_id": "s02",
                 "waterline_id": "w1", "x_m": 20.0, "z_m": 2.0}])
    board = scoreboard(cells, HALF_BEAM, revision="r0001")
    # body fit 1 on 3 cells, plan fit 0 on 1 cell: (3 x 1 + 1 x 0) / 4
    assert board["combined_fit"] == pytest.approx(0.75)
    assert board["mode"] == "three_view" and board["gap_cells"] == 1 and board["measured_cells"] == 4
    plan = board["views"]["half_breadth_plan"]
    assert plan["coverage"] == pytest.approx(0.5) and plan["max_abs_m"] == pytest.approx(3.0)
    assert board["worst"][0].startswith("w1 plan +3.00 m")
    assert board["summary_line"].startswith("draft r0001  fit 0.75  body 0.000 m  plan 3.000 m")


def test_low_confidence_cells_weigh_less_and_missing_stations_score_zero():
    confident = _cell("body_plan", "station", 0.0, station_id="s01", waterline_id="w1")
    doubtful = _cell("body_plan", "station", 3.0, confidence=0.25, station_id="s02", waterline_id="w1")
    assert scoreboard([confident, doubtful], HALF_BEAM)["combined_fit"] == pytest.approx(1 / 1.25)
    missing = {"view": "body_plan", "target": "station", "status": "table_missing", "station_id": "s03",
               "waterline_id": "w1", "x_m": 30.0, "z_m": 2.0}
    board = scoreboard([confident, missing], HALF_BEAM)
    assert board["combined_fit"] == pytest.approx(0.5) and board["mode"] == "body_only"
    assert board["worst"][0] == "s03 body: not in the table (1 cells)"


def test_keep_rule_keeps_an_improving_edit_and_rejects_a_worsening_one():
    before = scoreboard([_cell("body_plan", "station", 0.2, station_id="s01", waterline_id="w1")], HALF_BEAM)
    better = scoreboard([_cell("body_plan", "station", 0.1, station_id="s01", waterline_id="w1")], HALF_BEAM)
    worse = scoreboard([_cell("body_plan", "station", 0.3, station_id="s01", waterline_id="w1")], HALF_BEAM)
    assert keep_edit(before, better)["keep"] is True
    rejected = keep_edit(before, worse)
    assert rejected["keep"] is False and "0.6667 -> 0.5" in rejected["reason"]


def test_keep_rule_accepts_a_gap_fill_that_leaves_measured_cells_unchanged():
    cells = [_cell("body_plan", "station", 0.2, station_id="s01", waterline_id="w1")]
    board = scoreboard(cells, HALF_BEAM)
    assert keep_edit(board, board, cells, cells, gap_fill_only=True)["keep"] is True
    worse_cells = [_cell("body_plan", "station", 0.3, station_id="s01", waterline_id="w1")]
    assert keep_edit(board, scoreboard(worse_cells, HALF_BEAM), cells, worse_cells, gap_fill_only=True)["keep"] is False


def test_residual_colours_follow_the_design_classes():
    assert residual_colour(0.005) == "#2ca02c" and residual_colour(0.02) == "#ff7f0e"
    assert residual_colour(0.2) == "#d62728"


def test_view_overlay_draws_lines_and_markers(tmp_path):
    image = np.full((120, 300), 255, dtype=np.uint8)
    image[60, 20:280] = 0
    result = draw_view_overlay(image, [10, 10, 290, 110], [("wl1", np.array([[20.0, 60.0], [280.0, 60.0]]))],
                               [((100.0, 60.0), "#2ca02c")], tmp_path / "plan.png", "plan")
    assert (tmp_path / "plan.png").exists() and result["crop_box_px"][0] < 10


def test_ink_fit_reads_a_mirrored_station_left_of_its_centreline():
    image = np.full((200, 200), 255, dtype=np.uint8)
    image[30:181, 120] = 0  # ink 1 m left of the centreline at x = 170 px (50 px per metre)
    calibration = {"centerline_px": 170.0, "baseline_px": 180.0, "pixels_per_metre": 50.0}
    points = np.array([[1.0, z] for z in np.linspace(0.1, 2.8, 20)])
    segments = np.stack([points[:-1], points[1:]], axis=1)
    mirrored = ink_fit(segments, calibration, [0, 0, 200, 200], image, side=-1)
    assert mirrored["max_m"] <= 0.02
    unmirrored = ink_fit(segments, calibration, [0, 0, 200, 200], image)  # looks right of the centreline
    assert unmirrored is None or unmirrored["max_m"] > 0.5


def test_unimodal_fit_keeps_an_ordered_waterline_and_flattens_an_out_of_order_station():
    from vessel_reconstruction.whole_vessel_score import unimodal_fit
    ordered = np.array([1.0, 3.0, 5.0, 5.5, 4.0, 2.0])
    assert np.allclose(unimodal_fit(ordered), ordered)
    broken = np.array([1.0, 3.0, 5.0, 5.5, 2.0, 4.0, 1.0])  # the sixth station sits on a wider line
    residual = broken - unimodal_fit(broken)
    assert residual[5] > 0.9 and residual[4] < -0.9 and np.allclose(residual[:4], 0)


def test_an_order_breaking_cell_scores_no_more_than_its_order_excess():
    on_ink = _cell("body_plan", "station", 0.0, station_id="s01", waterline_id="w1")
    assert scoreboard([on_ink], HALF_BEAM)["combined_fit"] == 1.0
    within_tolerance = {**on_ink, "order_residual_m": 0.15}  # 1.5 % of B/2: within the 2 % tolerance
    assert scoreboard([within_tolerance], HALF_BEAM)["combined_fit"] == 1.0
    out_of_order = {**on_ink, "order_residual_m": -2.0}
    assert scoreboard([out_of_order], HALF_BEAM)["combined_fit"] == 0.0


def test_keep_rule_rejects_an_edit_that_leaves_more_drawn_ink_unexplained():
    before_cells = [_cell("body_plan", "station", 0.4, station_id="s01", waterline_id="w1")]
    after_cells = [_cell("body_plan", "station", 0.0, station_id="s01", waterline_id="w1"),
                   _cell("body_plan", "ink_unexplained", 0.8, station_id="s01", waterline_id="w1")]
    before, after = scoreboard(before_cells, HALF_BEAM), scoreboard(after_cells, HALF_BEAM)
    assert after["combined_fit"] > before["combined_fit"] + 0.002
    decision = keep_edit(before, after, before_cells, after_cells)
    assert decision["keep"] is False and "unexplained" in decision["reason"]
    assert keep_edit(before, after)["keep"] is True  # without cells, only the fit decides


def test_keep_rule_rejects_an_edit_whose_curve_leaves_station_ink_it_followed():
    # The fit rises (a top cell is fixed) while the curve leaves its ink at w1.
    before_cells = [_cell("body_plan", "station", -0.1, station_id="s08", waterline_id="w1"),
                    _cell("profile", "top", 4.0, station_id="s08")]
    after_cells = [_cell("body_plan", "station", -4.4, station_id="s08", waterline_id="w1"),
                   _cell("profile", "top", 0.0, station_id="s08"),
                   _cell("profile", "keel", 0.0, station_id="s08")]
    before, after = scoreboard(before_cells, HALF_BEAM), scoreboard(after_cells, HALF_BEAM)
    assert after["combined_fit"] > before["combined_fit"] + 0.002
    decision = keep_edit(before, after, before_cells, after_cells)
    assert decision["keep"] is False and "left the station ink it followed at s08 w1" in decision["reason"]
    # A smaller move (here 0.8 m) can repair a trace that sat on another line: the fit decides.
    near = [{**after_cells[0], "residual_m": -0.8}, *after_cells[1:]]
    assert keep_edit(before, scoreboard(near, HALF_BEAM), before_cells, near)["keep"] is True
