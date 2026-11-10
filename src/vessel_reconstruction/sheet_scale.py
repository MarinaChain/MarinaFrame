"""Scale of a sheet, and whether the sheets of one set agree on the size of the vessel.

Per sheet, ``read_scale(text)`` finds the printed scale (``1:100``, ``SCALE 1/50``, ``1/16" = 1'-0"``,
``1" = 20'``) in the text of the sheet (PDF text layer or OCR). Several different scales on one sheet
is normal on detail sheets: the most frequent one is the main scale and the status is ``mixed``.
Imperial scales reuse ``sheet_calibration.parse_scale_ratio``.

Across the set, a sheet that shows the whole hull gives a length estimate: drawn length of the long
view (millimetres of paper) times the main scale. ``scale_agreement`` compares those estimates. A
sheet far from the others is a check item with both numbers, never a failure: the estimate comes
from the extent of the drawn view and is only as good as the view box (it can include dimension
lines and a bow overhang). A printed length overall in the text, when found, is a second reference.
Labels are code proposals; nothing here says a scale is "verified".
"""
from __future__ import annotations

import re
import statistics
from collections import Counter

import numpy as np

from .sheet_calibration import parse_scale_ratio

# Denominators that are real drawing scales; "1:37" or a time "10:30" is not a scale.
STANDARD_DENOMINATORS = {1, 2, 5, 10, 20, 25, 30, 40, 50, 60, 75, 80, 100, 120, 125, 150, 200, 250, 300, 400, 500,
                         600, 1000}
# A sheet's length estimate may differ from the median by this share before it becomes a check item. The
# estimate is the width of the drawn view, which also holds dimension lines and overhangs (about 13 %
# too long on the one development sheet with a printed length), so it is not tighter than this.
# Provisional: set after seeing that one sheet; re-measure on a set with two read scales (docs/DRAWING_SET_INTAKE.md 7.2).
AGREEMENT_TOLERANCE = 0.15
# A printed length and the estimate agree within this share.
PRINTED_TOLERANCE = 0.08
# Types whose sheets show the whole hull length in one view.
WHOLE_HULL_TYPES = ("lines_plan", "profile", "general_arrangement", "tank_plan", "construction_profile")
# A long view is at least this many times wider than tall.
LONG_VIEW_ASPECT = 2.0
# Millimetres per inch.
MM_PER_INCH = 25.4
# Metres per foot, for printed lengths in feet.
M_PER_FT = 0.3048
# Printed scales sit under the views or in the title block: the bottom and right strips of the page
# are read again at higher resolution when the whole page gave no scale.
BOTTOM_STRIP_FRACTION = 0.18
RIGHT_STRIP_FRACTION = 0.2
STRIP_OCR_SIDE = 6000
# Page images smaller than this many pixels across are too small to measure a view.
MIN_PAGE_PX = 400

_RATIO = re.compile(r"(?<![\d.:/])1\s*:\s*(\d{1,4})(?![\d:])")
_FRACTION_RATIO = re.compile(r"scale\s*[:=]?\s*1\s*/\s*(\d{1,4})(?![\d/\"'])", re.IGNORECASE)
_IMPERIAL = re.compile(r"(\d+\s+\d+\s*/\s*\d+|\d+\s*/\s*\d+|\d+)\s*[\"”″']{1,2}\s*=\s*(\d+)\s*['’′]"
                       r"(?:\s*-?\s*\d*\s*[\"”″]{0,2})?")
_LENGTH_WORDS = (r"(?:l\.?\s?o\.?\s?a\.?|length\s+over\s*all|l\.?\s?b\.?\s?p\.?|l\.?\s?p\.?\s?p\.?|"
                 r"length\s+betw(?:een|\.|v\.)?\s+perp(?:endiculars|\.)?|length\s+o\.?a\.?)")
_PRINTED_METRES = re.compile(_LENGTH_WORDS + r"\s*[:=.]*\s*(\d{1,3}(?:[.,]\d{1,3})?)\s*\[?\s*m\b\]?", re.IGNORECASE)
_PRINTED_FEET = re.compile(_LENGTH_WORDS + r"\s*[:=.]*\s*(\d{2,3})\s*['’]\s*-?\s*(\d{1,2})?", re.IGNORECASE)


