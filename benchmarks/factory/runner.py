"""Run the deterministic Rust pipeline on factory cases, in bounded parallel batches.

Each case runs ``marinaframe run --policy deterministic`` on ``inputs/<case>/spec.json`` only. The runner
never opens the sealed folder. Outcome classes (kept separate, never merged):

- ``built``      the controller reached ``awaiting_human_review`` with a valid candidate and a STEP model;
- ``abstained``  the controller finished with status ``abstained`` (it declined to build);
- ``failed``     anything else: blocked, validation failed, no progress, protocol error, crash, timeout.

Active task directories live under /tmp (README: runs inside the synchronised workspace pick up debris),
and are deleted after the small result record and the STEP model are copied to ``runs/<run>/<case>/``.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import signal
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ROOT = ROOT / "work" / "factory"
MANIFEST_DIR = Path(__file__).resolve().parent / "manifests"
MAX_JOBS = 3
TIMEOUT_S = 1200


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git_state() -> dict:
    run = lambda *a: subprocess.run(["git", "-C", str(ROOT), *a], capture_output=True, text=True).stdout.strip()  # noqa: E731
    return {"commit": run("rev-parse", "HEAD"), "dirty": bool(run("status", "--porcelain", "--untracked-files=no"))}


def inspection_summary(task: Path) -> dict:
    """Candidates per inspected section: hypothesis names, selectable counts (abstention evidence)."""
    summary = {}
    for record in sorted(task.glob("domain/inspections/*/section-*.json")):
        try:
            data = json.loads(record.read_text())
        except (OSError, ValueError):
            continue
        candidates = data.get("candidates", [])
        summary[data.get("section_id", record.stem)] = {
            "candidates": [c.get("hypothesis") for c in candidates],
            "selectable": sum(1 for c in candidates if c.get("selectable")),
            "retained_competing": data.get("retained_competing_count"),
            "unique_non_grid": (data.get("grid_evidence") or {}).get("unique_non_grid_candidate_id") is not None}
    return summary


def run_case(case: dict, run_dir: Path, inputs: Path, controller: Path, python: Path, worker_source: Path,
             task_root: Path, keep_task: bool, provenance: dict) -> dict:
    case_id = case["case_id"]
    out = run_dir / case_id
    if (out / "result.json").exists():
        return json.loads((out / "result.json").read_text())
    out.mkdir(parents=True, exist_ok=True)
    task = task_root / case_id / "task"
    shutil.rmtree(task_root / case_id, ignore_errors=True)
    (task_root / case_id).mkdir(parents=True)
    command = [str(controller), "run", "--task", str(task), "--source", str(inputs / case_id / "spec.json"),
               "--worker-python", str(python), "--worker-source", str(worker_source), "--policy", "deterministic"]
    started = time.perf_counter()
    record = {"case_id": case_id, "split": case["split"], "level": case["level"], "layout": case["layout"],
              "hull_id": case["hull_id"], "family": case["family"], "run": run_dir.name, **provenance}
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=True)
    try:
        stdout, stderr = process.communicate(timeout=TIMEOUT_S)
        record["exit_code"] = process.returncode
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        stdout, stderr = process.communicate()
        record["exit_code"] = None
        record["timeout"] = True
    record["seconds"] = round(time.perf_counter() - started, 2)
    status = {}
    try:
        status = json.loads(stdout) if stdout.strip().startswith("{") else {}
    except ValueError:
        pass
    record["controller_status"] = status.get("status")
    record["termination_reason"] = status.get("termination_reason")
    candidate = status.get("current_candidate") or {}
    model = task / candidate["path"] / "model.step" if candidate.get("path") else None
    if record.get("timeout"):
        outcome, kind = "failed", "timeout"
    elif status.get("status") == "awaiting_human_review" and candidate.get("valid") and model and model.exists():
        outcome, kind = "built", None
        shutil.copy2(model, out / "model.step")
        record["model_sha256"] = _sha256(out / "model.step")
        record["candidate_metrics"] = {k: candidate["metrics"].get(k) for k in
                                       ("volume_m3", "beam_m", "depth_m", "length_m", "section_count", "cad_valid")}
    elif status.get("status") == "abstained":
        outcome, kind = "abstained", None
    else:
        outcome = "failed"
        kind = status.get("status") or ("protocol_error" if record["exit_code"] else "no_status")
    record["outcome"], record["failure_kind"] = outcome, kind
    if outcome != "built":
        record["inspection"] = inspection_summary(task)
        record["stderr_tail"] = stderr[-400:]
    (out / "result.json").write_text(json.dumps(record, indent=1) + "\n")
    if not keep_task:
        shutil.rmtree(task_root / case_id, ignore_errors=True)
    return record


def load_cases(split: str | None, only: list[str] | None, limit: int | None) -> list[dict]:
    cases = [json.loads(line) for line in (MANIFEST_DIR / "cases.jsonl").read_text().splitlines()]
    if split:
        cases = [c for c in cases if c["split"] == split]
    if only:
        cases = [c for c in cases if c["case_id"] in only]
    return cases[:limit] if limit else cases


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--run", required=True, help="run name; one folder under runs/")
    parser.add_argument("--split")
    parser.add_argument("--cases", help="comma-separated case ids")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--jobs", type=int, default=MAX_JOBS)
    parser.add_argument("--controller", type=Path, default=ROOT / "target" / "release" / "marinaframe")
    parser.add_argument("--python", type=Path, default=Path(os.environ.get("MARINAFRAME_PY", ROOT.parents[2] / ".venv/bin/python")))
    parser.add_argument("--worker-source", type=Path, default=ROOT / "src")
    parser.add_argument("--keep-task", action="store_true")
    args = parser.parse_args()
    if args.jobs > MAX_JOBS:
        raise SystemExit("at most 3 concurrent native jobs")
    run_dir = args.root / "runs" / args.run
    run_dir.mkdir(parents=True, exist_ok=True)
    task_root = Path("/tmp/mf_factory") / args.run
    cases = load_cases(args.split, args.cases.split(",") if args.cases else None, args.limit)
    provenance = {"code": git_state(), "controller_sha256": _sha256(args.controller)}
    (run_dir / "run_info.json").write_text(json.dumps({"run": args.run, "started": time.strftime("%Y-%m-%dT%H:%M:%S"),
                                                       "cases": len(cases), "jobs": args.jobs, **provenance}, indent=1) + "\n")
    started = time.perf_counter()
    counts = {"built": 0, "abstained": 0, "failed": 0}
    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        futures = [pool.submit(run_case, c, run_dir, args.root / "inputs", args.controller, args.python,
                               args.worker_source, task_root, args.keep_task, provenance) for c in cases]
        for index, future in enumerate(futures, 1):
            record = future.result()
            counts[record["outcome"]] += 1
            if index % 10 == 0 or index == len(futures):
                print(f"{index}/{len(cases)} {counts} {time.perf_counter() - started:.0f}s", flush=True)
    print(json.dumps({"run": args.run, "cases": len(cases), **counts, "seconds": round(time.perf_counter() - started, 1)}))


if __name__ == "__main__":
    sys.exit(main())
