"""Restricted, reference-only ship programs. This module never evaluates model code.

Only the drawing measurement harness supplies the measurement map. A program
cannot add measurements, choose an output path, or set review/approval state.
"""
from __future__ import annotations

import json
import math
import re
from pathlib import Path

import numpy as np

SCHEMA = 'ship-cad/v1'
MAX_COMPONENTS = 64
MAX_PROGRAM_BYTES = 64 * 1024
# This is a draft comparison tolerance, not an engineering acceptance gate.
VIEW_DISTANCE_M = 0.05
IDENTIFIER = re.compile(r'[A-Za-z][A-Za-z0-9_-]{0,63}\Z')
OPERATIONS = {
    'hull': {'sections': 'sections'},
    'deck': {'outline': 'outline', 'height': 'interval'},
    'deckhouse': {'outline': 'outline', 'height': 'interval'},
    'bulwark': {'outline': 'outline', 'height': 'interval', 'thickness': 'length'},
    'appendage': {'outline': 'outline', 'span': 'interval'},
    'opening': {'outline': 'outline', 'height': 'interval', 'target': 'component'},
}
METHODS = {'closed_outline', 'parallel_lines', 'body_plan_regions', 'dimension_text'}


def _id(value) -> bool:
    return isinstance(value, str) and IDENTIFIER.fullmatch(value) is not None


def _keys(value, expected, context):
    if not isinstance(value, dict) or set(value) != set(expected):
        raise ValueError(f'{context}: unexpected or missing fields')


def _unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f'duplicate JSON key: {key}')
        result[key] = value
    return result


def parse_program(text: str) -> dict:
    if len(text.encode()) > MAX_PROGRAM_BYTES:
        raise ValueError('ship program exceeds byte limit')
    return validate_program(json.loads(text, object_pairs_hook=_unique_pairs,
                                      parse_constant=lambda x: (_ for _ in ()).throw(ValueError(x))))


def validate_program(program: dict) -> dict:
    _keys(program, {'schema', 'components'}, 'program')
    if program['schema'] != SCHEMA:
        raise ValueError('unknown ship language version')
    components = program['components']
    if not isinstance(components, list) or not 1 <= len(components) <= MAX_COMPONENTS:
        raise ValueError('ship component count')
    seen = set()
    for component in components:
        _keys(component, {'id', 'op', 'source', 'args'}, 'component')
        name, op = component['id'], component['op']
        if not _id(name) or name in seen or not isinstance(op, str) or op not in OPERATIONS:
            raise ValueError('invalid component id or operation')
        _keys(component['source'], {'view', 'region', 'method'}, 'source')
        source = component['source']
        if (source['view'] not in ('plan', 'profile', 'body') or not _id(source['region'])
                or source['method'] not in METHODS):
            raise ValueError('unknown source view, region or method')
        _keys(component['args'], OPERATIONS[op], 'arguments')
        for key, reference in component['args'].items():
            if not _id(reference):
                raise ValueError('dimensions must be named measurement references')
            if key == 'target' and reference not in seen:
                raise ValueError('opening target must be an earlier component')
        seen.add(name)
    return program


