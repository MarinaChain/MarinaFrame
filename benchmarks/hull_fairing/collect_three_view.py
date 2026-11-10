"""Collect point sets from stored development readings, without models or truth.

    PYTHONPATH=src:. .venv/bin/python -m benchmarks.hull_fairing.collect_three_view
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from benchmarks.hull_fairing.replay import WORK, ROUNDS, delivered_build, load_sections, stored_builds
from vessel_reconstruction import draft_fit, three_view_evidence, view_measure

PROTOCOL_PATH = Path(__file__).with_name("three_view_protocol.json")
DEFAULT_OUTPUT = Path("work/three-view-fairing/evidence")


def reading_sections(case: Path, build: Path, *, reader: bool = False) -> list[dict]:
    sections = load_sections(build)
    if not reader:
        return sections
    # Frozen reader values, before first-hull bottom/deck continuation.
    from vessel_reconstruction.body_plan_intake import station_number
    intake = json.loads((case / "task/domain/input/intake.json").read_text())
    by_number = {row["station"]: row for row in intake["body_plan_reading"]["stations"]}
    return [{**s, "source_label": "read", "points_yz_m": by_number[station_number(s["id"])]["curve_y_z_m"]}
            for s in sections if s.get("source_label") == "read" and station_number(s["id"]) in by_number]


def population(work: Path = WORK):
    protocol = json.loads(PROTOCOL_PATH.read_text())
    for split in ("fit", "check"):
        for name in protocol[f"{split}_cases"]:
            reader = name == "bue_girl"
            case = work / ("autocal-live-6" if reader else ROUNDS[int(name[-1])]) / name
            delivered = delivered_build(case)
            builds = [delivered] if reader else stored_builds(case)
            if not builds:
                raise ValueError(f"No stored builds for {name}")
            for build in builds:
                yield split, case, build, build == delivered, reader


def collect_build(case: Path, build: Path, *, reader: bool = False) -> dict:
    domain = case / "task/domain"
    source = domain / "input/source.png"
    intake = json.loads((domain / "input/intake.json").read_text())
    spec = json.loads((build / "input_spec.json").read_text())
    hints = next(p["regions"] for p in intake["pages"] if p["page_id"] == intake["spec_page_id"])
    grey = view_measure.load_grey(source)
    ppm = float(spec["sections"][0]["calibration"]["pixels_per_metre"])
    views = draft_fit.reference_views(grey, hints, ppm)
    sections = reading_sections(case, build, reader=reader)
    record = three_view_evidence.collect(sections, grey, views)
    if reader:
        record["reader_cells"] = [{"station": row["station"], "cells_z_y_m": row["cells_z_y_m"]}
                                  for row in intake["body_plan_reading"]["stations"]]
    record.update(case=case.name, build=build.name, reader_output=reader, sections=sections,
                  source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
                  sections_sha256=hashlib.sha256((build / "extracted_sections.json").read_bytes()).hexdigest())
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work", type=Path, default=WORK)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    manifest = []
    for split, case, build, delivered, reader in population(args.work):
        result = collect_build(case, build, reader=reader)
        name = f"{case.name}--{build.name}.json"
        result.update(split=split, delivered=delivered)
        (args.output / name).write_text(json.dumps(result, indent=1, allow_nan=False) + "\n")
        manifest.append({"file": name, "case": case.name, "build": build.name, "split": split,
                         "delivered": delivered, "coverage": result["coverage"]})
        print(case.name, build.name, json.dumps(result["coverage"]), flush=True)
    (args.output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")


if __name__ == "__main__":
    main()
