"""Post-lock independent v0.4 evaluation. Imports no reconstruction solver.

All receipt adaptation, measurements and scores are new files. Original inference
tasks, seals and references remain unchanged. Native measurement is serial under
the same admission lock as inference, with its own separate resource accounting.
"""
from __future__ import annotations

import argparse
from collections import Counter
import fcntl
import importlib.util
import json
import math
import os
from pathlib import Path
import statistics
import subprocess
import sys
import time
import traceback

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("measurement", HERE / "v04_step_measurement.py")
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
read, write, digest, utc = m.read, m.write, m.digest, m.utc
B = Path("/tmp/marinaframe-v04-independent")
INPUT = B / "inference_v2"
REF = B / "sealed_reference"
SEAL = B / "public_v2/seal_receipt.json"
LIVE = Path("/tmp/marinaframe-v04-final-live/runs")
ASSIST = Path("/tmp/marinaframe-v04-assistant-runs")
CURRENT = Path("/tmp/marinaframe-v04-runtime-8916e68")
CAD_ARMS = ["frozen_02_deterministic", "frozen_03_deterministic",
            "new_python_deterministic", "new_rust_deterministic", "live_deepseek"]
ARM_ROOTS = {
    "frozen_02_deterministic": B / "legacy_runs_v2_001/frozen_02_deterministic",
    "frozen_03_deterministic": B / "legacy_runs_v2_001/frozen_03_deterministic",
    "new_python_deterministic": B / "new_python_det_v2_001",
    "new_rust_deterministic": B / "new_rust_det_v2_001",
    "simple_pixel_baseline": B / "pixel_predictions_v2_001",
    "live_deepseek": LIVE,
    "assistant_operated": ASSIST,
}


def verify_external_lock(root, path, expected_sha):
    if digest(path) != expected_sha:
        raise ValueError(f"Changed output lock: {path}")
    lock = read(path)
    rows = ([{"path": k, "sha256": v} for k, v in lock["file_sha256"].items()]
            if "file_sha256" in lock else lock["files"])
    for row in rows:
        if digest(root / row["path"]) != row["sha256"]:
            raise ValueError(f"Changed locked file: {row['path']}")
    actual = {str(p.relative_to(root)) for p in root.rglob("*") if p.is_file() and p != path}
    if actual != {r["path"] for r in rows}:
        raise ValueError(f"Output inventory differs from lock: {root}")
    return lock, rows


