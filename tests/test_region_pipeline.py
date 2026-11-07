"""Multi-piece stations through the product path: spec -> pieces -> regions -> CAD -> audit.

Fixture: tests/region_fixture.py (three stations, each a bulb, a hull above it
and a skeg; exact areas 0.65 + 0.05 i, 1.725 + 0.075 i and 0.3 m2 per half).
"""
from __future__ import annotations

import copy
import json

import pytest

from region_fixture import write as write_region_fixture
from vessel_reconstruction.ingest import extract_sections
from vessel_reconstruction.provenance import digest_object
from vessel_reconstruction.run_record import observed_geometry
from vessel_reconstruction.schema import validate_spec
from vessel_reconstruction.section_regions import region_area

# Exact volume of the fixture: bulb 5.6, hull 14.4 and two skegs 1.2 m3 each.
FIXTURE_VOLUME_M3 = 22.4


def _kinds(gaps):
    return {gap["kind"] for gap in gaps}


def test_schema_accepts_declared_pieces_and_refuses_geometry_or_mixed_selection(tmp_path):
    path, spec = write_region_fixture(tmp_path)
    assert validate_spec(spec, path.parent) == []
    mixed = copy.deepcopy(spec)
    mixed["sections"][0]["contour_selection"] = mixed["sections"][0]["pieces"][0]["contour_selection"]
    assert "invalid_pieces" in _kinds(validate_spec(mixed, path.parent))
    answered = copy.deepcopy(spec)
    answered["sections"][0]["pieces"][0]["points_yz_m"] = [[0.5, 0.0], [0.8, 1.0]]
    assert "geometry_in_input" in _kinds(validate_spec(answered, path.parent))
    outside = copy.deepcopy(spec)
    outside["sections"][0]["pieces"][1]["z_max_m"] = 3.5
    assert "invalid_pieces" in _kinds(validate_spec(outside, path.parent))
    too_many = copy.deepcopy(spec)
    too_many["sections"][0]["pieces"] = too_many["sections"][0]["pieces"] * 3
    assert "invalid_pieces" in _kinds(validate_spec(too_many, path.parent))


def test_pieces_are_read_into_exact_regions(tmp_path):
    path, spec = write_region_fixture(tmp_path)
    extracted = extract_sections(spec, path.parent)
    assert extracted["gaps"] == []
    for index, section in enumerate(extracted["sections"]):
        assert "points_yz_m" not in section
        assert [r["kind"] for r in section["regions"]] == ["centreline", "offset", "centreline"]
        areas = [region_area(r["rows_m"]) for r in section["regions"]]
        assert areas == pytest.approx([0.65 + 0.05 * index, 0.3, 1.725 + 0.075 * index], abs=1e-9)
        assert len(section["pieces"]) == 3 and "inner_points_yz_m" in section["pieces"][2]
        assert section["evidence"]["identity_status"] == "explicit_supplied_piece_selections"


def test_overlapping_pieces_and_crossed_inner_curves_are_refused(tmp_path):
    path, spec = write_region_fixture(tmp_path)
    overlap = copy.deepcopy(spec)
    # The skeg read as a centreline piece covers the bulb: the pieces overlap.
    del overlap["sections"][0]["pieces"][2]["inner_selection"]
    crossed = copy.deepcopy(spec)
    skeg = crossed["sections"][0]["pieces"][2]
    skeg["contour_selection"], skeg["inner_selection"] = skeg["inner_selection"], skeg["contour_selection"]
    for broken in (overlap, crossed):
        gaps = extract_sections(broken, path.parent)["gaps"]
        assert [(g["section_id"], g["kind"]) for g in gaps] == [("st0", "invalid_outline")]


def test_single_curve_observation_identity_is_unchanged():
    section = {"id": "s0", "x_m": 1.0, "points_yz_m": [[1.0, 0.0], [1.2, 1.0]], "coverage": 1.0}
    # The identity every single-curve run was sealed with.
    legacy = digest_object([{key: section[key] for key in ("id", "x_m", "points_yz_m")}])
    assert digest_object([observed_geometry(section)]) == legacy


