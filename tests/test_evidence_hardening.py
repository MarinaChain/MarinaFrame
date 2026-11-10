"""Independent adversarial regressions for transactional, immutable run evidence."""
from __future__ import annotations

import copy
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from vessel_reconstruction import pipeline
from vessel_reconstruction.pipeline import reconstruct, recover_interrupted_run, verify_run
from vessel_reconstruction.provenance import digest_file
from vessel_reconstruction.schema import loads_bounded_json, validate_spec
from vessel_reconstruction.transaction import RunPublicationError, RunTransaction


def independent_spec(root):
    root.mkdir(parents=True, exist_ok=True)
    image = Image.new("L", (660, 230), 255)
    draw = ImageDraw.Draw(image)
    sections = []
    for i, station in enumerate((0, 4, 8)):
        centre, baseline = i * 220 + 20, 205
        draw.line([(centre + 50, baseline), (centre + 80, baseline - 150)], fill=0, width=3)
        sections.append({"id": f"station-{i}", "x_m": station,
                         "roi_px": [i * 220 + 5, 40, i * 220 + 205, 215],
                         "calibration": {"centerline_px": centre, "baseline_px": baseline, "pixels_per_metre": 50},
                         "z_min_m": 0, "z_max_m": 3,
                         "evidence": "Independent controlled trace, panel, station and datum."})
    image.save(root / "drawing.png")
    spec = {"schema_version": "1.0", "vessel_id": "evidence-regression", "units": "m",
            "source": {"file": "drawing.png"}, "symmetry": "port_starboard",
            "symmetry_evidence": "Explicit controlled bilateral assumption.",
            "end_closure": "flat_at_terminal_stations", "sections": sections}
    (root / "spec.json").write_text(json.dumps(spec))
    return spec


def test_failed_iges_writer_keeps_other_cad_exports(tmp_path, monkeypatch):
    from vessel_reconstruction import geometry

    independent_spec(tmp_path)

    def fail(*args, **kwargs):
        raise RuntimeError("injected IGES writer failure")

    monkeypatch.setattr(geometry, "export_iges", fail)
    result = reconstruct(tmp_path / "spec.json", tmp_path / "run", export_cad=True)
    assert result["status"] == "review_required", result["gaps"]
    assert result["export_results"]["iges"] == {"status": "failed", "reason": "injected IGES writer failure"}
    for format_name in ("step", "3dm", "stl"):
        assert result["export_results"][format_name]["status"] == "ok"
        assert (tmp_path / "run" / result["exports"][format_name]).is_file()
    assert "iges" not in result["exports"]
    assert verify_run(tmp_path / "run")["exports_allowed"]


def test_failed_step_reload_keeps_other_cad_exports(tmp_path, monkeypatch):
    from vessel_reconstruction import geometry

    independent_spec(tmp_path)

    def fail(*args, **kwargs):
        raise RuntimeError("injected STEP reload failure")

    monkeypatch.setattr(geometry.cq.importers, "importStep", fail)
    result = reconstruct(tmp_path / "spec.json", tmp_path / "run", export_cad=True)
    assert result["status"] == "review_required", result["gaps"]
    assert result["export_results"]["step"]["status"] == "failed"
    assert "step" not in result["exports"]
    assert not (tmp_path / "run/model.step").exists()
    assert all((tmp_path / "run" / result["exports"][name]).is_file() for name in ("iges", "3dm", "stl"))
    assert verify_run(tmp_path / "run")["exports_allowed"]


@pytest.fixture(scope="module")
def good_run(tmp_path_factory):
    root = tmp_path_factory.mktemp("complete-evidence")
    independent_spec(root)
    result = reconstruct(root / "spec.json", root / "run", export_cad=True)
    assert result["status"] == "review_required", result["gaps"]
    assert verify_run(root / "run")["exports_allowed"]
    return root / "run"


def cloned_run(good_run, root):
    target = root / "run"
    shutil.copytree(good_run, target)
    return target


def mutate_json(root, name, action):
    path = root / name
    document = json.loads(path.read_text())
    action(document)
    path.write_text(json.dumps(document))


