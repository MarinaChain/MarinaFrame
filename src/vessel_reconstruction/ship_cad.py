"""Restricted ship programs. This module never evaluates model code.

The drawing measurement harness supplies the measurement map. Since the
whole-vessel plan (docs/plans/2026-11-09-whole-vessel-scope.md), gaps are
filled, not left unbuilt: an argument can also be an inline value with a
source label (``ai_inferred`` or ``guessed``), and the host can give a
labelled guess for each measurement reference. A program still cannot run
code, choose an output path, or set review state.
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
METHODS = {'closed_outline', 'parallel_lines', 'body_plan_regions', 'dimension_text',
           'enclosed_region', 'profile_levels'}
SOURCE_VIEWS = ('plan', 'profile', 'body')
# A component source the program declared wrongly; its geometry still builds (triage_program).
UNSPECIFIED = 'unspecified'
# Source labels of values that are not read from drawing ink.
FILLED_SOURCES = ('ai_inferred', 'guessed')
INLINE_FIELDS = {'value', 'source', 'basis'}
MAX_BASIS_CHARS = 400


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


def _check_header(program: dict) -> None:
    _keys(program, {'schema', 'components'}, 'program')
    if program['schema'] != SCHEMA:
        raise ValueError('unknown ship language version')
    components = program['components']
    if not isinstance(components, list) or not 1 <= len(components) <= MAX_COMPONENTS:
        raise ValueError('ship component count')


class SourceMetadataError(ValueError):
    """Only the source view or method value is unknown; the geometry arguments are valid."""


def _check_component(component, seen: set) -> None:
    _keys(component, {'id', 'op', 'source', 'args'}, 'component')
    name, op = component['id'], component['op']
    if not _id(name) or name in seen or not isinstance(op, str) or op not in OPERATIONS:
        raise ValueError('invalid component id or operation')
    _keys(component['source'], {'view', 'region', 'method'}, 'source')
    source = component['source']
    if not all(isinstance(source[key], str) and _id(source[key]) for key in ('view', 'region', 'method')):
        raise ValueError(f'component {name!r}: source values must be short identifiers')
    _keys(component['args'], OPERATIONS[op], 'arguments')
    for key, reference in component['args'].items():
        kind = OPERATIONS[op][key]
        if isinstance(reference, dict) and kind not in ('component', 'sections'):
            _validate_inline(reference, kind)
            continue
        if not _id(reference):
            raise ValueError('dimensions must be measurement references or labelled inline values')
        if key == 'target' and reference not in seen:
            raise ValueError('opening target must be an earlier component')
    if (source['view'] not in SOURCE_VIEWS + (UNSPECIFIED,)
            or (source['method'] not in METHODS and source['method'] != UNSPECIFIED)):
        # Name the component and the allowed values: a model can only fix what it is told.
        raise SourceMetadataError(f'component {name!r}: unknown source view or method {source!r}; view is '
                                  f'plan, profile or body; method is one of {sorted(METHODS)}')


def validate_program(program: dict) -> dict:
    """Strict check: any invalid component rejects the program (``triage_program`` does not)."""
    _check_header(program)
    seen = set()
    for component in program['components']:
        _check_component(component, seen)
        seen.add(component['id'])
    return program


def triage_program(program: dict) -> tuple[dict, list[dict], dict]:
    """Keep every buildable component; never reject the whole program for one component.

    Founder rule: do not make builds fail. A component with only unknown source metadata
    (view or method) is kept with its source marked ``unspecified`` and builds as a labelled
    ``draft_guess``. A component with invalid geometry arguments is left out and reported
    as unbuilt with the reason. The program header (schema, component list) stays strict.
    Returns the buildable program, the unbuilt components and the source notes by id.
    """
    _check_header(program)
    kept, rejected, notes, seen = [], [], {}, set()
    for component in program['components']:
        try:
            _check_component(component, seen)
            kept.append(component)
        except SourceMetadataError as exc:
            repaired = dict(component, source={'view': UNSPECIFIED, 'region': component['source']['region'],
                                               'method': UNSPECIFIED})
            _check_component(repaired, seen)
            notes[component['id']] = str(exc)[:MAX_BASIS_CHARS]
            kept.append(repaired)
        except ValueError as exc:
            name = component.get('id') if isinstance(component, dict) else None
            rejected.append({'id': name if _id(name) else f'component_{len(kept) + len(rejected) + 1}',
                             'op': component.get('op') if isinstance(component, dict) else None,
                             'status': 'draft_guess', 'built': False, 'source_labels': {},
                             'reason': f'not built: {str(exc)[:MAX_BASIS_CHARS]}'})
            continue
        seen.add(component['id'])
    if not kept:
        raise ValueError('no buildable component: ' + '; '.join(r['reason'] for r in rejected)[:2000])
    return {'schema': program['schema'], 'components': kept}, rejected, notes


def _finite(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _validate_inline(item, kind):
    """An inline value must carry its source label and a short basis."""
    _keys(item, INLINE_FIELDS, 'inline value')
    if item['source'] not in FILLED_SOURCES:
        raise ValueError('inline value source must be ai_inferred or guessed')
    if not isinstance(item['basis'], str) or not 0 < len(item['basis']) <= MAX_BASIS_CHARS:
        raise ValueError('inline value needs a short basis text')
    if not _value_ok(item['value'], kind):
        raise ValueError(f'inline value is not a valid {kind}')


def _guess_ok(record, kind) -> bool:
    return (isinstance(record, dict) and record.get('kind') == kind
            and record.get('source') in FILLED_SOURCES and isinstance(record.get('basis'), str)
            and _value_ok(record.get('value'), kind))


def _measurement_ok(record: dict, kind: str) -> bool:
    if (not isinstance(record, dict) or record.get('status') != 'measured' or record.get('kind') != kind
            or record.get('view') not in ('plan', 'profile', 'body')
            or not _id(record.get('region')) or record.get('method') not in METHODS
            or not isinstance(record.get('source_sha256'), str)
            or re.fullmatch('[a-f0-9]{64}', record['source_sha256']) is None
            or not record.get('entity_ids')):
        return False
    return _value_ok(record.get('value'), kind)


def _value_ok(value, kind: str) -> bool:
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


def _expected_view(op: str, argument: str, kind: str) -> str | None:
    if kind == 'sections':
        return 'body'
    if kind == 'outline':
        return 'profile' if op == 'appendage' else 'plan'
    return 'profile' if argument == 'height' else None


def _measurement_problem(op, argument, kind, reference, record) -> str | None:
    """Return why a measurement cannot be used, or None when it is traced evidence."""
    if not _measurement_ok(record, kind):
        return f'{reference}: {record.get("reason", "missing or invalid measurement")}'
    expected_view = _expected_view(op, argument, kind)
    if expected_view is not None and record['view'] != expected_view:
        return f'{reference}: expected {expected_view} measurement'
    return None


def resolve_program(program: dict, measurements: dict, guesses: dict | None = None) -> list[dict]:
    """Resolve each argument to traced evidence, an inline value or a host guess.

    Source labels: ``traced`` (measured drawing ink), ``ai_inferred`` (a model
    value) and ``guessed`` (a code gap fill). A component that uses any filled
    value is built with status ``draft_guess``. A component stays unbuilt only
    when an argument has neither a usable measurement nor a valid guess.
    """
    validate_program(program)
    guesses = guesses or {}
    resolved = []
    for component in program['components']:
        op = component['op']
        values, evidence, labels, failures, fills = {}, {}, {}, [], []
        for argument, kind in OPERATIONS[op].items():
            reference = component['args'][argument]
            if kind == 'component':
                values[argument] = reference
                continue
            if isinstance(reference, dict):
                values[argument] = reference['value']
                labels[argument] = reference['source']
                evidence[argument] = {'source': reference['source'], 'basis': reference['basis']}
                fills.append(f'{argument}: {reference["source"]}: {reference["basis"]}')
                continue
            record = measurements.get(reference, {})
            problem = _measurement_problem(op, argument, kind, reference, record)
            if problem is None:
                values[argument] = record['value']
                labels[argument] = 'traced'
                evidence[reference] = record
                continue
            guess = guesses.get(reference)
            if not _guess_ok(guess, kind):
                failures.append(problem)
                continue
            values[argument] = guess['value']
            labels[argument] = guess['source']
            evidence[reference] = {'source': guess['source'], 'basis': guess['basis'],
                                   'entity_ids': guess.get('entity_ids', []), 'replaces': problem}
            fills.append(f'{reference}: {guess["source"]}: {guess["basis"]}')
        primary_argument = 'sections' if op == 'hull' else 'outline'
        primary = component['args'][primary_argument]
        unspecified = UNSPECIFIED in (component['source']['view'], component['source']['method'])
        if unspecified:
            fills.append('source metadata not recognised; built from its values')
        elif labels.get(primary_argument) == 'traced':
            record = evidence[primary]
            if any(record[key] != component['source'][key] for key in ('view', 'region', 'method')):
                failures.append('primary measurement does not match named source')
        if failures:
            status, reason = 'draft_guess', '; '.join(failures)
        elif fills:
            status, reason = 'draft_guess', '; '.join(fills)
        else:
            status, reason = 'measured_draft', 'Component identity needs human review'
        resolved.append({'id': component['id'], 'op': op, 'source': component['source'],
                         'status': status, 'reason': reason, 'source_labels': labels,
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
    from OCP.gp import gp_Dir, gp_Pln, gp_Pnt

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


def _straight_part(op, values):
    """A part as its plan outline extruded straight up (used when no hull side is given)."""
    import cadquery as cq

    if op != 'bulwark':
        return _prism(values['outline'], values['height'])
    low, high = values['height']
    outer = cq.Workplane('XY').polyline(values['outline']).close().extrude(high - low).val().translate((0, 0, low))
    inner = (cq.Workplane('XY').polyline(values['outline']).close()
             .offset2D(-values['thickness']).extrude(high - low).val().translate((0, 0, low)))
    return outer.cut(inner)


# Parts above the hull that follow the hull side when the host gives one (superstructure.py).
SHAPED_OPS = ('deck', 'bulwark', 'deckhouse')


def _hull_side(detail):
    """The host's hull side, or None (then parts are straight extrusions, as before)."""
    from .superstructure import HullSide

    item = (detail or {}).get('hull_side')
    if not isinstance(item, dict) or not isinstance(item.get('value'), dict):
        return None
    try:
        return HullSide.from_dict(item['value'])
    except (KeyError, TypeError, ValueError):
        return None


