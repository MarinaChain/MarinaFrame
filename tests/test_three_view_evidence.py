"""Cross-view evidence is measured ink, with explicit association uncertainty."""
import copy

import numpy as np
import pytest

from vessel_reconstruction import three_view_evidence as evidence

def fixture():
    grey = np.full((210, 260), 255.)
    ppm, origin = 20., 20.
    sections = []
    for x in (0., 5., 10.):
        z = np.linspace(0, 2, 21)
        sections.append({"id": f"s{x:g}", "x_m": x, "source_label": "read",
                         "points_yz_m": np.column_stack([1 + .2 * z + .02 * x, z]).tolist()})
    for column in range(20, 221):
        x = (column - origin) / ppm
        for z in (.5, 1., 1.5, 2.):
            row = int(180 - (1 + .2 * z + .02 * x) * ppm)
            grey[row, column] = 0
        grey[35, column] = grey[75, column] = 0
    views = {
        "profile": {"roi_px": [10, 20, 235, 85], "waterlines_z_m": [.5, 1., 1.5],
                    "calibration": {"pixels_per_metre": ppm, "x_origin_px": origin, "baseline_px": 75.5}},
        "half_breadth_plan": {"roi_px": [10, 120, 235, 190],
                              "calibration": {"pixels_per_metre": ppm, "x_origin_px": origin, "centerline_px": 180.5}}}
    return sections, grey, views


def test_collects_between_stations_in_hull_metres_without_mutating_reading():
    sections, grey, views = fixture()
    before = copy.deepcopy(sections)
    result = evidence.collect(sections, grey, views)
    assert sections == before
    plan = [p for p in result["points"] if p["view"] == "half_breadth_plan" and p["target"] == "waterline"]
    assert {p["z_m"] for p in plan} == {.5, 1., 1.5}
    assert any(0 < p["x_m"] < 5 for p in plan)
    for point in plan:
        expected = 1 + .2 * point["z_m"] + .02 * point["x_m"]
        assert point["y_m"] == pytest.approx(expected, abs=.06)
        assert point["source_label"] in ("traced", "repaired")
        assert point["association"] == "stored_hull_prediction"
    profile = [p for p in result["points"] if p["view"] == "profile"]
    assert {p["target"] for p in profile} >= {"keel", "top"}
    assert all(p["y_m"] is None for p in profile)
    assert result["coverage"]["half_breadth_plan"]["between_station_points"] > 0


def test_shared_ink_is_not_counted_as_two_traced_waterlines():
    points = [{"x_m": 2., "y_m": 1., "z_m": z, "view": "half_breadth_plan", "target": "waterline",
               "source_label": "traced", "confidence": 1., "pixel_xy": [60., 160.], "curve_id": f"wl{z}"}
              for z in (.5, 1.)]
    evidence.mark_shared_ink(points, pixels_per_metre=20.)
    assert all(p["source_label"] == "repaired" and p["confidence"] <= .25 for p in points)
    assert all(p["shared_ink"] for p in points)


def test_missing_views_stay_missing_and_do_not_invent_curves():
    sections, grey, _ = fixture()
    result = evidence.collect(sections, grey, {})
    assert {p["view"] for p in result["points"]} == {"body_plan"}
    assert result["coverage"]["profile"]["available"] is False
    assert result["coverage"]["half_breadth_plan"]["points"] == 0
