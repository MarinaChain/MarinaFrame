"""Multi-region stations: exact decomposition and lofts with known area and volume."""
from __future__ import annotations

import math

import numpy as np
import pytest

from vessel_reconstruction import section_regions as sr
from vessel_reconstruction.errors import GeometryError

# A wall-sided hull with one rectangular skeg per side: the skeg spans
# y = 1..2 m below z = 1 m; the hull spans y = 0..3 m from z = 1 m to 2 m.
TWIN_SKEG = [[0, 1], [1, 1], [1, 0], [2, 0], [2, 1], [3, 1], [3, 2], [0, 2]]
TWIN_SKEG_HALF_AREA = 1.0 + 3.0


def circle(centre_y: float, centre_z: float, radius: float, count: int = 64) -> list[list[float]]:
    angle = np.linspace(0, 2 * np.pi, count, endpoint=False)
    return np.column_stack([centre_y + radius * np.cos(angle), centre_z + radius * np.sin(angle)]).tolist()


def test_twin_skeg_splits_into_offset_and_centreline_regions():
    regions = sr.decompose_outline([TWIN_SKEG])
    kinds = sorted(region["kind"] for region in regions)
    assert kinds == [sr.CENTRELINE, sr.OFFSET]
    skeg = next(r for r in regions if r["kind"] == sr.OFFSET)
    hull = next(r for r in regions if r["kind"] == sr.CENTRELINE)
    assert skeg["rows_m"] == [[0.0, 1.0, 2.0], [1.0, 1.0, 2.0]]
    assert hull["rows_m"] == [[1.0, 0.0, 3.0], [2.0, 0.0, 3.0]]
    assert sum(r["area_m2"] for r in regions) == pytest.approx(TWIN_SKEG_HALF_AREA, abs=1e-12)


def test_sloped_tunnel_roof_gives_a_centreline_wedge_and_keeps_area():
    # The roof rises from the centreline (z = 1.5) to the skeg (z = 1.8): between
    # those heights there is material near the centreline and in the skeg.
    roof = [[0, 1.5], [2.2, 1.8], [2.3, 0.0], [3.0, 0.0], [3.1, 2.0], [4.8, 3.0], [4.8, 5.0], [0, 5.0]]
    regions = sr.decompose_outline([roof])
    assert [r["kind"] for r in regions].count(sr.CENTRELINE) == 2
    assert [r["kind"] for r in regions].count(sr.OFFSET) == 1
    assert sum(r["area_m2"] for r in regions) == pytest.approx(sr.ring_area(np.array(roof)), rel=1e-12)


def test_bulb_and_bow_pieces_are_separate_regions():
    bulb = [[0, 0], [0.8, 0.5], [0, 1.0]]
    bow = [[0, 1.5], [1.0, 1.5], [1.5, 3.0], [0, 3.0]]
    regions = sr.decompose_outline([bulb, bow])
    assert [r["z_range_m"] for r in regions] == [[0.0, 1.0], [1.5, 3.0]]
    assert all(r["kind"] == sr.CENTRELINE for r in regions)
    assert sum(r["area_m2"] for r in regions) == pytest.approx(0.4 + 1.875, rel=1e-12)


def test_horizontal_ledge_is_a_step_inside_one_region():
    ledge = [[0, 0], [1, 0], [1, 1], [2, 1], [2, 2], [0, 2]]
    regions = sr.decompose_outline([ledge])
    assert len(regions) == 1
    assert regions[0]["rows_m"] == [[0.0, 0.0, 1.0], [1.0, 0.0, 1.0], [1.0, 0.0, 2.0], [2.0, 0.0, 2.0]]
    assert regions[0]["area_m2"] == pytest.approx(3.0)


def test_heights_differing_by_rounding_do_not_open_regions():
    flat_start = [[0, 0.0], [0.1, 1e-12], [1.0, 1.0], [1.0, 2.0], [0, 2.0]]
    regions = sr.decompose_outline([flat_start])
    assert len(regions) == 1 and regions[0]["kind"] == sr.CENTRELINE


def test_overlapping_pieces_and_bad_rings_are_refused():
    with pytest.raises(GeometryError, match="overlap"):
        sr.decompose_outline([[[0, 0], [2, 0], [2, 2], [0, 2]], [[1, 1], [3, 1], [3, 3], [1, 3]]])
    with pytest.raises(GeometryError, match="crosses the centreline"):
        sr.decompose_outline([[[-0.1, 0], [1, 0], [1, 1]]])
    with pytest.raises(GeometryError):
        sr.decompose_outline([])


