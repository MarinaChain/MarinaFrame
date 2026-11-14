#!/usr/bin/env python3
"""Reference convergence for commissioning a numerical Michell comparison."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import sys

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from investigate_thin_ship_bulbs import load_module, reference_rw
from validate_thin_ship_shipd import digest, selected_rows, subset_path


def convergence_summary(rows):
    result = {}
    selected = None
    for low, high in ((161, 321), (321, 641)):
        changes = []
        for row in rows:
            a, b = row[str(low)], row[str(high)]
            changes.append(100*abs(a-b)/abs(b) if a is not None and b is not None
                           and math.isfinite(a) and math.isfinite(b) and b > 0 else math.inf)
        values = sorted(changes)
        position = .9*(len(values)-1)
        lower, upper = values[math.floor(position)], values[math.ceil(position)]
        p90 = lower+(upper-lower)*(position % 1) if math.isfinite(upper) else None
        result[f"{low}_to_{high}"] = {"conditions": len(values),
            "finite": sum(math.isfinite(v) for v in values), "p90_change_percent": p90,
            "median_change_percent": float(np.median(values)),
            "max_change_percent": max(values) if math.isfinite(max(values)) else None}
        if selected is None and p90 is not None and p90 < .1:
            selected = low
    return {"pairs": result, "selected_angle_count": selected,
            "criterion": "p90 change to next level strictly below 0.1 percent"}


def run(args):
    manifest = json.loads(args.manifest.read_text())
    if hashlib.sha256("\n".join(manifest["ids"]).encode()).hexdigest() != manifest["sample_sha256"]:
        raise ValueError("Development sample digest mismatch")
    excluded = set(args.exclusions.read_text().splitlines())
    if excluded.intersection(manifest["ids"]):
        raise ValueError("Development sample intersects exclusions; request PM clarification")
    for name, expected in manifest["sources"].items():
        if digest(args.source/name) != expected:
            raise ValueError(f"Source changed: {name}")
    geometry = load_module("shipd_geometry", args.source/"code/HullParameterization.py")
    args.output.mkdir(parents=True, exist_ok=True)
    rows = []
    with (args.output/"convergence.jsonl").open("x") as stream:
        for subset in (1, 2, 3):
            ids = [i for i in manifest["ids"] if i.startswith(f"shipd-{subset}-")]
            vectors = selected_rows(subset_path(args.source, subset)/"Input_Vectors.csv",
                                    {int(i.rsplit("-", 1)[1]) for i in ids})
            for identifier in ids:
                hull = geometry.Hull_Parameterization(vectors[int(identifier.rsplit("-", 1)[1])])
                for draft in manifest["drafts"]:
                    x, z, y, wl = hull.gen_PC_for_Cw(hull.Dd*draft, NUM_WL=51, PointsPerWL=301)
                    for fn in manifest["froudes"]:
                        speed = fn*math.sqrt(9.81*wl)
                        row = {"id": identifier, "draft": draft, "fn": fn}
                        for count in (161, 321, 641):
                            cw = reference_rw(y, speed, x, z, count)/(.5*1000*speed**2*hull.LOA**2)
                            row[str(count)] = cw if math.isfinite(cw) else None
                        stream.write(json.dumps(row, allow_nan=False)+"\n")
                        stream.flush()
                        rows.append(row)
                print(json.dumps({"completed_hulls": len(rows)//32}), flush=True)
    summary = convergence_summary(rows)
    summary.update(development_sample_sha256=manifest["sample_sha256"],
                   exclusions_sha256=digest(args.exclusions), status="review_required",
                   engineering_approved=False)
    (args.output/"summary.json").write_text(json.dumps(summary, indent=2, allow_nan=False)+"\n")
    print(json.dumps(summary), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("source", "exclusions", "manifest", "output"):
        parser.add_argument("--"+name, type=Path, required=True)
    run(parser.parse_args())
