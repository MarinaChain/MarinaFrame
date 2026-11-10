"""Focused checks for draft IGES files beside the existing STEP files."""
from pathlib import Path

import cadquery as cq
from OCP.IFSelect import IFSelect_RetDone
from OCP.IGESControl import IGESControl_Reader
from OCP.BRepBuilderAPI import BRepBuilderAPI_Sewing
import pytest

from vessel_reconstruction.geometry import export_geometry
from vessel_reconstruction.structure import block3d, solid
from vessel_reconstruction.structure.model import Member, SectionResult, Stroke


def read_iges(path: Path) -> cq.Shape:
    reader = IGESControl_Reader()
    assert reader.ReadFile(str(path)) == IFSelect_RetDone
    # IGES unit flag 2 means millimetres, the same unit as STEP and the OCC model.
    assert reader.IGESModel().GlobalSection().UnitFlag() == 2
    assert reader.IGESModel().GlobalSection().UnitName().ToCString() == "MM"
    entity_types = {reader.IGESModel().Entity(i).TypeNumber()
                    for i in range(1, reader.IGESModel().NbEntities() + 1)}
    assert 144 in entity_types  # Trimmed surfaces, without MSBO solids (entity 186).
    assert 186 not in entity_types
    assert reader.TransferRoots() > 0
    return cq.Shape.cast(reader.OneShape())


def assert_draft_stamp(path: Path) -> None:
    start = " ".join(line[:72].rstrip() for line in path.read_text().splitlines() if line[72:73] == "S")
    assert "DRAFT" in start
    assert "not for construction" in start
    assert "engineering_approved=false" in start
    assert "Units mm;" in start


def test_hull_export_writes_iges_in_millimetres_with_a_draft_stamp(tmp_path):
    shape = cq.Solid.makeBox(10000, 4000, 3000, cq.Vector(0, -2000, 0))
    exports, _ = export_geometry(shape, tmp_path)
    assert exports["iges"] == "model.iges"
    assert exports["iges_units"] == exports["step_units"] == "mm"
    path = tmp_path / exports["iges"]
    assert_draft_stamp(path)
    imported = read_iges(path)
    assert imported.isValid() and not imported.Solids()
    assert len(imported.Faces()) == len(shape.Faces())
    # One micrometre in millimetres allows exchange-file roundoff at shared edges.
    sewing = BRepBuilderAPI_Sewing(0.001)
    for face in imported.Faces():
        sewing.Add(face.wrapped)
    sewing.Perform()
    sewn = cq.Shape.cast(sewing.SewedShape())
    assert sewn.isValid() and len(sewn.Shells()) == 1
    assert sewn.Shells()[0].Closed()
    bounds = imported.BoundingBox()
    assert (bounds.xlen, bounds.ymin, bounds.ymax, bounds.zlen) == pytest.approx((10000, -2000, 2000, 3000))


def test_mesh_only_export_does_not_write_iges(tmp_path):
    exports, _ = export_geometry(cq.Solid.makeBox(1000, 2000, 3000), tmp_path, export_cad=False)
    assert exports == {"mesh": "mesh.json", "mesh_units": "m"}
    assert not (tmp_path / "model.iges").exists()


def test_iges_writer_keeps_all_faces_in_a_tank_compound(tmp_path):
    from vessel_reconstruction.cad_exports import export_iges

    tanks = cq.Compound.makeCompound([
        cq.Solid.makeBox(2000, 1000, 1000),
        cq.Solid.makeBox(3000, 1000, 1000, cq.Vector(4000, 0, 0)),
    ])
    path = tmp_path / "tanks.iges"
    export_iges(tanks, path)
    assert_draft_stamp(path)
    imported = read_iges(path)
    assert imported.isValid() and not imported.Solids()
    assert len(imported.Faces()) == len(tanks.Faces())


def test_structure_slice_writes_iges_beside_step(tmp_path):
    member = Member("deck", Stroke(0, ((0, 0), (1000, 0)), "synthetic"),
                    thickness_mm=20, ship_points_mm=((0, 3000), (1000, 3000)))
    section = SectionResult([member], [], None, None, [], [], "vector", 1, 0)
    path = tmp_path / "slice.step"
    assert solid.export_slice_step(section, path, 500) == []
    assert path.is_file()
    iges = path.with_suffix(".iges")
    assert_draft_stamp(iges)
    imported = read_iges(iges)
    assert imported.isValid() and not imported.Solids()
    source, _ = solid.build_slice(section, 500)
    assert len(imported.Faces()) == len(source.Faces())


def test_structure_block_writes_iges_beside_step(tmp_path):
    block = {"engineering_approved": False, "members": [
        {"thickness_mm": 20, "box": [0, 0, 3, 2, 1, 3]},
        {"thickness_mm": 10, "box": [0, 0, 0, 2, 1, 0]},
    ]}
    path = tmp_path / "block.step"
    assert block3d.export_step(block, path) == 2
    assert path.is_file() and block["engineering_approved"] is False
    iges = path.with_suffix(".iges")
    assert_draft_stamp(iges)
    imported = read_iges(iges)
    assert imported.isValid() and not imported.Solids()
    source = cq.importers.importStep(str(path)).val()
    assert len(imported.Faces()) == len(source.Faces())


def test_iges_writer_reports_file_write_failure(tmp_path):
    from vessel_reconstruction.cad_exports import export_iges
    from vessel_reconstruction.errors import GeometryError

    with pytest.raises(GeometryError, match="IGES"):
        export_iges(cq.Solid.makeBox(1000, 1000, 1000), tmp_path / "missing" / "hull.iges")


def test_discard_geometry_removes_iges_files(tmp_path):
    from vessel_reconstruction.pipeline import _discard_geometry

    for name in ("model.iges", "model-draft.iges"):
        (tmp_path / name).write_text("partial geometry")
    result = {"exports": {"iges": "model.iges"}, "provenance": {}}
    _discard_geometry(tmp_path, result)
    assert result["exports"] == {}
    assert not (tmp_path / "model.iges").exists()
    assert not (tmp_path / "model-draft.iges").exists()
