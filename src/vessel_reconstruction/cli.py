from __future__ import annotations

import argparse
import json
from pathlib import Path


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="vessel-reconstruct", description="Reconstruct evidenced hull envelopes from calibrated drawing views.")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("reconstruct", help="Read drawing pixels and export a measured hull envelope.")
    p.add_argument("spec", type=Path)
    p.add_argument("--out", required=True, type=Path)
    p.add_argument("--no-cad", action="store_true", help="Skip STEP/STL exports for fast evaluations; geometry kernel and mesh still run.")
    p = sub.add_parser("verify", help="Check the source and export hashes of a run.")
    p.add_argument("run", type=Path)
    p = sub.add_parser("review", help="Record a named local review decision; this never certifies engineering.")
    p.add_argument("run", type=Path)
    p.add_argument("--decision", choices=["accept_geometry", "reject", "needs_information"], required=True)
    p.add_argument("--reviewer", required=True)
    p.add_argument("--notes", required=True)
    p.add_argument("--expected-run-id", required=True)
    p = sub.add_parser("snapshot", help="Create a self-contained interactive HTML inspection file from a real run.")
    p.add_argument("run", type=Path)
    p.add_argument("--out", required=True, type=Path)
    p = sub.add_parser("serve", help="Start the local review workbench.")
    p.add_argument("--artifacts", type=Path, default=Path("artifacts"))
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--host", default="127.0.0.1")
    args = parser.parse_args(argv)
    if args.command == "reconstruct":
        from .pipeline import reconstruct
        try:
            r = reconstruct(args.spec, args.out, export_cad=not args.no_cad)
        except FileExistsError as exc:
            parser.error(str(exc))
        print(json.dumps({"run_id": r["run_id"], "status": r["status"], "output": str(args.out.resolve()), "metrics": r["metrics"], "gaps": r["gaps"]}, indent=2))
        return 0 if r["status"] == "review_required" else 2
    if args.command == "verify":
        from .pipeline import verify_run
        r = verify_run(args.run)
        print(json.dumps(r, indent=2))
        return 0 if r["valid"] else 2
    if args.command == "review":
        from .review import record_review
        r = record_review(args.run, decision=args.decision, reviewer=args.reviewer, notes=args.notes, expected_run_id=args.expected_run_id)
        print(json.dumps(r, indent=2))
        return 0
    if args.command == "snapshot":
        from .server import write_snapshot
        p = write_snapshot(args.run, args.out)
        print(str(p.resolve()))
        return 0
    if args.command == "serve":
        from .server import serve
        serve(artifacts_dir=args.artifacts, host=args.host, port=args.port)
    return 0