def entries():
    for root in [B / "legacy_runs_v2_001", B / "new_python_det_v2_001",
                 B / "new_rust_det_v2_001", B / "pixel_predictions_v2_001"]:
        commitments = root / "attempt_commitments.json"
        lock_file = root / ("legacy_output_lock.json" if "legacy" in root.name else "output_lock.json")
        lock = read(lock_file)
        if digest(commitments) != lock["attempt_commitments_sha256"]:
            raise ValueError("Attempt commitment changed")
        for row in read(commitments)["attempts"]:
            path = Path(row["receipt_path"])
            if digest(path) != row["receipt_sha256"]:
                raise ValueError("Attempt receipt changed")
            a = read(path)
            a["original_receipt"] = {"path": str(path), "sha256": digest(path)}
            a["output_lock"] = {"path": str(lock_file), "sha256": digest(lock_file)}
            a["task_path"] = str(path.parent / "task")
            a["input_spec_sha256"] = a.get("input_spec_sha256", a.get("input_sha256"))
            yield a
    live_lock, live_files = verify_external_lock(LIVE, LIVE / "output-lock.json",
        "aa6c7fb5a6cb333b68ee9b1f2d1ba3a33f7ba063cc4aba0c1917fe73fa79070d")
    for case in sorted(p.name for p in INPUT.iterdir()):
        receipt = LIVE / case / "attempt.json"
        d = read(receipt)
        yield {"arm": "live_deepseek", "case_id": case, "attempt_id": f"live_deepseek__{case}__primary_001",
               "finalized": True, "finalized_utc": live_lock["locked_utc"],
               "input_spec_sha256": digest(INPUT / case / "spec.json"),
               "original_receipt": {"path": str(receipt), "sha256": digest(receipt)},
               "output_lock": {"path": str(LIVE / "output-lock.json"), "sha256": digest(LIVE / "output-lock.json")},
               "task_path": str(LIVE / case / "task"), "execution_wall_seconds": d.get("wall_seconds"),
               "output_files": [{"path": str(LIVE / r["path"]), "sha256": r["sha256"]}
                                for r in live_files if r["path"].startswith(case + "/")]}
    assist_lock, assist_files = verify_external_lock(ASSIST, ASSIST / "output-lock.json",
        "754113d9c1ab85081c286badbacb1c4ffcd816d129b31fb87bf6adccd69a9bb9")
    for case in read(ASSIST / "assistant-report.json")["cases"]:
        cid = case["case_id"]
        yield {"arm": "assistant_operated", "case_id": cid,
               "attempt_id": f"assistant_operated__{cid}__primary_001",
               "finalized": True, "finalized_utc": assist_lock["created_utc"],
               "input_spec_sha256": digest(INPUT / cid / "spec.json"),
               "original_receipt": {"path": str(ASSIST / "assistant-report.json"), "sha256": digest(ASSIST / "assistant-report.json")},
               "output_lock": {"path": str(ASSIST / "output-lock.json"), "sha256": digest(ASSIST / "output-lock.json")},
               "task_path": str(ASSIST / cid), "operator_actions": case["intervention_count"],
               "execution_wall_seconds": case["native_cli_elapsed_seconds"],
               "wall_scope": "Sum of native CLI waits for this case; shared assistant session effort is reported separately.",
               "output_files": [{"path": str(ASSIST / r["path"]), "sha256": r["sha256"]}
                                for r in assist_files if r["path"].startswith(cid + "/")]}


