"""Author-separated protocol adversaries over preserved real native evidence.

No CAD or provider call is made. Each mutation applies only to a fresh task copy
and deliberately constructs malformed tool evidence; it does not claim a hostile
host can be authenticated by local hashes. The Rust CLI must reject every bad
readiness attempt, independently of Python's stricter tool-side checks.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import json
from pathlib import Path
import shutil
import subprocess

from vessel_reconstruction.agent_tools import DomainTools
from vessel_reconstruction.provenance import digest_file, write_json
from vessel_reconstruction.validation_contract import ready_for_review


def main(binary, evidence, out):
    out.mkdir(parents=True, exist_ok=False)
    results = []
    cases = ["pass", "failed_native", "missing_contract", "stale_revision", "missing_audit",
             "changed_step", "numeric_boolean", "semantics_removed", "sampling_changed",
             "metric_extra_field", "section_edges_zero", "uncertainty_string",
             "receipt_resource_bool", "receipt_inventory_changed", "selection_record_changed",
             "evidence_kind_path_misbound", "context_metrics_changed", "context_sections_changed"]
    for name in cases:
        source_name = "failure" if name == "failed_native" else "pass"
        root = out / name
        shutil.copytree(evidence / f"real-native-{source_name}-current", root)
        observation = json.loads((evidence / f"real-native-{source_name}-current-observation.json").read_text())
        domain = json.loads((evidence / f"real-native-{source_name}-current-describe.json").read_text())
        context = json.loads((evidence / f"real-native-{source_name}-current-context.json").read_text())
        validation = observation["validation"]
        contract = validation["contract"]
        artifacts = validation["artifacts"]
        audit_path = root / next(a["path"] for a in artifacts if a["kind"] == "step_reimport_validation")
        receipt_path = root / next(a["path"] for a in artifacts if a["kind"] == "validation_worker_receipt")
        raw = json.loads(audit_path.read_text())
        receipt = json.loads(receipt_path.read_text())
        changed_raw = False
        if name == "numeric_boolean": raw["geometry_checks_passed"] = 1; changed_raw = True
        if name == "semantics_removed": raw["unresolved_semantics"] = []; changed_raw = True
        if name == "sampling_changed": raw["section_sampling"] = "exhaustive"; changed_raw = True
        if name == "metric_extra_field": raw["geometry_audit"]["metrics"]["unknown"] = 0; changed_raw = True
        if name == "section_edges_zero": raw["sampled_sections"][0]["section_edges"] = 0; changed_raw = True
        if name == "uncertainty_string": raw["sampled_sections"][0]["source_measurement_uncertainty_m"] = "unknown"; changed_raw = True
        if changed_raw:
            validation.update(deepcopy(raw))
            receipt["validation"] = deepcopy(raw)
            write_json(audit_path, raw)
        if name == "receipt_resource_bool": receipt["resources"]["cpu_seconds"] = False
        if name == "receipt_inventory_changed": receipt["artifacts"][0]["file"] = "other-section.png"
        write_json(receipt_path, receipt)
        if name == "selection_record_changed":
            reference = next(e for e in context["evidence"] if e["kind"] == "revision_selection")
            path = root / reference["path"]
            selection = json.loads(path.read_text()); selection["engineering_approved"] = True
            write_json(path, selection)
            reference.update(sha256=digest_file(path), bytes=path.stat().st_size)
        if name == "evidence_kind_path_misbound":
            reference = next(e for e in context["evidence"] if e["kind"] == "captured_input_spec")
            relative = domain["current_candidate"]["path"] + "/submitted_spec.json"
            path = root / relative
            reference.update(path=relative, sha256=digest_file(path), bytes=path.stat().st_size)
        if name == "context_metrics_changed": context["engine_metrics"]["volume_m3"] = 987654321.0
        if name == "context_sections_changed": context["section_info"] = {}
        for a in artifacts:
            path = root / a["path"]
            a.update(sha256=digest_file(path), bytes=path.stat().st_size)
            a["id"] = "artifact-" + a["sha256"][:24]
        contract["evidence"] = context["evidence"] + [{k: a[k] for k in ("kind", "path", "sha256", "bytes")} for a in artifacts]
        if name == "missing_contract": del validation["contract"]["binding"]["step_sha256"]
        if name == "stale_revision": observation["revision_id"] = "r9999"
        if name == "missing_audit": audit_path.unlink()
        if name == "changed_step":
            path = root / domain["current_candidate"]["path"] / "model.step"
            path.write_bytes(path.read_bytes() + b"\nMUTATED TEST FIXTURE\n")
        observation["validation"] = validation
        observation["artifacts"] = deepcopy(artifacts)
        domain["validation"] = validation
        for label, value in (("observation", observation), ("domain", domain), ("context", context)):
            write_json(root / (label + ".json"), value)
        try:
            tools = DomainTools(root, root / "domain/input/spec.json")
            python_ready = ready_for_review(observation, tools.validation_context(), root)
        except (ValueError, OSError, KeyError, TypeError):
            python_ready = False
        execution = subprocess.run([str(binary), "check-validation", "--task", str(root),
            "--observation", str(root / "observation.json"), "--domain", str(root / "domain.json"),
            "--context", str(root / "context.json")], capture_output=True, text=True, timeout=30)
        try:
            response = json.loads(execution.stdout if execution.returncode == 0 else execution.stderr)
        except json.JSONDecodeError:
            response = {"unparsed_response": (execution.stdout + execution.stderr)[:2000]}
        rust_ready = response.get("ready_for_human_review") is True
        results.append({"case": name, "python_ready": python_ready, "rust_ready": rust_ready,
                        "rust_exit_code": execution.returncode, "response": response,
                        "expected_ready": name == "pass"})
    report = {"reviewer": "validation_v04; separate author from Rust controller",
              "binary_sha256": digest_file(binary), "native_or_provider_calls": 0,
              "cases": results, "unexpected_readiness": [r["case"] for r in results if r["rust_ready"] != r["expected_ready"]]}
    write_json(out / "results.json", report)
    print(json.dumps(report, indent=2))
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    main(args.binary.resolve(), args.evidence.resolve(), args.out.resolve())
