"""Calibrate the STEP-cut evaluator on generic known geometry only.

These shapes are measurement fixtures, not MarinaFrame reconstruction attempts.
The production solver, held-out inputs, inferred CAD and reference files are not
read. All native work holds the shared admission lock. Raw fixtures and measured
ordinates are retained with hashes; checks cover terminal and interior cuts.
"""
from __future__ import annotations

import argparse
import fcntl
import importlib.util
import json
import os
from pathlib import Path
import time


HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("v04_measurement", HERE / "v04_step_measurement.py")
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


def run(output):
    output.mkdir(parents=True, exist_ok=False)
    queue = time.monotonic()
    with Path(f"/tmp/marinaframe-native-admission-{os.geteuid()}.lock").open("a+b") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        queue_wait = time.monotonic() - queue
        started = time.monotonic()
        import cadquery as cq
        import numpy as np

        box = cq.Workplane("XY").box(2300, 2500, 1700, centered=(False, True, False)).val()
        outer = cq.Workplane("XY").box(1000, 2000, 2000, centered=(False, True, False)).val()
        hole = cq.Workplane("XY").box(1200, 500, 1000, centered=(False, True, False)).translate((-100, 0, 500)).val()
        tunnel = outer.cut(hole)
        positions = [0., 1.4, 3.1]
        lower = [.7, 1.05, .85]
        upper = [1.6, 2.1, 1.9]
        height = 2.2
        wires = []
        for x, lo, hi in zip(positions, lower, upper):
            vertices = [cq.Vector(x*1000, -lo*1000, 0), cq.Vector(x*1000, lo*1000, 0),
                        cq.Vector(x*1000, hi*1000, height*1000), cq.Vector(x*1000, -hi*1000, height*1000)]
            wires.append(cq.Wire.makePolygon(vertices, close=True))
        frustum = cq.Solid.makeLoft(wires, ruled=True)
        areas = [height * (lo + hi) for lo, hi in zip(lower, upper)]
        frustum_volume = sum((b-a)*(u+v)/2 for a, b, u, v in zip(positions[:-1], positions[1:], areas[:-1], areas[1:]))
        fixtures = [
            {"id": "instrument_box", "shape": box, "xs": [0., 1.15, 2.3],
             "height": 1.7, "volume": 2.3*2.5*1.7,
             "width": lambda x, z: np.full_like(z, 1.25)},
            {"id": "instrument_ruled_frustum", "shape": frustum,
             "xs": [0., .7, 1.4, 2.25, 3.1], "height": height,
             "volume": frustum_volume,
             "width": lambda x, z: np.interp(x, positions, lower) +
                       (np.interp(x, positions, upper)-np.interp(x, positions, lower))*z/height},
            {"id": "instrument_internal_tunnel", "shape": tunnel, "xs": [0., .5, 1.],
             "height": 2., "volume": 3.5, "width": lambda x, z: np.full_like(z, 1.),
             "expect_competing": True, "expect_interior_horizontal": True},
        ]
        freeze_path = output / "instrument_freeze.json"
        m.write(freeze_path, {"frozen": True, "frozen_utc": m.utc(),
                              "arms": {"instrument_calibration": {"kind": "known geometry; no reconstruction"}},
                              "measurement_tool_sha256": m.digest(HERE / "v04_step_measurement.py"),
                              "calibration_script_sha256": m.digest(__file__),
                              "cadquery_version": cq.__version__})
        records = []
        for fixture in fixtures:
            directory = output / fixture["id"]
            directory.mkdir()
            step = directory / "fixture.step"
            cq.exporters.export(fixture["shape"], str(step))
            input_file = directory / "measurement_spec.json"
            m.write(input_file, {"vessel_id": fixture["id"],
                                 "kind": "measurement calibration fixture, not an inference input",
                                 "sections": [{"id": f"cut_{i}", "x_m": x, "z_min_m": 0., "z_max_m": fixture["height"]}
                                              for i, x in enumerate(fixture["xs"])]})
            attempt = directory / "fixture_receipt.json"
            trace_file = None
            if fixture["id"] == "instrument_box":
                trace_file = directory / "known_selected_trace.json"
                m.write(trace_file, {"sections": [{"id": f"cut_{i}", "x_m": x,
                    "points_yz_m": [[1.25, .4], [1.2505, .8], [1.2512, 1.2]]}
                    for i, x in enumerate(fixture["xs"])]})
            m.write(attempt, {"arm": "instrument_calibration", "case_id": fixture["id"],
                              "attempt_id": fixture["id"], "finalized": True, "finalized_utc": m.utc(),
                              "input_spec_sha256": m.digest(input_file),
                              "kind": "exported generic geometry fixture; no production inference",
                              "output_files": [{"path": str(p), "sha256": m.digest(p)}
                                               for p in [step, input_file] + ([trace_file] if trace_file else [])]})
            measured_path = directory / "measurements.json"
            m.cut_step(step, input_file, measured_path, freeze_path, attempt, trace_file)
            measured = m.read(measured_path)
            errors = []
            unresolved = 0
            for section in measured["sections"]:
                z = np.array(section["z_m"])
                expected = fixture["width"](section["x_m"], z)
                actual = np.array([np.nan if y is None else y for y in section["y_m"]])
                unresolved += int(np.sum(~np.isfinite(actual)))
                errors.extend(np.abs(actual[np.isfinite(actual)]-expected[np.isfinite(actual)]).tolist())
            maximum_mm = max(errors)*1000 if errors else None
            volume_error = abs(measured["volume_m3"]-fixture["volume"])
            competing = sum(s["competing_interior_ordinates"] for s in measured["sections"])
            horizontal = sum(s["interior_horizontal_overlap_ordinates"] for s in measured["sections"])
            ok = (measured["shape_valid"] and measured["solid_count"] == 1 and unresolved == 0 and
                  maximum_mm is not None and maximum_mm <= .001 and volume_error <= 1e-8)
            ok &= bool(competing) == fixture.get("expect_competing", False)
            ok &= bool(horizontal) == fixture.get("expect_interior_horizontal", False)
            trace_check = None
            if trace_file:
                trace_result = measured["selected_trace"]
                trace_check = (trace_result["passed"] is False and trace_result["unresolved_samples"] == 0
                               and trace_result["required_samples"] == 9
                               and all(abs(actual-expected) < 1e-7
                                       for row in trace_result["sections"]
                                       for actual, expected in zip(row["distances_mm"], [0., .5, 1.2])))
                ok &= trace_check
            records.append({"fixture": fixture["id"], "expected_volume_m3": fixture["volume"],
                            "measured_volume_m3": measured["volume_m3"], "absolute_volume_error_m3": volume_error,
                            "required_cuts": len(fixture["xs"]), "required_ordinates": 4097*len(fixture["xs"]),
                            "terminal_cuts_included": True, "unresolved_ordinates": unresolved,
                            "maximum_half_breadth_error_mm": maximum_mm, "passed": bool(ok),
                            "competing_interior_ordinates": competing,
                            "interior_horizontal_overlap_ordinates": horizontal,
                            "known_nearest_trace_distances_0_05_12_mm_passed": trace_check,
                            "step_sha256": m.digest(step), "measurements_sha256": m.digest(measured_path)})
        indices, values, clamped = m.bounded_segment(np.array([0.]), -1e-6, -.998e-6, 1000., 1001.)
        clamp_ok = len(values) == 1 and abs(values[0]-1001.) < 1e-9 and clamped == 1
        # Binding rejection is checked before any geometry import/measurement.
        fixture_dir = output / fixtures[0]["id"]
        original_receipt = m.read(fixture_dir / "fixture_receipt.json")
        binding_checks = {}
        for label, altered in [
            ("unlisted_step", {**original_receipt, "output_files": []}),
            ("wrong_case", {**original_receipt, "case_id": "another_instrument_fixture"}),
            ("wrong_spec", {**original_receipt, "input_spec_sha256": "0"*64}),
        ]:
            bad_receipt = output / f"binding_probe_{label}.json"
            m.write(bad_receipt, altered)
            try:
                m.bind_inputs(fixture_dir / "fixture.step", fixture_dir / "measurement_spec.json", freeze_path, bad_receipt)
            except ValueError:
                binding_checks[label] = True
            else:
                binding_checks[label] = False
        result = {"schema_version": "marinaframe-measurement-instrument-calibration-1",
                  "completed_utc": m.utc(), "queue_wait_seconds": queue_wait,
                  "execution_wall_seconds": time.monotonic()-started,
                  "fixtures": records, "near_horizontal_clamp_passed": bool(clamp_ok),
                  "binding_rejections_passed": binding_checks,
                  "all_passed": all(r["passed"] for r in records) and bool(clamp_ok) and all(binding_checks.values()),
                  "heldout_outputs_or_references_read": False,
                  "production_solver_executed": False,
                  "scope": "Checks finite straight/ruled geometry and terminal/interior plane coverage; not a proof for arbitrary curved/unsupported topology."}
        m.write(output / "calibration_result.json", result)
        fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
    return {"calibration_result": str(output / "calibration_result.json"),
            "all_passed": result["all_passed"], "heldout_scoring_performed": False}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(run(args.out), sort_keys=True))


if __name__ == "__main__":
    main()