def summarize_attempt(a):
    task = Path(a["task_path"])
    state = read(task / "state.json").get("state", {}) if (task / "state.json").exists() else {}
    domain = read(task / "domain/state.json") if (task / "domain/state.json").exists() else {}
    result = read(task / "result.json") if (task / "result.json").exists() else {}
    status = state.get("status", result.get("status"))
    revision = state.get("revision_id", f"r{domain.get('revision', 0):04d}")
    candidate = (state.get("domain", {}).get("current_candidate") if "domain" in state
                 else domain.get("last_valid_candidate"))
    current = bool(candidate and candidate.get("valid") and candidate.get("revision_id") == revision)
    if state.get("generation_id") and candidate:
        current &= candidate.get("generation_id") == state["generation_id"]
    if a["arm"] == "frozen_02_deterministic":
        build_path = task if (task / "model.step").exists() else None
        current = bool(build_path and status == "review_required")
        ready = current
    else:
        build_path = task / candidate["path"] if current else None
        validation = domain.get("validation") or {}
        ready = bool(current and status == "awaiting_human_review" and validation.get("geometry_checks_passed")
                     and validation.get("generation_id") == candidate.get("generation_id")
                     and validation.get("revision_id") == candidate.get("revision_id"))
    if build_path and not (build_path / "model.step").is_file():
        raise ValueError("Current candidate names missing STEP")
    errors = list(domain.get("input_errors", [])) + list(result.get("gaps", []))
    for value in domain.get("catalog", {}).values():
        errors += value.get("baseline_gaps", [])
    for build in domain.get("builds", []):
        errors += build.get("gaps", [])
    unique = {json.dumps(e, sort_keys=True): e for e in errors}
    errors = list(unique.values())
    supervision = []
    for event_path in sorted((task / "events").glob("*.json")):
        event = read(event_path)
        if event.get("kind") == "worker_result" and "supervision" in event.get("payload", {}):
            p = event["payload"]
            supervision.append({"operation": p.get("operation"), **p["supervision"]})
    resource_file = Path(a["original_receipt"]["path"]).parent / "resource_usage.json"
    usage = read(resource_file).get("usage", {}) if resource_file.exists() else {}
    queue = a.get("queue_wait_seconds")
    if supervision:
        queue = sum(float(r.get("queue_wait_seconds", 0)) for r in supervision)
    counters = state.get("counters") or {k: state.get(k) for k in
        ["actions", "policy_calls", "builds", "rejections", "operator_actions", "live_calls_reserved"]}
    cutoff = bool(a.get("interrupted_truncated", a.get("supervisory_timeout", False)))
    known_terminal = status in {"review_required", "awaiting_human_review", "blocked", "abstained",
                               "no_progress", "failed", "resource_limited", "budget_exhausted"}
    return {"arm": a["arm"], "case_id": a["case_id"], "attempt_id": a["attempt_id"],
            "attempted": True, "process_finalized": a["finalized"],
            "terminal_record_present": known_terminal, "workflow_status": status,
            "termination_reason": state.get("termination_reason"),
            "exit_code": a.get("exit_code"), "interrupted_truncated": cutoff,
            "execution_failed": status in {None, "failed"},
            "no_progress": status == "no_progress",
            "resource_limited": status in {"resource_limited", "budget_exhausted"},
            "current_candidate": current, "ready_for_review": ready,
            "exported_steps": [{"path": str(p), "sha256": digest(p)} for p in sorted(task.rglob("model.step"))],
            "current_step": str(build_path / "model.step") if build_path else None,
            "selected_trace_file": str(build_path / "extracted_sections.json") if build_path else None,
            "current_revision": revision, "current_generation": candidate.get("generation_id") if current and candidate else None,
            "rendered_views": domain.get("rendered_views", []),
            "diagnostics": errors, "counters": counters,
            "engineering_approved": bool(state.get("engineering_approved", result.get("review", {}).get("engineering_approved", False))),
            "resources": {"execution_wall_seconds": a.get("execution_wall_seconds"),
                          "wall_scope": a.get("wall_scope", "CLI execution wall; concurrent campaign, not controlled latency"),
                          "native_queue_wait_seconds": queue,
                          "controller_worker_supervision": supervision,
                          "cli_cpu_seconds": usage.get("ru_utime", 0)+usage.get("ru_stime", 0) if usage else None,
                          "cli_descendant_max_rss_kib": usage.get("ru_maxrss"),
                          "task_disk_bytes": sum(p.stat().st_size for p in task.rglob("*") if p.is_file()),
                          "wait4": usage},
            "original_receipt": a["original_receipt"], "output_lock": a["output_lock"]}


def prepare(out):
    out.mkdir(parents=True, exist_ok=False)
    inputs = m._u.verify_inputs(INPUT, SEAL)
    m._u.verify_references(REF, SEAL)
    frozen = read(CURRENT / "freeze.json")
    for path, sha in frozen["files"].items():
        if digest(CURRENT / path) != sha:
            raise ValueError("Frozen runtime changed")
    calibration = B / "instrument_check_003/calibration_result.json"
    if not read(calibration)["all_passed"]:
        raise ValueError("Measurement calibration failed")
    write(out / "scoring_freeze.json", {"frozen": True, "frozen_utc": utc(),
        "kind": "Post-lock scoring admission; runtime freezes and original output locks remain separately bound",
        "coordinator_scoring_GO_received": True,
        "application_commit": "8916e68f4c175bdab291d7c0bf2978862be8915d",
        "runtime_freeze_sha256": digest(CURRENT / "freeze.json"),
        "arms": {arm: {"output_root": str(path)} for arm, path in ARM_ROOTS.items()},
        "inputs": inputs, "reference_manifest_sha256": digest(REF / "reference_manifest.json"),
        "measurement_instrument_sha256": digest(HERE / "v04_step_measurement.py"),
        "scoring_script_sha256": digest(__file__),
        "calibration": {"path": str(calibration), "sha256": digest(calibration)}})
    index = []
    for a in entries():
        case, arm = a["case_id"], a["arm"]
        spec_file = INPUT / case / "spec.json"
        if digest(spec_file) != a["input_spec_sha256"]:
            raise ValueError("Attempt does not bind exact sealed spec")
        p = out / arm / case
        write(p / "finalized_attempt.json", a)
        m._u.require_frozen_finalized(out / "scoring_freeze.json", p / "finalized_attempt.json")
        if arm == "simple_pixel_baseline":
            row = {"arm": arm, "case_id": case, "attempt_id": a["attempt_id"],
                   "attempted": True, "process_finalized": True, "CAD_exported": False,
                   "prediction_path": str(Path(a["original_receipt"]["path"]).parent / "pixel_predictions.json"),
                   "execution_wall_seconds": a["execution_wall_seconds"], "original_receipt": a["original_receipt"]}
        else:
            row = summarize_attempt(a)
        write(p / "workflow.json", row)
        index.append({"arm": arm, "case_id": case, "directory": str(p),
                      "step": row.get("current_step"), "trace": row.get("selected_trace_file")})
    if len(index) != 92:
        raise ValueError(f"Expected all 92 primary executions, found {len(index)}")
    write(out / "attempt_index.json", {"prepared_utc": utc(), "attempts": index,
        "primary_attempt_count": 92, "malformed_intake_preflight_count_separate": 30})
    return {"prepared": len(index), "measurements_required": sum(bool(r["step"]) for r in index)}


