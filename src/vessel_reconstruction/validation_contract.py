"""Strict candidate-validation contract shared by control planes.

A completed validator is not necessarily a successful audit. A cached report
has exactly the same meaning as a fresh report, and finalization must check the
complete report, current binding and artifact bytes. These hashes detect local
inconsistency; they do not authenticate an engineer or a hostile host.
"""
from __future__ import annotations

from dataclasses import dataclass
from importlib import metadata
import math
from pathlib import Path
import re

from .provenance import canonical_json, digest_file, digest_object, safe_relative_file
from .resources import KNOWN_RESOURCE_PROFILES
from .schema import load_bounded_json


SCHEMA_VERSION = "marinaframe.validation.v1"
AUDIT_CONTRACT_VERSION = "step_source_sections_v1"
SAMPLING_POLICY = "first_two_middle_last_two_v1"
SECTION_SAMPLING_TEXT = "first two, middle, last two; bounded sample, not exhaustive"
TOLERANCES = {"max_section_distance_m": 0.0011, "max_relative_metric_error": 1e-6}
UNITS = {"input": "m", "step": "mm", "reported": "m"}
BINDING_KEYS = {"generation_id", "revision_id", "run_id", "source_manifest_sha256",
                "input_spec_sha256", "selection_sha256", "revision_spec_sha256",
                "run_manifest_sha256", "run_result_sha256", "step_sha256",
                "audit_implementation_sha256"}
CONTRACT_KEYS = {"schema_version", "binding", "checks", "outcome", "units", "tolerances",
                 "sampling", "measurements", "evidence", "audit_contract_version",
                 "semantic_review", "engineering_approved"}
RAW_KEYS = {"geometry_checks_passed", "immutable_run_verified", "geometry_audit", "sampled_sections",
            "sampled_section_count", "total_section_count", "section_sampling",
            "numeric_reference_truth_used", "unresolved_semantics", "human_semantic_review_required",
            "engineering_approved"}
GEOMETRY_KEYS = {"source", "step_sha256", "step_units", "reported_units", "valid_shape",
                 "solid_count", "shell_count", "closed_shell", "metrics", "relative_metric_error",
                 "engineering_approved", "human_semantic_review_required"}
SECTION_KEYS = {"section_id", "x_m", "sample_count", "distance_type", "rms_m", "p95_m",
                "max_m", "max_px", "source_measurement_uncertainty_m", "section_edges"}
VALIDATION_KEYS = RAW_KEYS | {"generation_id", "revision_id", "identity_certified", "artifacts", "contract"}
SEMANTICS = ["contour identity", "caller calibration", "station correspondence", "symmetry",
             "terminal and upper closure", "current vessel condition"]
SHA256 = re.compile(r"[0-9a-f]{64}\Z")
DISTANCE_TYPE = "observed source-centre samples to actual STEP section boundary; no reference truth used"


class ValidationContractError(ValueError):
    """A report cannot support current-candidate validation or finalization."""


@dataclass(frozen=True)
class Assessment:
    passed: bool
    cad_validity_passed: bool
    trace_fidelity_passed: bool
    max_section_distance_m: float
    relative_metric_error: float


def require(condition, message):
    if not condition:
        raise ValidationContractError(message)


def record(value, keys, label):
    require(type(value) is dict and set(value) == keys, label + " has missing or unknown fields")
    return value


def number(value, label, *, minimum=0.0):
    require(type(value) in (int, float) and math.isfinite(value) and value >= minimum,
            label + " must be a finite number in the declared domain")
    return float(value)


def integer(value, label, minimum, maximum):
    require(type(value) is int and minimum <= value <= maximum, label + " must be a bounded integer")
    return value


def boolean(value, label):
    require(type(value) is bool, label + " must be an exact boolean")
    return value


def sha256(value, label):
    require(type(value) is str and SHA256.fullmatch(value) is not None, label + " must be a SHA-256")
    return value


def close(a, b):
    return math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-12)


def artifact_reference(task_dir, path, kind):
    relative = Path(path).relative_to(task_dir).as_posix()
    file = safe_relative_file(Path(task_dir), relative)
    return {"kind": kind, "path": relative, "sha256": digest_file(file), "bytes": file.stat().st_size}


