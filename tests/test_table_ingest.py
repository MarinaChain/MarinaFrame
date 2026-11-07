from pathlib import Path
import math

import pytest
from PIL import Image, ImageDraw

from vessel_reconstruction.fonts import dejavu_sans
from vessel_reconstruction.table_ingest import extract_table_sections, parse_feet_inches_eighths


def test_exact_feet_inches_eighths_unit_conversion():
    value,token=parse_feet_inches_eighths('18-7-4')
    assert token=='18-7-4'
    assert value==pytest.approx((18+7.5/12)*.3048)
    assert parse_feet_inches_eighths(' 0 - 0 - 1 ')[0]==pytest.approx(.0254/8)


@pytest.mark.parametrize('bad',['18-12-0','18-7-8','18-7','18.74','I8-7-4','-18-7-4','18-74','18874',''])
def test_ambiguous_notation_never_gets_repaired(bad):
    with pytest.raises(ValueError):
        parse_feet_inches_eighths(bad)


def table_fixture(path:Path):
    image=Image.new('L',(300,400),255)
    draw=ImageDraw.Draw(image)
    font=dejavu_sans(34)
    cells=[]
    tokens=['1-0-0','2-3-4','3-6-0','4-8-2','5-10-6']
    for i,text in enumerate(tokens):
        y=10+i*75
        draw.text((20,y+8),text,fill=0,font=font)
        cells.append({'z_m':float(i),'roi_px':[10,y,260,y+65]})
    image.save(path/'table.png')
    spec={'input_mode':'offset_table_ocr','units':'m','table_value_units':'feet_inches_eighths',
          'source':{'file':'table.png'},'sections':[{'id':'s1','x_m':0.0,'roi_px':[0,0,280,390],
          'evidence':'Cell regions and waterline values explicitly declared for unit fixture','cells':cells}]}
    return spec,tokens


def test_source_table_values_only_are_observed(tmp_path):
    spec,tokens=table_fixture(tmp_path)
    result=extract_table_sections(spec,tmp_path)
    assert not result['gaps'],result
    assert len(result['sections'])==1
    observed=result['sections'][0]['points_yz_m']
    for point,token in zip(observed,tokens):
        assert point[0]==pytest.approx(parse_feet_inches_eighths(token)[0])
    assert len(result['cell_evidence'])==5
    assert len(result['diagnostics']['language_model']['sha256'])==64
    assert all(e['corrections_applied']==[] for e in result['cell_evidence'])


def test_erased_required_cell_blocks_section(tmp_path):
    spec,_=table_fixture(tmp_path)
    with Image.open(tmp_path/'table.png') as image:
        draw=ImageDraw.Draw(image);draw.rectangle((0,160,299,225),fill=255)
        image.save(tmp_path/'table.png')
    result=extract_table_sections(spec,tmp_path)
    assert not result['sections']
    assert any(g['kind']=='ambiguous_table_cell' for g in result['gaps'])


def test_answers_are_not_allowed_in_cell_metadata(tmp_path):
    spec,_=table_fixture(tmp_path)
    spec['sections'][0]['cells'][0]['value_m']=99
    result=extract_table_sections(spec,tmp_path)
    assert not result['sections']
    assert any(g['kind']=='geometry_in_input' for g in result['gaps'])


def test_cell_cannot_silently_read_another_column(tmp_path):
    spec,_=table_fixture(tmp_path)
    spec['sections'][0]['cells'][0]['roi_px']=[281,10,299,75]
    result=extract_table_sections(spec,tmp_path)
    assert not result['sections']
    assert any(g['kind']=='invalid_table_cell' for g in result['gaps'])


def test_enormous_station_integer_is_a_table_gap(tmp_path):
    spec,_=table_fixture(tmp_path)
    spec['sections'][0]['x_m']=10**400
    result=extract_table_sections(spec,tmp_path)
    assert not result['sections']
    assert any(g['kind']=='missing_station' for g in result['gaps'])
