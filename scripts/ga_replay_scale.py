"""Replay the stored frame-scale replies of a GA run through the current code, with no model call.

For each case of a stored development run (``ga_commercial batch --measure --out``), this drops
the measured values and extents from its ``ga_reading.json``, runs the frame-scale pass again with
the replies stored under ``<case>/scale/<request>-provider/`` (or in an ``--also`` folder), and
writes ``<out>/<case>/ga_reading.json`` and ``ga_arrangement_input.json``. A request that no
folder has a reply for gets none, as in a run where the model did not answer; nothing is sent.
It prints lane W's gate per case. Development ships only.

    PYTHONPATH=src python scripts/ga_replay_scale.py --run RUN --inputs INPUTS --out OUT [--also DIR ...]
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from vessel_reconstruction import ga_scale, ga_scale_arrangement, ga_scale_settings
from vessel_reconstruction.ga_counts import drop_fragments
from vessel_reconstruction.provenance import write_json

def stored_reply(request_name: str, folders: list[Path]) -> dict:
    """The stored reply of one request from the first folder that has it, or no reply."""
    for folder in folders:
        stored = folder / "scale" / f"{request_name}-provider" / "vision_reading.json"
        if stored.exists():
            return json.loads(stored.read_text())
    return {"reply": None, "stop_reason": "not stored in the replayed run", "usage": {}, "receipts": []}


def replay_case(reading_path: Path, inputs: Path, target: Path, also: list[Path]) -> dict | None:
    """Replay one case into ``target``; returns lane W's gate, or None without a GA."""
    case_dir = reading_path.parent
    result = json.loads(reading_path.read_text())
    for key in ("frames", "measured"):
        result.pop(key, None)
    # The checks of the frame-scale pass are made again by the replay.
    result["checks"] = [c for c in result["checks"] if c.get("code") not in ga_scale_settings.SCALE_PASS_CHECKS]
    for space in result["spaces"]:
        space.pop("extent", None)
    drop_fragments(result)
    folders = [case_dir, *(folder / case_dir.name for folder in also)]
    target.mkdir(parents=True)
    gate = None
    if "ga" in result.get("sources", {}):
        result.setdefault("passes", {})["scale"] = ga_scale.scale_pass(
            result, inputs / result["sources"]["ga"]["file"], target / "scale",
            lambda request_dir, provider_dir: stored_reply(request_dir.name, folders))
        arrangement = ga_scale_arrangement.arrangement_input(result, case_dir.name)
        write_json(target / "ga_arrangement_input.json", arrangement)
        gate = ga_scale_arrangement.arrangement_gate(arrangement)
    result["replayed_from"] = str(case_dir)
    write_json(target / "ga_reading.json", result)
    return gate


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--run", required=True, type=Path, help="A stored run: <case>/ or <group>/<case>/ folders.")
    parser.add_argument("--inputs", required=True, type=Path, help="The folder of the case images.")
    parser.add_argument("--out", required=True, type=Path, help="A new folder.")
    parser.add_argument("--also", nargs="*", type=Path, default=[],
                        help="Later runs that hold replies the run lacks (deck top-ups, redraws).")
    args = parser.parse_args(argv)
    if args.out.exists():
        parser.error(f"{args.out} exists; give a new folder")
    readings = sorted(list(args.run.glob("*/GA-*/ga_reading.json")) + list(args.run.glob("GA-*/ga_reading.json")))
    for reading_path in readings:
        gate = replay_case(reading_path, args.inputs, args.out / reading_path.parent.name, args.also)
        if gate is not None:
            print(f"{reading_path.parent.name}: gate {'pass' if gate['passed'] else 'FAIL'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
