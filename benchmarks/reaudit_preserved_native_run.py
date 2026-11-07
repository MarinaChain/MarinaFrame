"""Audit a copy of an immutable native run and exercise cached finalization.

This explicit test fixture preserves a legacy cached report before requesting a
new current-contract audit. It is not an automatic cache migration or a rebuild;
the original task and its STEP bytes remain unchanged. Native geometry is real,
and no audit measurement is replaced or injected.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import shutil

from vessel_reconstruction.agent_harness import Harness, ScriptedPolicy, TaskStore, verify_task
from vessel_reconstruction.agent_tools import DomainTools
from vessel_reconstruction.provenance import digest_file, write_json


class CountingNativeDomain(DomainTools):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.audit_calls = 0

    def _worker(self, operation, *args, **kwargs):
        if operation == "audit":
            self.audit_calls += 1
        return super()._worker(operation, *args, **kwargs)


def probe(source_task, out, *, expected="failed"):
    source_task, out = Path(source_task), Path(out)
    original_state = source_task / "domain/state.json"
    original_digest = digest_file(original_state)
    with TaskStore(out, create=True) as store:
        shutil.copytree(source_task / "domain", out / "domain")
        domain = CountingNativeDomain(out, out / "domain/input/spec.json")
        legacy_check = domain.execute("validate_candidate", {})
        # Explicitly create a new audit fixture in this copy, never in the
        # original task and never as a production response to an invalid cache.
        write_json(out / "preserved-legacy-validation.json", domain.state["validation"])
        domain.state["validation"] = None
        domain._save()
        first = domain.execute("validate_candidate", {})
        second = domain.execute("validate_candidate", {})
        audit_calls = domain.audit_calls
        restarted = CountingNativeDomain(out, out / "domain/input/spec.json")
        after_restart = restarted.execute("validate_candidate", {})
        decision = {"tool": "finish", "arguments": {
            "outcome": "candidate_ready_for_review",
            "summary": "Exercise finalization after a fresh native audit of preserved STEP."},
            "reason": "Exercise the current typed finalization gate with preserved real STEP."}
        state = Harness(store, restarted, ScriptedPolicy([decision])).run()
        validation = restarted.state["validation"]
        result = {
            "probe_kind": "fresh_current_contract_native_audit_of_preserved_STEP_no_rebuild",
            "source_task": str(source_task), "source_state_sha256": original_digest,
            "source_unchanged": digest_file(original_state) == original_digest,
            "explicit_test_fixture_revalidation": True,
            "expected_audit_outcome": expected,
            "legacy_cache_accepted": legacy_check["ok"],
            "legacy_cache_status": legacy_check["status"],
            "first_ok": first["ok"], "second_ok": second["ok"],
            "after_restart_ok": after_restart["ok"],
            "audit_calls": audit_calls, "restart_or_finish_audit_calls": restarted.audit_calls,
            "contract": validation["contract"],
            "maximum_section_distance_m": max(s["max_m"] for s in validation["sampled_sections"]),
            "threshold_m": 0.0011, "final_controller_status": state["status"],
            "engineering_approved": state["engineering_approved"],
        }
        write_json(out / "first-observation.json", first)
        write_json(out / "second-observation.json", second)
        write_json(out / "restart-observation.json", after_restart)
        write_json(out / "result.json", result)
    result["task_verification"] = verify_task(out)
    write_json(out / "result.json", result)
    expected_pass = expected == "passed"
    assert result["first_ok"] is result["second_ok"] is result["after_restart_ok"] is expected_pass
    assert result["audit_calls"] == 1 and result["restart_or_finish_audit_calls"] == 0
    assert result["final_controller_status"] == ("awaiting_human_review" if expected_pass else "blocked")
    assert result["engineering_approved"] is False and result["source_unchanged"] is True
    assert result["task_verification"]["valid"] is True
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-task", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--expect", choices=("passed", "failed"), default="failed")
    args = parser.parse_args()
    import json
    print(json.dumps(probe(args.source_task, args.out, expected=args.expect), indent=2))
