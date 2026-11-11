"""Superstructure detail metrics on Gunnerus (fixed before the build).

Definitions: docs/plans/2026-11-09-whole-vessel-scope.md, section 3.8. Do not change the
constants after a result is seen; add a new metric version instead.

S1 overhang: area samples of each deck, bulwark and deckhouse surface, and their plan distance
outside the hull side at their own height. The hull side is the lines-plan station envelope
(``superstructure.HullSide``), read again here from the lines plan, not from the build inputs.

Usage::

    PYTHONPATH=src:. python -m benchmarks.gunnerus.whole_vessel_superstructure_metrics \\
        --run <step 1 run> --sources work/sources/gunnerus --truth-mesh <truth dir>/truth_mesh.npz
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np

METRIC_VERSION = 'whole-vessel-superstructure/v1'
SHAPED_OPS = ('deck', 'bulwark', 'deckhouse')
# A surface point more than this outside the hull side overhangs. 0.02 m is two deck plate
# thicknesses: below it, plate thickness and the linear station interpolation dominate.
OVERHANG_TOLERANCE_M = 0.02
# Area samples per part (fixed seed): about one sample per 0.05 m2 on the largest deckhouse.
SAMPLES_PER_PART = 20_000
SAMPLE_SEED = 20261110
# Tessellation of the part STEP files (mm): their faces are flat or ruled.
TESSELLATION_MM = 1.0
# Bow stations where the first tier meets the flared hull side (truth half-breadths of the
# tier-1 region are about 4.5, 3.6, 2.5 and 1.4 m here).
BOW_STATIONS_M = (28.0, 31.0, 33.0, 34.0)
TARGETS = {'S1_max_overhang_m': OVERHANG_TOLERANCE_M, 'S4_bow_half_breadth_error_m': 0.10,
           'M2_footprint_iou_min': 0.940, 'M4_volume_error_abs_max': 0.094}


def part_triangles(path: Path) -> np.ndarray:
    import cadquery as cq

    shape = cq.importers.importStep(str(path)).val()
    vertices, faces = shape.tessellate(TESSELLATION_MM, 0.2)
    points = np.array([[v.x, v.y, v.z] for v in vertices]) / 1000.0
    return points[np.asarray(faces)]


def surface_samples(triangles: np.ndarray, count: int, seed: int = SAMPLE_SEED) -> np.ndarray:
    """Area-uniform points on the triangles, plus every vertex (the corners overhang first)."""
    a, b, c = triangles[:, 0], triangles[:, 1], triangles[:, 2]
    areas = 0.5 * np.linalg.norm(np.cross(b - a, c - a), axis=1)
    generator = np.random.default_rng(seed)
    chosen = generator.choice(len(triangles), size=count, p=areas / areas.sum())
    u, v = generator.random(count), generator.random(count)
    flip = u + v > 1
    u[flip], v[flip] = 1 - u[flip], 1 - v[flip]
    points = a[chosen] + u[:, None] * (b - a)[chosen] + v[:, None] * (c - a)[chosen]
    return points, triangles.reshape(-1, 3)


def overhang(hull, triangles: np.ndarray) -> dict:
    samples, corners = surface_samples(triangles, SAMPLES_PER_PART)
    sample_distance = hull.outside_distance(samples[:, 0], samples[:, 1], samples[:, 2])
    corner_distance = hull.outside_distance(corners[:, 0], corners[:, 1], corners[:, 2])
    worst = int(np.argmax(corner_distance))
    return {'max_m': float(max(sample_distance.max(), corner_distance.max())),
            'area_share_outside': float(np.mean(sample_distance > OVERHANG_TOLERANCE_M)),
            'worst_point_m': corners[worst].round(3).tolist()}


def bow_half_breadths(top_map: np.ndarray) -> list[float | None]:
    from benchmarks.gunnerus.whole_vessel_metrics import HOUSE_THRESHOLD_M, grid

    xs, ys = grid()
    result = []
    for x in BOW_STATIONS_M:
        column = top_map[:, int(np.argmin(np.abs(xs - x)))]
        with np.errstate(invalid='ignore'):
            inside = ys[column >= HOUSE_THRESHOLD_M]
        result.append(float(np.abs(inside).max()) if len(inside) else None)
    return result


def score(run: Path, sources: Path, truth_mesh: Path) -> dict:
    from benchmarks.gunnerus.whole_vessel_detail import hull_sections
    from benchmarks.gunnerus.whole_vessel_metrics import (
        score_run,
        step_triangles,
        top_height_map,
    )
    from vessel_reconstruction.superstructure import HullSide

    hull = HullSide.from_sections(hull_sections(sources))
    execution = json.loads((run / 'execution.json').read_text())
    components = (execution.get('result') or {}).get('components', [])
    output = run / 'task' / 'work' / 'output'
    parts, checks, labels = {}, {}, {}
    for component in components:
        for label in component.get('source_labels', {}).values():
            labels[label] = labels.get(label, 0) + 1
        path = output / f'{component["id"]}.step'
        if component.get('op') not in SHAPED_OPS or not component.get('built') or not path.is_file():
            continue
        parts[component['id']] = overhang(hull, part_triangles(path))
        checks[component['id']] = component.get('check_items', [])
    step1 = score_run(run, truth_mesh)
    truth_map = top_height_map(np.load(truth_mesh)['triangles'])
    bow = {'stations_m': list(BOW_STATIONS_M), 'truth_m': bow_half_breadths(truth_map)}
    house = output / 'house_t1.step'
    if house.is_file():
        bow['built_m'] = bow_half_breadths(top_height_map(step_triangles(house)))
        bow['error_m'] = [None if b is None or t is None else round(b - t, 3)
                          for b, t in zip(bow['built_m'], bow['truth_m'])]
    return {'metric_version': METRIC_VERSION, 'engineering_approved': False, 'case': 'gunnerus development',
            'metrics_file_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            'targets': TARGETS, 'overhang_tolerance_m': OVERHANG_TOLERANCE_M,
            'S1_overhang': parts,
            'S1_max_overhang_m': max((p['max_m'] for p in parts.values()), default=None),
            'S2_check_items': checks,
            'S4_bow_half_breadth': bow,
            'S6_argument_labels': labels,
            'step1_metrics': step1['metrics'], 'step1_built': [step1['M7_built'], step1['M7_requested']]}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--sources', type=Path, required=True)
    parser.add_argument('--truth-mesh', type=Path, required=True)
    parser.add_argument('--out', type=Path, help='Report path (default: <run>/superstructure_score.json)')
    args = parser.parse_args()
    report = score(args.run, args.sources, args.truth_mesh)
    (args.out or args.run / 'superstructure_score.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({key: report[key] for key in ('S1_max_overhang_m', 'S1_overhang', 'S4_bow_half_breadth',
                                                   'S6_argument_labels')}, indent=2))


if __name__ == '__main__':
    main()
