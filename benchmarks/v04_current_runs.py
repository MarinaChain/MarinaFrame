"""Frozen current-arm execution, separate from reference decoding and scoring.

Preparation performs byte/environment checks only. CAD-free pixel predictions
need the confirmed application freeze. Native runs additionally require a GO
receipt for the shared native admission window. Rust owns its per-operation
admission lock; the retained Python harness needs an outer whole-task lock.
"""
from __future__ import annotations

import argparse
import fcntl
import importlib.util
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import time


HERE = Path(__file__).resolve().parent
helper_path = HERE / "v04_legacy_runs.py"
helper_spec = importlib.util.spec_from_file_location("v04_execution_helpers", helper_path)
h = importlib.util.module_from_spec(helper_spec)
helper_spec.loader.exec_module(h)

ROOT = Path("/tmp/marinaframe-v04-independent")
RUNTIME = Path("/tmp/marinaframe-v04-runtime-8916e68")
PYTHON = "/tmp/marinaframe-v04-release-env/bin/python"
EXPECTED_RUNTIME = "a7aea135d54d3873715dc6849dacfd87ae67ab882064add8c708370983a24684"
EXPECTED_BINARY = "071d76828b845d0134e57a3f4c14e48fc2843027cfa45806de5d67767d5b6f72"
EXPECTED_SOURCE = "8916e68f4c175bdab291d7c0bf2978862be8915d"
INPUT_TREE = "56faaf412e89105aac3628792152749d0099106192049d6394cbb30420c438e1"
SCHEMA = "marinaframe-independent-v04-current-execution-1"


def check_runtime():
    manifest_path = RUNTIME / "freeze.json"
    if h.sha(manifest_path) != EXPECTED_RUNTIME:
        raise ValueError("Application freeze changed")
    manifest = h.load(manifest_path)
    if manifest["source_commit"] != EXPECTED_SOURCE:
        raise ValueError("Source revision does not match confirmed freeze")
    for name, digest in manifest["files"].items():
        path = RUNTIME / name
        if not path.resolve().is_relative_to(RUNTIME) or h.sha(path) != digest:
            raise ValueError("Frozen runtime file changed: " + name)
    if h.sha(RUNTIME / "marinaframe") != EXPECTED_BINARY:
        raise ValueError("Frozen executable changed")
    python_files = {str(p.relative_to(RUNTIME)) for p in (RUNTIME / "src").rglob("*.py")}
    if not python_files.issubset(manifest["files"]):
        raise ValueError("Uncommitted Python module in frozen worker source")
    return manifest


def environment_receipt():
    query = (
        "import importlib.metadata as m,importlib.util,json,platform,sys;"
        "print(json.dumps({'python':sys.version,'executable':sys.executable,"
        "'platform':platform.platform(),"
        "'module_origin':importlib.util.find_spec('vessel_reconstruction').origin,"
        "'packages':{d.metadata['Name']:d.version for d in m.distributions()}}))"
    )
    data = json.loads(subprocess.check_output(
        [PYTHON, "-c", query], cwd=RUNTIME, env=h.runtime_env(RUNTIME), text=True,
    ))
    if Path(data["module_origin"]).resolve() != (RUNTIME / "src/vessel_reconstruction/__init__.py").resolve():
        raise ValueError("Python resolved a different domain engine")
    return {**data, "python_executable_sha256": h.sha(Path(PYTHON).resolve()),
            "PYTHONPATH": str(RUNTIME / "src")}


def check_inputs():
    seal = h.load(ROOT / "public_v2/seal_receipt.json")
    rows = h.inventory(ROOT / "inference_v2")
    if rows != seal["files"] or h.tree_sha(rows) != INPUT_TREE:
        raise ValueError("Inference input seal changed")
    index = h.load(ROOT / "public_v2/implementation_inputs.json")
    if index["input_tree_sha256"] != INPUT_TREE:
        raise ValueError("Implementation input index changed")
    if any(set(case) != {"case_id", "input", "drawing"} for case in index["cases"]):
        raise ValueError("Execution input index includes non-inference metadata")
    return index


