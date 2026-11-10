"""Three-view evidence with plan/profile points from view_reader_v2 (frozen settings).

Takes each stored build's record from ``collect_three_view`` (sections, body
points, metadata) and replaces its plan and profile points with the v2 reader's
points, read from the same drawing, regions and scale. Body points and sections
are unchanged, so a replay isolates the plan/profile reader. One evidence folder
is written per split, each with its own manifest, so the splits can replay in
parallel with ``replay_three_view replay`` and the unchanged weight choice.

    PYTHONPATH=src:. .venv/bin/python -m benchmarks.hull_fairing.collect_view_reader_v2 \
        --old work/view-reader-v2/old-evidence --output work/view-reader-v2/evidence
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from benchmarks.hull_fairing.replay import ROUNDS, WORK
from benchmarks.hull_fairing.view_reader_eval import frozen_reader
from vessel_reconstruction import draft_fit, view_measure, view_reader_v2


def new_record(record: dict, case_dir: Path) -> dict:
    body = [p for p in record["points"] if p["view"] == "body_plan"]
    if not record["views"]:
        # No plan or profile region (BUE GIRL): the record keeps its body points only.
        return {**record, "points": body, "method": view_reader_v2.METHOD}
    domain = case_dir / "task/domain"
    grey = view_measure.load_grey(domain / "input/source.png")
    views = {kind: view for kind, view in record["views"].items()}
    reading = view_reader_v2.read_views(grey, views)
    points, coverage = view_reader_v2.evidence_points(reading)
    return {**record, "points": body + points, "coverage": coverage, "method": view_reader_v2.METHOD,
            "reader_settings": "benchmarks/hull_fairing/view_reader_v2_settings.json"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--old", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    frozen_reader()
    manifest = json.loads((args.old / "manifest.json").read_text())
    by_split = {}
    for entry in manifest:
        record = json.loads((args.old / entry["file"]).read_text())
        case_dir = (WORK / "autocal-live-6" / entry["case"]) if record.get("reader_output") \
            else WORK / ROUNDS[int(entry["case"][-1])] / entry["case"]
        result = new_record(record, case_dir)
        folder = args.output / entry["split"]
        folder.mkdir(parents=True, exist_ok=True)
        (folder / entry["file"]).write_text(json.dumps(result, indent=1, allow_nan=False) + "\n")
        by_split.setdefault(entry["split"], []).append({**entry, "coverage": result["coverage"]})
        print(entry["case"], entry["build"], json.dumps({k: v.get("points") for k, v in result["coverage"].items()}),
              flush=True)
    for split, rows in by_split.items():
        (args.output / split / "manifest.json").write_text(json.dumps(rows, indent=2) + "\n")


if __name__ == "__main__":
    main()
