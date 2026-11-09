"""Score the 3D cargo-hold block against MiDShip 3D truth (plan section 4.3.1, metrics S1 to S6).

Truth: the design's full IGES (one surface per CAD object, named by the BOM ``struct_rsObject``)
and the BOM. Development designs only: the W3 sealed designs are refused.

    python -m vessel_reconstruction.structure.block_eval --root work/sources/midship \\
        --out work/step2/block_dev.json [--designs 379 37] [--ocx-dir DIR --steel-dir DIR]

With ``--ocx-dir`` each block is also exported to OCX 3.0.1, checked with the schema and read back
(round trip); with ``--steel-dir`` its steel tables are written (docs/STRUCTURE_V2.md section 6).
"""
from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
import json
from pathlib import Path
import statistics
import sys

import numpy as np

from . import ocx, steel
from .block3d import VIEWS, build_block
from .midship_eval import SPLIT, truth_label

SUBSET_DIR = "SGLD_Gen_Structures"
OCX_SCHEMA_DIR = Path("work/sources/ocx_schema/ocx/ocx_301")
# Fixed in plan section 4.3.1: SGLD designs with 3D on disk, minus the W3 sealed ones.
DEVELOPMENT_3D = (107, 168, 292, 379, 391, 37, 66, 80, 191, 60, 230, 445)
SEALED_W3 = {design for subset, design in SPLIT["test"] if subset == "SGLD"}
PAD_M = 0.05
MATCH_IOU = 0.5
LONGITUDINAL_MIN_X_M = 20.0

TRANSVERSE_LABELS = {
    "Transverse_Bulkhead": "transverse_bulkhead", "Transverse_Floor": "floor",
    "Vertical_Web_Frame": "web_frame", "Deck_Transvere_Beam": "deck_beam",
    "Vertical_Side_Frame": "frame", "Transverse_Bottom_Frame": "frame",
    "Inner_Bottom_Transverse_Beam": "frame", "Deck_Transverse_Stiffener,": "frame",
}


def label_3d(bom_class: str) -> str:
    if bom_class in TRANSVERSE_LABELS:
        return TRANSVERSE_LABELS[bom_class]
    if bom_class.startswith("Transverse_Bulkhead_") and bom_class.endswith("_Stiffener"):
        return "bulkhead_stiffener"
    if bom_class.startswith("Bracket_"):
        return "bracket"
    if bom_class.endswith("_Vertical_Stiffener"):  # inner side shell / bulkhead vertical frames
        return "frame"
    return truth_label(bom_class)


@dataclass(frozen=True)
class TruthMember:
    object_id: str
    bom_class: str
    label: str
    group: str
    box: tuple[float, ...]
    thickness_mm: float
    volume_m3: float


def load_truth(igs: Path, bom_csv: Path) -> list[TruthMember]:
    from OCP.BRepBndLib import BRepBndLib
    from OCP.Bnd import Bnd_Box
    from OCP.IGESControl import IGESControl_Reader

    reader = IGESControl_Reader()
    if reader.ReadFile(str(igs)) != 1:
        raise ValueError(f"cannot read {igs}")
    reader.TransferRoots()
    transfer = reader.WS().TransferReader()
    boxes: dict[str, list[float]] = {}
    for index in range(1, reader.NbShapes() + 1):
        shape = reader.Shape(index)
        entity = transfer.EntityFromShapeResult(shape, 1)
        name = entity.NameValue().ToCString() if entity is not None and entity.HasName() else None
        bound = Bnd_Box()
        BRepBndLib.AddOptimal_s(shape, bound, False, False)
        values = [v / 1000 for v in bound.Get()]  # IGES unit is millimetres
        if name in boxes:  # union of several surfaces of one object
            old = boxes[name]
            values = [min(old[i], values[i]) for i in range(3)] + [max(old[i], values[i]) for i in range(3, 6)]
        boxes[name] = values
    truth, seen = [], set()
    with open(bom_csv, newline="") as handle:
        for row in csv.DictReader(handle):
            key = row["struct_rsObject"]
            if key in seen or key not in boxes:
                continue  # rows that share one CAD object count once
            seen.add(key)
            box = tuple(boxes[key])
            group = "longitudinal" if box[3] - box[0] > LONGITUDINAL_MIN_X_M else "transverse"
            truth.append(TruthMember(row["Object_ID"], row["Class"], label_3d(row["Class"]), group, box,
                                     float(row["Thickness"]) * 1000, float(row["volume_pannel"] or 0.0)))
    return truth


