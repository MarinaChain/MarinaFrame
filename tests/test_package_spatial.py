"""Portable package display meshes and spatial records, using synthetic geometry only."""
import hashlib
import json
import shutil
import struct
import zipfile

import numpy as np
import pytest

from vessel_reconstruction.display_mesh import tank_style, write_glb
from vessel_reconstruction.exports import ExportError, export_draft
from vessel_reconstruction.structure.display import write_structure_glb
from test_exports import box_tank_model, make_box_task, prism


def display_task(tmp_path):
    task = make_box_task(tmp_path, with_cad=False)
    model = box_tank_model()
    model[0].source_labels = {"geometry": "traced", "name": "read"}
    hull = prism([(0, 0), (4, 0), (4, 5), (0, 5)], 40)
    meshes = {"hull": (hull.reshape(-1, 3) * 1000, np.arange(hull.size // 3).reshape(-1, 3)),
              "db1": (model[0].triangles.reshape(-1, 3) * 1000,
                      np.arange(model[0].triangles.size // 3).reshape(-1, 3))}
    write_glb(meshes, task / "whole-vessel-draft.glb",
              {"db1": tank_style(model[0].name, model[0].content, model[0].source_labels)})
    build = task / "domain/builds/r0001-test"
    (build / "whole-vessel-draft.glb").hardlink_to(task / "whole-vessel-draft.glb")
    result_path = build / "result.json"
    result = json.loads(result_path.read_text())
    result["exports"]["whole_vessel_glb"] = "whole-vessel-draft.glb"
    result_path.write_text(json.dumps(result))
    structure = tmp_path / "structure"
    structure.mkdir()
    write_structure_glb([{"member_id": "floor-1", "label": "floor", "thickness_mm": 8,
                          "thickness_source": "printed",
                          "contour": [(5, -1, 0), (5, 1, 0), (5, 1, 1), (5, -1, 1)]}],
                        structure / "block_DRAFT_structure.glb")
    return task, model, structure


def read_record(out, name):
    return json.loads((out / name).read_text())


def test_package_contains_metre_glbs_asset_nodes_spaces_and_frame_table(tmp_path):
    import trimesh

    task, model, structure = display_task(tmp_path)
    frames = {"spacing_m": 0.5, "zero_x_m": -1.0, "source": {"spacing": "read", "zero": "read"},
              "frames": [{"number": 0, "x_m": -1}, {"number": 2, "x_m": 0}]}
    (task / "frames.json").write_text(json.dumps(frames))
    source = task / "whole-vessel-draft.glb"
    original = source.read_bytes()
    out = tmp_path / "out"
    manifest = export_draft(task, "r1", out, tanks=model, structure_dir=structure)
    entries = {entry["file"]: entry for entry in manifest["files"]}
    assert {"assets.json", "spaces.json", "frames.json", "glb/whole-vessel-draft.glb",
            "glb/block_DRAFT_structure.glb"} <= entries.keys()
    assert source.read_bytes() == original
    glb_entry = entries["glb/whole-vessel-draft.glb"]
    assert glb_entry["units"] == "m" and glb_entry["source_units"] == "mm"
    assert glb_entry["source_sha256"] == hashlib.sha256(original).hexdigest()
    scene = trimesh.load(out / glb_entry["file"], force="scene")
    np.testing.assert_allclose(scene.bounds, [[0, 0, -4], [40, 5, 4]], atol=1e-6)
    assert {"hull", "db1"} <= set(scene.graph.nodes_geometry)

    assets = read_record(out, "assets.json")["assets"]
    ids = {a["part_id"]: a["asset_id"] for a in manifest["assets"]}
    assert set(assets) == set(ids.values())
    tank = assets[ids["db1"]]
    assert (tank["glb_file"], tank["node_name"], tank["kind"], tank["label"], tank["source_label"]) == (
        "glb/whole-vessel-draft.glb", "db1", "tank", "No 1 water ballast", "traced")
    assert assets[ids["hold"]]["glb_file"] is None
    assert assets[ids["hold"]]["node_name"] is None
    steel = assets[ids["structure_primary"]]
    assert steel["glb_file"] == "glb/block_DRAFT_structure.glb"
    assert steel["node_name"] == "structure_primary" and steel["source_label"] == "printed"
    spaces = read_record(out, "spaces.json")["spaces"]
    assert len(spaces) == 1
    assert spaces[0]["asset_id"] == ids["db1"]
    assert spaces[0]["name"] == model[0].name and spaces[0]["content_class"] == "water_ballast"
    assert spaces[0]["bounds_m"] == {"min": [2, -1, 0], "max": [4, 1, 1]}
    assert spaces[0]["source"]["geometry"] == "traced"
    exported_frames = read_record(out, "frames.json")
    for field, value in frames.items():
        assert exported_frames[field] == value
    assert exported_frames["units"] == "m" and exported_frames["source_file"] == "frames.json"
    axes = manifest["units_axes"]
    assert axes["glb"]["units"] == "m" and axes["glb"]["up"] == "y"
    assert axes["glb"]["model_to_glb"] == ["x", "z", "-y"]
    assert axes["cad"]["units"] == "mm" and axes["model"]["up"] == "z"
    assert axes["model"]["x"] == "forward" and axes["model"]["y"] == "port"
    assert manifest["engineering_approved"] is False
    with zipfile.ZipFile(out / manifest["package"]["file"]) as archive:
        assert set(archive.namelist()) == set(entries) | {manifest["manifest_file"]}
        for name, entry in entries.items():
            assert hashlib.sha256(archive.read(name)).hexdigest() == entry["sha256"]
        assert json.loads(archive.read(manifest["manifest_file"]))["units_axes"] == axes


def test_missing_display_and_frame_data_stay_unknown(tmp_path):
    task = make_box_task(tmp_path, with_cad=False)
    out = tmp_path / "out"
    manifest = export_draft(task, "r1", out, tanks=box_tank_model())
    assert not (out / "glb").exists()
    assert all(a["glb_file"] is None and a["node_name"] is None
               for a in read_record(out, "assets.json")["assets"].values())
    frames = read_record(out, "frames.json")
    assert frames["spacing_m"] is None and frames["zero_x_m"] is None
    assert frames["source"] == "unknown" and frames["frames"] == []
    assert manifest["units_axes"]["model"]["x"] == "along_length_as_drawn"
    assert manifest["units_axes"]["model"]["y"] == "transverse_sign_not_recorded"


def test_real_whole_vessel_producer_is_packaged_for_its_revision(tmp_path):
    import cadquery as cq
    from benchmarks.gunnerus.whole_vessel_assembly import export_all

    task = make_box_task(tmp_path, with_cad=False)
    export_all({"hull": cq.Solid.makeBox(1000, 2000, 3000)}, task, task=task, revision="r1")
    manifest = export_draft(task, "r1", tmp_path / "out")
    entry = next(entry for entry in manifest["files"] if entry["file"] == "glb/whole-vessel-draft.glb")
    assert entry["source_sha256"] == hashlib.sha256((task / "whole-vessel-draft.glb").read_bytes()).hexdigest()


def test_task_display_records_explain_revision_and_hash_mismatches(tmp_path):
    import cadquery as cq
    from benchmarks.gunnerus.whole_vessel_assembly import export_all

    task = make_box_task(tmp_path, with_cad=False)
    domain = task / "domain"
    shutil.copytree(domain / "builds/r0001-test", domain / "builds/r0002-test")
    shutil.copytree(domain / "revisions/r0001", domain / "revisions/r0002")
    state_path = domain / "state.json"
    state = json.loads(state_path.read_text())
    state["revision"] = 2
    state["builds"].append({"revision_id": "r0002", "path": "domain/builds/r0002-test", "valid": True})
    state_path.write_text(json.dumps(state))
    export_all({"hull": cq.Solid.makeBox(1000, 2000, 3000)}, task, task=task, revision="r2")

    older = export_draft(task, "r1", tmp_path / "old")
    assert not any(entry["file"] == "glb/whole-vessel-draft.glb" for entry in older["files"])
    assert "r0002" in str(older["display_omissions"])
    model = task / "whole-vessel-draft.glb"
    model.write_bytes(model.read_bytes() + b"corrupt")
    newer = export_draft(task, "r2", tmp_path / "new")
    assert not any(entry["file"] == "glb/whole-vessel-draft.glb" for entry in newer["files"])
    assert "hash" in str(newer["display_omissions"]).lower()


def test_task_display_without_record_is_omitted_with_reason(tmp_path):
    task = make_box_task(tmp_path, with_cad=False)
    (task / "tanks.glb").write_bytes(b"unbound model")
    manifest = export_draft(task, "r1", tmp_path / "out")
    assert not any(entry["file"] == "glb/tanks.glb" for entry in manifest["files"])
    assert any("no build record" in item["reason"] for item in manifest["display_omissions"])


def test_reexport_removes_a_previously_packaged_stale_task_model(tmp_path):
    from vessel_reconstruction.tanks import write_tanks_display

    task = make_box_task(tmp_path, with_cad=False)
    model = task / "tanks.glb"
    write_tanks_display(box_tank_model(), model, task=task, revision="r1")
    out = tmp_path / "out"
    export_draft(task, "r1", out)
    assert (out / "glb/tanks.glb").is_file()
    model.write_bytes(model.read_bytes() + b"changed")
    manifest = export_draft(task, "r1", out)
    assert any("hash" in item["reason"] for item in manifest["display_omissions"])
    from vessel_reconstruction.exports.generations import resolve_package_folder
    assert not (resolve_package_folder(out) / 'glb/tanks.glb').exists()


def test_display_record_rejects_a_changed_build(tmp_path):
    from vessel_reconstruction.tanks import write_tanks_display

    task = make_box_task(tmp_path, with_cad=False)
    write_tanks_display(box_tank_model(), task / "tanks.glb", task=task, revision="r1")
    result_path = task / "domain/builds/r0001-test/result.json"
    result = json.loads(result_path.read_text())
    result["vessel_id"] = "different-build"
    result_path.write_text(json.dumps(result))
    manifest = export_draft(task, "r1", tmp_path / "out")
    assert not any(entry["file"] == "glb/tanks.glb" for entry in manifest["files"])
    assert any("different build" in item["reason"] for item in manifest["display_omissions"])


def test_real_tank_display_producer_is_packaged_for_its_revision(tmp_path):
    from vessel_reconstruction.tanks import write_tanks_display

    task = make_box_task(tmp_path, with_cad=False)
    source = task / "tanks.glb"
    write_tanks_display(box_tank_model(), source, task=task, revision="r1")
    manifest = export_draft(task, "r1", tmp_path / "out")
    entry = next(entry for entry in manifest["files"] if entry["file"] == "glb/tanks.glb")
    assert entry["source_sha256"] == hashlib.sha256(source.read_bytes()).hexdigest()


def test_task_local_producers_refuse_missing_revision_binding(tmp_path):
    import cadquery as cq
    from benchmarks.gunnerus.whole_vessel_assembly import export_all
    from vessel_reconstruction.tanks import write_tanks_display

    task = make_box_task(tmp_path, with_cad=False)
    with pytest.raises(ValueError, match="explicit task and revision"):
        export_all({"hull": cq.Solid.makeBox(1000, 2000, 3000)}, task)
    with pytest.raises(ValueError, match="explicit task and revision"):
        write_tanks_display(box_tank_model(), task / "tanks.glb")
    assert not (task / "whole-vessel-draft.glb").exists()
    assert not (task / "tanks.glb").exists()


def test_tank_producer_does_not_record_a_build_changed_during_write(tmp_path, monkeypatch):
    from vessel_reconstruction import display_mesh
    from vessel_reconstruction.tanks import write_tanks_display

    task = make_box_task(tmp_path, with_cad=False)
    result_path = task / "domain/builds/r0001-test/result.json"
    original_writer = display_mesh.write_glb

    def write_then_change_build(*args, **kwargs):
        original_writer(*args, **kwargs)
        result = json.loads(result_path.read_text())
        result["vessel_id"] = "changed-during-write"
        result_path.write_text(json.dumps(result))

    monkeypatch.setattr(display_mesh, "write_glb", write_then_change_build)
    with pytest.raises(ValueError, match="build changed"):
        write_tanks_display(box_tank_model(), task / "tanks.glb", task=task, revision="r1")
    assert not (task / "tanks.glb.json").exists()


def test_internals_display_keeps_the_base_build_binding(tmp_path):
    import cadquery as cq
    from benchmarks.gunnerus.whole_vessel_assembly import export_all
    from benchmarks.gunnerus.whole_vessel_internals import write_internals_display

    task = make_box_task(tmp_path, with_cad=False)
    base = tmp_path / "assembly"
    base.mkdir()
    export_all({"hull": cq.Solid.makeBox(1000, 2000, 3000)}, base, task=task, revision="r1")
    model = task / "whole-vessel-draft.glb"
    write_internals_display({}, [], base / "whole-vessel-draft.glb", model, task=task, revision="r1")
    manifest = export_draft(task, "r1", tmp_path / "out")
    entry = next(entry for entry in manifest["files"] if entry["file"] == "glb/whole-vessel-draft.glb")
    assert entry["source_sha256"] == hashlib.sha256(model.read_bytes()).hexdigest()


def test_internals_display_refuses_an_unbound_base(tmp_path):
    from benchmarks.gunnerus.whole_vessel_internals import write_internals_display

    task = make_box_task(tmp_path, with_cad=False)
    base = tmp_path / "unbound.glb"
    base.write_bytes(b"unbound")
    with pytest.raises(ValueError, match="no build record"):
        write_internals_display({}, [], base, task / "whole-vessel-draft.glb", task=task, revision="r1")
    assert not (task / "whole-vessel-draft.glb").exists()


def test_spatial_package_is_repeatable_across_output_folders(tmp_path):
    task, model, structure = display_task(tmp_path)
    first = export_draft(task, "r1", tmp_path / "first", tanks=model, structure_dir=structure)
    second = export_draft(task, "r1", tmp_path / "second", tanks=model, structure_dir=structure)
    assert first["files"] == second["files"]
    assert first["package"]["sha256"] == second["package"]["sha256"]


def test_build_glb_is_confined_and_linked_without_whole_vessel_model(tmp_path):
    task, _, _ = display_task(tmp_path)
    build = task / "domain/builds/r0001-test"
    shutil.move(task / "whole-vessel-draft.glb", build / "display.glb")
    result = read_record(build, "result.json")
    result["exports"].pop("whole_vessel_glb")
    result["exports"]["glb"] = "display.glb"
    (build / "result.json").write_text(json.dumps(result))
    out = tmp_path / "out"
    manifest = export_draft(task, "r1", out)
    hull_id = next(a["asset_id"] for a in manifest["assets"] if a["kind"] == "hull")
    assert read_record(out, "assets.json")["assets"][hull_id]["glb_file"] == "glb/hull.glb"
    result["exports"]["glb"] = "../outside.glb"
    (build / "result.json").write_text(json.dumps(result))
    with pytest.raises(ExportError, match="leaves the task folder"):
        export_draft(task, "r1", tmp_path / "bad")


@pytest.mark.parametrize("field,value", [("spacing_m", 0), ("spacing_m", -1), ("zero_x_m", float("nan"))])
def test_invalid_frame_table_is_not_exported_as_known(tmp_path, field, value):
    task = make_box_task(tmp_path, with_cad=False)
    (task / "frames.json").write_text(json.dumps({field: value}))
    with pytest.raises(ExportError, match="frame"):
        export_draft(task, "r1", tmp_path / "out")


def test_invalid_glb_is_refused_and_source_is_unchanged(tmp_path):
    task = make_box_task(tmp_path, with_cad=False)
    build = task / "domain/builds/r0001-test"
    source = build / "whole-vessel-draft.glb"
    source.write_bytes(b"not a glb")
    result_path = build / "result.json"
    result = json.loads(result_path.read_text())
    result["exports"]["whole_vessel_glb"] = source.name
    result_path.write_text(json.dumps(result))
    manifest = export_draft(task, "r1", tmp_path / "out")
    assert manifest["format_results"]["glb"]["status"] == "failed"
    assert "GLB" in manifest["format_results"]["glb"]["reason"]
    assert source.read_bytes() == b"not a glb"


def test_glb_conversion_scales_existing_node_translations(tmp_path):
    import trimesh

    task, _, _ = display_task(tmp_path)
    source = task / "whole-vessel-draft.glb"
    original = source.read_bytes()
    size = struct.unpack_from("<I", original, 12)[0]
    document = json.loads(original[20:20 + size])
    hull = next(node for node in document["nodes"] if node.get("name") == "hull")
    hull["translation"] = [1000, 2000, 3000]
    payload = json.dumps(document).encode()
    payload += b" " * (-len(payload) % 4)
    buffers = original[20 + size:]
    source.write_bytes(struct.pack("<4sIII4s", b"glTF", 2, 20 + len(payload) + len(buffers), len(payload), b"JSON")
                       + payload + buffers)
    export_draft(task, "r1", tmp_path / "out")
    scene = trimesh.load(tmp_path / "out/glb/whole-vessel-draft.glb", force="scene")
    matrix, _ = scene.graph.get("hull")
    np.testing.assert_allclose(matrix[:3, 3], [1, 2, 3])
    np.testing.assert_allclose(np.diag(matrix)[:3], [0.001] * 3)


def test_spatial_ids_and_links_survive_a_geometry_revision(tmp_path):
    task, model, structure = display_task(tmp_path)
    first = export_draft(task, "r1", tmp_path / "first", tanks=model, structure_dir=structure)
    domain = task / "domain"
    shutil.copytree(domain / "builds/r0001-test", domain / "builds/r0002-test")
    shutil.copytree(domain / "revisions/r0001", domain / "revisions/r0002")
    state = read_record(domain, "state.json")
    state["revision"] = 2
    state["builds"].append({"revision_id": "r0002", "path": "domain/builds/r0002-test", "valid": True})
    (domain / "state.json").write_text(json.dumps(state))
    model[0].triangles = model[0].triangles + [0.5, 0, 0]
    model[0].name = "Renamed ballast tank"
    second = export_draft(task, "r2", tmp_path / "second", tanks=model, structure_dir=structure)
    assert first["assets"] == second["assets"] and first["vessel_id"] == second["vessel_id"]
    first_assets = read_record(tmp_path / "first", "assets.json")["assets"]
    second_assets = read_record(tmp_path / "second", "assets.json")["assets"]
    assert first_assets.keys() == second_assets.keys()
    for asset_id in first_assets:
        for key in ("glb_file", "node_name"):
            assert first_assets[asset_id][key] == second_assets[asset_id][key]
    space = read_record(tmp_path / "second", "spaces.json")["spaces"][0]
    assert space["bounds_m"]["min"][0] == 2.5 and space["name"] == "Renamed ballast tank"


def test_standalone_tank_glb_and_guessed_frames_keep_their_sources(tmp_path):
    task, model, _ = display_task(tmp_path)
    (task / "whole-vessel-draft.glb").rename(task / "tanks.glb")
    build = task / "domain/builds/r0001-test"
    result_path = build / "result.json"
    result = json.loads(result_path.read_text())
    result["exports"]["tanks_glb"] = result["exports"].pop("whole_vessel_glb")
    result_path.write_text(json.dumps(result))
    (task / "frames.json").write_text(json.dumps({"spacing_m": 0.55, "zero_x_m": 0, "source": "guessed"}))
    out = tmp_path / "out"
    export_draft(task, "r1", out, tanks=model)
    assert read_record(out, "frames.json")["source"] == "guessed"
    tank = next(a for a in read_record(out, "assets.json")["assets"].values() if a["part_id"] == "db1")
    assert tank["glb_file"] == "glb/tanks.glb" and tank["node_name"] == "db1"


def test_metre_glb_is_not_scaled_twice(tmp_path):
    import trimesh

    task = make_box_task(tmp_path, with_cad=False)
    build = task / "domain/builds/r0001-test"
    mesh = trimesh.creation.box(extents=(40, 8, 5))
    write_glb({"hull": (mesh.vertices, mesh.faces)}, build / "display.glb")
    result = read_record(build, "result.json")
    result["exports"].update(glb="display.glb", glb_units="m")
    (build / "result.json").write_text(json.dumps(result))
    export_draft(task, "r1", tmp_path / "out")
    scene = trimesh.load(tmp_path / "out/glb/hull.glb", force="scene")
    np.testing.assert_allclose(scene.extents, [40, 5, 8])


def test_units_block_keeps_declared_stl_units(tmp_path):
    task = make_box_task(tmp_path, with_cad=False)
    build = task / "domain/builds/r0001-test"
    result = read_record(build, "result.json")
    result["exports"]["stl_units"] = "m"
    (build / "result.json").write_text(json.dumps(result))
    manifest = export_draft(task, "r1", tmp_path / "out")
    assert manifest["units_axes"]["cad"]["units"] == "mm"
    assert manifest["units_axes"]["stl"]["units"] == "m"


@pytest.mark.parametrize("table", [[], {"units": "mm"}, {"frames": "not a table"},
                                    {"frames": [{"number": 1, "x_m": float("nan")}] }])
def test_malformed_frame_records_are_refused(tmp_path, table):
    task = make_box_task(tmp_path, with_cad=False)
    (task / "frames.json").write_text(json.dumps(table))
    with pytest.raises(ExportError, match="frame"):
        export_draft(task, "r1", tmp_path / "out")
