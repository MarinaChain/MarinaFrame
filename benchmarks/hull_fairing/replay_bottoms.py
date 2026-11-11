"""Replay stored phase-1 readings through the complete first-hull path.

Run once with the baseline src directory on PYTHONPATH and once with the fix.
No model calls, images, fairing, or sealed evaluation inputs are required.
"""
from __future__ import annotations

import argparse
import copy
import json
import os
from pathlib import Path
from uuid import uuid4

from benchmarks.hull_fairing.replay import WORK, ROUNDS, BUE_GIRL_CASE, bue_girl_score, factory_score
from vessel_reconstruction.agent_tools import DomainTools
from vessel_reconstruction.first_hull_tools import build_first_hull


def replay(case: Path, destination: Path) -> dict:
    saved = json.loads((case / "task/domain/state.json").read_text())
    tools = DomainTools(destination, case / "intake/run-input/spec.json")
    for key in ("sheet_setups", "described_views"):
        tools.state[key] = copy.deepcopy(saved[key])
    tools._save()
    # Re-measure the saved model description with the same source and setups.
    description = saved["vessel_description"]
    tools._describe_vessel(copy.deepcopy(description.get("model_description", description)))
    observation = build_first_hull(tools)
    if not observation.get("ok"):
        raise RuntimeError(f"{case.name}: {observation}")
    candidate = tools.state["last_valid_candidate"]
    build = destination / candidate["path"]
    record = json.loads((build / "result.json").read_text())
    if case == BUE_GIRL_CASE:
        rows = tools.state["vessel_table"]["stations"]
        score = bue_girl_score(rows)
    else:
        step = build / record["exports"]["step"]
        score = factory_score(case.name, step)
    return {"case": case.name, "score": score, "build": str(build),
            "left_out_anchor_ids": observation.get("left_out_anchor_ids", []),
            "station_count": len(tools.state["vessel_table"]["stations"])}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--tasks", type=Path, required=True)
    parser.add_argument("--cases", nargs="*")
    parser.add_argument("--resume", action="store_true", help="keep completed results in --out")
    args = parser.parse_args()
    os.environ.pop("MARINAFRAME_HULL_FAIRING", None)
    cases = [BUE_GIRL_CASE] + [p for r in ROUNDS for p in sorted((WORK / r).glob("*-L?"))]
    if args.cases:
        cases = [p for p in cases if p.name in args.cases]
    args.out.parent.mkdir(parents=True, exist_ok=True)
    results = json.loads(args.out.read_text())["rows"] if args.resume and args.out.exists() else []
    completed = {row["case"] for row in results}
    for case in cases:
        if case.name in completed:
            continue
        destination = args.tasks / case.name
        if destination.exists():
            # An interrupted build is not a clean phase-1 reading. Keep it for
            # diagnosis and start a new task instead of reusing its state.
            destination = args.tasks / f"{case.name}-{uuid4().hex[:8]}"
        result = replay(case, destination)
        results.append(result)
        args.out.write_text(json.dumps({"rows": results, "fairing": False,
                                        "engineering_approved": False}, indent=2))
        print(json.dumps(result), flush=True)


if __name__ == "__main__":
    main()
