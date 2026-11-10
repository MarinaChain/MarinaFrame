"""Round 13: frozen body-plan reader on BUMBLE BEE 47, HAER OR-165 sheet 2 ("Lines").

Protocol: docs/holdouts/round13-bumble-bee.md. Truth and all run outputs stay outside the
repository. Only the sheet calibration, the truth loader and the scorer dimensions differ from
round 12 (BUE GIRL); the printed-value parser and the run orchestration are reused.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path

from benchmarks.balclutha import crossing_value as round8
from benchmarks.balclutha import model_value as round4
from benchmarks.balclutha import router_value as round6
from benchmarks.bue_girl import holdout_value as bue_girl
from benchmarks.thayer import holdout_value as thayer
from benchmarks.frozen_readers.v1 import body_plan_crossings as bpc
from benchmarks.frozen_readers.v1 import body_plan_reader as bpr

PROTOCOL = 'docs/holdouts/round13-bumble-bee.md'
SHEET_SHA256 = 'd1c0830dff9648b8c6967ead14fcaff484a91021eece277fda62725a0002f991'

# Host calibration (protocol section 2), measured from the drawn grid only.
CENTRE_COLUMN = 3009.0  # thin dashed centreline, ink columns 3007 to 3011
BASE_ROW = 8705  # dash-dot baseline of the body plan, ink rows 8703 to 8707
PIXELS_PER_FT = 400.0  # feet scale bar and buttock grid agree
PIXELS_PER_M = PIXELS_PER_FT / 0.3048
# Largest drawn half-breadth at a scored waterline is about 1,780 px; 120 px margin.
MAX_OFFSET_PX = 1900
# Waterline heights are the table row labels (feet-inches-eighths); rows = baseline - height.
WATERLINE_HEIGHTS_FT = {'1-6-0': 1.5, '2-3-0': 2.25, '3-0-0': 3.0, '3-9-0': 3.75}
WATERLINE_ROWS = {label: int(round(BASE_ROW - feet * PIXELS_PER_FT))
                  for label, feet in WATERLINE_HEIGHTS_FT.items()}
WATERLINES = tuple(WATERLINE_ROWS)
# Buttocks 1 to 4 ft each side of the centreline.
BUTTOCK_OFFSETS_FT = (1, 2, 3, 4)
FORE_STATIONS_OUTER_FIRST = (6, 5, 4, 3, 2, 1)
AFT_STATIONS_OUTER_FIRST = (7, 8, 9, 10, 11, 12, 13, 14)
STATIONS = tuple(range(1, 15))
# Printed table columns: station 0 is the stem (no curve in the body plan) and is never scored.
PRINTED_STATIONS = tuple(range(0, 15))
ARMS = ('code', 'crouton', 'sonnet')


def grid_columns(sign: int) -> tuple[float, ...]:
    return tuple(CENTRE_COLUMN + sign * feet * PIXELS_PER_FT for feet in BUTTOCK_OFFSETS_FT)


def sheet_layout() -> bpr.SheetLayout:
    """Fore half left of the centreline, aft half right."""
    sides = (bpr.SideLayout('fore', -1, FORE_STATIONS_OUTER_FIRST, grid_columns(-1)),
             bpr.SideLayout('aft', 1, AFT_STATIONS_OUTER_FIRST, grid_columns(1)))
    return bpr.SheetLayout(CENTRE_COLUMN, PIXELS_PER_M, dict(WATERLINE_ROWS), MAX_OFFSET_PX, sides)


printed_half_breadth = bue_girl.printed_half_breadth


def _check_excluded(entries: list) -> None:
    for entry in entries:
        if entry.get('station') not in STATIONS or entry.get('waterline') not in WATERLINES:
            raise ValueError(f'excluded cell outside the scored block: {entry!r}')
        if not entry.get('reason'):
            raise ValueError(f'excluded cell without a reason: {entry!r}')


def load_truth(path: Path) -> dict:
    """{(station, waterline label): half-breadth m} for the nonblank scored cells (section 6)."""
    data = json.loads(path.read_text())
    if data.get('sheet_sha256') != SHEET_SHA256:
        raise ValueError('truth is for a different sheet')
    if data['stations'] != list(PRINTED_STATIONS):
        raise ValueError('truth must list the printed stations 0 to 14 in order')
    if set(data['rows']) != set(WATERLINES):
        raise ValueError(f'truth rows must be exactly {list(WATERLINES)}')
    _check_excluded(data.get('excluded', []))
    truth = {}
    for waterline in WATERLINES:
        row = data['rows'][waterline]
        if len(row) != len(PRINTED_STATIONS):
            raise ValueError(f'{waterline}: expected {len(PRINTED_STATIONS)} station cells')
        for station, value in zip(PRINTED_STATIONS, row):
            if station in STATIONS and value is not None:
                truth[(station, waterline)] = printed_half_breadth(value)
    return truth


def score(table: dict, truth: dict) -> dict:
    return round4.score(table, truth, STATIONS, WATERLINES)


def check_sheet(sheet_path: Path) -> None:
    digest = hashlib.sha256(sheet_path.read_bytes()).hexdigest()
    if digest != SHEET_SHA256:
        raise ValueError(f'sheet SHA-256 {digest} is not the protocol sheet')


def run(arm: str, sheet_path: Path, truth_path: Path, out: Path, call=None) -> dict:
    """One code run or three fixed model repeats; never overwrite an earlier arm."""
    check_sheet(sheet_path)
    truth = load_truth(truth_path)
    out.mkdir(parents=True, exist_ok=False)
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
