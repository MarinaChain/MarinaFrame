"""Gunnerus appendages from the GA (step 1b, development case): azimuth thrusters and skeg fins.

Plan: docs/plans/2026-11-09-whole-vessel-scope.md, section 3.7 (metrics fixed before the build).
Each appendage is a ship-cad ``appendage``: a side outline in the profile (x, z), extruded over a
transverse span (y). The selectors below are what a person read from the GA; code snaps them to
drawn ink. What the drawing does not give is a labelled guess (source ``guessed``):

- Azimuth thrusters (two, aft): side outline = convex hull of the thruster block linework below
  the drawn stern bottom (profile); centre y = the thruster block on the tank-top plan; the
  underwater breadth is not drawn (guessed).
- Skeg fins (under the aft twin skegs): side outline = the lowest S0CO2 linework under the
  profile keel line, closed by that line; the breadth is not drawn (guessed). The aft body has
  twin skegs and a centre tunnel. The profile keel line is the side view of the twin-skeg bottom,
  and the azimuth thrusters sit at the aft end of the twin skegs, so each fin is placed at the
  thruster centre y (development run 2; run 1 put one fin on the centreline, under the tunnel).
- Rudder: none drawn (azimuth propulsion). The bow thruster is a tunnel inside the hull (an
  opening, not an appendage) and the drop keel is marked optional: both are not built here.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

# Profile and plan calibration of the GA (drawing mm): frame 0 and baseline (as whole_vessel.py).
FRAME0_X = 4973.089172
PROFILE_BASE_Y = 47493.95
# Person-read selectors (block names and layers in the GA DXF).
THRUSTER_PROFILE_BLOCK = 'A$C18113CC1'
THRUSTER_PLAN_BLOCK = 'A$C433C2106'
FRAME_RULER_BLOCK = 'A$C64097268'
# Linework sample spacing (drawing mm) for the thruster outline.
SAMPLE_SPACING_MM = 10.0
NON_OUTLINE_LINETYPES = {'CENTER', 'CENTER2', 'PHANTOM', 'PHANTOM2', 'HIDDEN', 'DASHED'}
# The tank-top plan is the lowest plan on the sheet (drawing y below this value).
TANK_TOP_PLAN_MAX_Y = 11000.0
STERN_BOTTOM_LAYER = 'S0CO3'
SKEG_LAYER = 'S0CO2'
KEEL_LAYER = 'S0CO3'
# Skeg window in ship metres (x from frame 0, z from the profile baseline).
SKEG_X_RANGE = (1.0, 9.0)
SKEG_Z_RANGE = (-1.2, 0.0)
# Points closer than this in x are one station of the skeg's lower edge (two drawn lines 15 mm apart).
SKEG_X_MERGE_M = 0.05
# A lower-edge point less than this below the keel line is on the keel line (the skeg tip).
SKEG_MIN_DEPTH_M = 0.005
# Gap fills (source "guessed"): the GA has no underwater breadth for these parts.
THRUSTER_HALF_BREADTH_M = 0.25
SKEG_BREADTH_M = 0.30
APPENDAGE_IDS = ('azimuth_ps', 'azimuth_sb', 'skeg_ps', 'skeg_sb')
LABELS = {'azimuth_ps': 'Azimuth thruster, port', 'azimuth_sb': 'Azimuth thruster, starboard',
          'skeg_ps': 'Skeg fin, port twin skeg', 'skeg_sb': 'Skeg fin, starboard twin skeg'}


def _ship(point) -> list[float]:
    return [round((point[0] - FRAME0_X) / 1000.0, 4), round((point[1] - PROFILE_BASE_Y) / 1000.0, 4)]


def _insert_points(insert) -> np.ndarray:
    """Drawing points (mm) of the exploded block linework."""
    from ezdxf import path as ezpath

    points = []
    for entity in insert.virtual_entities():
        # Centre lines and phantom lines (shaft axis, steering range) are not material outline.
        if entity.dxftype() == 'TEXT' or str(entity.dxf.get('linetype', '')).upper() in NON_OUTLINE_LINETYPES:
            continue
        try:
            drawn = ezpath.make_path(entity)
        except (TypeError, ValueError):
            continue
        for sub in drawn.sub_paths():
            vertices = np.array([(vertex.x, vertex.y) for vertex in sub.flattening(1.0)])
            if len(vertices) == 1:
                points.extend(vertices)
            # Sample each segment densely so a cut at the hull bottom keeps the crossing points.
            for a, b in zip(vertices, vertices[1:]):
                count = max(2, int(np.ceil(np.linalg.norm(b - a) / SAMPLE_SPACING_MM)) + 1)
                points.extend(a + (b - a) * t for t in np.linspace(0.0, 1.0, count))
    return np.asarray(points, dtype=float)


def _polyline_points(entity) -> list[tuple[float, float]]:
    if entity.dxftype() == 'LWPOLYLINE':
        return [(p[0], p[1]) for p in entity.get_points()]
    if entity.dxftype() == 'LINE':
        return [(entity.dxf.start.x, entity.dxf.start.y), (entity.dxf.end.x, entity.dxf.end.y)]
    return []


def _convex_hull(points: np.ndarray) -> list[list[float]]:
    from scipy.spatial import ConvexHull

    hull = ConvexHull(points)
    return [[round(float(x), 4), round(float(z), 4)] for x, z in points[hull.vertices]]


def stern_bottom(msp) -> tuple[np.ndarray, list[str]]:
    """The drawn stern bottom line under the thrusters (ship m, sorted by x): an S0CO3 polyline above 1.5 m."""
    best, handle = None, None
    for entity in msp.query(f'LWPOLYLINE[layer=="{STERN_BOTTOM_LAYER}"]'):
        points = np.array([_ship(p) for p in _polyline_points(entity)])
        if len(points) >= 3 and points[:, 0].min() <= 0.0 <= points[:, 0].max() and 1.5 < points[:, 1].min() < 3.0:
            if best is None or len(points) > len(best):
                best, handle = points[np.argsort(points[:, 0])], entity.dxf.handle
    return best, [handle] if handle else []


def thruster_outline(msp) -> tuple[list[list[float]], list[str], str]:
    """Side outline of the thruster below the drawn stern bottom (convex hull of its block linework)."""
    insert = next(e for e in msp.query('INSERT') if e.dxf.name == THRUSTER_PROFILE_BLOCK)
    points = np.array([_ship(p) for p in _insert_points(insert)])
    bottom, bottom_ids = stern_bottom(msp)
    limit = np.interp(points[:, 0], bottom[:, 0], bottom[:, 1])
    below = points[points[:, 1] <= limit]
    basis = (f'convex hull of the thruster block linework ({THRUSTER_PROFILE_BLOCK}) below the drawn stern '
             f'bottom; {len(below)} points')
    return _convex_hull(below), [insert.dxf.handle] + bottom_ids, basis


def thruster_centres(msp) -> tuple[list[float], list[str]]:
    """Transverse centres (m, port positive) of the thruster blocks on the tank-top plan."""
    rulers = [e for e in msp.query('INSERT') if e.dxf.name == FRAME_RULER_BLOCK
              and e.dxf.insert.y < TANK_TOP_PLAN_MAX_Y]
    centreline = rulers[0].dxf.insert.y
    blocks = [e for e in msp.query('INSERT') if e.dxf.name == THRUSTER_PLAN_BLOCK
              and e.dxf.insert.y < TANK_TOP_PLAN_MAX_Y]
    centres = sorted(round((e.dxf.insert.y - centreline) / 1000.0, 4) for e in blocks)
    return centres, [e.dxf.handle for e in blocks] + [rulers[0].dxf.handle]


def skeg_outline(msp) -> tuple[list[list[float]], list[str]] | tuple[None, list]:
    """Skeg side outline: the lowest S0CO2 edge under the aft keel, closed by the keel line."""
    lower, ids = [], []
    for entity in msp.query(f'LWPOLYLINE[layer=="{SKEG_LAYER}"]'):
        points = [_ship(p) for p in _polyline_points(entity)]
        inside = [p for p in points if SKEG_X_RANGE[0] <= p[0] <= SKEG_X_RANGE[1] and SKEG_Z_RANGE[0] <= p[1] <= SKEG_Z_RANGE[1]]
        if len(inside) == len(points):
            lower.extend(points)
            ids.append(entity.dxf.handle)
    keel = None
    for entity in msp.query(f'LINE[layer=="{KEEL_LAYER}"]'):
        a, b = sorted((_ship(p) for p in _polyline_points(entity)), key=lambda p: p[0])
        inside = all(SKEG_Z_RANGE[0] <= p[1] <= SKEG_Z_RANGE[1] for p in (a, b))
        if inside and SKEG_X_RANGE[0] - 2.0 <= a[0] <= SKEG_X_RANGE[0] and SKEG_X_RANGE[1] - 1.0 <= b[0] <= SKEG_X_RANGE[1] + 1.0:
            keel, keel_id = (a, b), entity.dxf.handle
    if not lower or keel is None:
        return None, []
    edge = []
    for x, z in sorted(lower):
        if edge and x - edge[-1][0] <= SKEG_X_MERGE_M:
            edge[-1] = [edge[-1][0], min(edge[-1][1], z)]
        else:
            edge.append([x, z])

    def keel_z(x: float) -> float:
        (x0, z0), (x1, z1) = keel
        return round(z0 + (z1 - z0) * (x - x0) / (x1 - x0), 4)

    # Forward, the lower edge runs into the keel line: the skeg ends at the first point on it.
    below = [index for index, (x, z) in enumerate(edge) if keel_z(x) - z > SKEG_MIN_DEPTH_M]
    last = below[-1]
    tip = edge[last + 1] if last + 1 < len(edge) else edge[last]
    outline = [[edge[0][0], keel_z(edge[0][0])]] + edge[:last + 1] + [[tip[0], keel_z(tip[0])]]
    return outline, ids + [keel_id]


def add_appendages(inputs: dict, sources: Path, ga_file: str) -> dict:
    """Add the appendage components, measurements and guesses to step 1 ``inputs`` (in place)."""
    from vessel_reconstruction.dxf_documents import read_document

    msp = read_document(sources / ga_file).modelspace()
    sha = inputs['source']['sha256']
    program, measurements, guesses = inputs['program'], inputs['measurements'], inputs['guesses']

    def outline_measurement(region, outline, entity_ids, basis):
        measurements[f'{region}_outline'] = {
            'status': 'measured', 'kind': 'outline', 'view': 'profile', 'region': region,
            'method': 'enclosed_region', 'source_sha256': sha, 'value': outline, 'entity_ids': entity_ids,
            'basis': basis}

    def add(region, span, span_basis):
        guesses[f'{region}_span'] = {'kind': 'interval', 'value': span, 'source': 'guessed', 'basis': span_basis}
        program['components'].append({'id': region, 'op': 'appendage',
                                      'source': {'view': 'profile', 'region': region, 'method': 'enclosed_region'},
                                      'args': {'outline': f'{region}_outline', 'span': f'{region}_span'}})

    outline, outline_ids, basis = thruster_outline(msp)
    centres, centre_ids = thruster_centres(msp)
    for region, centre in (('azimuth_ps', max(centres)), ('azimuth_sb', min(centres))):
        outline_measurement(region, outline, outline_ids, basis)
        add(region, [round(centre - THRUSTER_HALF_BREADTH_M, 4), round(centre + THRUSTER_HALF_BREADTH_M, 4)],
            f'centre y {centre} m from the thruster block on the tank-top plan ({", ".join(centre_ids)}); '
            f'underwater breadth not drawn: half breadth guessed {THRUSTER_HALF_BREADTH_M} m')
    skeg, skeg_ids = skeg_outline(msp)
    if skeg:
        for region, centre in (('skeg_ps', max(centres)), ('skeg_sb', min(centres))):
            outline_measurement(region, skeg, skeg_ids,
                                'lowest S0CO2 linework under the profile keel line, closed by that line')
            add(region, [round(centre - SKEG_BREADTH_M / 2, 4), round(centre + SKEG_BREADTH_M / 2, 4)],
                f'under the twin skeg at the thruster centre y {centre} m (tank-top plan); fin breadth not '
                f'drawn: guessed {SKEG_BREADTH_M} m')
    inputs['appendages'] = {'ids': [c for c in APPENDAGE_IDS if any(p['id'] == c for p in program['components'])],
                            'not_built': {'rudder': 'none drawn (azimuth propulsion)',
                                          'bow_thruster': 'tunnel inside the hull: an opening, not an appendage',
                                          'drop_keel': 'marked optional on the GA'}}
    return inputs
