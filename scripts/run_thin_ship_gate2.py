#!/usr/bin/env python3
"""Frozen G-TS-SHIPD2 selection and one-shot numerical scoring."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import sys

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from investigate_thin_ship_bulbs import load_module, reference_rw
from validate_thin_ship_shipd import (digest, selected_rows, subset_path,
                                    evaluate_offsets, relative_error, summarize_errors)

SEED = "G-TS-SHIPD2-20261114"


def select_fresh(old, excluded):
    blocked = set(old) | set(excluded)
    ids = []
    for subset in (1, 2, 3):
        eligible = [f"shipd-{subset}-{index:05d}" for index in range(10000)
                    if f"shipd-{subset}-{index:05d}" not in blocked]
        if len(eligible) < 100:
            raise ValueError("Insufficient eligible IDs")
        ids.extend(sorted(eligible, key=lambda i: hashlib.sha256(f"{SEED}:{i}".encode()).digest())[:100])
    return ids


def main(args):
    old = json.loads(args.development.read_text())
    if args.mode == "freeze":
        ids = select_fresh(old["ids"], args.exclusions.read_text().splitlines())
        manifest = {**old, "ids": ids, "seed": SEED, "gate": "G-TS-SHIPD2",
                    "reference_angles": 321, "exclusions_sha256": digest(args.exclusions),
                    "sample_sha256": hashlib.sha256("\n".join(ids).encode()).hexdigest()}
        args.manifest.parent.mkdir(parents=True, exist_ok=True)
        with args.manifest.open("x") as stream:
            json.dump(manifest, stream, indent=2)
        print(json.dumps({k: manifest[k] for k in ("sample_sha256", "exclusions_sha256")}))
        return
    manifest = json.loads(args.manifest.read_text())
    if digest(args.exclusions) != manifest["exclusions_sha256"]:
        raise ValueError("Exclusion list changed since freeze")
    ids = manifest["ids"]
    if len(ids) != 300 or len(set(ids)) != 300 or set(ids) & (set(old["ids"]) | set(args.exclusions.read_text().splitlines())):
        raise ValueError("Fresh sample boundary failed")
    if hashlib.sha256("\n".join(ids).encode()).hexdigest() != manifest["sample_sha256"]:
        raise ValueError("Sample digest mismatch")
    for name, expected in manifest["sources"].items():
        if digest(args.source/name) != expected:
            raise ValueError(f"Source changed: {name}")
    geometry = load_module("shipd_geometry", args.source/"code/HullParameterization.py")
    args.output.mkdir(parents=True, exist_ok=True)
    records = []
    with (args.output/"trace.jsonl").open("x") as stream:
        for subset in (1, 2, 3):
            selected = [i for i in ids if i.startswith(f"shipd-{subset}-")]
            vectors = selected_rows(subset_path(args.source, subset)/"Input_Vectors.csv",
                                    {int(i.rsplit("-", 1)[1]) for i in selected})
            for identifier in selected:
                hull = geometry.Hull_Parameterization(vectors[int(identifier.rsplit("-", 1)[1])])
                for draft in manifest["drafts"]:
                    x, z, y, wl = hull.gen_PC_for_Cw(hull.Dd*draft, NUM_WL=51, PointsPerWL=301)
                    for fn in manifest["froudes"]:
                        speed = fn*math.sqrt(9.81*wl)
                        reference = reference_rw(y, speed, x, z, 321)/(.5*1000*speed**2*hull.LOA**2)
                        result = evaluate_offsets(x, z, y, wl, hull.LOA, fn)
                        row = {"id": identifier, "fn": fn, "draft": draft, **result,
                               "reference_cw": reference,
                               "error_percent": relative_error(result["cw"], reference),
                               "absolute_cw_difference": abs(result["cw"]-reference) if result["cw"] is not None else None}
                        stream.write(json.dumps(row, allow_nan=False)+"\n")
                        stream.flush()
                        records.append(row)
                print(json.dumps({"completed_hulls": len(records)//32}), flush=True)
    summary = {"gate": "G-TS-SHIPD2", "sample_sha256": manifest["sample_sha256"],
               "reference_angles": 321, "status": "review_required", "engineering_approved": False,
               "numerical_agreement_only": True,
               "primary": summarize_errors([r["error_percent"] for r in records], 9600)}
    for label, rows in (("fn_le_015_information", [r for r in records if r["fn"] <= .15]),
                        ("fn_gt_015_information", [r for r in records if r["fn"] > .15])):
        summary[label] = summarize_errors([r["error_percent"] for r in rows], len(rows))
        differences = [r["absolute_cw_difference"] for r in rows if r["absolute_cw_difference"] is not None]
        summary[label]["absolute_cw_difference_median_p90"] = np.percentile(differences, [50, 90]).tolist()
        summary[label].pop("gate_pass")
    with (args.output/"score.json").open("x") as stream:
        json.dump(summary, stream, indent=2, allow_nan=False)
    print(json.dumps(summary), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("freeze", "run"))
    for name in ("development", "exclusions", "manifest", "source", "output"):
        parser.add_argument("--"+name, type=Path, required=True)
    main(parser.parse_args())
