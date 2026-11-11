import json

import pytest

from vessel_reconstruction.schema import BoundedJSONError, load_build_result


def test_large_build_result_fits_the_budget(tmp_path):
    # 72 sections, each with 21 candidate traces of 129 pixel pairs, plus
    # other section data: more items than the measured Gunnerus result.
    candidate = {"source_points_px": [[1, 2]] * 129}
    section = {"candidate_evidence": [candidate] * 21, "other": [0] * 2500}
    path = tmp_path / "result.json"
    path.write_text(json.dumps({"sections": [section] * 72}))
    assert len(load_build_result(path)["sections"]) == 72


def test_build_result_over_item_ceiling_names_file_and_limit(tmp_path):
    path = tmp_path / "result.json"
    path.write_text(json.dumps([0] * 3_000_000))
    with pytest.raises(BoundedJSONError, match=r"result\.json.*3,000,001.*3,000,000.*build result"):
        load_build_result(path)


def test_depth_error_names_file_and_limit(tmp_path):
    path = tmp_path / "result.json"
    path.write_text('[' * 33 + '0' + ']' * 33)
    with pytest.raises(BoundedJSONError, match=r"result\.json.*depth.*33.*32"):
        load_build_result(path)


def test_section_diagnostics_are_stored_once_in_hashed_extraction(tmp_path):
    from vessel_reconstruction.pipeline import _externalize_section_diagnostics
    from vessel_reconstruction.provenance import digest_file

    path = tmp_path / "extracted_sections.json"
    diagnostics = {"s0": {"candidate_evidence": [{"source_points_px": [[1, 2]]}]}}
    path.write_text(json.dumps({"diagnostics": {"sections": diagnostics}}))
    result = {"diagnostics": {"sections": diagnostics, "fairness": {"status": "warning"}}}
    _externalize_section_diagnostics(tmp_path, result)
    assert result["diagnostics"] == {
        "sections_artifact": {"file": "extracted_sections.json", "sha256": digest_file(path)},
        "fairness": {"status": "warning"},
    }
    assert json.loads(path.read_text())["diagnostics"]["sections"] == diagnostics


def test_byte_limit_error_names_file_and_limit(tmp_path):
    from vessel_reconstruction.schema import load_bounded_json

    path = tmp_path / "input.json"
    path.write_bytes(b"12345")
    with pytest.raises(BoundedJSONError, match=r"input\.json.*5.*4.*byte"):
        load_bounded_json(path, max_bytes=4)