def prepare(path):
    runtime = check_runtime()
    check_inputs()
    if path.exists():
        raise ValueError("Preserve the existing execution plan; use a new path")
    plans = {
        "new_python_deterministic": {
            "command_template": [PYTHON, "-m", "vessel_reconstruction", "agent", "run",
                                 "{input_spec}", "--out", "{task_directory}", "--policy", "deterministic"],
            "admission": "outer_whole_task",
            "policy": "retained Python deterministic raw product default",
            "policy_limits": "Unchanged TaskLimits defaults; no CLI override",
            "view_workflow": "Python default oblique view",
            "supervisory_watchdog_seconds": 900,
            "watchdog_kind": "external evaluation resource boundary, not a product default",
            "CAD_capability": True,
        },
        "new_rust_deterministic": {
            "command_template": [str(RUNTIME / "marinaframe"), "run", "--task", "{task_directory}",
                                 "--source", "{input_spec}", "--worker-python", PYTHON,
                                 "--worker-source", str(RUNTIME / "src"), "--policy", "deterministic"],
            "admission": "Rust_internal_per_operation",
            "policy": "Rust deterministic raw product default",
            "policy_limits": "No aggregate product task wall cap; finite worker bounds and original no-progress/retry/storage guards",
            "view_workflow": "Rust default body and oblique views",
            "supervisory_watchdog_seconds": 900,
            "watchdog_kind": "external evaluation resource boundary, not a product default",
            "CAD_capability": True,
        },
        "simple_pixel_baseline": {
            "command_template": [PYTHON, str(HERE / "v04_sealed_eval.py"), "pixel-baseline",
                                 "--spec", "{input_spec}", "--out", "{prediction_file}",
                                 "--freeze", "{execution_plan}"],
            "admission": "none_no_CAD",
            "policy": "Frozen independent dark-run row-median baseline; threshold 128 and original coverage rules",
            "policy_limits": "No CAD, model calls, source grammar or reference-derived prior",
            "view_workflow": "none",
            "supervisory_watchdog_seconds": 120,
            "watchdog_kind": "external execution backstop",
            "CAD_capability": False,
        },
    }
    record = {
        "schema_version": SCHEMA,
        "frozen": True,
        "frozen_utc": h.utc(),
        "application_freeze_confirmation": "Root confirmed exact application revision 8916e68f4c175bdab291d7c0bf2978862be8915d after installed Rust smoke and worker-process-group validation; native execution remains separately gated on GO.",
        "source_commit": EXPECTED_SOURCE,
        "runtime_root": str(RUNTIME),
        "runtime_freeze_sha256": EXPECTED_RUNTIME,
        "binary_sha256": EXPECTED_BINARY,
        "runtime_files": runtime["files"],
        "environment": environment_receipt(),
        "input_root": str(ROOT / "inference_v2"),
        "input_tree_sha256": INPUT_TREE,
        "implementation_index_sha256": h.sha(ROOT / "public_v2/implementation_inputs.json"),
        "input_seal_receipt_sha256": h.sha(ROOT / "public_v2/seal_receipt.json"),
        "execution_files": {str(p): h.sha(p) for p in [Path(__file__), helper_path, HERE / "v04_sealed_eval.py"]},
        "native_admission_lock": f"/tmp/marinaframe-native-admission-{os.geteuid()}.lock",
        "same_domain_engine": True,
        "same_default_operation_sequence": False,
        "comparison_scope": "Separate product-default arms. Raw default latency is not an identical-operation performance comparison.",
        "identical_operation_performance": "Separate controlled experiment owned by the data agent",
        "scoring_performed": False,
        "arms": plans,
    }
    h.write(path, record)
    return {"execution_plan": str(path), "sha256": h.sha(path),
            "arms": list(plans), "native_execution_authorized_by_this_plan": False}


def validate_plan(path):
    plan = h.load(path)
    check_runtime()
    check_inputs()
    if plan["runtime_freeze_sha256"] != EXPECTED_RUNTIME or plan["input_tree_sha256"] != INPUT_TREE:
        raise ValueError("Execution plan does not match the confirmed runtime/input freeze")
    for file, digest in plan["execution_files"].items():
        if h.sha(file) != digest:
            raise ValueError("Frozen evaluation execution file changed")
    if environment_receipt() != plan["environment"]:
        raise ValueError("Python runtime environment changed")
    return plan


