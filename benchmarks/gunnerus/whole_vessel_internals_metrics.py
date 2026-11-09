"""Metrics G1 to G5 for the Gunnerus internals (plan section 4.3.2, fixed before the build).

G1 tank x extents against the tank-table frame range; G2 tank volume against the table net
volume; G3 bulkhead x (tank arrangement profile) against the longitudinal-section bulkheads;
G4 share of built internal volume outside the truth solid; G5 parts built by source label.

G4 uses the cached truth mesh (read only): a point is inside the truth when it lies between the
lowest and the highest truth surface on its vertical line (cells of 0.05 m, as step 1).
"""
from __future__ import annotations

import statistics

import numpy as np

from benchmarks.gunnerus.whole_vessel_metrics import CELL_M, X_RANGE_M, Y_RANGE_M, top_height_map
from benchmarks.gunnerus.whole_vessel_internals import frame_x_m

G4_GRID_M = 0.10
G1_TARGET_M = 0.5
G2_TARGET = 0.15
G3_TARGET_M = 0.25
G4_TARGET = 0.05


def _median_abs(values):
    return round(statistics.median(abs(v) for v in values), 4) if values else None


def tank_metrics(parts) -> tuple[dict, dict]:
    g1, g2 = {}, {}
    for part in parts:
        if part.op != 'tank' or not part.slabs:
            continue
        aft, fwd = (frame_x_m(label) for label in part.geometry['table_frames'])
        x0, x1 = part.geometry['x_m']
        if aft is not None and fwd is not None:
            g1[part.id] = {'aft_error_m': round(x0 - aft, 3), 'fwd_error_m': round(x1 - fwd, 3)}
        table = part.geometry.get('table_volume_m3')
        if table:
            g2[part.id] = {'built_m3': round(part.volume_m3, 3), 'table_m3': table,
                           'rel_error': round(part.volume_m3 / table - 1, 4)}
    ends = [e for v in g1.values() for e in (v['aft_error_m'], v['fwd_error_m'])]
    g1_summary = {'per_tank': g1, 'median_abs_end_error_m': _median_abs(ends), 'n_tanks': len(g1),
                  'target_m': G1_TARGET_M}
    g2_summary = {'per_tank': g2, 'median_abs_rel_error': _median_abs([v['rel_error'] for v in g2.values()]),
                  'n_tanks': len(g2), 'target': G2_TARGET}
    return g1_summary, g2_summary


def bulkhead_metrics(reading: dict) -> dict:
    reference = reading['long_section']['bulkheads_x_m']
    built = reading['tank_plan']['profile_bulkheads_x_m']
    errors = {}
    for x in built:
        nearest = min(reference, key=lambda r: abs(r - x)) if reference else None
        errors[f'{x:.2f}'] = None if nearest is None else round(x - nearest, 3)
    within = sum(1 for e in errors.values() if e is not None and abs(e) <= G3_TARGET_M)
    unmatched_reference = [r for r in reference if all(abs(r - x) > G3_TARGET_M for x in built)]
    return {'errors_m': errors, 'within_target': within, 'n_built': len(built),
            'long_section_bulkheads_not_built': unmatched_reference, 'target_m': G3_TARGET_M}


def _inside_points(part) -> np.ndarray:
    """Points on a G4_GRID_M grid inside the part (slab polygons; a thin plate: its mid-plane)."""
    from matplotlib.path import Path as PolygonPath

    points = []
    for x0, x1, outline in part.slabs:
        polygon = np.asarray(outline)
        xs = np.arange(x0 + G4_GRID_M / 2, x1, G4_GRID_M) if x1 - x0 > G4_GRID_M else np.array([(x0 + x1) / 2])
        y0, z0 = polygon.min(axis=0)
        y1, z1 = polygon.max(axis=0)
        ys = np.arange(y0 + G4_GRID_M / 2, y1, G4_GRID_M) if y1 - y0 > G4_GRID_M else np.array([(y0 + y1) / 2])
        zs = np.arange(z0 + G4_GRID_M / 2, z1, G4_GRID_M) if z1 - z0 > G4_GRID_M else np.array([(z0 + z1) / 2])
        yy, zz = np.meshgrid(ys, zs)
        candidates = np.column_stack([yy.ravel(), zz.ravel()])
        keep = candidates[PolygonPath(polygon).contains_points(candidates)]
        for x in xs:
            points.append(np.column_stack([np.full(len(keep), x), keep]))
    return np.concatenate(points) if points else np.zeros((0, 3))


def containment(parts, triangles: np.ndarray) -> dict:
    top = top_height_map(triangles)
    flipped = np.asarray(triangles, dtype=np.float64).copy()
    flipped[..., 2] *= -1
    bottom = -top_height_map(flipped)
    per_part, total_in, total = {}, 0, 0
    for part in parts:
        if not part.slabs:
            continue
        points = _inside_points(part)
        if len(points) == 0:
            continue
        ix = np.floor((points[:, 0] - X_RANGE_M[0]) / CELL_M).astype(int)
        iy = np.floor((points[:, 1] - Y_RANGE_M[0]) / CELL_M).astype(int)
        valid = (ix >= 0) & (ix < top.shape[1]) & (iy >= 0) & (iy < top.shape[0])
        inside = np.zeros(len(points), bool)
        t = top[iy[valid], ix[valid]]
        b = bottom[iy[valid], ix[valid]]
        z = points[valid, 2]
        inside[valid] = np.isfinite(t) & (z >= b) & (z <= t)
        per_part[part.id] = round(1 - inside.mean(), 4)
        total_in += int(inside.sum())
        total += len(points)
    return {'outside_share': round(1 - total_in / total, 4) if total else None, 'points': total,
            'per_part_outside_share': per_part, 'target': G4_TARGET}


def score(parts, reading: dict, truth_triangles: np.ndarray) -> dict:
    g1, g2 = tank_metrics(parts)
    labels: dict[str, int] = {}
    for part in parts:
        if not part.slabs:
            labels['not_built'] = labels.get('not_built', 0) + 1
            continue
        key = 'guessed' if 'guessed' in part.source_labels.values() else 'traced'
        labels[key] = labels.get(key, 0) + 1
    plates = [p for p in parts if p.op in ('deck', 'bulkhead') and p.slabs]
    return {'engineering_approved': False,
            'G1_tank_x_extents': g1, 'G2_tank_volume': g2, 'G3_bulkheads': bulkhead_metrics(reading),
            'G4_containment': containment(parts, truth_triangles),
            'G5_parts': {'built_by_label': labels, 'plates_with_id_and_thickness': len(plates),
                         'plate_thickness_source': 'guessed'}}
