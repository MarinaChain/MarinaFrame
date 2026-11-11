"""Write the concept-preview survey launch: ``python -m benchmarks.concept_launch --out <folder>``."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .run_folder import generate


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True,
                        help="output folder (git-ignored, for example work/web-demo-runs/concept-survey-launch)")
    args = parser.parse_args()
    result = generate(args.out)
    print(json.dumps({"task": result["task"], "manifest_entry": result["manifest_entry"]}, indent=1))


if __name__ == "__main__":
    main()
