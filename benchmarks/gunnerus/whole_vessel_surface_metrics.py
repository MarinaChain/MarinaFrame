"""Side-wall smoothness of the parts above the hull on Gunnerus (fixed before the build).

Definitions: docs/WHOLE_VESSEL_GUNNERUS.md, section 7.1. Do not change the constants after a
result is seen; add a new metric version instead.

F1 smoothness: on vertical cuts through the port side wall of each deckhouse and bulwark, the
outward surface normal is read every ``CUT_STEP_M`` (a ray from outboard hits the wall; the
normal is the exact B-rep surface normal there). A wall made of stacked ruled bands turns its
normal only at the band edges (a kink); a smooth surface turns it a little at every step.
Reported per part: the largest turn between two neighbouring samples (degrees), the number of
neighbouring samples with a turn above ``KINK_DEG`` and the number of distinct B-rep faces
that the cuts cross (one for a single surface).
F2 containment: S1 of ``whole_vessel_superstructure_metrics`` (largest distance outside the
hull side, tolerance 0.02 m). S1 meshes the parts with CadQuery's ``tessellate``, whose
deflection is relative to the edge size: exact for flat and ruled faces, but on a curved
B-spline face its triangles are up to about 0.04 m off the surface. v2 adds F2 exact: the same
S1 sampling on a mesh with an absolute deflection of ``EXACT_DEFLECTION_MM``.
F3 accuracy: M2 and M4 of ``whole_vessel_metrics`` (tier-1 footprint IoU and volume) and the
hull + tier-1 volume against the truth (from the assembly record).
F4 cost: face count of each part STEP, whole-vessel STEP and GLB size, build time.

Usage::

    PYTHONPATH=src:. python -m benchmarks.gunnerus.whole_vessel_surface_metrics \\
        --run <step 1 run> --assembly <assembly run> --sources work/sources/gunnerus \\
        --truth-mesh <truth dir>/truth_mesh.npz
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np

METRIC_VERSION = 'whole-vessel-surfaces/v2'
# v2: F2 exact. A mesh of the part STEP (millimetres) at this absolute deflection and angle.
EXACT_DEFLECTION_MM = 1.0
EXACT_ANGLE_RAD = 0.1
WALL_OPS = ('bulwark', 'deckhouse')
# Normal samples on a cut are this far apart in z (a quarter of the thinnest refined band
# spacing that is visible at 1 m viewing distance; finer than any loft level spacing).
CUT_STEP_M = 0.01
# A turn of the normal above this between two samples 0.01 m apart is a kink: a smooth flare
# with a 0.3 m radius (tighter than any Gunnerus bow section) turns 1.9 degrees per step.
KINK_DEG = 2.0
# Cuts at these fractions of each part's length, plus the tier-1 bow stations of S4.
CUT_FRACTIONS = (0.1, 0.3, 0.5, 0.7, 0.9)
BOW_STATIONS_M = (28.0, 31.0, 33.0, 34.0)
# Samples closer than this to the part's base or top are left out (the wall's own corners).
END_MARGIN_M = 0.02
# The ray starts this far to port of the centreline (outside every part).
RAY_START_Y_M = 20.0
TARGETS = {'F2_exact_max_outside_m': 0.02, 'F3_tier1_iou_min': 0.997, 'F3_tier1_volume_error_abs_max': 0.031,
           'F3_hull_tier1_error_abs_max': 0.016}


def read_step(path: Path):
    import cadquery as cq

    return cq.importers.importStep(str(path)).val()


def wall_normals(shape, x_m: float, z_values_m) -> list[tuple[float, np.ndarray, int] | None]:
    """(y, unit outward normal, face index) of the outermost port wall at (x, z); None: no hit.

    The shape is in millimetres (part STEP files); x and z are metres.
    """
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.BRepLProp import BRepLProp_SLProps
    from OCP.gp import gp_Dir, gp_Lin, gp_Pnt
    from OCP.IntCurvesFace import IntCurvesFace_ShapeIntersector
    from OCP.TopAbs import TopAbs_REVERSED

    faces = [face.wrapped for face in shape.Faces()]
    intersector = IntCurvesFace_ShapeIntersector()
    intersector.Load(shape.wrapped, 1e-3)
    results = []
    for z in z_values_m:
        line = gp_Lin(gp_Pnt(x_m * 1000, RAY_START_Y_M * 1000, z * 1000), gp_Dir(0, -1, 0))
        intersector.Perform(line, 0.0, 2 * RAY_START_Y_M * 1000)
        if not intersector.IsDone() or intersector.NbPnt() == 0:
            results.append(None)
            continue
        first = min(range(1, intersector.NbPnt() + 1), key=intersector.WParameter)
        face = intersector.Face(first)
        props = BRepLProp_SLProps(BRepAdaptor_Surface(face), intersector.UParameter(first),
                                  intersector.VParameter(first), 1, 1e-6)
        if not props.IsNormalDefined():
            results.append(None)
            continue
        normal = np.array(props.Normal().Coord())
        if face.Orientation() == TopAbs_REVERSED:
            normal = -normal
        index = next((i for i, f in enumerate(faces) if f.IsSame(face)), -1)
        results.append((intersector.Pnt(first).Y() / 1000, normal, index))
    return results


def exact_triangles(path: Path) -> np.ndarray:
    """Triangles (metres) within ``EXACT_DEFLECTION_MM`` of the part surface (absolute deflection)."""
    from OCP.BRep import BRep_Tool
    from OCP.BRepMesh import BRepMesh_IncrementalMesh
    from OCP.TopLoc import TopLoc_Location

    shape = read_step(path)
    BRepMesh_IncrementalMesh(shape.wrapped, EXACT_DEFLECTION_MM, False, EXACT_ANGLE_RAD, True)
    triangles = []
    for face in shape.Faces():
        location = TopLoc_Location()
        mesh = BRep_Tool.Triangulation_s(face.wrapped, location)
        if mesh is None:
            continue
        nodes = np.array([mesh.Node(i).Transformed(location.Transformation()).Coord()
                          for i in range(1, mesh.NbNodes() + 1)])
        corners = np.array([[t.Value(k) for k in (1, 2, 3)] for t in mesh.Triangles()]) - 1
        triangles.append(nodes[corners])
    return np.concatenate(triangles) / 1000.0


def cut_smoothness(shape, x_m: float, z_low: float, z_high: float) -> dict | None:
    """Normal turns along one vertical cut of the port wall at x."""
    z_values = np.arange(z_low + END_MARGIN_M, z_high - END_MARGIN_M, CUT_STEP_M)
    samples = [s for s in wall_normals(shape, x_m, z_values) if s is not None]
    if len(samples) < 2:
        return None
    normals = np.array([s[1] for s in samples])
    cosine = np.clip((normals[:-1] * normals[1:]).sum(axis=1), -1.0, 1.0)
    turns = np.degrees(np.arccos(cosine))
    return {'x_m': x_m, 'samples': len(samples), 'max_turn_deg': float(turns.max()),
            'kinks': int((turns > KINK_DEG).sum()), 'faces': len({s[2] for s in samples})}


def part_smoothness(path: Path, component: dict) -> dict:
    shape = read_step(path)
    box = component['bbox_m']
    x0, x1 = box['min'][0], box['max'][0]
    z0, z1 = box['min'][2], box['max'][2]
    xs = [x0 + f * (x1 - x0) for f in CUT_FRACTIONS]
    if component['id'] == 'house_t1':
        xs += [x for x in BOW_STATIONS_M if x0 < x < x1]
    cuts = [c for c in (cut_smoothness(shape, x, z0, z1) for x in xs) if c is not None]
    return {'step_faces': len(shape.Faces()), 'cuts': cuts,
            'max_turn_deg': max((c['max_turn_deg'] for c in cuts), default=None),
            'kinks': sum(c['kinks'] for c in cuts),
            'max_faces_on_cut': max((c['faces'] for c in cuts), default=None)}


def score(run: Path, assembly: Path | None, sources: Path, truth_mesh: Path) -> dict:
    from benchmarks.gunnerus.whole_vessel_superstructure_metrics import (
        score as superstructure_score,
    )

    execution = json.loads((run / 'execution.json').read_text())
    components = (execution.get('result') or {}).get('components', [])
    output = run / 'task' / 'work' / 'output'
    smoothness = {}
    for component in components:
        path = output / f'{component["id"]}.step'
        if component.get('op') in WALL_OPS and component.get('built') and path.is_file():
            smoothness[component['id']] = part_smoothness(path, component)
    containment = superstructure_score(run, sources, truth_mesh)
    from benchmarks.gunnerus.whole_vessel_detail import hull_sections
    from benchmarks.gunnerus.whole_vessel_superstructure_metrics import overhang
    from vessel_reconstruction.superstructure import HullSide

    hull = HullSide.from_sections(hull_sections(sources))
    exact = {part: overhang(hull, exact_triangles(output / f'{part}.step'))['max_m']
             for part in containment['S1_overhang']}
    step1 = containment['step1_metrics']
    report = {'metric_version': METRIC_VERSION, 'engineering_approved': False, 'case': 'gunnerus development',
              'metrics_file_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              'targets': TARGETS, 'F1_smoothness': smoothness,
              'F2_outside_m': {part: item['max_m'] for part, item in containment['S1_overhang'].items()},
              'F2_max_outside_m': containment['S1_max_overhang_m'],
              'F2_exact_outside_m': exact, 'F2_exact_max_outside_m': max(exact.values(), default=None),
              'F3_tier1_iou': step1.get('M2_footprint_iou'), 'F3_tier1_volume_error': step1.get('M4_volume_error'),
              'F4_part_step_faces': {part: item['step_faces'] for part, item in smoothness.items()}}
    if assembly is not None:
        record = json.loads((assembly / 'assembly.json').read_text())
        sizes = record['exports']['bytes']
        report.update(F3_hull_tier1_error=record.get('truth_comparable_error'),
                      F4_step_mb=sizes['whole-vessel-draft.step'] / 1e6, F4_glb_mb=sizes['whole-vessel-draft.glb'] / 1e6,
                      F4_assembly_seconds=record.get('seconds'))
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', type=Path, required=True, help='Step 1 run folder (whole_vessel.py output)')
    parser.add_argument('--assembly', type=Path, help='Assembly folder (whole_vessel_assembly.py output)')
    parser.add_argument('--sources', type=Path, required=True)
    parser.add_argument('--truth-mesh', type=Path, required=True)
    parser.add_argument('--out', type=Path, help='Report path (default: <run>/surface_score.json)')
    args = parser.parse_args()
    report = score(args.run, args.assembly, args.sources, args.truth_mesh)
    (args.out or args.run / 'surface_score.json').write_text(json.dumps(report, indent=2) + '\n')
    summary = {part: {key: item[key] for key in ('step_faces', 'max_turn_deg', 'kinks', 'max_faces_on_cut')}
               for part, item in report['F1_smoothness'].items()}
    print(json.dumps({'F1': summary, **{k: v for k, v in report.items() if k.startswith(('F2', 'F3', 'F4'))}},
                     indent=2))


if __name__ == '__main__':
    main()
