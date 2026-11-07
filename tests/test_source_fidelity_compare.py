"""Independent accelerated STEP comparator retains the strict boundary policy."""
import numpy as np
import pytest
from benchmarks.source_fidelity_compare import intersect_ordinates
from benchmarks.audit_exported_step_v2 import ordinate_intersection


@pytest.mark.parametrize('segments', [
    [([0., 0.], [2., 2.]), ([-2., 2.], [0., 0.])],
    [([1., 0.], [1., 1.]), ([1., 1.+5e-10], [2., 2.])],
    [([1., 0.], [1., 1.]), ([2., 0.], [2., 2.])],
    [([1., 0.], [1., 1.]), ([1., 1.], [2., 1.]), ([2., 1.], [2., 2.])],
    [([1., 0.], [1., .99]), ([1., 1.01], [2., 2.])],
    [([1., 1.], [1., 1.])],
    [],
])
def test_vectorized_comparator_matches_existing_strict_intersections(segments):
    z = np.unique(np.r_[np.linspace(-.1, 2.1, 137), 1., 1.+4e-10])
    y, statuses, closures, assisted = intersect_ordinates(segments, z)
    for i, zz in enumerate(z):
        expected = ordinate_intersection(segments, zz)
        assert statuses[i] == expected['status']
        if expected['status'] == 'complete':
            assert y[i] == pytest.approx(expected['y_m'], abs=1e-9)
        else:
            assert np.isnan(y[i])
    assert closures == 0


def test_endpoint_horizontal_closure_reports_outer_edge_and_absences_remain():
    segments = [([0., .5], [1., .5]), ([1., .5], [2., 2.]), ([2., 2.], [0., 2.])]
    y, statuses, closures, assisted = intersect_ordinates(segments, np.array([0., .5, 1., 2.]))
    assert statuses == ['absent', 'ambiguous', 'complete', 'complete']
    assert np.isnan(y[0])
    assert y[-1] == 2.
    assert closures == 1
