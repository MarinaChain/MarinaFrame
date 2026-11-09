"""raster_morphology gives OpenCV's pixels, labels and statistics without OpenCV."""
import numpy as np
import pytest

from vessel_reconstruction import raster_morphology as rm

KERNELS = [(1, 3), (3, 1), (1, 4), (4, 1), (1, 7), (6, 1), (3, 3), (2, 5)]


def random_ink(seed: int, shape: tuple[int, int], density: float) -> np.ndarray:
    return (np.random.default_rng(seed).random(shape) < density).astype(np.uint8)


def test_opening_keeps_long_runs_only():
    ink = np.zeros((5, 12), np.uint8)
    ink[1, 0:6] = 1   # 6 long: kept by a 1 x 5 opening, also at the image edge
    ink[3, 8:11] = 1  # 3 long: removed
    opened = rm.opening(ink, (1, 5))
    assert opened.dtype == np.uint8
    assert np.array_equal(np.nonzero(opened)[1], np.arange(0, 6))


def test_components_are_numbered_by_first_two_by_two_block():
    # Component b starts on row 1, column 1, inside the first 2 x 2 block; a starts later
    # in that block row. OpenCV numbers b first although a's first pixel comes first in
    # row order.
    mask = np.zeros((4, 8), np.uint8)
    mask[0, 4] = 1
    mask[1, 1] = 1
    count, labels, stats = rm.connected_components_with_stats(mask)
    assert count == 3
    assert labels[1, 1] == 1 and labels[0, 4] == 2
    assert stats[1].tolist() == [1, 1, 1, 1, 1]
    assert stats[0].tolist() == [0, 0, 8, 4, 30]


def test_empty_and_full_masks():
    count, labels, stats = rm.connected_components_with_stats(np.zeros((3, 4), np.uint8))
    assert count == 1 and not labels.any() and stats.tolist() == [[0, 0, 4, 3, 12]]
    count, _labels, stats = rm.connected_components_with_stats(np.ones((3, 4), np.uint8))
    assert count == 2 and stats[1].tolist() == [0, 0, 4, 3, 12]


@pytest.mark.parametrize('seed', range(30))
def test_matches_opencv(seed):
    cv2 = pytest.importorskip('cv2', reason='the comparison needs the plan-raster extra (OpenCV)')
    rng = np.random.default_rng(seed)
    shape = (900, 1300) if seed == 0 else tuple(int(n) for n in rng.integers(1, 80, size=2))
    ink = random_ink(seed, shape, float(rng.choice([0.02, 0.1, 0.3, 0.5, 0.7])))
    for kernel_shape in KERNELS:
        kernel = np.ones(kernel_shape, np.uint8)
        assert np.array_equal(rm.opening(ink, kernel_shape),
                              cv2.morphologyEx(ink, cv2.MORPH_OPEN, kernel)), kernel_shape
        assert np.array_equal(rm.dilation(ink, kernel_shape), cv2.dilate(ink, kernel)), kernel_shape
    expected_count, expected_labels, expected_stats, _ = cv2.connectedComponentsWithStats(ink, connectivity=8)
    count, labels, stats = rm.connected_components_with_stats(ink)
    assert count == expected_count
    assert np.array_equal(labels, expected_labels)
    assert np.array_equal(stats, expected_stats)
