"""Sub-shape lists and face triangulations (topology.py) equal CadQuery's, value for value."""
import numpy as np
import pytest

cq = pytest.importorskip('cadquery')
pytestmark = pytest.mark.cad


def _plate_with_hole():
    """A box with a cylindrical hole: faces with inner wires, a periodic face and a seam edge."""
    return cq.Workplane('XY').box(40, 30, 10).faces('>Z').workplane().hole(8).val()


def _same_shapes(ours, theirs):
    return len(ours) == len(theirs) and all(a.wrapped.IsEqual(b.wrapped) for a, b in zip(ours, theirs))


def test_lists_equal_cadquery_in_order():
    from vessel_reconstruction import topology

    solid = _plate_with_hole()
    assert _same_shapes(topology.faces(solid), solid.Faces())
    assert _same_shapes(topology.edges(solid), solid.Edges())
    assert _same_shapes(topology.wires(solid), solid.Wires())
    holed = [face for face in solid.Faces() if face.innerWires()]
    assert holed, 'the fixture must have a face with a hole'
    for face in solid.Faces():
        assert _same_shapes(topology.inner_wires(face), face.innerWires())
        assert _same_shapes(topology.edges(face), face.Edges())


def test_edges_leave_out_degenerated_edges_as_cadquery():
    from vessel_reconstruction import topology

    # A sphere's faces have degenerated edges at the poles.
    sphere = cq.Solid.makeSphere(10)
    assert _same_shapes(topology.edges(sphere), sphere.Edges())
    for face in sphere.Faces():
        assert _same_shapes(topology.edges(face), face.Edges())


@pytest.mark.parametrize('reverse', [False, True])
def test_face_triangulation_equals_tessellate(reverse):
    from vessel_reconstruction import topology

    tolerance, angular = 0.5, 0.3
    ours_solid, theirs_solid = _plate_with_hole(), _plate_with_hole()
    for ours, theirs in zip(ours_solid.Faces(), theirs_solid.Faces()):
        if reverse:
            ours, theirs = (cq.Face(face.wrapped.Reversed()) for face in (ours, theirs))
        vertices, triangles = topology.face_triangulation(ours, tolerance, angular)
        points, faces = theirs.tessellate(tolerance, angular)
        expected_vertices = np.array([[p.x, p.y, p.z] for p in points]).reshape(-1, 3)
        expected_triangles = np.asarray(faces, dtype=int).reshape(-1, 3)
        assert vertices.tobytes() == expected_vertices.tobytes()
        assert triangles.dtype == expected_triangles.dtype
        assert np.array_equal(triangles, expected_triangles)


def test_face_triangulation_applies_the_face_location():
    from vessel_reconstruction import topology

    moved = cq.Solid.makeBox(1, 2, 3).moved(cq.Location(cq.Vector(100, 0, 0)))
    for face in moved.Faces():
        vertices, _ = topology.face_triangulation(face, 0.1, 0.5)
        points, _ = face.tessellate(0.1, 0.5)
        assert vertices.tolist() == [[p.x, p.y, p.z] for p in points]
        assert vertices[:, 0].min() >= 100


def test_reused_volumes_integrates_each_object_once(monkeypatch):
    import OCP.BRepGProp

    from vessel_reconstruction.geometry import precise_volume_mm3, reused_volumes

    calls = []
    original = OCP.BRepGProp.BRepGProp

    class Counting:
        @staticmethod
        def VolumeProperties_s(*args):
            calls.append(args[0])
            return original.VolumeProperties_s(*args)

    monkeypatch.setattr(OCP.BRepGProp, 'BRepGProp', Counting)
    box = cq.Solid.makeBox(1, 2, 3)
    other = cq.Solid.makeBox(1, 2, 3)
    outside = precise_volume_mm3(box)
    with reused_volumes():
        first = precise_volume_mm3(box)
        assert precise_volume_mm3(box) == first == outside
        # A different object with the same geometry is integrated on its own.
        assert precise_volume_mm3(other) == first
        assert len(calls) == 3
        # An in-place change of the wrapped shape is not the kept value's shape.
        box.wrapped.Reverse()
        assert precise_volume_mm3(box) == pytest.approx(-first)
        assert len(calls) == 4
        with reused_volumes():  # a nested block shares the outer memo
            assert precise_volume_mm3(other) == first
        assert len(calls) == 4
    # Outside the block every call integrates again.
    precise_volume_mm3(other)
    assert len(calls) == 5


def test_closed_solid_reports_its_kernel_volume():
    from vessel_reconstruction.geometry import _closed_solid

    box = cq.Solid.makeBox(10, 20, 30)
    solid, volume = _closed_solid(box.Faces(), 'box')
    assert volume == solid.Volume() == pytest.approx(6000)
    # Reversed faces give a solid that is turned outward, with a positive volume.
    reversed_faces = [cq.Face(face.wrapped.Reversed()) for face in box.Faces()]
    solid, volume = _closed_solid(reversed_faces, 'reversed box')
    assert volume == solid.Volume() == pytest.approx(6000)
