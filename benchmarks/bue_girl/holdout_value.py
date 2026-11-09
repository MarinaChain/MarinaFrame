"""Round 12: frozen body-plan reader on BUE GIRL, HAER OR-166 sheet 2.

Protocol: plan section 3.5.11. Truth and all run outputs stay outside the repository.
Only sheet calibration, printed-value parsing and scorer dimensions differ from Thayer.
"""
from __future__ import annotations

import argparse
import json
import re
import time
from pathlib import Path

from benchmarks.balclutha import crossing_value as round8
from benchmarks.balclutha import model_value as round4
from benchmarks.balclutha import router_value as round6
from benchmarks.thayer import holdout_value as thayer
from vessel_reconstruction import body_plan_crossings as bpc
from vessel_reconstruction import body_plan_reader as bpr

PROTOCOL = 'docs/plans/2026-11-09-whole-vessel-scope.md 3.5.11'
CENTRE_COLUMN = 3266.5
BASE_ROW = 9082
PIXELS_PER_FT = 400.0
PIXELS_PER_M = PIXELS_PER_FT / 0.3048
MAX_OFFSET_PX = 1650
WATERLINE_ROWS = {'2-6-0': 8081, '3-6-0': 7681, '4-6-0': 7281,
                  '5-6-0': 6880, '6-6-0': 6480}
WATERLINES = tuple(WATERLINE_ROWS)
STATIONS = tuple(range(1, 13))
ARMS = ('code', 'crouton', 'sonnet')


def sheet_layout() -> bpr.SheetLayout:
    sides = (bpr.SideLayout('fore', -1, (6, 5, 4, 3, 2, 1),
                            (2966, 2698, 2430, 2162, 1894, 1693)),
             bpr.SideLayout('aft', 1, (7, 8, 9, 10, 11, 12),
                            (3566, 3834, 4102, 4370, 4638)))
    return bpr.SheetLayout(CENTRE_COLUMN, PIXELS_PER_M, dict(WATERLINE_ROWS), MAX_OFFSET_PX, sides)


def printed_half_breadth(value: str) -> float:
    """Magnitude in metres; leading dash is a separator, trailing + adds 1/16 inch."""
    match = re.fullmatch(r'\s*-?\s*(\d+)\s*-\s*(\d+)\s*-\s*([0-7])\s*(\+)?\s*', value)
    if match is None:
        raise ValueError(f'invalid feet-inches-eighths half-breadth: {value!r}')
    feet, inches, eighths = (int(match[i]) for i in (1, 2, 3))
    if inches >= 12:
        raise ValueError(f'inches out of range: {value!r}')
    plus_inches = 1 / 16 if match[4] else 0
    return (feet + (inches + eighths / 8 + plus_inches) / 12) * 0.3048


def load_truth(path: Path) -> dict:
    data = json.loads(path.read_text())
    if data['stations'] != list(STATIONS):
        raise ValueError('truth must contain numbered stations 1 to 12 in order')
    truth = {}
    for waterline in WATERLINES:
        row = data['rows'][waterline]
        if len(row) != len(STATIONS):
            raise ValueError(f'{waterline}: expected 12 station cells')
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
    summary = {'protocol': PROTOCOL, 'arm': arm, 'measurement': measured, 'repeats': results,
               'median_rms_m': median, 'passes_rule': passes, 'engineering_approved': False}
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
