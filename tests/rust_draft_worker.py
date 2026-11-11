"""Worker shim for the Rust draft-guard tests (rust-control/tests/draft_guards.rs).

It runs the real rust_worker protocol and real DomainTools: inspection, draft
guesses, native CAD build, STEP export, rendering and the native audit. Nothing
is injected by default.

The test can write `draft-mode.json` next to the task directory:
  forge_guess   after build_draft, replace the chosen candidate of the first
                open guess with an id that the inspection never produced; the
                domain description stays consistent with the forged checkpoint,
                so only the Rust guess contract can reject it

Commands other than the worker protocol:
  make-drawing DIR   write the ambiguous drawing (section s0 has two lines) and
                     its spec.json into DIR
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from draft_fixture import draft_drawing

from vessel_reconstruction import rust_worker
from vessel_reconstruction.agent_tools import DomainTools

FORGED_CANDIDATE_ID = "contour-forged-by-worker"


def _domain_class(task_root: Path):
    path = task_root.parent / "draft-mode.json"
    mode = json.loads(path.read_text()) if path.is_file() else {}

    class Domain(DomainTools):
        def execute(self, name, arguments):
            observed = super().execute(name, arguments)
            if name == "build_draft" and mode.get("forge_guess") and self.open_guesses:
                self.state["guesses"][0]["chosen_candidate_id"] = FORGED_CANDIDATE_ID
                self._save()
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