def parse_scales(text: str) -> list[dict]:
    """Every printed scale in ``text`` as ``{ratio, text}``; ratio is the real size over the drawn size."""
    found = []
    for match in _RATIO.finditer(text or ""):
        denominator = int(match.group(1))
        if denominator in STANDARD_DENOMINATORS:
            found.append({"ratio": float(denominator), "text": match.group(0).replace(" ", "")})
    for match in _FRACTION_RATIO.finditer(text or ""):
        denominator = int(match.group(1))
        if denominator in STANDARD_DENOMINATORS:
            found.append({"ratio": float(denominator), "text": match.group(0).strip()})
    for match in _IMPERIAL.finditer(text or ""):
        # 1/16" = 1'-0" is 192 times smaller than life; 1" = 20' is 240 times.
        text_match = match.group(0)
        mixed = " " in match.group(1).strip()
        # The shared parser reads N" = M' but not a mixed number such as 1 1/2".
        inches_per_foot = None if mixed else parse_scale_ratio(text_match)
        if inches_per_foot is None:
            try:
                inches_per_foot = sum(_fraction(part) for part in match.group(1).split()) / int(match.group(2))
            except (ValueError, ZeroDivisionError):
                continue
        if inches_per_foot and inches_per_foot > 0:
            found.append({"ratio": round(12.0 / inches_per_foot, 1), "text": " ".join(text_match.split())})
    return found


def _fraction(part: str) -> float:
    if "/" in part:
        top, bottom = part.replace(" ", "").split("/")
        return int(top) / int(bottom)
    return float(part)


def read_scale(text: str, text_where: str = "ocr") -> dict:
    """``{status, main_ratio, scales, source}``; status is ``read``, ``mixed`` or ``missing``."""
    scales = parse_scales(text)
    if not scales:
        return {"status": "missing", "main_ratio": None, "scales": [], "source": "none"}
    counts = Counter(round(s["ratio"]) for s in scales)
    first_seen = {}
    for index, scale in enumerate(scales):
        first_seen.setdefault(round(scale["ratio"]), index)
    main = sorted(counts, key=lambda ratio: (-counts[ratio], first_seen[ratio]))[0]
    printed = next(s["text"] for s in scales if round(s["ratio"]) == main)
    return {"status": "mixed" if len(counts) > 1 else "read", "main_ratio": float(main),
            "main_text": printed, "scales": [{"ratio": r, "count": c} for r, c in counts.most_common()],
            "source": f"text:{text_where}"}


def strip_text(gray: np.ndarray, ocr=None, words_out: list[dict] | None = None) -> str:
    """OCR text of the bottom and right strips of the page (where scales are printed), at high resolution.

    ``gray`` is the page at full resolution. ``ocr`` takes a grey array and returns text or (text, title);
    by default it is the ``tesseract`` reader at ``STRIP_OCR_SIDE`` pixels.
    """
    from functools import partial
    from .sheet_types import ocr_read
    height, width = gray.shape[:2]
    strips = (gray[int(height * (1 - BOTTOM_STRIP_FRACTION)):, :], gray[:, int(width * (1 - RIGHT_STRIP_FRACTION)):])
    texts = []
    origins = ((0, int(height * (1 - BOTTOM_STRIP_FRACTION))),
               (int(width * (1 - RIGHT_STRIP_FRACTION)), 0))
    for index, (strip, (left, top)) in enumerate(zip(strips, origins)):
        words = []
        read = ocr or partial(ocr_read, side=STRIP_OCR_SIDE, words_out=words)
        answer = read(np.ascontiguousarray(strip))
        texts.append(answer if isinstance(answer, str) else answer[0])
        if words_out is not None:
            for word in words:
                x0, y0, x1, y1 = word["bbox"]
                words_out.append({**word, "line": [index, *word["line"]],
                                  "bbox": [x0 + left, y0 + top, x1 + left, y1 + top]})
    return "\n".join(texts)


