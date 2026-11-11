"""Independent analytic checks of actual exported STEP at and between stations.

Unlike the historical station diagnostic, this comparator requests original
feature elevations, dense interior elevations, endpoints, and every extra CAD
cut vertex. Missing, multiple, or unsupported boundaries remain failed checks.
The three fixtures are engineering primitives, not benchmark hull families.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import time

import numpy as np

from .audit_exported_step_v2 import ordinate_intersection


COMPARATOR_VERSION = "analytic_step_stations_midstations_knots_v1"
BOUNDARY_TOLERANCE_M = 1e-9


def analytic_fixture(name: str) -> dict:
    if name == "off_grid_narrow_peak":
        return {"name": name, "xs": [0., 5., 10.], "bases": [0., 0., 0.],
                "heights": [4., 4., 4.], "counts": [129, 129, 129],
                "coefficients": [[1., 0., 0., 2.]] * 3,
                "peak_t": 1 / 64, "peak_half_width_t": 1 / 128, "chine_t": .62,
                "kind": "linear_chine_triangle", "maximum_error_gate_m": 1e-8,
                "volume_relative_gate": 1e-9,
                "description": "A two-metre half-breadth peak between the old 33-height sample positions; exact volume 81.25 m3 and beam 6 m."}
    if name == "chines_unequal_heights_zero_keels":
        return {"name": name, "xs": [0., 3.7, 9.6], "bases": [-.4, .25, -.1],
                "heights": [2.6, 3.35, 2.85], "counts": [17, 65, 97],
                "coefficients": [[0., 1.1, -.22, 2.4], [.12, 1.3, .15, 2.], [0., .9, -.1, 1.8]],
                "peak_t": .019, "peak_half_width_t": .002, "chine_t": .62,
                "kind": "linear_chine_triangle", "maximum_error_gate_m": 1e-8,
                "volume_relative_gate": 1e-9,
                "description": "Nonuniform stations, different source point counts and elevation domains, alternating zero/finite keels, sharp narrow feature and upper chine."}
    if name == "smooth_unequal_sampling":
        return {"name": name, "xs": [0., 4., 10.], "bases": [-.1, .2, 0.],
                "heights": [2.4, 3., 2.8], "counts": [65, 97, 129],
                "coefficients": [[.4, .8, .6], [.8, .3, .9], [.6, .7, .4]],
                "kind": "quadratic", "maximum_error_gate_m": .0011,
                "volume_relative_gate": .001,
                "description": "Analytic quadratic ordinates sampled independently at 65/97/129 points; gate includes the declared 1 mm CAD bound and input discretization."}
    raise ValueError(f"Unknown analytic fixture: {name}")


FIXTURE_NAMES = ("off_grid_narrow_peak", "chines_unequal_heights_zero_keels", "smooth_unequal_sampling")


def _ordinates(t: np.ndarray, coefficients: np.ndarray, fixture: dict) -> np.ndarray:
    a, b, c = coefficients[:3]
    if fixture["kind"] == "quadratic":
        return a + b * t + c * t ** 2
    triangle = np.maximum(0, 1 - np.abs(t - fixture["peak_t"]) / fixture["peak_half_width_t"])
    return a + b * t + c * np.maximum(0, t - fixture["chine_t"]) + coefficients[3] * triangle


def _feature_knots(fixture: dict) -> np.ndarray:
    if fixture["kind"] == "quadratic":
        return np.asarray([0., 1.])
    peak, half = fixture["peak_t"], fixture["peak_half_width_t"]
    return np.asarray([0., peak - half, peak, peak + half, fixture["chine_t"], 1.])


def measured_sections(fixture: dict) -> list[dict]:
    """Source observations; no production correspondence implementation used."""
    sections = []
    for i, (x, base, height, count, coefficients) in enumerate(zip(
            fixture["xs"], fixture["bases"], fixture["heights"], fixture["counts"], fixture["coefficients"])):
        t = np.unique(np.concatenate((np.linspace(0, 1, count), _feature_knots(fixture))))
        # Keep the original peak reproducer's exact 129-point input intact.
        if fixture["name"] == "off_grid_narrow_peak":
            t = np.linspace(0, 1, count)
        y = _ordinates(t, np.asarray(coefficients), fixture)
        sections.append({"id": f"analytic-{i}", "x_m": x,
                         "points_yz_m": np.column_stack((y, base + height * t)).tolist()})
    return sections


def reference_at(fixture: dict, x: float) -> tuple[float, float, np.ndarray]:
    xs = np.asarray(fixture["xs"])
    base = float(np.interp(x, xs, fixture["bases"]))
    height = float(np.interp(x, xs, fixture["heights"]))
    coefficients = np.asarray(fixture["coefficients"])
    interpolated = np.asarray([np.interp(x, xs, coefficients[:, j]) for j in range(coefficients.shape[1])])
    return base, height, interpolated


def reference_area(fixture: dict, x: float) -> float:
    _, height, coefficients = reference_at(fixture, x)
    a, b, c = coefficients[:3]
    if fixture["kind"] == "quadratic":
        integral = a + b / 2 + c / 3
    else:
        integral = (a + b / 2 + c * (1 - fixture["chine_t"]) ** 2 / 2
                    + coefficients[3] * fixture["peak_half_width_t"])
    return float(2 * height * integral)


def reference_metrics(fixture: dict) -> dict:
    xs = fixture["xs"]
    # Height and ordinates interpolate linearly in each bay, so area is a
    # quadratic in x. Simpson integration is analytically exact here.
    volume = sum((right - left) * (reference_area(fixture, left)
                 + 4 * reference_area(fixture, (left + right) / 2)
                 + reference_area(fixture, right)) / 6 for left, right in zip(xs[:-1], xs[1:]))
    t = _feature_knots(fixture)
    maximum_y = max(float(np.max(_ordinates(t, np.asarray(c), fixture))) for c in fixture["coefficients"])
    return {"volume_m3": float(volume), "beam_m": 2 * maximum_y,
            "length_m": xs[-1] - xs[0],
            "depth_m": max(b + h for b, h in zip(fixture["bases"], fixture["heights"])) - min(fixture["bases"])}


def read_step(step_path: Path):
    from OCP.STEPControl import STEPControl_Reader
    from OCP.IFSelect import IFSelect_RetDone
    reader = STEPControl_Reader()
    if reader.ReadFile(str(step_path)) != IFSelect_RetDone:
        raise ValueError("Cannot read exported STEP")
    reader.TransferRoots()
    return reader.OneShape()


def cut_segments(shape, x_m: float) -> dict:
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Section
    from OCP.gp import gp_Pln, gp_Pnt, gp_Dir
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopAbs import TopAbs_EDGE
    from OCP.BRepAdaptor import BRepAdaptor_Curve
    from OCP.TopoDS import TopoDS
    from OCP.GeomAbs import GeomAbs_Line, GeomAbs_BSplineCurve

    section = BRepAlgoAPI_Section(shape, gp_Pln(gp_Pnt(x_m * 1000, 0, 0), gp_Dir(1, 0, 0)), False)
    section.Build()
    if not section.IsDone():
        return {"status": "cut_failed", "segments": [], "curve_types": {}, "unsupported": []}
    explorer = TopExp_Explorer(section.Shape(), TopAbs_EDGE)
    segments, unsupported, kinds = [], [], {}
    while explorer.More():
        curve = BRepAdaptor_Curve(TopoDS.Edge_s(explorer.Current()))
        kind = str(curve.GetType())
        kinds[kind] = kinds.get(kind, 0) + 1
        first, last = curve.FirstParameter(), curve.LastParameter()
        parameters = [first, last]
        if curve.GetType() == GeomAbs_BSplineCurve:
            spline = curve.BSpline()
            if spline.Degree() != 1:
                unsupported.append(f"{kind}:degree={spline.Degree()}")
                explorer.Next()
                continue
            parameters += [spline.Knot(i) for i in range(1, spline.NbKnots() + 1) if first < spline.Knot(i) < last]
        elif curve.GetType() != GeomAbs_Line:
            unsupported.append(kind)
            explorer.Next()
            continue
        vertices = [curve.Value(p) for p in sorted(set(parameters))]
        segments.extend((([a.Y() / 1000, a.Z() / 1000], [b.Y() / 1000, b.Z() / 1000]))
                        for a, b in zip(vertices[:-1], vertices[1:]))
        explorer.Next()
    return {"status": "unsupported_boundary" if unsupported else "complete" if segments else "no_boundary",
            "segments": segments, "curve_types": kinds, "unsupported": unsupported}


def _boundary(segments: list, z: float, *, closure: bool, expected_zero: bool) -> dict:
    hit = ordinate_intersection(segments, z)
    if closure and hit["horizontal_intervals_y_m"]:
        # At a declared endpoint a top/bottom closure spans the complete beam.
        # Compare its outer edge explicitly instead of treating its interior
        # as several competing hull boundaries or skipping that ordinate.
        candidates = hit["boundary_candidates_y_m"] + [p[1] for p in hit["horizontal_intervals_y_m"]]
        return {**hit, "status": "complete", "y_m": max(candidates), "closure_endpoint": True}
    if expected_zero and hit["status"] == "absent":
        return {**hit, "status": "complete", "y_m": 0., "zero_area_absence": True}
    return hit


def audit_step(step_path: Path, fixture: dict) -> dict:
    import cadquery as cq
    shape = read_step(step_path)
    reloaded = cq.Shape.cast(shape)
    from vessel_reconstruction.geometry import metrics_for
    observed = metrics_for(reloaded)
    expected = reference_metrics(fixture)
    xs = np.asarray(fixture["xs"])
    locations = sorted(set(xs.tolist() + ((xs[:-1] + xs[1:]) / 2).tolist()))
    records = []
    for x in locations:
        base, height, coefficients = reference_at(fixture, x)
        cut = cut_segments(shape, x)
        # Probe all input knots as well as feature knots and dense elevations.
        source_t = [(np.asarray(s["points_yz_m"])[:, 1] - b) / h
                    for s, b, h in zip(measured_sections(fixture), fixture["bases"], fixture["heights"])]
        t = np.unique(np.concatenate([np.linspace(0, 1, 1025), _feature_knots(fixture), *source_t]))
        extra_z = [p[1] for segment in cut["segments"] for p in segment
                   if base <= p[1] <= base + height]
        z = np.unique(np.concatenate((base + height * t, extra_z)))
        expected_y = _ordinates((z - base) / height, coefficients, fixture)
        errors, measured_y, unresolved, closures, zero_absences = [], [], [], 0, 0
        for elevation, reference_y in zip(z, expected_y):
            if cut["status"] != "complete":
                unresolved.append({"z_m": float(elevation), "status": cut["status"]})
                continue
            endpoint = abs(elevation - base) <= BOUNDARY_TOLERANCE_M or abs(elevation - base - height) <= BOUNDARY_TOLERANCE_M
            hit = _boundary(cut["segments"], float(elevation), closure=endpoint, expected_zero=reference_y == 0)
            if hit["status"] != "complete":
                unresolved.append({"z_m": float(elevation), **hit})
                continue
            errors.append(float(hit["y_m"] - reference_y))
            measured_y.append(float(hit["y_m"]))
            closures += int(hit.get("closure_endpoint", False))
            zero_absences += int(hit.get("zero_area_absence", False))
        complete = not unresolved and len(errors) == len(z)
        records.append({"x_m": float(x), "location_type": "station_or_terminal_cap" if x in xs else "between_stations",
                        "status": "complete" if complete else "incomplete",
                        "requested_ordinates": len(z), "compared_ordinates": len(errors),
                        "maximum_absolute_error_m": max(map(abs, errors)) if complete else None,
                        "rms_error_m": float(np.sqrt(np.mean(np.square(errors)))) if complete else None,
                        "reference_section_area_m2": reference_area(fixture, x),
                        "cad_section_area_m2": float(2 * np.trapezoid(measured_y, z)) if complete else None,
                        "section_area_error_m2": float(2 * np.trapezoid(measured_y, z) - reference_area(fixture, x)) if complete else None,
                        "closure_endpoints_compared": closures, "zero_area_absences_compared": zero_absences,
                        "curve_types": cut["curve_types"], "unsupported_boundaries": cut["unsupported"],
                        "unresolved_ordinates": unresolved})
    complete = all(record["status"] == "complete" for record in records)
    maximum = max(r["maximum_absolute_error_m"] for r in records) if complete else None
    volume_error = abs(observed["volume_m3"] - expected["volume_m3"]) / expected["volume_m3"]
    return {"fixture": fixture, "comparator_version": COMPARATOR_VERSION,
            "step_sha256": hashlib.sha256(step_path.read_bytes()).hexdigest(),
            "complete": complete, "maximum_absolute_error_m": maximum,
            "maximum_station_error_m": max((r["maximum_absolute_error_m"] for r in records if r["location_type"] == "station_or_terminal_cap"), default=None) if complete else None,
            "maximum_between_station_error_m": max((r["maximum_absolute_error_m"] for r in records if r["location_type"] == "between_stations"), default=None) if complete else None,
            "maximum_section_area_error_m2": max(abs(r["section_area_error_m2"]) for r in records) if complete else None,
            "reference_metrics": expected, "actual_reimported_step_metrics": observed,
            "volume_relative_error": volume_error, "beam_absolute_error_m": abs(observed["beam_m"] - expected["beam_m"]),
            "passed": bool(complete and maximum <= fixture["maximum_error_gate_m"]
                           and volume_error <= fixture["volume_relative_gate"]
                           and abs(observed["beam_m"] - expected["beam_m"]) <= 1e-8
                           and observed["cad_valid"] and observed["solid_count"] == 1),
            "cuts": records}


def run(out: Path) -> dict:
    from vessel_reconstruction.geometry import build_hull, export_geometry, approximation_summary
    if out.exists():
        raise FileExistsError("Retain the previous evidence; choose a fresh output directory")
    out.mkdir(parents=True)
    records = []
    for name in FIXTURE_NAMES:
        fixture = analytic_fixture(name)
        destination = out / name
        destination.mkdir()
        started = time.perf_counter()
        shape, normalized = build_hull(measured_sections(fixture))
        _, metrics = export_geometry(shape, destination)
        result = audit_step(destination / "model.step", fixture)
        result["approximation"] = approximation_summary(normalized)
        result["mesh_metrics"] = {k: v for k, v in metrics.items() if k.startswith("mesh_")}
        result["wall_seconds"] = time.perf_counter() - started
        (destination / "reference_fixture.json").write_text(json.dumps(fixture, indent=2) + "\n")
        (destination / "cad_sections.json").write_text(json.dumps(normalized, indent=2) + "\n")
        records.append(result)
    report = {"comparator_version": COMPARATOR_VERSION, "all_passed": all(r["passed"] for r in records),
              "comparison_scope": "Actual reimported STEP boundary; original knots, CAD cut vertices, 1025 height samples, terminal closures, interior stations, and each bay midpoint against explicit analytic ground truth",
              "model_scope": "Declared linearly interpolated normalized-height ruled envelope; no claim about unknown real geometry between source stations",
              "cases": records}
    (out / "report.json").write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    report = run(parser.parse_args().out)
    print(json.dumps({"all_passed": report["all_passed"], "cases": [
        {k: case[k] for k in ("complete", "passed", "maximum_station_error_m", "maximum_between_station_error_m", "volume_relative_error", "beam_absolute_error_m")}
        | {"name": case["fixture"]["name"]} for case in report["cases"]]}, indent=2))
