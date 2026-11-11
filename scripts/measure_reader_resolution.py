"""Measure the body-plan reader on development sheets at native and reduced resolution.

Code-review item 8. One arm per run: the frozen v1 reader (no scaling) or the product reader
(whatever this checkout holds). Each development sheet is read at the given scales; a reduced
sheet is made by area-averaging the ink mask and thresholding at half, which is what a scan at
lower dpi gives. The harness calibration is mapped to the reduced pixel grid. No model calls; rank
identity and the existing harness scorers. Truth stays outside the repository.

Output: one JSON summary (scores, resolution factor, low-resolution flag, SHA-256 of the full
reading) and, per case, the full reading as Python repr text, for byte comparison between arms.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict, replace
import hashlib
import importlib
import json
from pathlib import Path
import time

import numpy as np
from PIL import Image

from benchmarks.balclutha import crossing_value as cv
from benchmarks.balclutha import model_value as balclutha
from benchmarks.bue_girl import holdout_value as bue
from benchmarks.bumble_bee import holdout_value as bumble
from benchmarks.pardon_me import holdout_value as pardon
from benchmarks.thayer import holdout_value as thayer

READERS = {'frozen': 'benchmarks.frozen_readers.v1', 'product': 'vessel_reconstruction'}


def corrected_bumble_layout(reader):
    """docs/AUTO_CALIBRATION.md section 4 (as scripts/measure_body_plan_chine.py)."""
    layout = bumble.sheet_layout()
    sides = (reader.SideLayout('aft', -1, tuple(range(9, 15)), bumble.grid_columns(-1)),
             reader.SideLayout('fore', 1, tuple(range(8, 0, -1)), bumble.grid_columns(1)))
    return replace(layout, sides=sides)


def cases(sources: Path, truth_root: Path, legacy_truth_root: Path, reader) -> list:
    """(name, sheet, truth, layout, load_truth, scorer) for the five development sheets."""
    return [
        ('PARDON ME', sources / 'haer/master-pnp-habshaer-ny-ny2300-ny2390-sheet-00004a.tif',
         truth_root / 'pardon-me/truth_s4.json', pardon.sheet_layout(), pardon.load_truth, pardon.score),
        ('BUE GIRL', sources / 'haer/master-pnp-habshaer-or-or0500-or0590-sheet-00002a.tif',
         truth_root / 'bue-girl/truth_s2.json', bue.sheet_layout(), bue.load_truth, bue.score),
        ('C.A. Thayer', sources / 'haer/ca_thayer/loc_ca1506_sheet_04.tif',
         legacy_truth_root / 'thayer/truth_s4.json', thayer.sheet_layout(), thayer.load_truth, thayer.score),
        ('Balclutha', sources / 'balclutha_ca54_s7.tif',
         legacy_truth_root / 'balclutha/truth_s7.json', cv.sheet_layout(), balclutha.load_truth, cv.score),
        ('BUMBLE BEE (corrected sides)', sources / 'haer/master-pnp-habshaer-or-or0500-or0589-sheet-00002a.tif',
         truth_root / 'bumble-bee/truth_s2.json', corrected_bumble_layout(reader), bumble.load_truth, bumble.score),
    ]


def reduce_ink(ink: np.ndarray, scale: float) -> np.ndarray:
    """The ink mask of the same sheet scanned at `scale` times the pixel density."""
    if scale == 1.0:
        return ink
    paper = Image.fromarray(np.where(ink, 0, 255).astype(np.uint8))
    size = (round(ink.shape[1] * scale), round(ink.shape[0] * scale))
    return np.asarray(paper.resize(size, Image.Resampling.BOX)) < 128


def reduce_layout(layout, scale: float, reader):
    """The calibration mapped to the reduced grid (pixel centres: x' = (x + 0.5) * scale - 0.5)."""
    if scale == 1.0:
        return layout

    def point(value: float) -> float:
        return (value + 0.5) * scale - 0.5

    sides = tuple(replace(side, grid_columns=tuple(point(c) for c in side.grid_columns)) for side in layout.sides)
    return reader.SheetLayout(point(layout.centre_column), layout.pixels_per_metre * scale,
                              {label: int(round(point(row))) for label, row in layout.waterline_rows.items()},
                              int(round(layout.max_offset_px * scale)), sides)


def score_readings(readings: dict, layout, truth: dict, scorer, reader) -> dict:
    identities = {name: reader.identities_by_rank(r.chains, r.layout.stations_outer_first)
                  for name, r in readings.items()}
    table = {}
    for name, reading in readings.items():
        table.update(reader.table_from_identities(reading, identities[name], layout.pixels_per_metre,
                                                  layout.centre_column))
    result = scorer(table, truth)
    common = [key for key in truth if key in table]
    result['cells_within_0_05'] = int(sum(abs(table[key] - truth[key]) <= 0.05 for key in common))
    result['chains'] = {name: len(r.chains) for name, r in readings.items()}
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reader', choices=sorted(READERS), required=True)
    parser.add_argument('--label', required=True, help='Arm name in the output, e.g. frozen, base, scaled')
    parser.add_argument('--sources', required=True, type=Path)
    parser.add_argument('--truth-root', required=True, type=Path)
    parser.add_argument('--legacy-truth-root', required=True, type=Path)
    parser.add_argument('--scales', default='1.0,0.5,0.35')
    parser.add_argument('--only', default='', help='Comma-separated sheet names (default: all five)')
    parser.add_argument('--out', required=True, type=Path, help='Folder for summary JSON and readings')
    args = parser.parse_args()
    package = READERS[args.reader]
    reader = importlib.import_module(f'{package}.body_plan_reader')
    crossings = importlib.import_module(f'{package}.body_plan_crossings')
    from vessel_reconstruction import body_plan_crossings as product_crossings
    from vessel_reconstruction import body_plan_reader as product_reader
    from vessel_reconstruction import sheet_calibration

    def calibration_factor(ink: np.ndarray, layout) -> float:
        """The factor `sheet_calibration.calibrate` sets, on a body-plan box built from the layout."""
        rows = sorted(layout.waterline_rows.values())
        spacing = float(np.median(np.diff(rows)))
        box = [max(0, int(layout.centre_column - layout.max_offset_px)), max(0, int(rows[0] - spacing)),
               min(ink.shape[1], int(layout.centre_column + layout.max_offset_px)),
               min(ink.shape[0], int(rows[-1] + spacing))]
        stroke = sheet_calibration.stroke_width(ink, box, sheet_calibration.straight_lines(ink, box, 'h'))
        return product_crossings.resolution_factor(stroke)

    scales = [float(value) for value in args.scales.split(',')]
    wanted = {name.strip() for name in args.only.split(',') if name.strip()}
    args.out.mkdir(parents=True, exist_ok=True)
    summary = {'reader': package, 'label': args.label, 'engineering_approved': False, 'cases': []}
    for name, sheet, truth_path, layout, load_truth, scorer in cases(args.sources, args.truth_root,
                                                                      args.legacy_truth_root, reader):
        if wanted and name not in wanted:
            continue
        missing = [str(path) for path in (sheet, truth_path) if not path.is_file()]
        if missing:
            summary['cases'].append({'sheet': name, 'unavailable_inputs': missing})
            continue
        truth = load_truth(truth_path)
        native = crossings.load_ink(sheet)
        for scale in scales:
            started = time.monotonic()
            ink = reduce_ink(native, scale)
            scaled_layout = reduce_layout(layout, scale, reader)
            readings = {side.name: reader.measure_side(ink, scaled_layout, side) for side in scaled_layout.sides}
            text = repr({side: asdict(reading) for side, reading in readings.items()})
            stem = f"{name.split(' (')[0].replace(' ', '_').replace('.', '')}_{scale:g}_{args.label}"
            (args.out / f'{stem}.reading.txt').write_text(text)
            factor = calibration_factor(ink, scaled_layout)
            side_strokes = {side: product_reader.side_stroke_width(reading) for side, reading in readings.items()}
            result = score_readings(readings, scaled_layout, truth, scorer, reader)
            case = {'sheet': name, 'scale': scale, 'shape': list(ink.shape), 'resolution_factor': factor,
                    'low_resolution_flag': sheet_calibration.low_resolution(factor),
                    'reader_stroke_px': side_strokes,
                    'reader_threshold_scale': {side: product_crossings.threshold_scale(stroke)
                                               for side, stroke in side_strokes.items()},
                    'reading_sha256': hashlib.sha256(text.encode()).hexdigest(), 'score': result,
                    'seconds': round(time.monotonic() - started, 1)}
            summary['cases'].append(case)
            print(f"{args.label} {name} x{scale:g}: factor {factor:.2f}, cells {result['cells_given']}/"
                  f"{result['truth_cells']}, within 5 cm {result['cells_within_0_05']}, "
                  f"RMS {result.get('rms_m', float('nan')):.4f}, sha {case['reading_sha256'][:12]}", flush=True)
            del ink, readings, text
        del native
    (args.out / f'summary_{args.label}.json').write_text(json.dumps(summary, indent=2) + '\n')


if __name__ == '__main__':
    main()
