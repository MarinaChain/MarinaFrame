"""Regression tests for cached failed audits and finalization trust boundaries."""
from copy import deepcopy
import json

import pytest

from vessel_reconstruction.provenance import write_json
from vessel_reconstruction.validation_contract import (ValidationContractError, ready_for_review,
                                                       validate_contract_shape, verify_validation)
from validation_fixture import ControlledValidationDomain


def test_complete_failed_audit_stays_failed_when_cached(tmp_path):
    domain = ControlledValidationDomain(tmp_path / "direct")
    first = domain.execute("validate_candidate", {})
    second = domain.execute("validate_candidate", {})
    third = domain.execute("validate_candidate", {})
    assert first["ok"] is second["ok"] is third["ok"] is False
    assert first["status"] == second["status"] == "validation_failed"
    assert first["validation"] == second["validation"] == third["validation"]
    assert second["reused"] and third["reused"] and domain.audit_calls == 1
    assert first["validation"]["contract"]["checks"] == {
        "worker_execution": "succeeded", "artifact_integrity": "passed",
        "cad_validity": "passed", "trace_fidelity": "failed"}
    # Finishing on the cached failure is guarded in Rust:
    # rust-control/tests/finalization_guards.rs.


def test_fresh_and_cached_pass_have_identical_authoritative_semantics(tmp_path):
    domain = ControlledValidationDomain(tmp_path / "task", maximum=0.0005)
    first = domain.execute("validate_candidate", {})
    second = domain.execute("validate_candidate", {})
    assert first["ok"] is second["ok"] is True
    assert first["status"] == second["status"] == "validated_review_required"
    assert first["validation"] == second["validation"] and second["reused"]
    assert domain.audit_calls == 1
    assert ready_for_review(second, domain.validation_context(), domain.task_dir)


@pytest.mark.parametrize("passed", [False, True])
def test_restart_retains_cached_pass_or_failure_without_a_new_audit(tmp_path, passed):
    domain = ControlledValidationDomain(tmp_path / "task", maximum=0.0005 if passed else 0.01)
    first = domain.execute("validate_candidate", {})
    reopened = ControlledValidationDomain(domain.task_dir, maximum=0.0)
    second = reopened.execute("validate_candidate", {})
    assert first["ok"] is second["ok"] is passed
    assert reopened.audit_calls == 0 and first["validation"] == second["validation"]


@pytest.mark.parametrize("field", ["geometry_checks_passed", "immutable_run_verified"])
@pytest.mark.parametrize("bad", [None, 0, 1, "true", "false", [], {}])
def test_native_check_requires_exact_boolean(tmp_path, field, bad):
    domain = ControlledValidationDomain(tmp_path / "task", maximum=0.0,
        raw_mutator=lambda raw: raw.__setitem__(field, bad))
    observed = domain.execute("validate_candidate", {})
    assert observed["ok"] is False and observed["error_code"] == "invalid_validation_contract"
    assert domain.state["validation"] is None


@pytest.mark.parametrize("artifact", ["validation.json", "observation.json"])
@pytest.mark.parametrize("field,numeric", [
    ("geometry_checks_passed", 1), ("immutable_run_verified", 1),
    ("engineering_approved", 0), ("numeric_reference_truth_used", 0),
    ("human_semantic_review_required", 1),
])
def test_authoritative_artifact_cannot_use_numeric_boolean_equivalents(tmp_path, artifact, field, numeric):
    class ArtifactTypeMutation(ControlledValidationDomain):
        def _worker(self, operation, request, out, **kwargs):
            outcome, result = super()._worker(operation, request, out, **kwargs)
            path = out / artifact
            changed = json.loads(path.read_text())
            raw = changed["validation"] if artifact == "observation.json" else changed
            raw[field] = numeric
            write_json(path, changed)
            return outcome, result

    domain = ArtifactTypeMutation(tmp_path / "task", maximum=0.0005)
    observation = domain.execute("validate_candidate", {})
    assert observation["ok"] is False
    assert observation["error_code"] == "invalid_validation_contract"
    assert domain.audit_calls == 1 and domain.state["validation"] is None