def task_status_metadata(task):
    # A status is evidence of workflow state, never proof of geometry correctness.
    for name in ["state.json", "result.json"]:
        path = task / name
        if not path.is_file():
            continue
        try:
            value = h.load(path)
        except (ValueError, OSError):
            continue
        for obj in [value, value.get("state"), value.get("snapshot")]:
            if isinstance(obj, dict) and isinstance(obj.get("status"), str):
                return {"path": str(path), "sha256": h.sha(path), "status": obj["status"]}
    return None


def run_case(plan, plan_path, arm_name, case, output):
    cfg = plan["arms"][arm_name]
    attempt_id = f'{arm_name}__{case["case_id"]}__inputs_{INPUT_TREE[:12]}__primary_001'
    target = output / case["case_id"] / "primary_001"
    target.mkdir(parents=True, exist_ok=False)
    task = target / "task"
    substitutions = {
        "input_spec": str(ROOT / "inference_v2" / case["input"]),
        "task_directory": str(task),
        "prediction_file": str(target / "pixel_predictions.json"),
        "execution_plan": str(plan_path),
    }
    command = [s.format(**substitutions) for s in cfg["command_template"]]
    receipt_path = target / "attempt_record.json"
    receipt = {
        "schema_version": SCHEMA, "arm": arm_name, "case_id": case["case_id"],
        "attempt_id": attempt_id, "input_tree_sha256": INPUT_TREE,
        "input_spec_sha256": h.sha(substitutions["input_spec"]),
        "source_image_sha256": h.sha(ROOT / "inference_v2" / case["drawing"]),
        "execution_plan_sha256": h.sha(plan_path), "command": command,
        "working_directory": str(RUNTIME), "PYTHONPATH": str(RUNTIME / "src"),
        "requested_utc": h.utc(), "finalized": False,
        "provider_calls": 0, "operator_actions": 0,
        "admission": cfg["admission"], "queue_wait_seconds": None,
        "queue_accounting_note": "Rust internal native queue wait is retained by its task receipts; Python outer queue is recorded here. Pixel baseline has no native admission.",
        "supervisory_watchdog_seconds": cfg["supervisory_watchdog_seconds"],
        "watchdog_kind": cfg["watchdog_kind"],
        "timeout_classification": "If triggered: interrupted/truncated by evaluation boundary, not a domain refusal or domain failure.",
        "workflow_and_correctness_are_separate": True,
    }
    h.write(receipt_path, receipt)
    print(json.dumps({"event": "queued", "attempt_id": attempt_id}), flush=True)
    lock = None
    queue_start = time.monotonic()
    if cfg["admission"] == "outer_whole_task":
        lock = Path(plan["native_admission_lock"]).open("a+b")
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        receipt["queue_wait_seconds"] = time.monotonic() - queue_start
    elif cfg["admission"] == "none_no_CAD":
        receipt["queue_wait_seconds"] = 0
    receipt["started_utc"] = h.utc()
    h.write(receipt_path, receipt)
    start = time.monotonic()
    process = None
    try:
        with (target / "stdout.log").open("wb") as stdout, (target / "stderr.log").open("wb") as stderr:
            process = subprocess.Popen(command, cwd=RUNTIME, env=h.runtime_env(RUNTIME),
                                       stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr,
                                       start_new_session=True)
            receipt["launcher_pid"] = process.pid
            h.write(receipt_path, receipt)
            try:
                receipt["exit_code"], usage = h.wait_with_resources(process, cfg["supervisory_watchdog_seconds"])
                receipt["interrupted_truncated"] = False
            except subprocess.TimeoutExpired:
                receipt["interrupted_truncated"] = True
                receipt["exit_code"], usage = h.terminate_group(process, [
                    (signal.SIGINT, 20), (signal.SIGTERM, 5), (signal.SIGKILL, 5),
                ])
            h.write(target / "resource_usage.json", {
                "collector": "Linux wait4 for the CLI process and its waited-for children",
                "maxrss_units": "KiB", "usage": usage,
            })
    except Exception as exc:
        receipt["execution_exception"] = type(exc).__name__ + ": " + str(exc)
        if process is not None and process.returncode is None:
            receipt["cleanup_exit_code"], usage = h.terminate_group(process, [
                (signal.SIGINT, 20), (signal.SIGTERM, 5), (signal.SIGKILL, 5),
            ])
            h.write(target / "resource_usage.json", {"collector": "Linux wait4 after cleanup",
                                                       "maxrss_units": "KiB", "usage": usage})
    finally:
        receipt["execution_wall_seconds"] = time.monotonic() - start
        receipt["process_finished_utc"] = h.utc()
        if lock is not None:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
            lock.close()
    if cfg["CAD_capability"]:
        receipt["workflow_status_evidence"] = task_status_metadata(task)
        receipt["status_not_inferred_from_exit_code"] = True
    else:
        receipt["baseline_output_kind"] = "source_traces_only_no_CAD"
        receipt["CAD_exported"] = False
    rows = [r for r in h.inventory(target) if r["path"] != receipt_path.name]
    receipt["output_files"] = [{**r, "path": str(target / r["path"])} for r in rows]
    receipt["output_tree_sha256"] = h.tree_sha(rows)
    receipt["finalized"] = True
    receipt["finalized_utc"] = h.utc()
    receipt["scoring_performed"] = False
    h.write(receipt_path, receipt)
    print(json.dumps({"event": "output_locked", "attempt_id": attempt_id}), flush=True)
    return {"arm": arm_name, "case_id": case["case_id"], "attempt_id": attempt_id,
            "receipt_path": str(receipt_path), "receipt_sha256": h.sha(receipt_path),
            "output_tree_sha256": receipt["output_tree_sha256"]}


