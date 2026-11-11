"""Draft .3dm faces: exact NURBS or trimmed planes, with labelled mesh fallbacks."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, TYPE_CHECKING

from .errors import GeometryError

if TYPE_CHECKING:
    import cadquery as cq
    import rhino3dm as rhino

# Rhino 8 is the file format supported by the pinned rhino3dm 8.x dependency.
RHINO_FILE_VERSION = 8
# Area differences above 0.5% identify material removed by trims rather than
# integration roundoff. Inner wires are checked separately, even for tiny holes.
TRIMMED_FACE_AREA_RELATIVE_TOLERANCE = 0.005
# Integrate much more accurately than the trim threshold; distances are in mm.
AREA_INTEGRATION_RELATIVE_TOLERANCE = 1e-8
PLANAR_TOLERANCE_MM = 1e-7
# Absolute chord deflection and angular deflection for explicitly labelled meshes.
MESH_DEFLECTION_MM = 0.5
MESH_ANGULAR_DEFLECTION_RAD = 0.1
RHINO_NOTES = (
    "MarinaFrame DRAFT: not for construction. engineering_approved=false. Units mm.\n"
    "Geometry: exact untrimmed NURBS surfaces and exact trimmed planes. "
    "Trimmed curved faces and planar inner holes use a labelled mesh fallback. "
    "Each mesh records its fallback reason and inner-hole count. "
    "Representation counts are in document user text. Use STEP for solid topology."
)


@dataclass(frozen=True)
class CadPart:
    """One named part, with millimetre geometry and its output layer."""

    part_id: str
    shape: cq.Shape
    layer: str


def _expanded_knots(surface, direction: str) -> list[float]:
    """Convert OCC's unique knots and multiplicities to the OpenNURBS sequence."""
    knot = getattr(surface, f"{direction}Knot")
    multiplicity = getattr(surface, f"{direction}Multiplicity")
    count = getattr(surface, f"Nb{direction}Knots")()
    expanded = [knot(i) for i in range(1, count + 1) for _ in range(multiplicity(i))]
    # OpenNURBS omits the first and last knot from the full clamped knot vector.
    return expanded[1:-1]


def _nurbs_surface(face: cq.Face) -> rhino.NurbsSurface:
    """Copy a bounded OCC support surface, including rational weights and placement."""
    import rhino3dm as rhino
    from OCP.BRep import BRep_Tool
    from OCP.BRepTools import BRepTools
    from OCP.Geom import Geom_BSplineSurface, Geom_RectangularTrimmedSurface
    from OCP.GeomConvert import GeomConvert
    from OCP.TopAbs import TopAbs_REVERSED

    # Surface_s applies the face location. Convert the surface directly: OCC's
    # whole-face NURBS converter can drop a BSpline surface after it is meshed.
    support = BRep_Tool.Surface_s(face.wrapped)
    bounds = BRepTools.UVBounds_s(face.wrapped)
    if isinstance(support, Geom_BSplineSurface):
        source = support.Copy()
        source.Segment(*bounds)
    else:
        bounded = Geom_RectangularTrimmedSurface(support, *bounds)
        source = GeomConvert.SurfaceToBSplineSurface_s(bounded)
    source.SetUNotPeriodic()
    source.SetVNotPeriodic()
    # A separate surface has no OCC face orientation flag. Reverse its U
    # direction when needed to preserve the face normal for later edits.
    if face.wrapped.Orientation() == TopAbs_REVERSED:
        source.UReverse()
    rational = source.IsURational() or source.IsVRational()
    surface = rhino.NurbsSurface.Create(3, rational, source.UDegree() + 1, source.VDegree() + 1,
                                       source.NbUPoles(), source.NbVPoles())
    if surface is None:
        raise GeometryError("The 3dm NURBS surface could not be created.")
    for u in range(1, source.NbUPoles() + 1):
        for v in range(1, source.NbVPoles() + 1):
            pole, weight = source.Pole(u, v), source.Weight(u, v)
            # OCC stores Cartesian poles; OpenNURBS uses homogeneous control points.
            surface.Points[u - 1, v - 1] = rhino.Point4d(
                pole.X() * weight, pole.Y() * weight, pole.Z() * weight, weight)
    for target, direction in ((surface.KnotsU, "U"), (surface.KnotsV, "V")):
        knots = _expanded_knots(source, direction)
        if len(knots) != len(target):
            raise GeometryError("The 3dm NURBS knot count does not match its control points.")
        for index, value in enumerate(knots):
            target[index] = value
    if not surface.IsValid:
        raise GeometryError("The converted 3dm NURBS surface is invalid.")
    return surface


