"""Compare model locations and calibrated tracer readings on development drawings."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import json
from pathlib import Path

import numpy as np
from PIL import Image

from benchmarks.factory import generate as G, hulls as H, render as R
from benchmarks.llm_setup_review.sample import SETUP_SAMPLE_HULLS
from benchmarks.localisation.calibrate import request
from vessel_reconstruction.ingest import extract_sections
from vessel_reconstruction.llm_setup import digest, write_json


def crossing(curves, height):
    values = []
    for curve in curves:
        for a, b in zip(curve[:-1], curve[1:]):
            if min(a[1], b[1]) <= height <= max(a[1], b[1]) and a[1] != b[1]:
                values.append(float(a[0] + (b[0] - a[0]) * (height - a[1]) / (b[1] - a[1])))
    return max(values) if values else None


def project(sheet, params, sid, breadth, height):
    matrix = np.asarray(params['geometry']['matrix'])
    if params['layout'] == 'separate':
        return list(R._apply(matrix, sheet.centreline_px[sid] + breadth * sheet.ppm,
                             sheet.baseline_px[sid] - height * sheet.ppm))
    # The factory concatenates right and mirrored-left raster panels. Reproduce
    # those raster operations, not the approximate calibration in the spec.
    aft = int(sid[1:]) < 5
    sign = -1 if aft else 1
    x, y = R._apply(matrix, sheet.overlay_centreline_px + sign * breadth * sheet.ppm,
                    sheet.baseline_px['overlay'] - height * sheet.ppm)
    cl_x, _ = R._apply(matrix, sheet.overlay_centreline_px,
                      sum(sheet.rois['overlay'][1::2]) / 2)
    cl = round(cl_x)
    start = max(0, cl - R.COMPOSITE_MARGIN_PX)
    right_end = min(sheet.image.width, sheet.rois['overlay'][2] + 40)
    if aft:
        stop = min(sheet.image.width, cl + R.COMPOSITE_MARGIN_PX + 1)
        x = right_end - start + R.COMPOSITE_GAP_PX + stop - 1 - x
    else:
        x -= start
    return [float(x), float(y)]


def fit_image(image, box):
    crop = image.crop(box)
    scale = min(1., 1024 / max(crop.size), (800_000 / (crop.width * crop.height)) ** .5)
    return crop.resize((max(1, round(crop.width * scale)), max(1, round(crop.height * scale))), Image.Resampling.LANCZOS)


def evaluate_case(case, root, out, binary):
    directory = root / 'inputs' / case
    params = json.loads((root / 'params' / f'{case}.json').read_text())
    if params['split'] != 'development':
        raise ValueError('Development cases only')
    spec = json.loads((directory / 'spec.json').read_text())
    image = Image.open(directory / 'drawing.png').convert('RGB')
    sections = [s for s in spec['sections'] if s['id'] in ['s03', 's07']]
    subset = deepcopy(spec)
    subset['sections'] = sections
    deterministic = extract_sections(subset, directory)
    write_json(out / f'{case}-tracer.json', deterministic)
    measured = {s['id']: s for s in deterministic['sections']}
    depth = sections[0]['z_max_m']
    step = R._nice_step(depth, 8)
    heights = [step * max(1, round(depth * fraction / step)) for fraction in [.3, .6]]
    rows = []
    for mode in ['sheet', 'crop']:
        for section in sections:
            sid = section['id']
            roi = section['roi_px']
            box = [0, 0, image.width, image.height] if mode == 'sheet' else [
                max(0, roi[0] - 55), max(0, roi[1] - 40), min(image.width, roi[2] + 30), min(image.height, roi[3] + 45)]
            attached = fit_image(image, box)
            scale_x = attached.width / (box[2] - box[0])
            scale_y = attached.height / (box[3] - box[1])
            calibration = section['calibration']
            centre = (calibration['centerline_px'] - box[0]) * scale_x
            baseline = (calibration['baseline_px'] - box[1]) * scale_y
            ppm = calibration['pixels_per_metre']
            questions = []
            for index, z in enumerate(heights):
                questions += [
                    {'id': f'P{index}', 'question': f'Locate the hull curve of printed station {int(sid[1:])} where it crosses the printed waterline WL{z:g}. Return normalized x,y.'},
                    {'id': f'B{index}', 'question': f'Read half-breadth in metres of station {int(sid[1:])} at height {z:g} m. Supplied calibration: centreline column {centre:.4f} attachment pixels, baseline row {baseline:.4f}, horizontal scale {ppm*scale_x:.6f} px/m, vertical scale {ppm*scale_y:.6f} px/m. Return value, x=y=null.'}]
            # The original combined run also asked for scale here. That value
            # is contaminated by B's supplied calibration and must not be scored
            # as independent. Use scale.py for independent grid-scale requests.
            context = {'coordinate_frame': 'normalized x=1000*column/image_width, y=1000*row/image_height; top-left origin, x right, y down.',
                       'image_size_px': list(attached.size), 'questions': questions,
                       'station': int(sid[1:]), 'note': 'Use the printed station labels, not the grid or another station.'}
            attempt = out / f'{case}-{mode}-{sid}'
            reply = request(attached, attempt, context, binary, digest(directory / 'drawing.png'), box)
            # Hidden geometric truth is first opened after this model request.
            hull = H.load_cached(root / 'hulls', params['hull_id'])
            stations = G.station_curves(hull)
            sheet = (R.draw_separate(stations, hull.depth_m, hull.max_half_breadth_m, params['render'])
                     if params['layout'] == 'separate' else R.draw_overlay(stations, hull.depth_m, hull.max_half_breadth_m,
                         params['render'], sum(s.x_m < .5 * hull.length_m - 1e-6 for s in stations)))
            station = next(s for s in stations if s.station_id == sid)
            answers = {a['id']: a for a in (reply or {}).get('answers', [])}
            for index, z in enumerate(heights):
                target = crossing(station.curves, z)
                truth_px = project(sheet, params, sid, target, z) if target is not None else None
                point = answers.get(f'P{index}', {})
                observed = None
                if point.get('x') is not None and point.get('y') is not None:
                    observed = [box[0] + point['x'] / 1000 * (box[2]-box[0]),
                                box[1] + point['y'] / 1000 * (box[3]-box[1])]
                breadth = answers.get(f'B{index}', {}).get('value')
                trace = measured.get(sid, {}).get('points_yz_m')
                tracer = crossing([np.asarray(trace)], z) if trace else None
                row = {'case_id': case, 'level': params['level'], 'layout': params['layout'], 'mode': mode,
                       'station': sid, 'height_m': z, 'truth_half_breadth_m': target,
                       'truth_position_px': truth_px, 'model_position_px': observed,
                       'position_error_px': float(np.linalg.norm(np.array(observed)-truth_px)) if observed is not None and truth_px is not None else None,
                       'half_breadth_m': breadth, 'half_breadth_error_m': abs(breadth-target) if breadth is not None and target is not None else None,
                       'tracer_half_breadth_m': tracer, 'tracer_error_m': abs(tracer-target) if tracer is not None and target is not None else None,
                       'scale_value': answers.get('S', {}).get('value'), 'scale_truth_attachment_px_per_unit': ppm*scale_x,
                       'scale_relative_error': abs(answers['S']['value']/(ppm*scale_x)-1) if answers.get('S',{}).get('value') is not None else None,
                       'raw_answers': answers}
                rows.append(row)
            write_json(attempt / 'score.json', rows[-2:])
    write_json(out / f'{case}.json', rows)
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--binary', type=Path, required=True)
    parser.add_argument('--jobs', type=int, default=2)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=False)
    cases = [f'{h}-L{level}' for h in SETUP_SAMPLE_HULLS for level in range(4)]
    def one(case):
        try:
            rows = evaluate_case(case, args.root, args.out, args.binary)
            print(json.dumps({'case': case, 'rows': len(rows)}), flush=True)
            return rows
        except Exception as error:
            write_json(args.out / f'{case}-error.json', {'error': str(error)})
            print(json.dumps({'case': case, 'error': str(error)}), flush=True)
            return []
    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        rows = [row for group in pool.map(one, cases) for row in group]
    write_json(args.out / 'results.json', rows)


if __name__ == '__main__':
    main()
