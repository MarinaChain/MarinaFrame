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
from uuid import UUID, uuid4

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
                          "stl_units": "mm", "iges": "model-draft.iges", "iges_units": "mm",
                          "3dm": "model-draft.3dm", "3dm_units": "mm"},
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
        import cadquery as cq
        from vessel_reconstruction.cad_exports import export_iges
        from vessel_reconstruction.rhino_exports import CadPart, export_3dm

        shape = cq.Solid.makeBox(40000, 8000, 5000, cq.Vector(0, -4000, 0))
        export_iges(shape, build / "model-draft.iges")
        export_3dm([CadPart("hull", shape, "Hull")], build / "model-draft.3dm")
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
                     f"{stem}_report.pdf", f"{stem}_model.step", f"{stem}_model.stl",
                     f"{stem}_model.iges", f"{stem}_model.3dm", "assets.json", "spaces.json", "frames.json"}
    assert manifest["engineering_approved"] is False and manifest["not_built"] == []
    assert manifest["open_guesses"] == 1
    out = tmp_path / "out"
    for entry in manifest["files"]:
        assert hashlib.sha256((out / entry["file"]).read_bytes()).hexdigest() == entry["sha256"]
    for suffix, role in (("iges", "iges_model"), ("3dm", "rhino_model")):
        entry = next(entry for entry in manifest["files"] if entry["role"] == role)
        source = task / "domain/builds/r0001-test" / f"model-draft.{suffix}"
        assert (out / entry["file"]).read_bytes() == source.read_bytes()
        assert entry["source_sha256"] == entry["sha256"]
        assert entry["units"] == "mm"

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


@pytest.mark.parametrize("existing", [False, True])
def test_package_write_failure_keeps_target_unchanged(tmp_path, monkeypatch, existing):
    from vessel_reconstruction.exports import package

    task = make_box_task(tmp_path, with_cad=False)
    target = tmp_path / "out"
    if existing:
        target.mkdir()
        (target / "old.txt").write_text("previous package")

    def fail(*args, **kwargs):
        raise OSError("injected write failure")

    monkeypatch.setattr(package, "write_hydrostatics", fail)
    with pytest.raises(OSError, match="injected"):
        export_draft(task, "r1", target)
    if existing:
        assert sorted(path.name for path in target.iterdir()) == ["old.txt"]
        assert (target / "old.txt").read_text() == "previous package"
    else:
        assert not target.exists()


def test_package_replaces_existing_directory_after_complete_write(tmp_path):
    task = make_box_task(tmp_path, with_cad=False)
    target = tmp_path / "out"
    target.mkdir()
    (target / "viewer_capture.png").write_bytes(b"not an image")
    manifest = export_draft(task, "r1", target)
    from vessel_reconstruction.exports.generations import resolve_package_folder
    published = resolve_package_folder(target)
    assert (published / manifest['package']['file']).is_file()
    assert (published / 'viewer_capture.png').read_bytes() == b'not an image'
    assert not list(tmp_path.glob(".out.*"))


def test_package_destination_cannot_replace_current_directory(tmp_path, monkeypatch):
    from vessel_reconstruction.exports import package

    target = tmp_path / "out"
    target.mkdir()
    monkeypatch.chdir(target)
    with pytest.raises(ExportError, match="current directory"):
        with package._package_stage(Path(".")):
            pass


def test_failed_ocx_export_keeps_other_package_files(tmp_path, monkeypatch):
    from vessel_reconstruction.exports import package

    task = make_box_task(tmp_path, with_cad=False)
    def fail(*args, **kwargs):
        raise RuntimeError("injected OCX failure")

    monkeypatch.setattr(package.ocx, "export_ocx", fail)
    manifest = export_draft(task, "r1", tmp_path / "out", tanks=box_tank_model())
    assert manifest["format_results"]["ocx"] == {"status": "failed", "reason": "injected OCX failure"}
    assert any(entry["role"] == "offsets_table" for entry in manifest["files"])


def test_old_revision_uses_its_recorded_display_glb(tmp_path):
    import trimesh

    task = make_box_task(tmp_path, with_cad=False)
    domain = task / "domain"
    old = domain / "builds/r0001-test"
    new = domain / "builds/r0002-test"
    shutil.copytree(old, new)
    shutil.copytree(domain / "revisions/r0001", domain / "revisions/r0002")
    for build, length in ((old, 1), (new, 2)):
        result_path = build / "result.json"
        result = json.loads(result_path.read_text())
        result["exports"]["glb"] = "display.glb"
        result_path.write_text(json.dumps(result))
        trimesh.creation.box(extents=[length, 1, 1]).export(build / "display.glb")
    shutil.copyfile(new / "display.glb", task / "whole-vessel-draft.glb")
    state_path = domain / "state.json"
    state = json.loads(state_path.read_text())
    state["revision"] = 2
    state["builds"].append({"revision_id": "r0002", "path": "domain/builds/r0002-test", "valid": True})
    state_path.write_text(json.dumps(state))

    manifest = export_draft(task, "r1", tmp_path / "package")
    displays = [entry for entry in manifest["files"] if entry["role"] == "display_glb"]
    assert len(displays) == 1
    assert displays[0]["source_sha256"] == hashlib.sha256((old / "display.glb").read_bytes()).hexdigest()