def _surface_area(face) -> float:
    """Measure the exact OCC surface, without using an existing triangulation."""
    from OCP.BRepGProp import BRepGProp
    from OCP.GProp import GProp_GProps

    properties = GProp_GProps()
    BRepGProp.SurfaceProperties_s(face, properties, Eps=AREA_INTEGRATION_RELATIVE_TOLERANCE)
    return properties.Mass()


def _is_trimmed(face: cq.Face) -> bool:
    """Compare actual face area with its rectangular UV support patch."""
    from OCP.BRep import BRep_Tool
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeFace
    from OCP.BRepTools import BRepTools

    support = BRep_Tool.Surface_s(face.wrapped)
    rectangle = BRepBuilderAPI_MakeFace(support, *BRepTools.UVBounds_s(face.wrapped), PLANAR_TOLERANCE_MM)
    if not rectangle.IsDone():
        raise GeometryError("The 3dm face's support area could not be measured.")
    face_area = _surface_area(face.wrapped)
    support_area = _surface_area(rectangle.Face())
    return abs(face_area - support_area) > TRIMMED_FACE_AREA_RELATIVE_TOLERANCE * support_area


def _outer_boundary(face: cq.Face) -> rhino.PolyCurve:
    """Copy the ordered outer wire as exact, placed NURBS curves in millimetres."""
    import rhino3dm as rhino
    from OCP.BRep import BRep_Tool
    from OCP.BRepAdaptor import BRepAdaptor_Curve
    from OCP.BRepTools import BRepTools, BRepTools_WireExplorer
    from OCP.Geom import Geom_TrimmedCurve
    from OCP.GeomConvert import GeomConvert
    from OCP.TopAbs import TopAbs_REVERSED

    boundary = rhino.PolyCurve()
    explorer = BRepTools_WireExplorer(BRepTools.OuterWire_s(face.wrapped), face.wrapped)
    while explorer.More():
        edge = explorer.Current()
        adaptor = BRepAdaptor_Curve(edge)
        support = BRep_Tool.Curve_s(edge, 0, 0)
        trimmed = Geom_TrimmedCurve(support, adaptor.FirstParameter(), adaptor.LastParameter())
        source = GeomConvert.CurveToBSplineCurve_s(trimmed)
        source.SetNotPeriodic()
        if edge.Orientation() == TopAbs_REVERSED:
            source.Reverse()
        curve = rhino.NurbsCurve(3, source.IsRational(), source.Degree() + 1, source.NbPoles())
        for index in range(1, source.NbPoles() + 1):
            pole, weight = source.Pole(index), source.Weight(index)
            curve.Points[index - 1] = rhino.Point4d(pole.X() * weight, pole.Y() * weight,
                                                   pole.Z() * weight, weight)
        knots = [source.Knot(i) for i in range(1, source.NbKnots() + 1)
                 for _ in range(source.Multiplicity(i))][1:-1]
        for index, value in enumerate(knots):
            curve.Knots[index] = value
        if not curve.IsValid or not boundary.Append(curve):
            raise GeometryError("The 3dm planar face boundary could not be converted.")
        explorer.Next()
    return boundary


