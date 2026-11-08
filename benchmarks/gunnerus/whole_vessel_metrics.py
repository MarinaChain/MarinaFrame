"""Whole-vessel step 1 metrics on Gunnerus (fixed before the build).

Definitions: docs/plans/2026-11-09-whole-vessel-scope.md, section 3.4. Do not
change the constants after a result is seen; add a new metric version instead.

Truth: the cached truth mesh of the sealed hull protocol (read only). The truth
and every built component are measured the same way: a top-height map, the
highest surface on the vertical line at each cell centre.

Usage::

    PYTHONPATH=src python -m benchmarks.gunnerus.whole_vessel_metrics \\
        --run work/whole-vessel/run-001 --truth-mesh <truth dir>/truth_mesh.npz
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np

METRIC_VERSION = 'whole-vessel-step1/v1'
CELL_M = 0.05
X_RANGE_M = (-2.0, 36.0)
Y_RANGE_M = (-5.2, 5.2)
HOUSE_THRESHOLD_M = 5.5  # between the bulwark top and A-deck
OPENING_M = 0.30  # removes rails and bulwarks from the house region
DECK_BAND_M = (3.8, 4.4)
DECK_EROSION_M = 0.30
BULWARK_LOW_M = 4.6
DEPTH_TO_1_DECK_M = 4.287  # GA title block; common base of the volume metric
TARGETS = {'M1_deck_level_error_m': 0.05, 'M1_coverage': 0.90, 'M2_footprint_iou': 0.90,
           'M3_roof_height_error_m': 0.10, 'M4_volume_error': 0.10, 'M5_x_end_error_m': 0.5,
           'M6_bulwark_top_error_m': 0.10}
# Triangle pairs per vectorised chunk (memory bound, about 0.5 GB of float64 work arrays).
CHUNK_PAIRS = 4_000_000
# Faces closer to vertical than this give no top height (their projection has no area).
MIN_PROJECTED_AREA_M2 = 1e-12


def grid():
    nx = int(round((X_RANGE_M[1] - X_RANGE_M[0]) / CELL_M))
    ny = int(round((Y_RANGE_M[1] - Y_RANGE_M[0]) / CELL_M))
    xs = X_RANGE_M[0] + (np.arange(nx) + 0.5) * CELL_M
    ys = Y_RANGE_M[0] + (np.arange(ny) + 0.5) * CELL_M
    return xs, ys


def top_height_map(triangles: np.ndarray) -> np.ndarray:
    """Highest surface z at each cell centre; NaN where no surface is above or below."""
    xs, ys = grid()
    t = np.asarray(triangles, dtype=np.float64)
    a, b, c = t[:, 0], t[:, 1], t[:, 2]
    area2 = (b[:, 0] - a[:, 0]) * (c[:, 1] - a[:, 1]) - (c[:, 0] - a[:, 0]) * (b[:, 1] - a[:, 1])
    keep = np.abs(area2) > 2 * MIN_PROJECTED_AREA_M2
    a, b, c, area2 = a[keep], b[keep], c[keep], area2[keep]
    lo = np.minimum(np.minimum(a, b), c)
    hi = np.maximum(np.maximum(a, b), c)
    ix0 = np.ceil((lo[:, 0] - X_RANGE_M[0]) / CELL_M - 0.5).astype(np.int64).clip(0, len(xs))
    ix1 = np.floor((hi[:, 0] - X_RANGE_M[0]) / CELL_M - 0.5).astype(np.int64).clip(-1, len(xs) - 1)
    iy0 = np.ceil((lo[:, 1] - Y_RANGE_M[0]) / CELL_M - 0.5).astype(np.int64).clip(0, len(ys))
    iy1 = np.floor((hi[:, 1] - Y_RANGE_M[0]) / CELL_M - 0.5).astype(np.int64).clip(-1, len(ys) - 1)
    nxr, nyr = ix1 - ix0 + 1, iy1 - iy0 + 1
    hit = (nxr > 0) & (nyr > 0)
    index = np.nonzero(hit)[0]
    counts = (nxr * nyr)[index]
    top = np.full(len(ys) * len(xs), -np.inf)
    start = 0
    while start < len(index):
        stop = start + max(1, int(np.searchsorted(np.cumsum(counts[start:]), CHUNK_PAIRS)))
        tri, n = index[start:stop], counts[start:stop]
        rep = np.repeat(tri, n)
        local = np.arange(n.sum()) - np.repeat(np.cumsum(n) - n, n)
        gx = ix0[rep] + local % nxr[rep]
        gy = iy0[rep] + local // nxr[rep]
        px, py = xs[gx], ys[gy]
        ax, ay, bx, by, cx, cy = a[rep, 0], a[rep, 1], b[rep, 0], b[rep, 1], c[rep, 0], c[rep, 1]
        d = area2[rep]
        w1 = ((bx - px) * (cy - py) - (cx - px) * (by - py)) / d
        w2 = ((cx - px) * (ay - py) - (ax - px) * (cy - py)) / d
        w3 = 1.0 - w1 - w2
        inside = (w1 >= -1e-9) & (w2 >= -1e-9) & (w3 >= -1e-9)
        z = w1 * a[rep, 2] + w2 * b[rep, 2] + w3 * c[rep, 2]
        np.maximum.at(top, (gy * len(xs) + gx)[inside], z[inside])
        start = stop
    top[~np.isfinite(top)] = np.nan
    return top.reshape(len(ys), len(xs))


def _largest(mask):
    from scipy import ndimage

    labels, count = ndimage.label(mask)
    if count == 0:
        return mask
    sizes = ndimage.sum(mask, labels, index=np.arange(1, count + 1))
    return labels == (int(np.argmax(sizes)) + 1)


def truth_regions(truth: np.ndarray) -> dict:
    from scipy import ndimage

    xs, _ = grid()
    x = np.broadcast_to(xs[None, :], truth.shape)
    with np.errstate(invalid='ignore'):
        size = int(round(OPENING_M / CELL_M))
        house = _largest(ndimage.binary_opening(truth >= HOUSE_THRESHOLD_M, structure=np.ones((size, size))))
        x_house = float(x[house].min()) if house.any() else np.inf
        deck = (truth >= DECK_BAND_M[0]) & (truth <= DECK_BAND_M[1]) & (x < x_house)
        deck = ndimage.binary_erosion(deck, iterations=int(round(DECK_EROSION_M / CELL_M)))
        bulwark = (x < x_house) & (truth > BULWARK_LOW_M) & (truth < HOUSE_THRESHOLD_M)
    return {'house': house, 'deck': deck, 'bulwark': bulwark}


def _x_ends(mask) -> list[float] | None:
    xs, _ = grid()
    columns = np.nonzero(mask.any(axis=0))[0]
    return [float(xs[columns[0]]), float(xs[columns[-1]])] if len(columns) else None


def score_maps(truth: np.ndarray, built: dict[str, np.ndarray], tops: dict[str, float]) -> dict:
    """Metrics M1-M6 from the truth map and built maps per component id."""
    regions = truth_regions(truth)
    cell_area = CELL_M ** 2
    result = {'truth_region_cells': {k: int(v.sum()) for k, v in regions.items()}}
    deck = built.get('aft_deck')
    if deck is not None and regions['deck'].any():
        both = regions['deck'] & np.isfinite(deck)
        result['M1_deck_level_error_m'] = float(np.median(deck[both] - truth[both])) if both.any() else None
        result['M1_coverage'] = float(both.sum() / regions['deck'].sum())
    house = built.get('house_t1')
    if house is not None and regions['house'].any():
        with np.errstate(invalid='ignore'):
            footprint = house >= HOUSE_THRESHOLD_M
        union = (footprint | regions['house']).sum()
        common = footprint & regions['house']
        result['M2_footprint_iou'] = float(common.sum() / union)
        result['M3_roof_height_error_m'] = float(np.median(house[common] - truth[common])) if common.any() else None
        volume_truth = float(np.sum(truth[regions['house']] - DEPTH_TO_1_DECK_M) * cell_area)
        volume_built = float(np.sum(house[footprint] - DEPTH_TO_1_DECK_M) * cell_area)
        result['M4_volume_truth_m3'] = volume_truth
        result['M4_volume_built_m3'] = volume_built
        result['M4_volume_error'] = (volume_built - volume_truth) / volume_truth
        truth_ends, built_ends = _x_ends(regions['house']), _x_ends(footprint)
        result['M5_x_ends_truth_m'] = truth_ends
        result['M5_x_ends_built_m'] = built_ends
        if truth_ends and built_ends:
            result['M5_x_end_error_m'] = [built_ends[0] - truth_ends[0], built_ends[1] - truth_ends[1]]
    if 'aft_bulwark' in tops:
        if regions['bulwark'].any():
            result['M6_truth_bulwark_cells'] = int(regions['bulwark'].sum())
            result['M6_bulwark_top_error_m'] = float(tops['aft_bulwark'] - np.median(truth[regions['bulwark']]))
        else:
            result['M6_bulwark_top_error_m'] = 'not measurable: truth has no surface in the bulwark band'
    return result


def step_triangles(path: Path, tolerance_m: float = 0.001) -> np.ndarray:
    """Tessellate an exported component STEP (millimetres) into triangles in metres."""
    import cadquery as cq

    shape = cq.importers.importStep(str(path)).val()
    vertices, faces = shape.tessellate(tolerance_m * 1000, 0.2)
    points = np.array([[v.x, v.y, v.z] for v in vertices]) / 1000.0
    return points[np.asarray(faces)]


def score_run(run: Path, truth_mesh: Path) -> dict:
    execution = json.loads((run / 'execution.json').read_text())
    components = (execution.get('result') or {}).get('components', [])
    output = run / 'task' / 'work' / 'output'
    truth = top_height_map(np.load(truth_mesh)['triangles'])
    built, tops, labels = {}, {}, {}
    for component in components:
        labels[component['id']] = {'status': component['status'], 'built': component.get('built', False),
                                   'source_labels': component.get('source_labels', {})}
        path = output / f'{component["id"]}.step'
        if component.get('built') and path.is_file():
            built[component['id']] = top_height_map(step_triangles(path))
            tops[component['id']] = component['bbox_m']['max'][2]
    metrics = score_maps(truth, built, tops)
    counts = {}
    for item in labels.values():
        for label in item['source_labels'].values():
            counts[label] = counts.get(label, 0) + 1
    report = {'metric_version': METRIC_VERSION, 'engineering_approved': False, 'case': 'gunnerus development',
              'metrics_file_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              'truth_mesh_sha256': hashlib.sha256(truth_mesh.read_bytes()).hexdigest(),
              'targets': TARGETS, 'metrics': metrics,
              'M7_components': labels, 'M7_built': sum(item['built'] for item in labels.values()),
              'M7_requested': len(labels), 'M7_argument_labels': counts,
              'not_measurable': ['house_t2', 'wheelhouse', 'fwd_rail', 'main_deck (inside the house)']}
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--truth-mesh', type=Path, required=True)
    args = parser.parse_args()
    report = score_run(args.run, args.truth_mesh)
    (args.run / 'whole_vessel_score.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report['metrics'], indent=2))
    print('built', report['M7_built'], 'of', report['M7_requested'], report['M7_argument_labels'])


if __name__ == '__main__':
    main()
