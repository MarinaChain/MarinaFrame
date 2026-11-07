"""Score section reading against MiDShip ground truth (docs/STRUCTURE_V1.md).

Ground truth comes from the design's ``*_Slice_Elements.csv`` (boxes) and
``*_Structural_Elements.csv`` (BOM class, thickness, web height). The reader
under test receives only the plain PDF. The sealed test split runs only with
``--confirm-sealed-run`` from a clean source tree, and the result records the
commit.
"""
from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
import json
import math
from pathlib import Path
import statistics
import subprocess
import sys

import numpy as np

from . import read_section_pdf
from .model import PLATE_ROLES, ROLES, SectionResult

VIEW = "Midship Section of Long. Structure"
# The dataset pads every box by 1 drawing millimetre on each side.
BOX_PAD_MM = 1.0
MATCH_IOU = 0.5

STEMS = {"Random": "random_test_design_", "Repaired": "repaired_random_design_design_",
         "SGLD": "sgld_design_"}
SHIP_TYPES = {
    "Random": {5597: "tanker", 5942: "tanker", 1253: "tanker", 4270: "tanker",
               6018: "container", 3498: "container", 4660: "container", 1571: "container",
               5718: "bulk", 5088: "bulk", 2870: "bulk", 2787: "bulk"},
    "Repaired": {3835: "tanker", 3460: "tanker", 1332: "tanker", 2313: "tanker",
                 5156: "container", 2176: "container", 1698: "container", 2203: "container",
                 5643: "bulk", 2564: "bulk", 1383: "bulk", 2082: "bulk"},
    "SGLD": {379: "tanker", 429: "tanker", 205: "tanker", 381: "tanker",
             37: "container", 118: "container", 71: "container", 308: "container",
             215: "bulk", 17: "bulk", 473: "bulk", 257: "bulk"},
}
# Fixed in docs/STRUCTURE_V1.md section 4 before any extraction code existed.
SPLIT = {
    "development": [("Random", 5597), ("Random", 3498), ("Random", 2870),
                    ("Repaired", 2313), ("Repaired", 2203), ("Repaired", 1383),
                    ("SGLD", 429), ("SGLD", 379), ("SGLD", 37), ("SGLD", 473)],
    "test": [("Random", i) for i in (5942, 1253, 4270, 6018, 4660, 1571, 5718, 5088, 2787)]
            + [("Repaired", i) for i in (3835, 3460, 1332, 5156, 2176, 1698, 5643, 2564, 2082)]
            + [("SGLD", i) for i in (205, 381, 118, 71, 308, 215, 17, 257)],
}

HOST_PREFIXES = ("Inner_Bottom", "Inner_Side_Shell", "Bottom", "Deck", "Side_Shell",
                 "Longitudinal_Bulkhead", "Hopper_Pannel")


def truth_label(bom_class: str) -> str:
    fixed = {"Bottom_Shell": "bottom_shell", "Side_Shell": "side_shell",
             "Shell_Strake": "shell_strake", "Deck": "deck",
             "Longitudinal_Bulkhead": "longitudinal_bulkhead", "Hopper Pannel": "hopper_plate",
             "Stiffener_Flange": "flange"}
    if bom_class in fixed:
        return fixed[bom_class]
    if bom_class.endswith("_Longitudinal_Girder"):
        return "girder"
    if bom_class.endswith("_Longitudinal_Stiffener"):
        return "stiffener_web"
    return "other"


def truth_host(bom_class: str) -> str | None:
    for prefix in HOST_PREFIXES:
        if bom_class.startswith(prefix + "_"):
            return prefix
    return None


@dataclass(frozen=True)
class TruthElement:
    object_id: str
    bom_class: str
    label: str
    host: str | None
    drawing_box: tuple[float, float, float, float]  # padded, x0 z0 x1 z1, drawing mm
    ship_box_mm: tuple[float, float, float, float]  # unpadded, y0 z0 y1 z1
    thickness_mm: float
    l2_mm: float


