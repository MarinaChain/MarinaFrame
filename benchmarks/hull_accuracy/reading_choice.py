"""How often the best-of-2 reading choice keeps the reading that is better against truth.

For each live case with two first-hull builds (one per reading), compares:

- ``stored``: the draft fits the run recorded for its readings (``state["readings"]``,
  computed on the form-fit table before the build);
- ``built``: the draft fit of each build's delivered sections (``extracted_sections.json``).

Both are drawing-only scores; truth (DEVELOPMENT factory only) is used to judge the choice.
Write outputs under the main checkout's ``work/``.

    PYTHONPATH=src:. .venv/bin/python -m benchmarks.hull_accuracy.reading_choice \\
        --rounds ../work/round-hull-L0-fix-5b8a9d5 --out ../work/hull-lane/reading-choice.json
"""
from __future__ import annotations

import argparse
import json
import shutil
import tempfile
from pathlib import Path

from benchmarks.hull_accuracy.replay_readings import score_step


def built_fit(task: Path, build: Path) -> float | None:
    """Draft fit of one build's delivered sections, in the task's reference frame."""
    from vessel_reconstruction import draft_fit
    from vessel_reconstruction.agent_tools import DomainTools
    from vessel_reconstruction.first_hull_tools import built_table
    from vessel_reconstruction.vessel_model import StationRow, VesselTable, waterline_grid

    with tempfile.TemporaryDirectory() as scratch:
        # A copy: opening a task must never change the round's own evidence.
        copy = Path(scratch) / "task"
        shutil.copytree(task, copy, ignore=shutil.ignore_patterns("builds", "events", "receipts", "requests"))
        tools = DomainTools(copy, copy / "domain/input/spec.json")
        sections = json.loads((build / "extracted_sections.json").read_text())["sections"]
        rows = [StationRow(str(s["id"]), float(s["x_m"]), s["points_yz_m"], "traced") for s in sections]
        table = built_table(VesselTable(rows, waterline_grid(rows)), build)
        image, _, _ = tools._source()
        scale = float(tools.spec["sections"][0]["calibration"]["pixels_per_metre"])
        board = draft_fit.score(table, tools.spec, image, tools.intake_hints(), scale,
                                float(tools.state["score_half_beam_m"]))
        return board.get("draft_fit")


def case_rows(case_dir: Path) -> dict | None:
    state = json.loads((case_dir / "task/domain/state.json").read_text())
    readings = [r for r in state.get("readings", []) if not r.get("same_setup")]
    builds = sorted((case_dir / "task/domain/builds").glob("first-*"), key=lambda p: p.stat().st_mtime)
    if len(readings) < 2 or len(builds) < 2:
        return None
    rows = []
    for record, build in zip(readings, builds):
        score = score_step(case_dir.name, build / "model-draft.step")
        rows.append({"build": build.name, "stored_fit": record.get("draft_fit"),
                     "built_fit": built_fit(case_dir / "task", build),
                     "rms_pct": score["rms_pct"], "volume_pct": score["volume_pct"]})
    return {"case": case_dir.name, "round": case_dir.parent.name, "readings": rows}


def choice_right(rows: list[dict], key: str) -> bool | None:
    """True when the higher ``key`` fit (ties keep the first) is the lower-RMS reading."""
    first, second = rows[0], rows[1]
    if first[key] is None or second[key] is None or first["rms_pct"] == second["rms_pct"]:
        return None
    kept = second if second[key] > first[key] else first
    return kept["rms_pct"] == min(first["rms_pct"], second["rms_pct"])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--rounds", type=Path, nargs="+", required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    cases = []
    for folder in args.rounds:
        for case_dir in sorted(folder.glob("*-L?")):
            if not (case_dir / "task/domain/state.json").exists():
                continue
            row = case_rows(case_dir)
            if row is None:
                continue
            row["stored_right"] = choice_right(row["readings"], "stored_fit")
            row["built_right"] = choice_right(row["readings"], "built_fit")
            cases.append(row)
            print(json.dumps(row), flush=True)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps({"cases": cases, "engineering_approved": False}, indent=2))


if __name__ == "__main__":
    main()