def iou_matrix(pred: np.ndarray, true: np.ndarray, pad: float = PAD_M) -> np.ndarray:
    a = pred.copy(); b = true.copy()
    a[:, :3] -= pad; a[:, 3:] += pad
    b[:, :3] -= pad; b[:, 3:] += pad
    lo = np.maximum(a[:, None, :3], b[None, :, :3])
    hi = np.minimum(a[:, None, 3:], b[None, :, 3:])
    inter = np.prod(np.clip(hi - lo, 0, None), axis=2)
    va = np.prod(a[:, 3:] - a[:, :3], axis=1)
    vb = np.prod(b[:, 3:] - b[:, :3], axis=1)
    return inter / (va[:, None] + vb[None, :] - inter)


def match(pred_boxes: np.ndarray, true_boxes: np.ndarray) -> list[tuple[int, int, float]]:
    from scipy.optimize import linear_sum_assignment

    if len(pred_boxes) == 0 or len(true_boxes) == 0:
        return []
    iou = iou_matrix(pred_boxes, true_boxes)
    weights = np.where(iou >= MATCH_IOU, iou, 0.0)
    rows, cols = linear_sum_assignment(-weights)
    return [(int(r), int(c), float(iou[r, c])) for r, c in zip(rows, cols) if iou[r, c] >= MATCH_IOU]


def score_design(block: dict, truth: list[TruthMember]) -> dict:
    members = block["members"]
    pred = np.array([m["box"] for m in members], dtype=float).reshape(-1, 6)
    true = np.array([t.box for t in truth], dtype=float).reshape(-1, 6)
    pairs = match(pred, true)
    matched_pred = {p for p, _, _ in pairs}
    matched_true = {t for _, t, _ in pairs}
    record: dict = {"n_pred": len(members), "n_true": len(truth), "tp": len(pairs)}
    for group in ("longitudinal", "transverse"):
        n_true = sum(1 for t in truth if t.group == group)
        n_pred = sum(1 for m in members if m["group"] == group)
        record[group] = {"n_true": n_true, "n_pred": n_pred,
                         "tp_true": sum(1 for t in matched_true if truth[t].group == group),
                         "tp_pred": sum(1 for p in matched_pred if members[p]["group"] == group)}
    labels: dict[str, dict[str, int]] = {}
    for t in truth:
        labels.setdefault(t.label, {"true": 0, "pred": 0, "tp": 0})["true"] += 1
    for m in members:
        labels.setdefault(m["label"], {"true": 0, "pred": 0, "tp": 0})["pred"] += 1
    centre, x_error, thickness = [], [], []
    for p, t, _ in pairs:
        member, item = members[p], truth[t]
        if member["label"] == item.label:
            labels[item.label]["tp"] += 1
        c_pred = (pred[p, :3] + pred[p, 3:]) / 2
        c_true = (true[t, :3] + true[t, 3:]) / 2
        centre.append(float(np.linalg.norm(c_pred - c_true)) * 1000)
        if item.group == "transverse":
            x_error.append(float(abs(c_pred[0] - c_true[0])) * 1000)
        if member["thickness_mm"] is not None:
            thickness.append({"group": item.group, "source": member["thickness_source"],
                              "pred": member["thickness_mm"], "true": item.thickness_mm})
    volume_pred = sum((m["thickness_mm"] or 0.0) / 1000 * m["area_m2"] for m in members)
    volume_true = sum(t.volume_m3 for t in truth)
    sources: dict[str, int] = {}
    for m in members:
        key = "guessed" if "guessed" in {v for k, v in m["sources"].items() if k != "length" and k != "block_length"} \
            else "traced_section_and_spacing"
        sources[key] = sources.get(key, 0) + 1
    record.update(labels=labels, centre_mm=centre, transverse_x_mm=x_error, thickness=thickness,
                  volume_pred_m3=volume_pred, volume_true_m3=volume_true,
                  volume_rel_error=volume_pred / volume_true - 1 if volume_true else None,
                  placement_sources=sources)
    return record


