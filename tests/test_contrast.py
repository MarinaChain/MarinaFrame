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
def test_original_lighter_grid_fixture_requires_explicit_identity(tmp_path, width, noise):
    # Preserve the original pixels. A pale straight stroke may be a grid line
    # or the hull; contrast alone is insufficient to make that distinction.
    # The old automatic acceptance was intentional behaviour, now withdrawn.
    spec = make_fixture(tmp_path, width=width, noise=noise)
    result = extract_sections(spec, tmp_path)
    assert result["sections"] == []
    assert any(g["kind"] == "ambiguous_curve" for g in result["gaps"])
    diagnostic = result["diagnostics"]["sections"]["grid-fixture"]
    assert diagnostic["unresolved_candidate_count"] > 0
    assert diagnostic["candidate_evidence"]


@pytest.mark.parametrize("width,noise", [(1, 0), (3, 0), (1, 4), (3, 4)])
def test_same_grid_pixels_are_measured_after_explicit_source_selection(tmp_path, width, noise):
    spec = make_fixture(tmp_path, width=width, noise=noise)
    # Fixed, reviewable clicks in drawing pixels. They select a narrow band,
    # not a replacement contour: inference still measures the raster stroke.
    spec["sections"][0]["contour_selection"] = {
        "anchors_px": [[52, 305], [70, 250], [92, 195], [119, 140], [150, 85], [184, 30]],
        "half_width_px": 4,
    }
    result = extract_sections(spec, tmp_path)
    assert not result["gaps"], result
    points = np.asarray(result["sections"][0]["points_yz_m"])
    expected = 0.5 + 0.28 * points[:, 1] + 0.04 * points[:, 1] ** 2
    assert np.sqrt(np.mean((points[:, 0] - expected) ** 2)) < 0.025
    diagnostic = result["diagnostics"]["sections"]["grid-fixture"]
    assert diagnostic["identity_status"] == "explicit_supplied_pixel_selection"
    assert diagnostic["competing_candidate_count"] > 0
    assert not diagnostic["unresolved_candidate_count"]
    assert all(c["status"] == "excluded_by_explicit_pixel_selection" for c in diagnostic["candidate_evidence"])


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
