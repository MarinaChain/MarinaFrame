"""Method check of the tank tables on exact OCX compartment solids (docs/TANKS_V1.md, T1 and T3).

Each OCX ``Compartment`` is a closed set of ``CompartmentFace`` items: a NURBS surface trimmed by
a boundary curve (NURBS, often degree 1). The faces are built and sewn into an OpenCASCADE solid
(the exact solid). Then:

- T1: our sounding table (the solid tessellated, then ``vessel_reconstruction.tanks``) at a fixed
  interval against the direct volume at each level (Boolean common of the exact solid with the
  half-space below the level, ``GProp`` volume);
- T3: our centroid and volume at 100 % fill against ``GProp`` of the exact solid; the centre of
  gravity and volume printed in the file (``CompartmentProperties``) are reported beside them.

Usage (the OCX samples are third-party data; outputs go to git-ignored ``work/``)::

    PYTHONPATH=src:. python -m benchmarks.ocx.compartment_check --out work/tanks/ocx-check.json \\
        work/sources/ocx_models_platform/models/D-VLCC_1-HOLD-OCX-simple_v3.3docx \\
        work/sources/ocx_models_ocxtools/tests/data/NAPA-OCX_M9.3docx
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
from pathlib import Path
import time
import xml.etree.ElementTree as ElementTree

import numpy as np

from vessel_reconstruction import tanks

T1_INTERVAL_M = 0.10
T1_TARGET = 0.005
# T1 relative errors are taken where the direct volume is at least this share of the full volume.
T1_MIN_FILL = 0.01
T3_TARGET_M = 0.02
T3_VOLUME_TARGET = 0.001
# Tessellation of the exact solid for our tables: chord deviation as a share of the solid's
# bounding-box diagonal, and angle (rad). The first run used a fixed 2 mm chord deviation: the volume
# then came out 0.16 % low on the M9 tanks (T1 1.0 %); the error is the tessellation, not the level
# integration (it falls to 0.04 % at 0.1 mm), so the deviation scales with the solid.
MESH_DEFLECTION_SHARE = 1e-5
MESH_ANGLE_RAD = 0.1
# Sewing tolerance (m): degree-1 boundary curves on a curved face are chords of the true edge.
SEWING_TOLERANCE_M = 0.01
# Elements outside compartments are skipped while parsing (the VLCC file is 22 MB of structure).
SKIPPED_ELEMENTS = ('Plate', 'Stiffener', 'Bracket', 'Pillar', 'Panel', 'EdgeReinforcement', 'Seam')


def _tag(element) -> str:
    return element.tag.split('}')[-1]


def _child(element, name):
    return next((c for c in element if _tag(c) == name), None)


def _floats(text: str) -> list[float]:
    return [float(v) for v in text.split()]


@dataclass
class OcxCompartment:
    name: str
    purpose: str | None
    faces: list  # list of (surface element, boundary element)
    printed_volume_m3: float | None
    printed_cog_m: tuple[float, float, float] | None


def read_compartments(path: Path) -> list[OcxCompartment]:
    compartments = []
    for _, element in ElementTree.iterparse(path, events=('end',)):
        tag = _tag(element)
        if tag in SKIPPED_ELEMENTS:
            element.clear()
            continue
        if tag != 'Compartment':
            continue
        purpose = next((v for k, v in element.attrib.items() if k.endswith('compartmentPurpose')), None)
        volume = cog = None
        properties = _child(element, 'CompartmentProperties')
        if properties is not None:
            for item in properties:
                if _tag(item) == 'Volume':
                    volume = float(item.get('numericvalue'))
                if _tag(item) == 'CenterOfGravity':
                    cog = tuple(_floats(item.get('coordinates')))
        faces = []
        for face in element:
            if _tag(face) != 'CompartmentFace':
                continue
            surface = list(_child(face, 'UnboundedGeometry'))[0]
            faces.append((surface, _child(face, 'FaceBoundaryCurve')))
        compartments.append(OcxCompartment(element.get('name'), purpose, faces, volume, cog))
    return compartments


# --- OpenCASCADE construction --------------------------------------------------------------

def _array1(values, kind):
    from OCP.TColStd import TColStd_Array1OfInteger, TColStd_Array1OfReal

    array = (TColStd_Array1OfReal if kind is float else TColStd_Array1OfInteger)(1, len(values))
    for index, value in enumerate(values, start=1):
        array.SetValue(index, kind(value))
    return array


def _knots(vector: list[float]) -> tuple[list[float], list[int]]:
    """Flat knot vector -> distinct knots and multiplicities."""
    knots, multiplicities = [], []
    for value in vector:
        if knots and abs(value - knots[-1]) < 1e-12:
            multiplicities[-1] += 1
        else:
            knots.append(value)
            multiplicities.append(1)
    return knots, multiplicities


def _control_points(element) -> tuple[list[tuple[float, float, float]], list[float]]:
    points, weights = [], []
    for point in _child(element, 'ControlPtList'):
        points.append(tuple(_floats(point.get('coordinates'))))
        weights.append(float(point.get('weight', '1')))
    return points, weights


def nurbs_surface(element, u_fastest: bool):
    """Geom_BSplineSurface of an OCX NURBSSurface; the control point order is tried both ways."""
    from OCP.Geom import Geom_BSplineSurface
    from OCP.TColgp import TColgp_Array2OfPnt
    from OCP.TColStd import TColStd_Array2OfReal
    from OCP.gp import gp_Pnt

    u_props, v_props = _child(element, 'U_NURBSproperties'), _child(element, 'V_NURBSproperties')
    nu, nv = int(u_props.get('numCtrlPts')), int(v_props.get('numCtrlPts'))
    u_knots, u_mult = _knots(_floats(_child(element, 'UknotVector').get('value')))
    v_knots, v_mult = _knots(_floats(_child(element, 'VknotVector').get('value')))
    points, weights = _control_points(element)
    poles, pole_weights = TColgp_Array2OfPnt(1, nu, 1, nv), TColStd_Array2OfReal(1, nu, 1, nv)
    for index, (point, weight) in enumerate(zip(points, weights)):
        i, j = (index % nu, index // nu) if u_fastest else (index // nv, index % nv)
        poles.SetValue(i + 1, j + 1, gp_Pnt(*point))
        pole_weights.SetValue(i + 1, j + 1, weight)
    return Geom_BSplineSurface(poles, pole_weights, _array1(u_knots, float), _array1(v_knots, float),
                               _array1(u_mult, int), _array1(v_mult, int),
                               int(u_props.get('degree')), int(v_props.get('degree')))


def boundary_wire(element):
    """Wire of the face boundary. A degree-1 NURBS3D piece is its polyline, one edge per segment,
    so that sewing can match the corners with the neighbouring faces; other pieces are one
    B-spline edge each."""
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeEdge, BRepBuilderAPI_MakeWire
    from OCP.Geom import Geom_BSplineCurve
    from OCP.TColgp import TColgp_Array1OfPnt
    from OCP.gp import gp_Pnt

    wire = BRepBuilderAPI_MakeWire()
    for curve in element.iter():
        if _tag(curve) != 'NURBS3D':
            continue
        props = _child(curve, 'NURBSproperties')
        points, weights = _control_points(curve)
        if int(props.get('degree')) == 1:
            corners = [p for i, p in enumerate(points) if i == 0 or np.linalg.norm(np.subtract(p, points[i - 1])) > 1e-7]
            for a, b in zip(corners, corners[1:]):
                wire.Add(BRepBuilderAPI_MakeEdge(gp_Pnt(*a), gp_Pnt(*b)).Edge())
            continue
        knots, multiplicities = _knots(_floats(_child(curve, 'KnotVector').get('value')))
        poles = TColgp_Array1OfPnt(1, len(points))
        for index, point in enumerate(points, start=1):
            poles.SetValue(index, gp_Pnt(*point))
        bspline = Geom_BSplineCurve(poles, _array1(weights, float), _array1(knots, float),
                                    _array1(multiplicities, int), int(props.get('degree')))
        wire.Add(BRepBuilderAPI_MakeEdge(bspline).Edge())
    return wire.Wire()


def _surface_gap(surface, points) -> float:
    from OCP.GeomAPI import GeomAPI_ProjectPointOnSurf
    from OCP.gp import gp_Pnt

    gaps = []
    for point in points:
        projection = GeomAPI_ProjectPointOnSurf(gp_Pnt(*point), surface)
        gaps.append(projection.LowerDistance() if projection.NbPoints() else 1e9)
    return max(gaps)


def _trimmed_face(surface, wire):
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeFace
    from OCP.ShapeFix import ShapeFix_Face

    fix = ShapeFix_Face(BRepBuilderAPI_MakeFace(surface, wire, True).Face())
    fix.Perform()
    return fix.Face()


def make_face(surface_element, boundary_element):
    """The trimmed face. A boundary that runs clockwise about the surface normal bounds the
    outside of the face (negative area): it is reversed."""
    import cadquery as cq
    from OCP.TopoDS import TopoDS

    boundary_points = [p for curve in boundary_element.iter() if _tag(curve) == 'NURBS3D'
                       for p in _control_points(curve)[0]][::5]
    candidates = [nurbs_surface(surface_element, order) for order in (True, False)]
    surface = min(candidates, key=lambda s: _surface_gap(s, boundary_points))
    wire = boundary_wire(boundary_element)
    face = _trimmed_face(surface, wire)
    if cq.Face(face).Area() < 0:
        face = _trimmed_face(surface, TopoDS.Wire_s(wire.Reversed()))
    return face


def exact_solid(compartment: OcxCompartment):
    import cadquery as cq
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeSolid, BRepBuilderAPI_Sewing
    from OCP.ShapeFix import ShapeFix_Solid
    from OCP.TopAbs import TopAbs_SHELL
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopoDS import TopoDS

    sewing = BRepBuilderAPI_Sewing(SEWING_TOLERANCE_M)
    for surface, boundary in compartment.faces:
        sewing.Add(make_face(surface, boundary))
    sewing.Perform()
    explorer = TopExp_Explorer(sewing.SewedShape(), TopAbs_SHELL)
    maker = BRepBuilderAPI_MakeSolid()
    while explorer.More():
        maker.Add(TopoDS.Shell_s(explorer.Current()))
        explorer.Next()
    fix = ShapeFix_Solid(maker.Solid())
    fix.Perform()
    solid = cq.Solid(fix.Solid())
    if solid.Volume() < 0:
        solid = cq.Solid(solid.wrapped.Reversed())
    return solid


def solid_triangles(solid) -> np.ndarray:
    deflection = MESH_DEFLECTION_SHARE * solid.BoundingBox().DiagonalLength
    vertices, triangles = solid.tessellate(deflection, MESH_ANGLE_RAD)
    points = np.array([v.toTuple() for v in vertices])
    return tanks.outward(points[np.array(triangles)])


def direct_volume_below(solid, level: float) -> float:
    import cadquery as cq

    box = solid.BoundingBox()
    margin = 1.0
    below = cq.Solid.makeBox(box.xlen + 2 * margin, box.ylen + 2 * margin, level - box.zmin + margin,
                             cq.Vector(box.xmin - margin, box.ymin - margin, box.zmin - margin))
    return abs(solid.intersect(below).Volume())


# --- checks ----------------------------------------------------------------------------------

def check(compartment: OcxCompartment, interval_m: float) -> dict:
    started = time.time()
    solid = exact_solid(compartment)
    exact_volume = solid.Volume()
    exact_centre = solid.Center().toTuple()
    triangles = solid_triangles(solid)
    full = tanks.fill_state(triangles, float(triangles[:, :, 2].max()))
    table = tanks.sounding_table(triangles, interval_m)
    rows, worst_rel, worst_abs_share = [], 0.0, 0.0
    for row in table:
        direct = direct_volume_below(solid, row['level_z_m'])
        abs_share = abs(row['volume_m3'] - direct) / exact_volume
        rel = abs(row['volume_m3'] - direct) / direct if direct >= T1_MIN_FILL * exact_volume else None
        worst_abs_share = max(worst_abs_share, abs_share)
        if rel is not None:
            worst_rel = max(worst_rel, rel)
        rows.append({'sounding_m': row['sounding_m'], 'ours_m3': round(row['volume_m3'], 4),
                     'direct_m3': round(direct, 4), 'rel_error': None if rel is None else round(rel, 6)})
    centre_error = [round(a - b, 5) for a, b in zip(full.centroid_m, exact_centre)]
    printed_gap = ([round(a - b, 4) for a, b in zip(full.centroid_m, compartment.printed_cog_m)]
                   if compartment.printed_cog_m else None)
    return {
        'name': compartment.name, 'purpose': compartment.purpose, 'faces': len(compartment.faces),
        'triangles': int(len(triangles)), 'levels': len(rows),
        'exact_volume_m3': round(exact_volume, 4), 'our_volume_m3': round(full.volume_m3, 4),
        'printed_volume_m3': compartment.printed_volume_m3,
        'T1_max_rel_error': round(worst_rel, 6), 'T1_max_abs_share_of_full': round(worst_abs_share, 6),
        'T3_centroid_error_m': centre_error, 'T3_volume_rel_error': round(full.volume_m3 / exact_volume - 1, 6),
        'exact_centre_m': [round(v, 4) for v in exact_centre], 'our_centre_m': [round(v, 4) for v in full.centroid_m],
        'printed_cog_m': compartment.printed_cog_m, 'printed_cog_gap_m': printed_gap,
        'printed_volume_gap_rel': (round(full.volume_m3 / compartment.printed_volume_m3 - 1, 5)
                                   if compartment.printed_volume_m3 else None),
        'rows': rows, 'seconds': round(time.time() - started, 1)}


def summary(results: list[dict]) -> dict:
    t1 = max(r['T1_max_rel_error'] for r in results)
    t3 = max(abs(e) for r in results for e in r['T3_centroid_error_m'])
    t3_volume = max(abs(r['T3_volume_rel_error']) for r in results)
    return {'compartments': len(results), 'engineering_approved': False,
            'T1_max_rel_error': t1, 'T1_target': T1_TARGET, 'T1_met': t1 <= T1_TARGET,
            'T1_max_abs_share_of_full': max(r['T1_max_abs_share_of_full'] for r in results),
            'T3_max_centroid_error_m': t3, 'T3_max_volume_rel_error': t3_volume,
            'T3_target_m': T3_TARGET_M, 'T3_volume_target': T3_VOLUME_TARGET,
            'T3_met': t3 <= T3_TARGET_M and t3_volume <= T3_VOLUME_TARGET}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('files', nargs='+', type=Path)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--interval', type=float, default=T1_INTERVAL_M)
    args = parser.parse_args()
    results = []
    for path in args.files:
        for compartment in read_compartments(path):
            result = check(compartment, args.interval) | {'file': path.name}
            print(json.dumps({k: v for k, v in result.items() if k != 'rows'}), flush=True)
            results.append(result)
    report = {'summary': summary(results), 'results': results}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report['summary'], indent=2))


if __name__ == '__main__':
    main()
