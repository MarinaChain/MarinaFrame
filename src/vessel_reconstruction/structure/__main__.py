"""Command line: read one midship section sheet into a member list.

    python -m vessel_reconstruction.structure SHEET.pdf --out members.json \
        [--mode auto|vector|raster] [--step slice.step --slice-length-mm 1000]
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from . import read_section_pdf


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Read structural members from a midship section PDF.")
    parser.add_argument("pdf", type=Path)
    parser.add_argument("--out", type=Path, required=True, help="member list (JSON)")
    parser.add_argument("--mode", choices=("auto", "vector", "raster"), default="auto")
    parser.add_argument("--step", type=Path, help="optional STEP slice of the members")
    parser.add_argument("--slice-length-mm", type=float, default=1000.0,
                        help="length along the ship of the STEP slice (not read from the drawing)")
    args = parser.parse_args(argv)
    result = read_section_pdf(args.pdf, mode=args.mode)
    report = result.as_dict()
    if args.step:
        from .solid import export_slice_step
        omitted = export_slice_step(result, args.step, args.slice_length_mm)
        report["step"] = {"path": str(args.step), "slice_length_mm": args.slice_length_mm,
                          "slice_length_source": "caller", "omitted_members": omitted}
    args.out.write_text(json.dumps(report, indent=1))
    print(f"{len(result.members)} members, {len(result.abstentions)} abstentions -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