@pytest.mark.cad
def test_region_run_builds_a_verified_compound(tmp_path):
    from vessel_reconstruction.pipeline import reconstruct
    from vessel_reconstruction.run_record import seal_run, verify_run
    path, _ = write_region_fixture(tmp_path / "input")
    result = reconstruct(path, tmp_path / "run")
    assert result["status"] == "review_required", result["gaps"]
    metrics = result["metrics"]
    assert metrics["solid_count"] == 4 and metrics["region_loft"]["solid_count"] == 4
    assert metrics["volume_m3"] == pytest.approx(FIXTURE_VOLUME_M3, rel=1e-6)
    assert sorted(metrics["region_loft"]["solid_volumes_m3"]) == pytest.approx([1.2, 1.2, 5.6, 14.4], rel=1e-6)
    assert metrics["region_loft"]["unlofted_regions"] == []
    assert "geometry_approximation" not in metrics
    assert any(a["id"] == "region_matching" for a in result["assumptions"])
    assert verify_run(tmp_path / "run")["valid"]
    # The record is checked against its traced pieces: a changed region fails.
    record = json.loads((tmp_path / "run" / "result.json").read_text())
    record["sections"][0]["regions"][0]["rows_m"][0][2] += 0.01
    (tmp_path / "run" / "result.json").write_text(json.dumps(record))
    assert not verify_run(tmp_path / "run")["valid"]


@pytest.mark.cad
def test_region_candidate_passes_the_independent_v2_audit(tmp_path):
    from vessel_reconstruction.agent_tools import DomainTools
    from vessel_reconstruction.validation_contract import REGION_AUDIT_CONTRACT_VERSION
    path, _ = write_region_fixture(tmp_path / "input")
    tools = DomainTools(tmp_path / "task", path)
    observed = tools.execute("inspect_source", {})
    assert observed["ok"], observed
    choices = []
    for section in observed["sections"]:
        (candidate,) = section["candidates"]
        assert candidate["hypothesis"] == "declared_piece_corridors"
        assert section["grid_evidence"]["unique_non_grid_candidate_id"] == candidate["candidate_id"]
        choices.append({"section_id": section["section_id"], "candidate_id": candidate["candidate_id"]})
    assert tools.execute("select_contours", {"selections": choices})["ok"]
    revision = json.loads((tools.root / "revisions" / tools.revision_id / "spec.json").read_text())
    assert all("pieces" in s and "contour_selection" not in s for s in revision["sections"])
    built = tools.execute("build_provisional", {})
    assert built["ok"] and built["status"] == "review_required", built
    rendered = tools.execute("render_candidate", {"view": "body"})
    assert rendered["ok"] and rendered["geometry_audit"]["solid_count"] == 4
    validated = tools.execute("validate_candidate", {})
    assert validated["ok"], validated
    audit = validated["validation"]
    assert validated["validation"]["contract"]["audit_contract_version"] == REGION_AUDIT_CONTRACT_VERSION
    assert validated["validation"]["contract"]["outcome"] == "passed"
    geometry = audit["geometry_audit"]
    assert geometry["expected_solid_count"] == geometry["solid_count"] == 4
    assert all(s["valid_shape"] and s["closed_shell"] and s["shell_count"] == 1 for s in geometry["solids"])
    assert geometry["solid_volume_relative_error"] <= 1e-6
    for section in audit["sampled_sections"]:
        assert [p["sample_count"] for p in section["pieces"]] == [129, 129, 258]
        assert max(p["max_m"] for p in section["pieces"]) == pytest.approx(section["max_m"])
        assert section["max_m"] < .0011


@pytest.mark.cad
def test_draft_mode_spans_an_unreadable_multi_piece_station(tmp_path):
    from vessel_reconstruction.agent_tools import DomainTools
    from vessel_reconstruction.run_record import verify_run
    path, _ = write_region_fixture(tmp_path / "input", stations=4, blank=("st1",))
    tools = DomainTools(tmp_path / "task", path)
    observed = tools.execute("inspect_source", {})
    readable = [{"section_id": s["section_id"], "candidate_id": s["grid_evidence"]["unique_non_grid_candidate_id"]}
                for s in observed["sections"] if s["grid_evidence"]["unique_non_grid_candidate_id"]]
    assert [s["section_id"] for s in readable] == ["st0", "st2", "st3"]
    tools.execute("select_contours", {"selections": readable})
    built = tools.execute("build_draft", {})
    assert built["ok"], built
    assert [(g["section_id"], g["kind"]) for g in built["draft"]["guesses"]] == [("st1", "bridged_gap")]
    run = tmp_path / "task" / built["candidate"]["path"]
    assert verify_run(run)["valid"]
    record = json.loads((run / "result.json").read_text())
    assert [s["id"] for s in record["sections"]] == ["st0", "st2", "st3"]
    assert record["metrics"]["solid_count"] == 4 and record["exports"]["step"] == "model-draft.step"
    refused = tools.execute("validate_candidate", {})
    assert not refused["ok"] and "draft" in refused["message"]
