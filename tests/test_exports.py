"""Exports for a naval architect: offsets CSV, hydrostatics, PDF report, package.

Fixture ``tests/fixtures/exports/shipd-1-00679-L0`` is a small copy of a real
draft task (work/w17/runs/w18d-corrected/shipd-1-00679-L0, revision r0003):
state.json and result.json trimmed to what the exports read, the matching
render's scoreboard and observation, and two downscaled overlay images. The
STEP and STL files (15 MB) are not copied, so that fixture tests the path
without CAD files. The synthetic task below has a box hull with a mesh.
"""
from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
import shutil
import struct
import zipfile

import numpy as np
from PIL import Image
import pytest

from vessel_reconstruction.exports import ExportError, export_draft
from vessel_reconstruction.exports.__main__ import main
from vessel_reconstruction.exports.hydrostatics import clip_below, mesh_hydrostatics, signed_volume, table_hydrostatics
from vessel_reconstruction.exports.offsets import half_breadth_at, offsets_table
from vessel_reconstruction.exports.report import FOOTER
from vessel_reconstruction.exports.source import normalise_revision

FIXTURE = Path(__file__).parent / "fixtures" / "exports" / "shipd-1-00679-L0"
STEP_TEXT = ("ISO-10303-21;\nHEADER;\nFILE_DESCRIPTION(('Open CASCADE Model'),'2;1');\n"
             "FILE_NAME('x','2026-01-01T00:00:00',('A'),('B'),'C','D','E');\n"
             "FILE_SCHEMA(('AUTOMOTIVE_DESIGN { 1 0 10303 214 1 1 1 1 }'));\nENDSEC;\nDATA;\nENDSEC;\n"
             "END-ISO-10303-21;\n")


# ---------------------------------------------------------------------------
# Synthetic geometry


def prism(section_yz: list[tuple[float, float]], length: float) -> np.ndarray:
    """Closed, outward triangle mesh (metres) of a prism from x = 0 to length.

    ``section_yz`` is the starboard half of a convex section from the keel
    (y = 0) up to the top (y = 0 again after the deck), counter-clockwise when
    seen from +x.
    """
    half = [np.array(p, float) for p in section_yz]
    ring = half + [np.array([-y, z]) for y, z in reversed(half[1:-1])]
    triangles = []
    count = len(ring)
    for k in range(count):
        a, b = ring[k], ring[(k + 1) % count]
        p0, p1 = [0.0, *a], [0.0, *b]
        q0, q1 = [length, *a], [length, *b]
        triangles += [[p0, q0, q1], [p0, q1, p1]]
    centre = np.mean(ring, axis=0)
    for k in range(count):
        a, b = ring[k], ring[(k + 1) % count]
        triangles.append([[0.0, *centre], [0.0, *b], [0.0, *a]])
        triangles.append([[length, *centre], [length, *a], [length, *b]])
    mesh = np.array(triangles, float)
    return mesh if signed_volume(mesh) > 0 else mesh[:, ::-1]


def binary_stl(triangles_m: np.ndarray, path: Path) -> None:
    triangles_mm = triangles_m * 1000.0
    with path.open("wb") as handle:
        handle.write(b"STL Exported by test".ljust(80, b"\0"))
        handle.write(struct.pack("<I", len(triangles_mm)))
        for triangle in triangles_mm:
            handle.write(struct.pack("<12fH", 0, 0, 0, *triangle.ravel(), 0))


BOX = dict(length=40.0, beam=8.0, depth=5.0)


def box_section(section_id: str, x: float, label: str) -> dict:
    half = BOX["beam"] / 2
    curve = [[0.0, 0.0], [half, 0.0], [half, BOX["depth"]], [0.0, BOX["depth"]]]
    return {"id": section_id, "x_m": x, "points_yz_m": curve, "source_label": label}


