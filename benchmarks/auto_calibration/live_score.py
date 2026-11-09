"""Score a live app-path run on BUE GIRL against the frozen truth (docs/AUTO_CALIBRATION.md 5.3).

Two tables are scored with the round-12 scorer: the intake's body-plan reading (the reader's
waterline cells, as the hull path receives them) and the first hull's station rows (half-breadth
at each truth waterline height, interpolated along the built row). Outputs stay out of the repo.

    PYTHONPATH=src:. .venv/bin/python -m benchmarks.auto_calibration.live_score \\
        --case <round>/bue_girl --truth <truth_s2.json>
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from benchmarks.bue_girl import holdout_value as bue_girl
from vessel_reconstruction import body_plan_intake as bpi

FEET_M = 0.3048


def heights_m() -> dict:
    return {w: bue_girl.printed_half_breadth(w) for w in bue_girl.WATERLINES}


def intake_table(reading: dict) -> dict:
    table = {}
    for station in reading.get('stations', []):
        for z, y in station['cells_z_y_m']:
            for label, height in heights_m().items():
                if abs(z - height) < 0.02:
                    table[(station['station'], label)] = y
    return table


def hull_table(vessel: dict) -> dict:
    table = {}
    for row in vessel['table']['stations']:
        number = bpi.station_number(row['id'])
        if number is None:
            continue
        points = np.array(sorted(row['points_yz_m'], key=lambda p: p[1]))
        for label, height in heights_m().items():
            if points[0, 1] <= height <= points[-1, 1]:
                table[(number, label)] = float(np.interp(height, points[:, 1], points[:, 0]))
    return table


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('--case', type=Path, required=True)
    parser.add_argument('--truth', type=Path, required=True)
    args = parser.parse_args()
    truth = bue_girl.load_truth(args.truth)
    intake = json.loads((args.case / 'intake' / 'run-input' / 'intake.json').read_text())
    reading = intake.get('body_plan_reading') or {}
    result = {'reader_used_for_build': None, 'calibration_flags': reading.get('calibration', {}).get('flags'),
              'calibration_notes': reading.get('calibration', {}).get('notes'),
              'intake_reader': bue_girl.score(intake_table(reading), truth), 'engineering_approved': False}
    check = args.case / 'task' / 'domain' / bpi.CHECK_JSON
    if check.exists():
        result['reader_used_for_build'] = json.loads(check.read_text())
    vessel = args.case / 'task' / 'domain' / 'vessel.json'
    if vessel.exists():
        result['first_hull'] = bue_girl.score(hull_table(json.loads(vessel.read_text())), truth)
    print(json.dumps(result, indent=2, default=str))


if __name__ == '__main__':
    main()