def design_files(root: Path, subset: str, design_id: int) -> dict[str, Path]:
    stem = f"{STEMS[subset]}{design_id}"
    found = {}
    with open(root / "manifest.tsv", newline="") as handle:
        for row in csv.DictReader(handle, delimiter="\t"):
            name = Path(row["path"]).name
            if not name.startswith(stem + "_") and not name.startswith(stem + "."):
                continue
            if name == f"{stem}_{VIEW}.pdf":
                found["pdf"] = root / row["path"]
            elif name == f"{stem}_Slice_Elements.csv":
                found["slices"] = root / row["path"]
            elif name == f"{stem}_Structural_Elements.csv":
                found["bom"] = root / row["path"]
    missing = {"pdf", "slices", "bom"} - set(found)
    if missing:
        raise FileNotFoundError(f"{stem}: missing {sorted(missing)}")
    return found


def load_truth(slices_csv: Path, bom_csv: Path) -> tuple[list[TruthElement], float, tuple[float, float]]:
    with open(bom_csv, newline="") as handle:
        bom = list(csv.DictReader(handle))
    elements, scales, origins = [], set(), []
    with open(slices_csv, newline="") as handle:
        for row in csv.DictReader(handle):
            if row["Slice_Name"] != VIEW or row["bbox_y"] == "":
                continue
            scale = float(row["Ship2Dwg_Scale [1m:Xmm]"])
            scales.add(scale)
            item = bom[int(row["struct_elem_idx"])]
            pad_m = BOX_PAD_MM / scale
            y, z = float(row["bbox_y"]), float(row["bbox_z"])
            ly, lz = float(row["bbox_Ly"]), float(row["bbox_Lz"])
            dy, dz = float(row["bbox_dwg_mm_y"]), float(row["bbox_dwg_mm_z"])
            dly, dlz = float(row["bbox_dwg_mm_Ly"]), float(row["bbox_dwg_mm_Lz"])
            origins.append((dy - scale * y, dz - scale * z))
            ship = ((y + pad_m) * 1000, (z + pad_m) * 1000, (y + ly - pad_m) * 1000, (z + lz - pad_m) * 1000)
            elements.append(TruthElement(
                row["Object_ID"], item["Class"], truth_label(item["Class"]), truth_host(item["Class"]),
                (dy, dz, dy + dly, dz + dlz), ship,
                float(item["Thickness"]) * 1000, float(item["L2"]) * 1000))
    if len(scales) != 1:
        raise ValueError(f"{slices_csv}: expected one scale, found {sorted(scales)}")
    origin = (statistics.median(o[0] for o in origins), statistics.median(o[1] for o in origins))
    return elements, scales.pop(), origin