def measure_one(out, arm, case):
    directory = out / arm / case
    row = read(directory / "workflow.json")
    start = time.monotonic()
    with Path(f"/tmp/marinaframe-native-admission-{os.geteuid()}.lock").open("a+b") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        queue = time.monotonic()-start
        result = m.cut_step(row["current_step"], INPUT / case / "spec.json", directory / "measurements.json",
            out / "scoring_freeze.json", directory / "finalized_attempt.json", row["selected_trace_file"])
        fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
    return {"arm": arm, "case_id": case, "queue_wait_seconds": queue,
            "wall_seconds_including_queue": time.monotonic()-start,
            "measurement_sha256": digest(directory / "measurements.json"),
            "selected_trace_passed": result["selected_trace"]["passed"]}


def run_measurements(out):
    results = []
    for row in read(out / "attempt_index.json")["attempts"]:
        if not row["step"]:
            continue
        directory = Path(row["directory"])
        receipt = directory / "measurement_execution.json"
        if receipt.exists():
            raise ValueError("Never silently rerun or replace an existing measurement execution")
        command = [sys.executable, str(Path(__file__).resolve()), "measure-one", "--out", str(out),
                   "--arm", row["arm"], "--case", row["case_id"]]
        start = time.monotonic()
        with (directory / "measurement.stdout.log").open("wb") as stdout, (directory / "measurement.stderr.log").open("wb") as stderr:
            process = subprocess.Popen(command, stdout=stdout, stderr=stderr, start_new_session=True)
            timed_out = False
            try:
                process.wait(timeout=300)
            except subprocess.TimeoutExpired:
                timed_out = True
                import signal
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
        result = {"arm": row["arm"], "case_id": row["case_id"], "command": command,
                  "exit_code": process.returncode, "instrument_timeout": timed_out,
                  "wall_seconds": time.monotonic()-start, "completed_utc": utc(),
                  "measurement_exists": (directory / "measurements.json").exists(),
                  "instrument_failure_is_not_product_failure": True}
        write(receipt, result)
        results.append(result)
        print(json.dumps({k: result[k] for k in ["arm", "case_id", "exit_code", "wall_seconds"]}), flush=True)
    write(out / "measurement_executions.json", {"measurements": results})
    return {"measurements": len(results), "instrument_failures": sum(r["exit_code"] != 0 for r in results)}


