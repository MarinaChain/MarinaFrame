"""Full source sections retain variable-height ends without extrapolation."""
import numpy as np
import pytest

from vessel_reconstruction.hull_variation import HullSections, section_properties, vary_sections


@pytest.mark.cad
def test_disconnected_region_candidate_is_closed():
    from vessel_reconstruction.hull_variation import build_candidate
    regions = [[{'kind': 'centreline', 'rows_m': [[0, 0, 1], [2, 0, 1]]},
                {'kind': 'centreline', 'rows_m': [[8, 0, 1], [10, 0, 1]]}]
               for _ in range(4)]
    hull = HullSections([0, 2, 8, 10], [0, 5, 10], np.ones((4, 3)),
                        10, 2, 5, (2, 8), regions=regions)
    candidate = build_candidate(hull)
    assert candidate.solid.isValid()
    assert candidate.report['hydrostatics']['volume_m3'] == pytest.approx(40.)
    assert candidate.report['engineering_approved'] is False


def test_triangle_section_preserves_two_intersections():
    from vessel_reconstruction.full_hull_source import triangle_section
    triangles = np.array([[[-1, 0, 0], [1, 2, 0], [1, 0, 2]]], dtype=float)
    cut = triangle_section(triangles, 0)
    assert cut.shape == (1, 2, 2)
    np.testing.assert_allclose(cut[0], [[1, 0], [0, 1]])


def test_section_segments_keep_disconnected_source_ranges():
    from vessel_reconstruction.full_hull_source import section_regions_from_segments
    segments = np.array([[[0, 0], [1, 2]], [[1, 2], [0, 4]],
                         [[0, 8], [1, 10]], [[1, 10], [0, 12]]], dtype=float)
    regions = section_regions_from_segments(segments)
    assert len(regions) == 2
    assert np.asarray(regions[0]['rows_m'])[:, 0][[0, -1]].tolist() == [0, 4]
    assert np.asarray(regions[1]['rows_m'])[:, 0][[0, -1]].tolist() == [8, 12]


def test_section_segments_reject_ambiguous_positive_skin():
    from vessel_reconstruction.full_hull_source import section_regions_from_segments
    with pytest.raises(ValueError, match='multiple'):
        section_regions_from_segments(np.array([[[1, 0], [1, 4]], [[2, 0], [2, 4]]]))


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


def test_disconnected_regions_do_not_fill_stern_gap():
    regions = [[{'kind': 'centreline', 'rows_m': [[0, 0, 1], [2, 0, 1]]},
                {'kind': 'centreline', 'rows_m': [[8, 0, 1], [10, 0, 1]]}]
               for _ in range(4)]
    hull = HullSections([0, 2, 8, 10], [0, 5, 10], np.ones((4, 3)),
                        10, 2, 5, (2, 8), regions=regions)
    assert section_properties(hull) == pytest.approx((.4, 5.))
    varied = vary_sections(hull, length_m=20, breadth_m=4, draft_m=10,
                           cb=.4, lcb_fraction=.5)
    assert section_properties(varied) == pytest.approx((.4, 10.))
    np.testing.assert_allclose(varied.regions[0][1]['rows_m'], [[16, 0, 2], [20, 0, 2]])


@pytest.mark.parametrize('heights', [np.zeros((4, 3)), np.zeros((3, 3)),
                                     np.array([[0, 5, float('nan')]] * 4)])
def test_invalid_variable_heights_are_rejected(heights):
    with pytest.raises(ValueError, match='section'):
        HullSections([0, 2, 8, 10], [0, 5, 10], np.ones((4, 3)),
                     10, 2, 5, (2, 8), section_z_m=heights)