def test_matching_is_mutual_and_kind_specific():
    a = sr.decompose_outline([TWIN_SKEG])
    b = sr.decompose_outline([[[0, 1], [3, 1], [3, 2], [0, 2]]])  # no skeg here
    matches = sr.match_regions(a, b)
    assert len(matches) == 1
    assert a[matches[0][0]]["kind"] == sr.CENTRELINE


def test_step_knots_keep_left_and_right_values():
    t = np.array([0.0, 0.5, 0.5, 1.0])
    y = np.array([1.0, 1.0, 2.0, 2.0])
    knots = sr.merge_knots([sr.boundary_knots(t, y, 0.001)])
    assert knots == [(0.0, 1), (0.5, 2), (1.0, 1)]
    assert sr.evaluate_boundary(t, y, knots).tolist() == [1.0, 1.0, 2.0, 2.0]
    plain = sr.evaluate_boundary(np.array([0.0, 1.0]), np.array([0.0, 2.0]), knots)
    assert plain.tolist() == [0.0, 1.0, 1.0, 2.0]


# CAD lofts ------------------------------------------------------------------------

geometry = pytest.importorskip("vessel_reconstruction.geometry")


def stations(rings_by_x: dict[float, list]) -> list[dict]:
    return [{"id": f"s{i}", "x_m": x, "regions": sr.decompose_outline(rings, section_id=f"s{i}")}
            for i, (x, rings) in enumerate(sorted(rings_by_x.items()))]


def test_twin_skeg_prism_has_exact_volume():
    shape, report = geometry.build_region_hull(stations({0.0: [TWIN_SKEG], 5.0: [TWIN_SKEG], 10.0: [TWIN_SKEG]}))
    # Two sides, length 10 m: the whole section area is twice the half area.
    assert shape.Volume() / 1e9 == pytest.approx(2 * TWIN_SKEG_HALF_AREA * 10.0, rel=1e-9)
    assert report["volume_m3"] == pytest.approx(80.0, rel=1e-9)
    assert report["solid_count"] == 3  # hull, port skeg, starboard skeg
    assert not report["unlofted_regions"]
    assert all(s.isValid() for s in shape.Solids())


def test_twin_circular_skegs_follow_the_polygon_area():
    skeg = circle(1.5, 0.6, 0.4)
    hull = [[0, 1.2], [3, 1.2], [3, 2.5], [0, 2.5]]
    shape, report = geometry.build_region_hull(stations({0.0: [skeg, hull], 4.0: [skeg, hull]}))
    expected = 2 * (sr.ring_area(np.array(skeg)) + 3 * 1.3) * 4.0
    assert shape.Volume() / 1e9 == pytest.approx(expected, rel=1e-9)
    assert report["solid_count"] == 3


def test_tapered_skeg_volume_is_the_prismatoid():
    def skeg(width: float) -> list:
        return [[0, 1], [1, 1], [1, 0], [1 + width, 0], [1 + width, 1], [3, 1], [3, 2], [0, 2]]

    shape, report = geometry.build_region_hull(stations({0.0: [skeg(1.0)], 6.0: [skeg(0.5)]}))
    # Skeg area falls linearly from 1.0 to 0.5 m2 per side; the hull is 3 m2 per side.
    expected = 2 * (6.0 * (1.0 + 0.5) / 2 + 3.0 * 6.0)
    assert shape.Volume() / 1e9 == pytest.approx(expected, rel=1e-9)


def test_region_present_at_one_station_is_reported_not_dropped():
    plain = [[0, 1], [3, 1], [3, 2], [0, 2]]
    shape, report = geometry.build_region_hull(stations({0.0: [plain], 5.0: [TWIN_SKEG], 10.0: [plain]}))
    assert [u["station"] for u in report["unlofted_regions"]] == ["s1"]
    assert report["unlofted_regions"][0]["half_area_m2"] == pytest.approx(1.0)
    assert shape.Volume() / 1e9 == pytest.approx(2 * 3.0 * 10.0, rel=1e-9)


def test_bulb_run_ends_with_a_flat_closure():
    angle = np.linspace(-np.pi / 2, np.pi / 2, 17)  # half circle from the keel to the top
    bulb = np.column_stack([np.maximum(0.4 * np.cos(angle), 0.0), 0.5 + 0.4 * np.sin(angle)])
    bow = [[0, 1.2], [1.0, 1.2], [1.5, 3.0], [0, 3.0]]
    shape, report = geometry.build_region_hull(stations({0.0: [bow], 2.0: [bulb.tolist(), bow], 4.0: [bulb.tolist(), bow]}))
    bulb_area = sr.ring_area(bulb)
    bow_area = sr.ring_area(np.array(bow))
    expected = 2 * (bow_area * 4.0 + bulb_area * 2.0)
    assert shape.Volume() / 1e9 == pytest.approx(expected, rel=1e-9)
    assert len(report["runs"]) == 2


