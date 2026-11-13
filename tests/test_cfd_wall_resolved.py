"""PM DB2 half-hull and low-Re SST contracts."""
import json
import pytest
from vessel_reconstruction.cfd import CaseInput
from vessel_reconstruction.cfd.wall_resolved import write_wall_resolved_case, gate_db2


def half_box():
    from vessel_reconstruction.cfd.surface import validate_surface
    v=[(0,0,-1),(1,0,-1),(1,1,-1),(0,1,-1),(0,0,0),(1,0,0),(1,1,0),(0,1,0)]
    faces=[(0,3,2,1),(4,5,6,7),(0,1,5,4),(1,2,6,5),(2,3,7,6),(3,0,4,7)]
    return validate_surface([(v[f[0]],v[f[1]],v[f[2]]) for f in faces]+[(v[f[0]],v[f[2]],v[f[3]]) for f in faces])


def test_half_case_resolves_wall_and_normalizes_full_hull(tmp_path):
    config=CaseInput(length_m=1,speed_m_s=1,wetted_area_m2=4,density_kg_m3=1000,viscosity_m2_s=1e-6,base_cells=74,refinement_level=3,iterations=2000,sources=('synthetic',))
    case=tmp_path/'half'
    write_wall_resolved_case(case,config,half_box(),refinement_factor=1,available_bytes=40_000_000_000)
    metadata=json.loads((case/'case-input.json').read_text())
    assert metadata['force_multiplier']==2
    mesh=(case/'system/blockMeshDict').read_text()
    assert 'centreplane { type symmetryPlane;' in mesh
    assert '(148 74 74)' in mesh
    for field in ('U','p','k','omega','nut'):
        assert 'centreplane { type symmetryPlane; }' in (case/'0'/field).read_text()
    assert 'hull { type fixedValue; value uniform 0; }' in (case/'0/k').read_text()
    assert 'nutLowReWallFunction' in (case/'0/nut').read_text()
    snappy=(case/'system/snappyHexMeshDict').read_text()
    assert 'relativeSizes false' in snappy
    assert 'nSurfaceLayers 30' in snappy
    assert 'firstLayerThickness 8e-06' in snappy
    assert 'maxGlobalCells 6000000' in snappy
    assert 'aftRefinement' in snappy and 'levels ((1e15 3))' in snappy
    assert 'finalLayerThickness' not in snappy
    assert 'locationInMesh (-0.9 0.5 -1.0)' in snappy


def test_gate_requires_converged_mesh_and_reports_working_wave_bounds():
    result=gate_db2(1.215,0.0034496540429658747,converged=True)
    assert result['passed']
    assert result['ct_lower']==pytest.approx(result['ct_est']-.0001)
    assert result['ct_upper']==pytest.approx(result['ct_est']+.0001)
    assert not gate_db2(1.215,0.0034496540429658747,converged=False)['passed']
    assert not gate_db2(1.3,.0034496540429658747,converged=True)['passed']
