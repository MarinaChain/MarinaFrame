"""Raster fallback: line strokes from the pixels of a rendered or scanned sheet.

Ink is split into horizontal runs, vertical runs and the remainder
(inclined lines and curves) with morphological opening. Each connected
component becomes one stroke. This loses detail that the vector path keeps:
collinear touching members merge, and lines shorter than the opening kernel
are lost. Words are not read from pixels (no OCR in v1); the caller supplies
them, for example from the PDF text layer, or the section reader abstains on
scale and scantlings.
"""
from __future__ import annotations

import numpy as np

from ..raster_morphology import connected_components_with_stats, dilation, opening
from .model import SheetInput, Stroke, Word

INK_THRESHOLD = 160  # grey level below which a pixel is ink (0 black, 255 white)
# Minimum straight run kept by the opening, in millimetres on the sheet. Runs
# shorter than this are inclined ink or lost.
MIN_RUN_MM = 0.6
# Strokes touch when an end lies within this distance (about two pixels at 200 dpi).
RASTER_TOUCH_TOLERANCE_MM = 0.35
MIN_COMPONENT_PIXELS = 3


def sheet_from_pixels(gray: np.ndarray, dpi: float, words: tuple[Word, ...] = ()) -> SheetInput:
    mm_per_px = 25.4 / dpi
    height_px, width_px = gray.shape
    ink = (gray < INK_THRESHOLD).astype(np.uint8)
    run = max(3, int(round(MIN_RUN_MM / mm_per_px)))
    horizontal = opening(ink, (1, run))
    vertical = opening(ink, (run, 1))
    straight = dilation(np.maximum(horizontal, vertical), (3, 3))
    rest = ink * (1 - straight)

    def to_mm(px: float, py: float) -> tuple[float, float]:
        return px * mm_per_px, (height_px - py) * mm_per_px

    strokes: list[Stroke] = []

    def add(points, source):
        strokes.append(Stroke(len(strokes), tuple(points), source))

    for name, mask, axis in (("h", horizontal, 0), ("v", vertical, 1)):
        count, _labels, stats = connected_components_with_stats(mask)
        for label in range(1, count):
            x, y, w, h, area = stats[label]
            if area < MIN_COMPONENT_PIXELS:
                continue
            if axis == 0:
                centre = y + (h - 1) / 2
                add([to_mm(x, centre), to_mm(x + w - 1, centre)], f"raster:{name}{label}")
            else:
                centre = x + (w - 1) / 2
                add([to_mm(centre, y + h - 1), to_mm(centre, y)], f"raster:{name}{label}")

    count, labels, stats = connected_components_with_stats(rest)
    for label in range(1, count):
        x, y, w, h, area = stats[label]
        if area < MIN_COMPONENT_PIXELS:
            continue
        ys, xs = np.nonzero(labels[y:y + h, x:x + w] == label)
        points = np.column_stack([xs + x, ys + y]).astype(float)
        add([to_mm(px, py) for px, py in _ordered_curve(points)], f"raster:r{label}")
    # Glyph ink inside a known word box is text, not structure.
    kept = [s for s in strokes if not any(_inside_word(s, w) for w in words)]
    strokes = [Stroke(i, s.points, s.source) for i, s in enumerate(kept)]
    return SheetInput(tuple(strokes), tuple(words), width_px * mm_per_px, height_px * mm_per_px,
                      "raster", RASTER_TOUCH_TOLERANCE_MM)


WORD_MARGIN_MM = 0.5


def _inside_word(stroke: Stroke, word: Word) -> bool:
    x0, z0, x1, z1 = stroke.bbox
    return (x0 >= word.x0 - WORD_MARGIN_MM and x1 <= word.x1 + WORD_MARGIN_MM
            and z0 >= word.z0 - WORD_MARGIN_MM and z1 <= word.z1 + WORD_MARGIN_MM)


def _ordered_curve(points: np.ndarray, samples: int = 12) -> list[tuple[float, float]]:
    """Order the pixels of a thin open curve along its chord and sample it.

    The chord joins the two pixels farthest apart along the main axis. The
    curve is taken to be monotone along that chord, which holds for straight
    inclined lines and for bilge arcs up to a quarter circle.
    """
    centred = points - points.mean(axis=0)
    _, _, axes = np.linalg.svd(centred, full_matrices=False)
    projection = centred @ axes[0]
    order = np.argsort(projection)
    ordered = points[order]
    t = projection[order]
    edges = np.linspace(t[0], t[-1], samples + 1)
    result = []
    for low, high in zip(edges, edges[1:]):
        mask = (t >= low) & (t <= high)
        if mask.any():
            result.append(tuple(ordered[mask].mean(axis=0)))
    first, last = tuple(ordered[0]), tuple(ordered[-1])
    if not result or result[0] != first:
        result.insert(0, first)
    if result[-1] != last:
        result.append(last)
    return result


def render_pdf_page(pdf_path, dpi: float, page_number: int = 0) -> np.ndarray:
    import fitz
    with fitz.open(pdf_path) as document:
        pixmap = document[page_number].get_pixmap(matrix=fitz.Matrix(dpi / 72, dpi / 72),
                                                  colorspace=fitz.csGRAY, alpha=False)
        return np.frombuffer(pixmap.samples, dtype=np.uint8).reshape(pixmap.height, pixmap.width).copy()
