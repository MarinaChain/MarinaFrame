"""WHITE GULL, COLLEEN or CALEB JONES hard-chine holdout: one run of the frozen reader, reader v2 and the
polyline reader (product rule) with the committed calibration and scorer (no model calls).

All three readers run before the truth file is read; truth is used for scoring only. Writes the
result JSON and an overlay (polyline stations with chine / rabbet / sheer marks, v2 chine line and
chine points) for the by-eye gate.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import time
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from benchmarks.balclutha import crossing_value as cv
from benchmarks.deadrise_holdout import score as sc
from benchmarks.frozen_readers.v1 import body_plan_crossings as crossings
from vessel_reconstruction import body_plan_polyline as polyline
from benchmarks.frozen_readers.v1 import body_plan_reader as reader
from benchmarks.hard_chine import reader_v2 as v2

BOATS = {'white-gull': 'benchmarks.white_gull.holdout_value', 'colleen': 'benchmarks.colleen.holdout_value',
         'caleb-jones': 'benchmarks.caleb_jones.holdout_value',
         'cama-beach-skiff-22': 'benchmarks.cama_beach_skiff_22.holdout_value'}  # calibration committed before its one run
ARMS = ('frozen', 'v2', 'polyline')


def overlay(ink, halves, sides, cal, out: Path) -> None:
    top, bottom, left, right = cal.OVERLAY_REGION
    image = Image.fromarray(np.where(ink[top:bottom, left:right], 0, 255).astype(np.uint8)).convert('RGB')
    draw = ImageDraw.Draw(image)
    for side in sides.values():
        if side.line is not None:
            colour = (255, 0, 0) if side.uses_chine else (255, 160, 0)
            draw.line([(c - left, r - top) for r, c in side.line.points], fill=colour, width=2)
        for point in side.chine_points:
            x, y = point.column - left, point.row - top
            draw.rectangle([x - 7, y - 7, x + 7, y + 7], outline=(0, 120, 255), width=2)
    for half in halves.values():
        for station in half.stations + half.unnamed:  # engaged stations are among the unnamed
            colour = (220, 0, 0) if station.station is not None else (255, 150, 0)
            draw.line([(c - left, r - top) for r, c in station.points], fill=colour, width=3)
            for (row, column), mark in ((station.chine, (0, 160, 0)), (station.rabbet, (0, 0, 255)),
                                        (station.sheer, (160, 0, 160))):
                x, y = column - left, row - top
                draw.ellipse([x - 8, y - 8, x + 8, y + 8], outline=mark, width=3)
            x, y = station.chine[1] - left, station.chine[0] - top
            draw.text((x + 10, y + 10), str(station.station), fill=(0, 0, 200))
    out.parent.mkdir(parents=True, exist_ok=True)
    image.save(out)


def station_record(station, layout, cal) -> dict:
    def point(row_column):
        row, column = row_column
        return {'row': row, 'column': column, 'height_m': cal.height_ft(row, column) * 0.3048,
                'half_breadth_m': station.offset_px(column, layout.centre_column) / layout.pixels_per_metre}
    return {'station': station.station, 'side': station.side, 'turn_deg': station.turn_deg,
            'chine': point(station.chine), 'rabbet': point(station.rabbet), 'sheer': point(station.sheer),
            'points': len(station.points), 'notes': station.notes}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--boat', choices=sorted(BOATS), required=True)
    parser.add_argument('--sheet', type=Path, required=True)
    parser.add_argument('--truth', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--overlay', type=Path, required=True)
    args = parser.parse_args()
    cal = importlib.import_module(BOATS[args.boat])
    sheet_sha = hashlib.sha256(args.sheet.read_bytes()).hexdigest()
    if sheet_sha != cal.SHEET_SHA256:
        raise SystemExit(f'sheet sha256 {sheet_sha} is not the protocol sheet; stop')
    polyline_sha = hashlib.sha256(Path(polyline.__file__).read_bytes()).hexdigest()
    layout = cal.sheet_layout()
    ink = crossings.load_ink(args.sheet)

    seconds = {}
    started = time.monotonic()
    frozen = cv.measure(ink, layout)
    identities = {name: reader.identities_by_rank(r.chains, r.layout.stations_outer_first)
                  for name, r in frozen.items()}
    seconds['frozen'] = round(time.monotonic() - started, 1)
    started = time.monotonic()
    sides = v2.read_sheet(ink, layout, frozen)
    seconds['v2'] = round(time.monotonic() - started, 1)
    started = time.monotonic()
    halves = polyline.read_sheet(ink, layout)
    sc.engage(halves, frozen, identities, layout, ink)
    seconds['polyline'] = round(time.monotonic() - started, 1)

    tables = {'frozen': cv.table_and_flags(frozen, identities, layout)[0],
              'v2': v2.sheet_table(sides, layout)[0],
              'polyline': sc.polyline_table(halves, frozen, identities, layout)}
    curves = {'frozen': sc.frozen_curves(frozen, identities, layout, cal),
              'v2': sc.v2_curves(sides, layout, cal),
              'polyline': sc.polyline_curves(halves, frozen, identities, layout, cal)}

    truth = sc.load_truth(args.truth, cal)  # read only now, after all three readers have run
    raw = json.loads(args.truth.read_text())
    results = {arm: {'waterline': sc.score_waterlines(tables[arm], truth, cal),
                     'point': sc.score_points(curves[arm], truth, cal)} for arm in ARMS}
    gates = {arm: {kind: sc.gates(results['frozen'][kind], results[arm][kind]) for kind in ('waterline', 'point')}
             for arm in ('v2', 'polyline')}
    report = {
        'holdout': f'{args.boat}; one run, no tuning', 'engineering_approved': False,
        'sheet_sha256': sheet_sha, 'truth_sha256': cal.TRUTH_SHA256, 'polyline_sha256': polyline_sha,
        'truth_unsure_entries': len(raw.get('unsure', [])),
        'truth_unmatched_waterlines': truth['unmatched_waterlines'],
        'truth_cells': {'waterline': sum(v is not None for v in truth['waterlines'].values()),
                        'point': sum(v['height'] is not None and v['half_breadth'] is not None
                                     for v in truth['points'].values())},
        'seconds': seconds, 'measurement': cv.measurement_summary(frozen), 'results': results, 'gates': gates,
        'frozen_identities': {n: {str(k): v for k, v in i.items()} for n, i in identities.items()},
        'v2': {'chine_verified': {n: s.uses_chine for n, s in sides.items()},
               'abstained': {n: len(s.abstained) for n, s in sides.items()},
               'chine_points': {n: [[p.station, p.row, p.column] for p in s.chine_points] for n, s in sides.items()},
               'notes': {n: s.notes for n, s in sides.items()}},
        'polyline': {name: {'read': h.read, 'line_width_px': h.line_width_px, 'notes': h.notes,
                            'stations': [station_record(s, layout, cal) for s in h.stations],
                            'engaged': [station_record(s, layout, cal) for s in h.engaged],
                            'unnamed': [station_record(s, layout, cal) for s in h.unnamed if all(s is not e for e in h.engaged)]}
                     for name, h in halves.items()},
        'tables': {arm: {f'{s}/{w}': v for (s, w), v in sorted(table.items())} for arm, table in tables.items()},
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, default=float) + '\n')
    overlay(ink, halves, sides, cal, args.overlay)

    keys = ('truth_cells', 'cells_given', 'rms_m', 'max_abs_m', 'wrong_cells', 'identity_errors',
            'missing_cell_keys', 'extra_cell_keys')
    for arm in ARMS:
        for kind in ('waterline', 'point'):
            result = results[arm][kind]
            print(arm, kind, json.dumps({k: result.get(k) for k in keys}, default=float))
        print(arm, 'chine', json.dumps(results[arm]['point'].get('chine_only'), default=float))
    for name, half in halves.items():
        print('polyline', name, 'read' if half.read else 'declined', [s.station for s in half.stations],
              'engaged', [s.station for s in half.engaged], half.notes)
    print('v2 chine verified', report['v2']['chine_verified'])
    print('unmatched waterlines', truth['unmatched_waterlines'])
    print('gates', json.dumps(gates))


if __name__ == '__main__':
    main()