@pytest.mark.parametrize("mutation", [
    lambda v: v.update(geometry_checks_passed=True),
    lambda v: v["geometry_audit"].update(valid_shape="true"),
    lambda v: v["geometry_audit"].update(solid_count=True),
    lambda v: v["geometry_audit"].update(step_units="m"),
    lambda v: v["geometry_audit"].update(step_sha256="b" * 64),
    lambda v: v["geometry_audit"].update(relative_metric_error=0.01),
    lambda v: v["sampled_sections"][0].update(max_px=0),
    lambda v: v["sampled_sections"][0].update(rms_m=2),
    lambda v: v["sampled_sections"][0].update(section_id="not-this-source"),
    lambda v: v["sampled_sections"][0].update(sample_count=1),
    lambda v: v["sampled_sections"].reverse(),
    lambda v: v.update(sampled_section_count=0),
    lambda v: v.update(sampled_sections=[]),
    lambda v: v.update(unknown_field=True),
    lambda v: v.update(engineering_approved=True),
    lambda v: v.update(numeric_reference_truth_used=True),
])
def test_native_contradictory_or_incomplete_audit_is_rejected(tmp_path, mutation):
    domain = ControlledValidationDomain(tmp_path / "task", raw_mutator=mutation)
    observed = domain.execute("validate_candidate", {})
    assert observed["ok"] is False and observed["error_code"] == "invalid_validation_contract"
    assert domain.state["validation"] is None


@pytest.mark.parametrize("field", ["schema_version", "audit_contract_version", "binding", "checks", "sampling",
                                    "measurements", "evidence", "semantic_review", "engineering_approved"])
def test_missing_contract_fields_are_not_inherited_from_cache(tmp_path, field):
    domain = ControlledValidationDomain(tmp_path / "task", maximum=0.0005)
    assert domain.execute("validate_candidate", {})["ok"]
    del domain.state["validation"]["contract"][field]
    domain._save()
    cached = domain.execute("validate_candidate", {})
    assert cached["ok"] is False and cached["error_code"] == "validation_cache_invalid"
    assert domain.audit_calls == 1


@pytest.mark.parametrize("mutation", [
    lambda c: c.update(schema_version="marinaframe.validation.v99"),
    lambda c: c.update(audit_contract_version="unknown"),
    lambda c: c.update(unknown_field=True),
    lambda c: c["checks"].update(trace_fidelity=True),
    lambda c: c["checks"].update(trace_fidelity="failed"),
    lambda c: c["tolerances"].update(max_section_distance_m=1.0),
    lambda c: c["tolerances"].update(max_relative_metric_error=True),
    lambda c: c["measurements"].update(max_section_distance_m=None),
    lambda c: c["measurements"].update(max_section_distance_m=float("nan")),
    lambda c: c["measurements"].update(relative_metric_error=float("inf")),
    lambda c: c["sampling"].update(section_ids=["s0", "s0", "s0"]),
    lambda c: c["sampling"].update(total_section_count=True),
    lambda c: c["units"].update(step="m"),
    lambda c: c.update(engineering_approved=0),
])
def test_strict_contract_rejects_invalid_serialization_or_semantics(tmp_path, mutation):
    domain = ControlledValidationDomain(tmp_path / "task", maximum=0.0005)
    contract = deepcopy(domain.execute("validate_candidate", {})["validation"]["contract"])
    mutation(contract)
    with pytest.raises(ValidationContractError):
        validate_contract_shape(contract)


@pytest.mark.parametrize("kind", ["exported_step", "run_manifest", "run_result", "captured_input_spec",
                                  "revision_spec", "revision_selection", "captured_source",
                                  "step_reimport_validation", "validation_worker_receipt", "step_section_cut_comparison"])
