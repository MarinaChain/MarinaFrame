"""Three-view lines drawings (layout lines_3view): render smoke test and plan/body-plan consistency."""
from __future__ import annotations

import numpy as np
import pytest

from benchmarks.factory import hulls as H
from benchmarks.factory import lines as L
from benchmarks.factory import render as R
from benchmarks.factory import render_lines as RL
from benchmarks.factory import truth as T

LENGTH, HALF_BREADTH, DEPTH = 100.0, 7.0, 8.0


def _half_breadth(x, z):
    """Analytic test hull: zero at keel (z = 0) and at both ends, widest at midships and the top."""
    xi = 2.0 * x / LENGTH - 1.0
    return HALF_BREADTH * (1.0 - xi ** 2) * (1.0 - (1.0 - z / DEPTH) ** 2)


def synthetic_hull(nx: int = 101, nz: int = 33) -> H.Hull:
    """Open triangle mesh of both sides of the analytic hull, in the canonical frame."""
    x = np.linspace(0.0, LENGTH, nx)
    z = np.linspace(0.0, DEPTH, nz)
    xx, zz = np.meshgrid(x, z, indexing="ij")
    triangles = []
    for side in (1.0, -1.0):
        grid = np.stack([xx, side * _half_breadth(xx, zz), zz], axis=-1)
        a, b, c, d = grid[:-1, :-1], grid[1:, :-1], grid[1:, 1:], grid[:-1, 1:]
        triangles.append(np.stack([a, b, c], axis=-2).reshape(-1, 3, 3))
        triangles.append(np.stack([a, c, d], axis=-2).reshape(-1, 3, 3))
    triangles = np.concatenate(triangles)
    return H.Hull("synthetic", "synthetic", triangles, LENGTH, DEPTH, HALF_BREADTH, False, {"source": "test"})


@pytest.fixture(scope="module")
def lines():
    hull = synthetic_hull()
    stations = []
    for index, x in enumerate(T.station_positions(hull.length_m, R.STATION_FRACTIONS)):
        stations.append(R.Station(f"s{index + 1:02d}", x, R.clean_deck_edge(hull.drawn_section(x), hull.depth_m)))
    return L.build_lines(hull, stations, draft_m=T.DRAFT_FRACTION * DEPTH)


def _render(lines, level):
    params = R.sample_params(level, RL.LAYOUT, 11)
    return RL.make_lines_case(lines, params, "factory-test", "test", "synthetic")


def test_lines_geometry_has_every_view(lines):
    assert lines.waterline_step_m == 1.0 and list(lines.waterlines) == [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0]
    assert lines.buttock_step_m == 2.0 and list(lines.buttocks) == [2.0, 4.0, 6.0]
    for z, polylines in lines.waterlines.items():
        points = np.vstack(polylines)
        assert (points[:, 1] >= -1e-9).all()
        assert points[:, 1].max() == pytest.approx(_half_breadth(50.0, z), abs=0.02)
    profile = np.vstack(lines.profile)
    assert profile[:, 1].min() == pytest.approx(0.0, abs=0.05)  # keel on the baseline
    assert len(lines.deck) > 90 and np.allclose(lines.deck[:, 2], DEPTH)
    assert lines.waterline_length_m == pytest.approx(LENGTH, abs=0.5)


@pytest.mark.parametrize("level", [0, 3])
def test_three_view_render_smoke(lines, level, tmp_path):
    from PIL import Image

    from vessel_reconstruction.schema import validate_spec

    image, spec, views, record = _render(lines, level)
    again = _render(lines, level)
    assert np.array_equal(image, again[0]) and spec == again[1] and views == again[2]
    height, width = image.shape[:2]
    assert views["sheet_size_px"] == [width, height]
    kinds = {v["kind"] for v in views["views"]}
    assert kinds == {"profile", "half_breadth_plan", "body_plan", "title_block"}
    for view in views["views"]:
        x0, y0, x1, y1 = view["roi_px"]
        assert 0 <= x0 < x1 <= width and 0 <= y0 < y1 <= height
    by_id = {v["id"]: v for v in views["views"]}
    assert by_id["profile"]["roi_px"][3] < by_id["half_breadth_plan"]["roi_px"][1]  # profile above plan
    assert by_id["body_plan"]["roi_px"][0] > by_id["profile"]["roi_px"][2]  # body plan to the side
    Image.fromarray(image).save(tmp_path / "drawing.png")
    assert validate_spec(spec, tmp_path) == []
    text = repr(spec) + repr(views)
    for forbidden in ("ground_truth", "half_breadth_table", "yz_m", "xy_m", "xz_m"):
        assert forbidden not in text


def test_plan_waterlines_match_body_plan_stations_within_a_pixel(lines):
    """Same (x, z): waterline half-breadth in plan == station half-breadth in body plan, within 1 px."""
    _, _, views, record = _render(lines, 0)
    ppm = record["ppm"]
    rows = L.cross_check(lines, ppm)
    assert len(rows) >= 50
    assert max(r["difference_px"] for r in rows) <= 1.0


def test_rendered_plan_ink_is_where_the_body_plan_says(lines):
    """On the clean sheet, the waterline ink at a station column lies on the body-plan half-breadth, within 1 px."""
    image, _, views, record = _render(lines, 0)
    gray = image.astype(float).mean(axis=2)
    plan = next(v for v in views["views"] if v["kind"] == "half_breadth_plan")["calibration"]
    ppm = plan["pixels_per_metre"]
    checked = 0
    for station in lines.stations:
        predicted = {z: L.station_half_breadth_at(station.curves, z) for z in lines.waterlines}
        deck = L.station_half_breadth_at(station.curves, DEPTH - 1e-6)
        column = int(round(plan["x_origin_px"] + station.x_m * ppm))
        for z, y in predicted.items():
            if y is None:
                continue
            row = plan["centerline_px"] - y * ppm
            others = [plan["centerline_px"] - v * ppm for k, v in predicted.items() if k != z and v is not None]
            others.append(plan["centerline_px"] - deck * ppm)
            if min(abs(row - o) for o in others) < 9.0:  # another curve too close to tell apart
                continue
            window = np.arange(int(row) - 5, int(row) + 7)
            darkness = np.clip(140.0 - gray[window][:, column - 1:column + 2].mean(axis=1), 0.0, None)
            assert darkness.sum() > 0, f"no ink near station {station.station_id} WL{z:g}"
            measured = float((window * darkness).sum() / darkness.sum())
            assert abs(measured - row) <= 1.0, (station.station_id, z, measured, row)
            checked += 1
    assert checked >= 10