def test_manifest_identity_is_stable_across_revisions_and_display_names(tmp_path):
    from vessel_reconstruction.structure.steel import write_steel_tables
    from test_structure_export import synthetic_block

    task = make_box_task(tmp_path, with_cad=False)
    domain = task / "domain"
    checkpoint = (domain / "state.json").read_bytes()
    structure = tmp_path / "structure"
    write_steel_tables(synthetic_block(), structure, "block_DRAFT")
    first = export_draft(task, "r1", tmp_path / "first", tanks=box_tank_model(), structure_dir=structure)
    assert first["schema_version"] == "1.0"
    assert UUID(first["vessel_id"]).version == 4
    assert first["parent_revision"] == "r0000"
    assert (domain / "state.json").read_bytes() == checkpoint
    identity = json.loads((domain / "vessel_identity.json").read_text())
    assert identity["vessel_id"] == first["vessel_id"]
    assets = {(a["kind"], a["part_id"]): a["asset_id"] for a in first["assets"]}
    assert set(assets) == {("hull", "hull"), ("tank", "db1"), ("tank", "hold"),
                           ("steel_group", "structure_shell"), ("steel_group", "structure_bulkhead"),
                           ("steel_group", "structure_primary")}
    assert len(set(assets.values())) == len(assets)
    assert all(UUID(value).version == 5 for value in assets.values())

    shutil.copytree(domain / "builds/r0001-test", domain / "builds/r0002-test")
    shutil.copytree(domain / "revisions/r0001", domain / "revisions/r0002")
    state = json.loads(checkpoint)
    state["revision"] = 2
    state["builds"].append({"revision_id": "r0002", "path": "domain/builds/r0002-test", "valid": True})
    (domain / "state.json").write_text(json.dumps(state))
    second = export_draft(task, "r2", tmp_path / "second", vessel="Renamed vessel",
                          tanks=list(reversed(box_tank_model())), structure_dir=structure)
    assert second["vessel_id"] == first["vessel_id"]
    assert second["revision"] == "r0002" and second["parent_revision"] == first["revision"]
    assert {(a["kind"], a["part_id"]): a["asset_id"] for a in second["assets"]} == assets
    with zipfile.ZipFile(tmp_path / "second" / second["package"]["file"]) as archive:
        packed = json.loads(archive.read(second["manifest_file"]))
    assert packed["assets"] == second["assets"]
    assert packed["vessel_id"] == first["vessel_id"]
    assert packed["engineering_approved"] is False


def test_manifest_uses_domain_uuid_and_keeps_known_particulars(tmp_path):
    task = make_box_task(tmp_path, with_cad=False)
    domain = task / "domain"
    vessel_id = str(uuid4())
    state = json.loads((domain / "state.json").read_text())
    state["vessel_uuid"] = vessel_id
    (domain / "state.json").write_text(json.dumps(state))
    manifest = export_draft(task, "r1", tmp_path / "out")
    assert manifest["vessel_id"] == vessel_id
    assert manifest["particulars"] == {"vessel_name": "Test Box 1", "draft_m": 3.0}
    assert "imo" not in manifest and "imo" not in manifest["particulars"]


@pytest.mark.parametrize("typed, expected", [("7654329", "7654329"), (" IMO 7654329 ", "7654329"),
                                            (None, None), ("", None), ("  ", None)])
def test_manifest_imo_comes_only_from_typed_intake(tmp_path, typed, expected):
    task = make_box_task(tmp_path, with_cad=False)
    domain = task / "domain"
    (domain / "input").mkdir()
    particulars = {"vessel_name": "Typed name", "loa_m": 40.0, "beam_m": 8.0}
    if typed is not None:
        particulars["imo"] = typed
    (domain / "input/intake.json").write_text(json.dumps({"particulars": particulars}))
    # A build's slug and unrelated fields are not a typed IMO number.
    result_path = domain / "builds/r0001-test/result.json"
    result = json.loads(result_path.read_text())
    result.update(vessel_id="7654329", imo="7654329")
    result_path.write_text(json.dumps(result))
    manifest = export_draft(task, "r1", tmp_path / "out")
    assert manifest["particulars"]["loa_m"] == 40.0
    assert manifest["particulars"]["vessel_name"] == "Typed name"
    if expected is None:
        assert "imo" not in manifest and "imo" not in manifest["particulars"]
    else:
        assert manifest["imo"] == expected and manifest["particulars"]["imo"] == expected


