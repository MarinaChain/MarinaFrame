"""Post-inference development comparison, including exported STEP intersections.

Reference data is accepted only by this evaluator. It is not a domain tool and
never feeds a candidate selection or reconstruction. Every requested ordinate
is counted, including absent/ambiguous boundaries. Raw records remain intact.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import time
import numpy as np

from benchmarks.audit_geometry_hardening import read_step, cut_segments


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def intersect_ordinates(segments, z):
    """Vectorized equivalent of the fixed1nm straight-edge intersection policy.

    Horizontal overlaps remain ambiguous except at the first/last requested
    domain endpoints, where their outer boundary is explicitly compared.
    No zero-area absence is converted to a successful boundary observation.
    """
    tolerance = 1e-9
    z = np.asarray(z, dtype=float)
    if not segments:
        return np.full(len(z), np.nan), ['absent'] * len(z), 0, 0
    s = np.asarray(segments, dtype=float)
    ya, za, yb, zb = (s[:, 0, 0, None], s[:, 0, 1, None],
                      s[:, 1, 0, None], s[:, 1, 1, None])
    low, high = np.minimum(za, zb), np.maximum(za, zb)
    bounded = np.minimum(high, np.maximum(low, z[None, :]))
    horizontal = np.abs(zb - za) <= tolerance
    inside = (z[None, :] >= low - tolerance) & (z[None, :] <= high + tolerance)
    values = ya + (bounded - za) * (yb - ya) / np.where(horizontal, 1., zb - za)
    valid = inside & ~horizontal & (values >= -tolerance)
    values = np.maximum(0., values)
    minimum = np.min(np.where(valid, values, np.inf), axis=0)
    maximum = np.max(np.where(valid, values, -np.inf), axis=0)
    # Degenerate horizontal points contribute the same boundary as endpoints.
    positive_horizontal = inside & horizontal & (np.maximum(ya, yb) >= -tolerance)
    lower_y, upper_y = np.maximum(0., np.minimum(ya, yb)), np.maximum(0., np.maximum(ya, yb))
    points = positive_horizontal & (upper_y - lower_y <= tolerance)
    mid = (lower_y + upper_y) / 2.
    minimum = np.minimum(minimum, np.min(np.where(points, mid, np.inf), axis=0))
    maximum = np.maximum(maximum, np.max(np.where(points, mid, -np.inf), axis=0))
    spans = positive_horizontal & (upper_y - lower_y > tolerance)
    overlap = np.any(spans, axis=0)
    ambiguous = overlap | ((maximum - minimum) > tolerance)
    absent = ~np.isfinite(minimum) & ~overlap
    y = np.full(len(z), np.nan)
    present = np.isfinite(minimum) & np.isfinite(maximum)
    y[present] = (minimum[present] + maximum[present]) / 2.
    statuses = np.where(absent, 'absent', np.where(ambiguous, 'ambiguous', 'complete'))
    closures = 0
    for index in (0, len(z) - 1):
        if overlap[index]:
            y[index] = max(float(maximum[index]), float(np.max(np.where(spans[:, index], upper_y[:, 0], -np.inf))))
            statuses[index] = 'complete'
            closures += 1
    y[statuses != 'complete'] = np.nan
    assisted = int(np.sum(np.any(valid & (bounded != z[None, :]), axis=0)))
    return y, statuses.tolist(), closures, assisted


def metrics(error):
    e = np.asarray(error, dtype=float)
    return {'sample_count': int(e.size), 'rms_y_m': float(np.sqrt(np.mean(e * e))),
            'p95_absolute_y_m': float(np.quantile(np.abs(e), .95)),
            'maximum_local_y_m': float(np.max(np.abs(e)))}


def compare(reference_path: Path, runs: list[Path], cut_ids: list[str], output: Path):
    if output.exists():
        raise FileExistsError('Retain previous evaluation evidence and choose a fresh output path')
    reference = json.loads(reference_path.read_text())
    report = {'experiment': 'source_fidelity_development_comparison_v1',
              'known_development_only': True, 'reference_accessed_after_inference': True,
              'reference_path': str(reference_path), 'reference_sha256': digest(reference_path),
              'comparator_sha256': digest(__file__), 'raw_frozen_gates_unchanged': True,
              'step_cut_ids_declared_before_scoring': cut_ids,
              'boundary_policy': 'Straight and degree1B-spline STEP edges, fixed1nm endpoint tolerance; outer endpoint of horizontal domain closure explicitly compared; absent and ambiguous ordinates remain unresolved.',
              'engineering_approved': False, 'runs': []}
    refs = {s['id']: s for s in reference['sections']}
    for task in runs:
        started = time.monotonic()
        summary = json.loads((task / 'probe-summary.json').read_text())
        run = task / summary['candidate_run_relative_path']
        result = json.loads((run / 'result.json').read_text())
        cad = json.loads((run / 'cad_sections.json').read_text())
        if isinstance(cad, dict): cad = cad['sections']
        row = {'name': task.name, 'candidate_run': str(run), 'step_sha256': digest(run / 'model.step'),
               'inference_summary_sha256': digest(task / 'probe-summary.json'), 'section_count': len(result['sections'])}
        for label, sections, key in [('extracted', result['sections'], 'points_yz_m'), ('declared_cad', cad, 'cad_points_yz_m')]:
            errors = []; per_section = []
            if set(s['id'] for s in sections) != set(refs): raise ValueError('Missing or extra source section')
            for section in sections:
                truth = np.asarray(refs[section['id']]['points_yz_m'])
                points = np.asarray(section[key]); z = truth[:, 1]
                if abs(section['x_m'] - refs[section['id']]['x_m']) > 1e-8: raise ValueError('Wrong station')
                if abs(points[0, 1] - z[0]) > 1e-8 or abs(points[-1, 1] - z[-1]) > 1e-8: raise ValueError('Incomplete height domain')
                error = np.interp(z, points[:, 1], points[:, 0]) - truth[:, 0]
                errors.extend(error.tolist())
                per_section.append({'id': section['id'], **metrics(error), 'first_ordinate_y_m': float(points[0, 0]), 'output_point_count': len(points)})
            row[label] = {**metrics(errors), 'sections': per_section}
        shape = read_step(run / 'model.step')
        import cadquery as cq
        solid = cq.Shape.cast(shape)
        row['step_reimport'] = {'valid': bool(solid.isValid()), 'solid_count': len(solid.Solids()),
                                'volume_m3': float(solid.Volume()) / 1e9}
        row['reference_volume_m3'] = reference['reference_volume_m3']
        row['relative_volume_error'] = abs(row['step_reimport']['volume_m3'] - reference['reference_volume_m3']) / reference['reference_volume_m3']
        tol = reference.get('original_tolerances')
        if tol:
            row['original_tolerances'] = tol
            row['original_numeric_gate_passed'] = bool(row['step_reimport']['valid'] and row['step_reimport']['solid_count'] == 1
                and row['relative_volume_error'] <= tol['relative_volume_error_max']
                and all(row[k]['rms_y_m'] <= tol['rms_section_y_m_max'] and row[k]['maximum_local_y_m'] <= tol['max_local_y_m_max'] for k in ('extracted', 'declared_cad')))
        cuts = []
        for sid in cut_ids:
            truth = np.asarray(refs[sid]['points_yz_m']); z = truth[:, 1]
            cut = cut_segments(shape, refs[sid]['x_m'])
            if cut['status'] == 'complete':
                y, statuses, closures, assisted = intersect_ordinates(cut['segments'], z)
            else:
                y, statuses, closures, assisted = np.full(len(z), np.nan), [cut['status']] * len(z), 0, 0
            complete = np.isfinite(y)
            errors = y[complete] - truth[complete, 0]
            cuts.append({'id': sid, 'x_m': refs[sid]['x_m'], 'complete': bool(np.all(complete)),
                         'requested': len(z), 'compared': int(np.sum(complete)),
                         'statuses': {key: statuses.count(key) for key in set(statuses)},
                         'metrics_on_compared_ordinates': metrics(errors) if len(errors) else None,
                         'closure_outer_endpoints_compared': closures, 'endpoint_tolerance_assisted_ordinates': assisted,
                         'curve_types': cut['curve_types'], 'unsupported': cut['unsupported'],
                         'samples_z_actual_reference_error': [[float(zz), float(yy) if np.isfinite(yy) else None, float(refy), float(yy - refy) if np.isfinite(yy) else None] for zz, yy, refy in zip(z, y, truth[:, 0])],
                         'unresolved_ordinates': [{'z_m': float(zz), 'status': status} for zz, status in zip(z, statuses) if status != 'complete']})
        row['actual_step_cuts'] = cuts
        row['wall_seconds'] = time.monotonic() - started
        report['runs'].append(row)
    output.write_text(json.dumps(report, indent=2, allow_nan=False) + '\n')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference', type=Path, required=True)
    parser.add_argument('--run', type=Path, action='append', required=True)
    parser.add_argument('--cut', action='append', required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    result = compare(args.reference, args.run, args.cut, args.out)
    print(json.dumps([{k: v for k, v in r.items() if k not in ('actual_step_cuts', 'extracted', 'declared_cad')} for r in result['runs']], indent=2))