def validate_reference(reference, task_dir=None):
    record(reference, {"kind", "path", "sha256", "bytes"}, "Artifact reference")
    require(type(reference["kind"]) is str and 0 < len(reference["kind"]) <= 80, "Invalid artifact kind")
    path = reference["path"]
    require(type(path) is str and 0 < len(path) <= 4096 and not path.startswith("/")
            and "\\" not in path and "\x00" not in path
            and all(p not in ("", ".", "..") for p in path.split("/")), "Unsafe artifact path")
    sha256(reference["sha256"], "Artifact digest")
    integer(reference["bytes"], "Artifact byte size", 1, 512 * 1024**2)
    if task_dir is not None:
        file = safe_relative_file(Path(task_dir), path)
        require(file.stat().st_size == reference["bytes"] and digest_file(file) == reference["sha256"],
                "Validation artifact is missing or changed")


def implementation_identity():
    names = ("agent_render_worker.py", "validation_contract.py", "run_record.py", "geometry.py",
             "schema.py", "provenance.py", "resources.py", "fonts.py")
    versions = {}
    for name in ("cadquery", "cadquery-ocp", "numpy"):
        try:
            versions[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            versions[name] = "unavailable"
    return digest_object({"audit_contract_version": AUDIT_CONTRACT_VERSION,
                          "implementation": {name: digest_file(Path(__file__).with_name(name)) for name in names},
                          "dependencies": versions})


def build_context(task_dir, domain_root, state, spec, candidate, run):
    """Bind the current captured source, selected revision and immutable run.

    The caller verifies the immutable run first. All files are reopened under
    confined paths here; submitted revision identity must match the engine run.
    """
    task_dir, domain_root, run = Path(task_dir), Path(domain_root), Path(run)
    require(type(candidate) is dict and candidate.get("valid") is True, "No valid provisional candidate")
    generation = "generation-" + digest_object({"source": state["input_spec_sha256"],
                                                 "selected": state["selected"]})[:24]
    revision = f"r{state['revision']:04d}"
    require(candidate.get("generation_id") == generation and candidate.get("revision_id") == revision,
            "Candidate generation or revision is stale")
    captured = safe_relative_file(domain_root, "input/spec.json")
    require(digest_file(captured) == state["input_spec_sha256"], "Captured input specification changed")
    require(load_bounded_json(captured) == spec, "Loaded calibration or specification is stale")
    submitted = safe_relative_file(domain_root, "input/submitted_spec.json")
    require(digest_object(load_bounded_json(submitted)) == state["submitted_spec_sha256"],
            "Original submitted specification changed")
    revision_spec = safe_relative_file(domain_root, f"revisions/{revision}/spec.json")
    selection_file = safe_relative_file(domain_root, f"revisions/{revision}/selection.json")
    selection = load_bounded_json(selection_file)
    expected_selection = {"revision_id": revision, "generation_id": generation, "selected": state["selected"],
                          "source_sha256": state["sources"], "human_semantic_review_required": True,
                          "engineering_approved": False, "identity_certified": False}
    require(selection == expected_selection and selection["human_semantic_review_required"] is True
            and selection["engineering_approved"] is False and selection["identity_certified"] is False,
            "Current selection record is inconsistent")
    run_record = safe_relative_file(run, "result.json")
    result = load_bounded_json(run_record, max_bytes=32 * 1024**2, max_nodes=600_000)
    require(result.get("run_id") == candidate.get("run_id") and result.get("status") == "review_required",
            "Candidate run identity or status is inconsistent")
    review = result.get("review")
    require(type(review) is dict and set(review) == {"state", "engineering_approved"}
            and review["state"] == "unreviewed" and review["engineering_approved"] is False,
            "Candidate semantic review boundary is inconsistent")
    require(result.get("provenance", {}).get("submitted_spec_sha256") == digest_file(revision_spec),
            "Built input differs from current revision or calibration")
    require(result.get("exports", {}).get("step_units") == "mm", "Candidate STEP units must be millimetres")
    step = safe_relative_file(run, result["exports"]["step"])
    manifest = safe_relative_file(run, "manifest.json")
    evidence = [artifact_reference(task_dir, captured, "captured_input_spec"),
                artifact_reference(task_dir, submitted, "submitted_input_spec"),
                artifact_reference(task_dir, revision_spec, "revision_spec"),
                artifact_reference(task_dir, selection_file, "revision_selection"),
                artifact_reference(task_dir, manifest, "run_manifest"),
                artifact_reference(task_dir, run_record, "run_result"),
                artifact_reference(task_dir, step, "exported_step")]
    for role, item in sorted(state["sources"].items()):
        source = safe_relative_file(domain_root / "input", item["file"])
        require(digest_file(source) == item["sha256"], "Captured source bytes changed")
        evidence.append(artifact_reference(task_dir, source, "captured_" + role))
    sections = result.get("sections")
    require(type(sections) is list and 3 <= len(sections) <= 300, "Invalid candidate section inventory")
    indices = sorted({0, min(1, len(sections) - 1), len(sections) // 2,
                      max(0, len(sections) - 2), len(sections) - 1})
    selected_sections = [sections[i] for i in indices]
    binding = {"generation_id": generation, "revision_id": revision, "run_id": result["run_id"],
               "source_manifest_sha256": digest_object({"spec_sha256": state["input_spec_sha256"],
                                                          "sources": state["sources"]}),
               "input_spec_sha256": state["input_spec_sha256"],
               "selection_sha256": digest_object(state["selected"]),
               "revision_spec_sha256": digest_file(revision_spec),
               "run_manifest_sha256": digest_file(manifest), "run_result_sha256": digest_file(run_record),
               "step_sha256": digest_file(step), "audit_implementation_sha256": implementation_identity()}
    return {"binding": binding, "evidence": evidence,
            "sampling": {"policy": SAMPLING_POLICY, "section_ids": [s["id"] for s in selected_sections],
                         "total_section_count": len(sections)},
            "section_info": {s["id"]: {"x_m": s["x_m"], "sample_count": len(s["points_yz_m"]),
                                        "pixels_per_metre": s["evidence"]["calibration"]["pixels_per_metre"]}
                             for s in selected_sections},
            "engine_metrics": {k: result["metrics"][k] for k in ("length_m", "beam_m", "depth_m", "volume_m3")}}


def assess_raw(raw, context):
    record(raw, RAW_KEYS, "Native audit")
    boolean(raw["geometry_checks_passed"], "Geometric result")
    require(boolean(raw["immutable_run_verified"], "Immutable run check") is True, "Native run is not verified")
    require(raw["numeric_reference_truth_used"] is False and raw["engineering_approved"] is False
            and raw["human_semantic_review_required"] is True, "Native review/truth boundary is invalid")
    require(raw["unresolved_semantics"] == SEMANTICS and raw["section_sampling"] == SECTION_SAMPLING_TEXT,
            "Unknown semantic obligations or section sampling contract")
    geometry = record(raw["geometry_audit"], GEOMETRY_KEYS, "Native geometry audit")
    require(geometry["source"] == "independently_reimported_exported_STEP"
            and geometry["step_units"] == "mm" and geometry["reported_units"] == "m",
            "Audit must measure actual exported millimetre STEP")
    require(geometry["step_sha256"] == context["binding"]["step_sha256"], "Audit belongs to another STEP")
    require(geometry["engineering_approved"] is False and geometry["human_semantic_review_required"] is True,
            "Native geometry review boundary is invalid")
    valid_shape = boolean(geometry["valid_shape"], "CAD shape validity")
    closed_shell = boolean(geometry["closed_shell"], "Closed shell check")
    solid_count = integer(geometry["solid_count"], "Solid count", 0, 20_000)
    shell_count = integer(geometry["shell_count"], "Shell count", 0, 20_000)
    metrics = record(geometry["metrics"], {"length_m", "beam_m", "depth_m", "volume_m3"}, "Reimported metrics")
    relative = number(geometry["relative_metric_error"], "Relative metric error")
    for key, value in metrics.items():
        require(number(value, key) > 0, "Reimported extents and volume must be positive")
    measured_relative = max(abs(metrics[k] - context["engine_metrics"][k]) /
                            max(abs(context["engine_metrics"][k]), 1e-12) for k in metrics)
    require(close(relative, measured_relative), "Reported metric error contradicts reimported measurements")
    cad_passed = valid_shape and closed_shell and solid_count == 1 and shell_count == 1 and relative <= TOLERANCES["max_relative_metric_error"]
    sections = raw["sampled_sections"]
    sampling = context["sampling"]
    require(type(sections) is list and len(sections) == len(sampling["section_ids"]), "Missing or excess sampled sections")
    require(integer(raw["sampled_section_count"], "Sampled section count", 1, 5) == len(sections)
            and integer(raw["total_section_count"], "Total section count", 3, 300) == sampling["total_section_count"],
            "Section count contradicts the current candidate")
    ids = []
    for section in sections:
        record(section, SECTION_KEYS, "Section measurement")
        sid = section["section_id"]
        require(type(sid) is str and sid in context["section_info"], "Unknown sampled section identity")
        info = context["section_info"][sid]
        ids.append(sid)
        require(close(number(section["x_m"], "Station position", minimum=-1e6), info["x_m"]), "Sampled station moved")
        require(integer(section["sample_count"], "Source sample count", 2, 1025) == info["sample_count"], "Source sample coverage changed")
        integer(section["section_edges"], "STEP section edge count", 1, 8192)
        require(section["distance_type"] == DISTANCE_TYPE, "Unknown trace distance definition")
        for key in ("rms_m", "p95_m", "max_m", "max_px"):
            number(section[key], key)
        require(section["rms_m"] <= section["max_m"] + 1e-12 and section["p95_m"] <= section["max_m"] + 1e-12,
                "Section error summaries are inconsistent")
        require(close(section["max_px"], section["max_m"] * info["pixels_per_metre"]), "Pixel/metre error conversion is inconsistent")
        if section["source_measurement_uncertainty_m"] is not None:
            number(section["source_measurement_uncertainty_m"], "Source measurement uncertainty")
    require(ids == sampling["section_ids"] and len(set(ids)) == len(ids), "Sampled section identity/order is inconsistent")
    maximum = max(section["max_m"] for section in sections)
    trace_passed = maximum <= TOLERANCES["max_section_distance_m"]
    passed = cad_passed and trace_passed
    require(raw["geometry_checks_passed"] is passed, "Native pass flag contradicts its individual checks")
    return Assessment(passed, cad_passed, trace_passed, float(maximum), relative)


def raw_validation(validation):
    record(validation, VALIDATION_KEYS, "Candidate validation")
    require(validation["identity_certified"] is False, "Contour identity cannot be automatically certified")
    return {key: validation[key] for key in RAW_KEYS}


def audit_artifact_references(artifacts, task_dir):
    require(type(artifacts) is list and 3 <= len(artifacts) <= 7, "Validation artifact inventory is incomplete")
    references = []
    seen = set()
    for artifact in artifacts:
        required = {"id", "path", "sha256", "mime_type", "kind", "bytes"}
        require(type(artifact) is dict and required <= set(artifact) and set(artifact) <= required | {"section_id"},
                "Unknown validation artifact metadata")
        reference = {key: artifact[key] for key in ("kind", "path", "sha256", "bytes")}
        validate_reference(reference, task_dir)
        require(artifact["id"] == "artifact-" + artifact["sha256"][:24], "Artifact ID/hash mismatch")
        require(artifact["path"] not in seen, "Duplicate validation artifact path")
        seen.add(artifact["path"])
        if artifact["kind"] == "step_section_cut_comparison":
            require(artifact["mime_type"] == "image/png" and type(artifact.get("section_id")) is str,
                    "Invalid section comparison artifact")
        else:
            require(artifact["kind"] in ("step_reimport_validation", "validation_worker_receipt")
                    and artifact["mime_type"] == "application/json" and "section_id" not in artifact,
                    "Unknown validation artifact kind")
        references.append(reference)
    return references


def make_contract(raw, context, artifacts, outcome, task_dir):
    require(type(outcome) is dict and outcome.get("state") == "exited"
            and type(outcome.get("exit_code")) is int and outcome["exit_code"] == 0,
            "Native audit did not complete successfully")
    assessment = assess_raw(raw, context)
    references = audit_artifact_references(artifacts, task_dir)
    contract = {"schema_version": SCHEMA_VERSION, "binding": context["binding"],
        "checks": {"worker_execution": "succeeded", "artifact_integrity": "passed",
                   "cad_validity": "passed" if assessment.cad_validity_passed else "failed",
                   "trace_fidelity": "passed" if assessment.trace_fidelity_passed else "failed"},
        "outcome": "passed" if assessment.passed else "failed", "units": dict(UNITS),
        "tolerances": dict(TOLERANCES), "sampling": context["sampling"],
        "measurements": {"max_section_distance_m": assessment.max_section_distance_m,
                         "relative_metric_error": assessment.relative_metric_error},
        "evidence": context["evidence"] + references, "audit_contract_version": AUDIT_CONTRACT_VERSION,
        "semantic_review": "required", "engineering_approved": False}
    return contract


def validate_contract_shape(contract):
    """Strict schema/semantic validation without trusting Python truthiness."""
    record(contract, CONTRACT_KEYS, "Validation contract")
    require(contract["schema_version"] == SCHEMA_VERSION and contract["audit_contract_version"] == AUDIT_CONTRACT_VERSION,
            "Unsupported validation contract version")
    binding = record(contract["binding"], BINDING_KEYS, "Validation binding")
    for key in BINDING_KEYS - {"generation_id", "revision_id", "run_id"}:
        sha256(binding[key], key)
    require(type(binding["generation_id"]) is str and re.fullmatch(r"generation-[0-9a-f]{24}", binding["generation_id"]) is not None,
            "Invalid generation identity")
    require(type(binding["revision_id"]) is str and re.fullmatch(r"r[0-9]{4,8}", binding["revision_id"]) is not None,
            "Invalid revision identity")
    require(type(binding["run_id"]) is str and re.fullmatch(r"[0-9a-f]{20}", binding["run_id"]) is not None, "Invalid run identity")
    checks = record(contract["checks"], {"worker_execution", "artifact_integrity", "cad_validity", "trace_fidelity"}, "Validation checks")
    require(checks["worker_execution"] == "succeeded" and checks["artifact_integrity"] == "passed",
            "Validation execution/integrity is incomplete")
    require(all(type(checks[k]) is str and checks[k] in ("passed", "failed") for k in ("cad_validity", "trace_fidelity")),
            "Unknown geometric check state")
    require(contract["outcome"] == ("passed" if checks["cad_validity"] == checks["trace_fidelity"] == "passed" else "failed"),
            "Validation conclusion contradicts individual checks")
    require(contract["units"] == UNITS and type(contract["units"]) is dict, "Invalid validation unit contract")
    tolerances = record(contract["tolerances"], set(TOLERANCES), "Audit tolerances")
    for key, wanted in TOLERANCES.items():
        require(number(tolerances[key], key) == wanted, "Audit tolerance is unsupported or changed")
    sampling = record(contract["sampling"], {"policy", "section_ids", "total_section_count"}, "Audit sampling")
    total = integer(sampling["total_section_count"], "Total section count", 3, 300)
    ids = sampling["section_ids"]
    require(sampling["policy"] == SAMPLING_POLICY and type(ids) is list and len(ids) == min(total, 5)
            and all(type(sid) is str and 0 < len(sid) <= 256 for sid in ids) and len(set(ids)) == len(ids),
            "Audit sampling is incomplete or unsupported")
    measurements = record(contract["measurements"], {"max_section_distance_m", "relative_metric_error"}, "Audit measurements")
    maximum = number(measurements["max_section_distance_m"], "Maximum trace distance")
    relative = number(measurements["relative_metric_error"], "Relative metric error")
    require((checks["trace_fidelity"] == "passed") == (maximum <= TOLERANCES["max_section_distance_m"]),
            "Trace check contradicts measured error")
    require(checks["cad_validity"] != "passed" or relative <= TOLERANCES["max_relative_metric_error"],
            "CAD check contradicts measured metric error")
    evidence = contract["evidence"]
    require(type(evidence) is list and 10 <= len(evidence) <= 64, "Validation evidence inventory is incomplete")
    for reference in evidence:
        validate_reference(reference)
    require(len({r["path"] for r in evidence}) == len(evidence), "Validation evidence paths are duplicated")
    require(contract["semantic_review"] == "required" and contract["engineering_approved"] is False,
            "Automated validation cannot grant engineering approval")


def verify_validation(validation, context, task_dir):
    """Recheck current identities, raw audit, all artifacts and derived checks."""
    raw = raw_validation(validation)
    contract = validation["contract"]
    validate_contract_shape(contract)
    require(contract["binding"] == context["binding"] and contract["sampling"] == context["sampling"],
            "Cached validation belongs to another source, revision, STEP or audit contract")
    require(validation["generation_id"] == context["binding"]["generation_id"]
            and validation["revision_id"] == context["binding"]["revision_id"], "Legacy validation identity disagrees")
    references = audit_artifact_references(validation["artifacts"], task_dir)
    require(contract["evidence"] == context["evidence"] + references, "Validation artifact binding is incomplete")
    for reference in contract["evidence"]:
        validate_reference(reference, task_dir)
    by_kind = {kind: [a for a in validation["artifacts"] if a["kind"] == kind]
               for kind in ("step_reimport_validation", "validation_worker_receipt", "step_section_cut_comparison")}
    require(len(by_kind["step_reimport_validation"]) == len(by_kind["validation_worker_receipt"]) == 1,
            "Missing or duplicate authoritative audit/receipt")
    sections = by_kind["step_section_cut_comparison"]
    require([a["section_id"] for a in sections] == context["sampling"]["section_ids"], "Section evidence coverage is incomplete")
    raw_file = safe_relative_file(Path(task_dir), by_kind["step_reimport_validation"][0]["path"])
    require(canonical_json(load_bounded_json(raw_file, max_bytes=2 * 1024**2, max_nodes=100_000)) == canonical_json(raw),
            "Cached validation contradicts authoritative audit artifact")
    receipt_file = safe_relative_file(Path(task_dir), by_kind["validation_worker_receipt"][0]["path"])
    receipt = load_bounded_json(receipt_file, max_bytes=2 * 1024**2, max_nodes=100_000)
    record(receipt, {"validation", "artifacts", "resources"}, "Native audit receipt")
    resources = record(receipt["resources"], {"wall_seconds", "cpu_seconds", "peak_rss_kib", "resource_profile"},
                       "Native audit resource receipt")
    number(resources["wall_seconds"], "Native wall time")
    number(resources["cpu_seconds"], "Native CPU time")
    integer(resources["peak_rss_kib"], "Native peak RSS", 1, 2**40)
    require(resources["resource_profile"] in KNOWN_RESOURCE_PROFILES, "Unknown native resource profile")
    require(canonical_json(receipt["validation"]) == canonical_json(raw),
            "Worker receipt contradicts authoritative audit")
    require(type(receipt["artifacts"]) is list and len(receipt["artifacts"]) == len(validation["artifacts"]) - 1,
            "Worker receipt artifact inventory is incomplete")
    expected_worker = [{"file": Path(a["path"]).name, "kind": a["kind"],
                        **({"section_id": a["section_id"]} if "section_id" in a else {})}
                       for a in validation["artifacts"] if a["kind"] != "validation_worker_receipt"]
    require(receipt["artifacts"] == expected_worker, "Worker receipt artifact inventory changed")
    assessment = assess_raw(raw, context)
    expected = make_contract(raw, context, validation["artifacts"], {"state": "exited", "exit_code": 0}, task_dir)
    require(contract == expected, "Validation contract contradicts authoritative measurements")
    return assessment


def ready_for_review(observation, context, task_dir):
    """Independent finalization predicate; a permissive envelope cannot pass."""
    try:
        require(type(observation) is dict and observation.get("ok") is True
                and observation.get("status") == "validated_review_required", "Validation observation is not a successful audit")
        require(observation.get("engineering_approved") is False
                and observation.get("human_semantic_review_required") is True,
                "Observation review boundary is invalid")
        require(observation.get("generation_id") == context["binding"]["generation_id"]
                and observation.get("revision_id") == context["binding"]["revision_id"], "Observation revision is stale")
        return verify_validation(observation.get("validation"), context, task_dir).passed
    except (ValidationContractError, OSError, ValueError, TypeError, KeyError):
        return False
