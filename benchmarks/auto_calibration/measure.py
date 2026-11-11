"""Measure the automatic body-plan calibration against the five hand calibrations (docs/AUTO_CALIBRATION.md).

Per field: centreline, waterline rows, px/ft, side assignment and station order, auto vs hand.
End to end: the frozen reader (code-only identity) with the auto and the hand calibration, scored
with each sheet's harness scorer. Truth and outputs stay outside the repository.

Usage (main checkout sheets; truth paths outside the repository)::

    PYTHONPATH=src:. .venv/bin/python -m benchmarks.auto_calibration.measure \\
        --sources ../../../work/sources --truth-dir <folder with the truth files> \\
        --cache <answers folder> --out <result.json>
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from PIL import Image

from benchmarks.balclutha import crossing_value as round8
from benchmarks.balclutha import model_value as round4
from benchmarks.bue_girl import holdout_value as bue_girl
from benchmarks.bumble_bee import holdout_value as bumble_bee
from benchmarks.pardon_me import holdout_value as pardon_me
from benchmarks.thayer import holdout_value as thayer
from vessel_reconstruction import body_plan_crossings as bpc
from vessel_reconstruction import body_plan_reader as bpr
from vessel_reconstruction import calibration_reading as cr
from vessel_reconstruction import sheet_calibration as sc

FEET_M = 0.3048


def bumble_bee_corrected() -> bpr.SheetLayout:
    """Round-13 calibration with the sides corrected to the truth's numbering (plan section 4)."""
    layout = bumble_bee.sheet_layout()
    sides = (bpr.SideLayout('aft', -1, (9, 10, 11, 12, 13, 14), bumble_bee.grid_columns(-1)),
             bpr.SideLayout('fore', 1, (8, 7, 6, 5, 4, 3, 2, 1), bumble_bee.grid_columns(1)))
    return bpr.SheetLayout(layout.centre_column, layout.pixels_per_metre, layout.waterline_rows,
                           layout.max_offset_px, sides)


def _feet(label) -> float:
    return sc.parse_feet(str(label))


# name -> (sheet file, hand layout, hand baseline row, waterline label -> height ft, truth loader, truth file, scorer)
CASES = {
    'balclutha': ('balclutha_ca54_s7.tif', round8.sheet_layout, 6857.6,
                  lambda w: float(w), round4.load_truth, 'balclutha/truth_s7.json', round8.score),
    'thayer': ('haer/ca_thayer/loc_ca1506_sheet_04.tif', thayer.sheet_layout, thayer.BASE_ROW,
               _feet, thayer.load_truth, 'thayer/truth_s4.json', thayer.score),
    'bue_girl': ('haer/master-pnp-habshaer-or-or0500-or0590-sheet-00002a.tif', bue_girl.sheet_layout,
                 bue_girl.BASE_ROW, _feet, bue_girl.load_truth, 'bue-girl/truth_s2.json', bue_girl.score),
    'bumble_bee': ('haer/master-pnp-habshaer-or-or0500-or0589-sheet-00002a.tif', bumble_bee_corrected,
                   bumble_bee.BASE_ROW, _feet, bumble_bee.load_truth, 'bumble-bee/truth_s2.json', bumble_bee.score),
    'pardon_me': ('haer/master-pnp-habshaer-ny-ny2300-ny2390-sheet-00004a.tif', pardon_me.sheet_layout,
                  pardon_me.BASE_ROW, pardon_me.waterline_height_ft, pardon_me.load_truth,
                  'pardon-me/truth_s4.json', pardon_me.score),
}


def side_of(layout: bpr.SheetLayout, name: str) -> bpr.SideLayout:
    return next(side for side in layout.sides if side.name == name)


