"""Controlled Python worker for the Rust finalization-guard tests.

The Rust controller starts this file in place of `-m vessel_reconstruction.rust_worker`.
It runs the real rust_worker protocol and real DomainTools: source inspection,
selection, native CAD build, STEP export and rendering are not doubled. Only the
native audit result is injected (ControlledValidationDomain's audit), so a test
can choose a passing or failing audit. The Rust controller still verifies the
real immutable run independently. Nothing here is engineering evidence.

The test writes `controlled-mode.json` next to the task directory:
  maximum          injected audit error in metres (above 0.0011 fails trace fidelity)
  permissive       report ok=true in the envelope even when the contract fails
  race_candidate   add one selectable alternative contour before validation
Each injected audit appends one line to `controlled-audits.log` beside it.

Commands other than the worker protocol:
  make-drawing DIR   write the pixel fixture drawing and its spec.json into DIR
  select-race TASK   try to commit the alternative selection; print the observation
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_agent_tools import drawing
from validation_fixture import ControlledValidationDomain

from vessel_reconstruction import rust_worker
from vessel_reconstruction.agent_tools import DomainTools

RACE_CANDIDATE_ID = "race-choice"


def _mode(task_root: Path) -> dict:
    return json.loads((task_root.parent / "controlled-mode.json").read_text())


def _race_arguments(domain) -> dict:
    sid = domain.spec["sections"][0]["id"]
    return {"selections": [{"section_id": sid, "candidate_id": RACE_CANDIDATE_ID}]}


def _install_race_candidate(domain) -> None:
    sid = domain.spec["sections"][0]["id"]
    candidates = domain.state["catalog"][sid]["candidates"]
    if any(c["candidate_id"] == RACE_CANDIDATE_ID for c in candidates):
        return
    candidates.append({
        "candidate_id": RACE_CANDIDATE_ID, "selectable": True, "hypothesis": "Controlled race source choice",
        "contour_selection": {"anchors_px": [[100, 30], [100, 210]], "half_width_px": 3}})
    domain._save()


def _controlled_domain_class(task_root: Path):
    mode = _mode(task_root)
    audit_log = task_root.parent / "controlled-audits.log"

    class Domain(ControlledValidationDomain):
        # Real candidate verification; ControlledValidationDomain skips it.
        _verified_candidate = DomainTools._verified_candidate

        def __init__(self, task_dir, spec_path, *, cancel_event=None):
            # Skip ControlledValidationDomain.__init__: it fabricates a build.
            DomainTools.__init__(self, task_dir, spec_path, cancel_event=cancel_event)
            self.audit_calls = 0
            self.maximum = mode["maximum"]
            self.raw_mutator = None
            self.outcome = None

        def _worker(self, operation, request, out, *, native=False):
            if operation != "audit":
                return DomainTools._worker(self, operation, request, out, native=native)
            with audit_log.open("a") as stream:
                stream.write(operation + "\n")
            outcome = super()._worker(operation, request, out, native=native)
            # rust_worker decodes comparison images into model observations, so
            # the fixture's placeholder bytes are replaced by real small PNGs.
            for artifact in outcome[1]["artifacts"]:
                if artifact["kind"] == "step_section_cut_comparison":
                    Image.new("RGB", (64, 64), "white").save(out / artifact["file"])
            return outcome

        def execute(self, name, arguments):
            if name == "validate_candidate" and mode.get("race_candidate"):
                _install_race_candidate(self)
            observed = super().execute(name, arguments)
            if mode.get("permissive") and name == "validate_candidate":
                observed = observed | {"ok": True, "status": "validated_review_required"}
            return observed

    return Domain


def main(argv: list[str]) -> int:
    if argv[:1] == ["make-drawing"]:
        drawing(Path(argv[1]))
        return 0
    if argv[:1] == ["select-race"]:
        task_root = Path(argv[1])
        domain_class = _controlled_domain_class(task_root)
        domain = domain_class(task_root, task_root / "domain/input/spec.json")
        print(json.dumps(domain.execute("select_contours", _race_arguments(domain))))
        return 0
    # Rust passes `-m vessel_reconstruction.rust_worker` before the worker flags.
    if argv[:2] == ["-m", "vessel_reconstruction.rust_worker"]:
        argv = argv[2:]
    task_root = Path(argv[argv.index("--task-root") + 1])
    rust_worker.DomainTools = _controlled_domain_class(task_root)
    return rust_worker.main(argv)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
