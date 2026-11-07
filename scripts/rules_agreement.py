"""Measure agreement between the rule checks and the MiDShip constraint tables.

Usage:
    python scripts/rules_agreement.py --midship-root work/sources/midship \\
        --out rules/agreement --full-out work/rules_agreement

The MiDShip data is licensed GPL-3.0 and is not committed. The summary and a
small set of example disagreements are written to ``--out``; the full
disagreement list goes to ``--full-out`` (git-ignored).
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

from vessel_reconstruction.rules import DEFAULT_RULE_FILE, load_rule_set
from vessel_reconstruction.rules import agreement as A
from vessel_reconstruction.rules import midship as M

EXAMPLES_PER_GROUP = 5
CSV_FIELDS = ["subset", "index", "ship_type", "column", "required", "provided",
              "ms_threshold", "ms_value", "mine_pass", "ms_pass", "cause"]


def find_boms(root: Path, subset: str):
    directory, _, _, stem = A.SUBSETS[subset]
    top = root / directory.split("/")[0]
    pattern = re.compile(re.escape(stem) + r"(\d+)_Structural_Elements\.csv")
    found = {}
    for path in top.rglob("*_Structural_Elements.csv"):
        match = pattern.fullmatch(path.name)
        if match:
            found[int(match.group(1))] = path
    return dict(sorted(found.items()))


def row_of(c: A.Comparison):
    return {k: getattr(c, k) for k in CSV_FIELDS}


def write_csv(path: Path, comparisons):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for c in comparisons:
            writer.writerow(row_of(c))


def strict_divergence(rule_set, tables_by_subset):
    """Where the strict text option changes the required value, and the result."""
    default, strict = [], []
    for tables in tables_by_subset.values():
        default += A.compare_tables(rule_set, tables, strict=False)
        strict += A.compare_tables(rule_set, tables, strict=True)
    changed = Counter()
    total = Counter()
    for d, s in zip(default, strict):
        total[d.column] += 1
        if not A.close(d.required, s.required):
            changed[d.column] += 1
    summary = A.summarize(strict)
    out = {}
    for column, n_changed in sorted(changed.items()):
        out[column] = {
            "designs_where_required_value_changes": n_changed,
            "of": total[column],
            "strict_pass_agreement_rate": summary[column]["pass_agreement_rate"],
            "strict_confusion": summary[column]["confusion"],
        }
    return out


def hatch_evidence(tables_by_subset):
    """Deck-girder threshold collapse versus the hatch-opening bit."""
    count = Counter()
    for tables in tables_by_subset.values():
        for index in tables.retained():
            row = tables.parameters[index]
            ship_type = M.ship_type_of(row)
            if ship_type in (None, "container_ship"):
                continue
            geometry = M.inputs_from_parameters(row, ship_type).geometry
            implied = tables.thresholds[index]["Deck_Beam_Depth"] / (1000.0 * 0.0833)
            collapsed = implied < 1.0e-6
            matches = A.close(implied, geometry["sp_deck_girder"])
            hatch = "hatch_bit_1" if row["Hatch Openings Bit"] == 1.0 else "hatch_bit_0"
            outcome = "collapsed" if collapsed else ("matches" if matches else "other")
            count[f"{hatch}:{outcome}"] += 1
    return dict(sorted(count.items()))


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--midship-root", type=Path, required=True)
    parser.add_argument("--out", type=Path, default=Path("rules/agreement"))
    parser.add_argument("--full-out", type=Path, default=Path("work/rules_agreement"))
    args = parser.parse_args()

    rule_set = load_rule_set()
    rule_file_sha = hashlib.sha256(Path(DEFAULT_RULE_FILE).read_bytes()).hexdigest()
    tables_by_subset = {name: A.load_tables(args.midship_root, name) for name in A.SUBSETS}

    population = []
    subset_sizes = {}
    for name, tables in tables_by_subset.items():
        population += A.compare_tables(rule_set, tables)
        subset_sizes[name] = {"candidate_rows": len(tables.parameters),
                              "retained_designs": len(tables.retained())}

    bom = {"robust": [], "legacy": []}
    bom_designs = []
    for name, tables in tables_by_subset.items():
        for index, path in find_boms(args.midship_root, name).items():
            bom_designs.append(f"{name}:{index}")
            for mode in bom:
                bom[mode] += A.compare_bom(rule_set, tables, index, path,
                                           legacy_unique=(mode == "legacy"))

    summary = {
        "rule_set": rule_set.data["rule_set"]["id"],
        "rule_file_sha256": rule_file_sha,
        "agreement_convention": "pass when value >= threshold; the spacing constraint is stored negated",
        "subsets": subset_sizes,
        "population_rule_side": {
            "description": "Required values rebuilt from parameter rows; member values read from the MiDShip value table.",
            "per_rule": A.summarize(population),
        },
        "bom_sample_independent": {
            "designs": bom_designs,
            "description": "Required and member values both computed from the bill of materials.",
            "robust_spacing": A.summarize(bom["robust"]),
            "evaluator_replica_spacing": A.summarize(bom["legacy"]),
        },
        "strict_text_option": strict_divergence(rule_set, tables_by_subset),
        "hatch_bit_evidence_non_container": hatch_evidence(tables_by_subset),
    }
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "summary.json").write_text(json.dumps(summary, indent=1) + "\n", encoding="utf-8")

    disagreements = [c for c in population if not c.threshold_match or c.mine_pass != c.ms_pass]
    bom_robust_bad = [c for c in bom["robust"] if not c.threshold_match or c.mine_pass != c.ms_pass]
    write_csv(args.full_out / "disagreements_population.csv", disagreements)

    examples, taken = [], defaultdict(int)
    for c in bom_robust_bad + disagreements:
        key = (c.column, c.cause)
        if taken[key] < EXAMPLES_PER_GROUP:
            taken[key] += 1
            examples.append(c)
    write_csv(args.out / "disagreement_examples.csv", examples)
    print(json.dumps({"rules": len(rule_set.rules), "population_comparisons": len(population),
                      "population_disagreements": len(disagreements),
                      "bom_designs": len(bom_designs)}, indent=1))


if __name__ == "__main__":
    main()
