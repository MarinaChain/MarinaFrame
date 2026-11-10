"""Fit-only weight choice, then fixed-parameter replay of all stored readings.

The choice command reads only L0 point sets. The replay command uses the saved
choice without tuning. Both use frozen development cases, never live models.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
from pathlib import Path

import numpy as np

from benchmarks.hull_fairing.collect_three_view import DEFAULT_OUTPUT, PROTOCOL_PATH
from benchmarks.hull_fairing.replay import BUE_GIRL_TRUTH, build_step, factory_score, bue_girl_score, half_breadth_at_mid
from benchmarks.hull_fairing.replay_outliers import selected_stations, perturb
from vessel_reconstruction import fairing

CHOICE_PATH = Path(__file__).with_name("three_view_choice.json")
KINDS = ("cell_0.1m", "cell_0.2m", "station_5pct")


def require_fit_rows(rows):
    if not rows or any(row["split"] != "fit" for row in rows):
        raise ValueError("Weight choice accepts fit rows only")


def select_candidate(candidates):
    def key(row):
        fidelity, follow = row["minimum_fidelity"], row["worst_follow_share"]
        if fidelity >= .95:
            return (0, 0, follow, row["plan_weight"])
        return (1, -fidelity, follow, row["plan_weight"])
    return min(candidates, key=key)


def injection_trials(sections, half_beam, fit):
    """Freeze other views in the fit closure; match the midpoint vertex in each pair."""
    try:
        station_ids = selected_stations(sections)
    except ValueError as exc:
        return [{"kind": kind, "station_id": None, "available": False, "share": None, "reason": str(exc)}
                for _ in range(2) for kind in KINDS]
    trials = []
    for sid in station_ids:
        for kind, amount in zip(KINDS, (.1, .2, .05 * half_beam)):
            whole = kind == "station_5pct"
            base_input = perturb(sections, sid, 0., whole=whole)
            changed = perturb(sections, sid, amount, whole=whole)
            trial = {"kind": kind, "station_id": sid, "injected_m": amount, "available": False, "share": None}
            try:
                base, _ = fit(base_input)
                after, _ = fit(changed)
                move = half_breadth_at_mid(after, sid) - half_breadth_at_mid(base, sid)
                by_id = {s["id"]: s for s in base}
                collateral = []
                for row in after:
                    if row["id"] == sid or row["id"] not in by_id:
                        continue
                    p, q = np.asarray(row["points_yz_m"]), np.asarray(by_id[row["id"]]["points_yz_m"])
                    collateral.extend(abs(p[:, 0] - np.interp(p[:, 1], q[:, 1], q[:, 0])))
                trial.update(available=True, share=float(move / amount), absolute_share=float(abs(move / amount)),
                             moved_m=float(move), off_target_max_m=float(max(collateral, default=0.)))
            except (ValueError, FloatingPointError, np.linalg.LinAlgError) as exc:
                trial["reason"] = f"{type(exc).__name__}: {exc}"
            trials.append(trial)
    return trials


def trial_summary(trials):
    summary = {}
    for kind in KINDS:
        rows = [t for t in trials if t["kind"] == kind]
        shares = [t["share"] for t in rows if t["available"]]
        bound = .6 if kind == "station_5pct" else .25
        worst = max(map(abs, shares)) if shares else None
        summary[kind] = {"planned": len(rows), "available": len(shares),
                         "median_signed_share": float(np.median(shares)) if shares else None,
                         "median_absolute_share": float(np.median(np.abs(shares))) if shares else None,
                         "max_absolute_share": worst,
                         "target_met": bool(rows) and len(shares) == len(rows) and worst <= bound}
    return summary


def minimum_fidelity(report):
    shares = []
    for labels in report.get("moves_by_view", {}).values():
        rows = [stats for label, stats in labels.items() if label in ("traced", "read")]
        total = sum(s["points"] for s in rows)
        if total:
            shares.append(sum(s["within_tolerance"] * s["points"] for s in rows) / total)
        else:
            shares.append(0.)
    return min(shares, default=0.)


def station_fit(half_beam):
    return lambda rows: fairing.fair_sections(rows, half_beam_m=half_beam)


def joint_fit(evidence, plan_weight):
    return lambda rows: fairing.fair_sections(rows, evidence=evidence, plan_weight=plan_weight)


def tune(evidence_dir, output, choice_path):
    protocol = json.loads(PROTOCOL_PATH.read_text())
    manifest = json.loads((evidence_dir / "manifest.json").read_text())
    # Filter metadata before opening any point set: check geometry is not read here.
    entries = [r for r in manifest if r["split"] == "fit" and r["delivered"]]
    require_fit_rows(entries)
    if {r["case"] for r in entries} != set(protocol["fit_cases"]):
        raise ValueError("Fit population differs from the frozen protocol")
    candidates = []
    for weight in protocol["plan_weight_candidates"]:
        rows = []
        for entry in entries:
            evidence = json.loads((evidence_dir / entry["file"]).read_text())
            fit = joint_fit(evidence, weight)
            _, report = fit(evidence["sections"])
            trials = injection_trials(evidence["sections"], evidence["half_beam_m"], fit)
            rows.append({"case": entry["case"], "minimum_fidelity": minimum_fidelity(report),
                         "trials": trials, "three_view_applied": report.get("three_view_applied", False)})
            print("fit", weight, entry["case"], rows[-1]["minimum_fidelity"], flush=True)
        summaries = trial_summary([t for r in rows for t in r["trials"]])
        candidate = {"plan_weight": weight, "minimum_fidelity": min(r["minimum_fidelity"] for r in rows),
                     "worst_follow_share": max(s["max_absolute_share"] if s["available"] == s["planned"] else 1e300
                                                for s in summaries.values()), "trials": summaries, "rows": rows}
        candidates.append(candidate)
    chosen = select_candidate(candidates)
    choice = {"plan_weight": chosen["plan_weight"], "fairness": protocol["fairness"],
              "fit_cases": protocol["fit_cases"], "protocol_sha256": hashlib.sha256(PROTOCOL_PATH.read_bytes()).hexdigest(),
              "minimum_fit_fidelity": chosen["minimum_fidelity"], "worst_fit_follow_share": chosen["worst_follow_share"],
              "selection": "section 8.3; no candidate met T4" if chosen["minimum_fidelity"] < .95 else "section 8.3; T4 eligible",
              "engineering_approved": False}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps({"candidates": candidates, "choice": choice}, indent=2, allow_nan=False) + "\n")
    # Exclusive creation prevents an accidental replay-time retune.
    with choice_path.open("x") as stream:
        stream.write(json.dumps(choice, indent=2, allow_nan=False) + "\n")
    print(json.dumps(choice, indent=2), flush=True)


def reader_reference(evidence):
    """Stored reader cell output, separately from interpolation along its curves."""
    from benchmarks.auto_calibration.live_score import intake_table
    from benchmarks.bue_girl import holdout_value
    table = intake_table({"stations": evidence["reader_cells"]})
    truth = holdout_value.load_truth(BUE_GIRL_TRUTH)
    return {"score": holdout_value.score(table, truth),
            "missing_truth_cells": [{"station": station, "waterline": waterline}
                                    for station, waterline in truth if (station, waterline) not in table]}


def _score(case, sections, reader):
    if reader:
        return bue_girl_score(sections)
    with tempfile.TemporaryDirectory() as folder:
        return factory_score(case, build_step(sections, Path(folder)))


def replay_row(evidence, choice):
    sections = evidence["sections"]
    fit = joint_fit(evidence, choice["plan_weight"])
    joint, report = fit(sections)
    old, old_report = fairing.fair_sections(sections)
    row = {k: evidence[k] for k in ("case", "build", "split", "delivered", "reader_output")}
    row.update(report=report, station_only_report=old_report, scores={}, failures={}, fairness={}, trials={})
    if evidence.get("reader_cells"):
        row["reader_reference"] = reader_reference(evidence)
    for name, rows in (("current", sections), ("station_only", old), ("joint", joint)):
        try:
            row["scores"][name] = _score(evidence["case"], rows, evidence["reader_output"])
        except Exception as exc:  # keep every planned case in the result denominator
            row["scores"][name] = None
            row["failures"][name] = f"{type(exc).__name__}: {exc}"
        row["fairness"][name] = fairing.fairness_metrics(rows, evidence["half_beam_m"])
    for name, fitter in (("station_only", station_fit(evidence["half_beam_m"])), ("joint", fit)):
        row["trials"][name] = injection_trials(sections, evidence["half_beam_m"], fitter)
    return row


def run_replay(evidence_dir, output, choice_path):
    choice_bytes = choice_path.read_bytes()
    choice = json.loads(choice_bytes)
    if choice["protocol_sha256"] != hashlib.sha256(PROTOCOL_PATH.read_bytes()).hexdigest():
        raise ValueError("Protocol changed after weight choice")
    manifest = json.loads((evidence_dir / "manifest.json").read_text())
    output.mkdir(parents=True, exist_ok=True)
    rows = []
    for entry in manifest:
        evidence = json.loads((evidence_dir / entry["file"]).read_text())
        row = replay_row(evidence, choice)
        rows.append(row)
        (output / entry["file"]).write_text(json.dumps(row, indent=1, allow_nan=False) + "\n")
        print(entry["case"], entry["build"], json.dumps(row["scores"]), row["failures"], flush=True)
    if choice_path.read_bytes() != choice_bytes:
        raise ValueError("Weight choice changed during replay")
    (output / "replay.json").write_text(json.dumps({"choice": choice, "choice_sha256": hashlib.sha256(choice_bytes).hexdigest(),
                                                   "rows": rows, "engineering_approved": False}, indent=1, allow_nan=False) + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("choose", "replay"))
    parser.add_argument("--evidence", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--choice", type=Path, default=CHOICE_PATH)
    args = parser.parse_args()
    if args.mode == "choose":
        tune(args.evidence, args.output, args.choice)
    else:
        run_replay(args.evidence, args.output, args.choice)


if __name__ == "__main__":
    main()
