"""Tone texture inside a broad ruler is not a separate stroke observation.

Authentic pattern (Balclutha HAER CA-54 sheet 7, 4x box-downsampled 1-bit scan):
the aliased edge of a waterline has dark and pale pixels along its length. The
contrast split of a broad run kept each dark speck as a short "stroke", so one
waterline row held 65 trace runs and the panel was refused as a resource limit
instead of being judged on its strokes. These rasters are synthetic.
"""
import json

import numpy as np
from PIL import Image, ImageDraw

from vessel_reconstruction.ingest import _eligible_trace_mask, _foreground, extract_sections

CENTRE, BASE, SCALE, WIDTH = 20, 250, 70., 460
RULER_ROW = 150


def textured_ruler(draw, row):
    """A broad ruler with periodic darker specks, as an aliased scanned line edge."""
    draw.line((CENTRE, row, CENTRE + 420, row), fill=(150,) * 3)
    for x in range(CENTRE + 2, CENTRE + 420, 5):
        draw.line((x, row, x + 1, row), fill=(60,) * 3)


def ruler_source(tmp_path, *, crossing=True):
    image = Image.new("RGB", (WIDTH, 290), "white")
    draw = ImageDraw.Draw(image)
    textured_ruler(draw, RULER_ROW)
    if crossing:  # The hull stroke is drawn over the ruler, as on a drawing.
        draw.line([(CENTRE + 30 + .4 * (BASE - y), y) for y in range(30, BASE + 1)], fill=(15,) * 3, width=3)
    image.save(tmp_path / "drawing.png")
    spec = {"schema_version": "1.0", "vessel_id": "ruler-texture", "units": "m",
            "source": {"file": "drawing.png"},
            "sections": [{"id": "s0", "x_m": 0., "roi_px": [5, 20, WIDTH - 5, 270],
                          "calibration": {"centerline_px": CENTRE, "baseline_px": BASE,
                                          "pixels_per_metre": SCALE},
                          "z_min_m": 0., "z_max_m": 3.}]}
    (tmp_path / "spec.json").write_text(json.dumps(spec))
    return spec, np.asarray(image)


def test_unsupported_specks_are_not_retained_but_a_crossing_stroke_is(tmp_path):
    _, raster = ruler_source(tmp_path)
    crop = raster[RULER_ROW - 5:RULER_ROW + 6, CENTRE:]
    mask, ink, _ = _foreground(crop)
    eligible, record = _eligible_trace_mask(mask, None, ink)
    row = 5
    assert not mask[row - 1, 120:].any() and not mask[row + 1, 120:].any()
    # Away from the crossing stroke, the specks have no ink above or below.
    assert not eligible[row, 120:].any()
    assert record["unsupported_contrast_subrun_count"] >= 60
    # The crossing stroke continues above and below the ruler and is retained.
    stroke = np.flatnonzero(raster[RULER_ROW, :, 0] < 30)
    assert stroke.size and eligible[row, stroke - CENTRE].all()
    assert record["retained_contrast_subrun_count"] >= 1


def test_stroke_running_along_a_thick_ruler_is_retained_row_by_row():
    # Procedural counterexample (degraded roundflare 271067, frame-17): a dark
    # stroke lies along a two-row ruler before it climbs away. The lower island
    # touches no ink outside the ruler; it connects only through the upper one.
    mask = np.zeros((20, 200), dtype=bool)
    ink = np.zeros(mask.shape)
    mask[9:11, :] = True
    ink[9:11, :] = 100.
    ink[10, 40:70] = 230.  # Stroke on the lower ruler row ...
    ink[9, 70:100] = 230.  # ... steps onto the upper ruler row ...
    mask[0:9, 100:103] = True  # ... and leaves the ruler upward.
    ink[0:9, 100:103] = 230.
    eligible, record = _eligible_trace_mask(mask, None, ink)
    assert eligible[9, 70:100].all() and eligible[10, 40:70].all()
    assert not eligible[9, :70].any() and not eligible[10, 70:].any()
    assert record["retained_contrast_subrun_count"] == 2


def test_ruler_texture_no_longer_exhausts_the_trace_budget(tmp_path):
    spec, _ = ruler_source(tmp_path)
    result = extract_sections(spec, tmp_path)
    # Before: 80+ specks on the ruler row exceeded the 64-run row budget and
    # the panel was refused with "resource_limit".
    assert not result["gaps"], result["gaps"]
    points = np.asarray(result["sections"][0]["points_yz_m"])
    ruler_z = (BASE - RULER_ROW) / SCALE
    near = points[np.argmin(np.abs(points[:, 1] - ruler_z))]
    expected_px = 30 + .4 * (BASE - RULER_ROW)
    assert abs(near[0] * SCALE - expected_px) <= 2.


def test_texture_alone_is_not_a_curve(tmp_path):
    spec, _ = ruler_source(tmp_path, crossing=False)
    result = extract_sections(spec, tmp_path)
    assert [gap["kind"] for gap in result["gaps"]] == ["missing_curve"]
