"""Round 14: frozen body-plan reader on PARDON ME, HAER NY-547 sheet 4.

Protocol: docs/holdouts/round14-pardon-me.md. Truth and all run outputs stay outside the
repository. Only sheet calibration and scorer dimensions differ from round 12 (BUE GIRL);
the printed-value parser, the scorer and the model transports are reused unchanged.
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from benchmarks.balclutha import crossing_value as round8
from benchmarks.balclutha import model_value as round4
from benchmarks.balclutha import router_value as round6
from benchmarks.bue_girl import holdout_value as round12
from benchmarks.thayer import holdout_value as thayer
from benchmarks.frozen_readers.v1 import body_plan_crossings as bpc
from benchmarks.frozen_readers.v1 import body_plan_reader as bpr

PROTOCOL = 'docs/holdouts/round14-pardon-me.md'
CENTRE_COLUMN = 3270.0
BASE_ROW = 5229  # the drawn "W0 BASELINE" row of the body plan
PIXELS_PER_FT = 300.0  # waterline grid and feet scale bar agree
PIXELS_PER_M = PIXELS_PER_FT / 0.3048
# Clears the outermost drawn curve (1451 px) and stops before the "W0 BASELINE" label (1590 px).
MAX_OFFSET_PX = 1550
# Printed table labels (feet-inches-eighths above W0) -> body-plan row; W-2 is not drawn.
WATERLINE_ROWS = {'3-0-0': 4329, '2-0-0': 4629, '1-0-0': 4929, '0-0-0': 5229,
                  '-1-0-0': 5529, '-2-0-0': 5829}
WATERLINES = tuple(WATERLINE_ROWS)
STATIONS = tuple(range(1, 12))
AFT_STATIONS_OUTER_FIRST = (6, 7, 8, 9, 10, 11)
FORE_STATIONS_OUTER_FIRST = (5, 4, 3, 2, 1)
AFT_GRID_COLUMNS = (2970, 2670, 2370, 2070)  # buttocks 1 to 4 ft, left of the centreline
FORE_GRID_COLUMNS = (3570, 3871, 4171, 4471)  # buttocks 1 to 4 ft, right of the centreline
ARMS = ('code', 'crouton', 'sonnet')

printed_half_breadth = round12.printed_half_breadth


def waterline_height_ft(label: str) -> float:
    """Signed height above W0 of a printed waterline label such as '-1-0-0'."""
    magnitude = printed_half_breadth(label) / 0.3048
    return -magnitude if label.strip().startswith('-') else magnitude


def sheet_layout() -> bpr.SheetLayout:
    """Host calibration of sheet 4: aftbody left of the centreline, forebody right."""
    sides = (bpr.SideLayout('aft', -1, AFT_STATIONS_OUTER_FIRST, AFT_GRID_COLUMNS),
             bpr.SideLayout('fore', 1, FORE_STATIONS_OUTER_FIRST, FORE_GRID_COLUMNS))
    return bpr.SheetLayout(CENTRE_COLUMN, PIXELS_PER_M, dict(WATERLINE_ROWS), MAX_OFFSET_PX, sides)


def load_truth(path: Path) -> dict:
    """{(station, waterline label): half-breadth m} for the nonblank printed cells."""
    data = json.loads(path.read_text())
    if data['stations'] != list(STATIONS):
        raise ValueError('truth must contain numbered stations 1 to 11 in order')
    if set(data['rows']) != set(WATERLINES):
        raise ValueError(f'truth rows must be exactly {list(WATERLINES)}')
    truth = {}
    for waterline in WATERLINES:
        row = data['rows'][waterline]
        if len(row) != len(STATIONS):
            raise ValueError(f'{waterline}: expected {len(STATIONS)} station cells')
        for station, value in zip(STATIONS, row):
            if value is not None:
                truth[(station, waterline)] = printed_half_breadth(value)
    return truth


def score(table: dict, truth: dict) -> dict:
    return round4.score(table, truth, STATIONS, WATERLINES)


def run(arm: str, sheet_path: Path, truth_path: Path, out: Path, call=None) -> dict:
    """One code run or three fixed model repeats; never overwrite an earlier arm."""
    out.mkdir(parents=True, exist_ok=False)
    truth = load_truth(truth_path)
    sheet_pixels = bpc.load_ink(sheet_path)
    layout = sheet_layout()
    started = time.time()
    readings = round8.measure(sheet_pixels, layout)
    measured = {'seconds': round(time.time() - started, 1), 'sides': round8.measurement_summary(readings)}
    print(json.dumps({'measurement': measured}), flush=True)
    results = []
    repeats = 1 if arm == 'code' else round4.REPEATS
    if arm == 'code':
        results.append(round8.run_code(readings, layout, truth, scorer=score))
        print(json.dumps(results[-1]), flush=True)
    else:
        questions = round8.build_questions(sheet_pixels, readings, layout)
        if call is None:
            call = round8.crouton_with_fallback() if arm == 'crouton' else thayer.claude_call(thayer.SONNET)
        for repeat in range(1, repeats + 1):
            results.append(round8.run_repeat(readings, questions, layout, truth, out / f'R1-{repeat}', call,
                                             scorer=score))
            print(json.dumps(results[-1]), flush=True)
    median, passes = round6.decide(results, repeats)
    summary = {'protocol': PROTOCOL, 'arm': arm, 'truth_cells': len(truth), 'measurement': measured,
               'repeats': results, 'median_rms_m': median, 'passes_rule': passes,
               'engineering_approved': False}
    (out / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--arm', choices=ARMS, required=True)
    parser.add_argument('--sheet', type=Path, required=True)
    parser.add_argument('--truth', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    if args.arm == 'crouton':
        round6.load_go_key1()
    summary = run(args.arm, args.sheet, args.truth, args.out.resolve())
    print(json.dumps({key: value for key, value in summary.items() if key != 'repeats'}, indent=2))


if __name__ == '__main__':
    main()
