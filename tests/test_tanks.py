"""Tanks: fill properties, sounding tables and the capacity plan on solids with exact answers."""
import math

import numpy as np
import pytest
import trimesh

from vessel_reconstruction import tanks

# Box tank: x 1..3 (L = 2), y -1..2 (B = 3), z 0.5..4.5 (H = 4).
BOX_MIN, BOX_MAX = (1.0, -1.0, 0.5), (3.0, 2.0, 4.5)


def box_triangles(low=BOX_MIN, high=BOX_MAX) -> np.ndarray:
    """An independent box mesh (trimesh), so the prism builder is not used to test itself."""
    extents = np.subtract(high, low)
    mesh = trimesh.creation.box(extents=extents)
    mesh.apply_translation(np.add(low, high) / 2)
    return mesh.triangles


def wedge_triangles(length=2.0) -> np.ndarray:
    """Triangular prism in x from 0 to ``length``; section (y, z): (0, 0), (2, 0), (0, 2).
    At height z the tank is 2 - z wide."""
    return tanks.prism_triangles(0.0, length, [(0, 0), (2, 0), (0, 2)])


def test_box_fill_state_is_exact():
    triangles = box_triangles()
    state = tanks.fill_state(triangles, 2.5)
    assert state.volume_m3 == pytest.approx(2 * 3 * 2.0)
    assert state.centroid_m == pytest.approx((2.0, 0.5, 1.5))
    assert state.free_surface_m2 == pytest.approx(6.0)
    assert state.i_transverse_m4 == pytest.approx(2 * 3 ** 3 / 12)
    assert state.i_longitudinal_m4 == pytest.approx(3 * 2 ** 3 / 12)


def test_inward_mesh_is_turned_outward():
    triangles = box_triangles()[:, ::-1]
    assert tanks.fill_state(tanks.outward(triangles), 4.5).volume_m3 == pytest.approx(24.0)


@pytest.mark.parametrize("level", [0.0, 0.3, 1.0, 1.7, 2.0])
def test_wedge_fill_state_is_exact(level):
    length = 2.0
    state = tanks.fill_state(wedge_triangles(length), level)
    area = 2 * level - level ** 2 / 2
    assert state.volume_m3 == pytest.approx(length * area, abs=1e-12)
    if area > 0:
        tcg = (8 - (2 - level) ** 3) / 6 / area
        vcg = (level ** 2 - level ** 3 / 3) / area
        assert state.centroid_m == pytest.approx((length / 2, tcg, vcg))
    width = 2 - min(max(level, 1e-6), 2 - 1e-6)
    assert state.free_surface_m2 == pytest.approx(length * width, abs=1e-5)
    assert state.i_transverse_m4 == pytest.approx(length * width ** 3 / 12, abs=1e-5)


def test_sounding_table_rows_and_last_level():
    rows = tanks.sounding_table(box_triangles(), interval_m=1.5)
    assert [r["sounding_m"] for r in rows] == pytest.approx([0.0, 1.5, 3.0, 4.0])
    assert [r["ullage_m"] for r in rows] == pytest.approx([4.0, 2.5, 1.0, 0.0])
    assert [r["volume_m3"] for r in rows] == pytest.approx([0.0, 9.0, 18.0, 24.0])
    assert rows[-1]["fill_pct"] == pytest.approx(100.0)
    assert rows[1]["vcg_m"] == pytest.approx(0.5 + 0.75)
    # The free surface at the top is taken just inside the tank: the full box section.
    assert rows[-1]["i_transverse_m4"] == pytest.approx(4.5)


def test_prism_matches_box_and_triangulates_concave_outline():
    prism = tanks.prism_triangles(1.0, 3.0, [(-1, 0.5), (2, 0.5), (2, 4.5), (-1, 4.5)])
    assert tanks.fill_state(prism, 4.5).volume_m3 == pytest.approx(24.0)
    # An L-shaped section (area 3) with collinear and repeated points.
    outline = [(0, 0), (1, 0), (2, 0), (2, 1), (1, 1), (1, 2), (0, 2), (0, 2), (0, 1)]
    state = tanks.fill_state(tanks.prism_triangles(0.0, 1.0, outline), 2.0)
    assert state.volume_m3 == pytest.approx(3.0)
    assert state.centroid_m == pytest.approx((0.5, (0.5 * 1 * 2 + 1.5 * 1 * 1) / 3, (1.0 * 2 + 0.5 * 1) / 3))


