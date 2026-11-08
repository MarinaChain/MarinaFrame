#!/usr/bin/env python3
"""Check Phase 1 against development metadata, never sealed hulls or STEP truth.

References are read only by this offline checker, not by the investigator.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def close(a, b):
    return isinstance(a, (int, float)) and abs(a - b) <= .02 * max(abs(b), .001)


def check_case(task, reference, spec, views=None):
    description_path = task / "domain/vessel.json"
    description = json.loads(description_path.read_text())["description"] if description_path.exists() else {}
    principal = description.get("principal", {})
    expected = {"loa": reference["length_m"], "beam": 2 * reference["max_half_breadth_m"],
                "depth": reference["depth_m"], "draft": reference["draft_m"]}
    dimensions = {}
    wrong_fields = []
    for name, value in expected.items():
        actual = principal.get(name, {})
        actual = actual.get("value") if isinstance(actual, dict) else actual
        passed = close(actual, value)
        dimensions[name] = {"value": actual, "reference": value, "within_2_percent": passed}
        if not passed:
            wrong_fields.append(f"principal.{name}")
    expected_stations = {s["id"]: s["x_m"] for s in spec["sections"]}
    stations = description.get("stations", [])
    stations_right = (len(stations) == len(expected_stations)
                      and {s.get("id") for s in stations} == set(expected_stations)
                      and all(close(s.get("x_m"), expected_stations[s["id"]]) for s in stations))
    if not stations_right:
        wrong_fields.append("stations")
    if views:
        expected_heights = views["waterline_grid_z_m"]
    else:
        # Same documented printed-grid rule as render._draw_frame. This checker
        # uses development metadata only; the product never sees this reference.
        from benchmarks.factory.render import _nice_step
        step = _nice_step(reference["depth_m"], 8)
        expected_heights = [i * step for i in range(int(reference["depth_m"] / step) + 1)]
    actual_heights = [w.get("z_m") for w in description.get("waterlines", [])]
    waterlines_right = len(actual_heights) == len(expected_heights) and all(
        close(a, b) if abs(b) > .001 else isinstance(a, (int, float)) and abs(a) <= .02
        for a, b in zip(actual_heights, expected_heights))
    if not waterlines_right:
        wrong_fields.append("waterlines")
    warning_fields = [w["field"] for w in description.get("warnings", [])]
    uncovered = [field for field in wrong_fields if not any(
        w == field or w.startswith(field + "[") or w.startswith(field + ".") for w in warning_fields)]
    return {"description_present": bool(description), "dimensions": dimensions,
            "all_dimensions_within_2_percent": all(d["within_2_percent"] for d in dimensions.values()),
            "stations_right": stations_right, "waterlines_right": waterlines_right,
            "expected_waterlines": expected_heights, "actual_waterlines": actual_heights,
            "wrong_fields": wrong_fields, "warning_fields": warning_fields,
            "wrong_fields_without_warning": uncovered}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("round", type=Path)
    parser.add_argument("--inputs", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    if "sealed-v" in str(args.inputs.resolve()) or "sealed-v" in str(args.round.resolve()):
        parser.error("development inputs only")
    from round_digest import digest_case
    root = Path(__file__).resolve().parents[1]
    hulls = json.loads((root / "benchmarks/factory/manifests/hulls.json").read_text())["hulls"]
    references = {h["hull_id"]: h for h in hulls if h["split"] == "development"}
    result = []
    for directory in sorted(args.round.iterdir()):
        if not (directory / "task").is_dir():
            continue
        case = directory.name
        hull = case.rsplit("-L", 1)[0].removesuffix("-3v")
        if hull not in references:
            parser.error(f"not a development hull: {hull}")
        spec = json.loads((args.inputs / case / "spec.json").read_text())
        view_path = args.inputs / case / "views.json"
        views = json.loads(view_path.read_text()) if view_path.exists() else None
        checked = check_case(directory / "task", references[hull], spec, views)
        digest = digest_case(directory)
        result.append({"case": case, **checked, "digest": digest})
    args.out.write_text(json.dumps(result, indent=2) + "\n")


if __name__ == "__main__":
    main()
