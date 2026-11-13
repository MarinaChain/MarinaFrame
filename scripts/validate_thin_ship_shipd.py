#!/usr/bin/env python3
"""Reproducible local Ship-D comparison. Never vendor dataset rows into git."""
import argparse
import csv
import hashlib
import json
from pathlib import Path
import importlib.util
import math
import sys
import time

import numpy as np

# -I removes the working directory; import only this repository's source tree.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from vessel_reconstruction.resistance_thin_ship import HullOffsets, wave_resistance

SEED = "20261114"
DRAFTS = (0.25, 0.33, 0.5, 0.67)
FROUDES = (0.1, 0.15, 0.2, 0.25, 0.3, 0.35, 0.4, 0.45)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def select_ids(subset, count, excluded, size=100):
    eligible = [f"shipd-{subset}-{row:05d}" for row in range(count)
                if f"shipd-{subset}-{row:05d}" not in excluded]
    if len(eligible) < size:
        raise ValueError("Insufficient eligible hulls")
    return sorted(eligible, key=lambda value: hashlib.sha256(
        f"{SEED}:{value}".encode()).digest())[:size]


def subset_path(source, subset):
    return source / "data/Ship_D_Dataset" / f"Constrained_Randomized_Set_{subset}"


def freeze(source, exclusions, output):
    excluded = set(exclusions.read_text().splitlines())
    selected = []
    sources = {}
    populations = {}
    for subset in (1, 2, 3):
        table = subset_path(source, subset) / "Input_Vectors.csv"
        with table.open() as stream:
            reader = csv.reader(stream)
            next(reader)
            count = sum(1 for _ in reader)
        selected.extend(select_ids(subset, count, excluded))
        sources[str(table.relative_to(source))] = digest(table)
        populations[str(subset)] = count
    for name in ("HullParameterization.py", "ModifiedMichellCw.py",
                 "Compute_Dataset_Entirety.ipynb"):
        sources[f"code/{name}"] = digest(source / "code" / name)
    manifest = {"seed": SEED, "ids": selected, "populations": populations,
                "sample_sha256": hashlib.sha256("\n".join(selected).encode()).hexdigest(),
                "exclusions_sha256": digest(exclusions), "sources": sources,
                "drafts": DRAFTS, "froudes": FROUDES,
                "gate_percent": {"median": 3, "p90": 10},
                "conditions": 9600}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps({key: manifest[key] for key in
                      ("sample_sha256", "populations", "exclusions_sha256", "sources")}, indent=2))


def cw_from_rw(rw, speed, loa):
    return rw / (0.5 * 1000 * speed**2 * loa**2)


def relative_error(calculated, reference):
    if calculated is None or not math.isfinite(calculated) or not math.isfinite(reference) or reference <= 0:
        return None
    return 100 * abs(calculated - reference) / abs(reference)


def summarize_errors(errors, expected):
    if len(errors) > expected or expected <= 0:
        raise ValueError("Invalid condition denominator")
    values = [float(v) if v is not None and math.isfinite(v) else math.inf for v in errors]
    values.extend([math.inf] * (expected - len(values)))
    values.sort()

    def percentile(fraction):
        position = fraction * (expected - 1)
        low, high = values[math.floor(position)], values[math.ceil(position)]
        if not math.isfinite(high):
            return None
        return low + (high - low) * (position % 1)

    median, p90 = percentile(0.5), percentile(0.9)
    return {"conditions": expected, "finite_conditions": sum(math.isfinite(v) for v in values),
            "median_percent": median, "p90_percent": p90,
            "gate_pass": median is not None and p90 is not None and median <= 3 and p90 <= 10}


def evaluate_offsets(x, z, y, wl, loa, fn, angle_count=512, lambda_max=24):
    start = time.perf_counter()
    try:
        speed = fn * math.sqrt(9.81 * wl)
        hull = HullOffsets(x, z, y, float(-z[0]), loa**2, ("Ship-D local parameterisation",))
        result = wave_resistance(hull, speed_m_s=speed, angle_count=angle_count, lambda_max=lambda_max)
        return {"cw": result.cw.value, "rw_n": result.rw.value,
                "elapsed_ms": 1000 * (time.perf_counter() - start), "error": None}
    except (ValueError, ArithmeticError) as error:
        return {"cw": None, "rw_n": None, "elapsed_ms": 1000 * (time.perf_counter() - start),
                "error": str(error)}


