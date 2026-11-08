"""Whole-vessel combined fit, scoreboard and keep rule (W19b), and the view overlay drawing."""
from __future__ import annotations

import numpy as np
import pytest

from vessel_reconstruction.station_overlay import draw_view_overlay, ink_fit, residual_colour
from vessel_reconstruction.whole_vessel_score import cell_score, keep_edit, scoreboard

HALF_BEAM = 10.0  # full-score residual = 5 % of B/2 = 0.5 m


def _cell(view, target, residual, confidence=1.0, **ids):
    return {"view": view, "target": target, "status": "measured", "residual_m": residual,
            "residual_px": residual * 10, "confidence": confidence, "competing_runs": 0,
            "x_m": ids.pop("x_m", 10.0), "z_m": ids.pop("z_m", 2.0), **ids}


def test_cell_score_is_linear_to_five_percent_of_the_half_beam():
    assert cell_score(0.0, HALF_BEAM) == 1.0
    assert cell_score(-0.25, HALF_BEAM) == pytest.approx(0.5)
    assert cell_score(0.9, HALF_BEAM) == 0.0


def test_combined_fit_weights_views_by_their_share_of_measured_cells_and_skips_gaps():
    cells = ([_cell("body_plan", "station", 0.0, station_id="s01", waterline_id=f"w{j}") for j in range(3)]
             + [_cell("half_breadth_plan", "waterline", 0.5, station_id="s01", waterline_id="w1")]
             + [{"view": "half_breadth_plan", "target": "waterline", "status": "no_ink", "station_id": "s02",
                 "waterline_id": "w1", "x_m": 20.0, "z_m": 2.0}])
    board = scoreboard(cells, HALF_BEAM, revision="r0001")
    # body fit 1 on 3 cells, plan fit 0 on 1 cell: (3 x 1 + 1 x 0) / 4
    assert board["combined_fit"] == pytest.approx(0.75)
    assert board["mode"] == "three_view" and board["gap_cells"] == 1 and board["measured_cells"] == 4
    plan = board["views"]["half_breadth_plan"]
    assert plan["coverage"] == pytest.approx(0.5) and plan["max_abs_m"] == pytest.approx(0.5)
    assert board["worst"][0].startswith("w1 plan +0.50 m")
    assert board["summary_line"].startswith("draft r0001  fit 0.75  body 0.000 m  plan 0.500 m")


def test_low_confidence_cells_weigh_less_and_missing_stations_score_zero():
    confident = _cell("body_plan", "station", 0.0, station_id="s01", waterline_id="w1")
    doubtful = _cell("body_plan", "station", 0.5, confidence=0.25, station_id="s02", waterline_id="w1")
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
    assert rejected["keep"] is False and "0.6 -> 0.4" in rejected["reason"]


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
