"""Independent end-to-end checks, including adverse inputs and unit scaling.

These fixtures draw straight section traces.  Analytical volumes stay solely
in test assertions and never enter the inference specification.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import cadquery as cq
import numpy as np
from PIL import Image, ImageDraw
import pytest

from vessel_reconstruction.pipeline import reconstruct, verify_run


def drawing_fixture(directory: Path, scale: float = 1.0, *, blank_middle=False):
    directory.mkdir(parents=True, exist_ok=True)
    image = Image.new('RGB', (780, 280), 'white')
    draw = ImageDraw.Draw(image)
    sections = []
    for i, station in enumerate([0, 5, 10]):
        cx, baseline, ppm = 30 + 260*i, 240, 60
        if not (blank_middle and i == 1):
            draw.line([(cx + 60, baseline), (cx + 96, baseline - 180)], fill=(5, 5, 5), width=3)
        sections.append({
            'id': f's{i}', 'x_m': station * scale,
            'roi_px': [260*i+10, 40, 260*i+230, 255],
            'calibration': {'centerline_px': cx, 'baseline_px': baseline, 'pixels_per_metre': ppm/scale},
            'z_min_m': 0.0, 'z_max_m': 3.0*scale,
            'evidence': 'Manually declared panel and dimensions for a controlled unit test; curve points are image observations.'
        })
    image.save(directory/'drawing.png')
    spec = {
        'schema_version':'1.0', 'vessel_id':'independent-audit', 'units':'m',
        'source':{'file':'drawing.png','license':'CC0 controlled fixture'},
        'symmetry':'port_starboard', 'symmetry_evidence':'Explicit bilateral assumption for unit fixture',
        'end_closure':'flat_at_terminal_stations', 'sections':sections,
    }
    return spec


def run(directory: Path, spec: dict, name='run', **options):
    path=directory/f'{name}.json'
    path.write_text(json.dumps(spec))
    return reconstruct(path, directory/name, **options)


@pytest.mark.cad
def test_pixels_to_cad_analytical_volume_and_export_units(tmp_path):
    spec=drawing_fixture(tmp_path)
    result=run(tmp_path,spec)
    assert result['status']=='review_required', result['gaps']
    # y(z)=1+0.2z, mirrored over 0<=z<=3, over 10 m length.
    expected_volume=10*2*(3+0.1*3**2)
    assert result['metrics']['volume_m3']==pytest.approx(expected_volume,rel=.012)
    assert result['metrics']['length_m']==pytest.approx(10)
    assert result['metrics']['beam_m']==pytest.approx(3.2,abs=.035)
    assert result['metrics']['depth_m']==pytest.approx(3)
    assert result['review']['engineering_approved'] is False
    assert result['metrics']['solid_count']==1
    assert result['metrics']['cad_valid'] is True
    step=cq.importers.importStep(str(tmp_path/'run'/'model.step')).val()
    assert step.BoundingBox().xlen==pytest.approx(10000,rel=1e-8)
    assert step.BoundingBox().zlen==pytest.approx(3000,rel=1e-8)
    mesh=json.loads((tmp_path/'run'/'mesh.json').read_text())
    vertices=np.asarray(mesh['vertices'])
    assert mesh['units']=='m'
    assert np.ptp(vertices[:,0])==pytest.approx(10)
    assert np.ptp(vertices[:,2])==pytest.approx(3)
    assert result['exports']['stl_units']=='mm'
    # Read the STL with an independent mesh library; STL itself has no units.
    import trimesh
    stl=trimesh.load(tmp_path/'run'/'model.stl',force='mesh')
    assert stl.extents[0]==pytest.approx(10000,rel=1e-7)
    assert stl.extents[2]==pytest.approx(3000,rel=1e-7)
    assert stl.is_watertight
    assert stl.volume/1e9==pytest.approx(result['metrics']['volume_m3'],rel=1e-6)
    assert verify_run(tmp_path/'run')['valid'] is True


@pytest.mark.cad
def test_dimensional_scaling_changes_length_area_volume_consistently(tmp_path):
    original=run(tmp_path/'original',drawing_fixture(tmp_path/'original'),export_cad=False)
    doubled=run(tmp_path/'doubled',drawing_fixture(tmp_path/'doubled',scale=2),export_cad=False)
    assert original['status']==doubled['status']=='review_required'
    for metric in ('length_m','beam_m','depth_m'):
        assert doubled['metrics'][metric]/original['metrics'][metric]==pytest.approx(2,rel=1e-8)
    assert doubled['metrics']['surface_area_m2']/original['metrics']['surface_area_m2']==pytest.approx(4,rel=1e-8)
    assert doubled['metrics']['volume_m3']/original['metrics']['volume_m3']==pytest.approx(8,rel=1e-8)


def test_independent_dimension_conflict_blocks_scaled_geometry(tmp_path):
    spec=drawing_fixture(tmp_path,scale=2)
    spec['constraints']={'beam_m':3.2,'relative_tolerance':.03}
    result=run(tmp_path,spec,export_cad=False)
    assert result['status']=='blocked'
    assert any(g['kind']=='dimension_conflict' for g in result['gaps'])
    assert result['parts']==[] and result['exports']=={}
    assert not (tmp_path/'run'/'mesh.json').exists()


def test_blank_required_station_never_gets_interpolated_away(tmp_path):
    spec=drawing_fixture(tmp_path,blank_middle=True)
    result=run(tmp_path,spec,export_cad=False)
    assert result['status']=='blocked'
    assert {s['id'] for s in result['sections']}=={'s0','s2'}
    assert any(g.get('section_id')=='s1' for g in result['gaps'])
    assert not (tmp_path/'run'/'mesh.json').exists()
    assert result['exports']=={} and result['parts']==[]


@pytest.mark.cad
def test_neighboring_reference_file_cannot_change_inference(tmp_path):
    spec=drawing_fixture(tmp_path)
    reference=tmp_path/'ground_truth.json'
    reference.write_text(json.dumps({'volume_m3':-1,'points_yz_m':[[999,999]]}))
    first=run(tmp_path,spec,'first',export_cad=False)
    reference.write_text(json.dumps({'volume_m3':1e90,'points_yz_m':[[0,0]]}))
    second=run(tmp_path,spec,'second',export_cad=False)
    assert first['status']==second['status']=='review_required'
    assert first['run_id']==second['run_id']
    assert first['metrics']==second['metrics']
    assert first['provenance']['extracted_geometry_sha256']==second['provenance']['extracted_geometry_sha256']
    assert not (tmp_path/'first'/'ground_truth.json').exists()
    assert not (tmp_path/'second'/'ground_truth.json').exists()


@pytest.mark.cad
def test_source_pixels_control_geometry_and_recorded_evidence(tmp_path):
    spec=drawing_fixture(tmp_path)
    first=run(tmp_path,spec,'first',export_cad=False)
    with Image.open(tmp_path/'drawing.png') as image:
        draw=ImageDraw.Draw(image)
        draw.rectangle((0,0,779,279),fill='white')
        for i in range(3):
            cx=30+260*i
            draw.line([(cx+90,240),(cx+126,60)],fill=(5,5,5),width=3)
        image.save(tmp_path/'drawing.png')
    second=run(tmp_path,spec,'second',export_cad=False)
    assert first['status']==second['status']=='review_required'
    assert first['run_id']!=second['run_id']
    assert first['sources'][0]['sha256']!=second['sources'][0]['sha256']
    assert second['metrics']['beam_m']>first['metrics']['beam_m']+.9
    # Prior evidence snapshot must remain stable despite input-file change.
    assert verify_run(tmp_path/'first')['valid'] is True


@pytest.mark.parametrize('value',[None,[],42,'invalid'])
def test_nonobject_json_is_a_structured_block(tmp_path,value):
    path=tmp_path/'bad.json';path.write_text(json.dumps(value))
    result=reconstruct(path,tmp_path/'run',export_cad=False)
    assert result['status']=='blocked'
    assert result['gaps']
    assert (tmp_path/'run'/'result.json').exists()


@pytest.mark.parametrize('token',['NaN','Infinity','-Infinity','1e999','-1e999'])
def test_nonfinite_json_is_a_structured_block(tmp_path,token):
    path=tmp_path/'bad.json';path.write_text('{"schema_version":"1.0","bad":'+token+'}')
    result=reconstruct(path,tmp_path/'run',export_cad=False)
    assert result['status']=='blocked'
    assert result['gaps']
    assert (tmp_path/'run'/'result.json').exists()


@pytest.mark.parametrize('tolerance',[True,False,'0.1',None,0,-.01,.25])
def test_invalid_constraint_tolerance_is_rejected(tmp_path,tolerance):
    spec=drawing_fixture(tmp_path)
    spec['constraints']={'beam_m':3.2,'relative_tolerance':tolerance}
    result=run(tmp_path,spec,export_cad=False)
    assert result['status']=='blocked'
    assert any('constraint' in g['kind'] for g in result['gaps'])
    assert not (tmp_path/'run'/'mesh.json').exists()


def test_enormous_integer_station_is_a_structured_block(tmp_path):
    spec=drawing_fixture(tmp_path)
    spec['sections'][0]['x_m']=10**400
    result=run(tmp_path,spec,export_cad=False)
    assert result['status']=='blocked'
    assert result['gaps']
    assert not (tmp_path/'run'/'mesh.json').exists()
