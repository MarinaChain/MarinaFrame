"""A whole drawing set: what each sheet is, what the set lacks, and whether the scales agree.

    analyse_page(...)  -> the ``sheet`` result of one page (type, scale, length estimate)
    analyse_set(pages) -> ``{rules, checklist, scale_agreement, counts}`` for the set

The checklist says, for each output (hull, tanks, steel, booklet check), which drawings are required
and which are recommended, and whether the set has them. A missing required drawing is a note for the
person, not a stop: the run goes on and the output is labelled with what it lacked. The rules are data
(``CHECKLIST_RULES``) and go to the app in the preview, so the app recomputes the list when the person
changes a type or skips a page. See docs/DRAWING_SET_INTAKE.md.

    python -m vessel_reconstruction.drawing_set FILE...      (prints the analysis as JSON)
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import numpy as np

from .sheet_scale import (drawn_width_fraction, strip_text, length_estimate_m, printed_length_m, read_scale, scale_agreement)
from .sheet_types import SHEET_TYPE_LABELS, type_sheet

SET_SCHEMA = "marinaframe.drawing_set/1"
OUTPUTS = (("hull", "Hull"), ("tanks", "Tanks"), ("steel", "Steel"), ("booklet", "Booklet check"))

# One rule per needed drawing. ``any_of`` lists the sheet types that meet it; ``via_views`` lets a
# lines plan meet it when its text names that view (a lines plan with a sheer plan shows the profile).
CHECKLIST_RULES = [
    {"id": "hull_lines", "output": "hull", "need": "Lines plan or body plan", "level": "required",
     "any_of": ["lines_plan"], "why": "The hull form is read from the lines or the body plan."},
    {"id": "hull_profile", "output": "hull", "need": "Profile", "level": "required",
     "any_of": ["profile", "construction_profile", "general_arrangement"],
     "via_views": [{"type": "lines_plan", "view": "sheer"}],
     "why": "The side view gives length, stem, stern, keel and deck lines."},
    {"id": "hull_ga", "output": "hull", "need": "General arrangement", "level": "recommended",
     "any_of": ["general_arrangement"], "why": "Gives main dimensions and checks the hull against the layout."},
    {"id": "tanks_plan", "output": "tanks", "need": "Tank or capacity plan", "level": "required",
     "any_of": ["tank_plan"], "why": "Tank outlines and volumes come from this plan."},
    {"id": "tanks_ga", "output": "tanks", "need": "General arrangement", "level": "recommended",
     "any_of": ["general_arrangement"], "why": "Shows where each tank lies in the vessel."},
    {"id": "tanks_profile", "output": "tanks", "need": "Profile", "level": "recommended",
     "any_of": ["profile", "construction_profile"], "why": "Gives tank heights."},
    {"id": "steel_midship", "output": "steel", "need": "Midship section", "level": "required",
     "any_of": ["midship_section"], "why": "Plate and stiffener sizes of a typical frame."},
    {"id": "steel_shell", "output": "steel", "need": "Shell expansion", "level": "required",
     "any_of": ["shell_expansion"], "why": "Shell plates and their thickness laid flat."},
    {"id": "steel_construction", "output": "steel", "need": "Construction profile and decks", "level": "recommended",
     "any_of": ["construction_profile"], "why": "Bulkheads, decks and girders along the vessel."},
    {"id": "booklet_tables", "output": "booklet", "need": "Hydrostatic tables", "level": "required",
     "any_of": ["hydrostatics"], "why": "The hull is checked against these tables."},
    {"id": "booklet_lines", "output": "booklet", "need": "Lines plan", "level": "recommended",
     "any_of": ["lines_plan"], "why": "Needed to rebuild the hull the tables describe."},
    {"id": "booklet_tanks", "output": "booklet", "need": "Tank or capacity plan", "level": "recommended",
     "any_of": ["tank_plan"], "why": "Checks tank volumes against the booklet."},
]

# Words in a lines-plan sheet's text that name the views it holds.
VIEW_WORDS = {"sheer": r"sheer|profile", "half_breadth": r"half\s*-?\s*breadth", "body_plan": r"body\s*plan"}


def views_in(text: str) -> list[str]:
    lowered = (text or "").lower()
    return [view for view, pattern in VIEW_WORDS.items() if re.search(pattern, lowered)]


def checklist(sheets: list[dict], rules: list[dict] = CHECKLIST_RULES) -> list[dict]:
    """Rule by rule: ``met`` with the pages that meet it, or ``missing``. ``sheets`` are ``{page_id, type, views}``."""
    items = []
    for rule in rules:
        met_by = [s["page_id"] for s in sheets if s["type"] in rule["any_of"]]
        via = [s["page_id"] for s in sheets
               for route in rule.get("via_views", []) if s["type"] == route["type"] and route["view"] in s.get("views", [])]
        pages = met_by + [page for page in via if page not in met_by]
        items.append({**{k: rule[k] for k in ("id", "output", "need", "level", "why")},
                      "status": "met" if pages else "missing", "met_by": pages,
                      "met_note": "from the sheer plan on the lines sheet" if via and not met_by else ""})
    return items


def analyse_page(*, path: Path | None, page_index: int, gray: np.ndarray, info: dict, file_name: str | None,
                 regions: list[dict] | None = None, ask=None, use_file_name: bool = True, ocr=None) -> dict:
    """The ``sheet`` result of one page: type (with source), scale, length estimate."""
    from functools import partial
    from .sheet_types import ocr_read, sheet_text
    from .particulars import pdf_words, read_text, read_words
    words = []
    text, title, where = sheet_text(path, page_index, gray, ocr or partial(ocr_read, words_out=words))
    source = {"text_source": "ocr", "bbox_space": "page_px", "file": str(path) if path else None,
              "page_index": page_index, "sheet": f"{file_name or path or 'sheet'}#{page_index + 1}"}
    readings = read_words(words, source=source)
    if ocr is not None and not words and where in ("ocr", "pdf_text+ocr"):
        readings = read_text(text, source={**source, "bbox_space": None})
    if path is not None and Path(path).suffix.lower() == ".pdf":
        try:
            layer = pdf_words(path, page_index, info.get("full_px") or [gray.shape[1], gray.shape[0]])
            readings = read_words(layer, source={**source, "text_source": "pdf_text"}) + readings
        except (OSError, ValueError, RuntimeError):
            pass  # A damaged layer does not discard the OCR readings.
    typed = type_sheet(gray=gray, file_name=file_name, regions=regions, text=text, title=title,
                       use_file_name=use_file_name, ask=ask)
    scale = read_scale(text, where)
    if scale["status"] == "missing":
        # Small lettering is lost in the whole-page OCR: read the strips where scales are printed.
        strip_words = []
        extra = strip_text(gray, ocr, words_out=strip_words)
        readings += read_words(strip_words, source=source)
        scale = read_scale(extra, "ocr_strip")
        text = f"{text}\n{extra}"
    # OCR boxes use the raster passed here; callers may analyse a reduced copy.
    sx = (info.get("full_px") or [gray.shape[1], gray.shape[0]])[0] / gray.shape[1]
    sy = (info.get("full_px") or [gray.shape[1], gray.shape[0]])[1] / gray.shape[0]
    for reading in readings:
        if reading["source"]["text_source"] == "ocr" and reading["source"]["bbox"] is not None:
            box = reading["source"]["bbox"]
            reading["source"]["bbox"] = [box[0] * sx, box[1] * sy, box[2] * sx, box[3] * sy]
    length = length_estimate_m(drawn_width_fraction(gray), info, scale["main_ratio"]) if scale["main_ratio"] else None
    return {"type": typed["type"], "type_label": SHEET_TYPE_LABELS[typed["type"]], "confidence": typed["confidence"],
            "source": typed["source"], "evidence": typed["evidence"], "alternatives": typed.get("alternatives", []),
            "text_source": where, "views": views_in(text) if typed["type"] == "lines_plan" else [],
            "scale": {k: scale.get(k) for k in ("status", "main_ratio", "main_text", "source", "scales")},
            "length_m": length, "printed_length_m": printed_length_m(text), "particulars": readings}


def analyse_set(pages: list[dict]) -> dict:
    """Checklist and scale agreement for pages that carry a ``sheet`` (skipped pages are left out)."""
    from .particulars import resolve
    kept = [p for p in pages if not p.get("skip") and p.get("sheet")]
    sheets = [{"page_id": p["page_id"], "type": p["sheet"]["type"], "views": p["sheet"].get("views", [])} for p in kept]
    agreement = scale_agreement([
        {"page_id": p["page_id"], "type": p["sheet"]["type"], "length_m": p["sheet"].get("length_m"),
         "printed_length_m": p["sheet"].get("printed_length_m"), "scale_status": p["sheet"]["scale"]["status"]}
        for p in kept])
    items = checklist(sheets)
    counts: dict[str, int] = {}
    for sheet in sheets:
        counts[sheet["type"]] = counts.get(sheet["type"], 0) + 1
    return {"schema": SET_SCHEMA, "rules": CHECKLIST_RULES, "outputs": [{"id": i, "label": l} for i, l in OUTPUTS],
            "checklist": items, "scale_agreement": agreement, "counts": counts,
            "missing_required": [i["id"] for i in items if i["level"] == "required" and i["status"] == "missing"],
            "engineering_approved": False, "particulars": resolve(pages)}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Type and scale-check the sheets of a drawing set.")
    parser.add_argument("files", nargs="+", type=Path)
    parser.add_argument("--no-file-names", action="store_true", help="do not use file names as evidence")
    args = parser.parse_args(argv)
    from .intake import read_pages
    pages = []
    for path in args.files:
        for info, image in read_pages(path):
            gray = image.mean(axis=2).astype(np.uint8) if image.ndim == 3 else image
            full = {**info, "full_px": [image.shape[1], image.shape[0]]}
            sheet = analyse_page(path=path, page_index=info["page_index"], gray=gray, info=full, file_name=path.name,
                                 use_file_name=not args.no_file_names)
            pages.append({"page_id": f"p{len(pages) + 1}", "file_name": path.name, "sheet": sheet})
    json.dump({"pages": pages, "set": analyse_set(pages)}, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
