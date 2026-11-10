"""Scale reading and cross-sheet agreement on the labelled development sheets.

    PYTHONPATH=src:. .venv/bin/python -m benchmarks.drawing_set.evaluate_scale [--out FILE]

Reported: (1) share of sheets with a printed scale read; (2) for sheets with a labelled scale (the
Gunnerus README table) whether the read main scale equals it; (3) per ship set, the length estimates
of the whole-hull sheets, their spread and the sheets that become check items. Ship lengths are
not labelled here (no truth), so agreement means "the sheets say the same length", not "the length is right".
"""
from __future__ import annotations

import argparse
import json
import statistics
from collections import defaultdict

from vessel_reconstruction.sheet_scale import (drawn_width_fraction, length_estimate_m, printed_length_m, read_scale,
                                               scale_agreement)
from vessel_reconstruction.sheet_types import decide, ocr_read

from .common import SOURCES, cached_strip_text, cached_text, labelled, load_gray


def run() -> dict:
    rows = []
    for rel, label in sorted(labelled().items()):
        path = SOURCES / rel
        gray, info = load_gray(path)
        text, title, where = cached_text(path, gray, ocr_read)
        scale = read_scale(text, where)
        if scale["status"] == "missing":  # as drawing_set.analyse_page: read the strips where scales are printed
            extra = cached_strip_text(path)
            scale = read_scale(extra, "ocr_strip")
            text = f"{text}\n{extra}"
        proposed = decide(text, where, None, None, title)["type"]  # no file name: a customer's names may say nothing
        width = drawn_width_fraction(gray)
        rows.append({"file": rel, "set": label["set"], "label_type": label["type"], "type": proposed,
                     "labelled_scale": label["scale"], "scale_status": scale["status"], "main_ratio": scale["main_ratio"],
                     "scales": scale["scales"], "printed_length_m": printed_length_m(text),
                     "width_fraction": None if width is None else round(width, 3),
                     "length_m": length_estimate_m(width, info, scale["main_ratio"]) if scale["main_ratio"] else None})
    sets = defaultdict(list)
    for index, row in enumerate(rows):
        sets[row["set"]].append({"page_id": f"p{index}", "type": row["type"], "length_m": row["length_m"],
                                 "printed_length_m": row["printed_length_m"], "scale_status": row["scale_status"],
                                 "file": row["file"]})
    agreement = {}
    for name, sheets in sets.items():
        result = scale_agreement(sheets)
        lengths = sorted(s["length_m"] for s in sheets if s["length_m"] and s["type"] != "other")
        agreement[name] = {"sheets": len(sheets), "status": result["status"], "estimates": result["estimates"],
                           "reference_m": result["reference_m"], "spread": result["spread"], "lengths_m": lengths,
                           "check_items": [{"code": i["code"], "file": next((s["file"] for s in sheets if s["page_id"] == i["page_id"]), None)}
                                           for i in result["items"] if i["code"] != "scale_missing"]}
    read = [r for r in rows if r["scale_status"] != "missing"]
    truth = [r for r in rows if r["labelled_scale"]]
    exact = [r for r in truth if r["main_ratio"] is not None and f"1:{round(r['main_ratio'])}" == r["labelled_scale"]]
    contained = [r for r in truth if any(f"1:{s['ratio']:.0f}" == r["labelled_scale"] for s in r["scales"])]
    summary = {"sheets": len(rows), "with_printed_scale_read": len(read),
               "by_set_read": {name: [sum(r["scale_status"] != "missing" for r in rows if r["set"] == name),
                                      sum(1 for r in rows if r["set"] == name)] for name in sets},
               "labelled": len(truth), "main_scale_equals_label": len(exact), "label_among_read_scales": len(contained),
               "printed_length_found": sum(r["printed_length_m"] is not None for r in rows)}
    return {"summary": summary, "agreement": agreement, "rows": rows}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--out")
    args = parser.parse_args()
    result = run()
    print(json.dumps(result["summary"], indent=1))
    print(json.dumps(result["agreement"], indent=1))
    for r in result["rows"]:
        if r["labelled_scale"]:
            print(r["file"][-40:], "label", r["labelled_scale"], "read", r["scales"], "len", r["length_m"], "printed", r["printed_length_m"])
    if args.out:
        open(args.out, "w").write(json.dumps(result, indent=1))
