"""Synthetic tests for parts above the hull (superstructure.py); no drawing data."""
import numpy as np
import pytest

from vessel_reconstruction.superstructure import MAX_EXTRAPOLATION_M, HullSide


def flared_section(x, top_z=5.0, half_breadth_at_deck=4.0, flare=0.2):
    """A wall-sided section to z 3 m, then flaring out by ``flare`` m per metre up to ``top_z``."""
    rows = [[z, 0.0, half_breadth_at_deck + max(z - 3.0, 0.0) * flare] for z in np.arange(0.0, top_z + 1e-9, 0.25)]
    return {'x_m': x, 'regions': [{'kind': 'main', 'rows_m': rows}]}


def bow_hull():
    """Parallel body from x 0 to 10 m, then a bow that narrows to 1 m at x 14 m."""
    sections = [flared_section(x) for x in (0.0, 5.0, 10.0)]
    sections += [flared_section(12.0, half_breadth_at_deck=2.5), flared_section(14.0, half_breadth_at_deck=1.0)]
    return HullSide.from_sections(sections)


def test_hull_side_interpolates_and_continues_the_flare_above_the_top():
    hull = bow_hull()
    assert hull.half_breadth(5.0, 4.0) == pytest.approx(4.2)
    assert hull.half_breadth(11.0, 2.0) == pytest.approx(3.25)
    # Above the drawn top (5 m) the flare continues for at most MAX_EXTRAPOLATION_M.
    assert hull.half_breadth(5.0, 5.5) == pytest.approx(4.5)
    assert hull.half_breadth(5.0, 20.0) == pytest.approx(4.4 + 0.2 * MAX_EXTRAPOLATION_M)
    assert hull.half_breadth(-1.0, 4.0) == 0.0 and hull.half_breadth(15.0, 4.0) == 0.0


def test_hull_side_round_trips_through_json_values():
    hull = bow_hull()
    again = HullSide.from_dict(hull.to_dict())
    assert again.half_breadth(12.5, 3.3) == pytest.approx(hull.half_breadth(12.5, 3.3), abs=1e-4)


def test_outside_distance_is_lateral_or_longitudinal_whichever_is_smaller():
    hull = bow_hull()
    distance = hull.outside_distance([5.0, 5.0, 14.5, 13.0], [3.0, 4.5, 0.0, 3.9], [3.0, 3.0, 3.0, 3.0])
    assert distance[0] == 0.0
    assert distance[1] == pytest.approx(0.5)
    assert distance[2] == pytest.approx(0.5, abs=0.03)  # beyond the bow end: longitudinal
    # x 13 m: half-breadth 1.75 m, so 2.15 m lateral; the side is 3.9 m wide only aft of x 10.13 m.
    assert distance[3] == pytest.approx(2.15, abs=0.01)
