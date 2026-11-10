"""Geometry and failure-path tests for the OCC/rhino3dm exchange checker."""
import importlib
from pathlib import Path

import cadquery as cq
import pytest
import rhino3dm as rhino

from vessel_reconstruction.cad_exports import export_iges

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check_cad_exports.py"


def checker():
    assert SCRIPT.is_file(), "The repeatable CAD export checker is missing."
    return importlib.import_module("scripts.check_cad_exports")


@pytest.mark.cad
def test_both_fixtures_pass_all_three_formats(tmp_path):
    check = checker()
    report = check.run_checks(tmp_path)
    assert report["passed"], report
    assert {(row["fixture"], row["format"]) for row in report["results"]} == {
        (fixture, format) for fixture in ("flat_deck_hull", "steel_block")
        for format in ("STEP", "IGES", "3dm")}
    for row in report["results"]:
        assert row["imported"] and row["valid"] and row["passed"], row
        assert row["bbox_error_mm"] <= check.BOUNDING_BOX_TOLERANCE_MM
        if row["format"] == "3dm":
            assert row["volume_relative_error"] is None and row["edits_ok"] is None
            assert sum(row["details"]["representation_counts"].values()) == row["details"]["object_count"]
            if row["fixture"] == "steel_block":
                assert row["details"]["representation_counts"]["mesh_fallback"] == 2
            else:
                assert row["details"]["representation_counts"]["exact_trimmed_plane"] > 0
        else:
            assert row["volume_relative_error"] <= check.VOLUME_RELATIVE_TOLERANCE
            assert row["edits_ok"] and all(row["details"]["edits"].values())
            assert set(row["details"]["edits"]) == {"waterline_cut", "frame_cut", "face_offset"}
            assert row["details"]["closed_solid_count"] == (1 if row["fixture"] == "flat_deck_hull" else 3)


@pytest.mark.cad
def test_missing_step_reports_failure_without_a_successful_edit(tmp_path):
    check = checker()
    fixture = check.make_fixtures()[0]
    row = check.check_format(fixture, "STEP", tmp_path / "missing.step")
    assert not row["imported"] and not row["valid"] and not row["passed"]
    assert row["edits_ok"] is None and row["errors"]


@pytest.mark.cad
def test_step_translation_is_detected_even_when_volume_is_unchanged(tmp_path):
    check = checker()
    fixture = check.make_fixtures()[0]
    path = tmp_path / "translated.step"
    fixture.shape.translate((100, 0, 0)).exportStep(str(path))
    row = check.check_format(fixture, "STEP", path)
    assert row["imported"] and row["valid"]
    assert row["volume_relative_error"] <= check.VOLUME_RELATIVE_TOLERANCE
    assert row["bbox_error_mm"] == pytest.approx(100)
    assert not row["passed"]


@pytest.mark.cad
def test_open_iges_does_not_pass_as_an_editable_closed_hull(tmp_path):
    check = checker()
    fixture = check.make_fixtures()[0]
    path = tmp_path / "open.iges"
    export_iges(cq.Compound.makeCompound(fixture.shape.Faces()[:-1]), path)
    row = check.check_format(fixture, "IGES", path)
    assert row["imported"] and not row["valid"] and not row["passed"]
    assert row["edits_ok"] is None
    assert any("face count" in error for error in row["errors"])


@pytest.mark.cad
def test_rhino_counts_are_checked_against_objects_and_export_return_value(tmp_path):
    check = checker()
    fixture = check.make_fixtures()[1]
    paths, counts = check.export_fixture(fixture, tmp_path)
    model = rhino.File3dm.Read(str(paths["3dm"]))
    model.Strings["mesh_fallback"] = "0"
    assert model.Write(str(paths["3dm"]), 8)
    row = check.check_format(fixture, "3dm", paths["3dm"], counts)
    assert row["imported"] and not row["valid"] and not row["passed"]
    assert any("representation counts" in error for error in row["errors"])


@pytest.mark.cad
def test_unlabelled_mesh_fallback_is_rejected(tmp_path):
    check = checker()
    fixture = check.make_fixtures()[1]
    paths, counts = check.export_fixture(fixture, tmp_path)
    model = rhino.File3dm.Read(str(paths["3dm"]))
    mesh = next(obj for obj in model.Objects if isinstance(obj.Geometry, rhino.Mesh))
    mesh.Attributes.SetUserString("approximation", "")
    assert model.Write(str(paths["3dm"]), 8)
    row = check.check_format(fixture, "3dm", paths["3dm"], counts)
    assert row["imported"] and not row["valid"] and not row["passed"]
    assert any("mesh" in error for error in row["errors"])


@pytest.mark.cad
def test_rhino_planar_trims_rebuild_with_their_original_areas(tmp_path):
    check = checker()
    fixture = check.make_fixtures()[0]
    paths, _ = check.export_fixture(fixture, tmp_path)
    model = rhino.File3dm.Read(str(paths["3dm"]))
    checked = 0
    for obj in model.Objects:
        if isinstance(obj.Geometry, rhino.Brep):
            rebuilt = check.rebuild_rhino_object(obj)
            source = fixture.shape.Faces()[int(obj.Attributes.GetUserString("source_face_index"))]
            assert rebuilt.isValid()
            assert rebuilt.Area() == pytest.approx(source.Area(), rel=1e-6)
            checked += 1
    assert checked > 0


@pytest.mark.cad
def test_rational_surface_rebuild_keeps_the_circle(tmp_path):
    check = checker()
    from vessel_reconstruction.rhino_exports import CadPart, export_3dm

    cylinder = cq.Solid.makeCylinder(1000, 2500).translate((5000, -3000, 0))
    path = tmp_path / "cylinder.3dm"
    export_3dm([CadPart("tank", cylinder, "Tanks")], path)
    model = rhino.File3dm.Read(str(path))
    curved = next(obj for obj in model.Objects if isinstance(obj.Geometry, rhino.NurbsSurface))
    rebuilt = check.rebuild_rhino_object(curved)
    assert rebuilt.isValid()
    assert check.surface_area(rebuilt) == pytest.approx(2 * 3.141592653589793 * 1000 * 2500, rel=1e-6)
    assert check.bbox_error(rebuilt, cylinder) <= check.BOUNDING_BOX_TOLERANCE_MM


@pytest.mark.cad
def test_valid_but_unchanged_cuts_do_not_pass(monkeypatch):
    check = checker()
    shape = check.make_fixtures()[0].shape
    monkeypatch.setattr(check, "_clip_at_plane", lambda source, axis, coordinate: source)
    edits = check.exercise_edits(shape)
    assert edits["waterline_cut"] is False and edits["frame_cut"] is False
    assert edits["face_offset"] is True


@pytest.mark.cad
def test_valid_but_unchanged_face_offset_does_not_pass(monkeypatch):
    check = checker()
    shape = check.make_fixtures()[0].shape
    monkeypatch.setattr(check, "_offset_face", lambda face: face)
    edits = check.exercise_edits(shape)
    assert edits["waterline_cut"] and edits["frame_cut"]
    assert edits["face_offset"] is False


def test_cli_rejects_output_outside_the_ignored_work_folder(tmp_path):
    check = checker()
    with pytest.raises(SystemExit) as error:
        check.main(["--out", str(check.PROJECT_ROOT / "outputs" / "cad-export-check")])
    assert error.value.code == 2
