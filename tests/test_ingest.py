"""Behavioral parser tests; expected curves are never passed to ingestion."""
from pathlib import Path
import json

import numpy as np
from PIL import Image, ImageDraw, ImageFilter
import pytest

from vessel_reconstruction.ingest import extract_sections


def _drawing(tmp_path: Path, *, degraded=False, color=False, extra=False, axes=True):
    im = Image.new('RGB', (420, 420), 'white')
    draw = ImageDraw.Draw(im)
    cx, base, ppm = 90, 360, 60
    z = np.linspace(0, 5, 1201)
    breadth = 3.6 * np.sqrt(1 - (1 - z / 5) ** 2)
    curve = [(cx + y * ppm, base - zz * ppm) for y, zz in zip(breadth, z)]
    if axes:
        for zz in range(6):
            draw.line((cx, base-zz*ppm, 350, base-zz*ppm), fill=(225,225,225), width=1)
        draw.line((cx, 45, cx, base), fill=(90,90,90), width=1)
        draw.line((cx, base, 345, base), fill=(90,90,90), width=1)
    draw.line(curve, fill=(0, 120, 200) if color else (15,15,15), width=3)
    if extra:
        draw.line([(px-30 if px>cx+40 else px, py) for px,py in curve], fill='black', width=2)
    if degraded:
        im = im.filter(ImageFilter.GaussianBlur(.55))
        array = np.asarray(im).astype(float)
        random = np.random.default_rng(9)
        array += random.normal(0, 9, array.shape)
        speckles = random.random(array.shape[:2]) < .001
        array[speckles] = 30
        im = Image.fromarray(np.clip(array,0,255).astype('uint8'))
    im.save(tmp_path/'drawing.png')
    spec = {'units':'m', 'source':{'file':'drawing.png'}, 'sections':[{
        'id':'station', 'x_m':12.5, 'roi_px':[65,40,350,375],
        'calibration':{'centerline_px':cx,'baseline_px':base,'pixels_per_metre':ppm},
        'z_min_m':0.,'z_max_m':5., 'evidence':'Manually calibrated test drawing'}]}
    return spec


@pytest.mark.parametrize('degraded,color', [(False,False),(True,False),(False,True),(True,True)])
def test_measures_pixel_curve(tmp_path, degraded, color):
    spec=_drawing(tmp_path,degraded=degraded,color=color)
    result=extract_sections(spec,tmp_path)
    assert result['gaps']==[], result
    section=result['sections'][0]
    points=np.array(section['points_yz_m'])
    expected=3.6*np.sqrt(1-(1-points[:,1]/5)**2)
    # Raster quantization and the steep near-keel curve bound accuracy.
    assert np.sqrt(np.mean((points[:,0]-expected)**2)) < .045
    assert np.max(np.abs(points[3:,0]-expected[3:])) < .055
    assert len(points)>=65
    assert section['coverage']>.95
    assert section['x_m']==12.5
    assert 'human_assistance' in section['evidence']
    json.dumps(result,allow_nan=False)


def test_missing_scale_abstains(tmp_path):
    spec=_drawing(tmp_path)
    del spec['sections'][0]['calibration']['pixels_per_metre']
    result=extract_sections(spec,tmp_path)
    assert result['sections']==[]
    assert result['gaps'][0]['kind']=='missing_scale'
    assert result['gaps'][0]['severity']=='blocking'


def test_blank_abstains(tmp_path):
    spec=_drawing(tmp_path)
    Image.new('RGB',(420,420),'white').save(tmp_path/'drawing.png')
    result=extract_sections(spec,tmp_path)
    assert result['sections']==[]
    assert result['gaps'][0]['kind']=='missing_curve'


def test_noisy_blank_abstains(tmp_path):
    spec=_drawing(tmp_path)
    random=np.random.default_rng(4)
    image=np.full((420,420,3),255,dtype='uint8')
    image[random.random((420,420))<.015]=0
    Image.fromarray(image).save(tmp_path/'drawing.png')
    result=extract_sections(spec,tmp_path)
    assert result['sections']==[]
    assert result['gaps']


def test_overlapping_curves_abstain(tmp_path):
    spec=_drawing(tmp_path,extra=True,axes=False)
    result=extract_sections(spec,tmp_path)
    assert result['sections']==[]
    assert result['gaps'][0]['kind']=='ambiguous_curve'


def test_long_erasure_abstains(tmp_path):
    spec=_drawing(tmp_path,axes=False)
    with Image.open(tmp_path/'drawing.png') as im:
        draw=ImageDraw.Draw(im)
        draw.rectangle((90,180,349,220),fill='white')
        im.save(tmp_path/'drawing.png')
    result=extract_sections(spec,tmp_path)
    assert result['sections']==[]
    assert result['gaps'][0]['kind']=='missing_curve_segment'


def test_reference_data_does_not_affect_trace(tmp_path):
    spec=_drawing(tmp_path)
    before=extract_sections(spec,tmp_path)
    # Adversarial unused keys must not act as a geometry shortcut.
    spec['ground_truth']={'points_yz_m':[[999,0],[999,5]]}
    spec['shape_generating_parameters']={'radius':999}
    after=extract_sections(spec,tmp_path)
    assert before==after


def test_pdf_raster_adapter(tmp_path):
    import fitz
    spec=_drawing(tmp_path,axes=False)
    with fitz.open() as document:
        page=document.new_page(width=210,height=210)
        page.insert_image(page.rect,filename=str(tmp_path/'drawing.png'))
        document.save(tmp_path/'drawing.pdf')
    spec['source']={'file':'drawing.pdf','page_index':0,'render_dpi':144}
    result=extract_sections(spec,tmp_path)
    assert not result['gaps'],result
    assert result['diagnostics']['source']['input_form']=='pdf_rendered_to_raster'


def test_bad_roi_abstains(tmp_path):
    spec=_drawing(tmp_path)
    spec['sections'][0]['roi_px']=[65,40,9999,375]
    result=extract_sections(spec,tmp_path)
    assert result['sections']==[]
    assert result['gaps'][0]['kind']=='invalid_view'