def _trimmed_plane(face: cq.Face):
    """Return an exact trimmed plane, or None when the support is not planar."""
    import rhino3dm as rhino
    from OCP.BRep import BRep_Tool
    from OCP.GeomLib import GeomLib_IsPlanarSurface

    planarity = GeomLib_IsPlanarSurface(BRep_Tool.Surface_s(face.wrapped), PLANAR_TOLERANCE_MM)
    if not planarity.IsPlanar():
        return None
    origin = planarity.Plan().Location()
    normal = face.normalAt()
    plane = rhino.Plane(rhino.Point3d(origin.X(), origin.Y(), origin.Z()),
                        rhino.Vector3d(normal.x, normal.y, normal.z))
    brep = rhino.Brep.CreateTrimmedPlane(plane, _outer_boundary(face))
    if brep is None or not brep.IsValid:
        raise GeometryError("The 3dm trimmed plane could not be created.")
    return brep


def _mesh_face(face: cq.Face) -> rhino.Mesh:
    """Tessellate the actual trimmed face, with absolute deflection in millimetres."""
    import rhino3dm as rhino
    from OCP.BRepMesh import BRepMesh_IncrementalMesh

    from . import topology

    BRepMesh_IncrementalMesh(face.wrapped, MESH_DEFLECTION_MM, False, MESH_ANGULAR_DEFLECTION_RAD, False)
    # The same values as face.tessellate, without its slow OCP iteration end.
    vertices, triangles = topology.face_triangulation(face, MESH_DEFLECTION_MM, MESH_ANGULAR_DEFLECTION_RAD)
    mesh = rhino.Mesh()
    mesh.Vertices.UseDoublePrecisionVertices = True
    for x, y, z in vertices.tolist():
        mesh.Vertices.AddPoint3d(x, y, z)
    for triangle in triangles.tolist():
        mesh.Faces.AddFace(*triangle)
    if not mesh.IsValid:
        raise GeometryError("The 3dm trimmed face mesh is invalid.")
    return mesh


def export_3dm(parts: Iterable[CadPart], path: Path) -> dict[str, int]:
    """Write named, layered faces in millimetres and return representation counts."""
    import rhino3dm as rhino
    from . import topology

    model = rhino.File3dm()
    model.Settings.ModelUnitSystem = rhino.UnitSystem.Millimeters
    model.ApplicationName = "MarinaFrame"
    # This API has no native Notes setter. Keep notes in the file comments and
    # document user text, both of which survive a rhino3dm write/read cycle.
    model.StartSectionComments = RHINO_NOTES
    model.Strings["Notes"] = RHINO_NOTES
    model.Strings["engineering_approved"] = "false"
    counts = {"exact_untrimmed": 0, "exact_trimmed_plane": 0, "mesh_fallback": 0}
    layers = {}
    for part in parts:
        if part.layer not in layers:
            layer = rhino.Layer()
            layer.Name = part.layer
            layers[part.layer] = model.Layers.Add(layer)
        # topology lists the same faces and wires as Faces() and Wires(), by index:
        # the end of an OCP iteration costs about 6 ms, once per call (topology.py).
        for index, face in enumerate(topology.faces(part.shape)):
            attributes = rhino.ObjectAttributes()
            attributes.Name = part.part_id
            attributes.LayerIndex = layers[part.layer]
            attributes.SetUserString("source_face_index", str(index))
            inner_holes = max(0, len(topology.wires(face)) - 1)
            if not inner_holes and not _is_trimmed(face):
                model.Objects.AddSurface(_nurbs_surface(face), attributes)
                counts["exact_untrimmed"] += 1
                continue
            if not inner_holes:
                plane = _trimmed_plane(face)
                if plane is not None:
                    model.Objects.AddBrep(plane, attributes)
                    counts["exact_trimmed_plane"] += 1
                    continue
            attributes.SetUserString("approximation", "mesh")
            attributes.SetUserString("inner_hole_count", str(inner_holes))
            reason = "inner_holes_not_supported" if inner_holes else "non_planar_trim"
            attributes.SetUserString("fallback_reason", reason)
            model.Objects.AddMesh(_mesh_face(face), attributes)
            counts["mesh_fallback"] += 1
    for key, value in counts.items():
        model.Strings[key] = str(value)
    if not model.Write(str(path), RHINO_FILE_VERSION):
        raise GeometryError("The 3dm file could not be written.")
    return counts
