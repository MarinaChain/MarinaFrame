"""Fit-half station-frame ablation. No check-half execution path.

Run once before the PM commits the settings file::

    PYTHONPATH=src:. OPENBLAS_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 \
      .venv/bin/python -m benchmarks.hull_fairing.replay_station_frame \
      --output work/station-frame --settings benchmarks/hull_fairing/station_frame_settings.json

Only the protocol L0 cases are opened. Derived evidence and scores stay in work/.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
from pathlib import Path

from benchmarks.hull_fairing import station_frame
from benchmarks.hull_fairing.collect_three_view import PROTOCOL_PATH, collect_build
from benchmarks.hull_fairing.collect_view_reader_v2 import new_record
from benchmarks.hull_fairing.replay import WORK, ROUNDS, delivered_build, stored_builds, build_step, factory_score
from benchmarks.hull_fairing.replay_three_view import (
    CHOICE_PATH, injection_trials, minimum_fidelity, station_fit, trial_summary,
)
from benchmarks.hull_fairing.view_reader_eval import frozen_reader
from vessel_reconstruction import fairing

SELECTION = ("Complete candidates first; most delivered fit gate passes (RMS <=2%, absolute volume <=5%); "
             "then lowest mean RMS, lowest mean absolute volume error, then candidate order.")


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")


def candidates():
    return [{"name": "a_current_joint", "arm": "current_joint", "bound_fraction": 0.}] + [
        {"name": f"b_endpoints_{bound:g}", "arm": "bounded_endpoints", "bound_fraction": bound}
        for bound in station_frame.BOUND_CANDIDATES] + [
        {"name": "c_registered_frame", "arm": "registered_frame", "bound_fraction": 0.}]


def fit_evidence(output):
    """Resolve only fit case paths, rather than collecting then filtering both halves."""
    protocol = json.loads(PROTOCOL_PATH.read_text())
    frozen_reader()
    records, manifest = [], []
    for name in protocol["fit_cases"]:
        if not name.endswith("-L0"):
            raise ValueError("Fit collection permits L0 only")
        case = WORK / ROUNDS[0] / name
        delivered = delivered_build(case)
        builds = stored_builds(case)
        if delivered not in builds:
            raise ValueError(f"Delivered build missing from stored population: {name}")
        for build in builds:
            record = new_record(collect_build(case, build), case)
            record.update(split="fit", delivered=build == delivered)
            filename = f"{name}--{build.name}.json"
            write_json(output / "evidence" / filename, record)
            manifest.append({"case": name, "build": build.name, "split": "fit",
                             "delivered": record["delivered"], "file": filename})
            records.append(record)
            print("evidence", name, build.name, "delivered", record["delivered"], flush=True)
    station_frame.require_fit_population(manifest, protocol)
    write_json(output / "evidence/manifest.json", manifest)
    return records


def score_sections(case, sections, output):
    with tempfile.TemporaryDirectory(prefix="cad-", dir=output) as folder:
        return factory_score(case, build_step(sections, Path(folder)))


def evaluate(record, fitter, output, *, injections=False):
    row = {key: record[key] for key in ("case", "build", "split", "delivered")}
    row.update(score=None, failure=None)
    try:
        sections, report = fitter(record["sections"])
        row.update(report=report, minimum_fidelity=minimum_fidelity(report),
                   fairness=fairing.fairness_metrics(sections, record["half_beam_m"]))
        row["score"] = score_sections(record["case"], sections, output)
    except Exception as exc:  # retain the planned denominator and the concrete failure
        row["failure"] = f"{type(exc).__name__}: {exc}"
    if injections:
        row["trials"] = injection_trials(record["sections"], record["half_beam_m"], fitter)
    print(record["case"], record["build"], row["score"], row["failure"], flush=True)
    return row


def identity_fit(sections):
    return sections, {}


def run(output, settings_path):
    if settings_path.exists():
        raise ValueError("Settings already exist; refusing to retune a frozen experiment")
    if (output / "experiment.json").exists():
        raise ValueError("Experiment results already exist; use a new output directory")
    output.mkdir(parents=True, exist_ok=True)
    choice = json.loads(CHOICE_PATH.read_text())
    protocol = json.loads(PROTOCOL_PATH.read_text())
    definitions = candidates()
    design = {"split": "fit", "fit_cases": protocol["fit_cases"], "candidates": definitions,
              "selection": SELECTION, "scale_bounds": station_frame.SCALE_BOUNDS,
              "x_offset_length_fraction": station_frame.X_OFFSET_LENGTH_FRACTION,
              "z_offset_half_beam_fraction": station_frame.Z_OFFSET_HALF_BEAM_FRACTION,
              "joint_choice": choice, "engineering_approved": False}
    # Save the search space and selection rule before any evidence or score.
    write_json(output / "design.json", design)
    records = fit_evidence(output)
    baseline = {"current": [], "station_only": []}
    for record in records:
        print("baseline", flush=True)
        baseline["current"].append(evaluate(record, identity_fit, output))
        baseline["station_only"].append(evaluate(record, station_fit(record["half_beam_m"]), output,
                                                 injections=record["delivered"]))
    results = []
    for definition in definitions:
        print("candidate", definition["name"], flush=True)
        rows = []
        for record in records:
            def fit(sections):
                return station_frame.fit_sections(sections, record, definition["arm"], definition["bound_fraction"],
                                                  plan_weight=choice["plan_weight"], fairness=choice["fairness"])
            rows.append(evaluate(record, fit, output, injections=record["delivered"]))
            write_json(output / "candidates" / definition["name"] / f"{record['case']}--{record['build']}.json", rows[-1])
        delivered = [row for row in rows if row["delivered"]]
        result = {**definition, "rows": rows, "scores": [row["score"] for row in delivered],
                  "delivered": station_frame.candidate_summary([row["score"] for row in delivered]),
                  "all_stored": station_frame.candidate_summary([row["score"] for row in rows]),
                  "trials": trial_summary([trial for row in delivered for trial in row["trials"]]),
                  "minimum_fidelity": min((row.get("minimum_fidelity", 0.) for row in delivered), default=0.)}
        results.append(result)
        print("summary", definition["name"], result["delivered"], flush=True)
    chosen = station_frame.select_candidate(results)
    experiment = {"design": design, "baselines": baseline, "candidates": results,
                  "chosen": chosen["name"], "check_status": "not_read_not_scored", "engineering_approved": False}
    write_json(output / "experiment.json", experiment)
    source_paths = [PROTOCOL_PATH, CHOICE_PATH, Path(__file__), Path(station_frame.__file__),
                    Path("src/vessel_reconstruction/three_view_fairing.py"),
                    Path("src/vessel_reconstruction/view_reader_v2.py"),
                    Path("benchmarks/hull_fairing/view_reader_v2_settings.json")]
    settings = {**design, "chosen": {key: chosen[key] for key in ("name", "arm", "bound_fraction")},
                "delivered_fit": chosen["delivered"], "all_stored_fit": chosen["all_stored"],
                "candidate_fit_summaries": [{key: row[key] for key in ("name", "delivered", "all_stored")}
                                            for row in results],
                "source_sha256": {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in source_paths},
                "fit_results": str(output / "experiment.json"),
                "fit_results_sha256": hashlib.sha256((output / "experiment.json").read_bytes()).hexdigest(),
                "check_status": "not_read_not_scored", "requires_pm_commit_before_check": True,
                "fairing_default": "off"}
    with settings_path.open("x") as stream:
        stream.write(json.dumps(settings, indent=2, allow_nan=False) + "\n")
    print("settings", settings_path, "chosen", chosen["name"], flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("work/station-frame"))
    parser.add_argument("--settings", type=Path, default=Path("benchmarks/hull_fairing/station_frame_settings.json"))
    args = parser.parse_args()
    run(args.output, args.settings)


if __name__ == "__main__":
    main()
