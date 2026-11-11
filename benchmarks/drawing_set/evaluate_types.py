"""Type accuracy of sheet_types on the labelled development sheets (docs/DRAWING_SET_INTAKE.md section 4).

    PYTHONPATH=src:. .venv/bin/python -m benchmarks.drawing_set.evaluate_types [--vision] [--out FILE]
"""
from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict

from vessel_reconstruction.drawing_set import CHECKLIST_RULES
from vessel_reconstruction.sheet_types import SHEET_TYPES, decide, ocr_read, VISION_BELOW

from .common import SOURCES, cached_text, labelled, load_gray


def run(vision: bool = False, files: list[str] | None = None) -> dict:
    labels = labelled()
    rows = []
    for rel, label in sorted(labels.items()):
        if files and not any(f in rel for f in files):
            continue
        path = SOURCES / rel
        gray, _ = load_gray(path)
        text, title, where = cached_text(path, gray, ocr_read)
        row = {"file": rel, "set": label["set"], "label": label["type"], "text_chars": len(text), "text_where": where}
        for mode, use_name in (("with_name", True), ("no_name", False)):
            result = decide(text, where, path.name if use_name else None, None, title)
            row[mode] = {"type": result["type"], "confidence": result["confidence"], "source": result["source"]}
        rows.append(row)
    return {"rows": rows, "summary": summarise(rows), "checklist": checklist_agreement(rows)}


def checklist_agreement(rows: list[dict], mode: str = "no_name") -> dict:
    """Per ship set: the checklist from the proposed types against the checklist from the labels.

    Lines-plan view words are not used on either side (views are empty), so only types are compared.
    """
    from vessel_reconstruction.drawing_set import checklist
    result = {}
    sets = sorted({r["set"] for r in rows})
    for name in sets:
        mine = [r for r in rows if r["set"] == name]
        truth = checklist([{"page_id": str(i), "type": r["label"], "views": []} for i, r in enumerate(mine)])
        said = checklist([{"page_id": str(i), "type": r[mode]["type"], "views": []} for i, r in enumerate(mine)])
        differ = [t["id"] for t, d in zip(truth, said) if t["status"] != d["status"]]
        required_truth = [t["id"] for t in truth if t["level"] == "required" and t["status"] == "missing"]
        required_said = [d["id"] for d in said if d["level"] == "required" and d["status"] == "missing"]
        result[name] = {"sheets": len(mine), "items_differing": differ, "required_missing_true": required_truth,
                        "required_missing_said": required_said}
    items = len(sets) * len(CHECKLIST_RULES)
    wrong = sum(len(v["items_differing"]) for v in result.values())
    return {"per_set": result, "items": items, "items_equal": items - wrong}


def summarise(rows: list[dict]) -> dict:
    summary = {}
    for mode in ("with_name", "no_name"):
        right = sum(r[mode]["type"] == r["label"] for r in rows)
        settled = [r for r in rows if r[mode]["confidence"] >= VISION_BELOW]
        per_type = {}
        for kind in SHEET_TYPES:
            truth = [r for r in rows if r["label"] == kind]
            said = [r for r in rows if r[mode]["type"] == kind]
            hit = sum(r[mode]["type"] == kind for r in truth)
            per_type[kind] = {"n": len(truth), "recall": round(hit / len(truth), 3) if truth else None,
                              "precision": round(hit / len(said), 3) if said else None}
        summary[mode] = {"n": len(rows), "accuracy": round(right / len(rows), 3),
                         "settled_by_code": len(settled), "settled_accuracy":
                         round(sum(r[mode]["type"] == r["label"] for r in settled) / len(settled), 3) if settled else None,
                         "unsure": len(rows) - len(settled), "per_type": per_type}
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--out")
    parser.add_argument("files", nargs="*")
    args = parser.parse_args()
    result = run(files=args.files)
    print(json.dumps(result["summary"], indent=1))
    print(json.dumps(result["checklist"], indent=1))
    for r in result["rows"]:
        if r["no_name"]["type"] != r["label"]:
            print("MISS", r["label"], "->", r["no_name"]["type"], r["no_name"]["confidence"], r["text_chars"], r["file"][-60:])
    if args.out:
        open(args.out, "w").write(json.dumps(result, indent=1))
