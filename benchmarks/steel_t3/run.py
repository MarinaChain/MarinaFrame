"""Tranche 3 development run of the 3D cargo-hold block (docs/plans/2026-11-11-steel-tranche3.md).

Builds each block from the three plain PDFs only and scores it with the section 4.3.1 metrics
(``block_eval``): truth is the staging full IGES joined to the BOM. Drawings and BOM come from the
non-sealed ``midship-remainder/loose`` area, CAD from the tranche 3 development staging.

    PYTHONPATH=src:. .venv/bin/python -m benchmarks.steel_t3.run --label baseline [--ocx]

Outputs (git-ignored): ``work/steel-t3/<label>/report.json`` and one block JSON per design.
"""
from __future__ import annotations

import argparse
import csv
from dataclasses import asdict
import json
from multiprocessing import Pool
import os
from pathlib import Path
import sys

from vessel_reconstruction.structure import block_eval, ocx
from vessel_reconstruction.structure.block3d import VIEWS, build_block

DATA = Path("/Users/jonathanjie/Documents/workspace/MarinaFrame/work")
STAGING = DATA / "midship-tranche3"
LOOSE = DATA / "midship-remainder" / "loose"
OCX_SCHEMA = DATA / "sources" / "ocx_schema" / "ocx" / "ocx_301"
VLCC_SAMPLE = DATA / "sources" / "ocx_models_platform" / "models" / "D-VLCC_1-HOLD-OCX-simple_v3.3docx"
OUT = Path("work/steel-t3")

# Fixed in the plan, section 2, before any run: all covered designs minus the W3 sealed test split.
SAMPLE = {
    ("Repaired", "bulk_carrier"): (558, 5343, 5344, 5485, 5608, 5609, 5661, 5702, 5714, 5779, 5782, 5994,
                                   6180, 6232),
    ("Repaired", "container_ship"): (751, 755, 945, 950, 984, 5412, 5424, 5530, 5540, 5805, 5856, 5857, 5918,
                                     6110, 6114, 6115, 6205),
    ("Repaired", "tanker"): (564, 585, 685, 707, 861, 938, 5210, 5211, 5250, 5337, 5360, 5512, 5581, 5595,
                             5670, 5681, 5802, 5934, 5950, 6170),
    ("SGLD", "bulk_carrier"): (1, 15, 36, 43, 103, 131, 132, 136, 139, 140, 153, 156, 164, 182, 216, 217,
                               223, 234, 236, 239, 243, 246, 252, 255, 258, 285, 286, 356, 364, 368, 371,
                               390, 394, 397, 399, 415, 421, 422, 434, 438, 443, 449, 457, 463, 481, 485),
    ("SGLD", "container_ship"): (11, 20, 31, 39, 47, 102, 105, 110, 141, 143, 163, 175, 177, 180, 190, 199,
                                 221, 226, 293, 297, 303, 309, 314, 324, 332, 339, 348, 349, 357, 360, 377,
                                 388, 389, 405, 408, 409, 411, 432, 440, 452, 455, 459, 460, 475, 482),
    ("SGLD", "tanker"): (22, 29, 121, 122, 145, 152, 154, 169, 187, 188, 193, 195, 207, 219, 224, 232, 233,
                         242, 247, 249, 250, 266, 269, 277, 283, 294, 299, 329, 334, 335, 337, 342, 378, 384,
                         387, 395, 403, 420, 425, 428, 446, 450, 454, 478, 479),
}
FILE_PREFIX = {"SGLD": "sgld_design_", "Repaired": "repaired_random_design_design_"}
SUBSET_DIR = {"SGLD": "SGLD_Gen_Structures", "Repaired": "Repaired_Structures"}
# Below this share of BOM objects found in the IGES the CAD and BOM are not the same design (plan section 1).
IDENTITY_MIN_JOIN = 0.5


def staging_iges() -> dict[tuple[str, int], Path]:
    paths = {}
    with open(STAGING / "plan_dev.jsonl") as handle:
        for line in handle:
            row = json.loads(line)
            if row["modality"] == "cad_igs_full":
                paths[(row["subset"], int(row["design_id"]))] = STAGING / "staging" / "dev" / row["path"]
    return paths


def loose_file(subset: str, design: int, suffix: str) -> Path:
    name = f"{FILE_PREFIX[subset]}{design}_{suffix}"
    matches = sorted((LOOSE / SUBSET_DIR[subset]).rglob(name))
    if len(matches) != 1:
        raise FileNotFoundError(f"{subset} {design}: {len(matches)} files named {name}")
    return matches[0]


def design_inputs(subset: str, design: int, iges: dict) -> tuple[dict[str, Path], Path, Path]:
    sheets = {key: loose_file(subset, design, f"{view}.pdf") for key, view in VIEWS.items()}
    return sheets, iges[(subset, design)], loose_file(subset, design, "Structural_Elements.csv")