@pytest.mark.parametrize("typed", ["7654328", "123456", "12345678", "７６５４３２９", 7654329, True])
def test_manifest_rejects_invalid_typed_imo_before_writing_exports(tmp_path, typed):
    task = make_box_task(tmp_path, with_cad=False)
    (task / "domain/input").mkdir()
    (task / "domain/input/intake.json").write_text(json.dumps({"particulars": {"imo": typed}}))
    with pytest.raises(ExportError, match="IMO"):
        export_draft(task, "r1", tmp_path / "out")
    assert not (tmp_path / "out").exists()


def test_manifest_rejects_corrupt_persisted_identity(tmp_path):
    task = make_box_task(tmp_path, with_cad=False)
    identity = task / "domain/vessel_identity.json"
    identity.write_text('{"vessel_id": "not-a-uuid"}')
    with pytest.raises(ExportError, match="identity"):
        export_draft(task, "r1", tmp_path / "out")
    assert json.loads(identity.read_text())["vessel_id"] == "not-a-uuid"


def test_manifest_steel_ids_match_existing_display_nodes(tmp_path):
    from vessel_reconstruction.structure.display import write_structure_glb
    from vessel_reconstruction.structure.steel import write_steel_tables

    structure = tmp_path / "structure"
    members = [{"member_id": "frame-1", "label": "frame", "group": "transverse",
                "trace": [(5, 1, 0), (5, 1, 1)], "web_direction": (0, -1, 0),
                "profile": {"kind": "FlatBar", "height_mm": 100, "web_mm": 6},
                "thickness_mm": 6.0, "area_m2": 0.1}]
    write_steel_tables({"members": members}, structure, "block_DRAFT")
    write_structure_glb(members, structure / "block_DRAFT_structure.glb")
    task = make_box_task(tmp_path, with_cad=False)
    manifest = export_draft(task, "r1", tmp_path / "out")
    assert not any(a["kind"] == "steel_group" for a in manifest["assets"])
    manifest = export_draft(task, "r1", tmp_path / "steel", structure_dir=structure)
    assert [a["part_id"] for a in manifest["assets"] if a["kind"] == "steel_group"] == ["structure_stiffener"]


def test_manifest_root_revision_has_no_parent_and_uses_existing_hull_part_id(tmp_path):
    task = make_box_task(tmp_path, with_cad=False)
    state_path = task / "domain/state.json"
    state = json.loads(state_path.read_text())
    state["builds"][0].update(valid=True, path="domain/builds/r0001-test")
    state_path.write_text(json.dumps(state))
    result_path = task / "domain/builds/r0001-test/result.json"
    result = json.loads(result_path.read_text())
    result["parts"] = [{"id": "envelope-1", "kind": "hull_envelope"}]
    result_path.write_text(json.dumps(result))
    manifest = export_draft(task, "r0", tmp_path / "out")
    assert manifest["parent_revision"] is None
    assert manifest["assets"][0]["part_id"] == "envelope-1"


def test_export_of_real_build_fixture_without_cad(tmp_path):
    task = tmp_path / "task"
    shutil.copytree(FIXTURE / "task", task)
    manifest = export_draft(task, "r3", tmp_path / "out", draft_m=8.0)
    stem = "factory-70ed8f4700b0_r0003_DRAFT"
    assert manifest["not_built"] == ["step_model", "iges_model", "rhino_model", "stl_mesh"]
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
    assert printed["not_built"] == ["step_model", "iges_model", "rhino_model", "stl_mesh"]
    assert (tmp_path / "cli" / printed["package"]["file"]).is_file()


@pytest.mark.parametrize("missing", ["declaration", "file"])
def test_old_builds_without_new_cad_formats_keep_step_and_stl(tmp_path, missing):
    task = make_box_task(tmp_path)
    build = task / "domain/builds/r0001-test"
    if missing == "declaration":
        result = json.loads((build / "result.json").read_text())
        for kind in ("iges", "3dm"):
            result["exports"].pop(kind)
            result["exports"].pop(f"{kind}_units")
        (build / "result.json").write_text(json.dumps(result))
    else:
        for suffix in ("iges", "3dm"):
            (build / f"model-draft.{suffix}").unlink()
    manifest = export_draft(task, "r1", tmp_path / "out")
    assert manifest["not_built"] == ["iges_model", "rhino_model"]
    roles = {entry["role"] for entry in manifest["files"]}
    assert {"step_model", "stl_mesh"} <= roles
    assert not {"iges_model", "rhino_model"} & roles


