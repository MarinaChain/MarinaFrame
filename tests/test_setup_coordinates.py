import pytest
from PIL import Image

from vessel_reconstruction import llm_setup


def test_normalized_setup_maps_crop_margin_and_rounded_dimensions(tmp_path):
    source = tmp_path / 'source.png'
    Image.new('RGB', (2048, 1600), 'white').save(source)
    manifest = llm_setup.prepare_request(source, tmp_path / 'request', 'panel:P1', [233, 147, 2000, 1500])
    transform = manifest['context']['coordinate_transform']
    width, height = transform['image_size_px']
    content_width, content_height = transform['content_size_px']
    reply = {'panel_id': 'P1',
             'centreline_x_px': {'value': 1000 * (36 + content_width * .25) / width, 'evidence': 'axis'},
             'baseline_y_px': {'value': 1000 * (36 + content_height * .75) / height, 'evidence': 'base'},
             'scale_marks': [{'x_px': 36000 / width, 'y_px': 36000 / height,
                              'x2_px': 1000 * (36 + content_width) / width,
                              'y2_px': 1000 * (36 + content_height) / height}]}
    mapped = llm_setup.source_coordinates(reply, manifest)
    assert mapped['centreline_x_px']['value'] == pytest.approx(233 + 1767 * .25)
    assert mapped['baseline_y_px']['value'] == pytest.approx(147 + 1353 * .75)
    assert mapped['scale_marks'][0]['x_px'] == pytest.approx(233)
    assert mapped['scale_marks'][0]['y2_px'] == pytest.approx(1500)
    assert reply['centreline_x_px']['value'] != mapped['centreline_x_px']['value']


def test_normalized_coordinates_outside_frame_are_rejected(tmp_path):
    source = tmp_path / 'source.png'
    Image.new('RGB', (400, 400), 'white').save(source)
    manifest = llm_setup.prepare_request(source, tmp_path / 'request')
    with pytest.raises(ValueError, match='outside normalized'):
        llm_setup.source_coordinates({'panels': [{'box_px': [0, 0, 1040, 900]}]}, manifest)


def test_overview_maps_all_coordinate_fields_and_keeps_missing(tmp_path):
    source = tmp_path / 'source.png'
    Image.new('RGB', (400, 800), 'white').save(source)
    manifest = llm_setup.prepare_request(source, tmp_path / 'request')
    w, h = manifest['context']['coordinate_transform']['image_size_px']
    reply = {'panels': [{'box_px': [36000/w, 36000/h, 436000/w, 836000/h]}],
             'stations': [{'x_px': 36000/w, 'y_px': 36000/h}],
             'baseline_y_px': {'missing': 'not visible'}}
    mapped = llm_setup.source_coordinates(reply, manifest)
    assert mapped['panels'][0]['box_px'] == pytest.approx([0, 0, 400, 800])
    assert mapped['stations'][0]['x_px'] == pytest.approx(0)
    assert mapped['baseline_y_px'] == {'missing': 'not visible'}
