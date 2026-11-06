"""Independent regression fixtures for line-weight/grid separation.

These are drawn directly here and do not use benchmark hull families or labels.
"""
import numpy as np
from PIL import Image, ImageDraw
import pytest

from vessel_reconstruction.ingest import extract_sections


def make_fixture(tmp_path, *, width=1, noise=0, grid=True, faint=False, second=False):
    image = Image.new("RGB", (320, 340), "white")
    draw = ImageDraw.Draw(image)
    cx, baseline, ppm = 25, 305, 55
    if grid:
        for x in range(cx, 300, 40):
            draw.line((x, 25, x, baseline), fill=(200, 200, 200), width=1)
        for y in range(30, baseline + 1, 50):
            draw.line((cx, y, 300, y), fill=(200, 200, 200), width=1)
    z = np.linspace(0, 5, 1501)
    breadth = 0.5 + 0.28 * z + 0.04 * z**2
    color = (175, 175, 175) if faint else (20, 20, 20)
    draw.line([(cx + y * ppm, baseline - zz * ppm) for y, zz in zip(breadth, z)], fill=color, width=width)
    if second:
        draw.line([(cx + (y + 0.8) * ppm, baseline - zz * ppm) for y, zz in zip(breadth, z)], fill=color, width=width)
    if noise:
        array = np.asarray(image).astype(float)
        array += np.random.default_rng(86751).normal(0, noise, array.shape)
        image = Image.fromarray(np.clip(array, 0, 255).astype("uint8"))
    image.save(tmp_path / "drawing.png")
    return {"units": "m", "source": {"file": "drawing.png"}, "sections": [{
        "id": "grid-fixture", "x_m": 2.0, "roi_px": [15, 25, 310, 315],
        "calibration": {"centerline_px": cx, "baseline_px": baseline, "pixels_per_metre": ppm},
        "z_min_m": 0, "z_max_m": 5,
        "evidence": "Independent grid and stroke fixture; no contour coordinates supplied to parser."
    }]}


@pytest.mark.parametrize("width,noise", [(1, 0), (3, 0), (1, 4), (3, 4)])
def test_dark_primary_curve_survives_lighter_grid(tmp_path, width, noise):
    spec = make_fixture(tmp_path, width=width, noise=noise)
    result = extract_sections(spec, tmp_path)
    assert not result["gaps"], result
    points = np.asarray(result["sections"][0]["points_yz_m"])
    expected = 0.5 + 0.28 * points[:, 1] + 0.04 * points[:, 1] ** 2
    assert np.sqrt(np.mean((points[:, 0] - expected) ** 2)) < 0.025


def test_uniformly_faint_contour_is_preserved(tmp_path):
    spec = make_fixture(tmp_path, width=2, grid=False, faint=True)
    result = extract_sections(spec, tmp_path)
    assert not result["gaps"], result
    assert result["sections"][0]["coverage"] > 0.98


def test_equally_dark_second_contour_still_blocks(tmp_path):
    spec = make_fixture(tmp_path, width=2, second=True)
    result = extract_sections(spec, tmp_path)
    assert result["sections"] == []
    assert any(g["kind"] == "ambiguous_curve" for g in result["gaps"])
