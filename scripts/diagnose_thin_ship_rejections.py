#!/usr/bin/env python3
"""Inspect failed offsets from the two explicitly authorised development cohorts."""
import json
from pathlib import Path
import sys
from collections import Counter

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from investigate_thin_ship_bulbs import load_module
from validate_thin_ship_shipd import selected_rows, subset_path


def run(source, work):
    manifests = [json.loads((work/name).read_text()) for name in ("sample.json", "gate2-sample.json")]
    allowed = set(manifests[0]["ids"]) | set(manifests[1]["ids"])
    if len(allowed) != 600:
        raise ValueError("Expected exactly 600 authorised development IDs")
    geometry = load_module("shipd_geometry", source/"code/HullParameterization.py")
    output = work/"rejection-diagnosis"
    output.mkdir(exist_ok=True)
    evidence = []
    for cohort, folder in (("original", "full"), ("gate2", "gate2")):
        failures = {}
        for line in (work/folder/"trace.jsonl").read_text().splitlines():
            row = json.loads(line)
            if row["id"] not in allowed:
                raise ValueError("Unauthorised ID")
            if row["error_percent"] is None:
                key = (row["id"], row.get("draft", row.get("draft_fraction")))
                failures[key] = failures.get(key, 0)+1
        for (identifier, draft), count in failures.items():
            _, subset, index = identifier.split("-")
            vector = selected_rows(subset_path(source, int(subset))/"Input_Vectors.csv", {int(index)})[int(index)]
            hull = geometry.Hull_Parameterization(vector)
            x, z, y, wl = hull.gen_PC_for_Cw(hull.Dd*draft, NUM_WL=51, PointsPerWL=301)
            negative = np.argwhere(y < 0)
            nonfinite = np.argwhere(~np.isfinite(y))
            cause = ("negative_half_breadths" if len(negative) else "nonfinite_half_breadths"
                     if len(nonfinite) else "shape" if y.shape != (len(x), len(z))
                     else "nonmonotonic_grid" if np.any(np.diff(x) <= 0) or np.any(np.diff(z) <= 0)
                     else "open_ends" if np.any(y[[0, -1]] != 0) else "other")
            record = {"cohort": cohort, "id": identifier, "draft": draft, "conditions": count,
                      "cause": cause, "negative_count": len(negative), "nonfinite_count": len(nonfinite),
                      "minimum_breadth_m": float(np.min(y)), "maximum_breadth_m": float(np.max(y)),
                      "negative_waterline_count": int(np.sum(y[:, -1] < 0)),
                      "open_ends": bool(np.any(y[[0, -1]] != 0)),
                      "negative_locations": negative.tolist()}
            evidence.append(record)
    (output/"evidence.json").write_text(json.dumps(evidence, indent=2)+"\n")
    summary = {}
    for cohort in ("original", "gate2"):
        group = [r for r in evidence if r["cohort"] == cohort]
        summary[cohort] = {"hull_draft_grids": len(group),
            "conditions_by_cause": dict(sum((Counter({r["cause"]: r["conditions"]}) for r in group), Counter())),
            "negative_values": sum(r["negative_count"] for r in group),
            "minimum_breadth_m": min(r["minimum_breadth_m"] for r in group),
            "open_end_grids": sum(r["open_ends"] for r in group),
            "nonfinite_values": sum(r["nonfinite_count"] for r in group)}
    (output/"summary.json").write_text(json.dumps(summary, indent=2)+"\n")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--work", type=Path, required=True)
    args = parser.parse_args()
    run(args.source, args.work)
