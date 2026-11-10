"""E. C. COLLIER (development case): the frozen reader against the V-bottom polyline reader.

Same calibration (benchmarks/ec_collier/holdout_value.py) and point scorer (point_score.py) as the
spent holdout run. Both readers run before the truth file is read; truth is used for scoring only.
The polyline reader's value at a printed height is its traced station polyline evaluated at that
height: the polyline's own points are passed to the scorer as consecutive samples, so the scorer
interpolates along the traced ink instead of between measuring rows.

Writes a JSON result and an overlay of the traced stations (both git-ignored under work/).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from benchmarks.balclutha import crossing_value as cv
from benchmarks.ec_collier import holdout_value as cal
from benchmarks.ec_collier import point_score as ps
from vessel_reconstruction import body_plan_crossings as crossings
from vessel_reconstruction import body_plan_polyline as polyline
from vessel_reconstruction import body_plan_reader as reader

# Body-plan region drawn in the overlay (full-sheet rows and columns).
TOP, BOTTOM, LEFT, RIGHT = 6250, 7800, 1650, 4750


def polyline_samples(halves: dict, layout) -> tuple[dict, tuple]:
    """{station: {label: (height m, half-breadth m)}} along each traced polyline, and the labels.

    Labels number the polyline points from the rabbet up; the scorer interpolates between
    consecutive labels, which is the polyline itself.
    """
    found, longest = {}, 0
    for half in halves.values():
        if not half.read:
            continue
        for station in half.stations:
            cells = {}
            for k, (row, column) in enumerate(station.points):
                half_breadth = station.offset_px(column, layout.centre_column) / layout.pixels_per_metre
                cells[f'p{k:05d}'] = ps.sample(row, column, half_breadth)
            found[station.station] = cells
            longest = max(longest, len(station.points))
    return found, tuple(f'p{k:05d}' for k in range(longest))


def station_record(station, layout) -> dict:
    def point(row_column):
        row, column = row_column
        return {'row': row, 'column': column,
                'height_m': cal.height_ft(row, column) * 0.3048,
                'half_breadth_m': station.offset_px(column, layout.centre_column) / layout.pixels_per_metre}
    return {'station': station.station, 'side': station.side, 'turn_deg': station.turn_deg,
            'rabbet': point(station.rabbet), 'chine': point(station.chine), 'sheer': point(station.sheer),
            'points': len(station.points), 'notes': station.notes}


def overlay(ink, halves, out: Path) -> None:
    image = Image.fromarray(np.where(ink[TOP:BOTTOM, LEFT:RIGHT], 0, 255).astype(np.uint8)).convert('RGB')
    draw = ImageDraw.Draw(image)
    for half in halves.values():
        for station in half.stations + half.unnamed:
            colour = (220, 0, 0) if station.station is not None else (255, 150, 0)
            draw.line([(c - LEFT, r - TOP) for r, c in station.points], fill=colour, width=3)
            for (row, column), mark in ((station.chine, (0, 160, 0)), (station.rabbet, (0, 0, 255)),
                                        (station.sheer, (160, 0, 160))):
                x, y = column - LEFT, row - TOP
                draw.ellipse([x - 8, y - 8, x + 8, y + 8], outline=mark, width=3)
            x, y = station.chine[1] - LEFT, station.chine[0] - TOP
            draw.text((x + 10, y + 10), str(station.station), fill=(0, 0, 200))
    out.parent.mkdir(parents=True, exist_ok=True)
    image.save(out)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sheet', type=Path, required=True)
    parser.add_argument('--truth', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--overlay', type=Path, required=True)
    args = parser.parse_args()
    sheet_sha = hashlib.sha256(args.sheet.read_bytes()).hexdigest()
    if sheet_sha != cal.SHEET_SHA256:
        raise SystemExit(f'sheet sha256 {sheet_sha} is not the COLLIER sheet; stop')
    layout = cal.sheet_layout()
    ink = crossings.load_ink(args.sheet)
    started = time.monotonic()
    frozen = cv.measure(ink, layout)
    identities = {name: reader.identities_by_rank(r.chains, r.layout.stations_outer_first)
                  for name, r in frozen.items()}
    frozen_seconds = round(time.monotonic() - started, 1)
    started = time.monotonic()
    halves = polyline.read_sheet(ink, layout)
    polyline_seconds = round(time.monotonic() - started, 1)
    frozen_samples = ps.samples_frozen(frozen, identities, layout)
    traced_samples, labels = polyline_samples(halves, layout)

    truth = ps.load_truth(args.truth)  # read only now, after both readers have run
    frozen_score = ps.score(frozen_samples, truth)
    traced_score = ps.score(traced_samples, truth, labels)
    report = {
        'case': 'E. C. COLLIER, HAER MD-77 sheet 2; DEVELOPMENT case (holdout spent)',
        'engineering_approved': False, 'sheet_sha256': sheet_sha, 'truth_sha256': ps.TRUTH_SHA256,
        'seconds': {'frozen': frozen_seconds, 'polyline': polyline_seconds},
        'frozen': frozen_score,
        'polyline': dict(traced_score,
                         halves={name: {'read': h.read, 'line_width_px': h.line_width_px, 'notes': h.notes,
                                        'stations': [station_record(s, layout) for s in h.stations],
                                        'unnamed': [station_record(s, layout) for s in h.unnamed]}
                                 for name, h in halves.items()}),
        'gates_polyline_vs_frozen': ps.gates(frozen_score, traced_score),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, default=float) + '\n')
    overlay(ink, halves, args.overlay)
    for arm, result in (('frozen', frozen_score), ('polyline', traced_score)):
        print(arm, json.dumps({k: result.get(k) for k in ('cells_given', 'truth_cells', 'rms_m', 'max_abs_m',
                                                           'wrong_cells', 'chine_only', 'by_point',
                                                           'identity_errors', 'missing_cell_keys',
                                                           'extra_cell_keys')}))
        print(arm, 'errors', json.dumps({k: round(v, 4) for k, v in result['errors_m'].items()}))
    for name, half in halves.items():
        print(name, 'read' if half.read else 'declined', half.notes)
    print('gates', json.dumps(report['gates_polyline_vs_frozen']))


if __name__ == '__main__':
    main()
