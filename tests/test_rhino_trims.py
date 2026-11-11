"""Trimmed .3dm geometry must stay inside the source faces."""
import math

import cadquery as cq
from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeFace
from OCP.BRepGProp import BRepGProp
from OCP.BRepPrimAPI import BRepPrimAPI_MakeHalfSpace
from OCP.GProp import GProp_GProps
from OCP.gp import gp_Dir, gp_Pln, gp_Pnt
import pytest
import rhino3dm as rhino
from scipy.integrate import quad

from vessel_reconstruction.geometry import build_hull
from vessel_reconstruction.rhino_exports import CadPart, export_3dm

# Allow kernel and archive roundoff, in the millimetre CAD unit.
BOUNDING_BOX_TOLERANCE_MM = 0.001
AREA_RELATIVE_TOLERANCE = 0.005


def occ_area(face):
    properties = GProp_GProps()
    BRepGProp.SurfaceProperties_s(face.wrapped, properties)
    return properties.Mass()


def trimmed_brep_area(brep, normal):
    """Integrate the written trim edges, independently of the OCC area calculation."""
    integral = 0
    for trim in brep.Faces[0].OuterLoop.Trims:
        edge = brep.Edges[trim.EdgeIndex]

        def integrand(t):
            point, tangent = edge.DerivativeAt(t, 1)
            return ((point.Y * tangent.Z - point.Z * tangent.Y) * normal.x
                    + (point.Z * tangent.X - point.X * tangent.Z) * normal.y
                    + (point.X * tangent.Y - point.Y * tangent.X) * normal.z) / 2

        value, _ = quad(integrand, edge.Domain.T0, edge.Domain.T1)
        integral += -value if trim.IsReversed else value
    return abs(integral)


def mesh_area(mesh):
    area = 0
    for triangle in mesh.Faces:
        a, b, c = [mesh.Vertices.Point3dAt(index) for index in triangle[:3]]
        ab = (b.X - a.X, b.Y - a.Y, b.Z - a.Z)
        ac = (c.X - a.X, c.Y - a.Y, c.Z - a.Z)
        cross = (ab[1] * ac[2] - ab[2] * ac[1], ab[2] * ac[0] - ab[0] * ac[2],
                 ab[0] * ac[1] - ab[1] * ac[0])
        area += math.sqrt(sum(value * value for value in cross)) / 2
    return area


def assert_inside_source_bounds(objects, shape):
    source = shape.BoundingBox()
    for obj in objects:
        bounds = obj.Geometry.GetTightBoundingBox()
        for low, high, expected_low, expected_high in (
            (bounds.Min.X, bounds.Max.X, source.xmin, source.xmax),
            (bounds.Min.Y, bounds.Max.Y, source.ymin, source.ymax),
            (bounds.Min.Z, bounds.Max.Z, source.zmin, source.zmax),
        ):
            assert low >= expected_low - BOUNDING_BOX_TOLERANCE_MM
            assert high <= expected_high + BOUNDING_BOX_TOLERANCE_MM


def clip_with_plane(shape, origin, normal, inside):
    plane = BRepBuilderAPI_MakeFace(gp_Pln(gp_Pnt(*origin), gp_Dir(*normal))).Face()
    half_space = BRepPrimAPI_MakeHalfSpace(plane, gp_Pnt(*inside)).Solid()
    return shape.intersect(cq.Shape.cast(half_space))


@pytest.mark.parametrize("fixture", ["cut_box", "flat_deck_hull"])
def test_planar_trims_keep_exact_areas_and_source_bounds(tmp_path, fixture):
    if fixture == "cut_box":
        shape = clip_with_plane(cq.Solid.makeBox(4000, 3000, 2000),
                                (4000, 0, 0), (1, 0.5, 0), (0, 0, 0))
    else:
        sections = [{"id": f"s{i}", "x_m": x, "points_yz_m": [[width, z * 0.5] for z in range(7)]}
                    for i, (x, width) in enumerate(((0, 0.8), (5, 2), (10, 1.2)))]
        shape, _ = build_hull(sections)
    path = tmp_path / f"{fixture}.3dm"
    counts = export_3dm([CadPart("hull", shape, "Hull")], path)
    model = rhino.File3dm.Read(str(path))
    assert counts["exact_trimmed_plane"] > 0
    assert counts["mesh_fallback"] == 0
    assert sum(counts.values()) == len(shape.Faces()) == len(model.Objects)
    source_faces = shape.Faces()
    for obj in model.Objects:
        face = source_faces[int(obj.Attributes.GetUserString("source_face_index"))]
        if isinstance(obj.Geometry, rhino.Brep):
            assert obj.Geometry.IsValid
            area = trimmed_brep_area(obj.Geometry, face.normalAt())
            assert area == pytest.approx(occ_area(face), rel=AREA_RELATIVE_TOLERANCE)
    assert_inside_source_bounds(model.Objects, shape)
    for key, value in counts.items():
        assert model.Strings[key] == str(value)


