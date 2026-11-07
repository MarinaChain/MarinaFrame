"""The renderer must work with the controller's output-directory contract."""
import json

from PIL import Image
import pytest


def test_renderer_accepts_controller_created_empty_directory(tmp_path, monkeypatch):
    from vessel_reconstruction import llm_review, agent_render_worker
    source = tmp_path / "source.png"
    Image.new("RGB", (100, 100), "white").save(source)
    from vessel_reconstruction.provenance import digest_file
    record = {"metrics": {}, "sources": [{"file": "source.png", "sha256": digest_file(source)}],
              "sections": [{"id": "s1", "x_m": 1, "points_yz_m": [[0, 0], [1, 1]],
                            "evidence": {"roi_px": [0, 0, 100, 100],
                                         "calibration": {"centerline_px": 20, "baseline_px": 90, "pixels_per_metre": 50}}}]}
    monkeypatch.setattr(agent_render_worker, "_reimport", lambda run: (None, record, {"step_sha256": "a" * 64}))
    monkeypatch.setattr(agent_render_worker, "_cut_edges", lambda *args: [])
    out = tmp_path / "images"
    out.mkdir()
    manifest = llm_review.render(tmp_path, out)
    assert len(manifest["images"]) == 1
    assert manifest["engineering_approved"] is False
    assert (out / manifest["images"][0]["file"]).is_file()


def test_renderer_does_not_overwrite_existing_evidence(tmp_path, monkeypatch):
    from vessel_reconstruction import llm_review, agent_render_worker
    monkeypatch.setattr(agent_render_worker, "_reimport", lambda run: pytest.fail("must reject output before CAD"))
    out = tmp_path / "images"
    out.mkdir()
    (out / "existing.png").write_bytes(b"user evidence")
    with pytest.raises(ValueError, match="empty"):
        llm_review.render(tmp_path, out)
    assert (out / "existing.png").read_bytes() == b"user evidence"
