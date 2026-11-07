"""Read strokes and words from a vector PDF page (PyMuPDF).

Each drawn path becomes one or more strokes: consecutive path items that
share an end point form one polyline. Bezier items are sampled into short
chords. Coordinates are converted from PDF points (y down) to drawing
millimetres (z up).
"""
from __future__ import annotations

from pathlib import Path

from .model import SheetInput, Stroke, Word

MM_PER_POINT = 25.4 / 72
# Bezier items are replaced by this many chords. At the drawing scales seen
# (10 to 21 mm per ship metre) a bilge arc of a few millimetres then deviates
# from the true curve by far less than the 0.1 mm touch tolerance.
BEZIER_CHORDS = 8
# Path end points closer than this are the same point (PDF rounding).
JOIN_TOLERANCE_MM = 0.02
# Two vector strokes touch when an end point is this close to the other stroke.
VECTOR_TOUCH_TOLERANCE_MM = 0.1


def vector_path_count(pdf_path: Path, page_number: int = 0) -> int:
    """Return the number of drawn paths; zero means the page is not vector."""
    import fitz
    with fitz.open(pdf_path) as document:
        return len(document[page_number].get_drawings())


def read_vector_sheet(pdf_path: Path, page_number: int = 0) -> SheetInput:
    import fitz
    with fitz.open(pdf_path) as document:
        page = document[page_number]
        height_pt = page.rect.height
        strokes: list[Stroke] = []
        for path_index, drawing in enumerate(page.get_drawings()):
            for part, points in enumerate(_path_polylines(drawing, height_pt)):
                strokes.append(Stroke(len(strokes), tuple(points), f"pdf_path:{path_index}.{part}"))
        return SheetInput(tuple(strokes), _page_words(page), page.rect.width * MM_PER_POINT,
                          height_pt * MM_PER_POINT, "vector", VECTOR_TOUCH_TOLERANCE_MM)


def read_pdf_words(pdf_path: Path, page_number: int = 0) -> tuple[Word, ...]:
    """Words of the PDF text layer in drawing millimetres (empty for a scan)."""
    import fitz
    with fitz.open(pdf_path) as document:
        return _page_words(document[page_number])


def _page_words(page) -> tuple[Word, ...]:
    height_pt = page.rect.height
    return tuple(
        Word(x0 * MM_PER_POINT, (height_pt - y1) * MM_PER_POINT,
             x1 * MM_PER_POINT, (height_pt - y0) * MM_PER_POINT, text)
        for x0, y0, x1, y1, text, *_ in page.get_text("words"))


def _to_mm(point, height_pt: float) -> tuple[float, float]:
    return point.x * MM_PER_POINT, (height_pt - point.y) * MM_PER_POINT


def _item_points(item, height_pt: float) -> list[tuple[float, float]]:
    kind = item[0]
    if kind == "l":
        return [_to_mm(item[1], height_pt), _to_mm(item[2], height_pt)]
    if kind == "c":
        p0, p1, p2, p3 = (_to_mm(p, height_pt) for p in item[1:5])
        samples = []
        for step in range(BEZIER_CHORDS + 1):
            t = step / BEZIER_CHORDS
            u = 1 - t
            samples.append((
                u**3 * p0[0] + 3 * u * u * t * p1[0] + 3 * u * t * t * p2[0] + t**3 * p3[0],
                u**3 * p0[1] + 3 * u * u * t * p1[1] + 3 * u * t * t * p2[1] + t**3 * p3[1]))
        return samples
    if kind == "re":
        rect = item[1]
        corners = [(rect.x0, rect.y0), (rect.x1, rect.y0), (rect.x1, rect.y1),
                   (rect.x0, rect.y1), (rect.x0, rect.y0)]
        return [(x * MM_PER_POINT, (height_pt - y) * MM_PER_POINT) for x, y in corners]
    if kind == "qu":
        quad = item[1]
        corners = [quad.ul, quad.ur, quad.lr, quad.ll, quad.ul]
        return [_to_mm(p, height_pt) for p in corners]
    return []


def _path_polylines(drawing: dict, height_pt: float) -> list[list[tuple[float, float]]]:
    polylines: list[list[tuple[float, float]]] = []
    for item in drawing["items"]:
        points = _item_points(item, height_pt)
        if len(points) < 2:
            continue
        current = polylines[-1] if polylines else None
        if current and _close(current[-1], points[0]):
            current.extend(points[1:])
        else:
            polylines.append(list(points))
    return [_drop_repeats(p) for p in polylines if len(_drop_repeats(p)) >= 2]


def _close(a, b) -> bool:
    return abs(a[0] - b[0]) <= JOIN_TOLERANCE_MM and abs(a[1] - b[1]) <= JOIN_TOLERANCE_MM


def _drop_repeats(points):
    kept = [points[0]]
    for point in points[1:]:
        if not _close(point, kept[-1]):
            kept.append(point)
    return kept
