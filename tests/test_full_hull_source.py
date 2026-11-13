"""Full source sections retain variable-height ends without extrapolation."""
import numpy as np
import pytest

from vessel_reconstruction.hull_variation import HullSections, section_properties, vary_sections


def variable_hull():
    # Ends have a raised keel: a common 0..10 grid would invent bottom volume.
    return HullSections(np.array([0., 2., 8., 10.]), np.array([0., 5., 10.]),
                        np.ones((4, 3)), 10., 2., 5., (2., 8.),
                        section_z_m=np.array([[2., 6., 10.], [0., 5., 10.],
                                              [0., 5., 10.], [2., 6., 10.]]))


def test_variable_height_integrals_do_not_fill_below_keel():
    hull = variable_hull()
    cb, lcb = section_properties(hull)
    assert cb == pytest.approx(.92)
    assert lcb == pytest.approx(5.)


def test_variable_height_scaling_preserves_source_domain():
    hull = variable_hull()
    cb, lcb = section_properties(hull)
    varied = vary_sections(hull, length_m=20, breadth_m=4, draft_m=10,
                           cb=cb, lcb_fraction=lcb / hull.length_m)
    np.testing.assert_allclose(varied.section_z_m, hull.section_z_m * 2)
    assert section_properties(varied) == pytest.approx((cb, 10.))


@pytest.mark.parametrize('heights', [np.zeros((4, 3)), np.zeros((3, 3)),
                                     np.array([[0, 5, float('nan')]] * 4)])
def test_invalid_variable_heights_are_rejected(heights):
    with pytest.raises(ValueError, match='section'):
        HullSections([0, 2, 8, 10], [0, 5, 10], np.ones((4, 3)),
                     10, 2, 5, (2, 8), section_z_m=heights)
