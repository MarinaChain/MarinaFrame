"""Opt-in assistance must stay explicit, source-bound, and separate from inference."""
import hashlib
import json

from PIL import Image, ImageDraw
import pytest

from benchmarks.propose_pixel_corridors import propose
from vessel_reconstruction.ingest import extract_sections


def source_fixture(tmp_path, *, equally_dark=False):
    image = Image.new("RGB", (420, 420), "white")
    draw = ImageDraw.Draw(image)
    draw.line((180, 60, 180, 360), fill=(15, 15, 15), width=3)
    intensity = 15 if equally_dark else 210
    draw.line((270, 60, 270, 360), fill=(intensity,) * 3, width=3)
    image.save(tmp_path / "source.png")
    specification = {"units": "m", "source": {"file": "source.png"}, "sections": [{
        "id": "source-only", "x_m": 0, "roi_px": [65, 40, 350, 375],
        "calibration": {"centerline_px": 90, "baseline_px": 360, "pixels_per_metre": 60},
        "z_min_m": 0, "z_max_m": 5,
    }]}
    path = tmp_path / "spec.json"
    path.write_text(json.dumps(specification))
    return path, specification


def test_optional_corridor_proposal_preserves_source_and_does_not_claim_human_validation(tmp_path):
    path, spec = source_fixture(tmp_path)
    before = path.read_bytes()
    original = (tmp_path / "source.png").read_bytes()
    assert extract_sections(spec, tmp_path)["gaps"][0]["kind"] == "ambiguous_curve"
    report = propose(path, tmp_path / "proposal")
    assert path.read_bytes() == before
    assert (tmp_path / "proposal/source.png").read_bytes() == original
    assert report["source_sha256"] == hashlib.sha256(original).hexdigest()
    assert report["parent_calibration_spec_sha256"] == hashlib.sha256(before).hexdigest()
    assert report["proposal_status"] == "unvalidated_review_required"
    assert report["human_expert_adjudication"] is False
    assert report["manual_click_count"] == 0
    assert report["total_anchor_count"] == 2
    assisted = json.loads((tmp_path / "proposal/spec.json").read_text())
    assert "AI/pixel-assisted" in assisted["sections"][0]["evidence"]
    result = extract_sections(assisted, tmp_path / "proposal")
    assert not result["gaps"]
    assert result["sections"][0]["evidence"]["identity_status"] == "explicit_supplied_pixel_selection"
    assert result["diagnostics"]["sections"]["source-only"]["candidate_evidence"]
    # Producing a proposal does not convert the original unselected input into
    # an automatic success or edit the source to remove the competing stroke.
    assert extract_sections(spec, tmp_path)["gaps"][0]["kind"] == "ambiguous_curve"


def test_distinct_dark_strokes_require_manual_choice_instead_of_a_proposal(tmp_path):
    path, _ = source_fixture(tmp_path, equally_dark=True)
    with pytest.raises(ValueError, match="multiple dark strokes"):
        propose(path, tmp_path / "proposal")
    assert not (tmp_path / "proposal").exists()


def test_assistance_does_not_overwrite_an_earlier_proposal(tmp_path):
    path, _ = source_fixture(tmp_path)
    target = tmp_path / "proposal"
    propose(path, target)
    digest = hashlib.sha256((target / "spec.json").read_bytes()).hexdigest()
    with pytest.raises(FileExistsError):
        propose(path, target)
    assert hashlib.sha256((target / "spec.json").read_bytes()).hexdigest() == digest