def cached_truth(subset: str, design: int, igs: Path, bom: Path) -> tuple[list, float]:
    """Truth members (cached under work/) and the share of BOM objects found in the IGES."""
    cache = OUT / "truth" / f"{subset}_{design}.json"
    if cache.exists():
        record = json.loads(cache.read_text())
        members = [block_eval.TruthMember(**{**m, "box": tuple(m["box"])}) for m in record["members"]]
        return members, record["join_rate"]
    members = block_eval.load_truth(igs, bom)
    with open(bom, newline="") as handle:
        objects = {row["struct_rsObject"] for row in csv.DictReader(handle)}
    join_rate = len(members) / len(objects) if objects else 0.0
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps({"join_rate": join_rate, "members": [asdict(m) for m in members]}))
    return members, join_rate


def run_design(task: tuple) -> dict:
    subset, ship_type, design, iges, label, with_ocx = task
    key = f"{subset}/{ship_type}/{design}"
    record: dict = {"key": key, "subset": subset, "ship_type": ship_type, "design": design}
    sheets, igs, bom = design_inputs(subset, design, iges)
    truth, record["join_rate"] = cached_truth(subset, design, igs, bom)
    try:
        block = build_block(sheets)
    except ValueError as error:
        record["build_error"] = str(error)
        return record
    blocks = OUT / label / "blocks"
    blocks.mkdir(parents=True, exist_ok=True)
    (blocks / f"{subset}_{design}.json").write_text(json.dumps(block))
    record["score"] = block_eval.score_design(block, truth)
    if with_ocx:
        path = OUT / label / "ocx" / f"{subset}_{design}_DRAFT.3docx"
        path.parent.mkdir(parents=True, exist_ok=True)
        ocx.export_ocx(block, path, name=f"{subset} {design} cargo-hold block (draft)")
        check = ocx.validate(path, OCX_SCHEMA)
        record["ocx"] = {"schema_valid": check.valid, "schema_errors": check.errors[:3],
                         "round_trip": ocx.round_trip(block, path)}
        path.unlink()  # keep only the check; the files are large
    return record


def summarise_records(records: list[dict]) -> dict | None:
    scored = {r["key"]: r["score"] for r in records if "score" in r}
    if not scored:
        return None
    summary = block_eval.summarise(scored)
    summary["n_designs"] = len(scored)
    return summary


def ocx_summary(records: list[dict]) -> dict:
    checks = [r["ocx"] for r in records if "ocx" in r]
    if not checks:
        return {"run": False}
    equal = [c["round_trip"] for c in checks]
    return {"run": True, "n": len(checks), "schema_valid": sum(c["schema_valid"] for c in checks),
            "round_trip_all_equal": sum(bool(rt["all_equal"]) for rt in equal),
            "first_errors": [c["schema_errors"] for c in checks if not c["schema_valid"]][:3]}


def vlcc_check() -> dict:
    if not VLCC_SAMPLE.exists():
        return {"run": False, "reason": "VLCC sample not on disk"}
    plates = ocx.read_plates(VLCC_SAMPLE)
    return {"run": True, "plates": len(plates),
            "with_thickness": sum(1 for p in plates if p.thickness_m is not None)}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--label", required=True, help="run name, e.g. baseline or fix1")
    parser.add_argument("--ocx", action="store_true", help="OCX export, schema check and round trip per block")
    parser.add_argument("--designs", nargs="*", help="subset/id keys for a smoke run (default: whole sample)")
    parser.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 2))
    args = parser.parse_args(argv)
    iges = staging_iges()
    tasks = [(subset, ship_type, design, iges, args.label, args.ocx)
             for (subset, ship_type), designs in SAMPLE.items() for design in designs
             if not args.designs or f"{subset}/{design}" in args.designs]
    with Pool(args.workers) as pool:
        records = pool.map(run_design, tasks, chunksize=1)
    identity_fail = [r["key"] for r in records if r["join_rate"] < IDENTITY_MIN_JOIN]
    kept = [r for r in records if r["key"] not in identity_fail]
    cells = {}
    for subset, ship_type in SAMPLE:
        cells[f"{subset}/{ship_type}"] = summarise_records(
            [r for r in kept if (r["subset"], r["ship_type"]) == (subset, ship_type)])
    report = {
        "engineering_approved": False, "label": args.label, "n_designs": len(records),
        "build_errors": {r["key"]: r["build_error"] for r in records if "build_error" in r},
        "identity": {"excluded_below_0.5": identity_fail,
                     "below_0.95": {r["key"]: round(r["join_rate"], 4) for r in records if r["join_rate"] < 0.95}},
        "pooled": summarise_records(kept),
        "subsets": {s: summarise_records([r for r in kept if r["subset"] == s]) for s in ("Repaired", "SGLD")},
        "cells": cells,
        "ocx": ocx_summary(kept), "vlcc_parser": vlcc_check() if args.ocx else {"run": False},
        "per_design": {r["key"]: {"join_rate": round(r["join_rate"], 4),
                                  **({k: r["score"][k] for k in ("n_pred", "n_true", "tp", "longitudinal",
                                                                 "transverse", "volume_rel_error", "labels")}
                                     if "score" in r else {"build_error": r.get("build_error")})}
                       for r in records},
    }
    path = OUT / args.label / "report.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=1))
    print(f"{len(records)} designs, {len(report['build_errors'])} build errors -> {path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