def execute(args):
    plan = validate_plan(args.plan)
    cfg = plan["arms"][args.arm]
    if cfg["CAD_capability"]:
        if args.native_release is None:
            raise ValueError("Wait for the explicit native GO receipt")
        release = h.load(args.native_release)
        if (release.get("native_execution_go") is not True or
                release.get("execution_plan_sha256") != h.sha(args.plan) or
                release.get("runtime_freeze_sha256") != EXPECTED_RUNTIME):
            raise ValueError("Native release does not authorize this frozen execution plan")
    args.out.mkdir(parents=True, exist_ok=False)
    shutil.copy2(args.plan, args.out / "execution_plan.json")
    if args.native_release:
        shutil.copy2(args.native_release, args.out / "native_release.json")
    records = []
    for case in check_inputs()["cases"]:
        check_inputs()
        check_runtime()
        records.append(run_case(plan, args.plan, args.arm, case, args.out))
        h.write(args.out / "attempt_commitments.json", {"attempts": records})
    validate_plan(args.plan)
    for item in records:
        if h.sha(item["receipt_path"]) != item["receipt_sha256"]:
            raise ValueError("Locked attempt receipt changed")
        for row in h.load(item["receipt_path"])["output_files"]:
            if h.sha(row["path"]) != row["sha256"]:
                raise ValueError("Locked attempt artifact changed")
    lock_record = {
        "schema_version": SCHEMA, "arm": args.arm, "outputs_locked": True,
        "locked_utc": h.utc(), "attempts": len(records), "input_tree_sha256": INPUT_TREE,
        "execution_plan_sha256": h.sha(args.plan),
        "attempt_commitments_sha256": h.sha(args.out / "attempt_commitments.json"),
        "source_only_no_CAD": not cfg["CAD_capability"],
        "references_read": False, "scoring_performed": False,
    }
    h.write(args.out / "output_lock.json", lock_record)
    return lock_record


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("prepare")
    p.add_argument("--out", required=True, type=Path)
    p = sub.add_parser("run")
    p.add_argument("--plan", required=True, type=Path)
    p.add_argument("--arm", required=True,
                   choices=["new_python_deterministic", "new_rust_deterministic", "simple_pixel_baseline"])
    p.add_argument("--out", required=True, type=Path)
    p.add_argument("--native-release", type=Path)
    args = parser.parse_args()
    result = prepare(args.out) if args.command == "prepare" else execute(args)
    print(json.dumps(result, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
