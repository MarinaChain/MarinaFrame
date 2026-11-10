"""The vectorized ink-run helpers give exactly the old per-run results."""
import numpy as np
import pytest
from scipy import ndimage

from vessel_reconstruction.ingest import _dilate_5x5, _run_bounds, _run_weight_stats, _runs


def _reference_runs(row):
    """The previous element-by-element implementation of _runs."""
    indices = np.flatnonzero(row)
    if not len(indices):
        return []
    cuts = np.flatnonzero(np.diff(indices) > 1) + 1
    return [(int(group[0]), int(group[-1]) + 1) for group in np.split(indices, cuts)]


def _reference_weight_stats(ink_row, start, stop):
    """The previous per-run centre and mean weight in _trace and _candidate_evidence."""
    weights = np.maximum(1.0, ink_row[start:stop])
    return float(np.average(np.arange(start, stop), weights=weights)), float(np.mean(weights))


def _random_mask(rng, height, width):
    return rng.random((height, width)) < rng.uniform(0.02, 0.98)


@pytest.mark.parametrize("seed", range(5))
def test_runs_match_reference(seed):
    rng = np.random.default_rng(seed)
    for _ in range(200):
        row = _random_mask(rng, 1, int(rng.integers(0, 300)))[0]
        assert _runs(row) == _reference_runs(row)
    assert _runs(np.zeros(0, dtype=bool)) == []
    assert _runs(np.ones(4, dtype=bool)) == [(0, 4)]


@pytest.mark.parametrize("seed", range(5))
def test_run_bounds_and_weight_stats_match_reference(seed):
    rng = np.random.default_rng(100 + seed)
    for _ in range(20):
        height, width = int(rng.integers(1, 40)), int(rng.integers(1, 400))
        mask = _random_mask(rng, height, width)
        # Ink below 1 is clamped to weight 1; include such values.
        ink = rng.uniform(-20.0, 300.0, (height, width))
        run_rows, starts, stops = _run_bounds(mask)
        expected = [(row, a, b) for row in range(height) for a, b in _reference_runs(mask[row])]
        assert list(zip(run_rows.tolist(), starts.tolist(), stops.tolist())) == expected
        centres, mean_weights = _run_weight_stats(ink, run_rows, starts, stops)
        for index, (row, a, b) in enumerate(expected):
            # Exact equality: the vectorized sums keep the summation order.
            assert (float(centres[index]), float(mean_weights[index])) == _reference_weight_stats(ink[row], a, b)


def test_dilate_matches_binary_dilation():
    rng = np.random.default_rng(7)
    for shape in [(1, 1), (3, 7), (60, 45), (200, 130)]:
        mask = rng.random(shape) < 0.05
        expected = ndimage.binary_dilation(mask, structure=np.ones((5, 5), dtype=bool))
        assert np.array_equal(_dilate_5x5(mask), expected)