def public_summary(summary, records):
    """Export aggregate evidence without selected IDs or per-hull measurements."""
    result = {key: value for key, value in summary.items() if key != "convergence"}
    changes = []
    for refined in summary["convergence"]:
        baseline = next(row for row in records if row["id"] == refined["id"]
                        and row["fn"] == refined["fn"] and row["draft_fraction"] == 0.5)
        change = relative_error(refined["cw"], baseline["cw"]) if baseline["cw"] is not None else None
        if change is not None:
            changes.append(change)
    result["convergence_9_conditions_percent"] = {
        "min": min(changes) if changes else None,
        "median": float(np.median(changes)) if changes else None,
        "max": max(changes) if changes else None}
    differences = [abs(row["generated_wl_m"] - row["published_wl_m"])
                   for row in records if "generated_wl_m" in row]
    timings = [row["elapsed_ms"] for row in records if "elapsed_ms" in row]
    result["diagnostics"] = {
        "max_wl_difference_m": max(differences) if differences else None,
        "median_evaluation_ms": float(np.median(timings)) if timings else None,
        "conditions_over_10_percent_or_failed": sum(
            row["error_percent"] is None or row["error_percent"] > 10 for row in records)}
    return result


def selected_rows(path, indices):
    """Read selected rows only; never parse excluded hull geometry or values."""
    result = {}
    with path.open() as stream:
        reader = csv.reader(stream)
        next(reader)
        for index, row in enumerate(reader):
            if index in indices:
                result[index] = np.asarray(row, dtype=float)
    if result.keys() != set(indices):
        raise ValueError("Selected rows missing")
    return result


