"""Markdown tables of the plan/profile evidence error (old reader against view_reader_v2).

    PYTHONPATH=src:. .venv/bin/python -m benchmarks.hull_fairing.summary_view_reader_v2 \
        work/view-reader-v2/eval-fit.json work/view-reader-v2/eval-check.json
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def _f(value, digits=3):
    return "-" if value is None else f"{value:.{digits}f}"


def _pct(value):
    return "-" if value is None else f"{100 * value:.1f} %"


def evidence_table(results: list[dict]) -> str:
    lines = ["| Case | Reader | Plan points | Plan RMS / max m | Identity correct | Plan abstention | Negative "
             "| Keel RMS / max m | Deck RMS / max m | Stem / stern RMS m | Heights matched (spurious) |",
             "|---|---|---|---|---|---|---|---|---|---|---|"]
    for result in results:
        for row in result["rows"]:
            if not row["available"]:
                lines.append(f"| {row['case']} ({result['split']}) | both | not available: {row['reason']} "
                             "| | | | | | | | |")
                continue
            for name in ("old", "new"):
                r = row[name]
                plan, profile, heights = r["plan"], r["profile"], r["heights"]
                lines.append(
                    f"| {row['case']} | {name} | {plan['points']} | {_f(plan['all']['rms_m'])} / {_f(plan['all']['max_m'])} "
                    f"| {_pct(plan['identity_share'])} | {_pct(r['plan_abstention_share'])} | {plan['negative']} "
                    f"| {_f(profile['keel']['rms_m'])} / {_f(profile['keel']['max_m'])} "
                    f"| {_f(profile['top']['rms_m'])} / {_f(profile['top']['max_m'])} "
                    f"| {_f(profile['stem']['rms_m'])} / {_f(profile['stern']['rms_m'])} "
                    f"| {heights['matched']}/{len(heights['truth'])} ({heights['spurious']}) |")
    return "\n".join(lines)


def waterline_table(results: list[dict]) -> str:
    lines = ["| Case | Reader | Per curve: points, RMS m, max m |", "|---|---|---|"]
    for result in results:
        for row in result["rows"]:
            if not row["available"]:
                continue
            for name in ("old", "new"):
                cells = []
                for curve, stats in row[name]["plan"]["by_curve"].items():
                    if stats["n"]:
                        cells.append(f"{curve}: {stats['n']}, {_f(stats['rms_m'])}, {_f(stats['max_m'])}")
                    elif stats["points"]:
                        cells.append(f"{curve}: {stats['points']} unscorable")
                lines.append(f"| {row['case']} | {name} | {'; '.join(cells) or 'none'} |")
    return "\n".join(lines)


def totals(results: list[dict]) -> str:
    lines = ["| Split | Reader | Plan points | Identity correct | Plan abstention | Points within 1 % half-beam |",
             "|---|---|---|---|---|---|"]
    for result in results:
        for name in ("old", "new"):
            rows = [r[name] for r in result["rows"] if r["available"]]
            points = sum(r["plan"]["points"] for r in rows)
            correct = sum(r["plan"]["identity_correct"] for r in rows)
            attempted = sum((r["coverage"].get("half_breadth_plan") or {}).get("attempted", 0) for r in rows)
            if name == "old":
                missing = sum((r["coverage"].get("half_breadth_plan") or {}).get("missing", 0) for r in rows)
            else:
                missing = sum(sum((r["coverage"].get("half_breadth_plan") or {}).get("abstained", {}).values())
                              for r in rows)
            within = [r["plan"]["within_1pct_half_beam"] * r["plan"]["all"]["n"] for r in rows
                      if r["plan"]["within_1pct_half_beam"] is not None]
            scored = sum(r["plan"]["all"]["n"] for r in rows)
            lines.append(f"| {result['split']} | {name} | {points} | {_pct(correct / points if points else None)} "
                         f"| {_pct(missing / attempted if attempted else None)} "
                         f"| {_pct(sum(within) / scored if scored else None)} |")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("results", type=Path, nargs="+")
    args = parser.parse_args()
    results = [json.loads(path.read_text()) for path in args.results]
    print(totals(results), "", evidence_table(results), "", waterline_table(results), sep="\n")


if __name__ == "__main__":
    main()
