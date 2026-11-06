import json
import pytest
from PIL import Image
from vessel_reconstruction.pipeline import reconstruct
from vessel_reconstruction.review import record_review


def blocked_run(tmp_path):
    Image.new("RGB", (40, 40), "white").save(tmp_path / "input.png")
    p = tmp_path / "spec.json"
    p.write_text(json.dumps({"schema_version": "1.0", "source": {"file": "input.png"}, "units": "m", "symmetry": "port_starboard", "symmetry_evidence": "Assumption", "end_closure": "flat_at_terminal_stations", "sections": []}))
    out = tmp_path / "run"
    result = reconstruct(p, out)
    return out, result


def test_blocked_geometry_cannot_be_review_accepted(tmp_path):
    out, r = blocked_run(tmp_path)
    with pytest.raises(ValueError, match="blocked or incomplete"):
        record_review(out, decision="accept_geometry", reviewer="Test reviewer", notes="Not sufficient", expected_run_id=r["run_id"])


def test_named_review_is_never_engineering_certification(tmp_path):
    out, r = blocked_run(tmp_path)
    event = record_review(out, decision="needs_information", reviewer="Test reviewer", notes="Need three calibrated sections.", expected_run_id=r["run_id"])
    assert event["engineering_approved"] is False
    assert event["identity_verified"] is False
    assert json.loads((out / "result.json").read_text())["review"]["engineering_approved"] is False
    with pytest.raises(ValueError, match="identifier"):
        record_review(out, decision="reject", reviewer="Test reviewer", notes="Wrong run", expected_run_id="different")


def test_review_history_tamper_stops_append(tmp_path):
    out, r = blocked_run(tmp_path)
    record_review(out, decision="needs_information", reviewer="Test reviewer", notes="Need sources", expected_run_id=r["run_id"])
    history = json.loads((out / "review_history.json").read_text())
    history[0]["notes"] = "silently changed"
    (out / "review_history.json").write_text(json.dumps(history))
    with pytest.raises(ValueError, match="hash chain"):
        record_review(out, decision="reject", reviewer="Test reviewer", notes="Bad evidence", expected_run_id=r["run_id"])
