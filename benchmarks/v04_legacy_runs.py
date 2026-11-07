"""Run preserved legacy arms without reading references or reporting outcomes.

The source trees, inputs, interpreter, runner and all terminal output bytes are
committed in receipts. Every legacy CLI task holds the same advisory native lock
used by the current Rust controller. Queue time is outside active execution time.
This module neither imports an inference implementation nor changes its policy.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import time


ARMS = {
    "frozen_02_deterministic": {
        "source": "/workspace/scratch/3b76408c5d11/marinaframe-reviewed-baseline",
        "revision": "2b9ab4f905aff3dbbfed9a8c134ea85fad766546",
        "entrypoint": ["-m", "vessel_reconstruction", "reconstruct"],
        "policy_arguments": [],
    },
    "frozen_03_deterministic": {
        "source": "/tmp/marinaframe-v03-baseline-20261107",
        "revision": "5b0b48e3dd9bcef25427d27ce800118935f58d1a",
        "entrypoint": ["-m", "vessel_reconstruction", "agent", "run"],
        "policy_arguments": ["--policy", "deterministic"],
    },
}
DEFAULT_PYTHON = "/tmp/marinaframe-agentic-final-validation/env/bin/python"
SCHEMA = "marinaframe-independent-v04-legacy-execution-1"


def utc():
    return datetime.now(timezone.utc).isoformat()


def sha(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".writing")
    with temp.open("w") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temp, path)


def load(path):
    return json.loads(Path(path).read_text())


def inventory(root):
    root = Path(root)
    return [
        {"path": str(p.relative_to(root)), "bytes": p.stat().st_size, "sha256": sha(p)}
        for p in sorted(root.rglob("*")) if p.is_file()
    ]


def tree_sha(rows):
    return hashlib.sha256("\n".join(
        f'{r["path"]}\t{r["sha256"]}' for r in rows
    ).encode()).hexdigest()


def verify_inputs(root, seal_path, manifest_path):
    seal = load(seal_path)
    if sha(manifest_path) != seal["input_manifest_sha256"]:
        raise ValueError("Input manifest seal mismatch")
    rows = inventory(root)
    if rows != seal["files"] or tree_sha(rows) != seal["input_tree_sha256"]:
        raise ValueError("Sealed inference input mismatch")
    return seal


def runtime_env(source):
    # Explicit allow-list: provider credentials are neither read nor forwarded.
    allowed = ("PATH", "HOME", "LANG", "LC_ALL", "LC_CTYPE", "TMPDIR", "TZ")
    env = {name: os.environ[name] for name in allowed if name in os.environ}
    env["PYTHONPATH"] = str(Path(source) / "src")
    env["PYTHONNOUSERSITE"] = "1"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


def checked(command, cwd, env=None):
    return subprocess.check_output(command, cwd=cwd, env=env, text=True).strip()


def source_receipt(arm, python):
    source = Path(arm["source"])
    actual = checked(["git", "rev-parse", "HEAD"], source)
    status = checked(["git", "status", "--porcelain=v1"], source)
    if actual != arm["revision"] or status:
        raise ValueError("Preserved source revision or clean-tree check failed")
    tracked = subprocess.check_output(["git", "ls-files", "-z"], cwd=source)
    files = [p.decode() for p in tracked.split(b"\0") if p]
    rows = [
        {"path": p, "bytes": (source / p).stat().st_size, "sha256": sha(source / p)}
        for p in sorted(files) if (source / p).is_file()
    ]
    query = (
        "import importlib.metadata as m, importlib.util, json, platform, sys;"
        "print(json.dumps({'python':sys.version,'executable':sys.executable,"
        "'platform':platform.platform(),"
        "'module_origin':importlib.util.find_spec('vessel_reconstruction').origin,"
        "'packages':{n:m.version(n) for n in "
        "['cadquery','cadquery-ocp','numpy','scipy','Pillow','opencv-python-headless']}}))"
    )
    environment = json.loads(checked([python, "-c", query], source, runtime_env(source)))
    expected = source / "src" / "vessel_reconstruction" / "__init__.py"
    if Path(environment["module_origin"]).resolve() != expected.resolve():
        raise ValueError("Interpreter resolved the wrong baseline modules")
    return {
        **arm,
        "source_tree_clean": True,
        "tracked_files": rows,
        "tracked_tree_sha256": tree_sha(rows),
        "runtime": environment,
        "python_resolved": str(Path(python).resolve()),
        "python_executable_sha256": sha(Path(python).resolve()),
        "policy_limits": "unchanged defaults of the preserved CLI; no limit overrides",
        "environment_keys": sorted(runtime_env(source)),
        "PYTHONPATH": str(source / "src"),
    }


def descendants(pid):
    """Enumerate process IDs for watchdog cleanup, without reading environments."""
    parents = {}
    for proc in Path("/proc").iterdir():
        if not proc.name.isdigit():
            continue
        try:
            for line in (proc / "status").read_text().splitlines():
                if line.startswith("PPid:"):
                    parents[int(proc.name)] = int(line.split()[1])
                    break
        except (FileNotFoundError, ProcessLookupError, PermissionError):
            pass
    found = {pid}
    while True:
        extra = {p for p, parent in parents.items() if parent in found} - found
        if not extra:
            return sorted(found)
        found.update(extra)


def wait_with_resources(process, seconds):
    """Collect the launched process and waited-for descendants via Linux wait4."""
    deadline = time.monotonic() + seconds
    while True:
        pid, status, usage = os.wait4(process.pid, os.WNOHANG)
        if pid:
            process.returncode = os.waitstatus_to_exitcode(status)
            return process.returncode, {
                name: getattr(usage, name) for name in (
                    "ru_utime", "ru_stime", "ru_maxrss", "ru_ixrss", "ru_idrss",
                    "ru_isrss", "ru_minflt", "ru_majflt", "ru_nswap", "ru_inblock",
                    "ru_oublock", "ru_msgsnd", "ru_msgrcv", "ru_nsignals",
                    "ru_nvcsw", "ru_nivcsw",
                )
            }
        if time.monotonic() >= deadline:
            raise subprocess.TimeoutExpired(process.args, seconds)
        time.sleep(min(.2, max(0, deadline - time.monotonic())))


def terminate_group(process, signals):
    pids = descendants(process.pid)
    for sig, grace in signals:
        for pid in reversed(pids):
            try:
                os.kill(pid, sig)
            except ProcessLookupError:
                pass
        try:
            return wait_with_resources(process, grace)
        except subprocess.TimeoutExpired:
            pass
    return wait_with_resources(process, 10)


def run_attempt(arm_name, arm, case, args, freeze_sha):
    attempt_id = f'{arm_name}__{case["case_id"]}__inputs_{args.input_tree_sha256[:12]}__primary_001'
    attempt_dir = args.out / arm_name / case["case_id"] / "primary_001"
    attempt_dir.mkdir(parents=True, exist_ok=False)
    task = attempt_dir / "task"
    command = [
        args.python, *arm["entrypoint"], str(args.input_root / case["input"]),
        "--out", str(task), *arm["policy_arguments"],
    ]
    receipt_path = attempt_dir / "attempt_record.json"
    receipt = {
        "schema_version": SCHEMA,
        "arm": arm_name,
        "case_id": case["case_id"],
        "attempt_id": attempt_id,
        "cohort": case["cohort"],
        "input_file": str(args.input_root / case["input"]),
        "input_sha256": sha(args.input_root / case["input"]),
        "input_tree_sha256": args.input_tree_sha256,
        "source_image_sha256": sha(args.input_root / case["drawing"]),
        "freeze_sha256": freeze_sha,
        "command": command,
        "working_directory": arm["source"],
        "PYTHONPATH": str(Path(arm["source"]) / "src"),
        "requested_utc": utc(),
        "native_admission_lock": str(args.lock),
        "whole_task_lock": True,
        "launched": False,
        "finalized": False,
        "provider_calls": 0,
        "operator_actions": 0,
        "supervisory_watchdog_seconds": args.watchdog_seconds,
        "watchdog_note": "Safety backstop only; engine and harness limits remain unchanged.",
        "outcome_not_interpreted_by_runner": True,
    }
    write(receipt_path, receipt)
    print(json.dumps({"event": "queued", "attempt_id": attempt_id}), flush=True)
    queue_start = time.monotonic()
    with args.lock.open("a+b") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        receipt["queue_wait_seconds"] = time.monotonic() - queue_start
        receipt["started_utc"] = utc()
        receipt["launched"] = True
        write(receipt_path, receipt)
        print(json.dumps({"event": "started", "attempt_id": attempt_id}), flush=True)
        active_start = time.monotonic()
        process = None
        try:
            with (attempt_dir / "stdout.log").open("wb") as stdout, \
                    (attempt_dir / "stderr.log").open("wb") as stderr:
                process = subprocess.Popen(
                    command, cwd=arm["source"], env=runtime_env(arm["source"]),
                    stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr,
                    start_new_session=True,
                )
                receipt["launcher_pid"] = process.pid
                write(receipt_path, receipt)
                try:
                    receipt["exit_code"], usage = wait_with_resources(process, args.watchdog_seconds)
                    receipt["supervisory_timeout"] = False
                except subprocess.TimeoutExpired:
                    receipt["supervisory_timeout"] = True
                    receipt["exit_code"], usage = terminate_group(process, [
                        (signal.SIGINT, 20), (signal.SIGTERM, 5), (signal.SIGKILL, 5),
                    ])
                write(attempt_dir / "resource_usage.json", {
                    "collector": "Linux os.wait4 for the CLI process and its waited-for children",
                    "maxrss_units": "KiB",
                    "usage": usage,
                })
        except Exception as exc:
            receipt["execution_exception"] = type(exc).__name__ + ": " + str(exc)
            if process is not None and process.returncode is None:
                receipt["cleanup_exit_code"], usage = terminate_group(process, [
                    (signal.SIGINT, 20), (signal.SIGTERM, 5), (signal.SIGKILL, 5),
                ])
                write(attempt_dir / "resource_usage.json", {
                    "collector": "Linux os.wait4 after supervisory cleanup",
                    "maxrss_units": "KiB", "usage": usage,
                })
        finally:
            receipt["execution_wall_seconds"] = time.monotonic() - active_start
            receipt["process_finished_utc"] = utc()
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
    # Original files are not normalized, repaired, removed, or decoded here.
    rows = [r for r in inventory(attempt_dir) if r["path"] != receipt_path.name]
    receipt["output_files"] = [
        {**r, "path": str(attempt_dir / r["path"])} for r in rows
    ]
    receipt["output_tree_sha256"] = tree_sha(rows)
    receipt["finalized"] = True
    receipt["finalized_utc"] = utc()
    write(receipt_path, receipt)
    print(json.dumps({"event": "output_locked", "attempt_id": attempt_id}), flush=True)
    return {
        "arm": arm_name, "case_id": case["case_id"], "attempt_id": attempt_id,
        "receipt_path": str(receipt_path), "receipt_sha256": sha(receipt_path),
        "output_tree_sha256": receipt["output_tree_sha256"],
        "finalized_utc": receipt["finalized_utc"],
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-root", type=Path, required=True)
    parser.add_argument("--input-manifest", type=Path, required=True)
    parser.add_argument("--seal", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--python", default=DEFAULT_PYTHON)
    parser.add_argument("--watchdog-seconds", type=float, default=900)
    args = parser.parse_args()
    args.lock = Path(f"/tmp/marinaframe-native-admission-{os.geteuid()}.lock")
    if not hasattr(os, "wait4"):
        raise RuntimeError("Linux os.wait4 is required to retain per-attempt process resources")
    seal = verify_inputs(args.input_root, args.seal, args.input_manifest)
    args.input_tree_sha256 = seal["input_tree_sha256"]
    manifest = load(args.input_manifest)
    args.out.mkdir(parents=True, exist_ok=False)
    freeze = {
        "schema_version": SCHEMA,
        "frozen": True,
        "frozen_utc": utc(),
        "scope": "legacy arms only; new implementation remains unfrozen",
        "input_tree_sha256": seal["input_tree_sha256"],
        "seal_receipt_sha256": sha(args.seal),
        "runner_sha256": sha(__file__),
        "native_admission_lock": str(args.lock),
        "supervisory_watchdog_seconds": args.watchdog_seconds,
        "arms": {name: source_receipt(arm, args.python) for name, arm in ARMS.items()},
    }
    freeze_path = args.out / "legacy_freeze.json"
    write(freeze_path, freeze)
    shutil.copy2(args.input_manifest, args.out / "input_manifest.json")
    shutil.copy2(args.seal, args.out / "input_seal.json")
    shutil.copy2(__file__, args.out / "runner.py")
    records = []
    # Each task releases admission before the next request. Arm-major order is
    # fixed in advance; no ordering choice can depend on an outcome.
    for arm_name, arm in ARMS.items():
        for case in manifest["cases"]:
            verify_inputs(args.input_root, args.seal, args.input_manifest)
            records.append(run_attempt(arm_name, arm, case, args, sha(freeze_path)))
            write(args.out / "attempt_commitments.json", {"attempts": records})
    verify_inputs(args.input_root, args.seal, args.input_manifest)
    for name, arm in ARMS.items():
        current = source_receipt(arm, args.python)
        if current != freeze["arms"][name]:
            raise ValueError("Preserved runtime changed during execution")
    for item in records:
        if sha(item["receipt_path"]) != item["receipt_sha256"]:
            raise ValueError("Finalized attempt receipt changed")
        receipt = load(item["receipt_path"])
        for row in receipt["output_files"]:
            if sha(row["path"]) != row["sha256"]:
                raise ValueError("Finalized attempt output changed")
    complete = {
        "schema_version": SCHEMA,
        "all_legacy_outputs_locked": True,
        "locked_utc": utc(),
        "input_tree_sha256": seal["input_tree_sha256"],
        "legacy_freeze_sha256": sha(freeze_path),
        "attempt_commitments_sha256": sha(args.out / "attempt_commitments.json"),
        "attempts": len(records),
        "arms": list(ARMS),
        "references_read": False,
        "scoring_performed": False,
        "no_outcome_or_accuracy_summary": True,
    }
    write(args.out / "legacy_output_lock.json", complete)
    print(json.dumps(complete, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
