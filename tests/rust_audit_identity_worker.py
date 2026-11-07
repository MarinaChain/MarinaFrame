"""Worker shim for rust-control/tests/audit_identity.rs.

It runs the real rust_matrix_worker (real rust_worker protocol, real DomainTools, real
native audit) and adds identity faults. The test writes `audit-mode.json` next to the task
directory. The file is read at every worker request, so a test can switch a fault on
after initialization (all keys optional):

  omit_audit_identity       drop `audit_implementation_sha256` from the result, like a
                            worker that predates the audit pin
  report_audit_identity     report this identity in the result only; the validation
                            contract stays honest
  consistent_audit_identity this identity everywhere: result, validation contract and
                            validation context. This models a changed or substituted audit
                            implementation that reports itself consistently.
  envelope_worker_identity  report this worker `implementation_sha256` in the receipt,
                            while the worker's own expected-identity check still sees the
                            real value
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import rust_matrix_worker

from vessel_reconstruction import rust_worker, validation_contract


def _mode(task_root: Path) -> dict:
    path = task_root.parent / "audit-mode.json"
    return json.loads(path.read_text()) if path.is_file() else {}


def _install(mode: dict) -> None:
    consistent = mode.get("consistent_audit_identity")
    if consistent is not None:
        validation_contract.implementation_identity = lambda: consistent
        rust_worker.audit_implementation_identity = lambda: consistent
    reported = mode.get("report_audit_identity")
    if reported is not None:
        rust_worker.audit_implementation_identity = lambda: reported
    omit = mode.get("omit_audit_identity")
    envelope = mode.get("envelope_worker_identity")
    if not (omit or envelope):
        return
    execute = rust_worker.execute

    def changed(*args, **kwargs):
        response = execute(*args, **kwargs)
        if omit:
            response["result"].pop("audit_implementation_sha256", None)
        if envelope:
            response["implementation_sha256"] = envelope
        return response

    rust_worker.execute = changed


def main(argv: list[str]) -> int:
    if argv[:1] == ["make-drawing"]:
        return rust_matrix_worker.main(argv)
    task_root = Path(argv[argv.index("--task-root") + 1])
    _install(_mode(task_root))
    return rust_matrix_worker.main(argv)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
