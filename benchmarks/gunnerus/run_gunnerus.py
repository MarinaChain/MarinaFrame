"""Run one sealed Gunnerus benchmark path and score it. Run once per frozen commit.

``vector``: Lines Plan Rev0.dxf -> make_gunnerus_configs -> vector_path -> score.
``raster``: Lines Plan Rev0.pdf -> raster_path prepare -> marinaframe run
            (deterministic policy; --on-ambiguity abstain or draft) -> score of
            any built model (a draft's STEP is model-draft.step) -> overlay.

Outputs go to ``--out`` (must not exist; keep it under the git-ignored work/
folder). The record ``run_record.json`` holds the commit, hashes and status.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _git_commit() -> dict:
    head = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    dirty = subprocess.run(["git", "-C", str(ROOT), "status", "--porcelain", "--untracked-files=no"],
                           capture_output=True, text=True).stdout.strip()
    return {"commit": head, "tracked_changes": bool(dirty)}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run_vector(args, out: Path) -> dict:
    from . import make_gunnerus_configs, score, vector_path

    config, ledger = make_gunnerus_configs.vector_config(args.dxf)
    (out / "gunnerus_vector.json").write_text(json.dumps(config, indent=2) + "\n")
    (out / "identity_ledger.json").write_text(json.dumps(ledger, indent=2) + "\n")
    summary = vector_path.run(out / "gunnerus_vector.json", out / "vector")
    stations = json.loads((out / "vector" / "stations.json").read_text())
    model = out / "vector" / "model.brep"
    result = score.score(args.truth, model if model.exists() else None, stations,
                         json.loads(args.metric.read_text()), out / "score")
    return {"vector_run": summary, "score_status": result["status"]}


def run_raster(args, out: Path) -> dict:
    from . import make_gunnerus_configs, raster_path, score

    config, _ = make_gunnerus_configs.vector_config(args.dxf)
    raster = make_gunnerus_configs.raster_config(args.pdf, config["stations"])
    (out / "gunnerus_raster.json").write_text(json.dumps(raster, indent=2) + "\n")
    task_root = args.task_root
    task_root.mkdir(parents=True, exist_ok=False)
    raster_path.cmd_prepare(raster, out, task_root / "input")
    completed = subprocess.run([str(args.controller), "run", "--task", str(task_root / "task"),
                                "--source", str(task_root / "input" / "spec.json"),
                                "--worker-python", sys.executable, "--worker-source", str(ROOT / "src"),
                                "--policy", "deterministic", "--on-ambiguity", args.on_ambiguity],
                               capture_output=True, text=True)
    (out / "controller_stdout.json").write_text(completed.stdout)
    (out / "controller_stderr.txt").write_text(completed.stderr)
    status = json.loads(completed.stdout) if completed.stdout.strip().startswith("{") else {"status": "cli_error"}
    candidate = status.get("current_candidate") or {}
    model = None
    if candidate.get("path"):
        run_dir = task_root / "task" / candidate["path"]
        model = next((run_dir / name for name in ("model.step", "model-draft.step") if (run_dir / name).exists()),
                     run_dir / "model.step")
    overlay = raster_path.cmd_overlay(task_root / "input" / "drawing.png", task_root / "task", out / "overlay.png")
    (out / "overlay_candidates.json").write_text(json.dumps(overlay, indent=1) + "\n")
    stations = [{"id": s["id"], "x_m": s["x_m"], "status": "read" if model else "not_built"} for s in raster["stations"]]
    result = score.score(args.truth, model if model and model.exists() else None, stations,
                         json.loads(args.metric.read_text()), out / "score")
    return {"on_ambiguity": args.on_ambiguity, "controller_exit": completed.returncode, "controller_status": status.get("status"),
            "termination_reason": status.get("termination_reason"),
            "drawing_sha256": _sha256(task_root / "input" / "drawing.png"),
            "model_step": str(model) if model else None, "score_status": result["status"],
            "sections_inspected": len(overlay)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", choices=["vector", "raster"])
    parser.add_argument("--dxf", type=Path, required=True)
    parser.add_argument("--pdf", type=Path, required=True)
    parser.add_argument("--truth", type=Path, required=True)
    parser.add_argument("--metric", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--controller", type=Path, default=ROOT / "target/release/marinaframe")
    parser.add_argument("--task-root", type=Path, help="raster: fresh directory outside the synced workspace")
    parser.add_argument("--on-ambiguity", choices=["abstain", "draft"], default="abstain",
                        help="raster: controller policy for ambiguous or unreadable sections")
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=False)
    record = {"path": args.path, **_git_commit(), "started": time.strftime("%Y-%m-%dT%H:%M:%S"),
              "dxf_sha256": _sha256(args.dxf), "pdf_sha256": _sha256(args.pdf),
              "truth_sections_sha256": _sha256(args.truth / "truth_sections.npz"),
              "metric_sha256": _sha256(args.metric)}
    started = time.perf_counter()
    try:
        record.update(run_vector(args, args.out) if args.path == "vector" else run_raster(args, args.out))
        record["outcome"] = "completed"
    except Exception as exc:  # record every failure; do not hide it
        record.update(outcome="failed", error=f"{type(exc).__name__}: {exc}")
    record["seconds"] = time.perf_counter() - started
    (args.out / "run_record.json").write_text(json.dumps(record, indent=2, default=str) + "\n")
    print(json.dumps(record, indent=2, default=str))


if __name__ == "__main__":
    main()
