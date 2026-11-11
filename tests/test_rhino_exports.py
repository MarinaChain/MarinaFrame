"""Synthetic CAD fixtures for the per-face NURBS .3dm export."""
from pathlib import Path
import tomllib

import cadquery as cq
import pytest
import rhino3dm as rhino

from vessel_reconstruction.geometry import build_hull, export_geometry
from vessel_reconstruction.structure import block3d, solid
from vessel_reconstruction.structure.model import Member, SectionResult, Stroke


def read_model(path: Path) -> rhino.File3dm:
    model = rhino.File3dm.Read(str(path))
    assert model is not None
    assert model.Settings.ModelUnitSystem == rhino.UnitSystem.Millimeters
    assert "DRAFT" in model.StartSectionComments
    assert "not for construction" in model.StartSectionComments
    assert model.Strings["engineering_approved"] == "false"
    assert "trimmed planes" in model.Strings["Notes"]
    assert "mesh fallback" in model.Strings["Notes"]
    assert sum(int(model.Strings[key]) for key in ("exact_untrimmed", "exact_trimmed_plane", "mesh_fallback")) == len(model.Objects)
    assert len(model.Objects) > 0
    for obj in model.Objects:
        assert isinstance(obj.Geometry, (rhino.NurbsSurface, rhino.Brep, rhino.Mesh))
        assert obj.Geometry.IsValid, obj.Geometry.IsValidWithLog
        assert obj.Attributes.Name
    return model


def test_rhino_dependency_is_pinned_to_the_installed_version():
    root = Path(__file__).resolve().parents[1]
    project = tomllib.loads((root / "pyproject.toml").read_text())
    assert "rhino3dm==8.35.0" in project["project"]["dependencies"]
    assert "rhino3dm==8.35.0" in (root / "requirements-lock.txt").read_text().splitlines()
    assert rhino.__version__ == "8.35.0"


@pytest.mark.parametrize("lofted", [False, True])
def test_hull_export_writes_nurbs_in_millimetres(tmp_path, lofted):
    if lofted:
        sections = [{"id": f"s{i}", "x_m": x, "points_yz_m": [[2, z * 0.5] for z in range(7)]}
                    for i, x in enumerate((0, 5, 10))]
        shape, _ = build_hull(sections)
    else:
        shape = cq.Solid.makeBox(10000, 4000, 3000, cq.Vector(0, -2000, 0))
    exports, _ = export_geometry(shape, tmp_path)
    assert exports["3dm"] == "model.3dm"
    assert exports["3dm_units"] == exports["step_units"] == "mm"
    model = read_model(tmp_path / exports["3dm"])
    assert len(model.Objects) == len(shape.Faces())
    assert {layer.Name for layer in model.Layers} == {"Hull"}
    assert {obj.Attributes.Name for obj in model.Objects} == {"hull"}
    for obj, face in zip(model.Objects, shape.Faces()):
        surface = obj.Geometry
        u, v = surface.Domain(0), surface.Domain(1)
        normal = surface.NormalAt((u.T0 + u.T1) / 2, (v.T0 + v.T1) / 2)
        expected = face.normalAt()
        assert normal.X * expected.x + normal.Y * expected.y + normal.Z * expected.z == pytest.approx(1)
    bounds = model.Objects.GetBoundingBox()
    assert (bounds.Min.X, bounds.Min.Y, bounds.Min.Z) == pytest.approx((0, -2000, 0))
    assert (bounds.Max.X, bounds.Max.Y, bounds.Max.Z) == pytest.approx((10000, 2000, 3000))


def test_mesh_only_export_does_not_write_3dm(tmp_path):
    exports, _ = export_geometry(cq.Solid.makeBox(1000, 2000, 3000), tmp_path, export_cad=False)
    assert exports == {"mesh": "mesh.json", "mesh_units": "m"}
    assert not (tmp_path / "model.3dm").exists()