def field_errors(cal: sc.Calibration, hand: bpr.SheetLayout, hand_base: float, heights: dict) -> dict:
    hand_px_ft = hand.pixels_per_metre * FEET_M
    result = {'flags': [f'{f.field}: {f.message}' for f in cal.flags], 'usable': cal.usable}
    if cal.centre_column is not None:
        result['centre_px'] = round(cal.centre_column - hand.centre_column, 1)
    if cal.pixels_per_ft:
        result['px_per_ft_pct'] = round(100 * (cal.pixels_per_ft - hand_px_ft) / hand_px_ft, 3)
    if cal.baseline_row is not None and cal.pixels_per_ft:
        result['baseline_px'] = round(cal.baseline_row - hand_base, 1)
        result['waterline_rows_max_px'] = max(abs(cal.row_at(heights[w]) - hand.waterline_rows[w])
                                              for w in hand.waterline_rows)
    if len(cal.sides) == 2:
        auto_fore = next(s for s in cal.sides if s['name'] == 'fore')
        hand_fore = side_of(hand, 'fore')
        result['side'] = ('exact' if auto_fore['sign'] == hand_fore.sign else 'wrong') + (
            ', flagged' if cal.flagged('sides') else '')
        result['station_order'] = all(
            tuple(next(s for s in cal.sides if s['name'] == name)['stations_outer_first'])
            == side_of(hand, name).stations_outer_first for name in ('fore', 'aft'))
        result['stations_auto'] = {s['name']: s['stations_outer_first'] for s in cal.sides}
        result['max_offset_px'] = {'auto': cal.max_offset_px, 'hand': hand.max_offset_px}
    return result


def reader_score(ink, layout, truth, scorer) -> dict:
    readings = round8.measure(ink, layout)
    result = round8.run_code(readings, layout, truth, scorer=scorer)
    return {key: result.get(key) for key in ('cells_given', 'truth_cells', 'rms_m', 'max_abs_m', 'identity_errors')}


def auto_with_hand_sides(cal: sc.Calibration, hand: bpr.SheetLayout, heights: dict) -> bpr.SheetLayout:
    """Auto geometry with the hand side assignment and station order (a person's side choice)."""
    layout = cal.layout(heights)
    sides = []
    for side in hand.sides:
        auto = next(s for s in cal.sides if s['sign'] == side.sign) if len(cal.sides) == 2 else None
        grid = tuple(auto['grid_columns']) if auto else side.grid_columns
        sides.append(bpr.SideLayout(side.name, side.sign, side.stations_outer_first, grid))
    return bpr.SheetLayout(layout.centre_column, layout.pixels_per_metre, layout.waterline_rows,
                           layout.max_offset_px, tuple(sides))


def measure_case(name: str, sources: Path, truth_dir: Path, cache: Path, ask) -> dict:
    sheet, hand_layout, hand_base, height_of, load_truth, truth_file, scorer = CASES[name]
    path = sources / sheet
    with Image.open(path) as image:
        dpi = float((image.info.get('dpi') or (0,))[0]) or None
    ink = bpc.load_ink(path)
    hand = hand_layout()
    heights = {w: height_of(w) for w in hand.waterline_rows}
    reading = cr.ClaudeReading(ask, cache / name, sheet_id=name)
    started = time.time()
    cal = sc.calibrate(ink, reading, dpi=dpi)
    result = {'sheet': name, 'seconds': round(time.time() - started, 1), 'model_calls': reading.calls,
              'calibration': cal.to_json(), 'fields': field_errors(cal, hand, hand_base, heights),
              'reading_log': reading.log}
    truth_path = truth_dir / truth_file
    if truth_path.exists():
        truth = load_truth(truth_path)
        result['hand'] = reader_score(ink, hand, truth, scorer)
        if cal.usable:
            result['auto'] = reader_score(ink, cal.layout(heights), truth, scorer)
            result['auto_geometry_hand_sides'] = reader_score(ink, auto_with_hand_sides(cal, hand, heights),
                                                              truth, scorer)
    else:
        result['truth'] = f'not found: {truth_path}'
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('--sources', type=Path, required=True)
    parser.add_argument('--truth-dir', type=Path, required=True,
                        help='folder holding balclutha/, thayer/, bue-girl/, bumble-bee/, pardon-me/ truth files')
    parser.add_argument('--cache', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--sheets', nargs='*', default=list(CASES))
    args = parser.parse_args()
    ask = cr.claude_ask(receipts=args.cache / 'receipts')
    results = {}
    for name in args.sheets:
        results[name] = measure_case(name, args.sources, args.truth_dir, args.cache, ask)
        print(json.dumps({name: {k: results[name].get(k) for k in ('fields', 'hand', 'auto',
                                                                    'auto_geometry_hand_sides', 'model_calls')}},
                         default=str), flush=True)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps({'engineering_approved': False, 'results': results}, indent=2, default=str) + '\n')


if __name__ == '__main__':
    main()