@pytest.mark.parametrize("kind", ["iges", "3dm"])
def test_new_cad_export_paths_cannot_leave_the_build(tmp_path, kind):
    task = make_box_task(tmp_path)
    build = task / "domain/builds/r0001-test"
    result = json.loads((build / "result.json").read_text())
    result["exports"][kind] = f"../outside.{kind}"
    (build / "result.json").write_text(json.dumps(result))
    with pytest.raises(ExportError, match="leaves the task folder"):
        export_draft(task, "r1", tmp_path / "out")


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


# ---------------------------------------------------------------------------
# Viewer capture: the app's picture of its 3D view is the hero image on page 1 of the report


def page_one_images(path: Path) -> int:
    """Images drawn on page 1 (get_images would also list the images of other pages: the PDF shares them)."""
    fitz = pytest.importorskip("fitz")
    with fitz.open(path) as document:
        return len(document[0].get_image_info())


def report_with_capture(tmp_path, capture: bytes | None) -> Path:
    """Export the synthetic box; the app's capture file is in the export folder first, when given."""
    task = make_box_task(tmp_path)
    out = tmp_path / "out"
    out.mkdir()
    if capture is not None:
        (out / "viewer_capture.png").write_bytes(capture)
    export_draft(task, "r0001", out)
    from vessel_reconstruction.exports.generations import resolve_package_folder
    return next(resolve_package_folder(out).glob('*_report.pdf'))


def png_bytes(size=(1600, 1000), colour="white") -> bytes:
    import io

    buffer = io.BytesIO()
    Image.new("RGB", size, colour).save(buffer, format="PNG")
    return buffer.getvalue()


def test_report_without_a_viewer_capture_has_no_picture_on_page_one(tmp_path):
    report = report_with_capture(tmp_path, None)
    assert page_one_images(report) == 0
    assert "3D view as shown in the app" not in pdf_text(report)


def test_report_puts_the_viewer_capture_on_page_one(tmp_path):
    report = report_with_capture(tmp_path, png_bytes())
    assert page_one_images(report) == 1
    text = " ".join(pdf_text(report).split())
    assert "3D view as shown in the app when this report was exported" in text
    # The rest of page 1 and the report are unchanged: the summary and the footer still print.
    assert FOOTER in text and "Particulars (built model)" in text and "Station overlay" in text


def test_a_capture_that_is_not_an_image_leaves_the_report_complete(tmp_path):
    report = report_with_capture(tmp_path, b"this is not a png")
    assert page_one_images(report) == 0
    assert "Particulars (built model)" in pdf_text(report)


def test_the_capture_is_not_listed_in_the_package(tmp_path):
    report = report_with_capture(tmp_path, png_bytes())
    manifest = json.loads(next(report.parent.glob("*_manifest.json")).read_text())
    assert all(entry["file"] != "viewer_capture.png" for entry in manifest["files"])
    with zipfile.ZipFile(next(report.parent.glob("*_package.zip"))) as archive:
        assert "viewer_capture.png" not in archive.namelist()


def test_table_hydrostatics_preserves_inner_void_and_outer_beam():
    # A 40 m prism has an 8 m wide section and a 2 m wide void from z=1 to z=4.
    pieces = [
        {"points_yz_m": [[0, 0], [4, 0], [4, 1], [0, 1]]},
        {"points_yz_m": [[4, 1], [4, 4]], "inner_points_yz_m": [[1, 1], [1, 4]]},
        {"points_yz_m": [[0, 4], [4, 4], [4, 5], [0, 5]]},
    ]
    sections = [{"x_m": x, "pieces": pieces} for x in (0, 40)]
    h = table_hydrostatics(sections, 3, "test")
    assert h.largest_section_area_m2 == pytest.approx(20, abs=0.03)
    assert h.volume_m3 == pytest.approx(800, abs=1.2)
    assert h.vcb_m == pytest.approx(1.4, abs=0.002)
    assert h.waterplane_area_m2 == pytest.approx(240)
    assert h.bmt_m == pytest.approx(2.1, abs=0.004)
    assert h.waterline_beam_m == pytest.approx(8)
    assert h.largest_breadth_below_waterline_m == pytest.approx(8)


def test_table_hydrostatics_plain_box_analytic_moments():
    sections = [box_section("s01", 0, "traced"), box_section("s02", 40, "traced")]
    h = table_hydrostatics(sections, 3, "test")
    assert h.largest_section_area_m2 == pytest.approx(24)
    assert h.vcb_m == pytest.approx(1.5)
    assert h.bmt_m == pytest.approx(8**2 / (12 * 3))
    assert h.waterline_beam_m == pytest.approx(8)
