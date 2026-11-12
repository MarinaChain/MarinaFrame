"""Offline performance evaluator for explicit, source-labelled JSON cases.

No network, ship discovery, calibration or parameter fitting occurs here.
The independent evaluator supplies their own input; development never needs it.
See docs/plans/2026-11-12-performance-evaluator.md for the versioned contract.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import sys

from .performance import compare_resistance


def _require_keys(value: dict, allowed: set[str], required: set[str], context: str) -> None:
    if not isinstance(value, dict):
        raise ValueError(f"{context} must be an object")
    unknown = set(value) - allowed
    missing = required - set(value)
    if unknown or missing:
        raise ValueError(f"{context}: unknown keys {sorted(unknown)}, missing keys {sorted(missing)}")


def evaluate_case(case: dict) -> dict:
    """Evaluate one explicitly scaled hull without altering empirical constants."""
    from .holtrop import HoltropHull, holtrop_resistance

    required = {"schema_version", "ship", "scale", "method", "particulars_source",
                "hull", "water", "measurements"}
    _require_keys(case, required | {"propeller", "sfoc_g_per_kwh", "notes"}, required, "case")
    if case["schema_version"] != 1 or case["scale"] not in ("model", "ship"):
        raise ValueError("schema_version must be 1 and scale must be model or ship")
    if case["method"] not in ("holtrop_mennen_1982", "holtrop_1984"):
        raise ValueError("method must name a supported Holtrop version")
    for name in ("ship", "particulars_source"):
        if not isinstance(case[name], str) or not case[name].strip():
            raise ValueError(f"{name} must be nonempty text")
    if not isinstance(case["measurements"], list) or not case["measurements"]:
        raise ValueError("measurements must be a nonempty list")
    if "sfoc_g_per_kwh" in case and "propeller" not in case:
        raise ValueError("sfoc_g_per_kwh requires explicit propeller inputs")
    water = case["water"]
    water_keys = {"density_kg_m3", "kinematic_viscosity_m2_s"}
    _require_keys(water, water_keys, water_keys, "water")
    try:
        hull = HoltropHull(**case["hull"])
    except TypeError as error:
        raise ValueError(f"invalid hull fields: {error}") from error
    rows = []
    for measurement in case["measurements"]:
        keys = {"speed_ms", "ct", "reference_surface_m2", "source"}
        _require_keys(measurement, keys, keys, "measurement")
        if not isinstance(measurement["source"], str) or not measurement["source"].strip():
            raise ValueError("each measurement must have source text")
        resistance = holtrop_resistance(
            hull, speed_ms=measurement["speed_ms"], water_density_kg_m3=water["density_kg_m3"],
            kinematic_viscosity_m2_s=water["kinematic_viscosity_m2_s"],
            method=case["method"], include_correlation_allowance=case["scale"] == "ship")
        comparison = compare_resistance(
            estimated_resistance_n=resistance.total_resistance_n,
            estimated_wetted_surface_m2=resistance.wetted_surface_m2,
            measured_ct=measurement["ct"],
            measured_reference_surface_m2=measurement["reference_surface_m2"],
            speed_ms=measurement["speed_ms"], water_density_kg_m3=water["density_kg_m3"],
            scale=case["scale"], source=measurement["source"])
        row = asdict(comparison)
        warnings = list(resistance.validity_warnings)
        range_warnings = list(resistance.range_warnings)
        if case["scale"] == "model":
            warning = "Model scale: empirical ship regression; ship correlation allowance disabled."
            warnings.append(warning)
            range_warnings.append(warning)
        row.update(ship=case["ship"], speed_ms=measurement["speed_ms"], method=case["method"],
                   resistance=asdict(resistance), validity_warnings=warnings,
                   range_warnings=range_warnings,
                   status="outside_range" if range_warnings else "within_reported_range")
        if "propeller" in case:
            row["propulsion"] = _evaluate_propulsion(case, resistance, measurement["speed_ms"])
        rows.append(row)
    return {"ship": case["ship"], "engineering_approved": False,
            "particulars_source": case["particulars_source"], "input_case": case,
            "rows": rows,
            "mean_absolute_ct_error_percent": sum(abs(r["ct_error_percent"]) for r in rows) / len(rows),
            "mean_absolute_effective_power_error_percent":
                sum(abs(r["effective_power_error_percent"]) for r in rows) / len(rows)}


def _evaluate_propulsion(case: dict, resistance, speed_ms: float) -> dict:
    """Integration is kept separate from resistance scoring."""
    from .holtrop import HoltropHull, HoltropPropeller, holtrop_interaction
    from .propeller import match_propeller

    propeller = case["propeller"]
    keys = {"diameter_m", "blade_count", "pitch_diameter_ratio", "expanded_area_ratio",
            "shaft_efficiency"}
    _require_keys(propeller, keys, keys, "propeller")
    water = case["water"]
    interaction = holtrop_interaction(
        HoltropHull(**case["hull"]),
        HoltropPropeller(diameter_m=propeller["diameter_m"],
                        blade_area_ratio=propeller["expanded_area_ratio"],
                        pitch_diameter_ratio=propeller["pitch_diameter_ratio"]),
        speed_ms=speed_ms, water_density_kg_m3=water["density_kg_m3"],
        kinematic_viscosity_m2_s=water["kinematic_viscosity_m2_s"], method=case["method"],
        include_correlation_allowance=case["scale"] == "ship")
    matched = match_propeller(
        resistance_n=resistance.total_resistance_n, speed_ms=speed_ms,
        water_density_kg_m3=water["density_kg_m3"],
        diameter_m=propeller["diameter_m"], blade_count=propeller["blade_count"],
        pitch_diameter_ratio=propeller["pitch_diameter_ratio"],
        expanded_area_ratio=propeller["expanded_area_ratio"],
        thrust_deduction=interaction.thrust_deduction, wake_fraction=interaction.wake_fraction,
        relative_rotative_efficiency=interaction.relative_rotative_efficiency,
        shaft_efficiency=propeller["shaft_efficiency"],
        sfoc_g_per_kwh=case.get("sfoc_g_per_kwh"))
    return {"interaction": asdict(interaction), "matching": asdict(matched)}


def markdown_report(cases: list[dict]) -> str:
    lines = ["# Performance comparison — draft", "", "engineering_approved: false", "",
             "Errors = 100 × (estimate − measured) / measured.", "",
             "| Ship | Method | Speed m/s | CT estimate | CT measured | CT error % | PE error % | Status |",
             "|---|---|---:|---:|---:|---:|---:|---|"]
    for case in cases:
        for row in case["rows"]:
            ship = str(case["ship"]).replace("|", "\\|").replace("\n", " ")
            lines.append(f"| {ship} | {row['method']} | {row['speed_ms']:.6g} | "
                         f"{row['estimated_ct']:.7g} | {row['measured_ct']:.7g} | "
                         f"{row['ct_error_percent']:+.3f} | {row['effective_power_error_percent']:+.3f} | "
                         f"{row['status']} |")
        lines += ["", f"## {case['ship']}: sources and limits", "",
                  f"Particulars: {case['particulars_source']}"]
        for row in case["rows"]:
            lines.append(f"- {row['speed_ms']:.6g} m/s: {row['source']}")
            lines.extend(f"  - {warning}" for warning in row["validity_warnings"])
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--markdown", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.output.exists() or args.markdown.exists() or args.output == args.markdown:
            raise ValueError("output paths must be distinct and must not already exist")
        raw = args.input.read_bytes()
        data = json.loads(raw)
        _require_keys(data, {"cases"}, {"cases"}, "input")
        if not isinstance(data["cases"], list) or not data["cases"]:
            raise ValueError("cases must be a nonempty list")
        cases = [evaluate_case(case) for case in data["cases"]]
        output = {"schema_version": 1, "engineering_approved": False,
                  "input_sha256": hashlib.sha256(raw).hexdigest(), "cases": cases}
        # Exclusive creation prevents accidental replacement of another score.
        with args.output.open("x") as stream:
            json.dump(output, stream, indent=2, allow_nan=False)
            stream.write("\n")
        with args.markdown.open("x") as stream:
            stream.write(markdown_report(cases))
    except (ValueError, TypeError, OSError) as error:
        print(f"performance comparison: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