def _prf(tp: int, n_pred: int, n_true: int) -> dict:
    p = tp / n_pred if n_pred else 0.0
    r = tp / n_true if n_true else 0.0
    return {"precision": round(p, 4), "recall": round(r, 4),
            "f1": round(2 * p * r / (p + r), 4) if p + r else 0.0, "tp": tp, "n_pred": n_pred, "n_true": n_true}


def _quantiles(values: list[float]) -> dict:
    if not values:
        return {"n": 0}
    ordered = sorted(values)
    return {"n": len(ordered), "median": round(statistics.median(ordered), 2),
            "p95": round(ordered[min(len(ordered) - 1, int(0.95 * len(ordered)))], 2), "max": round(ordered[-1], 2)}


def summarise(per_design: dict[str, dict]) -> dict:
    records = list(per_design.values())
    tp = sum(r["tp"] for r in records)
    summary = {"S1_detection": _prf(tp, sum(r["n_pred"] for r in records), sum(r["n_true"] for r in records))}
    for group in ("longitudinal", "transverse"):
        n_true = sum(r[group]["n_true"] for r in records)
        n_pred = sum(r[group]["n_pred"] for r in records)
        summary[f"S1_{group}"] = {
            "recall": round(sum(r[group]["tp_true"] for r in records) / n_true, 4) if n_true else None,
            "precision": round(sum(r[group]["tp_pred"] for r in records) / n_pred, 4) if n_pred else None,
            "n_true": n_true, "n_pred": n_pred}
    labels: dict[str, dict[str, int]] = {}
    for r in records:
        for label, counts in r["labels"].items():
            total = labels.setdefault(label, {"true": 0, "pred": 0, "tp": 0})
            for key in total:
                total[key] += counts[key]
    typed = {label: _prf(c["tp"], c["pred"], c["true"]) for label, c in sorted(labels.items())}
    with_truth = [v["f1"] for label, v in typed.items() if labels[label]["true"]]
    summary["S2_typed"] = {"per_label": typed, "macro_f1": round(sum(with_truth) / len(with_truth), 4)}
    summary["S3_placement"] = {"centre_mm": _quantiles([v for r in records for v in r["centre_mm"]]),
                               "transverse_x_mm": _quantiles([v for r in records for v in r["transverse_x_mm"]])}
    s4 = {}
    # S4 counts members with a printed thickness; guessed thicknesses are a diagnostic.
    for key, source in (("longitudinal", "printed"), ("transverse", "printed"), ("guessed_diagnostic", "guessed")):
        group = None if key == "guessed_diagnostic" else key
        items = [t for r in records for t in r["thickness"]
                 if t["source"] == source and (group is None or t["group"] == group)]
        if items:
            s4[key] = {"n": len(items),
                       "exact": round(sum(round(t["pred"]) == round(t["true"]) for t in items) / len(items), 4),
                       "equals_truth_cut_to_mm": round(sum(int(t["pred"]) == int(t["true"] + 1e-6)
                                                           for t in items) / len(items), 4),
                       "abs_error_mm": _quantiles([abs(t["pred"] - t["true"]) for t in items])}
    summary["S4_thickness"] = s4
    errors = [r["volume_rel_error"] for r in records if r["volume_rel_error"] is not None]
    summary["S5_steel_volume"] = {"median_abs_rel_error": round(statistics.median(abs(e) for e in errors), 4),
                                  "per_design": {k: round(v["volume_rel_error"], 4) for k, v in per_design.items()}}
    sources: dict[str, int] = {}
    for r in records:
        for key, count in r["placement_sources"].items():
            sources[key] = sources.get(key, 0) + count
    summary["S6_placement_sources"] = sources
    return summary


def design_paths(root: Path, design: int) -> tuple[dict[str, Path], Path, Path]:
    base = root / SUBSET_DIR
    sheets = {key: base / "Dataset_Drawings" / f"sgld_design_{design}_{view}.pdf" for key, view in VIEWS.items()}
    return sheets, base / f"sgld_design_{design}.igs", base / f"sgld_design_{design}_Structural_Elements.csv"


