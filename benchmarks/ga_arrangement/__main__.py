"""Build an estimated 3D arrangement run from a GA reading with extents.

    PYTHONPATH=src:. python -m benchmarks.ga_arrangement --reading READING.json --image GA.png \\
        --out work/ga-arrangement-demo --split work/ga-internal-23/SPLIT.json

The case must be a development case of the split (``--split``); a reading marked
``test_fixture`` is built only with ``--test-fixture`` and its run is named as test data.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .run_folder import generate


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--reading", type=Path, required=True, help="GA reading with extents (marinaframe.ga_reading.v1)")
    parser.add_argument("--image", type=Path, required=True, help="the GA image the reading is of")
    parser.add_argument("--out", type=Path, required=True, help="output folder (git-ignored, under work/)")
    parser.add_argument("--split", type=Path, help="SPLIT.json: the case must be one of its development_cases")
    parser.add_argument("--test-fixture", action="store_true", help="allow a reading marked test_fixture")
    parser.add_argument("--source-round", help="the GA reader's round id of this reading (kept in ga_estimate.json)")
    parser.add_argument("--source-commit", help="the GA reader's commit (kept in ga_estimate.json)")
    args = parser.parse_args()
    reading = json.loads(args.reading.read_text())
    case_id = str(reading.get("case_id") or "")
    if args.split is not None:
        development = json.loads(args.split.read_text())["development_cases"]
        if case_id not in development:
            parser.error(f"{case_id} is not a development case of {args.split}")
    if reading.get("test_fixture") is True and not args.test_fixture:
        parser.error("this reading is test data; pass --test-fixture to build it (never for a demo)")
    slug = f"{case_id.lower()}-ga-estimate" + ("-test-fixture" if reading.get("test_fixture") is True else "")
    run_name = f"{case_id} estimated arrangement" + (" (TEST DATA)" if reading.get("test_fixture") is True else "")
    source = {"reading_file": args.reading.name, "round": args.source_round, "reader_commit": args.source_commit}
    result = generate(reading, args.image, args.out, slug, run_name, source)
    print(json.dumps({"task": result["task"], "summary": result["summary"]}, indent=1))


if __name__ == "__main__":
    main()
