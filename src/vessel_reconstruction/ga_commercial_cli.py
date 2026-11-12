"""Commercial GA commercial cli."""
from __future__ import annotations

from .ga_commercial_settings import (
    IMAGE_SUFFIXES,
    MAX_REQUESTS_PER_SHIP,
    MODEL,
)
from .ga_images import (
    prepare,
)
from .ga_interpretation import (
    reinterpret_particulars,
)
from .provenance import write_json
from pathlib import Path
import argparse
import json


def case_files(inputs: Path, case: str) -> tuple[Path | None, Path | None]:
    """The GA (``<case>_GA.*``) and the particulars table (the one other ``<case>_*`` image)."""
    files = sorted(p for p in Path(inputs).glob(f"{case}_*") if p.suffix.lower() in IMAGE_SUFFIXES)
    ga = [p for p in files if p.stem.upper() == f"{case}_GA".upper()]
    others = [p for p in files if p not in ga]
    if len(ga) > 1 or len(others) > 1 or not files:
        raise ValueError(f"{case}: expected one {case}_GA image and at most one other image, found {len(files)}")
    return (ga[0] if ga else None), (others[0] if others else None)


def main(argv=None) -> int:
    from .ga_commercial import measure_one, read_one
    parser = _argument_parser()
    args = parser.parse_args(argv)
    if args.command == "reinterpret-particulars":
        changed = {}
        for reading_path in sorted(args.run.glob("*/ga_reading.json")):
            case_dir = reading_path.parent
            changed[case_dir.name] = reinterpret_particulars(case_dir, args.inputs, args.out / case_dir.name)
        print(json.dumps({"ok": True, "model_calls": 0, "changed": changed, "engineering_approved": False}))
        return 0
    if args.command == "prepare":
        manifest = prepare(args.ga, args.out, args.particulars)
        print(json.dumps({"ok": True, "images": len(manifest["images"]), "engineering_approved": False}))
        return 0
    if args.command == "measure":
        result = json.loads(args.reading.read_text())
        args.out.mkdir(parents=True, exist_ok=False)
        measure_one(result, args.ga.resolve(), args.out.resolve(), args.binary.resolve(), args.basis, args.model,
                    args.case)
        write_json(args.out / "ga_reading.json", result)
        print(json.dumps({"ok": True, "scale": result["passes"]["scale"], "engineering_approved": False}))
        return 0
    definitions = {"split_holds_are_separate": not args.one_hold_per_number,
                   "slop_holding_tank_is_slop": not args.slop_holding_tank_not_slop}
    if args.command == "read":
        result = read_one(args.ga, args.particulars, args.out, args.binary, args.basis, args.model, args.app_task,
                          measure=args.measure, max_requests=args.max_requests_per_ship, definitions=definitions)
        print(json.dumps({"ok": bool(result["spaces"] or result["counts"].get("cargo_holds", {}).get("status") == "read"),
                          "usage": result["usage"], "engineering_approved": False}))
        return 0
    return _run_batch(args, definitions)


def _argument_parser():
    parser = argparse.ArgumentParser(prog="python -m vessel_reconstruction.ga_commercial")
    commands = parser.add_subparsers(dest="command", required=True)
    prep = commands.add_parser("prepare", help="Write a ga_reading request directory.")
    prep.add_argument("--ga", type=Path)
    prep.add_argument("--particulars", type=Path)
    prep.add_argument("--out", required=True, type=Path)
    read = commands.add_parser("read", help="Prepare, call the model once (receipted) and interpret.")
    read.add_argument("--ga", type=Path)
    read.add_argument("--particulars", type=Path)
    read.add_argument("--app-task", type=Path, help="Also write a run folder for the desktop app.")
    batch = commands.add_parser("batch", help="Read cases <case>_* of an inputs folder, one request each.")
    batch.add_argument("--inputs", required=True, type=Path)
    batch.add_argument("--cases", required=True, nargs="+")
    batch.add_argument("--max-requests", required=True, type=int,
                       help="Campaign budget: stop before a case when this many requests were sent.")
    measure = commands.add_parser("measure", help="Frame-scale pass on an existing reading (up to seven requests).")
    measure.add_argument("--reading", required=True, type=Path, help="A ga_reading.json of this GA.")
    measure.add_argument("--ga", required=True, type=Path)
    measure.add_argument("--case", required=True)
    for command in (read, batch):
        # Off by default: the GA exam run (plan, "What the evaluator runs") sends three requests
        # a ship and reads printed values only.
        command.add_argument("--measure", action="store_true",
                             help="Also measure with the printed frame scale (up to seven more requests a ship).")
        command.add_argument("--max-requests-per-ship", type=int, default=MAX_REQUESTS_PER_SHIP,
                             help="Ceiling of requests for one ship: one coarse request, then fine requests "
                                  "until every label blob is read (default %(default)s).")
        command.add_argument("--one-hold-per-number", action="store_true",
                             help="Definition: holds numbered as halves (4A, 4F) count as one hold.")
        command.add_argument("--slop-holding-tank-not-slop", action="store_true",
                             help="Definition: a slop holding tank is not counted as a slop tank.")
    again = commands.add_parser(
        "reinterpret-particulars",
        help="Rebuild the particulars of a stored run with the current checks; no model call.")
    again.add_argument("--run", required=True, type=Path, help="A batch --out folder (<case>/ga_reading.json).")
    again.add_argument("--inputs", required=True, type=Path, help="The folder of the case images of that run.")
    again.add_argument("--out", required=True, type=Path, help="A new folder: <case>/ga_reading.json.")
    for command in (read, batch, measure):
        command.add_argument("--out", required=True, type=Path)
        command.add_argument("--binary", required=True, type=Path)
        command.add_argument("--basis", required=True)
        command.add_argument("--model", default=MODEL)
    return parser


def _run_batch(args, definitions):
    from .ga_commercial import read_one
    ledger = {"schema": "marinaframe.ga_batch.v1", "model": args.model, "max_requests": args.max_requests,
              "cases": {}, "engineering_approved": False}
    sent = 0
    for case in args.cases:
        if sent >= args.max_requests:
            ledger["cases"][case] = {"status": "not_run_budget"}
            continue
        try:
            ga, particulars = case_files(args.inputs, case)
            result = read_one(ga, particulars, args.out / case, args.binary, args.basis, args.model,
                              measure=args.measure, case_id=case, max_requests=args.max_requests_per_ship,
                              definitions=definitions)
            sent += result["usage"]["requests"]
            ledger["cases"][case] = {"status": "read", "usage": result["usage"]}
        except (OSError, ValueError, RuntimeError) as error:
            ledger["cases"][case] = {"status": "failed", "error": str(error)[:300]}
        write_json(args.out / "batch.json", ledger)
    totals = {key: sum(c.get("usage", {}).get(key, 0) for c in ledger["cases"].values())
              for key in ("requests", "prompt_tokens", "completion_tokens", "list_cost_usd")}
    ledger["totals"] = totals
    write_json(args.out / "batch.json", ledger)
    print(json.dumps({"ok": True, "totals": totals, "engineering_approved": False}))
    return 0
