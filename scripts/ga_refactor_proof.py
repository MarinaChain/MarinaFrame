"""Capture or compare offline GA refactor evidence on the 14 development cases only.

Run from the worktree with PYTHONPATH=src. Per-case evidence stays in ignored work/.
No model entry point is available during this proof.
"""
from __future__ import annotations

import argparse
from contextlib import ExitStack
import json
from pathlib import Path
from unittest.mock import patch

from ga_replay_scale import replay_case
from vessel_reconstruction import ga_commercial, ga_interpretation, ga_scale_arrangement
from vessel_reconstruction.provenance import write_json


def capture(run: Path, inputs: Path, out: Path) -> None:
    paths = sorted(run.glob("*/GA-*/ga_reading.json")) + sorted(run.glob("GA-*/ga_reading.json"))
    if len(paths) != 14:
        raise ValueError(f"expected 14 development cases, found {len(paths)}")
    out.mkdir(parents=True, exist_ok=False)
    with ExitStack() as stack:
        stack.enter_context(patch.object(ga_commercial, "call_model", side_effect=AssertionError("model call forbidden")))
        stack.enter_context(patch("subprocess.run", side_effect=AssertionError("subprocess forbidden")))
        for path in paths:
            case = path.parent
            target = out / case.name / "first-pass"
            target.mkdir(parents=True)
            reading = json.loads((case / "provider" / "vision_reading.json").read_text())
            result = ga_interpretation.interpret(reading, case / "request", inputs)
            write_json(target / "ga_reading.json", result)
            ga_interpretation.reinterpret_particulars(case, inputs, out / case.name / "particulars")
            gate = replay_case(path, inputs, out / case.name / "scale", [])
            if gate is None or not gate["passed"]:
                raise AssertionError("development arrangement gate failed")
    print("Captured 14 development cases; gate 14/14; model calls 0")


def compare(out: Path, before: Path, latest: Path) -> None:
    cases = sorted(out.glob("GA-*"))
    if len(cases) != 14:
        raise AssertionError("comparison requires 14 cases")
    outputs = ("first-pass/ga_reading.json", "particulars/ga_reading.json",
               "scale/ga_reading.json", "scale/ga_arrangement_input.json")
    for case in cases:
        for name in outputs:
            if (case / name).read_bytes() != (before / case.name / name).read_bytes():
                raise AssertionError(f"bytes differ: {case.name}/{name}")
        arrangement = case / "scale/ga_arrangement_input.json"
        if arrangement.read_bytes() != (latest / case.name / arrangement.name).read_bytes():
            raise AssertionError(f"latest arrangement differs: {case.name}")
        if not ga_scale_arrangement.arrangement_gate(json.loads(arrangement.read_text()))["passed"]:
            raise AssertionError("development arrangement gate failed")
    for name in outputs:
        print(f"{name}: byte-identical 14/14")
    print("Latest arrangement: byte-identical 14/14; gate 14/14; model calls 0")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--inputs", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--before", type=Path)
    parser.add_argument("--latest", type=Path)
    args = parser.parse_args()
    # Limit this lane's runner to its explicitly permitted development round.
    if args.run.resolve().parts[-2:] != ("dev-runs", "u10"):
        parser.error("only dev-runs/u10 is permitted")
    if bool(args.before) != bool(args.latest):
        parser.error("--before and --latest must be supplied together")
    capture(args.run, args.inputs, args.out)
    if args.before:
        compare(args.out, args.before, args.latest)


if __name__ == "__main__":
    main()