def make_box_task(root: Path, *, with_cad: bool = True) -> Path:
    """A task folder with one draft build of a box hull, revision r0001."""
    domain = root / "task" / "domain"
    build = domain / "builds" / "r0001-test"
    build.mkdir(parents=True)
    (domain / "revisions" / "r0001").mkdir(parents=True)
    (domain / "revisions" / "r0001" / "spec.json").write_text(json.dumps({"vessel_name": "Test Box 1",
                                                                          "design_draft_m": 3.0}))
    sections = [box_section("s01", 0.0, "traced"), box_section("s02", 20.0, "ai_inferred"),
                box_section("s03", 40.0, "repaired")]
    result = {"run_id": "run-box", "vessel_id": "factory-box", "status": "review_required",
              "review": {"state": "unreviewed", "engineering_approved": False}, "sections": sections,
              "gaps": [{"kind": "draft_fairness_outlier", "severity": "warning", "section_id": "s02",
                        "message": "s02 is wider than its neighbours."}],
              "metrics": {"length_m": BOX["length"], "beam_m": BOX["beam"], "depth_m": BOX["depth"],
                          "volume_m3": BOX["length"] * BOX["beam"] * BOX["depth"], "cad_valid": True,
                          "bbox_m": {"min": [0, -4, 0], "max": [40, 4, 5]}},
              "exports": {"step": "model-draft.step", "step_units": "mm", "stl": "model-draft.stl",
                          "stl_units": "mm"},
              "draft": {"status": "draft_not_verified", "guesses": []}}
    (build / "result.json").write_text(json.dumps(result))
    guesses = [{"guess_id": "g1", "section_id": "s02", "kind": "model_authored", "x_m": 20.0,
                "reason": "No ink at x = 20 m; AI drew the section.", "status": "open"}]
    state = {"revision": 1, "guesses": guesses,
             "builds": [{"revision_id": "r0000", "path": "domain/builds/old", "valid": False, "status": "blocked"},
                        {"revision_id": "r0001", "path": "domain/builds/r0001-test", "valid": True, "draft": True}]}
    (domain / "state.json").write_text(json.dumps(state))
    if with_cad:
        half = BOX["beam"] / 2
        binary_stl(prism([(0, 0), (half, 0), (half, BOX["depth"]), (0, BOX["depth"])], BOX["length"]),
                   build / "model-draft.stl")
        (build / "model-draft.step").write_text(STEP_TEXT)
        render = domain / "renders" / "render-1"
        render.mkdir(parents=True)
        step_sha256 = hashlib.sha256((build / "model-draft.step").read_bytes()).hexdigest()
        (render / "observation.json").write_text(json.dumps({"geometry_audit": {"step_sha256": step_sha256}}))
        rows = [{"section_id": s["id"], "ink_fit": {"max_m": 0.02, "rms_m": 0.01, "near_fraction": 0.9}}
                for s in sections[:2]]
        (render / "station-scoreboard.json").write_text(json.dumps({"scoreboard": rows}))
        Image.new("RGB", (64, 48), "white").save(render / "station-overlay-00.png")
    return root / "task"


def pdf_text(path: Path) -> str:
    fitz = pytest.importorskip("fitz")
    with fitz.open(path) as document:
        return "\n".join(page.get_text() for page in document)


# ---------------------------------------------------------------------------
# Offsets


def test_half_breadth_reads_crossings_and_leaves_unreached_heights_empty():
    curve = [np.array([[0.0, 1.0], [2.0, 1.0], [3.0, 4.0], [0.0, 4.0]])]  # Keel at z = 1, top at z = 4.
    assert half_breadth_at(curve, 0.5) is None
    assert half_breadth_at(curve, 1.0) == pytest.approx(2.0)  # Flat floor: its outer end.
    assert half_breadth_at(curve, 2.5) == pytest.approx(2.5)
    assert half_breadth_at(curve, 4.0) == pytest.approx(3.0)
    assert half_breadth_at(curve, 4.5) is None


def test_offsets_table_uses_spec_waterlines_or_equal_steps():
    sections = [box_section("s02", 20.0, "ai_inferred"), box_section("s01", 0.0, "traced")]
    table = offsets_table(sections, {}, intervals=5)
    assert table.station_ids == ["s01", "s02"]
    assert table.waterlines_m == [0.0, 1.0, 2.0, 3.0, 4.0, 5.0]
    assert table.half_breadths_m[0] == [4.0] * 6
    assert table.source_labels == ["traced", "ai_inferred"]
    given = offsets_table(sections, {"waterlines_m": [6.0, 2.5]})
    assert given.waterlines_m == [2.5, 6.0]
    assert given.half_breadths_m[0] == [4.0, None]
    assert "specification" in given.waterline_basis


# ---------------------------------------------------------------------------
# Hydrostatics


