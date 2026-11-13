import importlib

import numpy as np
import pytest

from vessel_reconstruction.cfd.surface import validate_surface


@pytest.fixture
def module():
    return importlib.import_module('vessel_reconstruction.cfd.section_mesh')


def test_box_closed_area_volume_and_draft_clip(module):
    sections = [dict(x_m=x, points_yz_m=[[1, 0], [1, 2]]) for x in (0, 2, 4)]
    triangles, metadata = module.build_section_mesh(sections, samples=9)
    validate_surface(triangles)
    assert module.mesh_particulars(triangles, 3)['volume_m3'] == pytest.approx(16)
    wet = module.mesh_particulars(triangles, 1)
    assert wet['volume_m3'] == pytest.approx(8)
    assert wet['wetted_area_m2'] == pytest.approx(20)
    assert metadata['station_count'] == 3


def test_v_bottom_wedge_is_closed_and_clips_exactly(module):
    sections = [dict(x_m=x, points_yz_m=[[0, 0], [1, 1], [1, 2]]) for x in (0, 2, 4)]
    triangles, metadata = module.build_section_mesh(sections, samples=11)
    validate_surface(triangles)
    wet = module.mesh_particulars(triangles, 1)
    assert wet['volume_m3'] == pytest.approx(4)
    assert wet['wetted_area_m2'] == pytest.approx(8 * np.sqrt(2) + 2)
    assert metadata['fixed_knot_count'] >= 3
    assert any(np.allclose(point, [0, 1, 1]) for triangle in triangles for point in triangle)


def test_centreline_roundoff_does_not_create_microscopic_facets(module):
    sections = [dict(x_m=x, points_yz_m=[[1e-18, 0], [1, 1], [1, 2]]) for x in (0, 2, 4)]
    triangles, metadata = module.build_section_mesh(sections, samples=11)
    assert metadata['centreline_weld_tolerance_m'] == 1e-8
    assert np.all((abs(triangles[:, :, 1]) == 0) | (abs(triangles[:, :, 1]) >= 1e-8))
    validate_surface(triangles)


def test_empty_centreline_interval_does_not_create_duplicate_skin(module):
    profile = [[1, 0], [0, 1], [0, 2], [1, 3]]
    sections = [dict(x_m=x, points_yz_m=profile) for x in (0, 2, 4)]
    triangles, _ = module.build_section_mesh(sections, samples=11)
    validate_surface(triangles)
    assert not any(np.all(triangle[:, 1] == 0) for triangle in triangles)


def test_isolated_collapsed_interval_reconnects_each_side_without_four_face_edge(module):
    wide = [[1, 0], [.2, 1], [.2, 2], [1, 3]]
    collapsed = [[1, 0], [0, 1], [0, 2], [1, 3]]
    sections = [dict(x_m=x, points_yz_m=p) for x, p in ((0, wide), (2, collapsed), (4, wide))]
    triangles, metadata = module.build_section_mesh(sections, samples=11)
    validate_surface(triangles)
    assert metadata['centreline_edge_flips'] > 0
    assert set(triangles[:, :, 0].ravel()) == {0, 2, 4}


def test_collapsed_bow_section_closes_without_end_cap_edges(module):
    sections = [dict(x_m=x, points_yz_m=[[y, 0], [y, 2]]) for x, y in ((0, 1), (2, 1), (4, 0))]
    triangles, metadata = module.build_section_mesh(sections, samples=9)
    validate_surface(triangles)
    assert module.mesh_particulars(triangles, 3)['volume_m3'] == pytest.approx(12)


def test_nonincreasing_stations_rejected(module):
    sections = [dict(x_m=0, points_yz_m=[[1, 0], [1, 2]])] * 2
    with pytest.raises(ValueError, match='increasing'):
        module.build_section_mesh(sections)
