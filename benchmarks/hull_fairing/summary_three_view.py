"""Report the fixed three-view replay; no fitting or parameter changes."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from benchmarks.hull_fairing.collect_three_view import DEFAULT_OUTPUT, PROTOCOL_PATH
from benchmarks.hull_fairing.replay_three_view import trial_summary, injection_trials, station_fit, joint_fit, reader_reference
from benchmarks.hull_fairing.summary import short

MODES = ("current", "station_only", "joint")


def gate_targets(rows, *, expected_cases):
    complete = (len(rows) == len(expected_cases) and {r["case"] for r in rows} == expected_cases
                and all(r["scores"].get(mode) is not None for r in rows for mode in ("current", "joint")))
    if not complete:
        return {"complete": False, "T1": False, "T2": False}
    before = [r["scores"]["current"] for r in rows]
    after = [r["scores"]["joint"] for r in rows]
    delta = [a["rms_pct"] - b["rms_pct"] for b, a in zip(before, after)]
    return {"complete": True,
            "T1": max(delta) <= .1 + 1e-9 and float(np.mean(delta)) <= -.1 + 1e-9,
            "T2": all(not b["passes"] or a["passes"] for b, a in zip(before, after))
            and all(abs(a["volume_pct"]) - abs(b["volume_pct"]) <= .5 + 1e-9 for b, a in zip(before, after))}


def aggregate(rows):
    result = {"planned": len(rows), "modes": {}, "injections": {}}
    for mode in MODES:
        scores = [r["scores"][mode] for r in rows if r["scores"][mode] is not None]
        result["modes"][mode] = {"scored": len(scores), "mean_rms_pct": float(np.mean([s["rms_pct"] for s in scores]))
                                 if scores else None, "passes": sum(s["passes"] for s in scores)}
    for mode in ("station_only", "joint"):
        result["injections"][mode] = trial_summary([t for r in rows for t in r["trials"][mode]])
    return result


def summarize(data):
    protocol = json.loads(PROTOCOL_PATH.read_text())
    rows = data["rows"]
    primary = [r for r in rows if r["delivered"] and not r["reader_output"]]
    results = {}
    targets = {}
    for split in ("fit", "check"):
        selected = [r for r in primary if r["split"] == split]
        results[split] = aggregate(selected)
        target = gate_targets(selected, expected_cases=set(protocol[f"{split}_cases"]) - {"bue_girl"})
        trials = trial_summary([t for r in rows if r["delivered"] and r["split"] == split for t in r["trials"]["joint"]])
        target["T3"] = all(s["target_met"] for s in trials.values())
        fidelity = []
        for row in rows:
            if not row["delivered"] or row["split"] != split:
                continue
            views = row["report"].get("moves_by_view") or {"body_plan": row["report"].get("moves_by_label", {})}
            for labels in views.values():
                measured = [s for label, s in labels.items() if label in ("traced", "read")]
                fidelity.append(bool(measured) and all(s["within_tolerance"] >= .95 for s in measured))
        target["T4"] = bool(fidelity) and all(fidelity)
        targets[split] = target
    factory = [r for r in rows if not r["reader_output"]]
    results["all_builds"] = aggregate(factory)
    for split in ("fit", "check"):
        results[f"all_builds_{split}"] = aggregate([r for r in factory if r["split"] == split])
    bue = next(r for r in rows if r["reader_output"])
    b, a = bue["scores"]["current"], bue["scores"]["joint"]
    bue_safe = bool(b and a and a["cells_given"] >= b["cells_given"] and a["rms_m"] <= b["rms_m"] + 1e-9
                    and a["max_abs_m"] <= b["max_abs_m"] + 1e-9)
    t5 = bool(b and a and a["rms_m"] <= .01 and a["max_abs_m"] <= .05 and a["cells_given"] >= b["cells_given"])
    switch_default = (all(targets["check"][key] for key in ("complete", "T1", "T2", "T3")) and bue_safe
                      and all(r["scores"]["joint"] is not None for r in rows))
    return {"populations": results, "targets": targets, "bue_T5": t5, "bue_no_regression": bue_safe,
            "added_half_stations": sum(len(r["report"].get("added_half_stations", [])) for r in rows),
            "negative_breadth_projections": sum(r["report"].get("negative_breadth_projections", 0) for r in rows),
            "switch_default": switch_default, "engineering_approved": False}


def _triplet(row, key):
    return " / ".join("failed" if row["scores"][mode] is None else f"{row['scores'][mode][key]:.3f}" for mode in MODES)


def markdown(data, summary):
    lines = []
    emit = lines.append
    emit("Modes in each cell: **current / station-only / joint**. Signed volume errors use the unchanged in-range scorer.")
    emit(f"\nJoint-fit diagnostics: {summary['added_half_stations']} added half stations; "
         f"{summary['negative_breadth_projections']} negative breadth samples projected to the small positive floor.")
    emit("\n| Delivered case | Split | RMS % | Volume % | Gate passes |")
    emit("|---|---|---|---|---|")
    for row in data["rows"]:
        if not row["delivered"] or row["reader_output"]:
            continue
        passes = " / ".join("failed" if row["scores"][mode] is None else str(int(row["scores"][mode]["passes"])) for mode in MODES)
        emit(f"| {short(row['case'])} | {row['split']} | {_triplet(row, 'rms_pct')} | {_triplet(row, 'volume_pct')} | {passes} |")
    emit("\n| Population | Planned builds | Scored (current / station-only / joint) | Mean RMS % | Passes |")
    emit("|---|---|---|---|---|")
    for name, pop in summary["populations"].items():
        scored = " / ".join(str(pop["modes"][mode]["scored"]) for mode in MODES)
        rms = " / ".join(f"{pop['modes'][mode]['mean_rms_pct']:.3f}" if pop['modes'][mode]['mean_rms_pct'] is not None else "unavailable" for mode in MODES)
        passes = " / ".join(str(pop["modes"][mode]["passes"]) for mode in MODES)
        emit(f"| {name} | {pop['planned']} | {scored} | {rms} | {passes} |")
    emit("\n| Population | Mode | Injection | Available / planned | Median signed share | Median absolute share | Max absolute share | Target met |")
    emit("|---|---|---|---|---|---|---|---|")
    populations = {name: [r for r in data["rows"] if r["delivered"] and r["split"] == name and not r["reader_output"]]
                   for name in ("fit", "check")}
    populations["BUE GIRL reader"] = [r for r in data["rows"] if r["reader_output"]]
    populations["all stored (factory)"] = [r for r in data["rows"] if not r["reader_output"]]
    for name, rows in populations.items():
        for mode in ("station_only", "joint"):
            trials = trial_summary([t for r in rows for t in r["trials"][mode]])
            for kind, stats in trials.items():
                values = [f"{stats[key]:.3f}" if stats[key] is not None else "unavailable"
                          for key in ("median_signed_share", "median_absolute_share", "max_absolute_share")]
                emit(f"| {name} | {mode} | {kind} | {stats['available']} / {stats['planned']} | "
                     + " | ".join(values) + f" | {stats['target_met']} |")
    emit("\nThe current builder follows every available injection by 1.00. The JSON also records off-target maximum movement for every trial.")
    emit("\nTraced/read point movements below are **median / p95 / max metres; % within tolerance**. Each view uses its own measured points. Full per-source-label statistics and every excess location are in the replay JSON.")
    emit("\n| Delivered case | Body plan | Half-breadth plan | Profile |")
    emit("|---|---|---|---|")
    for row in data["rows"]:
        if not row["delivered"]:
            continue
        cells = []
        for view in ("body_plan", "half_breadth_plan", "profile"):
            labels = row["report"].get("moves_by_view", {}).get(view, {})
            measured = [(label, stats) for label, stats in labels.items() if label in ("traced", "read")]
            parts = []
            for label, stats in measured:
                values = [f"{stats[key]:.3f}" if stats[key] is not None else "unavailable" for key in ("median_m", "p95_m", "max_m")]
                parts.append(label + ": " + " / ".join(values) + f"; {100 * stats['within_tolerance']:.1f}% ({stats['points']} points, {stats['unavailable']} unavailable)")
            cells.append("; ".join(parts) if parts else "not available (station-only fallback)" if not row["report"].get("three_view_applied") else "no traced/read points")
        emit(f"| {short(row['case'])} | " + " | ".join(cells) + " |")
    emit("\n| Delivered case | WL inflections | Section inflections | Max curvature jump |")
    emit("|---|---|---|---|")
    for row in data["rows"]:
        if not row["delivered"]:
            continue
        fields = [" / ".join(f"{row['fairness'][mode][key]:.3f}" for mode in MODES)
                  for key in ("waterline_inflections", "section_inflections", "max_curvature_jump")]
        emit(f"| {short(row['case'])} | " + " | ".join(fields) + " |")
    bue = next(r for r in data["rows"] if r["reader_output"])
    emit("\n| BUE GIRL reader mode | RMS m | Max m | Within 0.05 m | Scored / truth cells |")
    emit("|---|---|---|---|---|")
    reference = bue.get("reader_reference")
    if reference:
        score = reference["score"]
        emit(f"| stored reader cells | {score['rms_m']:.5f} | {score['max_abs_m']:.5f} | {100 * score['within_0_05']:.1f}% | {score['cells_given']} / {score['truth_cells']} |")
        emit("\nMissing stored reader truth cells: `" + json.dumps(reference["missing_truth_cells"]) + "`.\n")
        # Keep the following mode rows in a separate valid Markdown table.
        emit("| Resampled reader curves | RMS m | Max m | Within 0.05 m | Scored / truth cells |")
        emit("|---|---|---|---|---|")
    for mode in MODES:
        score = bue["scores"][mode]
        emit(f"| {mode} | {score['rms_m']:.5f} | {score['max_abs_m']:.5f} | {100 * score['within_0_05']:.1f}% | {score['cells_given']} / {score['truth_cells']} |" if score else f"| {mode} | failed | | | |")
    emit("\nTargets: `" + json.dumps(summary["targets"]) + "`. BUE GIRL T5: `" + str(summary["bue_T5"]) + "`.")
    return "\n".join(lines) + "\n"


def export_sections(data, evidence_dir, output_dir):
    """Materialize the scored shapes with the same frozen fit, without rescoring.

    Report equality checks that this repeat uses the fitted method that was
    actually scored. The saved sections make all three modes inspectable.
    """
    from vessel_reconstruction import fairing
    output_dir.mkdir(parents=True, exist_ok=True)
    for row in data["rows"]:
        name = f"{row['case']}--{row['build']}.json"
        evidence = json.loads((evidence_dir / name).read_text())
        source = evidence["sections"]
        joint, report = fairing.fair_sections(source, evidence=evidence, plan_weight=data["choice"]["plan_weight"])
        scored_report = dict(row["report"])
        if not report.get("moves_by_view"):
            scored_report.pop("moves_by_view", None)  # derived fallback statistics from an earlier export
        if report != scored_report:
            raise ValueError(f"Fit changed since scoring: {name}")
        old, _ = fairing.fair_sections(source)
        # Repeat paired measurements with a fixed reference scale, including
        # the legacy fallback. This does not rebuild or change any gate score.
        frozen_joint = injection_trials(source, evidence["half_beam_m"], joint_fit(evidence, data["choice"]["plan_weight"]))
        if report.get("three_view_applied") and frozen_joint != row["trials"]["joint"]:
            raise ValueError(f"Joint injection response changed since scoring: {name}")
        row["trials"]["joint"] = frozen_joint
        row["trials"]["station_only"] = injection_trials(source, evidence["half_beam_m"], station_fit(evidence["half_beam_m"]))
        row["injection_reference_half_beam_m"] = evidence["half_beam_m"]
        if not report.get("moves_by_view"):
            # The legacy station-only report has no view breakdown. Derive
            # that breakdown from the actual returned points, including BUE GIRL.
            by_id = {s["id"]: s for s in joint}
            distances = {}
            for section in source:
                output = np.asarray(by_id[section["id"]]["points_yz_m"])
                points = np.asarray(section["points_yz_m"])
                movement = abs(np.interp(points[:, 1], output[:, 1], output[:, 0]) - points[:, 0])
                distances.setdefault(fairing.label_of(section), []).extend(movement)
            labels = {}
            for label, movement in distances.items():
                tolerance = fairing.tolerance_fraction(label) * evidence["half_beam_m"]
                labels[label] = {"points": len(movement), "unavailable": 0, "median_m": float(np.median(movement)),
                                 "p95_m": float(np.percentile(movement, 95)), "max_m": float(max(movement)),
                                 "within_tolerance": float(np.mean(np.asarray(movement) <= tolerance)),
                                 "tolerance_m": tolerance}
            row["report"]["moves_by_view"] = {"body_plan": labels}
        payload = {"case": row["case"], "build": row["build"], "choice": data["choice"],
                   "source_sha256": evidence["source_sha256"],
                   "sections": {"current": source, "station_only": old, "joint": joint}, "engineering_approved": False}
        path = output_dir / name
        path.write_text(json.dumps(payload, indent=1, allow_nan=False) + "\n")
        row["section_file"] = str(path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("replay", type=Path)
    parser.add_argument("--json-output", type=Path)
    parser.add_argument("--evidence", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--export-sections", type=Path)
    parser.add_argument("--complete-output", type=Path)
    args = parser.parse_args()
    data = json.loads(args.replay.read_text())
    for row in data["rows"]:
        if row["reader_output"]:
            name = f"{row['case']}--{row['build']}.json"
            evidence = json.loads((args.evidence / name).read_text())
            if evidence.get("reader_cells"):
                row["reader_reference"] = reader_reference(evidence)
    if args.export_sections:
        export_sections(data, args.evidence, args.export_sections)
    if args.complete_output:
        args.complete_output.write_text(json.dumps(data, indent=1, allow_nan=False) + "\n")
        for row in data["rows"]:
            path = args.complete_output.parent / f"{row['case']}--{row['build']}.json"
            path.write_text(json.dumps(row, indent=1, allow_nan=False) + "\n")
    summary = summarize(data)
    if args.json_output:
        args.json_output.write_text(json.dumps(summary, indent=2, allow_nan=False) + "\n")
    print(markdown(data, summary))


if __name__ == "__main__":
    main()