def geometry_score(measured, reference):
    import numpy as np
    measured_ids = [s["id"] for s in measured["sections"]]
    reference_ids = [s["id"] for s in reference["sections"]]
    if len(set(measured_ids)) != len(measured_ids) or len(set(reference_ids)) != len(reference_ids):
        raise ValueError("Duplicate station IDs cannot establish coverage")
    if not set(measured_ids).issubset(reference_ids):
        raise ValueError("Unexpected station IDs in measurements")
    sections = {s["id"]: s for s in measured["sections"]}
    squared, details, worst = [], [], None
    unresolved, required = 0, 4097*len(reference["sections"])
    for target in reference["sections"]:
        s = sections.get(target["id"])
        if not s:
            unresolved += 4097
            details.append({"id": target["id"], "unresolved": 4097})
            continue
        z = np.array(s["z_m"])
        expected_z = np.linspace(float(target["z_m"][0]), float(target["z_m"][-1]), 4097)
        if (len(z) != 4097 or len(s["y_m"]) != 4097 or not np.all(np.isfinite(z))
                or not np.all(np.diff(z) > 0) or not np.array_equal(z, expected_z)
                or not math.isfinite(float(s["x_m"])) or float(s["x_m"]) != float(target["x_m"])):
            raise ValueError("Incorrect station measurement grid")
        if any(y is not None and not math.isfinite(float(y)) for y in s["y_m"]):
            raise ValueError("Nonfinite measurement must be represented explicitly as unresolved")
        actual = np.array([np.nan if y is None else y for y in s["y_m"]])
        truth = np.interp(z, target["z_m"], target["y_m"])
        error = np.abs(actual-truth)
        valid = np.isfinite(error)
        unresolved += int(np.sum(~valid))
        err_px = error[valid]*reference["pixels_per_metre"]
        squared.extend((err_px**2).tolist())
        local = None
        if valid.any():
            i = int(np.nanargmax(error))
            local = {"section_id": s["id"], "x_m": s["x_m"], "z_m": float(z[i]),
                     "actual_y_m": float(actual[i]), "reference_y_m": float(truth[i]),
                     "error_mm": float(error[i]*1000), "error_px": float(error[i]*reference["pixels_per_metre"])}
            if worst is None or local["error_px"] > worst["error_px"]:
                worst = local
        details.append({"id": s["id"], "required": 4097, "unresolved": int(np.sum(~valid)),
                        "rms_px_resolved_only": float(np.sqrt(np.mean(err_px**2))) if valid.any() else None,
                        "worst": local})
    rms = math.sqrt(sum(squared)/len(squared)) if squared else None
    maximum = worst["error_px"] if worst else None
    volume = abs(measured["volume_m3"]-reference["reference_volume_m3"])/reference["reference_volume_m3"]
    gates = reference["gates"]
    checks = {"valid_single_solid": bool(measured["shape_valid"] and measured["solid_count"] == 1),
              "complete_section_coverage": unresolved == 0,
              "volume_within_3_percent": volume <= gates["volume_relative"],
              "section_rms_within_2_pixels": rms is not None and rms <= gates["section_rms_px"],
              "section_max_within_4_pixels": maximum is not None and maximum <= gates["section_max_px"]}
    return {"independent_geometry_pass": all(checks.values()), "checks": checks,
            "full_span_grid_identity_checked": True,
            "reference_volume_m3": reference["reference_volume_m3"], "reimported_volume_m3": measured["volume_m3"],
            "volume_relative_error": volume, "section_rms_px_resolved_only": rms,
            "section_max_px_resolved_only": maximum, "required_ordinates": required,
            "unresolved_ordinates": unresolved, "resolved_coverage": (required-unresolved)/required,
            "source_pixels_per_metre": reference["pixels_per_metre"], "worst": worst, "sections": details,
            "competing_interior_ordinates": sum(s["competing_interior_ordinates"] for s in measured["sections"]),
            "interior_horizontal_overlap_ordinates": sum(s["interior_horizontal_overlap_ordinates"] for s in measured["sections"])}


