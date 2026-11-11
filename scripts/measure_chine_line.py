"""Measure the drawn chine line of PARDON ME against the printed CHINE row (comparison only).

Truth is read after measuring and only for the error table. Usage:
  PYTHONPATH=src:. .venv/bin/python scripts/measure_chine_line.py --sheet SHEET.tif --truth table_as_printed.json
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from benchmarks.balclutha import crossing_value as round8
from benchmarks.pardon_me import holdout_value as hv
from benchmarks.hard_chine import chine_line as chine
from vessel_reconstruction import body_plan_crossings as bpc

PIXELS_PER_FT = hv.PIXELS_PER_FT


def measure(sheet: Path) -> dict:
    ink = bpc.load_ink(sheet)
    layout = hv.sheet_layout()
    readings = round8.measure(ink, layout)
    spacing = hv.bpr.waterline_spacing(layout)
    result = {}
    for name, reading in readings.items():
        line = chine.find_chine_line(ink, layout, reading)
        if line is None:
            result[name] = {'line': None, 'stations': {}}
            continue
        points = chine.station_chine_points(line, reading, spacing)
        stations = {}
        for station, point in zip(reading.layout.stations_outer_first, points):
            stations[station] = {
                'half_breadth_ft': reading.layout.sign * (point.column - layout.centre_column) / PIXELS_PER_FT,
                'height_ft': (hv.BASE_ROW - point.row) / PIXELS_PER_FT,
                'chain': point.chain, 'extrapolated': bool(point.extrapolated)}
        result[name] = {'line': {'columns': [float(line.points[0, 1]), float(line.points[-1, 1])],
                                 'score': int(line.touching_chains)}, 'stations': stations}
    return result


def compare(measured: dict, truth_path: Path) -> list[dict]:
    data = json.loads(truth_path.read_text())
    blocks = {b['name']: b for b in data['blocks'] if b}
    half = blocks['Halfbreadths From Centerline']['rows']['CHINE']
    height = blocks['Heights Above Baseline']['rows']['CHINE']
    rows = []
    for side in measured.values():
        for station, m in side['stations'].items():
            printed_y = hv.printed_half_breadth(half[station - 1]) / 0.3048
            printed_z = hv.waterline_height_ft(height[station - 1])
            rows.append({'station': station, 'y_ft': m['half_breadth_ft'], 'z_ft': m['height_ft'],
                         'printed_y_ft': printed_y, 'printed_z_ft': printed_z,
                         'error_y_ft': m['half_breadth_ft'] - printed_y,
                         'error_z_ft': m['height_ft'] - printed_z})
    return sorted(rows, key=lambda r: r['station'])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sheet', type=Path, required=True)
    parser.add_argument('--truth', type=Path, required=True)
    parser.add_argument('--out', type=Path, default=Path('work/chine/chine_line_measurement.json'))
    args = parser.parse_args()
    measured = measure(args.sheet)
    rows = compare(measured, args.truth)
    rms = {k: float(np.sqrt(np.mean([r[f'error_{k}_ft'] ** 2 for r in rows]))) if rows else None for k in 'yz'}
    out = {'measured': measured, 'comparison': rows, 'rms_ft': rms, 'stations_found': [r['station'] for r in rows]}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(out, indent=2) + '\n')
    print(json.dumps({'rms_ft': rms, 'stations': out['stations_found']}))
    for r in rows:
        print('%2d  y %.3f/%.3f (%+.3f)  z %.3f/%.3f (%+.3f)' % (
            r['station'], r['y_ft'], r['printed_y_ft'], r['error_y_ft'], r['z_ft'], r['printed_z_ft'], r['error_z_ft']))


if __name__ == '__main__':
    main()
