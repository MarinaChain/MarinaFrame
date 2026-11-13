#!/usr/bin/env python3
"""Reproducible local Ship-D comparison. Never vendor dataset rows into git."""
import argparse
import csv
import hashlib
import json
from pathlib import Path

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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["freeze"])
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--exclusions", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args()
    freeze(args.source, args.exclusions, args.manifest)


if __name__ == "__main__":
    main()
