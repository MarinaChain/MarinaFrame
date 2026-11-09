"""Command line: write the exports of one task revision.

    python -m vessel_reconstruction.exports --task DIR --revision rN --out DIR [--draft-m T] [--tanks FILE]
        [--structure DIR]

Prints the manifest as JSON on stdout. Exit code 2 when the task has no usable
build for the revision.
"""
from __future__ import annotations

import argparse
import json
import sys

from ..tanks import load_tanks
from .offsets import DEFAULT_WATERLINE_INTERVALS
from .package import export_draft
from .source import ExportError


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m vessel_reconstruction.exports",
                                     description="Write the offsets CSV, hydrostatics, PDF report and package "
                                                 "of a draft build.")
    parser.add_argument("--task", required=True, help="task folder (holds domain/state.json)")
    parser.add_argument("--revision", required=True, help="revision, for example r3 or r0003")
    parser.add_argument("--out", required=True, help="folder for the export files (created when missing)")
    parser.add_argument("--draft-m", type=float, default=None,
                        help="design waterline height above the baseline, metres (default: the spec's "
                             "design_draft_m, else 0.6 x depth, marked as assumed)")
    parser.add_argument("--waterlines", type=int, default=DEFAULT_WATERLINE_INTERVALS,
                        help="equal waterline intervals when the spec gives no waterlines_m")
    parser.add_argument("--vessel", default=None, help="vessel name for file names (default: from the build)")
    parser.add_argument("--tanks", default=None,
                        help="tank model file (.npz from vessel_reconstruction.tanks.save_tanks): adds the "
                             "capacity plan and sounding tables")
    parser.add_argument("--structure", default=None,
                        help="folder with steel tables (*_steel_members.csv, *_steel_totals.csv) and OCX "
                             "files (*.3docx): copied into the package")
    args = parser.parse_args(argv)
    tanks = load_tanks(args.tanks) if args.tanks else None
    try:
        manifest = export_draft(args.task, args.revision, args.out, draft_m=args.draft_m,
                                waterline_intervals=args.waterlines, vessel=args.vessel, tanks=tanks,
                                structure_dir=args.structure)
    except ExportError as error:
        print(json.dumps({"error": str(error)}), file=sys.stderr)
        return 2
    print(json.dumps(manifest, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