def _iou_matrix(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    if len(a) == 0 or len(b) == 0:
        return np.zeros((len(a), len(b)))
    x0 = np.maximum(a[:, None, 0], b[None, :, 0])
    z0 = np.maximum(a[:, None, 1], b[None, :, 1])
    x1 = np.minimum(a[:, None, 2], b[None, :, 2])
    z1 = np.minimum(a[:, None, 3], b[None, :, 3])
    inter = np.clip(x1 - x0, 0, None) * np.clip(z1 - z0, 0, None)
    area_a = (a[:, 2] - a[:, 0]) * (a[:, 3] - a[:, 1])
    area_b = (b[:, 2] - b[:, 0]) * (b[:, 3] - b[:, 1])
    return inter / (area_a[:, None] + area_b[None, :] - inter)


def match(result: SectionResult, truth: list[TruthElement]) -> list[tuple[int, int, float]]:
    """One-to-one matches (prediction index, truth index, IoU) with IoU >= 0.5."""
    from scipy.optimize import linear_sum_assignment
    predicted = np.array([[m.stroke.bbox[0] - BOX_PAD_MM, m.stroke.bbox[1] - BOX_PAD_MM,
                           m.stroke.bbox[2] + BOX_PAD_MM, m.stroke.bbox[3] + BOX_PAD_MM]
                          for m in result.members]).reshape(-1, 4)
    true = np.array([t.drawing_box for t in truth]).reshape(-1, 4)
    iou = _iou_matrix(predicted, true)
    if iou.size == 0:
        return []
    rows, cols = linear_sum_assignment(-np.where(iou >= MATCH_IOU, iou, 0.0))
    return [(int(r), int(c), float(iou[r, c])) for r, c in zip(rows, cols) if iou[r, c] >= MATCH_IOU]


def score_design(result: SectionResult, truth: list[TruthElement], scale: float,
                 true_origin: tuple[float, float]) -> dict:
    pairs = match(result, truth)
    matched_truth = {t for _, t, _ in pairs}
    record = {
        "predicted": len(result.members), "truth": len(truth), "matched": len(pairs),
        "abstentions": [a.as_dict() for a in result.abstentions],
        "section_strokes": result.section_strokes,
        "scale_read": result.scale_mm_per_m, "scale_true": scale,
        "label_pairs": [], "host_pairs": [], "centre_error_mm": [], "edge_error_mm": [],
        "plate_thickness": [], "web_thickness": [], "web_height": [], "flange_width": [],
        "unmatched_truth": [], "unmatched_predicted": [],
    }
    if result.origin_mm is not None:
        record["origin_error_mm"] = [(result.origin_mm[i] - true_origin[i]) / scale * 1000 for i in (0, 1)]
    for p, t, _ in pairs:
        member, element = result.members[p], truth[t]
        record["label_pairs"].append([member.role, element.label])
        if element.label in ("girder", "stiffener_web"):
            record["host_pairs"].append([member.host, element.host])
        if member.ship_bbox_mm is not None:
            pb, tb = member.ship_bbox_mm, element.ship_box_mm
            centre = math.dist(((pb[0] + pb[2]) / 2, (pb[1] + pb[3]) / 2),
                               ((tb[0] + tb[2]) / 2, (tb[1] + tb[3]) / 2))
            record["centre_error_mm"].append(centre)
            record["edge_error_mm"].append(max(abs(a - b) for a, b in zip(pb, tb)))
        if element.label in PLATE_ROLES:
            record["plate_thickness"].append([member.thickness_mm, element.thickness_mm])
        if element.label in ("girder", "stiffener_web"):
            record["web_thickness"].append([member.thickness_mm, element.thickness_mm])
            record["web_height"].append([member.measured_length_mm, element.l2_mm, element.label])
        if element.label == "flange":
            record["flange_width"].append([member.measured_length_mm, element.l2_mm])
    record["unmatched_truth"] = [[truth[i].object_id, truth[i].label]
                                 for i in range(len(truth)) if i not in matched_truth]
    matched_pred = {p for p, _, _ in pairs}
    record["unmatched_predicted"] = [[m.stroke.index, m.role, m.stroke.source]
                                     for i, m in enumerate(result.members) if i not in matched_pred]
    return record


def _prf(tp: int, n_pred: int, n_true: int) -> dict:
    precision = tp / n_pred if n_pred else None
    recall = tp / n_true if n_true else None
    f1 = 2 * tp / (n_pred + n_true) if (n_pred + n_true) else None
    return {"tp": tp, "predicted": n_pred, "truth": n_true,
            "precision": precision, "recall": recall, "f1": f1}


def _quantiles(values: list[float]) -> dict:
    if not values:
        return {"n": 0}
    array = np.array(values, dtype=float)
    return {"n": len(values), "median": float(np.median(array)),
            "p95": float(np.percentile(array, 95)), "max": float(array.max())}


def summarise(records: list[dict]) -> dict:
    tp = sum(r["matched"] for r in records)
    n_pred = sum(r["predicted"] for r in records)
    n_true = sum(r["truth"] for r in records)
    summary = {"designs": len(records), "detection": _prf(tp, n_pred, n_true)}
    per_label = {}
    labels = list(ROLES) + ["other"]
    for label in labels:
        typed_tp = sum(1 for r in records for p, t in r["label_pairs"] if p == t == label)
        predicted = sum(r["predicted_labels"].get(label, 0) for r in records)
        true = sum(r["truth_labels"].get(label, 0) for r in records)
        if predicted or true:
            per_label[label] = _prf(typed_tp, predicted, true)
    summary["typed"] = per_label
    f1s = [v["f1"] for k, v in per_label.items() if k != "other" and v["truth"]]
    summary["typed_macro_f1"] = float(np.mean(f1s)) if f1s else None
    summary["typed_micro_f1"] = _prf(sum(v["tp"] for v in per_label.values()), n_pred, n_true)["f1"]
    hosts = [pair for r in records for pair in r["host_pairs"]]
    summary["host_accuracy"] = {"n": len(hosts),
                                "correct": sum(1 for p, t in hosts if p == t),
                                "rate": (sum(1 for p, t in hosts if p == t) / len(hosts)) if hosts else None}
    summary["centre_error_mm"] = _quantiles([e for r in records for e in r["centre_error_mm"]])
    summary["edge_error_mm"] = _quantiles([e for r in records for e in r["edge_error_mm"]])
    for key in ("plate_thickness", "web_thickness"):
        pairs = [pair for r in records for pair in r[key]]
        covered = [(p, t) for p, t in pairs if p is not None]
        exact = sum(1 for p, t in covered if round(p) == round(t))
        # Added after the development run, before the sealed run: the sheet
        # prints the BOM thickness cut to whole millimetres (16.85 -> 16).
        truncated = sum(1 for p, t in covered if p == math.floor(t + 1e-6))
        summary[key] = {"matched": len(pairs), "covered": len(covered), "exact": exact,
                        "exact_rate": exact / len(covered) if covered else None,
                        "equals_truncated_truth": truncated,
                        "truncated_rate": truncated / len(covered) if covered else None,
                        "abs_error_mm": _quantiles([abs(p - t) for p, t in covered])}
    for key in ("web_height", "flange_width"):
        errors = [abs(p - t) for r in records for p, t, *_ in r[key] if p is not None]
        summary[key + "_abs_error_mm"] = _quantiles(errors)
    origin = [r["origin_error_mm"] for r in records if "origin_error_mm" in r]
    summary["origin_error_mm"] = {"centreline": _quantiles([abs(o[0]) for o in origin]),
                                  "baseline": _quantiles([abs(o[1]) for o in origin])}
    reasons: dict[str, int] = {}
    for r in records:
        for a in r["abstentions"]:
            reasons[a["reason"]] = reasons.get(a["reason"], 0) + 1
    summary["abstention_reasons"] = reasons
    stroke_abstentions = sum(1 for r in records for a in r["abstentions"] if a["subject"].startswith("stroke:"))
    strokes = sum(r["section_strokes"] for r in records)
    summary["section_strokes_explained"] = (1 - stroke_abstentions / strokes) if strokes else None
    return summary


def evaluate(root: Path, designs, mode: str) -> dict:
    records = []
    for subset, design_id in designs:
        files = design_files(root, subset, design_id)
        truth, scale, origin = load_truth(files["slices"], files["bom"])
        result = read_section_pdf(files["pdf"], mode=mode)
        record = score_design(result, truth, scale, origin)
        record.update({"subset": subset, "design": design_id,
                       "ship_type": SHIP_TYPES[subset][design_id],
                       "predicted_labels": _count(m.role for m in result.members),
                       "truth_labels": _count(t.label for t in truth)})
        records.append(record)
    groups = {"all": records}
    for subset in STEMS:
        groups[f"subset:{subset}"] = [r for r in records if r["subset"] == subset]
    for ship_type in ("tanker", "container", "bulk"):
        groups[f"type:{ship_type}"] = [r for r in records if r["ship_type"] == ship_type]
    per_design = {f"{r['subset']}:{r['design']}": summarise([r]) for r in records}
    return {"mode": mode, "summary": {k: summarise(v) for k, v in groups.items() if v},
            "per_design": per_design, "records": records}


def _count(values) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        counts[value] = counts.get(value, 0) + 1
    return counts


def _git_state(repo: Path) -> dict:
    sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True).stdout.strip()
    dirty = subprocess.run(["git", "status", "--porcelain", "--", "src"], cwd=repo,
                           capture_output=True, text=True).stdout.strip()
    return {"commit": sha, "src_dirty": bool(dirty)}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True, help="MiDShip sample directory with manifest.tsv")
    parser.add_argument("--split", choices=sorted(SPLIT), required=True)
    parser.add_argument("--mode", choices=("vector", "raster"), default="vector")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--confirm-sealed-run", action="store_true",
                        help="required for the test split; run once, from committed code")
    args = parser.parse_args(argv)
    repo = Path(__file__).resolve().parents[3]
    state = _git_state(repo)
    if args.split == "test":
        if not args.confirm_sealed_run:
            parser.error("the test split is sealed; pass --confirm-sealed-run for the single frozen run")
        if state["src_dirty"]:
            parser.error("source tree has uncommitted changes; commit before the sealed run")
    report = evaluate(args.root, SPLIT[args.split], args.mode)
    report["code"] = state
    report["split"] = args.split
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=1, default=float))
    print(json.dumps(report["summary"]["all"], indent=1, default=float))
    return 0


if __name__ == "__main__":
    sys.exit(main())
