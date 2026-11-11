"""Side-wall smoothness metric (benchmarks/gunnerus/whole_vessel_surface_metrics.py), synthetic."""
import pytest

cq = pytest.importorskip('cadquery')

from benchmarks.gunnerus.whole_vessel_surface_metrics import cut_smoothness


def _section(z_m: float, half_breadth_m: float):
    """A 10 m long rectangle in plan at height z (millimetres, as in the part STEP files)."""
    points = [(0, -half_breadth_m), (10, -half_breadth_m), (10, half_breadth_m), (0, half_breadth_m)]
    return cq.Wire.makePolygon([cq.Vector(x * 1000, y * 1000, z_m * 1000) for x, y in points], close=True)


def test_a_flat_wall_has_no_kink_and_one_face_on_the_cut():
    box = cq.Solid.makeBox(10_000, 8_000, 2_000, cq.Vector(0, -4_000, 0))
    cut = cut_smoothness(box, 5.0, 0.0, 2.0)
    assert cut['kinks'] == 0 and cut['faces'] == 1
    assert cut['max_turn_deg'] == pytest.approx(0.0, abs=1e-6)


def test_ruled_bands_show_a_kink_at_each_band_edge():
    wires = [_section(0.0, 4.0), _section(1.0, 4.4), _section(2.0, 4.5)]
    stacked = cq.Solid.makeLoft(wires, True)
    cut = cut_smoothness(stacked, 5.0, 0.0, 2.0)
    assert cut['kinks'] == 1 and cut['faces'] == 2
    # The flare changes from 0.4 to 0.1 m per metre: the normal turns by about 16 degrees.
    assert cut['max_turn_deg'] == pytest.approx(16.1, abs=0.5)


def test_a_smooth_loft_has_no_kink():
    wires = [_section(0.0, 4.0), _section(1.0, 4.4), _section(2.0, 4.5)]
    smooth = cq.Solid.makeLoft(wires, False)
    cut = cut_smoothness(smooth, 5.0, 0.0, 2.0)
    assert cut['kinks'] == 0 and cut['faces'] == 1