# ------------------------------------------------------------------ drawn hull length
def paper_size_mm(info: dict) -> tuple[float, float] | None:
    """Sheet size in millimetres from PDF points, else from full pixels and dpi."""
    if info.get("pdf_points"):
        width, height = info["pdf_points"]
        return width / 72 * MM_PER_INCH, height / 72 * MM_PER_INCH
    dpi, full = info.get("dpi"), info.get("full_px")
    if dpi and full:
        return full[0] / dpi * MM_PER_INCH, full[1] / dpi * MM_PER_INCH
    return None


def long_view_width_fraction(boxes: list[list[int]], page_width: int) -> float | None:
    """Width, as a share of the page, of the widest long view among the ink-group boxes."""
    widths = [(box[2] - box[0]) for box in boxes
              if (box[2] - box[0]) >= LONG_VIEW_ASPECT * max(1, box[3] - box[1])]
    return max(widths) / page_width if widths and page_width >= MIN_PAGE_PX else None


def length_estimate_m(width_fraction: float | None, info: dict, ratio: float | None) -> float | None:
    """Hull length in metres: drawn view width on paper times the printed scale."""
    paper = paper_size_mm(info)
    if width_fraction is None or paper is None or not ratio:
        return None
    return round(width_fraction * paper[0] * ratio / 1000.0, 2)


def printed_length_m(text: str) -> float | None:
    """A length overall or between perpendiculars printed in the text, in metres."""
    found = [float(m.group(1).replace(",", ".")) for m in _PRINTED_METRES.finditer(text or "")]
    for match in _PRINTED_FEET.finditer(text or ""):
        found.append((int(match.group(1)) + (int(match.group(2) or 0)) / 12) * M_PER_FT)
    found = [value for value in found if 3 <= value <= 500]
    return round(max(found), 2) if found else None


def drawn_width_fraction(gray: np.ndarray) -> float | None:
    """Width share of the widest long ink group on a grey page copy (uses the intake's grouping)."""
    from .intake import ink_groups
    boxes = ink_groups(gray)
    return long_view_width_fraction(boxes, gray.shape[1])


# ------------------------------------------------------------------ the set
def scale_agreement(sheets: list[dict]) -> dict:
    """Compare length estimates of the sheets of one set.

    Each sheet: ``{page_id, type, length_m (or None), printed_length_m (or None), scale_status}``.
    Result: ``{status, reference_m, spread, items}``; status is ``agree``, ``check`` or ``too_few``.
    Items are check items (``scale_disagrees``, ``scale_missing``, ``printed_length_differs``).
    """
    items = []
    for sheet in sheets:
        if sheet.get("type") in WHOLE_HULL_TYPES and sheet.get("scale_status") == "missing":
            items.append({"code": "scale_missing", "page_id": sheet["page_id"],
                          "message": "No printed scale found on this sheet."})
    estimates = [s for s in sheets if s.get("length_m") and s.get("type") in WHOLE_HULL_TYPES]
    if len(estimates) < 2:
        return {"status": "too_few", "reference_m": estimates[0]["length_m"] if estimates else None,
                "spread": None, "estimates": len(estimates), "items": items}
    values = [s["length_m"] for s in estimates]
    reference = statistics.median(values)
    for sheet in estimates:
        if abs(sheet["length_m"] / reference - 1) > AGREEMENT_TOLERANCE:
            items.append({"code": "scale_disagrees", "page_id": sheet["page_id"], "estimate_m": sheet["length_m"],
                          "reference_m": round(reference, 2),
                          "message": f"This sheet gives a length of {sheet['length_m']:.1f} m; "
                                     f"the other sheets give about {reference:.1f} m."})
    printed = [s["printed_length_m"] for s in sheets if s.get("printed_length_m")]
    if printed:
        stated = statistics.median(printed)
        if abs(stated / reference - 1) > PRINTED_TOLERANCE:
            items.append({"code": "printed_length_differs", "page_id": None, "estimate_m": round(reference, 2),
                          "reference_m": round(stated, 2),
                          "message": f"A printed length of {stated:.1f} m differs from the drawn length "
                                     f"of about {reference:.1f} m."})
    spread = max(values) / min(values) - 1
    disagree = any(item["code"] == "scale_disagrees" for item in items)
    return {"status": "check" if disagree else "agree",
            "reference_m": round(reference, 2), "spread": round(spread, 3), "estimates": len(estimates),
            "items": items}