@pytest.mark.parametrize("mode", ["missing", "changed"])
def test_cached_conclusions_cannot_outlive_bound_artifacts(tmp_path, kind, mode):
    domain = ControlledValidationDomain(tmp_path / "task", maximum=0.0005)
    observed = domain.execute("validate_candidate", {})
    reference = next(a for a in observed["validation"]["contract"]["evidence"] if a["kind"] == kind)
    path = domain.task_dir / reference["path"]
    if mode == "missing":
        path.unlink()
    else:
        path.write_bytes(path.read_bytes() + b"\nchanged-after-validation")
    repeated = domain.execute("validate_candidate", {})
    assert repeated["ok"] is False
    assert domain.audit_calls == 1


@pytest.mark.parametrize("which", ["generation", "revision", "selection", "calibration"])
def test_prior_current_candidate_cannot_satisfy_a_different_binding(tmp_path, which):
    domain = ControlledValidationDomain(tmp_path / "task", maximum=0.0005)
    observed = domain.execute("validate_candidate", {})
    context = domain.validation_context()
    context = deepcopy(context)
    key = {"generation": "generation_id", "revision": "revision_id", "selection": "selection_sha256",
           "calibration": "input_spec_sha256"}[which]
    context["binding"][key] = "different-current-identity"
    assert not ready_for_review(observed, context, domain.task_dir)
    with pytest.raises(ValidationContractError):
        verify_validation(observed["validation"], context, domain.task_dir)


@pytest.mark.parametrize("state", ["cancelled", "timeout", "interrupted", "failed"])
def test_interrupted_or_failed_audit_cannot_be_a_cached_pass(tmp_path, state):
    domain = ControlledValidationDomain(tmp_path / "task", outcome={"state": state, "elapsed_seconds": 0.0})
    observed = domain.execute("validate_candidate", {})
    assert observed["ok"] is False and observed["error_code"] == "validation_worker_failed"
    assert domain.state["validation"] is None


def test_cached_metadata_cannot_contradict_authoritative_json_even_if_envelope_passes(tmp_path):
    domain = ControlledValidationDomain(tmp_path / "task")
    observed = domain.execute("validate_candidate", {})
    validation = deepcopy(observed["validation"])
    validation["geometry_checks_passed"] = True
    validation["contract"]["outcome"] = "passed"
    validation["contract"]["checks"]["trace_fidelity"] = "passed"
    validation["contract"]["measurements"]["max_section_distance_m"] = 0.0
    for section in validation["sampled_sections"]:
        section.update(max_m=0.0, rms_m=0.0, p95_m=0.0, max_px=0.0)
    with pytest.raises(ValidationContractError, match="authoritative"):
        verify_validation(validation, domain.validation_context(), domain.task_dir)


@pytest.mark.parametrize("which", ["revision", "selection", "calibration"])
def test_persistent_domain_changes_invalidate_old_audit(tmp_path, which):
    from vessel_reconstruction.provenance import digest_file
    domain = ControlledValidationDomain(tmp_path / "task", maximum=0.0005)
    assert domain.execute("validate_candidate", {})["ok"]
    if which == "revision":
        domain.state["revision"] += 1
    elif which == "selection":
        domain.state["selected"]["s0"] = "a-different-source-choice"
    else:
        path = domain.root / "input/spec.json"
        spec = json.loads(path.read_text())
        spec["sections"][0]["calibration"]["pixels_per_metre"] = 61
        write_json(path, spec)
        domain.state["input_spec_sha256"] = digest_file(path)
    domain._save()
    assert domain.execute("validate_candidate", {})["ok"] is False
    assert domain.audit_calls == 1