def _shaped_part(component, values, hull, detail):
    """Build a part that follows the hull; label every detail value it used.

    Happy path: when the shaped build fails, the straight part is built and the reason is kept.
    """
    from .geometry import precise_volume_mm3
    from .superstructure import build_shaped

    part_detail = (detail.get('parts') or {}).get(component['id'], {})
    try:
        shape, report = build_shaped(component['id'], component['op'], values, hull, part_detail)
        # The default volume integration can even be negative on smooth B-spline walls.
        if not shape.isValid() or precise_volume_mm3(shape) <= 0:
            raise ValueError('invalid shaped solid')
    except Exception as exc:  # noqa: BLE001 - the straight part is the fallback
        component['shape'] = 'straight_extrusion'
        component['reason'] = f'{component["reason"]}; hull-following shape not built ({type(exc).__name__}: {exc})'
        return _straight_part(component['op'], values)
    component['shape'] = 'follows_hull_side'
    component['walls'] = report['walls']
    component['check_items'] = report['check_items']
    if report['windows_cut']:
        component['windows_cut'] = report['windows_cut']
    used = {'hull_side': detail['hull_side']} | {key: part_detail[key] for key in report['detail_used']}
    guessed = []
    for key, item in used.items():
        source = item.get('source', 'guessed')
        component['source_labels'][key] = source
        component['provenance'][key] = {'source': source, 'basis': str(item.get('basis', ''))[:MAX_BASIS_CHARS]}
        if source in FILLED_SOURCES:
            guessed.append(f'{key}: {source}: {item.get("basis", "")}')
    if guessed:
        reason = component['reason'] if component['status'] == 'draft_guess' else ''
        component.update(status='draft_guess', reason='; '.join([r for r in [reason] if r] + guessed))
    return shape


