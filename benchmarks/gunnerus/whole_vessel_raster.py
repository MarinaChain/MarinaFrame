"""Gunnerus whole-vessel round 3: the raster path (no vector layers), code only and with the model.

Protocol (fixed before running): docs/plans/2026-11-09-whole-vessel-scope.md, section 3.5.2.

- The GA PDF is rendered to one raster page. The readers see only that image.
- Host calibration (stands in for a person): each view crop is registered once to the GA
  vector file (scale and offset). Only the calibration numbers leave this step.
- R0: ``RasterReader`` gives the same evidence as the vector reader, from ink pixels.
- R1: DeepSeek reads the crops (JSON form, thinking disabled) with the R0 reading as text.

Usage (outputs are drawing derivatives: keep them out of the repository)::

    PYTHONPATH=src python -m benchmarks.gunnerus.whole_vessel_raster --sources work/sources/gunnerus \\
        --out work/whole-vessel/raster-001 --truth-mesh <truth dir>/truth_mesh.npz [--model]
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from benchmarks.gunnerus.whole_vessel import GA_FILE, VIEWS, build_inputs
from vessel_reconstruction import ga_reader
from vessel_reconstruction.ship_measure import read_dxf, source_hash

PDF_FILE = 'polarkonsult/GA Gunnerus Rev1.pdf'
DPI = 150
INK_THRESHOLD = 160  # grey level; darker pixels are ink
# The PDF plot scale is not printed for the page (the title block says 1:100, the page is scaled
# to fit); the registration searches this range of pixels per drawing millimetre.
SCALE_SEARCH = (0.075, 0.087, 49)
RASTER_VIEWS = ('profile', 'plan_1deck', 'plan_adeck')
# The raster has no layers: the heavy-layer wall view uses all ink of the A-deck plan.
VIEW_ALIASES = {'plan_adeck_walls': 'plan_adeck'}


def render_page(sources: Path) -> np.ndarray:
    import fitz

    page = fitz.open(sources / PDF_FILE)[0]
    pixmap = page.get_pixmap(dpi=DPI, colorspace=fitz.csGRAY)
    return np.frombuffer(pixmap.samples, np.uint8).reshape(pixmap.height, pixmap.width).copy()


def register(gray: np.ndarray, sources: Path) -> dict:
    """Host calibration per view: page pixel = (dxf_x * s + ox, oy - dxf_y * s)."""
    import cv2

    ink = cv2.dilate((gray < INK_THRESHOLD).astype(np.uint8) * 255, np.ones((3, 3), np.uint8))
    entities = read_dxf(sources / GA_FILE)
    result = {}
    for name in RASTER_VIEWS:
        x0, y0, x1, y1 = VIEWS[name].bounds
        best = None
        for s in np.linspace(*SCALE_SEARCH):
            template = np.zeros((int((y1 - y0) * s) + 1, int((x1 - x0) * s) + 1), np.uint8)
            for entity in entities:
                p = np.asarray(entity['points'])
                if p[:, 0].min() < x0 or p[:, 0].max() > x1 or p[:, 1].min() < y0 or p[:, 1].max() > y1:
                    continue
                q = np.round(np.c_[(p[:, 0] - x0) * s, (y1 - p[:, 1]) * s]).astype(np.int32)
                cv2.polylines(template, [q], False, 255, 3)
            score = cv2.matchTemplate(ink, template, cv2.TM_CCOEFF_NORMED)
            _, value, _, location = cv2.minMaxLoc(score)
            if best is None or value > best['score']:
                best = {'score': float(value), 's': float(s), 'ox': float(location[0] - x0 * s),
                        'oy': float(location[1] + y1 * s)}
        result[name] = best
    return result


class RasterReader:
    """The vector reader's evidence, from ink pixels of the rendered PDF page."""

    def __init__(self, sources: Path, gray: np.ndarray, calibration: dict):
        self.source_file, self.sha = PDF_FILE, source_hash(sources / PDF_FILE)
        self.labels = {}  # The PDF text is outlines: no printed-label snapping.
        self.crops, self.plans = {}, {}
        ink = (gray < INK_THRESHOLD).astype(np.uint8) * 255
        for name in RASTER_VIEWS:
            crop = self.crop(name, calibration[name], ink.shape)
            self.crops[name] = crop
            part = ink[crop['row0']:crop['row1'], crop['col0']:crop['col1']]
            crop['ink'] = part
            if VIEWS[name].kind == 'plan':
                self.plans[name] = ga_reader.PlanRaster.from_ink(
                    part, crop['x_of_column'](0), crop['v_of_row'](0), crop['pixel_m'], f'{name}: raster ink')
        profile = self.crops['profile']
        self.levels = ga_reader.raster_levels(profile['ink'], profile['x_of_column'], profile['v_of_row'],
                                              profile['pixel_m'])

    @staticmethod
    def crop(name, cal, shape) -> dict:
        view = VIEWS[name]
        s, ox, oy = cal['s'], cal['ox'], cal['oy']
        x0, y0, x1, y1 = view.bounds
        col0, col1 = max(0, int(x0 * s + ox)), min(shape[1], int(x1 * s + ox) + 1)
        row0, row1 = max(0, int(oy - y1 * s)), min(shape[0], int(oy - y0 * s) + 1)
        pixel_m = 0.001 / s
        origin_x, origin_v = view.origin
        return {'col0': col0, 'col1': col1, 'row0': row0, 'row1': row1, 'pixel_m': pixel_m,
                'x_of_column': lambda c: ((col0 + c - ox) / s - origin_x) * 0.001,
                'v_of_row': lambda r: ((oy - (row0 + r)) / s - origin_v) * 0.001,
                'formula': {'x_m': f'{((col0 - ox) / s - origin_x) * 0.001:.4f} + {pixel_m:.6f} * px',
                            ('z_m' if view.kind == 'profile' else 'y_m'):
                                f'{((oy - row0) / s - origin_v) * 0.001:.4f} - {pixel_m:.6f} * py'}}

    def footprint(self, view, x_range, mode, peel):
        return self.plans[VIEW_ALIASES.get(view, view)].footprint(x_range, mode, peel)

    def evidence(self, view) -> str:
        return f'{VIEW_ALIASES.get(view, view)}: raster ink'

    def end_walls(self, deck_view, x_range, min_length_m):
        crop = self.crops[VIEW_ALIASES.get(deck_view, deck_view)]
        return ga_reader.raster_transverse_walls(crop['ink'], crop['x_of_column'], x_range, min_length_m,
                                                 crop['pixel_m'])


