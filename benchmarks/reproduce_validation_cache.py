"""Controlled state-machine reproduction of the published 0.3 validation bug.

This probe injects a failed audit. It exercises the unmodified DomainTools
cache and Harness finalization methods; it does not claim a measured invalid
real hull or engineering approval. Run against a specified source checkout via
PYTHONPATH and retain that checkout's identity with the result.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from vessel_reconstruction.agent_harness import Harness, ScriptedPolicy, TaskStore
from vessel_reconstruction.agent_tools import DomainTools


class ControlledFailedAudit(DomainTools):
    """Minimal source/domain double, with a deliberately failed audit result."""

    def __init__(self, task_dir):
        self.task_dir = Path(task_dir)
        self.root = self.task_dir / "domain"
        self.root.mkdir(parents=True, exist_ok=True)
        self.state_path = self.root / "state.json"
        self.cancel_event = None
        self.audit_calls = 0
        self.spec = {"sections": [{"id": "probe-section"}]}
        self.state = {"revision": 1, "selected": {"probe-section": "injected-source-choice"},
                      "input_spec_sha256": "a" * 64, "validation": None}
        self._save()

    def _verify_inputs(self):
        pass  # Controlled domain double; this probe does not claim source truth.

    def describe(self):
        return {"source_manifest_sha256": "b" * 64, "generation_id": self.generation_id,
                "revision_id": self.revision_id, "section_count": 1, "catalog_ready": True,
                "sections": self.spec["sections"]}

    def _verified_candidate(self, *, allow_previous=False):
        return {"generation_id": self.generation_id, "revision_id": self.revision_id}, self.root

    def _worker(self, operation, request, out, *, native=False):
        assert operation == "audit"
        self.audit_calls += 1
        return {"elapsed_seconds": 0.0}, {"validation": {
            "geometry_checks_passed": False, "immutable_run_verified": True,
            "geometry_audit": {"valid_shape": True}, "sampled_sections": [],
            "sampled_section_count": 0, "total_section_count": 1,
            "numeric_reference_truth_used": False}, "artifacts": []}


def probe(out):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=False)
    direct = ControlledFailedAudit(out / "direct")
    first = direct.execute("validate_candidate", {})
    second = direct.execute("validate_candidate", {})
    choices = [
        {"tool": "validate_candidate", "arguments": {}, "reason": "Controlled failed-audit probe."},
        {"tool": "finish", "arguments": {"outcome": "candidate_ready_for_review",
                                           "summary": "Controlled finalization probe."},
         "reason": "Exercise cached validation during finalization."},
    ]
    with TaskStore(out / "controller", create=True) as store:
        domain = ControlledFailedAudit(store.path)
        state = Harness(store, domain, ScriptedPolicy(choices)).run()
        events = list(store.events)
    result = {
        "probe_kind": "controlled_injected_audit_failure_not_real_geometry_measurement",
        "first_ok": first.get("ok"), "second_ok": second.get("ok"),
        "cached_geometry_passed": (direct.state.get("validation") or {}).get("geometry_checks_passed"),
        "audit_calls": direct.audit_calls, "controller_audit_calls": domain.audit_calls,
        "controller_rejections": state["rejections"], "controller_actions": state["actions"],
        "final_controller_status": state["status"], "engineering_approved": state["engineering_approved"],
        "first_observation": first, "second_observation": second,
        "event_kinds": [e["kind"] for e in events],
    }
    (out / "result.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    probe(parser.parse_args().out)
