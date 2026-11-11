"""Binary-image operations for raster drawings, with SciPy instead of OpenCV.

The worker runtime does not bundle OpenCV: the macOS OpenCV wheel vendors FFmpeg
with GPL video codecs (docs/DEPENDENCIES_AND_RIGHTS.md). These functions give the
same pixels, labels and statistics as the OpenCV calls that they replace
(tests/test_raster_morphology.py compares them when OpenCV is installed):

- ``opening`` and ``dilation``: ``cv2.morphologyEx(MORPH_OPEN)`` and ``cv2.dilate``
  with a rectangular kernel, default anchor (the kernel centre) and default border.
- ``connected_components_with_stats``: ``cv2.connectedComponentsWithStats`` with
  8-connectivity, including the order of the labels.
"""
from __future__ import annotations

import numpy as np
from scipy import ndimage

# OpenCV's 8-connected labelling scans the image in blocks of 2 x 2 pixels and
# numbers the components in the order of the first block that each one touches.
LABEL_BLOCK_PIXELS = 2


def _largest_value(image: np.ndarray):
    """A value at least as large as every pixel of the image's type."""
    if image.dtype == bool:
        return True
    if np.issubdtype(image.dtype, np.integer):
        return np.iinfo(image.dtype).max
    return np.inf


def erosion(image: np.ndarray, kernel_shape: tuple[int, int]) -> np.ndarray:
    """Minimum over a rows x columns rectangle centred like OpenCV's default anchor.

    Pixels outside the image do not erode (OpenCV's default border for erosion).
    SciPy's window for size n and origin 0 starts n // 2 before the pixel, which
    is OpenCV's anchor for an n-wide kernel, also when n is even.
    """
    return ndimage.minimum_filter(image, size=kernel_shape, mode='constant',
                                  cval=_largest_value(image))


def dilation(image: np.ndarray, kernel_shape: tuple[int, int]) -> np.ndarray:
    """Maximum over the same window as :func:`erosion`; outside pixels do not dilate."""
    return ndimage.maximum_filter(image, size=kernel_shape, mode='constant', cval=0)


def opening(image: np.ndarray, kernel_shape: tuple[int, int]) -> np.ndarray:
    """Erosion, then dilation, with the same rectangular kernel (``cv2.MORPH_OPEN``)."""
    return dilation(erosion(image, kernel_shape), kernel_shape)


def connected_components_with_stats(mask: np.ndarray) -> tuple[int, np.ndarray, np.ndarray]:
    """8-connected components of the non-zero pixels.

    Returns ``(count, labels, stats)`` like ``cv2.connectedComponentsWithStats``:
    ``count`` includes the background label 0, ``labels`` is an int32 image and
    ``stats[label]`` is ``(left, top, width, height, area)`` in pixels.
    """
    scan_labels, found = ndimage.label(mask != 0, structure=np.ones((3, 3), bool))
    stats = np.zeros((found + 1, 5), np.int32)
    stats[0] = _background_stats(mask == 0)
    if found == 0:
        return 1, scan_labels.astype(np.int32), stats

    # Renumber the components in the order of the first 2 x 2 block that each touches.
    rows, columns = np.nonzero(scan_labels)
    blocks_per_row = (mask.shape[1] + LABEL_BLOCK_PIXELS - 1) // LABEL_BLOCK_PIXELS
    block_order = ((rows // LABEL_BLOCK_PIXELS).astype(np.int64) * blocks_per_row
                   + columns // LABEL_BLOCK_PIXELS)
    scan_label_of_pixel = scan_labels[rows, columns]
    first_block = ndimage.minimum(block_order, scan_label_of_pixel, index=np.arange(1, found + 1))
    new_label = np.zeros(found + 1, np.int32)
    new_label[1 + np.argsort(first_block, kind='stable')] = np.arange(1, found + 1, dtype=np.int32)
    labels = new_label[scan_labels]

    areas = np.bincount(scan_label_of_pixel, minlength=found + 1)
    for scan_label, box in enumerate(ndimage.find_objects(scan_labels), start=1):
        row_slice, column_slice = box
        stats[new_label[scan_label]] = (column_slice.start, row_slice.start,
                                        column_slice.stop - column_slice.start,
                                        row_slice.stop - row_slice.start, areas[scan_label])
    return found + 1, labels, stats


def _background_stats(background: np.ndarray) -> tuple[int, int, int, int, int]:
    """OpenCV's row 0: the bounding box and count of the background pixels."""
    rows = np.flatnonzero(background.any(axis=1))
    columns = np.flatnonzero(background.any(axis=0))
    if rows.size == 0:
        return (-1, np.iinfo(np.int32).max, 0, 0, 0)  # OpenCV's values when there is no background
    return (int(columns[0]), int(rows[0]), int(columns[-1] - columns[0] + 1),
            int(rows[-1] - rows[0] + 1), int(np.count_nonzero(background)))
