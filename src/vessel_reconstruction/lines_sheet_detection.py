"""Experimental, code-only lines-sheet region proposals; not a product reader.

Removing long frame strokes before grouping prevents one border from joining
all views. The resulting boxes are candidates, not established view identities.
A drawing ratio alone is not a pixel scale: scan DPI is also required.
"""
from __future__ import annotations

import math

import numpy as np
from scipy import ndimage

from . import intake
from .sheet_scale import read_scale
from .sheet_types import ocr_read

# Work at bounded resolution. These are proposal settings, not accuracy gates.
WORK_SIDE = 1200
# Frame strokes span a substantial share of a sheet, unlike station curves.
FRAME_SPAN = 0.35
FRAME_MARGIN_PX = 2
GROUP_GAP_PX = 9
MIN_BOX_SHARE = 0.01


def candidate_regions(gray):
    """Separate ink groups after frame suppression, in original page pixels."""
    step = max(1, int(np.ceil(max(gray.shape) / WORK_SIDE)))
    reduced = gray[::step, ::step]
    level, _ = intake.ink_levels(reduced)
    ink = reduced < level
    height, width = ink.shape
    horizontal = ndimage.binary_opening(ink, structure=np.ones((1, max(3, round(width * FRAME_SPAN)))))
    vertical = ndimage.binary_opening(ink, structure=np.ones((max(3, round(height * FRAME_SPAN)), 1)))
    frames = ndimage.binary_dilation(horizontal | vertical, iterations=FRAME_MARGIN_PX)
    ink &= ~frames
    grouped = ndimage.binary_closing(ink, structure=np.ones((GROUP_GAP_PX, GROUP_GAP_PX)))
    labels, _ = ndimage.label(grouped)
    regions = []
    for slices in ndimage.find_objects(labels):
        if slices is None:
            continue
        rows, cols = slices
        box_width, box_height = cols.stop - cols.start, rows.stop - rows.start
        if box_width * box_height < height * width * MIN_BOX_SHARE:
            continue
        box = [cols.start * step, rows.start * step,
               min(gray.shape[1], cols.stop * step), min(gray.shape[0], rows.stop * step)]
        regions.append({"region_px": box, "label": "other", "confidence": 0.3,
                        "evidence": "frame-suppressed ink group; view identity unresolved"})
    return regions


def drawing_scale(text, dpi):
    """Printed ratio with a pixel scale only for one ratio and isotropic DPI."""
    result = read_scale(text, "local_ocr")
    result["pixels_per_metre"] = None
    result["pixel_scale_status"] = "missing_ratio_or_scan_dpi"
    if result["status"] != "read" or not dpi or len(dpi) != 2:
        return result
    x_dpi, y_dpi = map(float, dpi)
    if not all(math.isfinite(value) and value > 1 for value in (x_dpi, y_dpi)) or x_dpi != y_dpi:
        result["pixel_scale_status"] = "invalid_or_anisotropic_scan_dpi"
        return result
    result["pixels_per_metre"] = x_dpi / .0254 / result["main_ratio"]
    result["pixel_scale_status"] = "printed_ratio_and_file_dpi_proposal"
    return result


def detect_sheet(image, *, dpi=None, words=None):
    """Return opt-in proposals without truth, a model or caller calibration.

    ``words`` permits deterministic OCR fixtures. When omitted, use local OCR
    on a bounded copy. Metadata-derived scale remains a proposal: scans can
    have been resized without updating their DPI tag.
    """
    gray = intake._gray(image).astype(np.uint8) if image.ndim == 3 else image
    if words is None:
        # OCR needs more detail than component grouping, but not a 240 MP TIFF.
        step = max(1, int(np.ceil(max(gray.shape) / 4000)))
        words = []
        ocr_read(gray[::step, ::step], side=4000, words_out=words)
    text = " ".join(word["text"] for word in words)
    return {"method": "experimental_frame_suppression_v1", "regions": candidate_regions(gray),
            "scale": drawing_scale(text, dpi), "engineering_approved": False}
