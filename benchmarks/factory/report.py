"""Score finished runs and aggregate accuracy tables.

``score``  score every ``built`` case of a run against the sealed truth (reads ``sealed/``; never used by inference).
``table``  aggregate results and scores into markdown tables by split, degradation level, layout and family.

Predeclared "correct" gate (fixed before any run, never widened): a case is *correct* when it is built, scored,
the RMS half-breadth error over its stations (main band) is at most 2 % of the hull's maximum half-breadth, and
the volume error below the design draft within the reconstructed range is at most 5 % in magnitude.
Denominators are always stated: correct / attempted (all cases) and correct / built. Abstention is its own
outcome; it is neither a failure nor a pass.
"""
from __future__ import annotations

import argparse
import json
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np

from . import truth as T

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ROOT = ROOT / "work" / "factory"
RMS_GATE_FRACTION = 0.02
VOLUME_GATE = 0.05
LEVEL_NAMES = {0: "0 clean", 1: "1 mild", 2: "2 moderate", 3: "3 heavy"}


def _score_one(args) -> str:
    root, run, case_dir = args
    result = json.loads((case_dir / "result.json").read_text())
    if result["outcome"] != "built" or (case_dir / "score.json").exists():
        return result["case_id"]
    params = json.loads((root / "params" / f"{result['case_id']}.json").read_text())
    stations = [{"id": f"s{i + 1:02d}", "x_m": x} for i, x in enumerate(params["station_x_m"])]
    try:
        score = T.score_model(root / "sealed" / "truth" / f"{result['hull_id']}.npz", case_dir / "model.step", stations)
    except Exception as exc:  # recorded as a scoring failure
        score = {"status": "scoring_error", "error": f"{type(exc).__name__}: {exc}"}
    if result["split"] == "hull-disjoint (v2)":
        score["split"] = "hull-disjoint (v2)"
        score["split_caveat"] = "Clusters can share broad families with the frozen splits; this is not family-disjoint."
    (case_dir / "score.json").write_text(json.dumps(score, indent=1) + "\n")
    return result["case_id"]


def cmd_score(root: Path, run: str, jobs: int) -> None:
    run_dir = root / "runs" / run
    tasks = [(root, run, d) for d in sorted(run_dir.iterdir()) if (d / "result.json").exists()]
    with ProcessPoolExecutor(max_workers=jobs) as pool:
        for index, _ in enumerate(pool.map(_score_one, tasks), 1):
            if index % 20 == 0:
                print(f"scored {index}/{len(tasks)}", flush=True)


def load_rows(root: Path, runs: list[str]) -> list[dict]:
    rows = []
    for run in runs:
        for case_dir in sorted((root / "runs" / run).iterdir()):
            if not (case_dir / "result.json").exists():
                continue
            row = json.loads((case_dir / "result.json").read_text())
            row["score"] = json.loads((case_dir / "score.json").read_text()) if (case_dir / "score.json").exists() else None
            if row["score"] and row["score"].get("status") == "scored":
                truth = row["score"]["truth"]
                hb = truth["max_half_breadth_m"]
                main = row["score"]["summary"].get("half_breadth_main")
                hydro = row["score"]["hydrostatics_at_design_draft"]
                row["rms_m"] = main["rms_of_station_rms_m"] if main else None
                row["rms_pct_hb"] = 100 * main["rms_of_station_rms_m"] / hb if main else None
                row["max_m"] = main["max_abs_m"] if main else None
                row["max_pct_hb"] = 100 * main["max_abs_m"] / hb if main else None
                row["vol_in"] = hydro["volume_error_relative_within_range"]
                row["vol_full"] = hydro["volume_error_relative_full"]
                row["wp_in"] = hydro["waterplane_error_relative_within_range"]
                row["wp_full"] = hydro["waterplane_error_relative_full"]
                row["correct"] = bool(row["rms_pct_hb"] is not None and row["rms_pct_hb"] <= 100 * RMS_GATE_FRACTION
                                      and row["vol_in"] is not None and abs(row["vol_in"]) <= VOLUME_GATE)
            else:
                row["correct"] = False
            rows.append(row)
    return rows


def _stat(values, fn) -> str:
    values = [v for v in values if v is not None]
    return f"{fn(values):.2f}" if values else "-"