def truth_guesses(bom_csv: Path) -> tuple[float, int]:
    """Diagnostic only: block length and frame spaces per web space from the BOM (truth)."""
    with open(bom_csv, newline="") as handle:
        rows = list(csv.DictReader(handle))
    length = next(float(r["L1"]) for r in rows if r["Class"] == "Bottom_Shell")
    webs = sorted({round(float(r["x_loc"]), 4) for r in rows if r["Class"] == "Transverse_Floor"})
    frames = sorted({round(float(r["x_loc"]), 4) for r in rows
                     if r["Class"] in ("Vertical_Side_Frame", "Inner_Bottom_Transverse_Beam")})
    return length, round((webs[1] - webs[0]) / (frames[1] - frames[0]))


def export_checks(block: dict, design: int, ocx_dir: Path | None, steel_dir: Path | None,
                  schema_dir: Path) -> dict:
    """OCX export, schema check and round trip; steel tables. Returns the check record."""
    record: dict = {}
    if steel_dir is not None:
        rows = steel.member_weights(block["members"])
        steel.write_steel_tables(block, steel_dir, f"sgld_{design}_DRAFT")
        record["steel_weight_t"] = round(sum(r["weight_t"] for r in rows), 3)
        record["steel_volume_m3"] = round(sum(r["volume_m3"] for r in rows), 5)
    if ocx_dir is not None:
        ocx_dir.mkdir(parents=True, exist_ok=True)
        path = ocx_dir / f"sgld_{design}_DRAFT.3docx"
        ocx.export_ocx(block, path, name=f"SGLD {design} cargo-hold block (draft)")
        check = ocx.validate(path, schema_dir)
        record["ocx"] = {"schema_valid": check.valid, "schema_errors": check.errors[:5],
                         "round_trip": ocx.round_trip(block, path)}
    return record


def evaluate(root: Path, designs, oracle_guesses: bool = False, ocx_dir: Path | None = None,
             steel_dir: Path | None = None, schema_dir: Path = OCX_SCHEMA_DIR) -> dict:
    per_design, errors, exports = {}, {}, {}
    for design in designs:
        if design in SEALED_W3:
            raise SystemExit(f"SGLD {design} is a W3 sealed design; it is not scored (plan section 4.3.1)")
        sheets, igs, bom = design_paths(root, design)
        try:
            if oracle_guesses:  # diagnostic: what the two generator guesses cost
                length, frames_per_web = truth_guesses(bom)
                block = build_block(sheets, length_m=length, frames_per_web=frames_per_web)
            else:
                block = build_block(sheets)
        except ValueError as error:
            errors[str(design)] = str(error)
            continue
        record = score_design(block, load_truth(igs, bom))
        per_design[str(design)] = record
        if ocx_dir is not None or steel_dir is not None:
            exports[str(design)] = export_checks(block, design, ocx_dir, steel_dir, schema_dir)
        d = _prf(record["tp"], record["n_pred"], record["n_true"])
        print(f"SGLD {design}: pred {record['n_pred']} true {record['n_true']} F1 {d['f1']} "
              f"volume {record['volume_rel_error']:+.3f}", file=sys.stderr)
    report = {"engineering_approved": False, "designs": list(designs), "build_errors": errors,
              "oracle_guesses": oracle_guesses,
              "summary": summarise(per_design) if per_design else None,
              "exports": exports,
              "per_design": {k: {key: v[key] for key in ("n_pred", "n_true", "tp", "longitudinal", "transverse",
                                                         "volume_rel_error", "labels")}
                             for k, v in per_design.items()}}
    return report


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--designs", type=int, nargs="*", default=list(DEVELOPMENT_3D))
    parser.add_argument("--ocx-dir", type=Path, help="write, validate and read back an OCX file per design")
    parser.add_argument("--steel-dir", type=Path, help="write the steel tables (CSV) per design")
    parser.add_argument("--ocx-schema", type=Path, default=OCX_SCHEMA_DIR, help="folder of the OCX 3.0.1 XSD")
    parser.add_argument("--oracle-guesses", action="store_true",
                        help="diagnostic: take block length and frame spacing from the truth BOM")
    args = parser.parse_args(argv)
    report = evaluate(args.root, args.designs, args.oracle_guesses, args.ocx_dir, args.steel_dir, args.ocx_schema)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=1))
    print(json.dumps(report["summary"], indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