def write_crops(gray: np.ndarray, reader: RasterReader, out: Path) -> dict:
    """PNG crops for the model (downscaled to at most 2000 px wide), with their calibration."""
    from PIL import Image

    images = []
    for name in RASTER_VIEWS:
        crop = reader.crops[name]
        part = Image.fromarray(gray[crop['row0']:crop['row1'], crop['col0']:crop['col1']])
        factor = min(1.0, 2000 / part.width)
        if factor < 1.0:
            part = part.resize((round(part.width * factor), round(part.height * factor)), Image.LANCZOS)
        path = out / f'raster_{name}.png'
        part.save(path)
        pixel_m = crop['pixel_m'] / factor
        formula = {key: value.replace(f'{crop["pixel_m"]:.6f}', f'{pixel_m:.6f}')
                   for key, value in crop['formula'].items()}
        images.append({'view': name, 'file': path.name, 'path': str(path), 'width': part.width,
                       'height': part.height, 'calibration': formula, 'sha256': source_hash(path)})
    return {'images': images}


RASTER_NOTE = """The images are crops of a scanned-style raster of the GA (no vector data). The code
reading below came from ink pixels and is less reliable than on a vector drawing. Check each tier's
levels and BOTH ends against the walls on the deck below (a roof can overhang an open deck), correct
the code reading where the images show otherwise, and fill every gap.
"""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sources', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--truth-mesh', type=Path, required=True)
    parser.add_argument('--calibration', type=Path, help='Reuse a host calibration JSON from an earlier run.')
    parser.add_argument('--model', action='store_true', help='Also run R1 (3 live repeats, key in environment).')
    args = parser.parse_args()
    from benchmarks.gunnerus import whole_vessel_ab as ab
    from benchmarks.gunnerus.whole_vessel_metrics import score_run
    from vessel_reconstruction.ship_cad_worker import run as run_worker

    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=False)
    gray = render_page(args.sources)
    calibration = (json.loads(args.calibration.read_text()) if args.calibration
                   else register(gray, args.sources))
    (out / 'calibration.json').write_text(json.dumps(calibration, indent=2) + '\n')
    reader = RasterReader(args.sources, gray, calibration)
    inputs = build_inputs(args.sources, reader)
    (out / 'inputs.json').write_text(json.dumps(inputs, indent=2) + '\n')
    r0 = out / 'R0'
    r0.mkdir()
    execution = run_worker(inputs['program'], inputs['measurements'], r0 / 'task', guesses=inputs['guesses'])
    (r0 / 'execution.json').write_text(json.dumps(execution, indent=2, default=str) + '\n')
    score = score_run(r0, args.truth_mesh)
    (r0 / 'whole_vessel_score.json').write_text(json.dumps(score, indent=2) + '\n')
    print('R0', json.dumps(score['metrics']), score['M7_built'], score['M7_argument_labels'], flush=True)
    if not args.model:
        return
    pack = write_crops(gray, reader, out)
    original = ab.COMMON
    ab.COMMON = original.replace('Images (rendered from the GA vector file;',
                                 'Images (crops of a raster page of the GA;') + RASTER_NOTE
    results = []
    for repeat in range(1, 4):
        folder = out / f'R1-{repeat}'
        record = ab.run_repeat('A', pack, inputs, folder, ab.ROUNDS['2'])
        (folder / 'record.json').write_text(json.dumps(record, indent=2, default=str) + '\n')
        summary = ab.summarise(folder, record, args.truth_mesh)
        (folder / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
        results.append(summary)
        print(json.dumps(summary), flush=True)
    ab.COMMON = original
    (out / 'r1_summary.json').write_text(json.dumps(results, indent=2) + '\n')


if __name__ == '__main__':
    main()
