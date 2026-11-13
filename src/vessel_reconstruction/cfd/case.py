"""OpenFOAM OpenCFD dialect: fixed-body, full closed double-body RANS.

Input coordinates: x downstream (flow positive x), z up, metres. A caller
must reflect the wetted body across z=0 and close it before calling this
writer. The reference wetted area is the original physical wetted area;
forces on the reflected full body are halved by the result reader.
"""
import json
from pathlib import Path
import shutil

from .models import CaseInput
from .surface import validate_surface, write_stl

DISK_RESERVE_BYTES = 10_000_000_000


def foam_file(name, body, kind='dictionary'):
    return f'FoamFile {{ version 2.0; format ascii; class {kind}; object {name}; }}\n{body}\n'


def write_case(root: Path, inputs: CaseInput, triangles, *, available_bytes=None):
    """Create a fresh serial case. Refuse replacement and insufficient disk.

    Peak estimate is conservative admission control, not a measured mesh size.
    snappyHexMesh's maxGlobalCells is a limit, not a guaranteed cell count.
    """
    root = Path(root)
    if root.exists():
        raise FileExistsError(root)
    triangles = validate_surface(triangles)
    points = [p for triangle in triangles for p in triangle]
    length = inputs.length_m
    lower = [min(p[i] for p in points) for i in range(3)]
    upper = [max(p[i] for p in points) for i in range(3)]
    if upper[0] - lower[0] > 1.1 * length:
        raise ValueError('Surface x extent exceeds declared hull length')
    max_cells = 2_500_000
    estimated_peak_bytes = max_cells * 2400 + len(triangles) * 1000
    if available_bytes is None:
        available_bytes = shutil.disk_usage(root.parent).free
    if available_bytes - estimated_peak_bytes < DISK_RESERVE_BYTES:
        raise OSError('CFD disk reserve would fall below 10 GB')
    root.mkdir()
    for name in ('0', 'constant/triSurface', 'system'):
        (root / name).mkdir(parents=True, exist_ok=True)
    write_stl(root / 'constant/triSurface/hull.stl', triangles)
    metadata = inputs.to_dict() | {'regime': 'double_body_fixed_attitude',
                                  'force_multiplier': 0.5,
                                  'estimated_peak_bytes': estimated_peak_bytes,
                                  'dialect': 'OpenCFD simpleFoam',
                                  'engineering_approved': False}
    (root / 'case-input.json').write_text(json.dumps(metadata, indent=2) + '\n')
    def save(folder, name, body, kind='dictionary'):
        (root / folder / name).write_text(foam_file(name, body, kind))
    save('system', 'controlDict', f'''application simpleFoam;
startFrom startTime; startTime 0; stopAt endTime; endTime {inputs.iterations};
deltaT 1; writeControl timeStep; writeInterval {inputs.iterations}; purgeWrite 1;
writeFormat binary; runTimeModifiable false;
functions {{ resistance {{ type forces; libs ("libforces.so"); patches (hull);
p p; U U; rho rhoInf; rhoInf {inputs.density_kg_m3}; CofR (0 0 0);
writeControl timeStep; writeInterval 1; }} }}''')
    xmin, xmax = lower[0] - length, upper[0] + 3 * length
    ymin, ymax = lower[1] - length, upper[1] + length
    zmin, zmax = lower[2] - length, upper[2] + length
    vertices = [(xmin,ymin,zmin), (xmax,ymin,zmin), (xmax,ymax,zmin), (xmin,ymax,zmin),
                (xmin,ymin,zmax), (xmax,ymin,zmax), (xmax,ymax,zmax), (xmin,ymax,zmax)]
    vertex_text = ' '.join('(' + ' '.join(map(str, p)) + ')' for p in vertices)
    n = inputs.base_cells
    save('system', 'blockMeshDict', f'''scale 1;
vertices ({vertex_text});
blocks (hex (0 1 2 3 4 5 6 7) ({2*n} {n} {n}) simpleGrading (1 1 1));
edges ();
boundary (
inlet {{ type patch; faces ((0 4 7 3)); }}
outlet {{ type patch; faces ((1 2 6 5)); }}
farfield {{ type patch; faces ((0 1 5 4) (3 7 6 2) (0 3 2 1) (4 5 6 7)); }}
); mergePatchPairs ();''')
    r = inputs.refinement_level
    save('system', 'snappyHexMeshDict', f'''castellatedMesh true; snap true; addLayers false;
geometry {{ hull.stl {{ type triSurfaceMesh; name hull; }} }}
castellatedMeshControls {{
maxLocalCells {max_cells}; maxGlobalCells {max_cells}; minRefinementCells 0;
maxLoadUnbalance 0.1; nCellsBetweenLevels 3;
features (); refinementSurfaces {{ hull {{ level ({r} {r}); patchInfo {{ type wall; }} }} }}
resolveFeatureAngle 30; refinementRegions {{}}
locationInMesh ({xmin + 0.1*length} 0 0); allowFreeStandingZoneFaces true;
}}
snapControls {{ nSmoothPatch 3; tolerance 2; nSolveIter 30; nRelaxIter 5; }}
addLayersControls {{ relativeSizes true; layers {{}}; expansionRatio 1.2;
finalLayerThickness 0.3; minThickness 0.1; nGrow 0; featureAngle 60;
nRelaxIter 5; nSmoothSurfaceNormals 1; nSmoothNormals 3; nSmoothThickness 10;
maxFaceThicknessRatio 0.5; maxThicknessToMedialRatio 0.3;
minMedialAxisAngle 90; nBufferCellsNoExtrude 0; nLayerIter 50; }}
meshQualityControls {{ #includeEtc "caseDicts/mesh/generation/meshQualityDict" }}
mergeTolerance 1e-6;''')
    save('system', 'fvSchemes', '''ddtSchemes { default steadyState; }
gradSchemes { default Gauss linear; }
divSchemes { default none; div(phi,U) bounded Gauss linearUpwind grad(U);
div(phi,k) bounded Gauss upwind; div(phi,omega) bounded Gauss upwind;
div((nuEff*dev2(T(grad(U))))) Gauss linear; }
laplacianSchemes { default Gauss linear corrected; }
interpolationSchemes { default linear; }
snGradSchemes { default corrected; }
wallDist { method meshWave; }''')
    save('system', 'fvSolution', '''solvers {
p { solver GAMG; tolerance 1e-7; relTol 0.01; smoother GaussSeidel; }
"(U|k|omega)" { solver smoothSolver; smoother symGaussSeidel; tolerance 1e-8; relTol 0.1; }
}
SIMPLE { nNonOrthogonalCorrectors 1; consistent yes; }
relaxationFactors { fields { p 0.3; } equations { U 0.7; k 0.7; omega 0.7; } }''')
    save('constant', 'transportProperties', f'transportModel Newtonian;\nnu [0 2 -1 0 0 0 0] {inputs.viscosity_m2_s};')
    save('constant', 'turbulenceProperties', 'simulationType RAS;\nRAS { RASModel kOmegaSST; turbulence on; printCoeffs on; }')
    speed = inputs.speed_m_s
    k = 1.5 * (0.01 * speed)**2
    omega = k**0.5 / (0.09**0.25 * 0.07 * length)
    fields = {
        'U': ('volVectorField', '[0 1 -1 0 0 0 0]', f'({speed} 0 0)', f'type fixedValue; value uniform ({speed} 0 0);', 'type zeroGradient;', 'type slip;'),
        'p': ('volScalarField', '[0 2 -2 0 0 0 0]', '0', 'type zeroGradient;', 'type fixedValue; value uniform 0;', 'type zeroGradient;'),
        'k': ('volScalarField', '[0 2 -2 0 0 0 0]', str(k), f'type fixedValue; value uniform {k};', 'type zeroGradient;', f'type kqRWallFunction; value uniform {k};'),
        'omega': ('volScalarField', '[0 0 -1 0 0 0 0]', str(omega), f'type fixedValue; value uniform {omega};', 'type zeroGradient;', f'type omegaWallFunction; value uniform {omega};'),
        'nut': ('volScalarField', '[0 2 -1 0 0 0 0]', '0', 'type calculated; value uniform 0;', 'type calculated; value uniform 0;', 'type nutkWallFunction; value uniform 0;'),
    }
    for name, (kind, dimensions, initial, inlet, outlet, wall) in fields.items():
        far = 'type slip;' if name == 'U' else 'type zeroGradient;'
        hull = 'type noSlip;' if name == 'U' else wall
        save('0', name, f'dimensions {dimensions};\ninternalField uniform {initial};\nboundaryField {{ inlet {{ {inlet} }} outlet {{ {outlet} }} farfield {{ {far} }} hull {{ {hull} }} }}', kind)
    return root
