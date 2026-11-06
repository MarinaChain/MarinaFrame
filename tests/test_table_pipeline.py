"""Real OCR-to-CAD integration over controlled printed numeric source cells."""
import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont
import pytest

from vessel_reconstruction.pipeline import reconstruct, verify_run
from vessel_reconstruction.table_ingest import parse_feet_inches_eighths


def fixture(directory:Path):
    tokens=['1-0-0','2-3-4','3-6-0','4-8-2','5-10-6']
    image=Image.new('L',(900,400),255);draw=ImageDraw.Draw(image)
    font=ImageFont.truetype('DejaVuSans.ttf',34)
    sections=[]
    for station in range(3):
        cells=[]
        for row,token in enumerate(tokens):
            y=10+row*75;left=station*300
            draw.text((left+20,y+8),token,fill=0,font=font)
            cells.append({'z_m':float(row),'roi_px':[left+10,y,left+260,y+65]})
        sections.append({'id':f's{station}','x_m':float(station*5),
                         'roi_px':[station*300,0,station*300+280,390],
                         'evidence':'Printed controlled source cells; station and waterline identity supplied as calibration.',
                         'cells':cells})
    image.save(directory/'table.png')
    spec={'schema_version':'1.0','vessel_id':'table-integration',
          'input_mode':'offset_table_ocr','units':'m','table_value_units':'feet_inches_eighths',
          'table_surface':'inner_hull_surface','source':{'file':'table.png'},
          'symmetry':'port_starboard','symmetry_evidence':'Explicit symmetry assumption for controlled fixture.',
          'end_closure':'flat_at_terminal_stations','sections':sections}
    return spec,tokens


def test_ocr_measurements_reach_cad_with_correct_units(tmp_path):
    spec,tokens=fixture(tmp_path)
    path=tmp_path/'spec.json';path.write_text(json.dumps(spec))
    result=reconstruct(path,tmp_path/'run',export_cad=False)
    assert result['status']=='review_required',result['gaps']
    widths=np.array([parse_feet_inches_eighths(token)[0] for token in tokens])
    expected=10*2*np.trapezoid(widths,np.arange(5))
    assert result['metrics']['volume_m3']==pytest.approx(expected,rel=1e-8)
    assert result['metrics']['length_m']==pytest.approx(10)
    assert result['metrics']['beam_m']==pytest.approx(2*widths[-1])
    assert result['method']=='archived_table_ocr+section_loft'
    assert len(result['sections'])==3
    assert all(len(s['evidence']['cell_evidence'])==5 for s in result['sections'])
    assert result['review']['engineering_approved'] is False
    assert verify_run(tmp_path/'run')['valid']


def test_blank_required_numeric_cell_blocks_all_exports(tmp_path):
    spec,_=fixture(tmp_path)
    with Image.open(tmp_path/'table.png') as image:
        draw=ImageDraw.Draw(image);draw.rectangle((310,160,560,225),fill=255)
        image.save(tmp_path/'table.png')
    path=tmp_path/'spec.json';path.write_text(json.dumps(spec))
    result=reconstruct(path,tmp_path/'run',export_cad=False)
    assert result['status']=='blocked'
    assert any(g['kind']=='ambiguous_table_cell' and g.get('section_id')=='s1' for g in result['gaps'])
    assert result['parts']==[] and result['exports']=={}
    assert not (tmp_path/'run'/'mesh.json').exists()


def test_undeclared_table_units_block_before_ocr(tmp_path):
    spec,_=fixture(tmp_path)
    del spec['table_value_units']
    path=tmp_path/'spec.json';path.write_text(json.dumps(spec))
    result=reconstruct(path,tmp_path/'run',export_cad=False)
    assert result['status']=='blocked'
    assert any(g['kind']=='table_units_unresolved' for g in result['gaps'])
    assert result['sections']==[]
