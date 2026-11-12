"""Experimental frame suppression never replaces the product intake."""
import numpy as np
import pytest

from vessel_reconstruction import lines_sheet_detection as detection


def connected_sheet():
    image = np.full((800, 1200), 255, dtype=np.uint8)
    # Long border ties otherwise distinct drawing panels together.
    image[20:780, 20:22] = 0
    image[20:22, 20:1180] = 0
    image[778:780, 20:1180] = 0
    image[20:780, 1178:1180] = 0
    from PIL import Image, ImageDraw
    picture = Image.fromarray(image)
    draw = ImageDraw.Draw(picture)
    for top in (150, 450):
        draw.line([(21, top), (200, top), (400, top + 90), (700, top + 40), (900, top)], fill=0, width=4)
    return np.asarray(picture)


def test_frame_suppression_separates_connected_long_views():
    result = detection.detect_sheet(connected_sheet(), words=[])
    boxes = [r["region_px"] for r in result["regions"]]
    assert len(boxes) >= 2
    assert max(b[3] - b[1] for b in boxes) < 400
    assert result["method"] == "experimental_frame_suppression_v1"


def test_blank_sheet_does_not_invent_region():
    result = detection.detect_sheet(np.full((300, 400), 255, dtype=np.uint8), words=[])
    assert result["regions"] == []


@pytest.mark.parametrize("dpi,expected", [(None, None), ((200, 200), 200 / .0254 / 25)])
def test_scale_ratio_needs_scan_dpi(dpi, expected):
    words = [{"text": 'SCALE 1:25', "bbox": [10, 250, 200, 275]}]
    result = detection.detect_sheet(np.full((300, 400), 255, dtype=np.uint8), words=words, dpi=dpi)
    assert result["scale"]["main_ratio"] == 25
    if expected is None:
        assert result["scale"]["pixels_per_metre"] is None
    else:
        assert result["scale"]["pixels_per_metre"] == pytest.approx(expected)


def test_mixed_scales_abstain_from_pixel_scale():
    words = [{"text": 'SCALE 1:25 SCALE 1:50', "bbox": [10, 250, 200, 275]}]
    result = detection.detect_sheet(np.full((300, 400), 255, dtype=np.uint8), words=words, dpi=(200, 200))
    assert result["scale"]["pixels_per_metre"] is None


def test_anisotropic_dpi_abstains_from_pixel_scale():
    words = [{"text": 'SCALE 1:25', "bbox": [10, 250, 200, 275]}]
    result = detection.detect_sheet(np.full((300, 400), 255, dtype=np.uint8), words=words, dpi=(200, 100))
    assert result["scale"]["pixels_per_metre"] is None
