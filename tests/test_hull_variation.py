"""Synthetic, public-data-free checks for draft hull variation."""
import numpy as np
import pytest

from vessel_reconstruction.hull_variation import HullSections, vary_sections, section_properties


def reference():
    x = np.linspace(0, 100, 41)
    fullness = np.minimum(1, np.minimum(x / 30, (100 - x) / 30))
    fullness = 0.02 + 0.98 * np.sin(fullness * np.pi / 2)
    z = np.linspace(0, 12, 13)
    widths = 10 * fullness[:, None] * np.sqrt(np.minimum(z / 3, 1))[None, :]
    return HullSections(x, z, widths, 100, 20, 10, (30, 70))


def test_identity_and_scaling_preserve_reference():
    hull = reference()
    cb, lcb = section_properties(hull)
    identity = vary_sections(hull, length_m=100, breadth_m=20, draft_m=10, cb=cb, lcb_fraction=lcb / 100)
    np.testing.assert_allclose(identity.x_m, hull.x_m, atol=1e-10)
    np.testing.assert_array_equal(identity.half_breadths_m, hull.half_breadths_m)
    scaled = vary_sections(hull, length_m=120, breadth_m=24, draft_m=12, cb=cb, lcb_fraction=lcb / 100)
    np.testing.assert_allclose(scaled.x_m, hull.x_m * 1.2, atol=1e-10)
    np.testing.assert_allclose(scaled.half_breadths_m, hull.half_breadths_m * 1.2)
    np.testing.assert_allclose(scaled.z_m, hull.z_m * 1.2)


@pytest.mark.parametrize('delta_cb,delta_lcb', [(0.015, 0.003), (-0.02, -0.004)])
def test_targets_and_parallel_middle_body(delta_cb, delta_lcb):
    hull = reference()
    cb, lcb = section_properties(hull)
    candidate = vary_sections(hull, length_m=100, breadth_m=20, draft_m=10,
                              cb=cb + delta_cb, lcb_fraction=lcb / 100 + delta_lcb)
    actual_cb, actual_lcb = section_properties(candidate)
    assert abs(actual_cb - cb - delta_cb) <= 0.001
    assert abs(actual_lcb / 100 - lcb / 100 - delta_lcb) <= 0.001
    middle = (hull.x_m >= 30) & (hull.x_m <= 70)
    np.testing.assert_array_equal(candidate.x_m[middle], hull.x_m[middle])
    assert np.all(np.diff(candidate.x_m) > 0)


@pytest.mark.cad
def test_candidate_solid_hydrostatics_and_capacity():
    from vessel_reconstruction.hull_variation import build_candidate, gross_capacity
    hull = reference()
    cb, lcb = section_properties(hull)
    result = build_candidate(hull)
    assert result.solid.isValid()
    assert len(result.solid.Solids()) == 1
    assert result.report['engineering_approved'] is False
    assert result.report['status'] == 'draft'
    assert abs(result.report['design_cb'] - cb) <= 0.001
    assert abs(result.report['hydrostatics']['lcb_m'] - lcb) <= 0.1
    assert result.report['mesh_volume_relative_error'] <= 0.001
    identity = vary_sections(hull, length_m=100, breadth_m=20, draft_m=10,
                             cb=cb, lcb_fraction=lcb / 100)
    assert abs(build_candidate(identity).solid.Volume() / result.solid.Volume() - 1) < 1e-8
    changed = vary_sections(hull, length_m=110, breadth_m=22, draft_m=11,
                            cb=cb + 0.01, lcb_fraction=lcb / 100 + 0.003)
    built = build_candidate(changed)
    assert built.solid.isValid()
    assert abs(built.report['design_cb'] - cb - 0.01) <= 0.001
    assert abs(built.report['hydrostatics']['lcb_m'] / 110 - lcb / 100 - 0.003) <= 0.001
    box = HullSections(np.array([0, 25, 75, 100]), np.array([0, 12]),
                       np.full((4, 2), 10), 100, 20, 10, (25, 75))
    assert gross_capacity(box, 25, 75) == pytest.approx(10000)
    assert gross_capacity(box, 0, 100) == pytest.approx(20000)
    for limits in [(-1, 50), (60, 50), (0, 101)]:
        with pytest.raises(ValueError):
            gross_capacity(box, *limits)


def test_parallel_body_requires_boundary_stations():
    hull = reference()
    hull.parallel_body_m = (31, 69)
    cb, lcb = section_properties(hull)
    with pytest.raises(ValueError, match='boundary stations'):
        vary_sections(hull, length_m=100, breadth_m=20, draft_m=10, cb=cb + .01,
                      lcb_fraction=lcb / 100)


def test_declared_breadth_matches_geometry():
    hull = reference()
    with pytest.raises(ValueError, match='breadth'):
        HullSections(hull.x_m, hull.z_m, hull.half_breadths_m * 1.2,
                     100, 20, 10, (30, 70))


@pytest.mark.cad
def test_two_height_box_builds():
    from vessel_reconstruction.hull_variation import build_candidate
    box = HullSections(np.array([0, 25, 75, 100]), np.array([0, 12]),
                       np.full((4, 2), 10), 100, 20, 10, (25, 75))
    assert build_candidate(box).solid.Volume() / 1e9 == pytest.approx(24000)


@pytest.mark.parametrize('changes', [{'length_m': -1}, {'cb': float('nan')}, {'cb': 0.99},
                                    {'lcb_fraction': 0.99}, {'draft_m': 0}])
def test_invalid_or_unreachable_targets(changes):
    hull = reference()
    cb, lcb = section_properties(hull)
    args = dict(length_m=100, breadth_m=20, draft_m=10, cb=cb, lcb_fraction=lcb / 100)
    args.update(changes)
    with pytest.raises(ValueError):
        vary_sections(hull, **args)
