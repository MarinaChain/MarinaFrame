"""E. C. COLLIER hard-chine holdout: one run of the frozen reader and reader v2 (no model calls).

Same calibration (benchmarks/ec_collier/holdout_value.py) and scorer (point_score.py) for both
arms. Both readers run before the truth file is read; truth is used for scoring only. Writes the
result JSON and an overlay of the v2 chine line and chine points for the by-eye gate.
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
from benchmarks.hard_chine import chine_line as chine_line
from benchmarks.frozen_readers.v1 import body_plan_crossings as crossings
from benchmarks.frozen_readers.v1 import body_plan_reader as reader
from benchmarks.hard_chine import reader_v2 as v2

# Body-plan region drawn in the overlay (full-sheet rows and columns).
TOP, BOTTOM, LEFT, RIGHT = 6250, 7800, 1650, 4750


def overlay(ink, readings, sides, out: Path) -> None:
    image = Image.fromarray(np.where(ink[TOP:BOTTOM, LEFT:RIGHT], 0, 255).astype(np.uint8)).convert('RGB')
    draw = ImageDraw.Draw(image)
    for name, side in sides.items():
        for waterline, found in readings[name].stations.items():
            for crossing in found:
                x, y = crossing.x_px - LEFT, crossing.row - TOP
                draw.ellipse([x - 4, y - 4, x + 4, y + 4], outline=(0, 120, 255), width=2)
        if side.line is not None:
            points = [(c - LEFT, r - TOP) for r, c in side.line.points]
            draw.line(points, fill=(255, 0, 0) if side.uses_chine else (255, 160, 0), width=3)
        for point in side.chine_points:
            x, y = point.column - LEFT, point.row - TOP
            draw.ellipse([x - 9, y - 9, x + 9, y + 9], outline=(0, 170, 0), width=3)
            draw.text((x + 10, y - 22), str(point.station), fill=(0, 140, 0))
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
        raise SystemExit(f'sheet sha256 {sheet_sha} is not the protocol sheet; stop')
    layout = cal.sheet_layout()
    started = time.monotonic()
    ink = crossings.load_ink(args.sheet)
    frozen = cv.measure(ink, layout)
    identities = {name: reader.identities_by_rank(r.chains, r.layout.stations_outer_first)
                  for name, r in frozen.items()}
    sides = v2.read_sheet(ink, layout, frozen)
    # Diagnosis only: the line the finder traced before v2's waterline check (v2 drops a rejected one).
    traced = {}
    for name, reading in frozen.items():
        line = chine_line.find_chine_line(ink, layout, reading)
        traced[name] = None if line is None else {
            'lies_on_waterline': v2.lies_on_waterline(line, layout), 'thickness_px': line.thickness_px,
            'touching_chains': line.touching_chains,
            'columns': [float(line.points[0, 1]), float(line.points[-1, 1])],
            'rows': [float(line.points[:, 0].min()), float(line.points[:, 0].max())]}
    seconds = round(time.monotonic() - started, 1)
    frozen_samples = ps.samples_frozen(frozen, identities, layout)
    v2_samples = ps.samples_v2(sides, layout)

    truth = ps.load_truth(args.truth)  # read only now, after both readers have run
    unsure = json.loads(args.truth.read_text()).get('unsure', [])
    frozen_score, v2_score = ps.score(frozen_samples, truth), ps.score(v2_samples, truth)
    report = {
        'holdout': 'E. C. COLLIER, HAER MD-77 sheet 2; one run, no tuning', 'engineering_approved': False,
        'sheet': str(args.sheet), 'sheet_sha256': sheet_sha, 'truth_sha256': ps.TRUTH_SHA256,
        'truth_unsure_entries': len(unsure), 'seconds': seconds,
        'calibration': {'centre_column': cal.CENTRE_COLUMN, 'base_row': cal.BASE_ROW,
                        'base_row_per_column': cal.BASE_ROW_PER_COLUMN, 'pixels_per_ft': cal.PIXELS_PER_FT,
                        'max_offset_px': cal.MAX_OFFSET_PX, 'measuring_rows': cal.MEASURING_ROWS,
                        'aft': cal.AFT_STATIONS_OUTER_FIRST, 'fore': cal.FORE_STATIONS_OUTER_FIRST},
        'measurement': cv.measurement_summary(frozen),
        'frozen': dict(frozen_score, identities={n: {str(k): v for k, v in i.items()} for n, i in identities.items()}),
        'v2': dict(v2_score,
                   chine_verified={n: s.uses_chine for n, s in sides.items()},
                   abstained={n: len(s.abstained) for n, s in sides.items()},
                   abstained_detail={n: s.abstained for n, s in sides.items()},
                   chine_points={n: [[p.station, p.row, p.column] for p in s.chine_points] for n, s in sides.items()},
                   notes={n: s.notes for n, s in sides.items()}),
        'traced_line_before_waterline_check': traced,
        'samples': {'frozen': {str(s): c for s, c in frozen_samples.items()},
                    'v2': {str(s): c for s, c in v2_samples.items()}},
        'gates': ps.gates(frozen_score, v2_score),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, default=float) + '\n')
    overlay(ink, frozen, sides, args.overlay)
    for arm, result in (('frozen', frozen_score), ('v2', v2_score)):
        print(arm, json.dumps({k: result.get(k) for k in ('cells_given', 'truth_cells', 'rms_m', 'max_abs_m',
                                                           'wrong_cells', 'chine_only', 'by_point',
                                                           'identity_errors', 'missing_cell_keys',
                                                           'extra_cell_keys')}))
    print('v2 chine verified', report['v2']['chine_verified'], 'abstained', report['v2']['abstained'])
    print('traced', json.dumps(traced, default=float))
    print('gates', json.dumps(report['gates']))


if __name__ == '__main__':
    main()
