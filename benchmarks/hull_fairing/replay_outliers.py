"""Replay report-only cell detection, without CAD, truth or rendered images.

Run: PYTHONPATH=src:. .venv/bin/python -m benchmarks.hull_fairing.replay_outliers
Protocol and targets: docs/HULL_FAIRING.md section 7. Data root is explicit;
only named development rounds and the BUE GIRL development run are read.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path

import numpy as np

from benchmarks.hull_fairing.replay import ROUNDS, delivered_build, load_sections, stored_builds
from vessel_reconstruction import cross_view_outliers as detector
from vessel_reconstruction import draft_fit, view_measure

DEFAULT_WORK = Path("/Users/jonathanjie/Documents/workspace/MarinaFrame/work")
# Fixed injection locations in the measured span (protocol 7.1).
STATION_FRACTIONS = (0.25, 0.5)
CELL_HALF_SPAN = 0.05
STATION_ERROR_FRACTION = 0.05


def selected_stations(sections):
    measured = sorted((s for s in sections if s.get("source_label", "traced") in ("read", "traced")),
                      key=lambda s: (s["x_m"], s["id"]))
    if len(measured) < 2:
        raise ValueError("Replay needs two distinct measured stations")
    low, high = measured[0]["x_m"], measured[-1]["x_m"]
    selected = []
    for fraction in STATION_FRACTIONS:
        target = low + fraction * (high - low)
        station = min((s for s in measured if s["id"] not in selected),
                      key=lambda s: (abs(s["x_m"] - target), s["x_m"], s["id"]))
        selected.append(station["id"])
    return selected


def perturb(sections, station_id, amount, *, whole):
    result = copy.deepcopy(sections)
    row = next(s for s in result if s["id"] == station_id)
    points = np.asarray(row["points_yz_m"], dtype=float)
    order = np.argsort(points[:, 1], kind="stable")
    points = points[order]
    z = points[:, 1]
    if np.any(np.diff(z) <= 0):
        raise ValueError(f"Injection needs increasing heights: {station_id}")
    mid = (z[0] + z[-1]) / 2
    if not whole and not np.any(np.isclose(z, mid, atol=1e-9, rtol=0)):
        points = np.vstack([points, [np.interp(mid, z, points[:, 0]), mid]])
        points = points[np.argsort(points[:, 1], kind="stable")]
    z = points[:, 1]
    bump = amount if whole else amount * np.clip(1 - abs(z - mid) / (CELL_HALF_SPAN * (z[-1] - z[0])), 0, 1)
    points[:, 0] = np.where(points[:, 0] > 0, points[:, 0] + bump, 0)
    row["points_yz_m"] = points.tolist()
    return result


def _key(cell):
    # Geometry coordinates, not point index: injecting a peak can insert a vertex.
    return cell["station_id"], round(cell["z_m"], 9)


def measure_trial(sections, station_id, kind, amount, check):
    whole = kind == "station_5pct"
    changed = perturb(sections, station_id, amount, whole=whole)
    # Insert the same vertex into the paired baseline so pre-existing alarms
    # are not credited as new detections and neighbour chords stay comparable.
    paired = perturb(sections, station_id, 0, whole=whole)
    baseline = {_key(c): c for c in check(paired)["cells"]}
    after = check(changed)["cells"]
    source = next(s for s in paired if s["id"] == station_id)["points_yz_m"]
    original = {round(z, 9): y for y, z in source}
    mid = (source[0][1] + source[-1][1]) / 2
    targets, collateral = [], []
    for cell in after:
        is_changed = (cell["station_id"] == station_id and
                      abs(cell["y_m"] - original[round(cell["z_m"], 9)]) > 1e-9)
        if is_changed and (whole or abs(cell["z_m"] - mid) < 1e-8):
            targets.append(cell)
        if not is_changed:
            collateral.append(cell)
    if not targets:
        raise ValueError(f"Injection changed no target cell: {station_id}")
    covered = lambda c: any(c["availability"].get(name) == "measured" for name in ("plan", "profile"))
    return {"kind": kind, "station_id": station_id, "amount_m": amount,
            "detected": any(c["flagged"] for c in targets),
            "new_detected": any(c["flagged"] and not baseline[_key(c)]["flagged"] for c in targets),
            "independent_covered": any(covered(c) for c in targets),
            "target_cells": len(targets), "collateral_cells": len(collateral),
            "collateral_new_alarms": sum(c["flagged"] and not baseline[_key(c)]["flagged"] for c in collateral)}


def summarize_trials(trials):
    result = {}
    for kind in sorted({t["kind"] for t in trials}):
        rows = [t for t in trials if t["kind"] == kind]
        covered = [t for t in rows if t["independent_covered"]]
        detected, new = sum(t["detected"] for t in rows), sum(t["new_detected"] for t in rows)
        # Missing-view trials count as misses even if a section-only check fires.
        eligible = sum(t["detected"] and t["independent_covered"] for t in rows)
        eligible_new = sum(t["new_detected"] and t["independent_covered"] for t in rows)
        result[kind] = {"trials": len(rows), "raw_flagged": detected, "new_flagged": new,
                        "covered_trials": len(covered), "detected": eligible, "new_detected": eligible_new,
                        "detection_rate": eligible / len(rows), "new_detection_rate": eligible_new / len(rows),
                        "covered_detection_rate": eligible / len(covered) if covered else None,
                        "collateral_cells": sum(t["collateral_cells"] for t in rows),
                        "collateral_new_alarms": sum(t["collateral_new_alarms"] for t in rows)}
    return result


def _alarm_counts(report):
    cells = report["cells"]
    independent = [c for c in cells if any(c["availability"][name] == "measured" for name in ("plan", "profile"))]
    alarms = sum(c["flagged"] for c in cells)
    return {"cells": len(cells), "alarms": alarms, "alarm_rate": alarms / len(cells) if cells else None,
            "independent_cells": len(independent), "independent_alarms": sum(c["flagged"] for c in independent),
            "covered_alarm_rate": sum(c["flagged"] for c in independent) / len(independent) if independent else None,
            "coverage": report["coverage"]}


def unavailable_trials(reason):
    """Keep the six planned trials in the denominator when no measured station exists."""
    return [{"kind": kind, "station_id": None, "amount_m": None, "detected": False,
             "new_detected": False, "independent_covered": False, "target_cells": 0,
             "collateral_cells": 0, "collateral_new_alarms": 0, "unavailable": reason}
            for _ in STATION_FRACTIONS for kind in ("cell_0.1m", "cell_0.2m", "station_5pct")]


def replay_build(case_dir, build, *, reader=False):
    domain = case_dir / "task/domain"
    intake = json.loads((domain / "input/intake.json").read_text())
    spec = json.loads((build / "input_spec.json").read_text())
    sections = load_sections(build)
    if reader:
        # Use frozen reader output before first-hull bottom/deck continuation.
        record = intake["body_plan_reading"]
        by_number = {r["station"]: r for r in record["stations"]}
        from vessel_reconstruction.body_plan_intake import station_number
        sections = [{**s, "source_label": "read", "points_yz_m": by_number[station_number(s["id"])]["curve_y_z_m"]}
                    for s in sections if station_number(s["id"]) in by_number and s.get("source_label") == "read"]
    measured = [s for s in sections if s.get("source_label", "traced") in ("read", "traced")]
    if len(measured) < 2:
        trials = unavailable_trials("Fewer than two measured sections in stored build")
        return {"case": case_dir.name, "build": build.name, "reader_output": reader,
                "unavailable": trials[0]["unavailable"],
                "baseline": {"cells": 0, "alarms": 0, "alarm_rate": None,
                             "independent_cells": 0, "independent_alarms": 0,
                             "covered_alarm_rate": None, "coverage": {}},
                "trials": trials, "detection": summarize_trials(trials), "check_items": []}
    half_beam = max(y for s in measured for y, _ in s["points_yz_m"])
    ppm = float(spec["sections"][0]["calibration"]["pixels_per_metre"])
    hints = next(p["regions"] for p in intake["pages"] if p["page_id"] == intake["spec_page_id"])
    source = domain / "input/source.png"
    grey = view_measure.load_grey(source)
    views = draft_fit.reference_views(grey, hints, ppm)
    def check(rows):
        evidence = detector.measure_evidence(rows, grey, views, half_beam_m=half_beam)
        return detector.detect_cells(rows, evidence=evidence, half_beam_m=half_beam)
    report = check(sections)
    trials = []
    for station in selected_stations(sections):
        for kind, amount in (("cell_0.1m", .1), ("cell_0.2m", .2), ("station_5pct", STATION_ERROR_FRACTION * half_beam)):
            trials.append(measure_trial(sections, station, kind, amount, check))
    digest = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
    return {"case": case_dir.name, "build": build.name, "reader_output": reader,
            "half_beam_m": half_beam, "pixels_per_metre": ppm,
            "source_sha256": digest(source), "sections_sha256": digest(build / "extracted_sections.json"),
            "view_calibrations": {k: v["calibration"] for k, v in views.items()},
            "baseline": _alarm_counts(report), "trials": trials, "detection": summarize_trials(trials),
            "check_items": report["check_items"]}


def aggregate(rows):
    cells = sum(r["baseline"]["cells"] for r in rows)
    alarms = sum(r["baseline"]["alarms"] for r in rows)
    return {"builds": len(rows), "cells": cells, "alarms": alarms, "alarm_rate": alarms / cells if cells else None,
            "detection": summarize_trials([t for r in rows for t in r["trials"]])}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work", type=Path, default=DEFAULT_WORK)
    parser.add_argument("--output", type=Path, default=Path("work/cross-view-outliers.json"))
    args = parser.parse_args()
    rows = []
    for round_name in ROUNDS:
        cases = sorted((args.work / round_name).glob("*-L?"))
        if len(cases) != 5:
            raise ValueError(f"Expected five cases in {round_name}, got {len(cases)}")
        for case in cases:
            delivered = delivered_build(case)
            for build in stored_builds(case):
                row = replay_build(case, build)
                row["delivered"] = build == delivered
                rows.append(row)
                print(case.name, build.name, json.dumps(row["baseline"]), flush=True)
    bue_case = args.work / "autocal-live-6/bue_girl"
    bue = replay_build(bue_case, delivered_build(bue_case), reader=True)
    result = {"method": detector.METHOD, "protocol": "docs/HULL_FAIRING.md section 7",
              "parameters": {"minimum_tolerance_m": detector.MIN_TOLERANCE_M,
                             "half_beam_fraction": detector.HALF_BEAM_FRACTION,
                             "pixel_tolerance": detector.PIXEL_TOLERANCE,
                             "neighbour_height_fraction": detector.NEIGHBOUR_HEIGHT_FRACTION,
                             "section_tolerance_factor": detector.SECTION_TOLERANCE_FACTOR},
              "delivered": aggregate([r for r in rows if r["delivered"]]),
              "all_builds": aggregate(rows), "bue_girl": bue, "rows": rows,
              "engineering_approved": False}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
    print(json.dumps({k: result[k] for k in ("delivered", "all_builds")}, indent=2), flush=True)


if __name__ == "__main__":
    main()
