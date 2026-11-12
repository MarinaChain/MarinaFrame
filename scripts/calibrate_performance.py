"""Fit the predeclared one-parameter correction on exposed development ships only.

Inputs are existing evaluator JSON files, not data directories. No downloads,
ship discovery or blind scoring. Writes a new draft report under ignored work/.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
import hashlib
import json
from pathlib import Path

from vessel_reconstruction.holtrop import HoltropHull
from vessel_reconstruction.performance_calibration import (
    CalibrationPoint, fit_alpha, full_form_weight, leave_one_ship_out,
)
from vessel_reconstruction.performance_compare import evaluate_case

DEVELOPMENT_SHIPS = {"KCS", "JBC", "KVLCC2"}


def prepare_points(cases: list[dict]) -> list[CalibrationPoint]:
    """Reject unknown ships and duplicate conditions; select only baseline 1984."""
    return [point for _, _, point in _records(cases)]


def _records(cases: list[dict]) -> list[tuple[dict, dict, CalibrationPoint]]:
    records = []
    seen = set()
    for case in cases:
        if case.get("ship") not in DEVELOPMENT_SHIPS:
            raise ValueError("only exposed development ships KCS/JBC/KVLCC2 are permitted")
        if case.get("method") != "holtrop_1984":
            continue
        if case.get("scale") != "model":
            raise ValueError("development fit requires model scale")
        result = evaluate_case(case)
        hull = HoltropHull(**case["hull"])
        for row in result["rows"]:
            # A repeated speed with distinct water/hull conditions is legitimate.
            key = (case["ship"], json.dumps(case["hull"], sort_keys=True),
                   json.dumps(case["water"], sort_keys=True), row["speed_ms"])
            if key in seen:
                raise ValueError("duplicate development condition")
            seen.add(key)
            resistance = row["resistance"]
            dynamic_area = (0.5 * case["water"]["density_kg_m3"] * row["speed_ms"]**2
                            * resistance["wetted_surface_m2"])
            sensitivity = (full_form_weight(hull.cb_lwl) * (resistance["form_factor"]-1)
                           * resistance["friction_resistance_n"] / dynamic_area)
            point = CalibrationPoint(case["ship"], row["estimated_ct"], sensitivity,
                                     row["measured_ct"])
            records.append((case, row, point))
    return records


def calibrate(cases: list[dict]) -> dict:
    records = _records(cases)
    points = [point for _, _, point in records]
    fit = fit_alpha(points)
    folds = leave_one_ship_out(points)
    rows = []
    for case, baseline, point in records:
        row = dict(ship=point.ship, speed_ms=baseline["speed_ms"], source=baseline["source"],
                   baseline_ct_error_percent=baseline["ct_error_percent"],
                   baseline_pe_error_percent=baseline["effective_power_error_percent"])
        # Preserve the measured published S0 versus estimated mesh-area distinction.
        reference_ratio = (baseline["resistance"]["wetted_surface_m2"]
                           / next(m["reference_surface_m2"] for m in case["measurements"]
                                  if m["speed_ms"] == baseline["speed_ms"]))
        for name, alpha in (("fit", fit.alpha), ("loo", folds[point.ship].alpha)):
            ct = point.baseline_ct-alpha*point.sensitivity_ct
            row[f"{name}_ct_error_percent"] = 100*(ct/point.measured_ct-1)
            row[f"{name}_pe_error_percent"] = 100*(ct/point.measured_ct*reference_ratio-1)
        rows.append(row)
    summaries = {}
    for ship in fit.ships:
        ship_rows = [r for r in rows if r["ship"] == ship]
        summaries[ship] = {
            key: sum(abs(r[key]) for r in ship_rows)/len(ship_rows)
            for key in rows[0] if key.endswith("error_percent")}
    aggregate = {key: sum(s[key] for s in summaries.values())/len(summaries)
                 for key in next(iter(summaries.values()))}
    gate = (all(s["loo_ct_error_percent"] <= 10 for s in summaries.values())
            and aggregate["loo_ct_error_percent"] < aggregate["baseline_ct_error_percent"])
    return dict(engineering_approved=False, fit=asdict(fit),
                leave_one_ship_out={k: asdict(v) for k, v in folds.items()},
                rows=rows, ship_mae_percent=summaries, equal_ship_mae_percent=aggregate,
                diagnostic_gate_passed=gate)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    cases = []
    provenance = []
    for path in args.input:
        raw = path.read_bytes()
        data = json.loads(raw)
        cases.extend(data["cases"])
        provenance.append(dict(path=str(path), sha256=hashlib.sha256(raw).hexdigest()))
    result = calibrate(cases)
    if set(result["fit"]["ships"]) != DEVELOPMENT_SHIPS:
        raise ValueError("final fit requires exactly KCS, JBC and KVLCC2")
    result["inputs"] = provenance
    with args.output.open("x") as stream:
        json.dump(result, stream, indent=2, allow_nan=False)
        stream.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
