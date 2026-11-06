"""Small hostile metadata fixtures: never render or allocate a huge image."""
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import pytest
from PIL import Image

from vessel_reconstruction.resources import DEFAULT_POLICY, ResourceLimitError, inspect_source, validate_sources


def png(tmp_path, name='source.png', size=(20, 30)):
    path = tmp_path / name
    Image.new('RGB', size, 'white').save(path)
    return path


def test_raster_metadata_is_checked_before_decode(tmp_path):
    path = png(tmp_path)
    with patch.object(Image.Image, 'load', side_effect=AssertionError('must not decode')):
        metadata = inspect_source(path, {})
    assert metadata['pixels'] == 600
    assert metadata['decoded_bytes_estimate'] == 4800
    with pytest.raises(ResourceLimitError, match='pixel'):
        inspect_source(path, {}, policy=replace(DEFAULT_POLICY, pixels=500))


@pytest.mark.parametrize('dpi', [720000, 0, float('nan'), float('inf'), True, '144'])
def test_pdf_dpi_rejected_before_native_open(tmp_path, dpi):
    path = tmp_path / 'source.pdf'; path.write_bytes(b'%PDF-1.7\n')
    fitz = pytest.importorskip('fitz')
    with patch.object(fitz, 'open', side_effect=AssertionError('must reject before parser')):
        with pytest.raises(ResourceLimitError):
            inspect_source(path, {'render_dpi': dpi})


def test_pdf_page_pixel_dimensions_and_count_without_pixmap(tmp_path):
    fitz = pytest.importorskip('fitz')
    path = tmp_path / 'huge.pdf'
    document = fitz.open(); document.new_page(width=14400, height=14400); document.save(path); document.close()
    with patch.object(fitz.Page, 'get_pixmap', side_effect=AssertionError('no allocation')):
        with pytest.raises(ResourceLimitError):
            inspect_source(path, {'render_dpi': 300})
        with pytest.raises(ResourceLimitError, match='page dimensions'):
            inspect_source(path, {'render_dpi': 36}, policy=replace(DEFAULT_POLICY, pdf_dimension_pt=500))
    document = fitz.open(); document.new_page(width=72, height=72); document.new_page(width=72, height=72)
    path = tmp_path / 'pages.pdf'; document.save(path); document.close()
    with pytest.raises(ResourceLimitError, match='page count'):
        inspect_source(path, {}, policy=replace(DEFAULT_POLICY, pdf_pages=1))


def test_reference_has_own_selected_page_settings_and_aggregate_budget(tmp_path):
    fitz = pytest.importorskip('fitz')
    png(tmp_path)
    document = fitz.open(); document.new_page(width=72, height=72); document.save(tmp_path/'reference.pdf'); document.close()
    spec = {'source': {'file': 'source.png'}, 'station_reference': {'file': 'reference.pdf', 'render_dpi': 72}, 'sections': []}
    result = validate_sources(spec, tmp_path)
    assert result['station_reference']['width_px'] == 72
    spec['station_reference']['render_dpi'] = 720000
    with pytest.raises(ResourceLimitError):
        validate_sources(spec, tmp_path)
    spec['station_reference']['render_dpi'] = 72
    with pytest.raises(ResourceLimitError, match='Combined'):
        validate_sources(spec, tmp_path, policy=replace(DEFAULT_POLICY, aggregate_pixels=600))


def test_table_cell_count_and_resize_amplification_are_bounded(tmp_path):
    png(tmp_path, size=(1000, 120))
    spec = {'source': {'file': 'source.png'}, 'input_mode': 'offset_table_ocr', 'sections': [{'roi_px': [0,0,1000,120], 'cells': [{'roi_px': [0,0,1000,1]}]}]}
    with pytest.raises(ResourceLimitError, match='enlarged OCR'):
        validate_sources(spec, tmp_path)
    spec['sections'][0]['cells'] = [{'roi_px': [0,0,10,20]}] * 513
    with pytest.raises(ResourceLimitError, match='cell count'):
        validate_sources(spec, tmp_path)


def test_multiframe_and_byte_budget_are_explicit(tmp_path):
    path = tmp_path/'frames.tiff'
    image = Image.new('RGB',(4,4),'white'); image.save(path, save_all=True, append_images=[image])
    with pytest.raises(ResourceLimitError, match='Multi-frame'):
        inspect_source(path, {})
    with pytest.raises(ResourceLimitError, match='file-byte'):
        inspect_source(path, {}, policy=replace(DEFAULT_POLICY, source_bytes=2))


def test_header_bomb_does_not_allocate(tmp_path):
    path = png(tmp_path)
    # Header-only object emulates dimensions in a tiny highly compressed raster.
    class Header:
        width = 100_000
        height = 100_000
        format = 'PNG'
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def verify(self): raise AssertionError('budget must precede image verification')
    with patch('PIL.Image.open', return_value=Header()):
        with pytest.raises(ResourceLimitError):
            inspect_source(path, {})
