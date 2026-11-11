"""Benchmark factory: geometry helpers, renderer determinism, specification contract, splits and scorer."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

pytest.importorskip('cv2', reason='the factory renderer needs the plan-raster extra (OpenCV)')

from benchmarks.factory import hulls as H
from benchmarks.factory import render as R
from benchmarks.factory import splits as S
from benchmarks.factory import truth as T


def test_chain_polylines_joins_shuffled_segments():
    points = np.array([[0.0, 0.0], [1.0, 0.5], [2.0, 1.5], [3.0, 3.0]])
    pieces = [points[[2, 3]], points[[0, 1]], points[[1, 2]][::-1]]
    chains = H.chain_polylines(pieces)
    assert len(chains) == 1 and len(chains[0]) == 4
    assert np.allclose(chains[0], points) or np.allclose(chains[0], points[::-1])


def test_clip_half_keeps_positive_side_and_interpolates():
    line = np.array([[-1.0, 0.0], [1.0, 2.0], [1.0, 3.0]])
    (kept,) = H.clip_half([line])
    assert kept[0][0] == pytest.approx(0.0) and kept[0][1] == pytest.approx(1.0)
    assert (kept[:, 0] >= 0).all()


def test_params_are_deterministic_and_levels_get_harder():
    assert R.sample_params(2, "separate", 7) == R.sample_params(2, "separate", 7)
    clean, heavy = R.sample_params(0, "separate", 7), R.sample_params(3, "separate", 7)
    assert clean["jpeg_quality"] == 100 and clean["rotation_deg"] == 0.0 and clean["occlusion_count"] == 0
    assert heavy["jpeg_quality"] < 60 and heavy["occlusion_count"] >= 1 and heavy["blur_sigma_px"] > 1.0


def _stations(count=9, length=100.0):
    stations = []
    for i in range(count):
        x = length * (i + 1) / (count + 1)
        z = np.linspace(0, 6, 40)
        y = 3.0 + 3.0 * np.sin(np.pi * (i + 1) / (count + 1)) * (z / 6) ** 0.5
        stations.append(R.Station(f"s{i + 1:02d}", round(x, 3), [np.column_stack([y, z])]))
    return stations


@pytest.mark.parametrize("layout", ["separate", "overlay"])
@pytest.mark.parametrize("level", [0, 3])
def test_render_is_deterministic_and_spec_is_valid(layout, level, tmp_path):
    from vessel_reconstruction.schema import validate_spec

    def make():
        params = R.sample_params(level, layout, 11)
        return R.make_case(_stations(), 6.0, 6.0, 100.0, params, "factory-test", "test", "synthetic")

    (image_a, spec_a, _), (image_b, spec_b, _) = make(), make()
    assert np.array_equal(image_a, image_b) and spec_a == spec_b
    from PIL import Image

    Image.fromarray(image_a).save(tmp_path / "drawing.png")
    assert validate_spec(spec_a, tmp_path) == []
    forbidden = {"points", "points_yz_m", "offsets", "ground_truth", "reference_mesh", "hull_parameters"}
    assert not forbidden & set(spec_a)
    for section in spec_a["sections"]:
        x0, y0, x1, y1 = section["roi_px"]
        assert 0 <= x0 < x1 <= image_a.shape[1] and 0 <= y0 < y1 <= image_a.shape[0]


def test_separate_rois_do_not_overlap():
    params = R.sample_params(3, "separate", 5)
    _, spec, _ = R.make_case(_stations(), 6.0, 6.0, 100.0, params, "v", "l", "d")
    boxes = [s["roi_px"] for s in spec["sections"]]
    for i, a in enumerate(boxes):
        for b in boxes[i + 1:]:
            assert a[2] <= b[0] or b[2] <= a[0] or a[3] <= b[1] or b[3] <= a[1]


def test_split_rules():
    split_of = S.cluster_splits()
    assert sorted(split_of) == list(range(S.N_CLUSTERS))
    for name, count in S.CLUSTERS_PER_SPLIT.items():
        assert sum(1 for v in split_of.values() if v == name) == count
    assert S.layout_for("kcs") == S.layout_for("kcs")
    assert {S.NAMED_SPLITS[k] for k in ("kcs", "kvlcc1", "kvlcc2")} == {"test"}
    overlay = sum(S.layout_for(f"h{i}") == "overlay" for i in range(2000)) / 2000
    assert 0.15 < overlay < 0.25


def test_deck_lid_removed_but_deck_edge_kept():
    curve = np.array([[0.0, 0.0], [2.0, 3.0], [2.5, 6.0], [1.0, 6.0], [0.0, 6.0]])
    (clean,) = R.clean_deck_edge([curve], 6.0)
    assert clean[-1].tolist() == [2.5, 6.0] and len(clean) == 3


def _box_hull(length=100.0, half=5.0, depth=6.0):
    from itertools import product

    corners = np.array(list(product([0, length], [-half, half], [0, depth])), dtype=float)
    faces = []
    for axis in range(3):
        for side in (0, 1):
            idx = [i for i, c in enumerate(corners) if c[axis] == (0, [length, half, depth][axis])[side] or
                   (axis != 0 and c[axis] == ([0, -half, 0][axis], [length, half, depth][axis])[side])]
            if len(idx) != 4:
                continue
            q = corners[idx]
            faces += [q[[0, 1, 2]], q[[1, 2, 3]]]
    return H.Hull("box", "box", np.array(faces), length, depth, half, False, {}, None, None)


@pytest.mark.cad
def test_scorer_recovers_a_box_exactly(tmp_path):
    import cadquery as cq

    hull = _box_hull()
    truth_path = tmp_path / "truth.npz"
    record = T.build_truth(hull, truth_path)
    assert record["volume_below_draft_m3"] == pytest.approx(100.0 * 10.0 * record["draft_m"], rel=5e-3)  # cuts at the flat ends lose half a step
    solid = cq.Workplane("XY").box(80000, 10000, 6000, centered=(False, True, False)).translate((10000, 0, 0))
    cq.exporters.export(solid, str(tmp_path / "model.step"))
    stations = [{"id": "a", "x_m": 10.5}, {"id": "b", "x_m": 50.0}, {"id": "c", "x_m": 89.5}]
    result = T.score_model(truth_path, tmp_path / "model.step", stations)
    assert result["status"] == "scored"
    assert result["summary"]["half_breadth_main"]["max_abs_m"] < 0.01
    assert abs(result["hydrostatics_at_design_draft"]["volume_error_relative_within_range"]) < 0.01
    assert result["hydrostatics_at_design_draft"]["volume_error_relative_full"] < -0.15
