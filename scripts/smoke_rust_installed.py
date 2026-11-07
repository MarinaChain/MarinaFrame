#!/usr/bin/env python3
"""Exercise the installed wheel through the actual Rust control-plane binary.

This generated, calibrated three-section input is an installation check, not an
accuracy benchmark. Active output should be outside synchronized workspaces.
The script preserves every command/result and does not supply PYTHONPATH.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--controller", type=Path, required=True)
    parser.add_argument("--worker-python", type=Path, default=Path(sys.executable))
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    root = args.out.absolute()
    root.mkdir(parents=True, exist_ok=False)
    controller = args.controller.resolve(strict=True)
    python = args.worker_python.absolute()
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    env.pop("OPENCODE_API_KEY", None)
    records = []

    def command(name, argv):
        started = time.monotonic()
        with (root / f"{name}.stdout").open("x") as out, (root / f"{name}.stderr").open("x") as err:
            result = subprocess.run(argv, cwd=root, env=env, stdout=out, stderr=err, check=False)
        records.append({"stage": name, "command": argv, "exit_code": result.returncode,
                        "wall_seconds": time.monotonic() - started})
        (root / "commands.json").write_text(json.dumps(records, indent=2) + "\n")
        if result.returncode:
            raise RuntimeError(f"{name} failed; original output is retained")
        return (root / f"{name}.stdout").read_text()

    installed = json.loads(command("installed-import", [str(python), "-I", "-c",
        "import json,vessel_reconstruction;print(json.dumps({"
        "'version':vessel_reconstruction.__version__,'path':vessel_reconstruction.__file__}))"]))
    if installed["version"] != "0.4.0" or "site-packages" not in Path(installed["path"]).parts:
        raise RuntimeError("Worker must be the installed non-editable 0.4.0 package")
    example = Path(__file__).resolve().parents[1] / "examples" / "make_agent_example.py"
    command("generate-input", [str(python), str(example), "--out", str(root / "input")])
    task = root / "task"
    state = json.loads(command("rust-run", [str(controller), "run", "--task", str(task),
        "--source", str(root / "input/spec.json"), "--worker-python", str(python),
        "--policy", "deterministic"]))
    verification = json.loads(command("rust-verify", [str(controller), "verify", "--task", str(task)]))
    domain = json.loads((task / "domain/state.json").read_text())
    checks = {
        "installed_worker": True,
        "review_ready": state["status"] == "awaiting_human_review",
        "one_native_build": state["counters"]["builds"] == 1,
        "no_provider_calls": state["counters"]["requests_intended"] == 0,
        "no_operator_interventions": state["counters"]["operator_actions"] == 0,
        "body_and_oblique": set(domain["rendered_views"]) == {"body", "oblique"},
        "current_audit_passed": domain["validation"]["geometry_checks_passed"] is True,
        "verified_evidence": verification["valid"] is True and verification["artifact_references_verified"] > 0,
        "engineering_unapproved": state["engineering_approved"] is False,
    }
    summary = {"schema_version": "marinaframe.installed-rust-smoke.v1", "checks": checks,
        "passed": all(checks.values()), "worker": installed,
        "controller_sha256": hashlib.sha256(controller.read_bytes()).hexdigest(),
        "state": state, "verification": verification, "independent_accuracy_claim": False}
    (root / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps({"passed": summary["passed"], "checks": checks}))
    return 0 if summary["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
