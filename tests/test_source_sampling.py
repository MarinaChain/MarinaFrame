"""A source feature must survive before CAD approximation is applied."""
import numpy as np
from PIL import Image, ImageDraw
import pytest

from vessel_reconstruction.ingest import _bounded_source_samples, extract_sections, DrawingError


def test_observed_chine_between_uniform_heights_is_retained(tmp_path):
    image = Image.new('L', (140, 550), 255)
    draw = ImageDraw.Draw(image)
    # A narrow, connected drafting feature between the regular output heights.
    # Direct row-centre observations provide an independent raster comparator.
    draw.line([(70, 20), (70, 268), (79, 270), (70, 272), (70, 532)], fill=15, width=1)
    image.save(tmp_path / 'source.png')
    spec = {'units': 'm', 'source': {'file': 'source.png'}, 'sections': [{
        'id': 'chine', 'x_m': 0., 'roi_px': [20, 10, 130, 540],
        'calibration': {'centerline_px': 25., 'baseline_px': 532., 'pixels_per_metre': 100.},
        'z_min_m': 0., 'z_max_m': 5.12}]}
    result = extract_sections(spec, tmp_path)
    assert not result['gaps'], result['gaps']
    points = np.asarray(result['sections'][0]['points_yz_m'])
    raster = np.asarray(image)
    observed_rows = np.arange(20, 533)
    observed_centres = np.asarray([np.flatnonzero(raster[row] < 100).mean() for row in observed_rows])
    z = (532. - observed_rows) / 100.
    recovered_px = np.interp(z, points[:, 1], points[:, 0]) * 100. + 25.
    assert np.max(np.abs(recovered_px - observed_centres)) <= .25 + 1e-9
    assert len(points) > 129
    diagnostic = result['diagnostics']['sections']['chine']['source_sampling']
    assert diagnostic['maximum_allowed_ordinate_deviation_px'] == .25
    assert diagnostic['output_point_count'] == len(points)
    # The old uniform-only representation demonstrably loses this observation.
    uniform_z = np.linspace(0., 5.12, 129)
    uniform_x = np.interp(uniform_z, z[::-1], observed_centres[::-1])
    assert np.max(np.abs(np.interp(z, uniform_z, uniform_x) - observed_centres)) > 1.


def test_source_sampling_retains_minimum_grid_and_zero_transition():
    rows = np.arange(513, dtype=float)
    xs = np.where(rows < 251, 20., 0.)
    z, x, diagnostic = _bounded_source_samples(rows, xs, baseline=512., trace_top=0,
        ppm=100., z_min=0., z_max=5.12, minimum_samples=129, centre_local=0.)
    assert all(np.any(z == p) for p in np.linspace(0., 5.12, 129))
    assert np.any((z == 2.61) & (x == 0.))
    assert np.any((z == 2.62) & (x == 20.))
    assert diagnostic['maximum_ordinate_deviation_px'] <= .25


def test_excessive_source_detail_refuses_instead_of_smoothing():
    rows = np.arange(2200, dtype=float)
    xs = 10. + (rows % 2) * 2.
    with pytest.raises(DrawingError, match='exceeds 1025') as caught:
        _bounded_source_samples(rows, xs, baseline=2199., trace_top=0, ppm=100.,
            z_min=0., z_max=21.99, minimum_samples=129, centre_local=0.)
    assert caught.value.kind == 'resource_limit'


def test_straight_source_keeps_the_requested_density():
    rows = np.arange(513, dtype=float)
    xs = 5. + rows / 8.
    z, x, diagnostic = _bounded_source_samples(rows, xs, baseline=512., trace_top=0,
        ppm=100., z_min=0., z_max=5.12, minimum_samples=129, centre_local=0.)
    assert len(z) == 129
    assert diagnostic['maximum_ordinate_deviation_px'] < 1e-12