def test_mesh_hydrostatics_of_a_box_are_exact():
    half = BOX["beam"] / 2
    mesh = prism([(0, 0), (half, 0), (half, BOX["depth"]), (0, BOX["depth"])], BOX["length"])
    h = mesh_hydrostatics(mesh, 3.0, "test")
    assert h.volume_m3 == pytest.approx(40 * 8 * 3)
    assert h.displacement_t == pytest.approx(960 * 1.025)
    assert (h.lcb_m, h.kb_m, h.lcf_m) == pytest.approx((20.0, 1.5, 20.0))
    assert h.waterplane_area_m2 == pytest.approx(320.0)
    assert h.bmt_m == pytest.approx(40 * 8**3 / 12 / 960)
    assert h.bml_m == pytest.approx(8 * 40**3 / 12 / 960)
    assert (h.cb, h.cp, h.cm, h.cwp) == pytest.approx((1.0, 1.0, 1.0, 1.0), rel=1e-6)
    assert h.wetted_surface_m2 == pytest.approx(40 * 8 + 2 * 40 * 3 + 2 * 8 * 3)


def test_mesh_waterplane_at_deck_is_the_limit_from_below():
    mesh = prism([(0, 0), (4, 0), (4, 5), (0, 5)], 40)
    h = mesh_hydrostatics(mesh, 5.0, "top boundary")
    assert h.volume_m3 == pytest.approx(1600)
    assert h.waterplane_area_m2 == pytest.approx(320)
    assert h.lcf_m == pytest.approx(20)
    assert h.bmt_m == pytest.approx(40 * 8**3 / 12 / 1600)


def test_mesh_hydrostatics_of_a_v_prism_match_closed_form():
    # Half-breadth y = z (45 degree V), deck at z = 4, length 10, waterline T = 2.
    mesh = prism([(0, 0), (4, 4), (0, 4)], 10.0)
    assert len(clip_below(mesh, 2.0)) > 0
    h = mesh_hydrostatics(mesh, 2.0, "test")
    assert h.volume_m3 == pytest.approx(10 * 2**2)
    assert h.kb_m == pytest.approx(2 * 2 / 3)
    assert h.waterplane_area_m2 == pytest.approx(10 * 4)
    assert h.bmt_m == pytest.approx((10 * 4**3 / 12) / 40)
    assert h.cb == pytest.approx(0.5)
    # A mesh with inward normals gives the same answer.
    assert mesh_hydrostatics(mesh[:, ::-1], 2.0, "test").volume_m3 == pytest.approx(40.0)


def test_table_hydrostatics_of_box_sections():
    sections = [box_section("s01", 0.0, "traced"), box_section("s02", 40.0, "traced")]
    h = table_hydrostatics(sections, 3.0, "test")
    assert h.volume_m3 == pytest.approx(960.0, rel=1e-3)
    assert h.lcb_m == pytest.approx(20.0)
    assert h.waterplane_area_m2 == pytest.approx(320.0)
    assert h.method.startswith("table")


# ---------------------------------------------------------------------------
# Whole export


def test_export_of_synthetic_box_writes_stamped_package(tmp_path):
    task = make_box_task(tmp_path)
    manifest = export_draft(task, "r1", tmp_path / "out")
    stem = "Test-Box-1_r0001_DRAFT"
    names = {entry["file"] for entry in manifest["files"]}
    assert names == {f"{stem}_offsets.csv", f"{stem}_hydrostatics.json", f"{stem}_hydrostatics.csv",
                     f"{stem}_report.pdf", f"{stem}_model.step", f"{stem}_model.stl"}
    assert manifest["engineering_approved"] is False and manifest["not_built"] == []
    assert manifest["open_guesses"] == 1
    out = tmp_path / "out"
    for entry in manifest["files"]:
        assert hashlib.sha256((out / entry["file"]).read_bytes()).hexdigest() == entry["sha256"]

    hydro = json.loads((out / f"{stem}_hydrostatics.json").read_text())["hydrostatics"]
    assert hydro["draft_basis"] == "specification design_draft_m"
    assert hydro["volume_m3"] == pytest.approx(960.0)

    step = (out / f"{stem}_model.step").read_text()
    assert "Not approved for construction" in step and "Open CASCADE Model" not in step
    assert step.endswith("END-ISO-10303-21;\n")
    stl = (out / f"{stem}_model.stl").read_bytes()
    assert stl.startswith(b"MarinaFrame DRAFT r0001")
    assert len(stl) == (task / "domain/builds/r0001-test/model-draft.stl").stat().st_size

    rows = list(csv.reader((out / f"{stem}_offsets.csv").read_text().splitlines()))
    assert rows[0][0].startswith("# Draft hull model from MarinaFrame")
    header = next(r for r in rows if r and r[0] == "station")
    assert header[:3] == ["station", "x_m", "source_label"]
    assert [r[2] for r in rows[rows.index(header) + 1:]] == ["traced", "ai_inferred", "repaired"]

    with zipfile.ZipFile(out / f"{stem}_package.zip") as archive:
        assert set(archive.namelist()) == names | {f"{stem}_manifest.json"}
        packed = json.loads(archive.read(f"{stem}_manifest.json"))
    assert packed["files"] == manifest["files"]

    text = pdf_text(out / f"{stem}_report.pdf")
    for expected in (FOOTER, "Test Box 1", "r0001", "AI drawn (no ink)", "From ink, repaired", "not checked",
                     "No ink at x = 20 m", "s02 is wider than its neighbours", "Station overlay"):
        assert expected in text


