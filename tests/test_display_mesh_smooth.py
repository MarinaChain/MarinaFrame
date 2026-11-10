"""Display mesh of smooth B-spline walls (display_mesh.shape_mesh), synthetic."""
import numpy as np
import pytest

cq = pytest.importorskip('cadquery')
pytestmark = pytest.mark.cad


def _flared_house():
    """A 10 m house in millimetres (as the assembly meshes it) whose sides bulge and flare smoothly."""
    def section(z, half_breadth):
        def point(x, y):
            return cq.Vector(x * 1000, y * 1000, z * 1000)

        starboard = cq.Edge.makeSpline([point(0, -half_breadth), point(5, -half_breadth - 0.3), point(10, -half_breadth)])
        port = cq.Edge.makeSpline([point(10, half_breadth), point(5, half_breadth + 0.3), point(0, half_breadth)])
        fwd = cq.Edge.makeLine(point(10, -half_breadth), point(10, half_breadth))
        aft = cq.Edge.makeLine(point(0, half_breadth), point(0, -half_breadth))
        return cq.Wire.assembleEdges([starboard, fwd, port, aft])

    return cq.Solid.makeLoft([section(0.0, 4.0), section(1.0, 4.3), section(2.0, 4.4)], False)


def test_smooth_walls_mesh_closed_outward_and_shared(monkeypatch):
    from vessel_reconstruction import display_mesh
    from vessel_reconstruction.display_mesh import mesh_volume_mm3, shape_mesh
    from vessel_reconstruction.geometry import precise_volume_mm3

    solid = _flared_house()
    records = []
    monkeypatch.setattr(display_mesh, 'report_progress', lambda *args, **kwargs: records.append(args))
    assert any(face.geomType() == 'BSPLINE' for face in solid.Faces())
    vertices, triangles = shape_mesh(solid, 1.0, 0.5, smooth_tolerance_mm=2.0)
    total = len(solid.Faces())
    assert records == [('Making the display mesh', i, total) for i in range(total + 1)]
    # Outward and closed: the mesh holds the solid's volume (chords of 2 mm at most).
    assert mesh_volume_mm3(vertices, triangles) == pytest.approx(precise_volume_mm3(solid), rel=2e-3)
    # Grid vertices are shared between neighbouring triangles (smooth shading).
    assert len(vertices) < 1.5 * len(triangles)
    p = vertices[triangles]
    assert np.linalg.norm(np.cross(p[:, 1] - p[:, 0], p[:, 2] - p[:, 0]), axis=1).min() > 0
