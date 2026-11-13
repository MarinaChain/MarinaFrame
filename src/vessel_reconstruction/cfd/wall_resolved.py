"""Lane-local PM DB2 half-hull, wall-resolved SST case specialization."""
import json
import math
import re
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
aftRefinement {{ type searchableBox; min ({aft_start} 0 {lower[2]-.02*length});
max ({upper[0]+.02*length} {upper[1]+.02*length} 0); }} }}''')
    text = text.replace('refinementRegions {}',
                        'refinementRegions { aftRefinement { mode inside; levels ((1e15 3)); } }')
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


def _replace_dictionary(text, name, body):
    """Replace one known dictionary using balanced braces, not a greedy regex."""
    match = re.search(r'\b' + re.escape(name) + r'\s*\{', text)
    if not match:
        raise ValueError(f'Missing dictionary {name}')
    opening = text.index('{', match.start())
    depth = 1
    end = opening + 1
    while end < len(text) and depth:
        depth += (text[end] == '{') - (text[end] == '}')
        end += 1
    if depth:
        raise ValueError(f'Unclosed dictionary {name}')
    return text[:match.start()] + name + ' {\n' + body + '\n}' + text[end:]


def separate_layer_dictionary(snapped_dictionary):
    """Official DTC-derived layer-only recovery; quality relaxation is pass-only."""
    text = snapped_dictionary
    for key, value in [('castellatedMesh', 'false'), ('snap', 'false'), ('addLayers', 'true')]:
        text, count = re.subn(r'\b' + key + r'\s+(?:true|false)\s*;',
                             f'{key} {value};', text, count=1)
        if count != 1:
            raise ValueError(f'Missing stage switch {key}')
    controls = '''relativeSizes true;
layers { hull { nSurfaceLayers 30; } }
expansionRatio 1.2; finalLayerThickness 0.3; minThickness 0.001;
nGrow 0; featureAngle 180; mergePatchFacesAngle 60;
layerTerminationAngle 30; slipFeatureAngle 30;
nRelaxIter 10; nSmoothSurfaceNormals 5; nSmoothNormals 10;
nSmoothThickness 30; maxFaceThicknessRatio 0.5;
maxThicknessToMedialRatio 0.3; minMedialAxisAngle 90;
nBufferCellsNoExtrude 0; nLayerIter 100; nRelaxedIter 20;'''
    text = _replace_dictionary(text, 'addLayersControls', controls)
    quality = '''#includeEtc "caseDicts/mesh/generation/meshQualityDict.cfg"
maxNonOrtho 75; minTetQuality -1e30; maxInternalSkewness 8;
minDeterminant 0.0001;
relaxed { maxNonOrtho 75; }'''
    text = _replace_dictionary(text, 'meshQualityControls', quality)
    return text + '\nwriteFlags (layerSets layerFields);\n'


def layer_admission(patch_layer_counts, requested_layers):
    """Require full requested count on >=95% faces of every hull patch."""
    if not patch_layer_counts or requested_layers < 1:
        raise ValueError('Nonempty hull patches and positive layer count required')
    fractions = {}
    for patch, counts in patch_layer_counts.items():
        if not counts or any(not isinstance(v, int) or v < 0 for v in counts):
            raise ValueError('Nonempty nonnegative integer layer counts required')
        fractions[patch] = sum(v >= requested_layers for v in counts) / len(counts)
    return {'passed': all(v >= .95 for v in fractions.values()),
            'full_count_fraction_by_patch': fractions}


def yplus_admission(values, areas):
    """Report area-weighted y+ acceptance; equality to one does not pass."""
    if len(values) != len(areas) or not values:
        raise ValueError('Matching nonempty y+ and area arrays required')
    if any(not math.isfinite(v) or v < 0 for v in values):
        raise ValueError('Finite nonnegative y+ required')
    if any(not math.isfinite(a) or a <= 0 for a in areas):
        raise ValueError('Finite positive areas required')
    total = sum(areas)
    fraction = sum(a for v, a in zip(values, areas) if v < 1) / total
    return {'passed': fraction >= .95, 'area_fraction_below_one': fraction,
            'minimum': min(values), 'maximum': max(values),
            'area_weighted_mean': sum(v*a for v, a in zip(values, areas))/total}