def test_export_is_repeatable(tmp_path):
    task = make_box_task(tmp_path)
    first = export_draft(task, "r0001", tmp_path / "a")
    second = export_draft(task, "r0001", tmp_path / "b")
    assert first["files"] == second["files"]
    assert first["package"]["sha256"] == second["package"]["sha256"]


def test_export_of_real_build_fixture_without_cad(tmp_path):
    task = tmp_path / "task"
    shutil.copytree(FIXTURE / "task", task)
    manifest = export_draft(task, "r3", tmp_path / "out", draft_m=8.0)
    stem = "factory-70ed8f4700b0_r0003_DRAFT"
    assert manifest["not_built"] == ["step_model", "stl_mesh"]
    assert manifest["open_guesses"] == 9
    out = tmp_path / "out"
    rows = list(csv.reader((out / f"{stem}_offsets.csv").read_text().splitlines()))
    body = rows[next(i for i, r in enumerate(rows) if r and r[0] == "station") + 1:]
    assert [r[0] for r in body] == [f"s0{k}" for k in range(1, 10)]
    assert [r[2] for r in body].count("ai_inferred") == 2
    hydro = json.loads((out / f"{stem}_hydrostatics.json").read_text())["hydrostatics"]
    assert hydro["method"].startswith("table") and hydro["draft_basis"] == "given for this export"
    assert 0.5 < hydro["cb"] < 1.0
    text = pdf_text(out / f"{stem}_report.pdf")
    assert FOOTER in text and "AI drawn (no ink)" in text and "No station overlay" in text


def test_revision_errors_and_cli(tmp_path, capsys):
    assert normalise_revision("r3") == "r0003" and normalise_revision("r0012") == "r0012"
    with pytest.raises(ExportError):
        normalise_revision("3")
    task = make_box_task(tmp_path, with_cad=False)
    with pytest.raises(ExportError, match="no valid build"):
        export_draft(task, "r0", tmp_path / "x")
    assert main(["--task", str(task), "--revision", "r9", "--out", str(tmp_path / "x")]) == 2
    assert "r0001" in capsys.readouterr().err
    assert main(["--task", str(task), "--revision", "r1", "--out", str(tmp_path / "cli")]) == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed["not_built"] == ["step_model", "stl_mesh"]
    assert (tmp_path / "cli" / printed["package"]["file"]).is_file()


def test_csv_text_cells_cannot_become_spreadsheet_formulas():
    from vessel_reconstruction.exports.csv_safety import safe_text_cell
    assert safe_text_cell("=HYPERLINK(\"x\")") == "'=HYPERLINK(\"x\")"
    assert safe_text_cell("+1") == "'+1" and safe_text_cell("@sum") == "'@sum"
    assert safe_text_cell("-cmd") == "'-cmd" and safe_text_cell("\tx") == "'\tx"
    assert safe_text_cell("s01") == "s01" and safe_text_cell(None) == ""


