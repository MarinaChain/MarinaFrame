"""Inspect one explicit STEP solid, retaining real submerged transom skin.

Native coordinates have z down and x aft. The community source's numeric
coordinates represent physical full-scale metres despite its mm declaration.
This diagnostic does not publish a CFD mesh or change a gate.
"""
import argparse
import hashlib
import json
from pathlib import Path

import cadquery as cq
from OCP.BRepGProp import BRepGProp
from OCP.GProp import GProp_GProps


def inspect_shape(shape, *, scale, draft):
    if len(shape.Solids()) != 1 or not shape.isValid():
        raise ValueError('Expected one valid solid')
    bounds = shape.BoundingBox()
    waterline = -draft * scale
    margin = 1.0
    clip = cq.Solid.makeBox(
        bounds.xlen + 2 * margin, bounds.ylen + 2 * margin,
        bounds.zmax - waterline + margin,
        cq.Vector(bounds.xmin - margin, bounds.ymin - margin, waterline),
    )
    immersed = shape.intersect(clip)
    if len(immersed.Solids()) != 1 or not immersed.isValid():
        raise ValueError('Clipping must retain one valid immersed solid')
    faces = []
    for index, face in enumerate(immersed.Faces()):
        properties = GProp_GProps()
        BRepGProp.SurfaceProperties_s(face.wrapped, properties, 1e-9)
        planar = face.geomType() == 'PLANE'
        normal = face.normalAt() if planar else None
        center = face.Center()
        # Underlying spline bounding boxes can extend beyond trimmed faces.
        # Identify the artificial cap from its actual plane, not its bbox.
        cap = planar and abs(abs(normal.z) - 1) < 1e-10 and abs(center.z - waterline) < 1e-7
        aft = planar and abs(abs(normal.x) - 1) < 1e-10 and center.x > bounds.xmax - 0.02
        faces.append({
            'index': index, 'area_model_m2': properties.Mass() / scale**2,
            'waterplane_cap': cap, 'aft_closure_candidate': aft,
            'center_native_numeric': list(center.toTuple()),
        })
    return {
        'valid_solid_count': 1,
        'shell_closed': [shell.wrapped.Closed() for shell in shape.Shells()],
        'bounds_native_numeric': [bounds.xmin, bounds.ymin, bounds.zmin, bounds.xmax, bounds.ymax, bounds.zmax],
        'model_draft_m': draft, 'native_waterline_numeric': waterline,
        'volume_model_m3': immersed.Volume() / scale**3,
        'wetted_area_model_m2': sum(f['area_model_m2'] for f in faces if not f['waterplane_cap']),
        'waterplane_area_model_m2': sum(f['area_model_m2'] for f in faces if f['waterplane_cap']),
        'immersed_aft_closure_area_model_m2': sum(f['area_model_m2'] for f in faces if f['aft_closure_candidate']),
        'faces': faces, 'engineering_approved': False, 'status': 'review_required',
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    result = inspect_shape(cq.importers.importStep(str(args.source)).val(), scale=58, draft=0.3586)
    result['source_sha256'] = hashlib.sha256(args.source.read_bytes()).hexdigest()
    result['unit_interpretation'] = 'numeric STEP mm coordinates interpreted as full-scale metres, divided by 58'
    with args.output.open('x') as stream:
        json.dump(result, stream, indent=2)
        stream.write('\n')
    print(json.dumps({k: v for k, v in result.items() if k != 'faces'}, indent=2))


if __name__ == '__main__':
    main()
