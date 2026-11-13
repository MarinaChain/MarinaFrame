"""Lane-local PM DB2 half-hull, wall-resolved SST case specialization."""
import json
import math
from pathlib import Path

from .case import foam_file, write_case
from .surface import validate_surface


def gate_db2(form_factor, cf, *, converged):
    """Score central working CW=0, reporting the non-cited +/-1e-4 bounds."""
    if not all(math.isfinite(v) and v > 0 for v in (form_factor, cf)):
        raise ValueError('Finite positive form factor and CF required')
    ct = form_factor * cf
    return {'passed': bool(converged and 1.17855 <= form_factor <= 1.25145
                           and 0.0039456 <= ct <= 0.0042744),
            'ct_est': ct, 'ct_lower': ct - .0001, 'ct_upper': ct + .0001,
            'bounds_inside_ct_gate': ct - .0001 >= .0039456 and ct + .0001 <= .0042744,
            'engineering_approved': False}


def write_wall_resolved_case(root, inputs, triangles, *, refinement_factor,
                             available_bytes):
    """Publish a fresh starboard half case; caps are replaced by domain symmetry.

    Absolute layer thickness is scaled with the background grid, not with local
    snapped cell size. Requested settings do not establish achieved y+ or layers.
    """
    if not math.isfinite(refinement_factor) or refinement_factor < 1:
        raise ValueError('refinement_factor must be finite and >=1')
    triangles = validate_surface(triangles)
    points = [p for t in triangles for p in t]
    if min(p[1] for p in points) > 1e-9 or max(p[1] for p in points) <= 0:
        raise ValueError('Surface must touch or cross centreplane with starboard skin')
    # Match a 6M ceiling disk allowance, rather than the older writer's 2.5M.
    estimated = 6_000_000 * 2400 + len(triangles) * 1000
    if available_bytes - estimated < 10_000_000_000:
        raise OSError('CFD disk reserve would fall below 10 GB')
    root = Path(root)
    write_case(root, inputs, triangles, available_bytes=available_bytes,
               waterplane_symmetry=True)
    lower = [min(p[i] for p in points) for i in range(3)]
    upper = [max(p[i] for p in points) for i in range(3)]
    length = inputs.length_m
    xmin, xmax = lower[0] - length, upper[0] + 3 * length
    ymax, zmin = upper[1] + length, lower[2] - length
    vertices = [(xmin,0,zmin),(xmax,0,zmin),(xmax,ymax,zmin),(xmin,ymax,zmin),
                (xmin,0,0),(xmax,0,0),(xmax,ymax,0),(xmin,ymax,0)]
    vtext = ' '.join('('+' '.join(map(str,p))+')' for p in vertices)
    n = inputs.base_cells
    body = f'''scale 1;
vertices ({vtext});
blocks (hex (0 1 2 3 4 5 6 7) ({2*n} {n} {n}) simpleGrading (1 1 1));
edges ();
boundary (
inlet {{ type patch; faces ((0 4 7 3)); }}
outlet {{ type patch; faces ((1 2 6 5)); }}
farfield {{ type patch; faces ((3 7 6 2) (0 3 2 1)); }}
centreplane {{ type symmetryPlane; faces ((0 1 5 4)); }}
waterplane {{ type symmetryPlane; faces ((4 5 6 7)); }}
); mergePatchPairs ();'''
    (root/'system/blockMeshDict').write_text(foam_file('blockMeshDict', body))
    path = root/'system/snappyHexMeshDict'
    text = path.read_text().replace('maxLocalCells 2500000; maxGlobalCells 2500000;',
                                   'maxLocalCells 6000000; maxGlobalCells 6000000;')
    seed_x, seed_z = xmin + .1 * length, zmin / 2
    text = text.replace(f'locationInMesh ({seed_x} 0 {seed_z})',
                        f'locationInMesh ({seed_x} {ymax/4} {seed_z})')
    aft_start = upper[0] - .35 * length
    text = text.replace('name hull; } }', f'''name hull; }}
aftRefinement {{ type searchableBox; min ({aft_start} 0 {-inputs.length_m*.15});
max ({upper[0]+.1*length} {upper[1]+.1*length} 0); }} }}''')
    text = text.replace('refinementRegions {}',
                        'refinementRegions { aftRefinement { mode inside; levels ((1e15 4)); } }')
    text = text.replace('relativeSizes true', 'relativeSizes false')
    text = text.replace('nSurfaceLayers 3;', 'nSurfaceLayers 30;')
    first, minimum = 8e-6/refinement_factor, 1e-6/refinement_factor
    text = text.replace('finalLayerThickness 0.3; minThickness 0.1;',
                        f'firstLayerThickness {first:g}; minThickness {minimum:g};')
    path.write_text(text)
    for field in ('U','p','k','omega','nut'):
        path = root/'0'/field
        text = path.read_text().replace('waterplane { type symmetryPlane; }',
                    'waterplane { type symmetryPlane; } centreplane { type symmetryPlane; }')
        if field == 'k':
            start = text.index('hull {')
            end = text.index('}', start) + 1
            text = text[:start] + 'hull { type fixedValue; value uniform 0; }' + text[end:]
        if field == 'nut':
            text = text.replace('nutkWallFunction', 'nutLowReWallFunction')
        path.write_text(text)
    path = root/'case-input.json'
    metadata = json.loads(path.read_text())
    metadata.update(force_multiplier=2, centreplane_y_m=0,
                    wall_treatment='low-Re SST; target y+<1; verify achieved',
                    requested_layers=30, first_layer_thickness_m=first,
                    refinement_factor=refinement_factor, estimated_peak_bytes=estimated)
    path.write_text(json.dumps(metadata, indent=2)+'\n')
    return root