def test_export_with_tanks_writes_capacity_plan_and_sounding_tables(tmp_path, capsys):
    from vessel_reconstruction import tanks

    box = tanks.prism_triangles(2.0, 4.0, [(-1.0, 0.0), (1.0, 0.0), (1.0, 1.0), (-1.0, 1.0)])
    model = [tanks.Tank("db1", "No 1 water ballast", "water ballast", box, ("4", "8"), 1.025,
                        {"geometry": "traced", "density": "read"}, 4.1),
             tanks.Tank("=evil", "Hold", "dry", None, notes=["not built"])]
    task = make_box_task(tmp_path)
    manifest = export_draft(task, "r1", tmp_path / "out", tanks=model)
    stem = "Test-Box-1_r0001_DRAFT"
    roles = {entry["file"]: entry["role"] for entry in manifest["files"]}
    assert roles[f"{stem}_capacity_plan.csv"] == "capacity_plan"
    assert roles[f"{stem}_sounding_db1.csv"] == "sounding_table"
    out = tmp_path / "out"
    rows = list(csv.reader((out / f"{stem}_capacity_plan.csv").read_text().splitlines()))
    assert rows[0][0].startswith("# Draft hull model from MarinaFrame")
    header = next(r for r in rows if r and r[0] == "id")
    body = {r[0]: dict(zip(header, r)) for r in rows[rows.index(header) + 1:]}
    assert body["db1"]["volume_100_m3"] == "4.000" and body["db1"]["weight_98_t"] == "4.018"
    assert body["db1"]["source_density"] == "read" and body["db1"]["lcg_m"] == "3.000"
    assert "'=evil" in body and body["'=evil"]["built"] == "False"
    sounding = list(csv.reader((out / f"{stem}_sounding_db1.csv").read_text().splitlines()))
    header = next(r for r in sounding if r and r[0] == "sounding_m")
    levels = sounding[sounding.index(header) + 1:]
    assert len(levels) == 11 and levels[-1][:3] == ["1.000", "0.000", "4.000"]
    with zipfile.ZipFile(out / f"{stem}_package.zip") as archive:
        assert f"{stem}_capacity_plan.csv" in archive.namelist()
    assert "Capacity plan (draft tank model)" in pdf_text(out / f"{stem}_report.pdf")

    tank_file = tmp_path / "tanks.npz"
    tanks.save_tanks(model, tank_file)
    loaded = tanks.load_tanks(tank_file)
    assert [t.id for t in loaded] == ["db1", "=evil"] and loaded[1].triangles is None
    assert main(["--task", str(task), "--revision", "r1", "--out", str(tmp_path / "cli"),
                 "--tanks", str(tank_file)]) == 0
    printed = json.loads(capsys.readouterr().out)
    assert any(entry["role"] == "capacity_plan" for entry in printed["files"])


def test_export_with_structure_folder_copies_steel_tables_and_ocx(tmp_path, capsys):
    structure = tmp_path / "structure"
    structure.mkdir()
    (structure / "block_DRAFT_steel_members.csv").write_text("# DRAFT\nmember_id,weight_t\nm1,1.0\n")
    (structure / "block_DRAFT_steel_totals.csv").write_text("# DRAFT\ngroup_by,key\nall,all\n")
    (structure / "block_DRAFT.3docx").write_text("<ocx/>")
    (structure / "notes.txt").write_text("not exported")
    task = make_box_task(tmp_path)
    manifest = export_draft(task, "r1", tmp_path / "out", structure_dir=structure)
    stem = "Test-Box-1_r0001_DRAFT"
    roles = {entry["file"]: entry["role"] for entry in manifest["files"]}
    assert roles[f"{stem}_block_DRAFT_steel_members.csv"] == "steel_members"
    assert roles[f"{stem}_block_DRAFT_steel_totals.csv"] == "steel_totals"
    assert roles[f"{stem}_block_DRAFT.3docx"] == "ocx_structure"
    assert not any("notes" in name for name in roles)
    assert (tmp_path / "out" / f"{stem}_block_DRAFT.3docx").read_text() == "<ocx/>"
    with zipfile.ZipFile(tmp_path / "out" / f"{stem}_package.zip") as archive:
        assert f"{stem}_block_DRAFT_steel_members.csv" in archive.namelist()
    assert main(["--task", str(task), "--revision", "r1", "--out", str(tmp_path / "cli"),
                 "--structure", str(structure)]) == 0
    printed = json.loads(capsys.readouterr().out)
    assert any(entry["role"] == "ocx_structure" for entry in printed["files"])