def test_rhino_writer_keeps_layers_part_ids_and_all_faces(tmp_path):
    from vessel_reconstruction.rhino_exports import CadPart, export_3dm

    box = cq.Solid.makeBox(1000, 2000, 3000)
    parts = [CadPart("hull", box, "Hull"),
             CadPart("tank-2", box.translate((4000, 0, 0)), "Tanks"),
             CadPart("frame-8", box.translate((8000, 0, 0)), "Structure")]
    path = tmp_path / "assembly.3dm"
    export_3dm(parts, path)
    model = read_model(path)
    assert len(model.Objects) == sum(len(part.shape.Faces()) for part in parts)
    layers = {i: layer.Name for i, layer in enumerate(model.Layers)}
    assert {(obj.Attributes.Name, layers[obj.Attributes.LayerIndex]) for obj in model.Objects} == {
        ("hull", "Hull"), ("tank-2", "Tanks"), ("frame-8", "Structure")}


def test_rhino_writer_preserves_rational_curvature_and_placement(tmp_path):
    from vessel_reconstruction.rhino_exports import CadPart, export_3dm

    shape = cq.Solid.makeCylinder(1000, 2500).translate((5000, -3000, 0))
    path = tmp_path / "curved.3dm"
    export_3dm([CadPart("tank-round", shape, "Tanks")], path)
    model = read_model(path)
    assert len(model.Objects) == len(shape.Faces())
    curved = [obj.Geometry for obj in model.Objects
              if isinstance(obj.Geometry, rhino.NurbsSurface) and obj.Geometry.IsRational]
    assert len(curved) == 1
    surface = curved[0]
    # An exact rational cylinder must stay on its circle after export and re-import.
    for fraction in (0, 0.13, 0.37, 0.71, 1):
        u, v = surface.Domain(0), surface.Domain(1)
        point = surface.PointAt(u.T0 + fraction * (u.T1 - u.T0), (v.T0 + v.T1) / 2)
        assert (point.X - 5000)**2 + (point.Y + 3000)**2 == pytest.approx(1000**2)
        assert point.Z == pytest.approx(1250)


def test_rhino_writer_reports_file_write_failure(tmp_path):
    from vessel_reconstruction.errors import GeometryError
    from vessel_reconstruction.rhino_exports import CadPart, export_3dm

    with pytest.raises(GeometryError, match="3dm"):
        export_3dm([CadPart("hull", cq.Solid.makeBox(1, 2, 3), "Hull")],
                   tmp_path / "missing" / "hull.3dm")


def test_structure_slice_3dm_names_follow_stroke_ids(tmp_path):
    member = Member("deck", Stroke(12, ((0, 0), (1000, 0)), "synthetic"),
                    thickness_mm=20, ship_points_mm=((0, 3000), (1000, 3000)))
    section = SectionResult([member], [], None, None, [], [], "vector", 1, 0)
    path = tmp_path / "slice.step"
    assert solid.export_slice_step(section, path, 500) == []
    model = read_model(path.with_suffix(".3dm"))
    assert {layer.Name for layer in model.Layers} == {"Structure"}
    assert {obj.Attributes.Name for obj in model.Objects} == {"stroke-12-segment-0"}
    assert len(model.Objects) == 6


def test_structure_block_3dm_names_follow_member_ids(tmp_path):
    block = {"engineering_approved": False, "members": [
        {"member_id": "deck", "thickness_mm": 20, "box": [0, 0, 3, 2, 1, 3]},
        {"member_id": "floor", "thickness_mm": 10, "box": [0, 0, 0, 2, 1, 0]},
    ]}
    path = tmp_path / "block.step"
    assert block3d.export_step(block, path) == 2
    model = read_model(path.with_suffix(".3dm"))
    assert {layer.Name for layer in model.Layers} == {"Structure"}
    assert {obj.Attributes.Name for obj in model.Objects} == {"deck", "floor"}
    assert len(model.Objects) == 12


def test_discard_geometry_removes_3dm_files(tmp_path):
    from vessel_reconstruction.pipeline import _discard_geometry

    for name in ("model.3dm", "model-draft.3dm"):
        (tmp_path / name).write_text("partial geometry")
    result = {"exports": {"3dm": "model.3dm"}, "provenance": {}}
    _discard_geometry(tmp_path, result)
    assert result["exports"] == {}
    assert not (tmp_path / "model.3dm").exists()
    assert not (tmp_path / "model-draft.3dm").exists()
