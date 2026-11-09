"""Bottom completion must not replace measured section evidence."""
import copy

import numpy as np
import pytest

from vessel_reconstruction.first_hull_tools import cut_bottoms_at_keel, extend_bottoms_to_keel
from vessel_reconstruction.form_fit import Anchor


def _anchors(source="read"):
    cells = [[0.6, 0.8], [0.9, 1.0], [1.1, 1.2], [1.2, 1.4]]
    return [
        Anchor("1", 0.0, [[0.0, 0.0], [1.0, 1.4]], {}, pixels_per_metre=100.0),
        Anchor("2", 1.0, cells, {}, pixels_per_metre=100.0, source=source),
        Anchor("3", 2.0, [[0.0, 0.0], [1.0, 1.4]], {}, pixels_per_metre=100.0),
    ]


@pytest.mark.parametrize("source", ["read", "traced"])
def test_bottom_completion_keeps_four_measured_waterlines_and_their_direction(source):
    anchors = _anchors(source)
    original = copy.deepcopy(anchors[1].points_yz_m)
    extend_bottoms_to_keel(anchors, {a.id: 0.0 for a in anchors})
    points = np.asarray(anchors[1].points_yz_m)
    for y, z in original:
        assert np.interp(z, points[:, 1], points[:, 0]) == pytest.approx(y)
    # Immediately below the lowest cell, continue its local direction, not
    # the chord from (0, keel) to (0.6, 0.8), whose slope is only 0.75.
    slope = (original[1][0] - original[0][0]) / (original[1][1] - original[0][1])
    assert np.interp(0.79, points[:, 1], points[:, 0]) == pytest.approx(0.6 - 0.01 * slope, abs=0.001)
    assert all(list(p) in anchors[1].points_yz_m for p in original)


@pytest.mark.parametrize("source", ["read", "traced"])
def test_profile_bottom_handling_does_not_cut_measured_cells(source):
    anchors = _anchors(source)
    original = copy.deepcopy(anchors[1].points_yz_m)
    cut_bottoms_at_keel(anchors, {"1": 0.0, "2": 1.0, "3": 0.0})
    assert anchors[1].points_yz_m == original


def test_transom_curve_end_above_keel_is_not_extended():
    anchors = _anchors()
    # A terminal station's drawn lower end is a transom, not missing bottom ink.
    anchors[0].points_yz_m = [[0.4, 0.5], [0.7, 0.8], [0.9, 1.1], [1.0, 1.4]]
    original = copy.deepcopy(anchors[0].points_yz_m)
    extend_bottoms_to_keel(anchors, {a.id: 0.0 for a in anchors})
    assert anchors[0].points_yz_m == original
    assert not anchors[0].extended


def test_completed_bottom_has_interpolated_labels_but_cells_keep_their_sources():
    from vessel_reconstruction.form_fit import fit_vessel
    from vessel_reconstruction.vessel_model import VesselTable, build_spec

    anchors = _anchors()
    for anchor in anchors:
        anchor.source = "read"
    original = copy.deepcopy(anchors[1].points_yz_m)
    extend_bottoms_to_keel(anchors, {a.id: 0.0 for a in anchors})
    sections = [{"id": a.id, "x_m": a.x_m, "z_min_m": 0.0, "z_max_m": 1.4} for a in anchors]
    table = fit_vessel(sections, anchors)
    row = next(r for r in table.stations if r.id == "2")
    assert row.point_sources
    for point, source in zip(row.points_yz_m, row.point_sources):
        assert source == ("read" if point in original else "interpolated")
    restored = VesselTable.from_json(table.to_json())
    assert restored.stations[1].point_sources == row.point_sources
    spec = build_spec(table, {"sections": sections}, sections)
    section = next(s for s in spec["sections"] if s["id"] == "2")
    assert section["authored"]["source_label"] == "interpolated"
    for point in original:
        assert point in section["authored"]["points_yz_m"]
