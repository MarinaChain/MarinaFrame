"""Check synthetic CAD exports with OCC and rhino3dm, not Rhino or other CAD tools.

Run with PYTHONPATH=src:. .venv/bin/python scripts/check_cad_exports.py.
The default output folder is work/cad-export-check; no ship data is used.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from importlib.metadata import version
import json
from pathlib import Path

import cadquery as cq
import rhino3dm as rhino
from OCP.BRepAlgoAPI import BRepAlgoAPI_Common
from OCP.BRepBndLib import BRepBndLib
from OCP.BRepBuilderAPI import (BRepBuilderAPI_MakeEdge, BRepBuilderAPI_MakeFace,
                               BRepBuilderAPI_MakePolygon, BRepBuilderAPI_MakeSolid,
                               BRepBuilderAPI_MakeWire, BRepBuilderAPI_Sewing)
from OCP.BRepLib import BRepLib
from OCP.BRepGProp import BRepGProp
from OCP.BRepOffsetAPI import BRepOffsetAPI_MakeOffsetShape
from OCP.BRepPrimAPI import BRepPrimAPI_MakeHalfSpace
from OCP.Bnd import Bnd_Box
from OCP.Geom import Geom_BSplineCurve, Geom_BSplineSurface
from OCP.GProp import GProp_GProps
from OCP.IFSelect import IFSelect_RetDone
from OCP.IGESControl import IGESControl_Reader
from OCP.STEPControl import STEPControl_Reader
from OCP.TColgp import TColgp_Array1OfPnt, TColgp_Array2OfPnt
from OCP.TColStd import TColStd_Array1OfInteger, TColStd_Array1OfReal, TColStd_Array2OfReal
from OCP.gp import gp_Dir, gp_Pln, gp_Pnt

from vessel_reconstruction.cad_exports import export_iges
from vessel_reconstruction.geometry import build_hull
from vessel_reconstruction.rhino_exports import CadPart, export_3dm

# Exact CAD round-trips should retain volume to one part per million.
VOLUME_RELATIVE_TOLERANCE = 1e-6
# Ten micrometres in the millimetre CAD unit accommodates exchange-file roundoff.
BOUNDING_BOX_TOLERANCE_MM = 0.01
# One micrometre joins exported edges without closing physically meaningful gaps.
SEWING_TOLERANCE_MM = 0.001
# Match the exporter trim threshold, allowing the documented mesh approximation.
SURFACE_AREA_RELATIVE_TOLERANCE = 0.005
# Offset an isolated face by 1 mm, large enough to distinguish from roundoff.
FACE_OFFSET_MM = 1.0
FACE_OFFSET_TOLERANCE_MM = 0.001
# Reconstruction tolerance is smaller than the round-trip comparison tolerance.
REBUILD_TOLERANCE_MM = 1e-7
# Adaptive integration avoids coarse quadrature errors on rational cylinders.
AREA_INTEGRATION_RELATIVE_TOLERANCE = 1e-8
REPRESENTATION_KEYS = ("exact_untrimmed", "exact_trimmed_plane", "mesh_fallback")
PROJECT_ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class Fixture:
    name: str
    parts: tuple[CadPart, ...]

    @property
    def shape(self) -> cq.Shape:
        if len(self.parts) == 1:
            return self.parts[0].shape
        return cq.Compound.makeCompound([part.shape for part in self.parts])


def make_fixtures() -> list[Fixture]:
    """A variable-width flat-deck hull and three separate thin steel members.

    The lower steel plate has a round hole. Its two planar faces exercise
    labelled mesh fallbacks; its cylindrical hole wall exercises rational NURBS.
    """
    sections = [{"id": f"s{i}", "x_m": x, "points_yz_m": [[width, z * 0.5] for z in range(7)]}
                for i, (x, width) in enumerate(((0, 0.8), (5, 2), (10, 1.2)))]
    hull, _ = build_hull(sections)
    bottom = cq.Solid.makeBox(4000, 2000, 20).cut(
        cq.Solid.makeCylinder(300, 40, cq.Vector(2000, 1000, -10)))
    deck = cq.Solid.makeBox(4000, 2000, 20, cq.Vector(0, 0, 2000))
    web = cq.Solid.makeBox(4000, 20, 1500, cq.Vector(0, 2500, 200))
    return [Fixture("flat_deck_hull", (CadPart("hull", hull, "Hull"),)),
            Fixture("steel_block", (CadPart("bottom", bottom, "Structure"),
                                    CadPart("deck", deck, "Structure"),
                                    CadPart("web", web, "Structure")))]


def export_fixture(fixture: Fixture, output: Path) -> tuple[dict[str, Path], dict[str, int]]:
    output.mkdir(parents=True, exist_ok=True)
    paths = {format: output / f"{fixture.name}.{suffix}"
             for format, suffix in (("STEP", "step"), ("IGES", "iges"), ("3dm", "3dm"))}
    fixture.shape.exportStep(str(paths["STEP"]), write_pcurves=False)
    export_iges(fixture.shape, paths["IGES"])
    counts = export_3dm(fixture.parts, paths["3dm"])
    return paths, counts


def _bounds(shape: cq.Shape) -> tuple[float, ...]:
    box = Bnd_Box()
    # Use actual geometry extrema, not the rational NURBS control-point hull.
    BRepBndLib.AddOptimal_s(shape.wrapped, box, False, False)
    return box.Get()


def bbox_error(actual: cq.Shape, source: cq.Shape) -> float:
    """Largest error across all six bounds, including translations, in mm."""
    return max(abs(a - b) for a, b in zip(_bounds(actual), _bounds(source)))


def surface_area(shape: cq.Shape) -> float:
    properties = GProp_GProps()
    BRepGProp.SurfaceProperties_s(shape.wrapped, properties, Eps=AREA_INTEGRATION_RELATIVE_TOLERANCE)
    return properties.Mass()


def _closed_solids(shape: cq.Shape) -> bool:
    solids = shape.Solids()
    return bool(solids) and shape.isValid() and all(
        solid.Shells() and all(shell.Closed() for shell in solid.Shells()) for solid in solids)


def _read_occ(path: Path, format: str) -> cq.Shape:
    reader = STEPControl_Reader() if format == "STEP" else IGESControl_Reader()
    if reader.ReadFile(str(path)) != IFSelect_RetDone:
        raise ValueError(f"{format} reader could not open the file")
    if format == "IGES" and reader.IGESModel().GlobalSection().UnitFlag() != 2:
        raise ValueError("IGES unit flag is not millimetres")
    if reader.TransferRoots() <= 0:
        raise ValueError(f"{format} reader transferred no geometry")
    return cq.Shape.cast(reader.OneShape())


def _sew_solids(shape: cq.Shape) -> cq.Shape:
    sewing = BRepBuilderAPI_Sewing(SEWING_TOLERANCE_MM)
    for face in shape.Faces():
        sewing.Add(face.wrapped)
    sewing.Perform()
    sewn = cq.Shape.cast(sewing.SewedShape())
    shells = sewn.Shells()
    if not shells or not sewn.isValid() or not all(shell.Closed() for shell in shells):
        raise ValueError("IGES faces do not sew into closed shells")
    solids = []
    for shell in shells:
        solid = BRepBuilderAPI_MakeSolid(shell.wrapped).Solid()
        if not BRepLib.OrientClosedSolid_s(solid):
            raise ValueError("A sewn IGES shell cannot be oriented as a solid")
        solids.append(cq.Shape.cast(solid))
    result = cq.Compound.makeCompound(solids)
    if not _closed_solids(result):
        raise ValueError("Sewn IGES solids are invalid")
    return result


def _knot_arrays(values) -> tuple[TColStd_Array1OfReal, TColStd_Array1OfInteger]:
    """Restore the two endpoint knots omitted by the OpenNURBS convention."""
    full = [values[0], *values, values[-1]]
    unique, multiplicities = [], []
    for value in full:
        if unique and value == unique[-1]:
            multiplicities[-1] += 1
        else:
            unique.append(value)
            multiplicities.append(1)
    knots = TColStd_Array1OfReal(1, len(unique))
    mults = TColStd_Array1OfInteger(1, len(unique))
    for index, (value, multiplicity) in enumerate(zip(unique, multiplicities), 1):
        knots.SetValue(index, value)
        mults.SetValue(index, multiplicity)
    return knots, mults


def _occ_surface(surface: rhino.NurbsSurface):
    u_count, v_count = surface.Points.CountU, surface.Points.CountV
    poles = TColgp_Array2OfPnt(1, u_count, 1, v_count)
    weights = TColStd_Array2OfReal(1, u_count, 1, v_count)
    for u in range(u_count):
        for v in range(v_count):
            point = surface.Points.GetControlPoint(u, v)
            poles.SetValue(u + 1, v + 1, gp_Pnt(point.X / point.W, point.Y / point.W, point.Z / point.W))
            weights.SetValue(u + 1, v + 1, point.W)
    u_knots, u_mults = _knot_arrays(list(surface.KnotsU))
    v_knots, v_mults = _knot_arrays(list(surface.KnotsV))
    return Geom_BSplineSurface(poles, weights, u_knots, v_knots, u_mults, v_mults,
                               surface.Degree(0), surface.Degree(1))


def _occ_curve(curve: rhino.Curve):
    source = curve.ToNurbsCurve()
    poles = TColgp_Array1OfPnt(1, len(source.Points))
    weights = TColStd_Array1OfReal(1, len(source.Points))
    for index, point in enumerate(source.Points, 1):
        poles.SetValue(index, gp_Pnt(point.X / point.W, point.Y / point.W, point.Z / point.W))
        weights.SetValue(index, point.W)
    knots, mults = _knot_arrays(list(source.Knots))
    return Geom_BSplineCurve(poles, weights, knots, mults, source.Degree)


def _occ_trimmed_plane(brep: rhino.Brep) -> cq.Shape:
    faces = []
    for face in brep.Faces:
        if len(face.Loops) != 1:
            raise ValueError("Unexpected inner trim in an exact planar Brep")
        wire = BRepBuilderAPI_MakeWire()
        for trim in face.OuterLoop.Trims:
            edge = BRepBuilderAPI_MakeEdge(_occ_curve(brep.Edges[trim.EdgeIndex])).Edge()
            if trim.IsReversed:
                edge.Reverse()
            wire.Add(edge)
        if not wire.IsDone():
            raise ValueError("Rhino planar trim wire could not be rebuilt")
        maker = BRepBuilderAPI_MakeFace(wire.Wire(), True)
        if not maker.IsDone():
            raise ValueError("Rhino trimmed plane could not be rebuilt")
        faces.append(cq.Shape.cast(maker.Face()))
    return cq.Compound.makeCompound(faces)


def _occ_mesh(mesh: rhino.Mesh) -> cq.Shape:
    faces = []
    for a, b, c, d in mesh.Faces:
        triangles = ((a, b, c),) if c == d else ((a, b, c), (a, c, d))
        for triangle in triangles:
            polygon = BRepBuilderAPI_MakePolygon()
            for index in triangle:
                point = mesh.Vertices.Point3dAt(index)
                polygon.Add(gp_Pnt(point.X, point.Y, point.Z))
            polygon.Close()
            faces.append(cq.Shape.cast(BRepBuilderAPI_MakeFace(polygon.Wire(), True).Face()))
    if not faces:
        raise ValueError("Rhino mesh has no faces")
    return cq.Compound.makeCompound(faces)


def rebuild_rhino_object(obj) -> cq.Shape:
    """Rebuild the written geometry, without consulting the original OCC face."""
    geometry = obj.Geometry
    if isinstance(geometry, rhino.NurbsSurface):
        return cq.Shape.cast(BRepBuilderAPI_MakeFace(_occ_surface(geometry), REBUILD_TOLERANCE_MM).Face())
    if isinstance(geometry, rhino.Brep):
        return _occ_trimmed_plane(geometry)
    if isinstance(geometry, rhino.Mesh):
        return _occ_mesh(geometry)
    raise ValueError(f"Unsupported Rhino object: {type(geometry).__name__}")


def _rebuild_model(model, expected_counts: dict[str, int], source_face_count: int):
    if model.Settings.ModelUnitSystem != rhino.UnitSystem.Millimeters:
        raise ValueError("Rhino model units are not millimetres")
    actual = dict.fromkeys(REPRESENTATION_KEYS, 0)
    shapes = []
    for obj in model.Objects:
        if not obj.Geometry.IsValid:
            raise ValueError("Rhino contains invalid geometry")
        if isinstance(obj.Geometry, rhino.Mesh):
            if obj.Attributes.GetUserString("approximation") != "mesh":
                raise ValueError("Rhino mesh fallback is not labelled")
            actual["mesh_fallback"] += 1
        elif isinstance(obj.Geometry, rhino.Brep):
            actual["exact_trimmed_plane"] += 1
        elif isinstance(obj.Geometry, rhino.NurbsSurface):
            actual["exact_untrimmed"] += 1
        else:
            raise ValueError("Rhino contains an unexpected object type")
        shapes.append(rebuild_rhino_object(obj))
    recorded = {key: int(model.Strings[key]) for key in REPRESENTATION_KEYS}
    if actual != recorded or actual != expected_counts or sum(actual.values()) != source_face_count:
        raise ValueError("Rhino representation counts disagree with objects or export counts")
    return cq.Compound.makeCompound(shapes), actual


def _clip_at_plane(shape: cq.Shape, axis: str, coordinate: float) -> cq.Shape:
    bounds = _bounds(shape)
    center = [(bounds[i] + bounds[i + 3]) / 2 for i in range(3)]
    index = 2 if axis == "z" else 0
    origin = center.copy()
    origin[index] = coordinate
    normal = [0, 0, 0]
    normal[index] = 1
    inside = origin.copy()
    inside[index] -= 1
    plane = BRepBuilderAPI_MakeFace(gp_Pln(gp_Pnt(*origin), gp_Dir(*normal))).Face()
    half_space = BRepPrimAPI_MakeHalfSpace(plane, gp_Pnt(*inside)).Solid()
    operation = BRepAlgoAPI_Common(shape.wrapped, half_space)
    if not operation.IsDone():
        raise ValueError("Plane cut did not complete")
    return cq.Shape.cast(operation.Shape())


def _offset_face(face: cq.Face) -> cq.Shape:
    operation = BRepOffsetAPI_MakeOffsetShape()
    operation.PerformBySimple(face.wrapped, FACE_OFFSET_MM)
    if not operation.IsDone():
        raise ValueError("Face offset did not complete")
    return cq.Shape.cast(operation.Shape())


def exercise_edits(shape: cq.Shape) -> dict[str, bool]:
    """Require valid, nonempty changes; merely returning a valid input is not enough."""
    edits = {}
    bounds = _bounds(shape)
    volume = shape.Volume()
    for name, axis, index in (("waterline_cut", "z", 2), ("frame_cut", "x", 0)):
        coordinate = (bounds[index] + bounds[index + 3]) / 2
        try:
            cut = _clip_at_plane(shape, axis, coordinate)
            edits[name] = bool(_closed_solids(cut) and 0 < cut.Volume() < volume * (1 - VOLUME_RELATIVE_TOLERANCE)
                               and _bounds(cut)[index + 3] <= coordinate + BOUNDING_BOX_TOLERANCE_MM)
        except Exception:
            edits[name] = False
    try:
        # A large planar face gives a stable, typical plate/deck offset.
        face = max((face for face in shape.Faces() if face.geomType() == "PLANE"), key=lambda face: face.Area())
        offset = _offset_face(face)
        distance = (offset.Center() - face.Center()).Length
        edits["face_offset"] = bool(offset.isValid() and len(offset.Faces()) == 1
                                    and abs(distance - FACE_OFFSET_MM) <= FACE_OFFSET_TOLERANCE_MM
                                    and abs(offset.Area() / face.Area() - 1) <= VOLUME_RELATIVE_TOLERANCE)
    except Exception:
        edits["face_offset"] = False
    return edits


def check_format(fixture: Fixture, format: str, path: Path, expected_counts=None) -> dict:
    row = {"fixture": fixture.name, "format": format, "file": path.name, "imported": False,
           "valid": False, "volume_relative_error": None, "bbox_error_mm": None,
           "edits_ok": None, "passed": False, "details": {}, "errors": []}
    source = fixture.shape
    try:
        if format == "3dm":
            model = rhino.File3dm.Read(str(path))
            if model is None:
                raise ValueError("Rhino reader could not open the file")
            row["imported"] = True
            shape, counts = _rebuild_model(model, expected_counts, len(source.Faces()))
            row["details"].update(representation_counts=counts, object_count=len(model.Objects))
            area_error = abs(surface_area(shape) / surface_area(source) - 1)
            row["details"]["surface_area_relative_error"] = area_error
            if area_error > SURFACE_AREA_RELATIVE_TOLERANCE:
                raise ValueError("Rebuilt Rhino surface area differs beyond the mesh tolerance")
        elif format in ("STEP", "IGES"):
            shape = _read_occ(path, format)
            row["imported"] = True
            if format == "IGES":
                row["details"]["imported_face_count"] = len(shape.Faces())
                if len(shape.Faces()) != len(source.Faces()):
                    raise ValueError("IGES face count differs from the source")
                if not shape.isValid():
                    raise ValueError("Imported IGES faces are invalid")
                shape = _sew_solids(shape)
            if not _closed_solids(shape) or len(shape.Solids()) != len(source.Solids()):
                raise ValueError(f"{format} does not contain the expected valid closed solids")
            row["details"]["closed_solid_count"] = len(shape.Solids())
            row["volume_relative_error"] = abs(shape.Volume() / source.Volume() - 1)
        else:
            raise ValueError(f"Unknown format {format}")
        row["valid"] = bool(shape.isValid())
        row["bbox_error_mm"] = bbox_error(shape, source)
        if format != "3dm":
            row["details"]["edits"] = exercise_edits(shape)
            row["edits_ok"] = all(row["details"]["edits"].values())
        volume_ok = row["volume_relative_error"] is None or row["volume_relative_error"] <= VOLUME_RELATIVE_TOLERANCE
        row["passed"] = bool(row["valid"] and volume_ok and row["bbox_error_mm"] <= BOUNDING_BOX_TOLERANCE_MM
                             and row["edits_ok"] is not False)
    except Exception as error:
        row["errors"].append(f"{type(error).__name__}: {error}")
    return row


def run_checks(output: Path) -> dict:
    rows, fixtures = [], []
    for fixture in make_fixtures():
        paths, counts = export_fixture(fixture, output / fixture.name)
        fixtures.append({"name": fixture.name, "faces": len(fixture.shape.Faces()),
                         "solids": len(fixture.shape.Solids()), "volume_mm3": fixture.shape.Volume(),
                         "bbox_mm": _bounds(fixture.shape), "export_counts": counts})
        for format, path in paths.items():
            rows.append(check_format(fixture, format, path, counts))
    return {"tools": {name: version(name) for name in ("cadquery", "cadquery-ocp", "rhino3dm")},
            "scope": "OCC and rhino3dm; not Rhino or other CAD tools", "engineering_approved": False,
            "tolerances": {"volume_relative": VOLUME_RELATIVE_TOLERANCE, "bbox_mm": BOUNDING_BOX_TOLERANCE_MM,
                           "sewing_mm": SEWING_TOLERANCE_MM, "surface_area_relative": SURFACE_AREA_RELATIVE_TOLERANCE,
                           "face_offset_mm": FACE_OFFSET_MM, "face_offset_tolerance_mm": FACE_OFFSET_TOLERANCE_MM},
            "fixtures": fixtures, "results": rows, "passed": all(row["passed"] for row in rows)}


def render_table(report: dict) -> str:
    lines = ["| Fixture | Format | Imported | Valid | Volume error (relative) | Bbox error (mm) | Edits ok |",
             "| --- | --- | --- | --- | --- | --- | --- |"]
    for row in report["results"]:
        volume = "n/a" if row["volume_relative_error"] is None else f"{row['volume_relative_error']:.3g}"
        bbox = "n/a" if row["bbox_error_mm"] is None else f"{row['bbox_error_mm']:.3g}"
        edits = "n/a" if row["edits_ok"] is None else "yes" if row["edits_ok"] else "no"
        imported, valid = ("yes" if row[key] else "no" for key in ("imported", "valid"))
        lines.append(f"| {row['fixture']} | {row['format']} | {imported} | {valid} | {volume} | {bbox} | {edits} |")
    return "\n".join(lines) + "\n"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=PROJECT_ROOT / "work" / "cad-export-check")
    args = parser.parse_args(argv)
    output = args.out.resolve()
    if not output.is_relative_to((PROJECT_ROOT / "work").resolve()):
        parser.error("--out must be inside the project's git-ignored work/ folder")
    report = run_checks(output)
    output.mkdir(parents=True, exist_ok=True)
    (output / "results.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    table = render_table(report)
    (output / "results.md").write_text(table, encoding="utf-8")
    print(table, end="")
    for row in report["results"]:
        for error in row["errors"]:
            print(f"{row['fixture']} {row['format']}: {error}")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
