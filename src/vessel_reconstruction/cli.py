from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def main(argv=None) -> int:
    argv=list(sys.argv[1:] if argv is None else argv)
    parser = argparse.ArgumentParser(prog="vessel-reconstruct", description="Reconstruct evidenced hull envelopes from calibrated drawing views.")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("reconstruct", help="Read drawing pixels and export a measured hull envelope.")
    p.add_argument("spec", type=Path)
    p.add_argument("--out", required=True, type=Path)
    p.add_argument("--no-cad", action="store_true", help="Skip STEP/STL exports for fast evaluations; geometry kernel and mesh still run.")
    p = sub.add_parser("verify", help="Check the source and export hashes of a run.")
    p.add_argument("run", type=Path)
    args = parser.parse_args(argv)
    if args.command == "reconstruct":
        from .isolation import run_isolated
        try:
            execution = run_isolated(args.spec, args.out, export_cad=not args.no_cad)
        except FileExistsError as exc:
            parser.error(str(exc))
        r = execution.get("result")
        summary = {"state": execution["state"], "output": str(args.out.resolve()),
                   "elapsed_seconds": execution.get("elapsed_seconds"),
                   "resources": execution.get("resources"), "error_code": execution.get("error_code")}
        if r is not None:
            summary.update(run_id=r["run_id"], status=r["status"], metrics=r["metrics"], gaps=r["gaps"])
        print(json.dumps(summary, indent=2))
        return 0 if execution["state"] == "succeeded" and r and r["status"] == "review_required" else 2
    if args.command == "verify":
        from .pipeline import verify_run
        r = verify_run(args.run)
        print(json.dumps(r, indent=2))
        return 0 if r["valid"] else 2
    return 0