def test_stacked_slabs_integrate_as_one_solid():
    slabs = [(0.0, 1.0, [(0, 0), (1, 0), (1, 1), (0, 1)]), (1.0, 2.0, [(0, 0), (2, 0), (2, 1), (0, 1)])]
    state = tanks.fill_state(tanks.slabs_triangles(slabs), 0.5)
    assert state.volume_m3 == pytest.approx(0.5 + 1.0)
    assert state.free_surface_m2 == pytest.approx(3.0)
    x_c = (0.5 * 1 + 1.5 * 2) / 3
    assert state.i_longitudinal_m4 == pytest.approx(1 / 12 + 1 * (0.5 - x_c) ** 2 + 2 / 12 + 2 * (1.5 - x_c) ** 2)


def test_tank_from_outline_clipped_to_hull():
    slicer = tanks.HullSlicer(box_triangles((0, -4, 0), (10, 4, 5)))
    slabs = tanks.tank_slabs_in_hull(slicer, (2.0, 4.0), lambda x: (0.0, 10.0), lambda x: (1.0, 3.0),
                                     slab_m=0.5, row_dz_m=0.1)
    assert len(slabs) == 4
    # The plan extent runs past the hull side at y = 4: the hull clips it.
    assert tanks.fill_state(tanks.slabs_triangles(slabs), 3.0).volume_m3 == pytest.approx(2 * 4 * 2)


def test_capacity_plan_rows_labels_and_totals():
    ballast = tanks.Tank("t1", "No 1", "water ballast", box_triangles(), ("2", "6"), density_t_m3=1.025,
                         source_labels={"geometry": "traced", "density": "read"}, printed_volume_m3=25.0)
    fuel = tanks.Tank("t2", "No 2", "fuel oil", box_triangles(), ("6", "8"),
                      source_labels={"geometry": "guessed"})
    missing = tanks.Tank("t3", "No 3", "fuel oil", None, ("8", "9"), notes=["not built"])
    rows = tanks.capacity_plan([ballast, fuel, missing])
    assert rows[0]["volume_100_m3"] == pytest.approx(24.0)
    assert rows[0]["volume_98_m3"] == pytest.approx(23.52)
    assert rows[0]["weight_98_t"] == pytest.approx(23.52 * 1.025)
    assert (rows[0]["lcg_m"], rows[0]["tcg_m"], rows[0]["vcg_m"]) == pytest.approx((2.0, 0.5, 2.5))
    assert rows[0]["max_free_surface_moment_tm"] == pytest.approx(1.025 * 4.5)
    assert rows[0]["source_labels"]["density"] == "read"
    assert rows[1]["density_t_m3"] == tanks.DEFAULT_DENSITY_T_M3["fuel oil"]
    assert rows[1]["source_labels"]["density"] == "guessed"
    assert rows[1]["source_labels"]["volume"] == "guessed"
    assert not rows[2]["built"] and rows[2]["volume_100_m3"] is None
    assert all(r["engineering_approved"] is False for r in rows)
    totals = tanks.group_totals(rows)
    assert totals["fuel oil"]["volume_100_m3"] == pytest.approx(24.0)
    assert (totals["fuel oil"]["tanks"], totals["fuel oil"]["built"]) == (2, 1)


def test_sounding_levels_end_at_top():
    assert tanks.sounding_levels(0.0, 0.25, 0.1) == pytest.approx([0.0, 0.1, 0.2, 0.25])
    assert tanks.sounding_levels(1.0, 1.2, 0.1) == pytest.approx([1.0, 1.1, 1.2])
    assert math.isclose(tanks.sounding_levels(0.0, 3.0, 0.1)[-1], 3.0)


def test_capacity_row_of_a_tank_with_an_empty_mesh_has_no_volume():
    tank = tanks.Tank("t4", "No 4", "fuel oil", np.zeros((0, 3, 3)), ("1", "2"))
    row = tanks.capacity_row(tank)
    assert row["volume_100_m3"] is None and row["weight_98_t"] is None