def run(source, exclusions, manifest_path, output, limit):
    manifest = json.loads(manifest_path.read_text())
    excluded = set(exclusions.read_text().splitlines())
    if digest(exclusions) != manifest["exclusions_sha256"] or set(manifest["ids"]) & excluded:
        raise ValueError("Exclusions changed or selected excluded ID")
    if hashlib.sha256("\n".join(manifest["ids"]).encode()).hexdigest() != manifest["sample_sha256"]:
        raise ValueError("Sample digest mismatch")
    for name, expected in manifest["sources"].items():
        if digest(source / name) != expected:
            raise ValueError(f"Source changed: {name}")
    geometry_path = source / "code/HullParameterization.py"
    spec = importlib.util.spec_from_file_location("shipd_geometry", geometry_path)
    geometry = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(geometry)
    ids = manifest["ids"][:limit]
    tables = {}
    reference_hashes = {}
    for subset in (1, 2, 3):
        indices = {int(value.rsplit("-", 1)[1]) for value in ids if value.startswith(f"shipd-{subset}-")}
        if not indices:
            continue
        root = subset_path(source, subset)
        tables[subset] = {}
        for name, path in (("inputs", root / "Input_Vectors.csv"),
                           ("cw", root / "GeometricMeasures/Cw.csv"),
                           ("wl", root / "GeometricMeasures/WL_Length.csv")):
            tables[subset][name] = selected_rows(path, indices)
            reference_hashes[str(path.relative_to(source))] = digest(path)
        rw_files = sorted((root / "GeometricMeasures").glob("Rw_Output*.npy"))
        if len(rw_files) == 1:
            tables[subset]["rw"] = np.load(rw_files[0], mmap_mode="r", allow_pickle=False)
            reference_hashes[str(rw_files[0].relative_to(source))] = digest(rw_files[0])
    output.mkdir(parents=True, exist_ok=True)
    trace = output / "trace.jsonl"
    if trace.exists():
        raise ValueError("Trace already exists; preserve earlier attempts")
    records = []
    convergence = []
    with trace.open("x") as stream:
        for hull_index, identifier in enumerate(ids):
            _, subset, row = identifier.split("-")
            subset, row = int(subset), int(row)
            table = tables[subset]
            vector = table["inputs"][row]
            shape = {"subset": subset, "bow_bulb": bool(vector[31]), "stern_bulb": bool(vector[32]),
                     "slenderness_band": "<5" if 1/vector[3] < 5 else "5-10" if 1/vector[3] < 10 else ">=10"}
            try:
                hull = geometry.Hull_Parameterization(vector)
                hull_error = None
            except Exception as error:
                hull_error = f"{type(error).__name__}: {error}"
            for draft_index, draft in enumerate(DRAFTS):
                geometry_error = hull_error
                if not geometry_error:
                    try:
                        x, z, y, wl = hull.gen_PC_for_Cw(hull.Dd*draft, NUM_WL=51, PointsPerWL=301)
                        open_ends = bool(np.any(y[[0, -1]] != 0))
                    except Exception as error:
                        geometry_error = f"{type(error).__name__}: {error}"
                for speed_index, fn in enumerate(FROUDES):
                    condition = draft_index * 8 + speed_index
                    reference = float(table["cw"][row][condition])
                    record = {"id": identifier, **shape, "draft_fraction": draft, "fn": fn,
                              "reference_cw": reference}
                    if geometry_error:
                        record.update(cw=None, error=geometry_error, open_ends=None)
                    else:
                        record.update(evaluate_offsets(x, z, y, wl, hull.LOA, fn))
                        record.update(open_ends=open_ends, generated_wl_m=float(wl),
                                      published_wl_m=float(table["wl"][row][(1, 2, 4, 6)[draft_index]] * hull.LOA))
                        if "rw" in table:
                            record["rw_implied_cw"] = cw_from_rw(float(table["rw"][row, condition]),
                                                                  fn*math.sqrt(9.81*wl), hull.LOA)
                    record["error_percent"] = relative_error(record["cw"], reference)
                    records.append(record)
                    stream.write(json.dumps(record, allow_nan=False) + "\n")
                    stream.flush()
                if not geometry_error and hull_index < 3 and draft == 0.5:
                    for fn in (0.1, 0.3, 0.45):
                        refined_x, refined_z, refined_y, refined_wl = hull.gen_PC_for_Cw(
                            hull.Dd*draft, NUM_WL=101, PointsPerWL=601)
                        convergence.append({"id": identifier, "fn": fn,
                                            **evaluate_offsets(refined_x, refined_z, refined_y,
                                                               refined_wl, hull.LOA, fn, 1024, 48)})
            print(json.dumps({"completed_hulls": hull_index+1, "conditions": len(records),
                              "finite": sum(r["error_percent"] is not None for r in records)}), flush=True)
    summary = {"sample_sha256": manifest["sample_sha256"], "reference_sha256": reference_hashes,
               "status": "review_required", "engineering_approved": False,
               "primary": summarize_errors([r["error_percent"] for r in records], len(ids)*32),
               "complete_case": None, "groups": {}, "convergence": convergence}
    finite = [r["error_percent"] for r in records if r["error_percent"] is not None]
    if finite:
        summary["complete_case"] = summarize_errors(finite, len(finite))
    for field in ("subset", "bow_bulb", "stern_bulb", "slenderness_band", "open_ends"):
        summary["groups"][field] = {}
        for value in sorted({str(r[field]) for r in records}):
            group = [r["error_percent"] for r in records if str(r[field]) == value]
            summary["groups"][field][value] = summarize_errors(group, len(group))
    (output / "summary.json").write_text(json.dumps(summary, indent=2, allow_nan=False) + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["freeze", "run", "export"])
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--exclusions", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--limit", type=int, choices=[3, 300], default=300)
    args = parser.parse_args()
    if args.mode == "freeze":
        freeze(args.source, args.exclusions, args.manifest)
    elif args.mode == "run":
        if args.output is None:
            parser.error("run requires --output")
        run(args.source, args.exclusions, args.manifest, args.output, args.limit)
    else:
        if args.output is None:
            parser.error("export requires --output (aggregate file)")
        summary = json.loads((args.source / "summary.json").read_text())
        records = [json.loads(line) for line in (args.source / "trace.jsonl").read_text().splitlines()]
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(public_summary(summary, records), indent=2, allow_nan=False) + "\n")


if __name__ == "__main__":
    main()
