"""Bounded deterministic drawing measurements for ship CAD investigation.

Region bounds are selectors, never dimensions. Ambiguous selectors abstain.
DXF units and drawing datums are host-reviewed input, not model assertions.
"""
from __future__ import annotations

import hashlib
import math
from pathlib import Path

MAX_ENTITIES = 200_000
MAX_POINTS = 4096


def _base(view, region, method, source_sha256):
    return {'view': view, 'region': region, 'method': method, 'source_sha256': source_sha256}


def _failure(base, reason):
    return {**base, 'status': 'failed', 'reason': reason}


def _inside(points, box):
    return all(box[0] <= p[0] <= box[2] and box[1] <= p[1] <= box[3] for p in points)


def _joined_outline(entities, bounds):
    """Join exact source endpoints (roundoff only), with no gaps or branches."""
    edges = [e for e in entities if not e.get('closed') and len(e['points']) >= 2
             and _inside(e['points'], bounds)]
    if not edges:
        return None
    def key(p):
        return tuple(round(v, 6) for v in p)
    adjacency = {}
    for i, edge in enumerate(edges):
        for p in (edge['points'][0], edge['points'][-1]):
            adjacency.setdefault(key(p), []).append(i)
    if any(len(indices) != 2 for indices in adjacency.values()):
        return None
    remaining, points, handles = set(range(len(edges))), [], []
    current = key(edges[0]['points'][0])
    start = current
    while remaining:
        choices = [i for i in adjacency[current] if i in remaining]
        if not choices:
            return None  # Disconnected loops are ambiguous, not an exterior.
        i = choices[0]
        edge = edges[i]
        p = edge['points'] if key(edge['points'][0]) == current else edge['points'][::-1]
        points.extend(p if not points else p[1:])
        handles.append(edge['id'])
        remaining.remove(i)
        current = key(p[-1])
    if current != start or len(points) > MAX_POINTS:
        return None
    return {'id': '+'.join(handles), 'entity_ids': handles, 'points': points, 'closed': True}


def measure_outline(entities, bounds, *, scale, origin, view, region, source_sha256):
    base = _base(view, region, 'closed_outline', source_sha256)
    if not math.isfinite(scale) or scale <= 0:
        return _failure(base, 'Drawing scale is not calibrated')
    candidates = []
    joined = _joined_outline(entities, bounds)
    for entity in list(entities) + ([joined] if joined else []):
        points = entity['points']
        if entity.get('closed') and 3 <= len(points) <= MAX_POINTS and _inside(points, bounds):
            if points[0] == points[-1]:
                points = points[:-1]
            area = abs(sum(a[0]*b[1] - b[0]*a[1] for a, b in zip(points, points[1:]+points[:1]))) / 2
            if area > 0:
                candidates.append((entity, points))
    if len(candidates) != 1:
        return _failure(base, f'Expected one closed outline; found {len(candidates)}')
    entity, points = candidates[0]
    return {**base, 'status': 'measured', 'kind': 'outline', 'entity_ids': entity.get('entity_ids', [entity['id']]),
            'value': [[(p[0]-origin[0])*scale, (p[1]-origin[1])*scale] for p in points],
            'calibration': {'metres_per_unit': scale, 'origin': list(origin)}, 'region_bounds': bounds}


def measure_interval(entities, bounds, *, scale, origin, view, region, source_sha256):
    base = _base(view, region, 'parallel_lines', source_sha256)
    candidates = []
    for entity in entities:
        p = entity['points']
        if len(p) == 2 and _inside(p, bounds) and abs(p[0][1]-p[1][1]) < 1e-6 and p[0][0] != p[1][0]:
            candidates.append((entity['id'], p[0][1]))
    levels = sorted(set(round(y, 6) for _, y in candidates))
    if len(levels) != 2:
        return _failure(base, f'Expected two horizontal levels; found {len(levels)}')
    return {**base, 'status': 'measured', 'kind': 'interval', 'entity_ids': [e for e, _ in candidates],
            'value': [(v-origin[1])*scale for v in levels],
            'calibration': {'metres_per_unit': scale, 'origin': list(origin)}, 'region_bounds': bounds}


def read_dxf(path: Path, *, layers=None):
    """Extract source entity coordinates; never infer a hull from the region box."""
    from ezdxf import path as dxf_path

    from .dxf_documents import read_document

    document = read_document(path)
    entities = []
    for index, entity in enumerate(document.modelspace()):
        if index >= MAX_ENTITIES:
            raise ValueError('DXF entity budget exceeded')
        if layers is not None and entity.dxf.layer not in layers:
            continue
        if entity.dxftype() not in ('LINE', 'LWPOLYLINE', 'POLYLINE', 'ARC', 'CIRCLE', 'SPLINE'):
            continue
        try:
            curve = dxf_path.make_path(entity)
            points = [[float(p.x), float(p.y)] for p in curve.flattening(distance=1.0, segments=4)]
            if len(points) > MAX_POINTS:
                continue
            entities.append({'id': entity.dxf.handle, 'layer': entity.dxf.layer, 'points': points,
                             'closed': curve.is_closed})
        except (ValueError, TypeError, NotImplementedError):
            continue
    return entities


def source_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        while block := stream.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def investigate(request: dict, views: dict, cache=None) -> dict:
    """Tool dispatcher. Host views bind files, scales, regions and drawing datums.

    The model supplies only tool, view and region names. It cannot choose files,
    calibration or numeric output. Repeated requests return the same evidence.
    """
    if set(request) != {'tool', 'view', 'region'}:
        raise ValueError('measurement tool fields')
    if request['tool'] not in ('closed_outline', 'parallel_lines'):
        raise ValueError('measurement tool not allowed')
    view = views[request['view']]
    region = view['regions'][request['region']]
    path = Path(view['file'])
    key = (str(path), tuple(view.get('layers', [])))
    if cache is None:
        cache = {}
    if key not in cache:
        cache[key] = read_dxf(path, layers=view.get('layers'))
    tool = measure_outline if request['tool'] == 'closed_outline' else measure_interval
    return tool(cache[key], region, scale=view['metres_per_unit'], origin=view['origin'],
                view=request['view'], region=request['region'], source_sha256=source_hash(path))