def diagnostic_score(row, reference):
    # Exact engine blocking-gap vocabulary; a keyword in arbitrary prose cannot
    # establish a correct refusal. Baseline catalog gaps omit severity, but these
    # specific gap kinds denote an unavailable required source condition.
    kinds = {d.get("kind") for d in row.get("diagnostics", [])
             if d.get("severity", "blocking") == "blocking"}
    if reference["expected"] == "candidate":
        return {}
    negative = reference.get("negative")
    if negative == "missing_calibration":
        required_kinds = {"missing_scale"}
    elif negative == "missing_data":
        required_kinds = {"missing_curve_segment"}
    elif negative in {"ambiguous", "ambiguity", "unsupported_topology"}:
        required_kinds = {"ambiguous_curve"}
    elif reference.get("complete_3d_gold") is False:
        required_kinds = {"missing_units", "symmetry_unresolved", "symmetry_evidence_missing", "insufficient_sections"}
    else:
        # Diagnostic labels are read from the sealed reference; unmatched labels
        # are an evaluator error requiring explicit inspection, never success.
        raise ValueError(f"Unrecognized diagnostic label {negative}")
    relevant = bool(kinds & required_kinds)
    safe = bool(not row["ready_for_review"] and relevant and not row["execution_failed"] and not row["interrupted_truncated"])
    explicit = bool(safe and row["workflow_status"] in {"blocked", "abstained"})
    return {"relevant_blocking_diagnostic": relevant, "matching_blocking_diagnostic_kinds": sorted(kinds & required_kinds),
            "diagnostic_evidence_basis": "Exact structured engine input/catalog gap kinds, not prose keyword matching",
            "safe_diagnostic_nonacceptance": safe,
            "explicit_correct_refusal_or_request": explicit,
            "no_progress_with_relevant_diagnostic": safe and row["no_progress"],
            "incorrect_acceptance_under_original_label": row["ready_for_review"],
            "scope_ambiguous_diagnostic": row["case_id"] == "q_b970f41e",
            "sensitivity_primary_negative_member": row["case_id"] != "q_b970f41e"}


def pixel_score(row, reference):
    import numpy as np
    prediction = read(row["prediction_path"])
    result = {**row, "expected": reference["expected"], "reference_kind": "source_only_no_CAD",
              "diagnostics": prediction["diagnostics"], "required_rows": 0, "resolved_rows": 0,
              "ambiguous_rows": 0, "missing_rows": 0}
    squared, worst = [], None
    targets = {s["id"]: s for s in reference.get("sections", [])}
    details = []
    for sec in prediction["sections"]:
        for name, key in [("required_rows", "rows_required"), ("resolved_rows", "rows_resolved"),
                          ("ambiguous_rows", "ambiguous_rows"), ("missing_rows", "missing_rows")]:
            result[name] += sec[key]
        if reference["expected"] != "candidate":
            continue
        ref = targets[sec["id"]]
        points = sec["points"]
        z = np.array([p["z_m"] for p in points]); y = np.array([p["y_m"] for p in points])
        truth = np.interp(z, ref["z_m"], ref["y_m"])
        err = np.abs(y-truth)*reference["pixels_per_metre"]
        squared.extend((err**2).tolist())
        if len(err):
            i = int(np.argmax(err))
            local = {"section_id": sec["id"], "z_m": float(z[i]), "error_px": float(err[i])}
            if worst is None or local["error_px"] > worst["error_px"]:
                worst = local
        details.append({"id": sec["id"], "required_rows": sec["rows_required"], "resolved_rows": sec["rows_resolved"]})
    result.update({"resolved_coverage": result["resolved_rows"]/result["required_rows"] if result["required_rows"] else None,
                   "section_rms_px_resolved_only": math.sqrt(sum(squared)/len(squared)) if squared else None,
                   "section_max_px_resolved_only": worst["error_px"] if worst else None,
                   "worst": worst, "sections": details, "CAD_success": False})
    return result


def stats(values):
    values = [v for v in values if v is not None]
    return {"n": len(values), "sum": sum(values), "median": statistics.median(values) if values else None,
            "min": min(values) if values else None, "max": max(values) if values else None}


def admitted_measurement(directory, row, out):
    measured_path = directory / "measurements.json"
    measured = read(measured_path)
    execution = read(directory / "measurement_execution.json")
    receipt = json.loads((directory / "measurement.stdout.log").read_text())
    freeze = read(out / "scoring_freeze.json")
    if (execution["exit_code"] != 0 or execution["instrument_timeout"]
            or receipt["measurement_sha256"] != digest(measured_path)
            or measured["case_id"] != row["case_id"]
            or measured["attempt_id"] != row["attempt_id"]
            or measured["step_sha256"] != digest(row["current_step"])
            or measured["input_spec_sha256"] != digest(INPUT / row["case_id"] / "spec.json")
            or measured["instrument_sha256"] != freeze["measurement_instrument_sha256"]
            or measured["selected_trace"]["file_sha256"] != digest(row["selected_trace_file"])):
        raise ValueError("Measurement identity or finalized execution binding mismatch")
    return measured


