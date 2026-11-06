from pathlib import Path
import numpy as np
import cadquery as cq
import pytest

from vessel_reconstruction.geometry import build_hull, export_geometry, GeometryError


def rectangular_sections():
    return [{"id": f"s{i}", "x_m": x, "points_yz_m": [[2.0, float(z)] for z in np.linspace(0, 3, 11)]} for i, x in enumerate([0, 5, 10])]


def test_box_hull_preserves_real_units_and_volume(tmp_path):
    shape, _ = build_hull(rectangular_sections())
    exports, metrics = export_geometry(shape, tmp_path)
    assert shape.isValid()
    assert metrics["volume_m3"] == pytest.approx(120, rel=1e-9)
    assert metrics["beam_m"] == pytest.approx(4)
    assert metrics["length_m"] == pytest.approx(10)
    step = cq.importers.importStep(str(tmp_path / "model.step")).val()
    assert step.BoundingBox().xlen == pytest.approx(10000)  # millimetres, never 10 mm
    assert step.Volume() == pytest.approx(120e9)
    assert exports["step_units"] == "mm"
    assert metrics["step_roundtrip_relative_error"] < 1e-9


def test_degenerate_section_is_rejected():
    sections = rectangular_sections()
    sections[1]["points_yz_m"] = [[0, float(z)] for z in np.linspace(0, 3, 11)]
    with pytest.raises(GeometryError, match="degenerates"):
        build_hull(sections)


def test_duplicate_stations_are_rejected():
    sections = rectangular_sections()
    sections[1]["x_m"] = sections[0]["x_m"]
    with pytest.raises(GeometryError, match="strictly"):
        build_hull(sections)


def test_no_nan_geometry():
    sections = rectangular_sections()
    sections[1]["points_yz_m"][3][0] = float("nan")
    with pytest.raises(GeometryError, match="Invalid"):
        build_hull(sections)


def test_mixed_keels_and_flat_bottoms_preserve_measured_volume_and_step(tmp_path):
    # Independently specified trapezoids alternate a zero-width keel with a
    # finite flat bottom. They have unequal closed-wire edge counts, but the
    # half-section correspondence is explicit. The exact area is H*(b+w).
    xs = [0.0, 1.1, 4.3, 9.0, 12.0]
    bottoms = [0.0, 0.35, 0.0, 0.15, 0.0]
    tops = [0.8, 1.2, 1.8, 1.1, 0.6]
    height = 3.2
    sections = [{
        "id": f"mixed-{i}", "x_m": x,
        "points_yz_m": [[b + (w - b) * z / height, float(z)] for z in np.linspace(0, height, 9)],
    } for i, (x, b, w) in enumerate(zip(xs, bottoms, tops))]
    areas = [height * (b + w) for b, w in zip(bottoms, tops)]
    expected = sum((xs[i + 1] - xs[i]) * (areas[i] + areas[i + 1]) / 2 for i in range(len(xs) - 1))
    shape, normalized = build_hull(sections)
    assert shape.isValid() and len(shape.Shells()) == 1 and shape.Shells()[0].Closed()
    assert len(shape.Solids()) == 1
    assert shape.Volume() / 1e9 == pytest.approx(expected, rel=1e-9)
    # No epsilon breadth is inserted into the zero-width observations.
    assert [s["cad_points_yz_m"][0][0] for s in normalized] == bottoms
    exports, metrics = export_geometry(shape, tmp_path)
    reloaded = cq.importers.importStep(str(tmp_path / exports["step"])).val()
    assert reloaded.isValid() and len(reloaded.Shells()) == 1 and reloaded.Shells()[0].Closed()
    assert reloaded.Volume() / 1e9 == pytest.approx(expected, rel=1e-9)
    assert metrics["step_roundtrip_extent_error"] < 1e-9
    # Independently check exported mesh closure and outward orientation.
    import trimesh
    stl = trimesh.load(tmp_path / exports["stl"], force="mesh")
    assert stl.is_watertight and stl.is_winding_consistent
    assert stl.volume > 0
    # STL approximates the nonplanar ruled surfaces at the declared mesh
    # tolerance; the exact-volume checks above apply to the BRep and STEP.
    assert stl.volume / 1e9 == pytest.approx(expected, rel=1e-3)


def test_changing_vertical_ranges_have_planar_top_bottom_and_correct_volume():
    xs = [0.0, 3.0, 8.0]
    half_widths = [1.0, 2.2, 1.5]
    heights = [2.0, 3.5, 2.8]
    bases = [-0.5, 0.2, -0.1]
    sections = [{
        "id": f"range-{i}", "x_m": x,
        "points_yz_m": [[w, float(z)] for z in np.linspace(base, base + h, 9)],
    } for i, (x, w, h, base) in enumerate(zip(xs, half_widths, heights, bases))]
    # Width and height vary linearly within each ruled bay, so cross-sectional
    # area is quadratic in x and Simpson's integral is exact.
    expected = 0.0
    for i in range(len(xs) - 1):
        left = 2 * half_widths[i] * heights[i]
        right = 2 * half_widths[i + 1] * heights[i + 1]
        middle = 2 * ((half_widths[i] + half_widths[i + 1]) / 2) * ((heights[i] + heights[i + 1]) / 2)
        expected += (xs[i + 1] - xs[i]) * (left + 4 * middle + right) / 6
    shape, _ = build_hull(sections)
    assert shape.isValid() and len(shape.Shells()) == 1 and shape.Shells()[0].Closed()
    assert shape.Volume() / 1e9 == pytest.approx(expected, rel=1e-9)
    assert shape.BoundingBox().zmin == pytest.approx(-500)
    assert shape.BoundingBox().zmax == pytest.approx(3700)


def test_zero_area_centreline_spur_does_not_invent_material():
    # The lower metre is exactly zero-width, followed by a triangular section.
    # Removing its retraced cap-wire spur must not add an epsilon-width strip.
    sections = [{
        "id": f"spur-{i}", "x_m": x,
        "points_yz_m": [[max(0, float(z) - 1), float(z)] for z in np.linspace(0, 4, 9)],
    } for i, x in enumerate([0.0, 2.0, 7.0])]
    shape, normalized = build_hull(sections)
    assert shape.isValid() and len(shape.Shells()) == 1 and shape.Shells()[0].Closed()
    assert shape.Volume() / 1e9 == pytest.approx(63.0, rel=1e-9)
    assert shape.BoundingBox().zmin == pytest.approx(1000)
    assert normalized[0]["cad_points_yz_m"][0] == [0.0, 0.0]


def test_interior_centreline_pinch_is_rejected_without_width_adjustment():
    sections = [{
        "id": f"pinched-{i}", "x_m": x,
        "points_yz_m": [[1.0, 0.0], [0.5, 1.0], [0.0, 2.0], [0.5, 3.0], [1.0, 4.0]],
    } for i, x in enumerate([0.0, 2.0, 7.0])]
    with pytest.raises(GeometryError, match="pinch"):
        build_hull(sections)

