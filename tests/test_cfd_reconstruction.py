"""Synthetic tests for CFD section reconstruction, in metres."""
import importlib

import numpy as np
import pytest

cq = pytest.importorskip('cadquery')


@pytest.fixture
def reconstruction():
    return importlib.import_module('vessel_reconstruction.cfd.reconstruction')


def test_station_spacing_is_dense_at_both_ends(reconstruction):
    x = reconstruction.station_positions(0, 10)
    assert len(x) == 321
    assert x[0] == 0 and x[-1] == 10
    assert np.all(np.diff(x) > 0)
    assert x[1] - x[0] < x[161] - x[160]
    assert x[-1] - x[-2] < x[161] - x[160]


def test_occt_section_of_half_box_keeps_flat_bottom(reconstruction):
    source = cq.Solid.makeBox(4, 1, 2)
    profile, evidence = reconstruction.slice_half_breadths(source, 2, 2, levels=9)
    assert profile.shape == (9, 2)
    assert profile[:, 0] == pytest.approx(np.ones(9))
    assert profile[:, 1] == pytest.approx(np.linspace(0, 2, 9))
    assert evidence['section_edges'] == 4


def test_disconnected_zero_width_section_does_not_bridge_bulb_to_stem(reconstruction):
    lower = cq.Solid.makeCone(0.5, 0, 1, cq.Vector(2, 0, 0))
    upper = cq.Solid.makeCone(0, 0.7, 1, cq.Vector(2, 0, 2))
    source = cq.Compound.makeCompound([lower, upper])
    profile, evidence = reconstruction.slice_half_breadths(source, 2, 3, levels=13)
    empty = (profile[:, 1] > 1) & (profile[:, 1] < 2)
    assert np.all(profile[empty, 0] == 0)
    assert evidence['centreline_gap_heights_m']


def test_mirrored_loft_has_exact_box_volume_and_wetted_area(reconstruction):
    profiles = [np.array([[1., 0.], [1., 1.], [1., 2.]])] * 3
    solid = reconstruction.loft_sections([0., 2., 4.], profiles)
    assert solid.isValid()
    assert solid.Volume() == pytest.approx(16.)
    measures = reconstruction.submerged_particulars(solid, 1.)
    assert measures['volume_m3'] == pytest.approx(8.)
    assert measures['wetted_area_m2'] == pytest.approx(20.)


def test_deck_roundoff_is_recorded_not_extrapolated_silently(reconstruction):
    source = cq.Solid.makeBox(4, 1, 2 - 2e-7)
    profile, evidence = reconstruction.slice_half_breadths(source, 2, 2)
    assert profile[-1] == pytest.approx([1, 2])
    assert evidence['deck_extension_m'] == pytest.approx(2e-7)


def test_section_trim_gap_at_deck_is_bounded_and_recorded(reconstruction):
    lower = cq.Solid.makeBox(4, 1, 1.999995)
    upper = cq.Solid.makeBox(4, 1, 1, cq.Vector(0, 0, 2.00000003))
    source = cq.Compound.makeCompound([lower, upper])
    profile, evidence = reconstruction.slice_half_breadths(source, 2, 2)
    assert profile[-1] == pytest.approx([1, 2])
    assert evidence['intersection_height_tolerance_m'] == 1e-6


def test_tessellation_is_closed_outward_box(reconstruction):
    from vessel_reconstruction.cfd.surface import validate_surface
    solid = cq.Solid.makeBox(4, 2, 2)
    triangles = reconstruction.triangulate(solid)
    assert len(validate_surface(triangles)) == 12


def test_sampled_source_distance_for_shifted_box(reconstruction):
    source = cq.Solid.makeBox(1, 1, 1)
    points = [(1.1, 0.5, 0.5), (0.5, 0.5, 1.2)]
    assert reconstruction.sample_distances(source, points) == pytest.approx([0.1, 0.2])


def test_slice_outside_source_fails(reconstruction):
    with pytest.raises(ValueError, match='section'):
        reconstruction.slice_half_breadths(cq.Solid.makeBox(4, 1, 2), 5, 2)


def test_loft_rejects_nonincreasing_stations(reconstruction):
    profile = np.array([[1., 0.], [1., 2.]])
    with pytest.raises(ValueError, match='increasing'):
        reconstruction.loft_sections([0., 0., 1.], [profile] * 3)