def aggregate(out):
    m._u.verify_inputs(INPUT, SEAL)
    m._u.verify_references(REF, SEAL)
    records = []
    for entry in read(out / "attempt_index.json")["attempts"]:
        directory = Path(entry["directory"])
        row = read(directory / "workflow.json")
        reference = read(REF / "cases" / f"{row['case_id']}.json")
        if row["arm"] == "simple_pixel_baseline":
            score = pixel_score(row, reference)
        else:
            score = {**row, "expected": reference["expected"], "family_key": reference.get("family_key"),
                     "convention": reference.get("convention"), "negative": reference.get("negative"),
                     "geometry": None, "selected_trace": None, "full_supported_pass": False,
                     **diagnostic_score(row, reference)}
            measured_path = directory / "measurements.json"
            if measured_path.exists():
                measured = admitted_measurement(directory, row, out)
                score["measurement_sha256"] = digest(measured_path)
                score["selected_trace"] = {k: v for k, v in measured["selected_trace"].items() if k != "sections"}
                if reference["expected"] == "candidate":
                    score["geometry"] = geometry_score(measured, reference)
                    score["full_supported_pass"] = bool(row["ready_for_review"] and
                        score["geometry"]["independent_geometry_pass"] and score["selected_trace"]["passed"])
            if entry["step"] and not measured_path.exists():
                score["instrument_unavailable"] = True
            score["supported_false_refusal"] = reference["expected"] == "candidate" and not row["ready_for_review"]
        write(directory / "score.json", score)
        records.append(score)
    summaries = {}
    for arm in ARM_ROOTS:
        rows = [r for r in records if r["arm"] == arm]
        if arm == "simple_pixel_baseline":
            positive = [r for r in rows if r["expected"] == "candidate"]
            summaries[arm] = {"attempted": len(rows), "CAD_exports": 0, "CAD_successes": 0,
                "supported_source_cases": len(positive),
                "supported_resolved_rows": sum(r["resolved_rows"] for r in positive),
                "supported_required_rows": sum(r["required_rows"] for r in positive),
                "per_case": [{k: r[k] for k in ["case_id", "resolved_coverage", "section_rms_px_resolved_only", "section_max_px_resolved_only"]} for r in positive]}
            continue
        positives = [r for r in rows if r["expected"] == "candidate"]
        negatives = [r for r in rows if r["expected"] == "refuse"]
        authentic = [r for r in rows if r["expected"] == "refuse_or_request_evidence"]
        def counts(cohort):
            return {"attempted": len(cohort), "terminal_records": sum(r["terminal_record_present"] for r in cohort),
                "exported_candidates": sum(bool(r["exported_steps"]) for r in cohort),
                "current_candidates": sum(r["current_candidate"] for r in cohort),
                "ready_for_review": sum(r["ready_for_review"] for r in cohort),
                "full_supported_pass": sum(r["full_supported_pass"] for r in cohort),
                "independent_geometry_pass": sum(bool(r["geometry"] and r["geometry"]["independent_geometry_pass"]) for r in cohort),
                "explicit_correct_refusals": sum(r.get("explicit_correct_refusal_or_request", False) for r in cohort),
                "safe_diagnostic_nonacceptance": sum(r.get("safe_diagnostic_nonacceptance", False) for r in cohort),
                "incorrect_acceptances_original_label": sum(r.get("incorrect_acceptance_under_original_label", False) for r in cohort),
                "false_refusals": sum(r.get("supported_false_refusal", False) for r in cohort),
                "no_progress": sum(r["no_progress"] for r in cohort),
                "interrupted_truncated": sum(r["interrupted_truncated"] for r in cohort),
                "resource_limited": sum(r["resource_limited"] for r in cohort),
                "execution_failed": sum(r["execution_failed"] for r in cohort),
                "workflow_statuses": dict(Counter(r["workflow_status"] for r in cohort))}
        family = {}
        for f in sorted({r["family_key"] for r in positives}):
            group = [r for r in positives if r["family_key"] == f]
            family[f] = {"attempted": len(group), "correct": sum(r["full_supported_pass"] for r in group),
                         "all_attempts_correct": all(r["full_supported_pass"] for r in group),
                         "paired_complete_family": len(group) == 2,
                         "case_ids": [r["case_id"] for r in group]}
        measured = [r for r in positives if r["geometry"]]
        worst = max(measured, key=lambda r: r["geometry"]["section_max_px_resolved_only"], default=None)
        summaries[arm] = {"all": counts(rows), "supported": counts(positives), "negative_original_four": counts(negatives),
            "negative_sensitivity_excluding_scope_ambiguous": counts([r for r in negatives if r["case_id"] != "q_b970f41e"]),
            "authentic_no_3d_gold": counts(authentic), "families": family,
            "paired_families_all_correct": sum(v["paired_complete_family"] and v["all_attempts_correct"] for v in family.values()),
            "metrics_supported_exports_only": {
                "measured": len(measured), "supported_attempted_denominator": len(positives),
                "volume_relative_error": stats(r["geometry"]["volume_relative_error"] for r in measured),
                "section_rms_px": stats(r["geometry"]["section_rms_px_resolved_only"] for r in measured),
                "section_max_px": stats(r["geometry"]["section_max_px_resolved_only"] for r in measured),
                "selected_trace_max_mm": stats(r["selected_trace"]["max_error_mm"] for r in measured),
                "worst_case": None if worst is None else {"case_id": worst["case_id"], **worst["geometry"]["worst"]}},
            "resources_all_attempts": {
                "execution_wall_seconds": stats(r["resources"]["execution_wall_seconds"] for r in rows),
                "native_queue_wait_seconds": stats(r["resources"]["native_queue_wait_seconds"] for r in rows),
                "cli_cpu_seconds": stats(r["resources"]["cli_cpu_seconds"] for r in rows),
                "cli_descendant_max_rss_kib": stats(r["resources"]["cli_descendant_max_rss_kib"] for r in rows),
                "task_disk_bytes": stats(r["resources"]["task_disk_bytes"] for r in rows),
                "interpretation": "Raw product defaults and concurrency differ. Wall sums are aggregate task exposure, not campaign elapsed time. RSS is the maximum individual waited-for descendant, not a summed process-tree peak."}}
    result = {"schema_version": "marinaframe-independent-v04-scoring-1", "completed_utc": utc(),
              "primary_attempts": len(records), "original_malformed_intake_attempts_separate": 30,
              "arms": summaries, "scoring_freeze_sha256": digest(out / "scoring_freeze.json"),
              "reference_manifest_sha256": digest(REF / "reference_manifest.json"),
              "source_label_note_sha256": digest(B / "evaluation_review_private/source_label_quality_note.json"),
              "all_per_case_scores": [{"arm": r["arm"], "case_id": r["case_id"],
                  "path": str(out / r["arm"] / r["case_id"] / "score.json"),
                  "sha256": digest(out / r["arm"] / r["case_id"] / "score.json")} for r in records]}
    write(out / "summary.json", result)
    return {"summary": str(out / "summary.json"), "primary_attempts": len(records),
            "full_pass_counts": {arm: v["supported"]["full_supported_pass"] for arm, v in summaries.items() if "supported" in v}}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("command", choices=["prepare", "measure-one", "measure-all", "aggregate"])
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--arm"); p.add_argument("--case")
    a = p.parse_args()
    if a.command == "prepare":
        r = prepare(a.out)
    elif a.command == "measure-one":
        r = measure_one(a.out, a.arm, a.case)
    elif a.command == "measure-all":
        r = run_measurements(a.out)
    else:
        r = aggregate(a.out)
    print(json.dumps(r, sort_keys=True))


if __name__ == "__main__":
    main()
