import numpy as np
import pytest


@pytest.mark.cad
def test_selected_surface_sampler_trims_to_supported_end_stations(tmp_path):
    import cadquery as cq
    from OCP.IGESControl import IGESControl_Writer
    from vessel_reconstruction.hull_waterlines import sample_supported_iges
    shell = cq.Face.makePlane(100, 12, (50, 10, 6), (0, 1, 0))
    path = tmp_path / 'shell.igs'
    writer = IGESControl_Writer('MM', 0)
    writer.AddShape(shell.wrapped)
    assert writer.Write(str(path))
    hull, report = sample_supported_iges(path, face_indices=[0], source_extent_m=(0, 100),
                                       source_z_levels_m=[1, 3, 5, 7, 9, 11],
                                       draft_source_z_m=9, interior_x_m=50,
                                       parallel_source_x_m=(30, 70), stations=21)
    assert hull.length_m == pytest.approx(100)
    assert hull.breadth_m == pytest.approx(20)
    assert report['selected_faces'] == [0]
    assert len(report['waterlines']) == 6
    assert report['keel_layer_excluded_m'] == 1


def test_common_closed_extent_reports_each_waterline_omission():
    from vessel_reconstruction.hull_waterlines import common_extent
    lines = [np.array([[0, 0], [20, 10], [80, 10], [100, 0]]),
             np.array([[5, 0], [20, 10], [80, 10], [95, 0]])]
    lo, hi, report = common_extent(lines, [0, 10], (0, 100))
    assert (lo, hi) == (5, 95)
    assert report[0]['left_omitted_m'] == 5
    assert report[1]['left_missing_m'] == 5
    assert report[0]['right_omitted_m'] == 5


def test_disjoint_waterline_is_rejected():
    from vessel_reconstruction.hull_waterlines import join_waterline
    with pytest.raises(ValueError, match='disconnected'):
        join_waterline([np.array([[0, 0], [10, 5]]), np.array([[20, 5], [30, 0]])])


def test_main_component_reports_disconnected_end_piece():
    from vessel_reconstruction.hull_waterlines import main_component
    parts = [np.array([[0, 0], [10, 3]]), np.array([[20, 5], [50, 10]]),
             np.array([[50, 10], [90, 0]])]
    line, excluded = main_component(parts, 50)
    assert line[0, 0] == 20
    assert line[-1, 0] == 90
    assert excluded == [[0.0, 10.0]]


def test_shared_patch_seam_is_joined_not_invented():
    from vessel_reconstruction.hull_waterlines import join_waterline
    result = join_waterline([np.array([[0, 0], [10, 5]]), np.array([[10, 5], [20, 0]])])
    np.testing.assert_allclose(result[[0, -1]], [[0, 0], [20, 0]])