def rehash_declared_record(root):
    """Independent test helper: simulate a replacement of the local hash file.

    The verifier promises useful internal-consistency checks, not authentication
    against a replacement of all evidence. This helper does not repair semantics.
    """
    manifest = json.loads((root / "manifest.json").read_text())
    for name in manifest["files"]:
        raw = (root / name).read_bytes()
        manifest["files"][name] = {"sha256": hashlib.sha256(raw).hexdigest(), "size_bytes": len(raw)}
    result = json.loads((root / "result.json").read_text())
    canonical = json.dumps(result, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()
    manifest["record"] = {"file": "result.json", "sha256": manifest["files"]["result.json"]["sha256"],
                          "canonical_sha256": hashlib.sha256(canonical).hexdigest()}
    (root / "manifest.json").write_text(json.dumps(manifest))


@pytest.mark.parametrize("artifact", ["result.json", "replay_spec.json", "cad_sections.json", "extracted_sections.json",
                                     "input_spec.json", "mesh.json", "model.step", "model.stl", "source.png"])
def test_each_authoritative_artifact_is_hash_bound(good_run, tmp_path, artifact):
    root = cloned_run(good_run, tmp_path)
    with (root / artifact).open("ab") as stream:
        stream.write(b"\nchanged")
    verification = verify_run(root)
    assert verification["valid"] is False
    assert verification["exports_allowed"] is False


@pytest.mark.parametrize("mutation", [
    lambda value: value["metrics"].update(volume_m3=123456789),
    lambda value: value["sections"][0].update(x_m=54321),
    lambda value: value.update(status="failed"),
    lambda value: value.update(gaps=[{"id": "failure:vessel", "kind": "failure", "severity": "blocking", "message": "Failed."}]),
    lambda value: value["provenance"].update(implementation_sha256="0" * 64),
    lambda value: value.update(review={"state": "accept_geometry", "engineering_approved": False}),
])
def test_result_semantics_reject_inconsistency_even_after_rehash(good_run, tmp_path, mutation):
    root = cloned_run(good_run, tmp_path)
    mutate_json(root, "result.json", mutation)
    rehash_declared_record(root)
    assert verify_run(root)["valid"] is False


@pytest.mark.parametrize("artifact", ["cad_sections.json", "replay_spec.json", "input_spec.json", "model.step", "model.stl", "mesh.json"])
def test_deleting_artifact_and_its_manifest_entry_cannot_hide_required_evidence(good_run, tmp_path, artifact):
    root = cloned_run(good_run, tmp_path)
    (root / artifact).unlink()
    mutate_json(root, "manifest.json", lambda value: value["files"].pop(artifact))
    assert verify_run(root)["valid"] is False


def test_empty_manifest_does_not_verify_vacuously(good_run, tmp_path):
    root = cloned_run(good_run, tmp_path)
    mutate_json(root, "manifest.json", lambda value: value.update(files={}))
    assert verify_run(root)["valid"] is False


def test_unexplained_native_side_output_is_not_servable_even_if_hashed(good_run, tmp_path):
    root = cloned_run(good_run, tmp_path)
    (root / "partial_native_output.step").write_text("untracked partial model")
    raw = (root / "partial_native_output.step").read_bytes()
    mutate_json(root, "manifest.json", lambda value: value["files"].update({"partial_native_output.step": {
        "sha256": hashlib.sha256(raw).hexdigest(), "size_bytes": len(raw)}}))
    assert verify_run(root)["valid"] is False


@pytest.mark.parametrize("name", ["../outside.json", "/tmp/outside.json", "implementation_source/../source.png", "source\\escape.png"])
def test_manifest_traversal_is_rejected(good_run, tmp_path, name):
    root = cloned_run(good_run, tmp_path)
    mutate_json(root, "manifest.json", lambda value: value["files"].update({name: {"sha256": "0" * 64, "size_bytes": 0}}))
    assert verify_run(root)["valid"] is False


def test_symlinked_artifact_is_not_followed(good_run, tmp_path):
    root = cloned_run(good_run, tmp_path)
    outside = tmp_path / "outside.png"
    (root / "source.png").replace(outside)
    (root / "source.png").symlink_to(outside)
    assert verify_run(root)["valid"] is False


def test_truncated_or_duplicate_key_manifest_is_rejected(good_run, tmp_path):
    root = cloned_run(good_run, tmp_path)
    (root / "manifest.json").write_text('{"files": {}, "files": {}}')
    assert verify_run(root)["valid"] is False
    (root / "manifest.json").write_text('{"files":')
    assert verify_run(root)["valid"] is False


def test_legacy_record_is_recognized_without_upgrading_assurance(tmp_path):
    (tmp_path / "result.json").write_text(json.dumps({"schema_version": "1.0", "status": "review_required", "sources": [], "provenance": {}}))
    verification = verify_run(tmp_path)
    assert verification["assurance"] == "legacy_unsealed"
    assert not verification["valid"] and not verification["exports_allowed"]


def _reuse_valid_geometry(monkeypatch, good_run):
    reference = json.loads((good_run / "result.json").read_text())
    # Recreate the CAD representation from this test's current observations,
    # preserving actual independently built points and metrics from good_run.
    def build(sections, **_options):
        normalized = []
        for observed, known in zip(sections, reference["normalized_sections"]):
            normalized.append({**observed, "cad_points_yz_m": known["cad_points_yz_m"], "cad_approximation": known["cad_approximation"]})
        return object(), normalized

    def export(_shape, out, *, export_cad):
        # Copy every file the reference export record names (mesh, STEP, IGES, 3dm, STL), not a fixed list.
        names = [value for key, value in reference["exports"].items() if not key.endswith("_units")]
        for name in names:
            shutil.copyfile(good_run / name, out / name)
        return copy.deepcopy(reference["exports"]), copy.deepcopy(reference["metrics"])

    monkeypatch.setattr(pipeline, "build_hull", build)
    monkeypatch.setattr(pipeline, "metrics_for", lambda _shape: copy.deepcopy(reference["metrics"]))
    monkeypatch.setattr(pipeline, "export_geometry", export)


@pytest.mark.parametrize("filename", ["extracted_sections.json", "cad_sections.json", "result.json", "manifest.json"])
def test_required_write_failure_never_publishes_success_or_geometry(good_run, tmp_path, monkeypatch, filename):
    independent_spec(tmp_path)
    _reuse_valid_geometry(monkeypatch, good_run)
    original = pipeline.write_json
    fired = False

    def fault(path, value):
        nonlocal fired
        if path.name == filename and not fired:
            fired = True
            raise OSError("Controlled required evidence write failure")
        return original(path, value)

    monkeypatch.setattr(pipeline, "write_json", fault)
    result = reconstruct(tmp_path / "spec.json", tmp_path / "run")
    assert fired
    assert result["status"] == "failed"
    assert result["exports"] == {} and result["parts"] == []
    assert result["metrics"] == {} and result["normalized_sections"] == []
    assert any(g["severity"] == "blocking" for g in result["gaps"])
    assert not any((tmp_path / "run" / name).exists() for name in ("mesh.json", "model.step", "model.stl", "cad_sections.json"))
    assert verify_run(tmp_path / "run")["valid"]
    assert not verify_run(tmp_path / "run")["exports_allowed"]


def test_persistent_storage_failure_returns_no_claimed_terminal_success(good_run, tmp_path, monkeypatch):
    independent_spec(tmp_path)
    _reuse_valid_geometry(monkeypatch, good_run)
    original = pipeline.write_json

    def fault(path, value):
        if path.name == "manifest.json":
            raise OSError("Controlled persistent storage failure")
        return original(path, value)

    monkeypatch.setattr(pipeline, "write_json", fault)
    with pytest.raises(RunPublicationError, match="complete terminal record"):
        reconstruct(tmp_path / "spec.json", tmp_path / "run")
    assert not (tmp_path / "run").exists()
    assert list(tmp_path.glob(".run.staging-*"))
    assert (tmp_path / ".run.run-lock").exists()
    monkeypatch.setattr(pipeline, "write_json", original)
    recovered = recover_interrupted_run(tmp_path / "run")
    assert recovered["published"] and recovered["status"] == "interrupted"
    verification = verify_run(tmp_path / "run")
    assert verification["valid"] and not verification["exports_allowed"]


@pytest.mark.parametrize("stage", ["implementation_capture", "export_after_files", "required_digest", "atomic_rename"])
def test_copy_export_hash_and_publication_failures_withdraw_geometry(good_run, tmp_path, monkeypatch, stage):
    from vessel_reconstruction import run_record
    independent_spec(tmp_path)
    _reuse_valid_geometry(monkeypatch, good_run)
    if stage == "implementation_capture":
        def broken_copy(directory):
            (directory / "implementation_source").mkdir()
            (directory / "implementation_source" / "partial.py").write_text("partial")
            raise OSError("Controlled snapshot copy failure")
        monkeypatch.setattr(pipeline, "snapshot_implementation", broken_copy)
    elif stage == "export_after_files":
        exporter = pipeline.export_geometry
        def broken_reload(*args, **kwargs):
            exporter(*args, **kwargs)
            raise RuntimeError("Controlled failure after exports before reload success")
        monkeypatch.setattr(pipeline, "export_geometry", broken_reload)
    elif stage == "required_digest":
        digest = run_record.digest_file
        def broken_digest(path):
            if path.name == "mesh.json":
                raise OSError("Controlled required output digest failure")
            return digest(path)
        monkeypatch.setattr(run_record, "digest_file", broken_digest)
    else:
        publish = RunTransaction.publish
        fired = False
        def broken_rename(transaction):
            nonlocal fired
            if not fired:
                fired = True
                raise OSError("Controlled pre-rename publication failure")
            return publish(transaction)
        monkeypatch.setattr(RunTransaction, "publish", broken_rename)
    result = reconstruct(tmp_path / "spec.json", tmp_path / "run")
    assert result["status"] == "failed" and result["exports"] == {} and result["parts"] == []
    assert not any((tmp_path / "run" / filename).exists() for filename in ("model.step", "model.stl", "mesh.json", "cad_sections.json"))
    assert verify_run(tmp_path / "run")["valid"]


def test_existing_empty_destination_and_active_reservation_are_never_overwritten(tmp_path):
    independent_spec(tmp_path)
    (tmp_path / "occupied").mkdir()
    with pytest.raises(FileExistsError):
        reconstruct(tmp_path / "spec.json", tmp_path / "occupied")
    transaction = RunTransaction(tmp_path / "run")
    try:
        with pytest.raises(FileExistsError):
            reconstruct(tmp_path / "spec.json", tmp_path / "run")
        assert recover_interrupted_run(tmp_path / "run")["reason"] == "active_transaction"
    finally:
        transaction.close()


def test_final_reservation_cleanup_sync_cannot_turn_durable_success_into_failed_job(good_run, tmp_path, monkeypatch):
    from vessel_reconstruction import transaction as transactions
    independent_spec(tmp_path)
    _reuse_valid_geometry(monkeypatch, good_run)
    original = transactions.sync_directory
    parent_syncs = 0

    def failure_on_cleanup(directory):
        nonlocal parent_syncs
        if directory == tmp_path:
            parent_syncs += 1
            if parent_syncs == 3:  # reservation create, durable publish, then cleanup
                raise OSError("Controlled final reservation cleanup fsync failure")
        return original(directory)

    monkeypatch.setattr(transactions, "sync_directory", failure_on_cleanup)
    result = reconstruct(tmp_path / "spec.json", tmp_path / "run")
    assert parent_syncs == 3
    assert result["status"] == "review_required"
    assert verify_run(tmp_path / "run")["exports_allowed"]
    assert not (tmp_path / ".run.run-lock").exists()


def test_failed_reservation_release_blocks_exports_and_remains_recoverable(good_run, tmp_path, monkeypatch):
    independent_spec(tmp_path)
    _reuse_valid_geometry(monkeypatch, good_run)
    original = Path.unlink

    def cannot_release(path, *args, **kwargs):
        if path == tmp_path / ".run.run-lock":
            raise PermissionError("Controlled reservation removal failure")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", cannot_release)
    with pytest.raises(RunPublicationError, match="reservation"):
        reconstruct(tmp_path / "spec.json", tmp_path / "run")
    assert not verify_run(tmp_path / "run")["exports_allowed"]
    monkeypatch.setattr(Path, "unlink", original)
    recovered = recover_interrupted_run(tmp_path / "run")
    assert recovered["published"] and recovered["status"] == "interrupted"
    assert verify_run(tmp_path / "run")["valid"] and not verify_run(tmp_path / "run")["exports_allowed"]


def test_parent_sync_failure_after_rename_never_admits_geometry(good_run, tmp_path, monkeypatch):
    from vessel_reconstruction import transaction as transactions
    independent_spec(tmp_path)
    _reuse_valid_geometry(monkeypatch, good_run)
    original = transactions.sync_directory
    parent_syncs = 0

    def fail_committed_parent(directory):
        nonlocal parent_syncs
        if directory == tmp_path:
            parent_syncs += 1
            if parent_syncs == 2:
                raise OSError("Controlled post-rename parent fsync failure")
        return original(directory)

    monkeypatch.setattr(transactions, "sync_directory", fail_committed_parent)
    with pytest.raises(RunPublicationError, match="durability"):
        reconstruct(tmp_path / "spec.json", tmp_path / "run")
    assert not verify_run(tmp_path / "run")["exports_allowed"]
    monkeypatch.setattr(transactions, "sync_directory", original)
    recovered = recover_interrupted_run(tmp_path / "run")
    assert recovered["published"] and verify_run(tmp_path / "run")["valid"]
    assert not verify_run(tmp_path / "run")["exports_allowed"]


def test_native_worker_exit_leaves_discoverable_export_free_interruption(tmp_path):
    script = """import os, sys
from pathlib import Path
from vessel_reconstruction.transaction import RunTransaction
transaction = RunTransaction(Path(sys.argv[1]))
transaction.checkpoint('geometry_export_and_reload')
(transaction.stage / 'model.step').write_text('partial native CAD output')
(transaction.stage / 'mesh.json').write_text('partial native mesh')
os._exit(23)
"""
    process = subprocess.run([sys.executable, "-c", script, str(tmp_path / "run")], env=os.environ.copy(), check=False)
    assert process.returncode == 23 and not (tmp_path / "run").exists()
    recovered = recover_interrupted_run(tmp_path / "run")
    assert recovered["status"] == "interrupted" and recovered["published"]
    assert verify_run(tmp_path / "run")["valid"]
    assert not verify_run(tmp_path / "run")["exports_allowed"]
    assert not list(tmp_path.rglob("model.step"))
    assert not list(tmp_path.rglob("mesh.json"))


@pytest.mark.parametrize("basename", ["run*", "run[ab]", "run?"])
def test_recovery_treats_glob_characters_in_output_name_literally(tmp_path, basename):
    target = tmp_path / basename
    own = RunTransaction(target)
    other_name = "runa" if "[" in basename else "runx"
    other = RunTransaction(tmp_path / other_name)
    other_stage = other.stage
    own.close()
    try:
        recovered = recover_interrupted_run(target)
        assert recovered["published"] and verify_run(target)["valid"]
        assert not own.stage.exists()
        assert other_stage.is_dir()
        assert recover_interrupted_run(tmp_path / other_name)["reason"] == "active_transaction"
    finally:
        other.close()


def _run_nonblocking_probe(tmp_path, spec_name):
    script = """import sys
from pathlib import Path
from vessel_reconstruction.pipeline import reconstruct, verify_run
root = Path(sys.argv[1]); result = reconstruct(root / sys.argv[2], root / 'run', export_cad=False)
assert result['status'] == 'blocked' and result['exports'] == {}
assert verify_run(root / 'run')['valid']
"""
    completed = subprocess.run([sys.executable, "-c", script, str(tmp_path), spec_name],
                               env=os.environ.copy(), capture_output=True, text=True, timeout=5)
    assert completed.returncode == 0, completed.stderr


def test_source_fifo_is_rejected_without_blocking_at_open(tmp_path):
    spec = independent_spec(tmp_path)
    os.mkfifo(tmp_path / "source.pipe")
    spec["source"]["file"] = "source.pipe"
    (tmp_path / "spec.json").write_text(json.dumps(spec))
    _run_nonblocking_probe(tmp_path, "spec.json")


def test_spec_fifo_is_rejected_without_blocking_at_open(tmp_path):
    os.mkfifo(tmp_path / "spec.pipe")
    _run_nonblocking_probe(tmp_path, "spec.pipe")


def test_implementation_replay_uses_bytecode_flag_to_preserve_original_evidence(good_run, tmp_path):
    root = cloned_run(good_run, tmp_path)
    result = json.loads((root / "result.json").read_text())
    assert "PYTHONDONTWRITEBYTECODE=1" in result["provenance"]["implementation_snapshot"]["replay_note"]
    environment = {**os.environ, "PYTHONPATH": str(root / "implementation_source"), "PYTHONDONTWRITEBYTECODE": "1"}
    completed = subprocess.run([sys.executable, "-c", "from vessel_reconstruction.pipeline import verify_run; import sys; assert verify_run(sys.argv[1])['valid']", str(root)],
                               env=environment, capture_output=True, text=True, timeout=15)
    assert completed.returncode == 0, completed.stderr
    assert not list((root / "implementation_source").rglob("__pycache__"))
    assert verify_run(root)["valid"]


@pytest.mark.parametrize("field,value", [
    ("input_mode", []), ("input_mode", {}), ("source", []), ("source", None),
    ("station_reference", []), ("sections", {}), ("symmetry_evidence", {}),
    ("vessel_id", []), ("constraints", []), ("components", {}),
])
def test_wrong_top_level_types_produce_structured_terminal_block(tmp_path, monkeypatch, field, value):
    spec = independent_spec(tmp_path)
    spec[field] = value
    (tmp_path / "spec.json").write_text(json.dumps(spec))
    monkeypatch.setattr(pipeline, "build_hull", lambda *a, **kw: pytest.fail("Invalid metadata reached CAD"))
    monkeypatch.setattr(pipeline, "validate_sources", lambda *a, **kw: pytest.fail("Invalid metadata reached native metadata inspection"))
    result = reconstruct(tmp_path / "spec.json", tmp_path / "run", export_cad=False)
    assert result["status"] == "blocked" and result["gaps"]
    assert result["exports"] == {} and verify_run(tmp_path / "run")["valid"]


@pytest.mark.parametrize("field,value", [
    ("id", []), ("x_m", True), ("roi_px", {}), ("calibration", []), ("evidence", {}),
    ("sample_count", True), ("sample_count", 10000000), ("contour_selection", []),
    ("unexpected_field", "unused"),
])
def test_nested_wrong_types_are_validation_gaps(tmp_path, field, value):
    spec = independent_spec(tmp_path)
    spec["sections"][0][field] = value
    assert validate_spec(spec, tmp_path)


@pytest.mark.parametrize("raw", [
    b'{"source":{},"source":{}}', b'{"nested":{"x":1,"x":2}}', b'{"x":NaN}',
    b'{"x":1e999}', b'{"x":' + b'9' * 500 + b'}', b'[' * 100 + b'0' + b']' * 100,
])
def test_duplicate_nonfinite_huge_integer_and_deep_json_fail_closed(tmp_path, raw):
    (tmp_path / "spec.json").write_bytes(raw)
    result = reconstruct(tmp_path / "spec.json", tmp_path / "run", export_cad=False)
    assert result["status"] == "blocked" and verify_run(tmp_path / "run")["valid"]


def test_bounded_json_enforces_input_bytes_and_aggregate_nodes():
    with pytest.raises(ValueError):
        loads_bounded_json(b" " * 1025, max_bytes=1024)
    with pytest.raises(ValueError):
        loads_bounded_json("[0,0,0,0]", max_nodes=3)


def test_verification_and_invalid_input_do_not_import_cad(tmp_path):
    script = """import json, sys
from pathlib import Path
from vessel_reconstruction.pipeline import reconstruct, verify_run
root = Path(sys.argv[1]); (root / 'invalid.json').write_text('{\"input_mode\":[]}')
result = reconstruct(root / 'invalid.json', root / 'run', export_cad=False)
assert result['status'] == 'blocked' and verify_run(root / 'run')['valid']
assert 'cadquery' not in sys.modules and 'OCP' not in sys.modules
"""
    completed = subprocess.run([sys.executable, "-c", script, str(tmp_path)], env=os.environ.copy(), capture_output=True, text=True, timeout=30)
    assert completed.returncode == 0, completed.stderr
