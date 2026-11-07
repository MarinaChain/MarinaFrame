"""An unobserved lower-boundary ordinate stays inside touching boundary-row ink."""
import json

import numpy as np
from PIL import Image, ImageDraw

from vessel_reconstruction.ingest import _lower_boundary_run_end, extract_sections

CENTRE, BASE, HEIGHT, SCALE = 20, 250, 210, 70.


def tangent_source(tmp_path, *, baseline_ruler=True):
    """A dark curve that is nearly horizontal at a pale baseline ruler.

    On the boundary row the dark stroke and the pale ruler form one broad run.
    Only contrast separates the stroke, so the trace has no boundary-row
    observation and the lowest centroid lies above the boundary.
    """
    image = Image.new("RGB", (260, 290), "white")
    draw = ImageDraw.Draw(image)
    draw.line((CENTRE, 25, CENTRE, BASE), fill=(205,) * 3)
    if baseline_ruler:
        draw.line((CENTRE, BASE, CENTRE + 230, BASE), fill=(205,) * 3)
    xx = np.linspace(0, 150, 1201)
    points = [(round(CENTRE + float(x)), round(BASE - HEIGHT * float(x / 150) ** 5)) for x in xx]
    draw.line(points, fill=(20,) * 3, width=1)
    image.save(tmp_path / "drawing.png")
    spec = {"schema_version": "1.0", "vessel_id": "boundary-run", "units": "m",
            "source": {"file": "drawing.png"},
            "sections": [{"id": "s0", "x_m": 0., "roi_px": [5, 20, 255, 270],
                          "calibration": {"centerline_px": CENTRE, "baseline_px": BASE,
                                          "pixels_per_metre": SCALE},
                          "z_min_m": 0., "z_max_m": 3.}]}
    (tmp_path / "spec.json").write_text(json.dumps(spec))
    return spec, np.asarray(image.convert("L"))


def test_boundary_ordinate_is_bounded_by_touching_boundary_ink(tmp_path):
    spec, raster = tangent_source(tmp_path)
    result = extract_sections(spec, tmp_path)
    assert not result["gaps"], result["gaps"]
    record = result["diagnostics"]["sections"]["s0"]["lower_boundary_run_end"]
    assert record is not None
    points = np.asarray(result["sections"][0]["points_yz_m"])
    boundary_px = points[0, 0] * SCALE + CENTRE
    # Independent comparator: the last dark stroke pixel on the boundary row.
    dark = np.flatnonzero(raster[BASE] < 100)
    assert boundary_px == float(dark.max())
    # The previous behaviour held the lowest centroid, beyond all boundary ink.
    assert record["lowest_centroid_local_px"] + CENTRE > dark.max()
    assert points[0, 1] == 0.


def test_no_boundary_record_without_contrast_separated_boundary_ink(tmp_path):
    # Without the pale ruler the boundary-row stroke is observed directly.
    spec, _ = tangent_source(tmp_path, baseline_ruler=False)
    result = extract_sections(spec, tmp_path)
    assert result["diagnostics"]["sections"]["s0"]["lower_boundary_run_end"] is None


def test_boundary_run_end_requires_one_touching_run():
    mask = np.zeros((12, 80), dtype=bool)
    rows = np.arange(11, dtype=float)
    xs = np.full(11, 40.)
    mask[10, 38:43] = True
    # Separated by a gap of more than one pixel: no continuation.
    mask[11, 10:30] = True
    assert _lower_boundary_run_end(mask, rows, xs) is None
    # Touching run that descends inward ends at its last pixel.
    mask[11, 10:38] = True
    value, record = _lower_boundary_run_end(mask, rows, xs)
    assert value == 37. and record["method"] == "touching_boundary_run_end_v1"
    # A second touching run on the other side is ambiguous.
    mask[11, 43:60] = True
    mask[11, 38:43] = False
    assert _lower_boundary_run_end(mask, rows, xs) is None
    # The boundary row itself observed: nothing to bound.
    assert _lower_boundary_run_end(mask, np.arange(12, dtype=float), np.full(12, 40.)) is None
