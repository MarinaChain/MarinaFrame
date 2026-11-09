"""Markdown tables from replay outputs (docs/HULL_FAIRING.md 6).

    PYTHONPATH=src:. .venv/bin/python -m benchmarks.hull_fairing.summary work/hull-fairing/len020.json
"""
from __future__ import annotations

import json
import sys

import numpy as np


def short(case: str) -> str:
    return case.replace("shipd-1-", "").replace("-3v", "")


def main() -> None:
    data = json.loads(open(sys.argv[1]).read())
    rows = data["rows"]
    print("options", data["options"])
    print("\n| Case | RMS % before | after | Vol % before | after | WL inflections | Section inflections | Max curvature jump | traced/read within tol | max move m | check items |")
    print("|---|---|---|---|---|---|---|---|---|---|---|")
    for r in rows:
        fb, fa = r["fairness_before"], r["fairness_after"]
        measured = [v for k, v in r["moves_by_label"].items() if k in ("traced", "read")]
        within = min(v["within_tolerance"] for v in measured) if measured else float("nan")
        move = max(v["max_m"] for v in measured) if measured else float("nan")
        if "rms_pct" in r["before"]:
            gate = (f"{r['before']['rms_pct']:.2f} | {r['after']['rms_pct']:.2f} | {r['before']['volume_pct']:+.1f} | "
                    f"{r['after']['volume_pct']:+.1f}")
        else:
            gate = (f"{1000 * r['before']['rms_m']:.1f} mm | {1000 * r['after']['rms_m']:.1f} mm | max "
                    f"{r['before']['max_abs_m']:.3f} m | {r['after']['max_abs_m']:.3f} m")
        print(f"| {short(r['case'])} | {gate} | {fb['waterline_inflections']} -> {fa['waterline_inflections']} | "
              f"{fb['section_inflections']} -> {fa['section_inflections']} | {fb['max_curvature_jump']:.2f} -> "
              f"{fa['max_curvature_jump']:.2f} | {100 * within:.1f} % | {move:.3f} | {r['check_items']} |")
    factory = [r for r in rows if "rms_pct" in r["before"]]
    if factory:
        print(f"\nmean RMS {np.mean([r['before']['rms_pct'] for r in factory]):.3f} -> "
              f"{np.mean([r['after']['rms_pct'] for r in factory]):.3f}; passes "
              f"{sum(r['before']['passes'] for r in factory)} -> {sum(r['after']['passes'] for r in factory)}")
    robust = [(r["case"], x) for r in rows for x in r.get("robustness", [])]
    if robust:
        print("\n| Kind | cases x places | faired moves / injected: median | max |")
        print("|---|---|---|---|")
        for kind in dict.fromkeys(x["kind"] for _, x in robust):
            shares = [x["share"] for _, x in robust if x["kind"] == kind]
            print(f"| {kind} | {len(shares)} | {np.median(shares):.2f} | {max(shares):.2f} |")
        print("\nper case max share (cell +0.2 m):", {short(c): round(max(x['share'] for cc, x in robust if cc == c and x['kind'] == 'cell +0.2 m'), 2)
                                                 for c in dict.fromkeys(c for c, _ in robust)})


if __name__ == "__main__":
    main()