def execute(program: dict, measurements: dict, out: Path, *, audit=None, veto=False,
            guesses: dict | None = None, detail: dict | None = None) -> dict:
    """Trusted worker entry. ``out`` is host-selected, never program-selected.

    ``detail`` (optional, host data): ``hull_side`` (a labelled ``superstructure.HullSide`` grid)
    and ``parts`` (labelled detail values by component id). With a hull side, decks, bulwarks
    and deckhouses follow the hull; without it they are straight extrusions.
    """
    import cadquery as cq

    from .geometry import precise_volume_mm3

    hull = _hull_side(detail)
    buildable, unbuilt, source_notes = triage_program(program)
    components = resolve_program(buildable, measurements, guesses)
    arguments = {c['id']: c['args'] for c in buildable['components']}
    for component in components:
        # The app shows each value (geometry) and which reference or inline value gave it (args).
        component['args'] = arguments[component['id']]
        if component['id'] in source_notes:
            component['reason'] = f'{component["reason"]}; {source_notes[component["id"]]}'
    shapes = {}
    out.mkdir(parents=True, exist_ok=True)
    for component in components:
        values = component['geometry']
        if component['op'] == 'hull' and values is not None:
            # Station sections are large; the result keeps their count, not the rows.
            component['geometry'] = {'sections': f'{len(values["sections"])} stations'}
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
            elif op in SHAPED_OPS and hull is not None:
                shape = _shaped_part(component, values, hull, detail)
            elif op == 'bulwark':
                shape = _straight_part(op, values)
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
            if not shape.isValid() or not shape.Solids() or precise_volume_mm3(shape) <= 0:
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
        # Adaptive integration: the default volume is about 1 % off on smooth B-spline walls.
        component.update(bbox_m={'min': [box.xmin, box.ymin, box.zmin], 'max': [box.xmax, box.ymax, box.zmax]},
                         volume_m3=precise_volume_mm3(shape))
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
              'readiness_authority': 'rust_controller_only', 'components': components + unbuilt,
              'cross_view': cross_view}
    (out / 'provenance.json').write_text(json.dumps(report, indent=2) + '\n')
    return report
