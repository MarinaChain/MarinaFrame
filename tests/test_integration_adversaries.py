"""Integrator-owned pixel-to-export regressions, independent of geometry unit fixtures."""
import json
from copy import deepcopy

from PIL import Image, ImageDraw
import pytest

from vessel_reconstruction.pipeline import reconstruct, verify_run


def sheet(tmp_path, kind='parallel', selected=False):
    image = Image.new('RGB', (420, 420), 'white')
    draw = ImageDraw.Draw(image)
    draw.line([(180,60),(180,360)], fill=(15,)*3, width=3)
    if kind == 'crossing':
        draw.line([(285,60),(130,360)], fill=(180,)*3, width=3)
    elif kind == 'bracket':
        draw.line([(230,120),(285,120),(285,310),(230,310)], fill=(180,)*3, width=3)
    else:
        draw.line([(270,60),(270,360)], fill=(180,)*3, width=3)
    image.save(tmp_path/'drawing.png')
    section={'id':'s0','x_m':0,'roi_px':[65,40,350,375],
             'calibration':{'centerline_px':90,'baseline_px':360,'pixels_per_metre':60},
             'z_min_m':0,'z_max_m':5,'evidence':'Integrator diagnostic; explicit source calibration'}
    if selected:
        section['contour_selection']={'anchors_px':[[271,60],[271,360]],'half_width_px':5}
    spec={'schema_version':'1.0','vessel_id':'Integration adversary','units':'m',
          'source':{'file':'drawing.png','license':'Generated locally'},
          'symmetry':'port_starboard','symmetry_evidence':'Explicit synthetic symmetry',
          'end_closure':'flat_at_terminal_stations','sections':[],'components':[]}
    for i in range(3):
        station=deepcopy(section);station.update(id=f's{i}',x_m=i*5);spec['sections'].append(station)
    path=tmp_path/'spec.json';path.write_text(json.dumps(spec))
    return path


@pytest.mark.parametrize('kind',['parallel','crossing','bracket'])
def test_alternative_lines_block_whole_pipeline_before_geometry(tmp_path,kind):
    out=tmp_path/'run'
    result=reconstruct(sheet(tmp_path,kind),out)
    assert result['status']=='blocked'
    assert any(gap['kind']=='ambiguous_curve' for gap in result['gaps'])
    assert not result['exports'] and not (out/'model.step').exists()
    assert verify_run(out)['valid']


def test_explicit_selection_yields_source_bound_outer_envelope(tmp_path):
    out=tmp_path/'run'
    result=reconstruct(sheet(tmp_path,selected=True),out)
    assert result['status']=='review_required',result['gaps']
    assert result['metrics']['beam_m']==pytest.approx(6,abs=1e-7)
    assert result['metrics']['volume_m3']==pytest.approx(300,abs=1e-7)
    assert result['review']['engineering_approved'] is False
    assert verify_run(out)['exports_allowed']
    assert all(section['evidence']['contour_selection'] for section in result['sections'])
    reference = result['diagnostics']['sections_artifact']
    assert 'sections' not in result['diagnostics']
    extracted = json.loads((out / reference['file']).read_text())
    assert set(extracted['diagnostics']['sections']) == {'s0', 's1', 's2'}
    with (out / reference['file']).open('a') as artifact:
        artifact.write(' ')
    assert not verify_run(out)['valid']
