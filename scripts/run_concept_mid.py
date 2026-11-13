#!/usr/bin/env python3
"""Freeze public-fleet metadata, then run the committed G2-mid gate once.

Third-party inputs and numeric outputs belong only in an ignored evidence folder.
Run with Python -I; source code is loaded from this repository, never the data path.
"""
from __future__ import annotations

import argparse
from collections import Counter
import csv
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
BANDS = ((70000, 85000), (85000, 110000), (110000, 125000), (125000, 170001))
GRADE = {"primary": 0, "secondary": 1, "copied": 2}
FIELDS = {"lpp": "lpp_m", "beam": "beam_m", "depth": "depth_m",
          "draft": "draft_summer_m", "cb": "cb"}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_new(path: Path, record: dict) -> None:
    with path.open("x") as stream:
        json.dump(record, stream, indent=2, sort_keys=True)
        stream.write("\n")


def dwt(row: dict) -> float:
    return float(row["dwt_summer_t"])


def rank(row: dict) -> tuple:
    return GRADE[row["source_grade"]], row["imo"], row["row_id"]


def sister(a: dict, b: dict) -> bool:
    if a["design_id"] == b["design_id"] or a["imo"] == b["imo"]:
        return True
    return (abs(float(a["lpp_m"]) - float(b["lpp_m"])) <= 1.0
            and abs(float(a["beam_m"]) - float(b["beam_m"])) <= 0.100000001
            and abs(float(a["depth_m"]) - float(b["depth_m"])) <= 0.100000001
            and abs(dwt(a) - dwt(b)) / min(dwt(a), dwt(b)) <= 0.02)


def freeze(source: Path, evidence: Path) -> None:
    with source.open() as stream:
        rows = [row for row in csv.DictReader(stream)
                if row["complete_for_concept_fit"].lower() == "true"
                and 70000 <= dwt(row) <= 170000]
    # Connected components conservatively join same-design and geometric sisters.
    groups = []
    remaining = sorted(rows, key=rank)
    while remaining:
        group = [remaining.pop(0)]
        while True:
            joined = [row for row in remaining if any(sister(row, member) for member in group)]
            if not joined:
                break
            group.extend(joined)
            remaining = [row for row in remaining if row not in joined]
        groups.append(group)
    representatives = [min(group, key=rank) for group in groups]
    selected = []
    for low, high in BANDS:
        candidates = [row for row in representatives if low <= dwt(row) < high]
        if not candidates:
            raise ValueError("no independent candidate in a frozen size band")
        midpoint = (low + min(high, 170000)) / 2
        selected.append(min(candidates, key=lambda row: (
            GRADE[row["source_grade"]], abs(dwt(row) - midpoint), row["imo"], row["row_id"])))
    excluded = {row["row_id"] for group in groups if any(row in group for row in selected)
                for row in group}
    training = [row for row in representatives if row["row_id"] not in excluded]
    assert len(training) >= 10
    assert min(map(dwt, training)) <= min(map(dwt, selected))
    assert max(map(dwt, training)) >= max(map(dwt, selected))
    assert any(row["segment"] == "Aframax/LR2" for row in selected)
    evidence.mkdir(parents=True, exist_ok=True)
    write_new(evidence / "freeze.json", {
        "gate": "G2-mid", "source_sha256": digest(source),
        "runner_sha256": digest(Path(__file__)), "rows": rows,
        "groups": [[row["row_id"] for row in group] for group in groups],
        "selected": selected, "training": training, "excluded_row_ids": sorted(excluded),
        "capacity_used": False, "speed_used": False,
        "quantity_gate": ["lpp", "beam", "draft", "cb"], "required_joint_coverage": 1.0,
    })
    print(json.dumps({"eligible_rows": len(rows), "derived_designs": len({r['design_id'] for r in rows}),
                      "clusters": len(groups), "training_clusters": len(training),
                      "excluded_rows": len(excluded), "selected_grades": dict(Counter(r['source_grade'] for r in selected))}))


def score(evidence: Path) -> None:
    frozen = json.loads((evidence / "freeze.json").read_text())
    assert digest(Path(__file__)) == frozen["runner_sha256"]
    assert not subprocess.check_output(["git", "status", "--porcelain", "--untracked-files=normal"], cwd=ROOT).strip()
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    # Exclusive attempt marker survives any failure: no automatic second fit/score.
    write_new(evidence / "attempt.json", {"commit": commit, "freeze_sha256": digest(evidence / "freeze.json")})
    sys.path.insert(0, str(ROOT / "src"))
    from vessel_reconstruction.concept_dimensions import FleetModel, FleetShip, Requirements

    def ship(row: dict) -> FleetShip:
        return FleetShip(ship_id=row["imo"], design_id=row["row_id"], dwt_t=dwt(row),
                         lpp_m=float(row["lpp_m"]), beam_m=float(row["beam_m"]),
                         depth_m=float(row["depth_m"]), draft_m=float(row["draft_summer_m"]),
                         cb=float(row["cb"]), sources=(row["source_url"],))

    model = FleetModel.fit(ship(row) for row in frozen["training"])
    results = []
    for row in frozen["selected"]:
        proposal = model.propose(Requirements(dwt_t=dwt(row)))
        quantities = {}
        for name, field in FIELDS.items():
            interval = proposal.dimensions[name]
            actual = float(row[field])
            quantities[name] = {**asdict(interval), "actual": actual,
                                "covered": interval.lower <= actual <= interval.upper,
                                "error_pct": 100 * (interval.value / actual - 1)}
        results.append({"row_id": row["row_id"], "grade": row["source_grade"],
                        "quantities": quantities, "warnings": proposal.warnings,
                        "joint_pass": all(quantities[key]["covered"] for key in frozen["quantity_gate"])})
    write_new(evidence / "result.json", {
        "commit": commit, "fit_count": 1, "proposal_count": len(results),
        "coefficients": model.coefficients, "log_bands": model.log_bands,
        "training_grades": dict(Counter(row["source_grade"] for row in frozen["training"])),
        "results": results, "engineering_approved": False,
    })
    print(json.dumps({"joint_pass": sum(row["joint_pass"] for row in results), "total": len(results)}))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("freeze", "score"))
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--source", type=Path)
    args = parser.parse_args()
    if args.mode == "freeze":
        if args.source is None:
            parser.error("freeze requires --source")
        freeze(args.source, args.evidence)
    else:
        score(args.evidence)


if __name__ == "__main__":
    main()
