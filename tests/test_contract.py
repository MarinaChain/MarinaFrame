import json
from pathlib import Path
from PIL import Image
import pytest

from vessel_reconstruction.schema import validate_spec
from vessel_reconstruction.pipeline import reconstruct, verify_run


def valid_spec(tmp_path):
    Image.new("RGB", (400, 350), "white").save(tmp_path / "drawing.png")
    return {
        "schema_version": "1.0", "vessel_id": "contract-test", "units": "m",
        "source": {"file": "drawing.png"}, "symmetry": "port_starboard",
        "symmetry_evidence": "Test assumption explicitly declared", "end_closure": "flat_at_terminal_stations",
        "sections": [{"id": f"s{i}", "x_m": x, "roi_px": [10, 10, 350, 340], "calibration": {"centerline_px": 30, "baseline_px": 310, "pixels_per_metre": 50}, "z_min_m": 0, "z_max_m": 5, "evidence": "Test view calibration"} for i, x in enumerate([0, 5, 10])],
    }


def test_unscaled_drawing_never_creates_geometry(tmp_path):
    spec = valid_spec(tmp_path)
    del spec["sections"][1]["calibration"]["pixels_per_metre"]
    p = tmp_path / "spec.json"
    p.write_text(json.dumps(spec))
    out = tmp_path / "run"
    r = reconstruct(p, out)
    assert r["status"] == "blocked"
    assert any(g["kind"] == "missing_scale" for g in r["gaps"])
    assert not (out / "model.step").exists()
    assert not (out / "mesh.json").exists()
    assert r["review"]["engineering_approved"] is False


def test_ground_truth_cannot_enter_drawing_spec(tmp_path):
    spec = valid_spec(tmp_path)
    spec["sections"][0]["points_yz_m"] = [[1, 0], [2, 1]]
    assert any(g["kind"] == "geometry_in_input" for g in validate_spec(spec, tmp_path))


def test_multi_region_geometry_cannot_enter_drawing_spec(tmp_path):
    spec = valid_spec(tmp_path)
    spec["sections"][0]["regions"] = [{"kind": "offset", "rows_m": [[0, 1, 2], [1, 1, 2]]}]
    assert any(g["kind"] == "geometry_in_input" for g in validate_spec(spec, tmp_path))


def test_source_hash_mismatch_blocks(tmp_path):
    spec = valid_spec(tmp_path)
    spec["source"]["sha256"] = "0" * 64
    p = tmp_path / "spec.json"
    p.write_text(json.dumps(spec))
    r = reconstruct(p, tmp_path / "run")
    assert r["status"] == "blocked"
    assert any(g["kind"] == "source_hash_mismatch" for g in r["gaps"])


def test_evidence_tampering_detected(tmp_path):
    spec = valid_spec(tmp_path)
    spec["units"] = "unknown"  # a blocked run still snapshots source evidence
    p = tmp_path / "spec.json"
    p.write_text(json.dumps(spec))
    out = tmp_path / "run"
    reconstruct(p, out)
    assert verify_run(out)["valid"]
    with (out / "source.png").open("ab") as f:
        f.write(b"modified")
    assert not verify_run(out)["valid"]


def test_exact_inference_source_is_retained_and_verified(tmp_path):
    spec = valid_spec(tmp_path)
    spec["units"] = "unknown"
    path = tmp_path / "spec.json"
    path.write_text(json.dumps(spec))
    out = tmp_path / "run"
    result = reconstruct(path, out)
    manifest = result["provenance"]["implementation_snapshot"]
    assert "implementation_source/vessel_reconstruction/geometry.py" in manifest["files_sha256"]
    assert verify_run(out)["valid"]
    with (out / "implementation_source/vessel_reconstruction/geometry.py").open("a") as f:
        f.write("\n# deliberate audit tampering\n")
    assert not verify_run(out)["valid"]


def test_completed_run_not_overwritten(tmp_path):
    spec = valid_spec(tmp_path)
    spec["units"] = "unknown"
    p = tmp_path / "spec.json"
    p.write_text(json.dumps(spec))
    out = tmp_path / "run"
    reconstruct(p, out)
    with pytest.raises(FileExistsError):
        reconstruct(p, out)


@pytest.mark.parametrize("change", ["huge_elevation", "tiny_pixel_scale", "far_centerline"])
def test_extreme_physical_coordinates_stop_before_kernel(tmp_path, change, monkeypatch):
    spec = valid_spec(tmp_path)
    section = spec["sections"][0]
    if change == "huge_elevation":
        section["z_max_m"] = 1e300
        section["calibration"]["pixels_per_metre"] = 1e-298
    elif change == "tiny_pixel_scale":
        section["calibration"]["pixels_per_metre"] = 1e-300
    else:
        section["calibration"]["centerline_px"] = -1e300
    def unexpected_geometry(*args, **kwargs):
        raise AssertionError("Out-of-range coordinates must not reach CAD")
    monkeypatch.setattr("vessel_reconstruction.pipeline.build_hull", unexpected_geometry)
    path = tmp_path / "spec.json"
    path.write_text(json.dumps(spec))
    result = reconstruct(path, tmp_path / "run", export_cad=False)
    assert result["status"] == "blocked"
    assert any(g["kind"] in {"physical_extent_out_of_range", "vertical_range_out_of_range"} for g in result["gaps"])
    assert not (tmp_path / "run" / "mesh.json").exists()
