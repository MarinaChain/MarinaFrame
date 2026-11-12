"""Offline one-to-one box scoring, independent of reader IDs and label spellings.

A pair is eligible only with the same kind and positive 3D intersection.
Maximize eligible pair count, then minimize mean absolute six-face error.
This is a measurement report, not an engineering acceptance gate.
"""
from __future__ import annotations

import math

import numpy as np
from scipy.optimize import linear_sum_assignment

from vessel_reconstruction.ga_arrangement import hull_size, item_box, load_input

AXES = 'xyz'
FACES = tuple(f'{axis}_{end}' for axis in AXES for end in ('min', 'max'))


def _faces(box):
    values = [float(value) for axis in AXES for value in box[axis]]
    if not all(math.isfinite(v) for v in values):
        raise ValueError('box faces must be finite')
    if any(values[i] >= values[i + 1] for i in (0, 2, 4)):
        raise ValueError('box faces must be ordered and have positive size')
    return np.array(values)


def _overlaps(a, b):
    return bool(np.all(np.minimum(a[1::2], b[1::2]) > np.maximum(a[::2], b[::2])))


def score(truth: dict, reading: dict) -> dict:
    if truth.get('schema') != 'marinaframe.ga_synthetic_truth.v1':
        raise ValueError('unsupported truth schema')
    if truth.get('case_id') != reading.get('case_id'):
        raise ValueError('case_id must agree')
    if truth.get('engineering_approved') is not False:
        raise ValueError('engineering_approved must be false')
    spaces = truth['spaces']
    if not spaces:
        raise ValueError('truth must contain spaces')
    data = load_input(reading)
    ids = [s['id'] for s in reading.get('spaces', [])]
    if len(ids) != len(set(ids)):
        raise ValueError('reading space IDs must be unique')
    size = hull_size(data)
    predicted = []
    for item in data.items:
        box = item_box(item, data, size)
        predicted.append({'id': item.id, 'kind': item.kind,
                          'faces': _faces({'x': box.x, 'y': box.y, 'z': box.z}),
                          'guessed_axes': box.guessed})
    expected = [{**space, 'faces': _faces(space['box_m'])} for space in spaces]
    matches, found, used = [], set(), set()
    by_kind = {}
    kinds = sorted({s['kind'] for s in expected} | {s['kind'] for s in predicted} |
                   {s['kind'] for s in reading.get('spaces', [])})
    for kind in kinds:
        targets = [s for s in expected if s['kind'] == kind]
        candidates = [s for s in predicted if s['kind'] == kind]
        errors = []
        if targets and candidates:
            costs = np.array([[float(np.mean(np.abs(t['faces'] - p['faces']))) for p in candidates]
                              for t in targets])
            eligible = np.array([[_overlaps(t['faces'], p['faces']) for p in candidates] for t in targets])
            # One ineligible edge must cost more than every eligible edge combined.
            penalty = (float(costs.max()) + 1) * (min(costs.shape) + 1)
            rows, cols = linear_sum_assignment(np.where(eligible, costs, penalty))
            for row, col in zip(rows, cols):
                if not eligible[row, col]:
                    continue
                target, candidate = targets[row], candidates[col]
                signed = candidate['faces'] - target['faces']
                found.add(target['id'])
                used.add(candidate['id'])
                errors.append(np.abs(signed))
                matches.append({'truth_id': target['id'], 'reading_id': candidate['id'], 'kind': kind,
                                'face_error_m': dict(zip(FACES, map(float, signed))),
                                'guessed_axes': candidate['guessed_axes']})
        flat = np.array(errors)
        kind_missing = [s['id'] for s in targets if s['id'] not in found]
        kind_extra = [s['id'] for s in candidates if s['id'] not in used]
        by_kind[kind] = {'truth_count': len(targets), 'found_count': len(errors),
                         'found_fraction': len(errors) / len(targets) if targets else None,
                         'missing': kind_missing, 'invented': kind_extra,
                         'mean_absolute_face_error_m': float(flat.mean()) if errors else None,
                         'max_absolute_face_error_m': float(flat.max()) if errors else None,
                         'mean_absolute_error_by_face_m': dict(zip(FACES, map(float, flat.mean(axis=0)))) if errors else None}
    # Unsupported kinds are inventions; known spaces without extents are unmeasured.
    unmeasured = [s['id'] for s in data.skipped if s['reason'] == 'no extent']
    unsupported = [s['id'] for s in data.skipped if s['reason'] != 'no extent']
    invented = [s['id'] for s in predicted if s['id'] not in used] + unsupported
    for space in reading.get('spaces', []):
        if space['id'] in unsupported:
            by_kind[space['kind']]['invented'].append(space['id'])
    return {'schema': 'marinaframe.ga_synthetic_score.v1', 'case_id': truth['case_id'],
            'engineering_approved': False,
            'matching': 'same kind; positive 3D overlap; max cardinality then min mean absolute face error',
            'found_fraction': len(found) / len(expected), 'matches': matches, 'by_kind': by_kind,
            'missing': [s['id'] for s in expected if s['id'] not in found],
            'invented': invented, 'unmeasured': unmeasured}
