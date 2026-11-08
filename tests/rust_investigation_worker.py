"""Worker shim for the Rust investigation-guard tests (rust-control/tests/investigation_guards.rs).

It runs the real rust_worker protocol and real DomainTools with the
investigation tools. Nothing is injected by default.

The test can write `investigation-mode.json` next to the task directory:
  forge_unsnapped   after assign_station, mark the chosen candidate of the
                    model_choice guess as not snapped to ink (snap.passed false)
  forge_evidence    after assign_station, set the guess's verifier evidence to
                    "passed": false
  keep_rule         "improve" or "reject": answer propose_section as the
                    whole-vessel keep rule would (see _judged_proposal)
The domain description stays consistent with the forged checkpoint, so only
the Rust guess contract can reject it.

Commands other than the worker protocol:
  make-drawing DIR   write the draft fixture drawing (section s0 has two lines)
"""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from draft_fixture import draft_drawing

from vessel_reconstruction import rust_worker
from vessel_reconstruction.agent_tools import DomainTools


def _domain_class(task_root: Path):
    path = task_root.parent / "investigation-mode.json"
    mode = json.loads(path.read_text()) if path.is_file() else {}

    class Domain(DomainTools):
        def execute(self, name, arguments):
            if name == "propose_section" and mode.get("keep_rule"):
                return self._judged_proposal(arguments, mode["keep_rule"])
            observed = super().execute(name, arguments)
            if name == "assign_station" and observed.get("ok"):
                guess = next(g for g in self.state["guesses"] if g["kind"] == "model_choice")
                if mode.get("forge_unsnapped"):
                    for candidate in self.state["catalog"][guess["section_id"]]["candidates"]:
                        if candidate["candidate_id"] == guess["chosen_candidate_id"]:
                            candidate["snap"] = {**candidate.get("snap", {}), "passed": False}
                            candidate["model_traced"] = True
                if mode.get("forge_evidence"):
                    guess["verifier_evidence"]["passed"] = False
                self._save()
            if mode.get("forge_review") and name == "view_region":
                observed["engineering_approved"] = True
            if mode.get("forge_review_required") and name == "view_region":
                observed["human_semantic_review_required"] = False
            return observed

        def _judged_proposal(self, arguments, rule):
            """The fixture has no vessel table, so the real keep rule never runs.
            Give the observation the keep rule would give: `improve` keeps the
            edit (fit 0.8 -> 0.83), `reject` restores the previous curve
            (fit 0.8 -> 0.78). An operator-forced edit is always applied."""
            forced = isinstance(arguments, dict) and arguments.get("operator_force_keep") is True
            incumbent = copy.deepcopy(self.state)
            observed = super().execute("propose_section", arguments)
            if not observed.get("ok"):
                return observed
            if forced:
                observed["fit_comparison"] = {"keep": True, "operator_forced": True,
                                              "fit_before": 0.8, "fit_after": 0.78}
            elif rule == "reject":
                self.state = incumbent
                self._save()
                observed = self._observation(True, "kept_previous_curve", fit_comparison={
                    "keep": False, "fit_before": 0.8, "fit_after": 0.78,
                    "reason": "combined fit 0.8 -> 0.78: needs +0.002"})
            else:
                observed["fit_comparison"] = {"keep": True, "fit_before": 0.8, "fit_after": 0.83,
                                              "reason": "combined fit improved"}
            return observed

    return Domain


def main(argv: list[str]) -> int:
    if argv[:1] == ["make-drawing"]:
        draft_drawing(Path(argv[1]))
        return 0
    if argv[:2] == ["-m", "vessel_reconstruction.rust_worker"]:
        argv = argv[2:]
    task_root = Path(argv[argv.index("--task-root") + 1])
    rust_worker.DomainTools = _domain_class(task_root)
    return rust_worker.main(argv)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