def _line(label: str, rows: list[dict]) -> str:
    built = [r for r in rows if r["outcome"] == "built"]
    scored = [r for r in built if "rms_m" in r]
    attempted = len(rows)
    correct = sum(r["correct"] for r in rows)
    median = lambda v: float(np.median(v))  # noqa: E731
    p90 = lambda v: float(np.percentile(v, 90))  # noqa: E731
    absolute = lambda key: [abs(r[key]) * 100 for r in scored if r.get(key) is not None]  # noqa: E731
    times = [r["seconds"] for r in rows]
    return (f"| {label} | {attempted} | {len(built)} | {sum(r['outcome'] == 'abstained' for r in rows)} | "
            f"{sum(r['outcome'] == 'failed' for r in rows)} | {correct}/{attempted} | "
            f"{correct}/{len(built) if built else 0} | {_stat([r['rms_m'] * 1000 for r in scored], median)} | "
            f"{_stat([r['rms_pct_hb'] for r in scored], median)} | {_stat([r['max_pct_hb'] for r in scored], median)} | "
            f"{_stat(absolute('vol_in'), median)} / {_stat(absolute('vol_in'), p90)} | "
            f"{_stat(absolute('vol_full'), median)} | {_stat(absolute('wp_in'), median)} | {_stat(times, median)} |")


HEADER = ("| {k} | attempted | built | abstained | failed | correct / attempted | correct / built | "
          "station RMS median (mm) | RMS % of B/2 median | max % of B/2 median | "
          "volume error in range, % median / p90 | volume error full, % median | waterplane in range, % median | "
          "seconds median |\n|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|")


def cmd_table(root: Path, runs: list[str], out: Path | None) -> str:
    rows = load_rows(root, runs)
    text = []
    for split in ("development", "validation", "test", "hull-disjoint (v2)"):
        part = [r for r in rows if r["split"] == split]
        if not part:
            continue
        text.append(f"\n### Split: {split} ({len(part)} cases, {len({r['hull_id'] for r in part})} hulls)\n")
        if split == "hull-disjoint (v2)":
            text.append("Clusters can share broad families with the frozen splits; this is not family-disjoint.\n")
        for title, key, labels in (("By degradation level", "level", LEVEL_NAMES), ("By layout", "layout", None)):
            text.append(f"\n{title}\n\n" + HEADER.format(k=key))
            values = sorted({r[key] for r in part})
            for value in values:
                text.append(_line(labels[value] if labels else str(value), [r for r in part if r[key] == value]))
        text.append("\nBy level and layout\n\n" + HEADER.format(k="level / layout"))
        for level in sorted({r["level"] for r in part}):
            for layout in sorted({r["layout"] for r in part}):
                sub = [r for r in part if r["level"] == level and r["layout"] == layout]
                if sub:
                    text.append(_line(f"{LEVEL_NAMES[level]} / {layout}", sub))
        text.append(_line("**all**", part))
        families = sorted({r["family"] for r in part})
        named = [f for f in families if not f.startswith("shipd-")]
        text.append("\nBy family (named hulls individually; Ship-D clusters pooled per cluster in the JSON)\n\n" + HEADER.format(k="family"))
        for family in named:
            text.append(_line(family, [r for r in part if r["family"] == family]))
        shipd = [r for r in part if r["family"].startswith("shipd-")]
        if shipd:
            text.append(_line(f"Ship-D ({len({r['family'] for r in shipd})} clusters)", shipd))
    result = "\n".join(text) + "\n"
    if out:
        out.write_text(result)
    per_family = {}
    for r in rows:
        d = per_family.setdefault((r["split"], r["family"]), {"attempted": 0, "built": 0, "abstained": 0, "failed": 0, "correct": 0})
        d["attempted"] += 1
        d[r["outcome"]] += 1
        d["correct"] += int(r["correct"])
    if out:
        out.with_suffix(".families.json").write_text(json.dumps(
            [{"split": s, "family": f, **v} for (s, f), v in sorted(per_family.items())], indent=1) + "\n")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["score", "table"])
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--run", action="append", required=True)
    parser.add_argument("--jobs", type=int, default=3)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    if args.command == "score":
        for run in args.run:
            cmd_score(args.root, run, min(args.jobs, 3))
    else:
        print(cmd_table(args.root, args.run, args.out))


if __name__ == "__main__":
    sys.exit(main())
