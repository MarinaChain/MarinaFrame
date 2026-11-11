"""Replay stored live readings through the first-hull code and score each station.

A live round stores each case's phase-1 reading (sheet setups, described views and
the model's vessel description) in ``<case>/task/domain/state.json``. This tool
re-measures that reading with the current source and builds the first hull again,
so a code change can be measured without new model calls (tasks/lessons.md,
"Replay a live round before spending another"). With ``--delivered`` it scores
the round's delivered draft instead, with the same per-station detail.

Scores use the frozen factory scorer and gate (2 % RMS of half-beam, 5 % in-range
volume) against DEVELOPMENT truth only. Never point it at sealed or holdout data.
Write outputs under the main checkout's git-ignored ``work/``.

    PYTHONPATH=src:. .venv/bin/python -m benchmarks.hull_accuracy.replay_readings \\
        --rounds ../work/round-hull-L0-base-4f03667 --tasks ../work/replay-x --out ../work/replay-x.json
"""
from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
from uuid import uuid4

from benchmarks.factory import truth
from scripts import round_digest

FACTORY = Path("/Users/jonathanjie/Documents/workspace/MarinaFrame/work/factory-3view")
RMS_GATE_PCT = 2.0
VOLUME_GATE_PCT = 5.0


def score_step(case: str, step: Path, factory: Path = FACTORY) -> dict:
    """Case RMS and volume errors in percent, and each station's RMS as percent of half-beam."""
    if "sealed-" in str(factory) or "holdout" in str(factory):
        raise ValueError("development factory only")
    params = json.loads((factory / "params" / f"{case}.json").read_text())
    stations = [{"id": f"s{i + 1:02d}", "x_m": x} for i, x in enumerate(params["station_x_m"])]
    hull = round_digest.truth_hull_name(case)
    result = truth.score_model(factory / "sealed" / "truth" / f"{hull}.npz", step, stations)
    half_beam = result["truth"]["max_half_breadth_m"]
    rms = 100 * result["summary"]["half_breadth_main"]["rms_of_station_rms_m"] / half_beam
    volume = 100 * result["hydrostatics_at_design_draft"]["volume_error_relative_within_range"]
    rows = []
    for entry in result["stations"]:
        errors = entry.get("half_breadth_main")
        if errors is None:
            continue
        rows.append({"id": entry["id"], "x_m": round(entry["x_m"], 2),
                     "rms_pct": round(100 * errors["rms_m"] / half_beam, 2),
                     "signed_at_max_m": round(errors["signed_at_max_m"], 3),
                     "z_at_max_m": round(errors["z_at_max_m"], 2)})
    return {"rms_pct": round(rms, 2), "volume_pct": round(volume, 2),
            "passes": rms <= RMS_GATE_PCT and abs(volume) <= VOLUME_GATE_PCT,
            "x_range_m": [round(v, 2) for v in result["reconstruction_x_range_m"]], "stations": rows}


def replay(case_dir: Path, destination: Path) -> dict:
    """Build the first hull from the case's stored reading with the current source."""
    from vessel_reconstruction.agent_tools import DomainTools
    from vessel_reconstruction.first_hull_tools import build_first_hull

    saved = json.loads((case_dir / "task/domain/state.json").read_text())
    if not saved.get("vessel_description") or "sheet_setups" not in saved:
        # A run that stopped before its phase-1 reading (blocked at input) has nothing to replay.
        return {"case": case_dir.name, "error": "no_reading"}
    tools = DomainTools(destination, case_dir / "intake/run-input/spec.json")
    for key in ("sheet_setups", "described_views"):
        tools.state[key] = copy.deepcopy(saved[key])
    tools._save()
    description = saved["vessel_description"]
    tools._describe_vessel(copy.deepcopy(description.get("model_description", description)))
    observation = build_first_hull(tools)
    if not observation.get("ok"):
        return {"case": case_dir.name, "error": observation.get("error_code", "first_hull_failed")}
    candidate = tools.state["last_valid_candidate"]
    build = destination / candidate["path"]
    record = json.loads((build / "result.json").read_text())
    return {"case": case_dir.name, "build": str(build),
            "score": score_step(case_dir.name, build / record["exports"]["step"])}


def delivered(case_dir: Path) -> dict:
    """Score the round's delivered draft (the task's last valid candidate)."""
    step = round_digest.latest_valid_draft_step(round_digest.load_events(case_dir), case_dir)
    if step is None:
        return {"case": case_dir.name, "error": "no_valid_draft"}
    return {"case": case_dir.name, "build": str(step.parent), "score": score_step(case_dir.name, step)}


def case_dirs(rounds: list[Path], only: list[str] | None) -> list[Path]:
    found = [path for folder in rounds for path in sorted(folder.glob("*-L?")) if (path / "task").is_dir()]
    return [path for path in found if not only or path.name in only]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--rounds", type=Path, nargs="+", required=True)
    parser.add_argument("--cases", nargs="*")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--tasks", type=Path, help="folder for replay tasks (required unless --delivered)")
    parser.add_argument("--delivered", action="store_true", help="score delivered drafts, no replay")
    args = parser.parse_args()
    if not args.delivered and args.tasks is None:
        parser.error("--tasks is required for a replay")
    rows = []
    for case_dir in case_dirs(args.rounds, args.cases):
        if args.delivered:
            row = delivered(case_dir)
        else:
            # A new task folder each time: an interrupted build is not a clean reading.
            row = replay(case_dir, args.tasks / f"{case_dir.name}-{uuid4().hex[:8]}")
        rows.append(row)
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps({"rows": rows, "engineering_approved": False}, indent=2))
        score = row.get("score") or {}
        worst = sorted(score.get("stations", []), key=lambda s: -s["rms_pct"])[:3]
        print(json.dumps({"case": row["case"], "rms_pct": score.get("rms_pct"), "volume_pct": score.get("volume_pct"),
                          "passes": score.get("passes"), "error": row.get("error"),
                          "worst": [(s["id"], s["rms_pct"]) for s in worst]}), flush=True)


if __name__ == "__main__":
    main()
