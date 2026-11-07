"""Worker shim for the Rust validation-matrix tests (rust-control/tests/validation_matrix.rs).

Like tests/rust_controlled_worker.py it runs the real rust_worker protocol and real
DomainTools. It differs in one respect: by default NOTHING is doubled, so the native
audit re-imports the exported STEP and measures real geometry.

The test writes `matrix-mode.json` next to the task directory (all keys optional):
  audit_outcome   inject a non-exited native audit outcome, for example
                  {"state": "interrupted", "elapsed_seconds": 0.0}; the worker
                  must not cache it as a validation
  loose_cad_bound   see below
  alternative_candidate   add one selectable second contour to section 0 after
                  inspect_source runs, so the test can select A, B and A again
Each native audit attempt appends one line to `matrix-audits.log` beside it.

Commands other than the worker protocol:
  make-drawing DIR [curved]   write the pixel fixture drawing and spec.json into DIR.
                              "curved" draws a quarter-circle hull stroke instead of the
                              straight one.

Failing geometry without an injected audit: a test writes {"loose_cad_bound": true} to
`matrix-mode.json` BEFORE the native build. The isolated build subprocess then runs with
tests/rust_matrix_sitecustomize, which raises the engine's 1 mm CAD approximation bound to
10 mm. The real STEP of the curved drawing deviates from the measured samples by more than
the 1.1 mm trace tolerance, and the real, unmodified audit reports the failure.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_agent_tools import drawing

from vessel_reconstruction import isolation, rust_worker
from vessel_reconstruction.agent_tools import DomainTools


ALTERNATIVE_CANDIDATE_ID = "race-choice"


def _install_alternative(domain) -> None:
    sid = domain.spec["sections"][0]["id"]
    candidates = domain.state["catalog"][sid]["candidates"]
    if any(c["candidate_id"] == ALTERNATIVE_CANDIDATE_ID for c in candidates):
        return
    candidates.append({
        "candidate_id": ALTERNATIVE_CANDIDATE_ID, "selectable": True,
        "hypothesis": "Controlled alternative source choice", "non_grid_competing_components": 0,
        "contour_selection": {"anchors_px": [[100, 30], [100, 210]], "half_width_px": 3}})
    domain._save()


def _curved_drawing(directory: Path):
    """The standard fixture with a quarter-circle stroke in every section."""
    path, spec = drawing(directory)
    image = Image.new("RGB", (600, 230), "white")
    draw = ImageDraw.Draw(image)
    for i in range(3):
        centre, bottom = i * 200 + 20, 210
        for x in range(centre, centre + 151, 30):
            draw.line((x, 30, x, bottom), fill=(210,) * 3, width=1)
        for y in range(30, bottom + 1, 30):
            draw.line((centre, y, centre + 170, y), fill=(210,) * 3, width=1)
        stroke = []
        for row in range(30, bottom + 1):
            height_fraction = (bottom - row) / (bottom - 30)
            stroke.append((centre + 30 + 100 * (1 - (1 - height_fraction) ** 2) ** 0.5, row))
        draw.line(stroke, fill=(15,) * 3, width=3)
    image.save(directory / "drawing.png")
    return path, spec


def _loosen_native_build_environment() -> None:
    """Give the isolated build subprocess the sitecustomize that loosens its CAD bound."""
    original = isolation.safe_worker_environment
    directory = str(Path(__file__).resolve().parent / "rust_matrix_sitecustomize")

    def environment():
        env = original()
        env["PYTHONPATH"] = os.pathsep.join((env["PYTHONPATH"], directory))
        env["MARINAFRAME_MATRIX_LOOSE_CAD"] = "1"
        return env

    isolation.safe_worker_environment = environment


def _mode(task_root: Path) -> dict:
    path = task_root.parent / "matrix-mode.json"
    return json.loads(path.read_text()) if path.is_file() else {}


def _domain_class(task_root: Path):
    mode = _mode(task_root)
    if mode.get("loose_cad_bound"):
        _loosen_native_build_environment()
    audit_log = task_root.parent / "matrix-audits.log"

    class Domain(DomainTools):
        def _worker(self, operation, request, out, *, native=False):
            if operation == "audit":
                with audit_log.open("a") as stream:
                    stream.write(operation + "\n")
                if mode.get("audit_outcome") is not None:
                    return dict(mode["audit_outcome"]), None
            return super()._worker(operation, request, out, native=native)

        def execute(self, name, arguments):
            observed = super().execute(name, arguments)
            if name == "inspect_source" and mode.get("alternative_candidate"):
                _install_alternative(self)
            return observed

    return Domain


def main(argv: list[str]) -> int:
    if argv[:1] == ["make-drawing"]:
        (_curved_drawing if argv[2:] == ["curved"] else drawing)(Path(argv[1]))
        return 0
    if argv[:2] == ["-m", "vessel_reconstruction.rust_worker"]:
        argv = argv[2:]
    task_root = Path(argv[argv.index("--task-root") + 1])
    rust_worker.DomainTools = _domain_class(task_root)
    return rust_worker.main(argv)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