def test_ledge_against_a_plain_station_builds_a_valid_solid():
    ledge = [[0, 0], [1, 0], [1, 1], [2, 1], [2, 2], [0, 2]]
    plain = [[0, 0], [1.5, 0], [1.5, 2], [0, 2]]
    shape, report = geometry.build_region_hull(stations({0.0: [ledge], 3.0: [plain]}))
    assert all(s.isValid() for s in shape.Solids())
    # Prismatoid of corresponding polygons; the volume audit inside the builder
    # already compares kernel and polygon volume; check it once more here.
    assert report["volume_m3"] == pytest.approx(shape.Volume() / 1e9, rel=1e-9)
    assert 2 * 3.0 * 3.0 * 0.9 < report["volume_m3"] < 2 * 3.0 * 3.0 * 1.1


def test_legacy_half_sections_give_the_build_hull_volume():
    z = np.linspace(0, 3, 40)
    legacy = [{"id": f"l{i}", "x_m": 4.0 * i, "points_yz_m": np.column_stack([s * 2 * np.sqrt(z / 3), z]).tolist()}
              for i, s in enumerate((0.6, 1.0, 0.7))]
    reference, _ = geometry.build_hull(legacy)
    shape, report = geometry.build_region_hull(legacy)
    # build_hull interpolates each station from its own kept knots; the region
    # loft evaluates the source polyline at every common knot. Both stay within
    # the 1 mm bound, so the volumes agree closely but not exactly.
    assert shape.Volume() / reference.Volume() == pytest.approx(1.0, abs=1e-4)
    assert report["maximum_half_breadth_deviation_m"] <= 0.001 + 1e-12
    assert math.isclose(report["volume_m3"], shape.Volume() / 1e9, rel_tol=1e-9)


def _one_face_cases() -> dict:
    def skeg(width: float) -> list:
        return [[0, 1], [1, 1], [1, 0], [1 + width, 0], [1 + width, 1], [3, 1], [3, 2], [0, 2]]

    angle = np.linspace(-np.pi / 2, np.pi / 2, 17)
    bulb = np.column_stack([np.maximum(0.4 * np.cos(angle), 0.0), 0.5 + 0.4 * np.sin(angle)]).tolist()
    bow = [[0, 1.2], [1.0, 1.2], [1.5, 3.0], [0, 3.0]]
    z = np.linspace(0, 3, 40)
    return {
        "twin_skeg": stations({0.0: [TWIN_SKEG], 5.0: [TWIN_SKEG], 10.0: [TWIN_SKEG]}),
        "tapered_skeg": stations({0.0: [skeg(1.0)], 6.0: [skeg(0.5)], 9.0: [skeg(0.2)]}),
        "bulb": stations({0.0: [bow], 2.0: [bulb, bow], 4.0: [bulb, bow]}),
        "curved": [{"id": f"l{i}", "x_m": 4.0 * i, "points_yz_m": np.column_stack([s * 2 * np.sqrt(z / 3), z]).tolist()}
                   for i, s in enumerate((0.6, 1.0, 0.7, 0.3))],
    }


@pytest.mark.parametrize("case", sorted(_one_face_cases()))
def test_one_face_per_side_keeps_the_panel_geometry(case):
    sections = _one_face_cases()[case]
    panels, panel_report = geometry.build_region_hull(sections)
    light, light_report = geometry.build_region_hull(sections, one_face_per_side=True)
    assert geometry.precise_volume_mm3(light) == pytest.approx(panels.Volume(), rel=1e-7)
    assert light_report["volume_m3"] == pytest.approx(panel_report["volume_m3"], rel=1e-7)
    assert all(solid.isValid() for solid in light.Solids())
    assert light_report["solid_count"] == panel_report["solid_count"]
    # One side face and two end caps per solid.
    assert len(light.Faces()) == 3 * light_report["solid_count"]
    assert light_report["side_faces"] == "one_bilinear_bspline_per_side"
    box_a, box_b = panels.BoundingBox(), light.BoundingBox()
    for a, b in ((box_a.xmin, box_b.xmin), (box_a.ymax, box_b.ymax), (box_a.zmin, box_b.zmin), (box_a.zmax, box_b.zmax)):
        assert a == pytest.approx(b, abs=1e-3)
