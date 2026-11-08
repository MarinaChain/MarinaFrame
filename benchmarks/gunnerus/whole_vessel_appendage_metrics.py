"""Appendage metrics A1 to A3 (docs/plans/2026-11-09-whole-vessel-scope.md, section 3.7).

A1: appendages built, by argument source label. A2: hull contact, the largest vertical gap
between the appendage top and the built hull bottom, over the cells where the hull is above the
appendage. A3: appendage volume where the truth has no material below its bottom (the truth has
no appendages: a content difference, reported only). Height maps use the step 1 grid
(``whole_vessel_metrics``: 0.05 m cells).

Usage::

    PYTHONPATH=src python -m benchmarks.gunnerus.whole_vessel_appendage_metrics \\
        --run <assembly folder> --truth-mesh <truth_mesh.npz>
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from benchmarks.gunnerus.whole_vessel_metrics import CELL_M, top_height_map

METRIC_VERSION = 'whole-vessel-appendages/v1'
TARGET_CONTACT_GAP_M = 0.05


def _triangles_m(shape) -> np.ndarray:
    from vessel_reconstruction.display_mesh import shape_mesh

    vertices, triangles = shape_mesh(shape, 1.0, 0.5)
    return vertices[triangles] / 1000.0


def bottom_height_map(triangles: np.ndarray) -> np.ndarray:
    """Lowest surface z at each cell centre (NaN where none)."""
    flipped = np.array(triangles, dtype=np.float64)
    flipped[..., 2] *= -1.0
    return -top_height_map(flipped)


def _cell_x(mask: np.ndarray, gap: np.ndarray) -> float:
    from benchmarks.gunnerus.whole_vessel_metrics import grid

    xs, _ = grid()
    _, column = np.unravel_index(np.nanargmax(np.where(mask, gap, np.nan)), gap.shape)
    return xs[column]


def contact_and_truth(appendage: np.ndarray, hull_bottom: np.ndarray, truth_bottom: np.ndarray) -> dict:
    top, bottom = top_height_map(appendage), bottom_height_map(appendage)
    cells = np.isfinite(top)
    under_hull = cells & np.isfinite(hull_bottom)
    gaps = np.clip(hull_bottom[under_hull] - top[under_hull], 0.0, None)
    floor = np.where(np.isfinite(truth_bottom), truth_bottom, np.inf)
    outside_truth = np.clip(np.minimum(top, floor) - bottom, 0.0, None)[cells]
    return {'top_cells': int(cells.sum()), 'top_cells_under_hull': int(under_hull.sum()),
            'A2_max_gap_m': float(gaps.max()) if gaps.size else None,
            'A2_met': bool(gaps.size and gaps.max() <= TARGET_CONTACT_GAP_M),
            # Information only (not the fixed metric): where the gap is.
            'cells_within_gap_target_fraction': float((gaps <= TARGET_CONTACT_GAP_M).mean()) if gaps.size else None,
            'x_of_max_gap_m': float(_cell_x(under_hull, hull_bottom - top)) if gaps.size else None,
            'A3_volume_without_truth_m3': float(outside_truth.sum() * CELL_M * CELL_M)}


def score_run(run: Path, truth_mesh: Path) -> dict:
    from benchmarks.gunnerus.whole_vessel_assembly import read_shape

    record = json.loads((run / 'whole_vessel' / 'execution.json').read_text())
    components = {c['id']: c for c in record['result']['components']}
    hull_bottom = bottom_height_map(_triangles_m(read_shape(run / 'hull_to_deck.brep')))
    truth_bottom = bottom_height_map(np.load(truth_mesh)['triangles'])
    result = {'metric_version': METRIC_VERSION, 'status': 'draft_only', 'engineering_approved': False,
              'appendages': {}}
    for name, component in components.items():
        if component.get('op') != 'appendage':
            continue
        entry = {'built': bool(component.get('built')), 'A1_source_labels': component.get('source_labels', {}),
                 'volume_m3': component.get('volume_m3')}
        if entry['built']:
            entry.update(contact_and_truth(_triangles_m(read_shape(run / 'whole_vessel' / f'{name}.step')),
                                           hull_bottom, truth_bottom))
        result['appendages'][name] = entry
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--truth-mesh', type=Path, required=True)
    args = parser.parse_args()
    result = score_run(args.run, args.truth_mesh)
    (args.run / 'appendage_score.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
