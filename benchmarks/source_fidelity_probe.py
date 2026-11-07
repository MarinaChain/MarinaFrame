"""Source-only development probe for explicit contour interpretations.

This is a measured domain-toolchain experiment, not a live model trajectory or
an independent final evaluation. No evaluator target is accepted or opened.
Run under the desired source checkout via PYTHONPATH; score returned outputs in
a separate process afterwards. Active native work should use a fresh /tmp path.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import time

from vessel_reconstruction.agent_tools import DomainTools
from vessel_reconstruction.provenance import digest_file, write_json
from vessel_reconstruction.run_record import verify_run


def run(spec: Path, output: Path, policy: str, *, render=True, build=True):
    if output.exists():
        raise ValueError("Use a fresh output directory; failed attempts are retained.")
    started = time.monotonic()
    domain = DomainTools(output, spec)
    records = []

    def action(name, arguments):
        before = time.monotonic()
        result = domain.execute(name, arguments)
        records.append({"operation": name, "arguments": arguments,
                        "elapsed_seconds": time.monotonic() - before, "result": result})
        write_json(output / "probe-actions.json", records)
        return result

    selections = []
    unresolved = []
    pending = [section["id"] for section in domain.describe()["sections"]]
    while pending:
        observed = action("inspect_source", {"section_ids": pending[:12]})
        if not observed["ok"]:
            unresolved.append({"reason": "inspection_failed", "result": observed})
            break
        returned = {section["section_id"] for section in observed["sections"]}
        if not returned:
            unresolved.append({"reason": "no_observable_progress"})
            break
        # Catalog inspection can finish before the48KiB bounded observation
        # returns every section. Explicitly request omitted known IDs again.
        pending = [sid for sid in pending if sid not in returned]
        for section in observed["sections"]:
            candidates = section["candidates"]
            endpoints = [c for c in candidates if c.get("endpoint_evidence")]
            legacy = [c for c in candidates if not c.get("endpoint_evidence")]
            preferred = section["grid_evidence"].get("unique_non_grid_candidate_id")
            base_choice = next((c for c in legacy if c["candidate_id"] == preferred), None)
            if base_choice is None and len(legacy) == 1:
                base_choice = legacy[0]
            choice = None
            if policy == "endpoint_contact" and base_choice is not None:
                related = [c for c in endpoints if c["endpoint_evidence"].get("centroid_alternative_id") == base_choice["candidate_id"]]
                if len(related) == 1:
                    choice = related[0]
                elif len(related) > 1:
                    unresolved.append({"section_id": section["section_id"], "reason": "multiple_endpoint_interpretations"})
                    continue
            if choice is None:
                choice = base_choice
            if choice is None:
                unresolved.append({"section_id": section["section_id"], "reason": "no_unique_source_hypothesis"})
            else:
                selections.append({"section_id": section["section_id"], "candidate_id": choice["candidate_id"]})
    selected = None
    built = None
    validation = None
    if not unresolved and len(selections) == domain.describe()["section_count"]:
        selected = action("select_contours", {"selections": selections})
        if selected["ok"] and build:
            built = action("build_provisional", {})
            if built["ok"]:
                if render:
                    for view in ("body", "plan", "profile", "oblique"):
                        action("render_candidate", {"view": view})
                validation = action("validate_candidate", {})
    candidate = built.get("candidate") if built else None
    run_path = output / candidate["path"] if candidate else None
    module = Path(__import__("vessel_reconstruction.ingest", fromlist=["x"]).__file__).parent
    result = {"experiment": "known_development_source_fidelity_probe_v1", "policy": policy,
              "not_a_final_holdout": True, "model_calls": 0, "operator_actions": 0,
              "selection_scope": "Explicit research policy over inspected source-supported candidates; not expert semantic approval",
              "reference_geometry_accessed": False, "source_spec_sha256": digest_file(spec),
              "source_manifest_sha256": domain.describe()["source_manifest_sha256"],
              "implementation_sha256": {p.name: digest_file(p) for p in module.glob("*.py")},
              "unresolved": unresolved, "section_count": domain.describe()["section_count"],
              "selected_count": len(selections), "built": bool(built and built["ok"]),
              "validation_ok": validation.get("ok") if validation else None,
              "validation_status": validation.get("status") if validation else None,
              "candidate_run_relative_path": candidate["path"] if candidate else None,
              "run_verification": verify_run(run_path) if run_path else None,
              "elapsed_seconds": time.monotonic() - started,
              "engineering_approved": False}
    write_json(output / "probe-summary.json", result)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("spec", type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--policy", choices=("legacy_candidate", "endpoint_contact"), required=True)
    parser.add_argument("--no-render", action="store_true")
    parser.add_argument("--no-build", action="store_true")
    args = parser.parse_args()
    result = run(args.spec, args.out, args.policy, render=not args.no_render, build=not args.no_build)
    print(json.dumps({k: v for k, v in result.items() if k != "implementation_sha256"}, indent=2))