def test_circular_planar_trims_preserve_exact_rational_boundary(tmp_path):
    shape = cq.Solid.makeCylinder(1000, 2500)
    path = tmp_path / "round_tank.3dm"
    counts = export_3dm([CadPart("tank", shape, "Tanks")], path)
    model = rhino.File3dm.Read(str(path))
    assert counts == {"exact_untrimmed": 1, "exact_trimmed_plane": 2, "mesh_fallback": 0}
    for obj in model.Objects:
        if isinstance(obj.Geometry, rhino.Brep):
            face = shape.Faces()[int(obj.Attributes.GetUserString("source_face_index"))]
            assert trimmed_brep_area(obj.Geometry, face.normalAt()) == pytest.approx(math.pi * 1000**2,
                                                                                   rel=AREA_RELATIVE_TOLERANCE)
    # Rhino's rational-curve bounds include its control hull. Area is measured
    # from the actual trim curves above, rather than that conservative box.


def test_trimmed_curved_faces_use_counted_labelled_meshes(tmp_path):
    shape = clip_with_plane(cq.Solid.makeCylinder(1000, 3000),
                            (0, 0, 2000), (-0.5, 0, 1), (0, 0, 0))
    path = tmp_path / "trimmed_tank.3dm"
    counts = export_3dm([CadPart("tank", shape, "Tanks")], path)
    model = rhino.File3dm.Read(str(path))
    meshes = [obj for obj in model.Objects if isinstance(obj.Geometry, rhino.Mesh)]
    assert counts["mesh_fallback"] == len(meshes) == 1
    assert counts["exact_trimmed_plane"] == 2
    assert sum(counts.values()) == len(shape.Faces())
    for obj in meshes:
        assert obj.Geometry.IsValid and len(obj.Geometry.Faces) > 0
        assert obj.Attributes.Name == "tank"
        assert model.Layers[obj.Attributes.LayerIndex].Name == "Tanks"
        assert obj.Attributes.GetUserString("approximation") == "mesh"
        face = shape.Faces()[int(obj.Attributes.GetUserString("source_face_index"))]
        assert mesh_area(obj.Geometry) == pytest.approx(occ_area(face), rel=AREA_RELATIVE_TOLERANCE)
    for obj in model.Objects:
        if isinstance(obj.Geometry, rhino.Brep):
            face = shape.Faces()[int(obj.Attributes.GetUserString("source_face_index"))]
            assert trimmed_brep_area(obj.Geometry, face.normalAt()) == pytest.approx(
                occ_area(face), rel=AREA_RELATIVE_TOLERANCE)
    assert model.Strings["mesh_fallback"] == "1"
    assert "mesh fallback" in model.Strings["Notes"]
    assert_inside_source_bounds(meshes, shape)


@pytest.mark.parametrize("radius", [500, 10])
def test_planar_inner_holes_use_recorded_mesh_fallback(tmp_path, radius):
    plate = cq.Solid.makeBox(4000, 3000, 100).cut(
        cq.Solid.makeCylinder(radius, 200, cq.Vector(2000, 1500, -50)))
    face = next(face for face in plate.Faces() if len(face.Wires()) == 2)
    path = tmp_path / "plate_with_hole.3dm"
    counts = export_3dm([CadPart("deck", face, "Structure")], path)
    model = rhino.File3dm.Read(str(path))
    assert counts == {"exact_untrimmed": 0, "exact_trimmed_plane": 0, "mesh_fallback": 1}
    obj = model.Objects[0]
    assert isinstance(obj.Geometry, rhino.Mesh)
    assert obj.Attributes.GetUserString("approximation") == "mesh"
    assert obj.Attributes.GetUserString("inner_hole_count") == "1"
    assert obj.Attributes.GetUserString("fallback_reason") == "inner_holes_not_supported"
    assert mesh_area(obj.Geometry) == pytest.approx(occ_area(face), rel=AREA_RELATIVE_TOLERANCE)
    assert_inside_source_bounds(model.Objects, face)