def _finite(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _measurement_ok(record: dict, kind: str) -> bool:
    if (not isinstance(record, dict) or record.get('status') != 'measured' or record.get('kind') != kind
            or record.get('view') not in ('plan', 'profile', 'body')
            or not _id(record.get('region')) or record.get('method') not in METHODS
            or not isinstance(record.get('source_sha256'), str)
            or re.fullmatch('[a-f0-9]{64}', record['source_sha256']) is None
            or not record.get('entity_ids')):
        return False
    value = record.get('value')
    if kind == 'length':
        return _finite(value) and 0 < value <= 1000
    if kind == 'interval':
        return (isinstance(value, list) and len(value) == 2 and all(_finite(v) for v in value)
                and -1000 <= value[0] < value[1] <= 1000)
    if kind == 'outline':
        return (isinstance(value, list) and 3 <= len(value) <= 4096
                and all(isinstance(p, list) and len(p) == 2
                        and all(_finite(v) and abs(v) <= 1000 for v in p) for p in value))
    if kind == 'sections':
        return isinstance(value, list) and 3 <= len(value) <= 256
    return False


def resolve_program(program: dict, measurements: dict) -> list[dict]:
    validate_program(program)
    resolved = []
    for component in program['components']:
        values, evidence, failures = {}, {}, []
        for argument, kind in OPERATIONS[component['op']].items():
            reference = component['args'][argument]
            if kind == 'component':
                values[argument] = reference
                continue
            record = measurements.get(reference, {})
            if not _measurement_ok(record, kind):
                failures.append(f'{reference}: {record.get("reason", "missing or invalid measurement")}')
                continue
            expected_view = ('body' if kind == 'sections' else
                             'profile' if kind == 'outline' and component['op'] == 'appendage' else
                             'plan' if kind == 'outline' else
                             'profile' if argument == 'height' else None)
            if expected_view is not None and record['view'] != expected_view:
                failures.append(f'{reference}: expected {expected_view} measurement')
                continue
            values[argument] = record['value']
            evidence[reference] = record
        primary = component['args']['sections' if component['op'] == 'hull' else 'outline']
        if primary in evidence:
            record = evidence[primary]
            if any(record[key] != component['source'][key] for key in ('view', 'region', 'method')):
                failures.append('primary measurement does not match named source')
        resolved.append({'id': component['id'], 'op': component['op'], 'source': component['source'],
                         'status': 'draft_guess' if failures else 'measured_draft',
                         'reason': '; '.join(failures) if failures else 'Component identity needs human review',
                         'geometry': None if failures else values, 'provenance': evidence})
    return resolved


def check_views(cuts: dict, drawings: dict, *, veto: bool = False) -> dict:
    """Symmetric sampled distance. Missing/empty/nonfinite evidence blocks.

    Inputs must be independently extracted STEP cuts and drawing traces in
    metres. Self-comparison is useful only in tests, never as source evidence.
    """
    from scipy.spatial import cKDTree

    missing, distances = [], {}
    for view in ('profile', 'plan', 'body'):
        a, b = np.asarray(cuts.get(view, []), dtype=float), np.asarray(drawings.get(view, []), dtype=float)
        if (a.ndim != 2 or b.ndim != 2 or a.shape[1:] != (2,) or b.shape[1:] != (2,)
                or not len(a) or not len(b) or not np.isfinite(a).all() or not np.isfinite(b).all()):
            missing.append(view)
            continue
        distances[view] = float(max(cKDTree(a).query(b)[0].max(), cKDTree(b).query(a)[0].max()))
    blocked = bool(missing or veto or any(d > VIEW_DISTANCE_M for d in distances.values()))
    return {'status': 'blocked' if blocked else 'checked_draft', 'missing': missing,
            'maximum_distance_m': distances, 'draft_tolerance_m': VIEW_DISTANCE_M, 'reviewer_veto': veto}


def step_cuts(path: Path, planes: dict) -> dict:
    """Reimport STEP and cut profile y, plan z and body x planes (metres)."""
    import cadquery as cq
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Section
    from OCP.gp import gp_Pln, gp_Pnt, gp_Dir

    shape = cq.importers.importStep(str(path)).val()
    results = {}
    for view, offset in planes.items():
        if view not in ('profile', 'plan', 'body') or not _finite(offset):
            raise ValueError('invalid cross-view plane')
        normal = {'profile':(0,1,0),'plan':(0,0,1),'body':(1,0,0)}[view]
        origin = [v*offset*1000 for v in normal]
        section = BRepAlgoAPI_Section(shape.wrapped, gp_Pln(gp_Pnt(*origin),gp_Dir(*normal)), False)
        section.Build()
        if not section.IsDone():
            results[view] = []
            continue
        points = []
        for edge in cq.Shape.cast(section.Shape()).Edges():
            # 10 mm sampled spacing bounds audit work and preserves small features.
            count = min(4096, max(2, math.ceil(edge.Length()/10)+1))
            for p in edge.sample(count)[0]:
                q = {'profile':(p.x,p.z),'plan':(p.x,p.y),'body':(p.y,p.z)}[view]
                points.append([v/1000 for v in q])
        if len(points) > 200_000:
            raise ValueError('cross-view sampling budget exceeded')
        results[view] = points
    return results


def _prism(outline, interval, plane='XY'):
    import cadquery as cq
    low, high = interval
    shape = cq.Workplane(plane).polyline(outline).close().extrude(high - low).val()
    return shape.translate((0, 0, low) if plane == 'XY' else (0, high, 0))


def execute(program: dict, measurements: dict, out: Path, *, audit=None, veto=False) -> dict:
    """Trusted worker entry. ``out`` is host-selected, never program-selected."""
    import cadquery as cq

    components = resolve_program(program, measurements)
    shapes = {}
    out.mkdir(parents=True, exist_ok=True)
    for component in components:
        values = component.pop('geometry')
        if values is None:
            component['built'] = False
            continue
        try:
            op = component['op']
            if op == 'hull':
                from .geometry import build_region_hull
                shape, _ = build_region_hull(values['sections'])
                shape = shape.scale(0.001)  # Existing hull pipeline uses millimetres.
            elif op == 'appendage':
                shape = _prism(values['outline'], values['span'], 'XZ')
            elif op == 'bulwark':
                low, high = values['height']
                wire = cq.Workplane('XY').polyline(values['outline']).close()
                outer = wire.extrude(high - low).val().translate((0, 0, low))
                inner = (cq.Workplane('XY').polyline(values['outline']).close()
                         .offset2D(-values['thickness']).extrude(high - low).val().translate((0, 0, low)))
                shape = outer.cut(inner)
            else:
                shape = _prism(values['outline'], values['height'])
                if op == 'opening':
                    target = values['target']
                    if target not in shapes:
                        raise ValueError('opening target was not built')
                    changed = shapes[target].cut(shape)
                    if not changed.isValid() or not changed.Solids() or changed.Volume() <= 0:
                        raise ValueError('opening leaves an empty or invalid target')
                    shapes[target] = changed
                    component['role'] = 'subtraction_tool_not_material'
            if not shape.isValid() or not shape.Solids() or shape.Volume() <= 0:
                raise ValueError('invalid or empty CAD solid')
            shapes[component['id']] = shape
            component['built'] = True
        except Exception as exc:
            component.update(status='draft_guess', built=False, reason=f'{type(exc).__name__}: {exc}')
    material = []
    for component in components:
        if not component['built']:
            continue
        shape = shapes[component['id']]
        box = shape.BoundingBox()
        component.update(bbox_m={'min': [box.xmin, box.ymin, box.zmin], 'max': [box.xmax, box.ymax, box.zmax]},
                         volume_m3=shape.Volume())
        # Language coordinates and the kernel are metres here. STEP records those
        # model units as mm, so export a scaled copy for interoperable SI geometry.
        cq.exporters.export(shape.scale(1000), str(out / f'{component["id"]}.step'))
        if component['op'] != 'opening':
            material.append(shape)
    if material:
        cq.exporters.export(cq.Compound.makeCompound(material).scale(1000), str(out / 'model-draft.step'))
    cross_view = check_views({}, {}, veto=veto)
    if material and audit:
        import hashlib
        step = out / 'model-draft.step'
        cuts = step_cuts(step, audit['planes'])
        cross_view = check_views(cuts, audit.get('drawings', {}), veto=veto)
        cross_view.update(step_sha256=hashlib.sha256(step.read_bytes()).hexdigest(),
                          cut_points={view:len(points) for view,points in cuts.items()},
                          source_provenance=audit.get('provenance', {}))
    report = {'schema': 'ship-cad-result/v1', 'status': 'draft_only', 'engineering_approved': False,
              'readiness_authority': 'rust_controller_only', 'components': components,
              'cross_view': cross_view}
    (out / 'provenance.json').write_text(json.dumps(report, indent=2) + '\n')
    return report
