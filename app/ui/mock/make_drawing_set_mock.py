"""Generate mock/drawing_set.json: the intake preview of a made-up 24 m survey launch drawing set.

Nine sheets; the set has no shell expansion (a missing required drawing), one tank plan whose scale is
read as 1:100 against 1:50 on the other sheets (a scale check item) and one sheet with no printed scale.
Every value is synthetic. The checklist and scale agreement come from the real worker code, so the
mock cannot drift from drawing_set.py.

Run from the repository root:  PYTHONPATH=src .venv/bin/python app/ui/mock/make_drawing_set_mock.py
"""
from __future__ import annotations

import json
from pathlib import Path

from vessel_reconstruction.drawing_set import analyse_set
from vessel_reconstruction.sheet_types import SHEET_TYPE_LABELS

OUT = Path(__file__).resolve().parent / "drawing_set.json"
# (file, type, confidence, source, scale text, ratio, length_m, views, evidence)
SHEETS = [
    ("01-lines-plan.pdf", "lines_plan", 0.95, "title:ocr+text:ocr", "1:50", 50, 24.1, ["sheer", "half_breadth", "body_plan"], ["title:ocr: lines plan"]),
    ("02-general-arrangement.pdf", "general_arrangement", 0.95, "text:pdf_text", "1:50", 50, 23.8, [], ["text:pdf_text: general arrangement"]),
    ("03-profile.pdf", "profile", 0.9, "file_name+text:ocr", "1:50", 50, 24.0, [], ["file_name: profile"]),
    ("04-midship-section.pdf", "midship_section", 0.95, "text:pdf_text", "1:25", 25, None, [], ["text:pdf_text: midship section"]),
    ("05-tank-plan.pdf", "tank_plan", 0.88, "title:ocr", "1:100", 100, 47.6, [], ["title:ocr: tank plan"]),
    ("06-hydrostatics.pdf", "hydrostatics", 0.92, "text:pdf_text", None, None, None, [], ["text:pdf_text: hydrostatic tables"]),
    ("07-structure.pdf", "construction_profile", 0.62, "model:claude-sonnet-5-5", "1:50", 50, 24.3, [], ["frames and girders"]),
    ("08-title-sheet.pdf", "other", 0.4, "code:no_rule", None, None, None, [], ["no title or keyword rule matched"]),
    ("09-notes.pdf", "other", 0.3, "code:no_rule", None, None, None, [], ["no title or keyword rule matched"]),
]


def page(index: int, row: tuple) -> dict:
    file_name, kind, confidence, source, text, ratio, length, views, evidence = row
    scale = ({"status": "read", "main_ratio": float(ratio), "main_text": text, "source": "text:ocr",
              "scales": [{"ratio": float(ratio), "count": 1}]} if ratio else
             {"status": "missing", "main_ratio": None, "scales": [], "source": "none"})
    return {"page_id": f"p{index}", "file_name": file_name, "skip": False,
            "sheet": {"type": kind, "type_label": SHEET_TYPE_LABELS[kind], "confidence": confidence, "source": source,
                      "evidence": evidence, "alternatives": [], "text_source": "ocr", "views": views, "scale": scale,
                      "length_m": length, "printed_length_m": None}}


def main() -> None:
    pages = [page(i + 1, row) for i, row in enumerate(SHEETS)]
    OUT.write_text(json.dumps({"pages": pages, "set": analyse_set(pages)}, indent=1) + "\n")
    print(f"wrote {OUT.name}: {len(pages)} sheets")


if __name__ == "__main__":
    main()