def box_tank_model():
    from vessel_reconstruction import tanks

    box = tanks.prism_triangles(2.0, 4.0, [(-1.0, 0.0), (1.0, 0.0), (1.0, 1.0), (-1.0, 1.0)])
    return [tanks.Tank("db1", "No 1 water ballast", "water ballast", box, ("4", "8"), 1.025),
            tanks.Tank("hold", "Hold", "dry", None, notes=["not built"])]


def test_export_with_tanks_alone_writes_an_ocx_file_of_compartments(tmp_path):
    from vessel_reconstruction.structure import ocx

    manifest = export_draft(make_box_task(tmp_path), "r1", tmp_path / "out", tanks=box_tank_model())
    stem = "Test-Box-1_r0001_DRAFT"
    entries = {entry["file"]: entry for entry in manifest["files"]}
    assert entries[f"{stem}_tanks.3docx"]["role"] == "ocx_tanks" and entries[f"{stem}_tanks.3docx"]["compartments"] == 1
    compartments = ocx.read_compartments(tmp_path / "out" / f"{stem}_tanks.3docx")
    assert [(c.name, c.purpose, c.volume_m3) for c in compartments] == [("db1", "Ballast", pytest.approx(4.0))]
    with zipfile.ZipFile(tmp_path / "out" / f"{stem}_package.zip") as archive:
        assert f"{stem}_tanks.3docx" in archive.namelist()


def test_export_adds_tanks_to_the_one_structure_ocx_file(tmp_path, capsys):
    from vessel_reconstruction.structure import ocx
    from test_structure_export import synthetic_block

    structure = tmp_path / "structure"
    structure.mkdir()
    ocx.export_ocx(synthetic_block(), structure / "block_DRAFT.3docx")
    task = make_box_task(tmp_path)
    manifest = export_draft(task, "r1", tmp_path / "out", tanks=box_tank_model(), structure_dir=structure)
    stem = "Test-Box-1_r0001_DRAFT"
    entries = {entry["file"]: entry for entry in manifest["files"]}
    merged = entries[f"{stem}_block_DRAFT.3docx"]
    assert merged["role"] == "ocx_structure_tanks" and merged["compartments"] == 1
    assert f"{stem}_tanks.3docx" not in entries  # one file carries both
    path = tmp_path / "out" / merged["file"]
    assert len(ocx.read_plates(path)) == 4 and [c.name for c in ocx.read_compartments(path)] == ["db1"]

    # A structure folder with two OCX files keeps its files unchanged and the tanks get their own file.
    ocx.export_ocx(synthetic_block(), structure / "block_two_DRAFT.3docx")
    manifest = export_draft(task, "r1", tmp_path / "two", tanks=box_tank_model(), structure_dir=structure)
    roles = {entry["file"]: entry["role"] for entry in manifest["files"]}
    assert roles[f"{stem}_block_DRAFT.3docx"] == "ocx_structure" and roles[f"{stem}_tanks.3docx"] == "ocx_tanks"
    assert main(["--task", str(task), "--revision", "r1", "--out", str(tmp_path / "cli"),
                 "--tanks", str(save_box_tanks(tmp_path)), "--structure", str(structure)]) == 0
    printed = json.loads(capsys.readouterr().out)
    assert any(entry["role"] == "ocx_tanks" for entry in printed["files"])


def save_box_tanks(folder: Path) -> Path:
    from vessel_reconstruction import tanks

    path = folder / "box_tanks.npz"
    tanks.save_tanks(box_tank_model(), path)
    return path


def test_report_has_an_accuracy_and_limits_section_without_approval_claims(tmp_path):
    task = make_box_task(tmp_path)
    out = tmp_path / "out"
    export_draft(task, "r0001", out)
    text = pdf_text(next(out.glob("*_report.pdf")))
    flat = " ".join(text.split())
    assert "Accuracy and limits" in text
    assert "Hull: measured on clean synthetic sheets only" in flat
    assert "Tanks: none in this run." in flat and "Steel: none in this run." in flat
    assert "hull.model_reading_clean" in flat and "docs/HULL_SELECTION.md s.7" in flat
    assert "engineering_approved stays false" in flat
    section = flat.split("Accuracy and limits", 1)[1].split("Station overlay", 1)[0].lower()
    assert "verified" not in section and "approved for" not in section