def test_reselecting_an_old_generation_requires_a_new_revision_build(tmp_path, monkeypatch):
    from test_agent_tools import drawing
    from vessel_reconstruction.agent_tools import DomainTools
    from vessel_reconstruction import agent_tools, run_record
    spec, _ = drawing(tmp_path / "source")
    domain = DomainTools(tmp_path / "task", spec)
    for section in domain.spec["sections"]:
        centre = section["calibration"]["centerline_px"]
        domain.state["catalog"][section["id"]] = {"section_id": section["id"], "grid_evidence": {},
            "candidates": [{"candidate_id": name, "selectable": True, "hypothesis": "controlled source choice",
                "contour_selection": {"anchors_px": [[centre + offset, 30], [centre + offset, 210]], "half_width_px": 3}}
                for name, offset in (("choice-a", 40), ("choice-b", 60))]}
    domain._save()
    builds = []
    def controlled_build(spec_path, out, **kwargs):
        out.mkdir(parents=True)
        result = {"status": "review_required", "exports": {"step": "model.step"},
                  "run_id": "2" * 20, "gaps": [], "metrics": {}}
        write_json(out / "result.json", result)
        (out / "model.step").write_bytes(b"CONTROLLED native-build test double\n")
        builds.append(out)
        return {"state": "committed", "result": result}
    monkeypatch.setattr(agent_tools, "run_isolated", controlled_build)
    monkeypatch.setattr(run_record, "verify_run", lambda path: {"valid": True})
    candidates = []
    for choice in ("choice-a", "choice-b", "choice-a"):
        domain.execute("select_contours", {"selections": [
            {"section_id": s["id"], "candidate_id": choice} for s in domain.spec["sections"]]})
        assert domain.describe()["current_candidate"] is None
        if len(candidates) == 2:
            # The earlier A candidate shares geometry identity, but is an older revision.
            assert candidates[0]["generation_id"] == domain.generation_id
            with pytest.raises(ValueError):
                domain._verified_candidate()
        built = domain.execute("build_provisional", {})
        assert built["ok"] and not built.get("reused", False)
        candidates.append(built["candidate"])
    assert len(builds) == 3 and len(set(builds)) == 3
    assert candidates[0]["generation_id"] == candidates[2]["generation_id"]
    assert candidates[0]["revision_id"] != candidates[2]["revision_id"]
    assert domain.execute("build_provisional", {})["reused"] is True


def test_render_marks_same_generation_older_revision_stale(tmp_path, monkeypatch):
    domain = ControlledValidationDomain(tmp_path / "task", maximum=0.0)
    old = deepcopy(domain.state["builds"][-1])
    domain.state["revision"] += 1
    domain._save()
    def render(operation, request, out, **kwargs):
        assert operation == "render"
        out.mkdir(parents=True)
        (out / "render.png").write_bytes(b"controlled full image")
        (out / "model.png").write_bytes(b"controlled model image")
        return {"elapsed_seconds": 0.0}, {"geometry_audit": {},
            "model_observation": {"file": "model.png", "model_eligible": True}}
    monkeypatch.setattr(domain, "_verified_candidate", lambda **kwargs: (old, domain.task_dir / old["path"]))
    monkeypatch.setattr(domain, "_worker", render)
    rendered = domain.execute("render_candidate", {"view": "body"})
    assert rendered["ok"] and rendered["stale_candidate"] is True
    assert rendered["rendered_generation_id"] == domain.generation_id
    assert domain.state["rendered_views"] == []


@pytest.mark.parametrize("invalid", [False, True, 0.0, -1, 100_000_000, "0", None])
def test_malformed_checkpoint_revision_rejected_on_reload_and_reopen(tmp_path, invalid):
    domain = ControlledValidationDomain(tmp_path / "task", maximum=0.0005)
    assert domain.execute("validate_candidate", {})["ok"] is True
    domain.state["revision"] = invalid
    domain._save()
    result = domain.execute("validate_candidate", {})
    assert result["ok"] is False and result["status"] == "blocked"
    assert result["revision_id"] is None and result["generation_id"] is None
    assert domain.audit_calls == 1
    with pytest.raises(ValueError, match="revision"):
        ControlledValidationDomain(domain.task_dir, maximum=0.0005)
