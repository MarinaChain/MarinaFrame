#!/usr/bin/env python3
"""Screen a caller-supplied fleet. Run from the repo with PYTHONPATH=src.

No fleet is bundled. Every complete fleet row needs a source citation and a
shared design_id for sister ships. Unknown JSON fields fail construction.
"""

import argparse
import json
from pathlib import Path

from vessel_reconstruction.concept_dimensions import FleetModel, FleetShip, Requirements


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fleet", required=True, type=Path)
    parser.add_argument("--requirements", required=True, type=Path)
    parser.add_argument("--exclude-ship", action="append", default=[])
    parser.add_argument("--exclude-design", action="append", default=[])
    args = parser.parse_args()
    try:
        rows = [FleetShip(**row) for row in json.loads(args.fleet.read_text())]
        requirements = Requirements(**json.loads(args.requirements.read_text()))
        model = FleetModel.fit(rows, excluded_ship_ids=args.exclude_ship,
                               excluded_design_ids=args.exclude_design)
        result = model.propose(requirements).to_record_fragment()
        print(json.dumps(result, indent=2, sort_keys=True, allow_nan=False))
    except (OSError, ValueError, TypeError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()
