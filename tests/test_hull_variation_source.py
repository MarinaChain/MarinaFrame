"""Public IGES sampler uses explicit source coordinate conventions."""
import numpy as np
import pytest


@pytest.mark.cad
@pytest.mark.parametrize('direction', [1, -1])
def test_sample_synthetic_half_hull(tmp_path, direction):
    from vessel_reconstruction.hull_variation_source import sample_iges
    from OCP.IGESControl import IGESControl_Writer
    import cadquery as cq
    surface = cq.Face.makePlane(100, 12, (50, 10, direction * 6), (0, 1, 0))
    path = tmp_path / 'half.igs'
    writer = IGESControl_Writer('MM', 0)
    writer.AddShape(surface.wrapped)
    assert writer.Write(str(path))
    hull = sample_iges(path, source_aft_x=0, length_m=100, breadth_m=20,
                       keel_z=0, draft_m=10, depth_m=12, parallel_body_m=(30, 70),
                       stations=11, heights=13, source_z_direction=direction)
    np.testing.assert_allclose(hull.half_breadths_m, 10, atol=1e-6)
    assert hull.x_m[-1] == pytest.approx(100)
    metres = tmp_path / 'metres.igs'
    metre_writer = IGESControl_Writer('M', 0)
    metre_writer.AddShape(surface.wrapped)
    assert metre_writer.Write(str(metres))
    with pytest.raises(ValueError, match='MM'):
        sample_iges(metres, source_aft_x=0, length_m=100, breadth_m=20,
                    keel_z=0, draft_m=10, depth_m=12, parallel_body_m=(30, 70),
                    stations=4, heights=5, source_z_direction=direction)
    inner = surface.translate((0, -5, 0))
    writer = IGESControl_Writer('MM', 0)
    writer.AddShape(surface.wrapped)
    writer.AddShape(inner.wrapped)
    multi = tmp_path / 'multi.igs'
    assert writer.Write(str(multi))
    with pytest.raises(ValueError, match='multiple'):
        sample_iges(multi, source_aft_x=0, length_m=100, breadth_m=20,
                    keel_z=0, draft_m=10, depth_m=12, parallel_body_m=(30, 70),
                    stations=4, heights=5, source_z_direction=direction)
    with pytest.raises(ValueError, match='Missing shell'):
        sample_iges(path, source_aft_x=0, length_m=100, breadth_m=20,
                    keel_z=0, draft_m=10, depth_m=14, parallel_body_m=(30, 70),
                    stations=4, heights=5, source_z_direction=direction)
