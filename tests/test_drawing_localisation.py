import numpy as np
import pytest

# benchmarks.localisation imports the factory renderer, which needs OpenCV (plan-raster extra).
pytest.importorskip('cv2', reason='the factory renderer needs the plan-raster extra (OpenCV)')


def test_crossing_interpolates_polyline_without_extrapolation():
    from benchmarks.localisation.drawings import crossing
    curve = np.array([[1., 1.], [3., 2.], [4., 4.]])
    assert crossing([curve], 1.5) == pytest.approx(2.)
    assert crossing([curve], 0.5) is None


def test_source_point_includes_affine_rotation():
    from benchmarks.localisation.drawings import project
    sheet = type('Sheet', (), {'centreline_px': {'s03': 20}, 'baseline_px': {'s03': 100}, 'ppm': 10})()
    params = {'layout': 'separate', 'geometry': {'matrix': [[1, .1, 7], [-.2, 1, 3]]}}
    assert project(sheet, params, 's03', 2, 3) == pytest.approx([54, 65])
