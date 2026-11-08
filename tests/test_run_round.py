"""Tests for scripts/run_round.py with a fake controller: no network, no real keys."""

from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "run_round.py"
spec = importlib.util.spec_from_file_location("run_round", SCRIPT)
run_round = importlib.util.module_from_spec(spec)
spec.loader.exec_module(run_round)

# A fake marinaframe controller: writes digest-able events, prints a final JSON
# summary line. Cases whose id starts with "bad" fail the same way every time.
FAKE_CONTROLLER = """#!/usr/bin/env python3
import json, sys
from pathlib import Path

args = {k.lstrip("-"): v for k, v in zip(sys.argv[2:][0::2], sys.argv[2:][1::2])}  # argv[1] is "run"
events = Path(args["task"]) / "events"
events.mkdir(parents=True, exist_ok=True)
case = Path(args["source"]).parent.name

def event(n, kind, payload):
    (events / f"{n:08d}.json").write_text(json.dumps({"sequence": n, "kind": kind, "payload": payload}))

if case.startswith("bad"):
    for n in range(3):
        event(n + 1, "decision", {"actor": "live_model", "decision": {"tool": "read_region", "arguments": {"id": "s1"}, "reason": "stuck"}})
    event(4, "task_terminated", {"reason": "repeated_identical_action_refusals"})
    print(json.dumps({"status": "no_progress", "termination_reason": "repeated_identical_action_refusals"}))
else:
    event(1, "decision", {"actor": "live_model", "decision": {"tool": "build_draft", "arguments": {}, "reason": "go"}})
    event(2, "worker_result", {"operation": "build_draft", "response": {"result": {"status": "built", "candidate": {"valid": True}}}})
    print(json.dumps({"status": "completed", "termination_reason": "none"}))
"""

LIVE_FLAGS = ("--policy", "live", "--on-ambiguity", "draft", "--context", "conversation")


def setup_round(tmp_path, monkeypatch, case_names, known_extra=(), flags=("--policy", "deterministic"),
                cases_arg=None, key=None):
    """Build argv for main() against a fake main checkout; returns (argv, out, binary)."""
    for name in list(os.environ):
        if name.startswith("OPENCODE_API_KEY"):
            monkeypatch.delenv(name)
    if key:
        monkeypatch.setenv("OPENCODE_API_KEY", key)
    main_root = tmp_path / "main"
    inputs = tmp_path / "inputs"
    for name in case_names:
        (inputs / name).mkdir(parents=True)
        (inputs / name / "spec.json").write_text("{}")
    binary = tmp_path / "fake-marinaframe"
    binary.write_text(FAKE_CONTROLLER)
    binary.chmod(0o755)
    worker_python = tmp_path / "python3"
    worker_python.write_text("# fake interpreter\n")
    worker_source = tmp_path / "src"
    worker_source.mkdir()
    monkeypatch.setattr(run_round, "main_checkout", lambda: main_root)
    monkeypatch.setattr(run_round, "worktree_roots", lambda: [main_root])
    out = main_root / "work" / "round1"
    argv = ["--cases", *(cases_arg if cases_arg is not None else case_names), "--inputs", str(inputs),
            "--out", str(out), "--binary", str(binary), "--worker-source", str(worker_source),
            "--worker-python", str(worker_python), "--basis", "authorized for tests",
            *known_extra, *flags]
    return argv, out, binary


def read(path):
    return json.loads(path.read_text())


def test_round_runs_cases_writes_results_and_digest(tmp_path, monkeypatch):
    argv, out, binary = setup_round(tmp_path, monkeypatch, ["c1", "c2"], flags=LIVE_FLAGS, key="k-TESTSECRET-1")
    assert run_round.main(argv) == 0
    row = read(out / "c1" / "result.json")
    assert row["case"] == "c1" and row["controller_status"] == "completed" and row["exit_code"] == 0
    command = read(out / "c1" / "command.json")
    assert command[:6] == [str(binary), "run", "--task", str(out / "c1" / "task"),
                           "--source", str(tmp_path / "inputs" / "c1" / "spec.json")]
    tail = dict(zip(command[6::2], command[7::2]))
    assert tail["--worker-python"] == str(tmp_path / "python3")
    assert tail["--worker-source"] == str(tmp_path / "src")
    assert tail["--policy"] == "live" and tail["--context"] == "conversation"
    assert tail["--provider-transfer-basis"] == "authorized for tests"
    assert "## c1" in (out / "digest.md").read_text() and "## c2" in (out / "digest.md").read_text()
    assert (out / "round.log").read_text()
    meta = read(out / "round.json")
    assert meta["cases"] == ["c1", "c2"] and meta["jobs"] == 2
    assert "marinaframe-native-admission" in meta["native_admission_lock"]
    for path in out.rglob("*"):  # never read, print or log key material
        if path.is_file():
            assert "k-TESTSECRET-1" not in path.read_text()
            assert "OPENCODE_API_KEY" not in path.read_text()


def test_early_stop_skips_remaining_cases(tmp_path, monkeypatch):
    argv, out, _ = setup_round(tmp_path, monkeypatch, ["bad1", "bad2", "good1"])
    assert run_round.main(argv) == 0
    assert (out / "bad1" / "result.json").exists() and (out / "bad2" / "result.json").exists()
    assert not (out / "good1").exists()
    log = (out / "round.log").read_text()
    assert "early stop" in log and "good1: " not in log
    assert "early stop" in (out / "digest.md").read_text()
    assert read(out / "round.json")["cases"] == ["bad1", "bad2", "good1"]


def test_no_early_stop_flag_runs_all_cases(tmp_path, monkeypatch):
    argv, out, _ = setup_round(tmp_path, monkeypatch, ["bad1", "bad2", "good1"],
                               known_extra=("--no-early-stop",))
    assert run_round.main(argv) == 0
    assert read(out / "good1" / "result.json")["controller_status"] == "completed"


def test_live_policy_without_key_fails_before_any_run(tmp_path, monkeypatch):
    argv, out, _ = setup_round(tmp_path, monkeypatch, ["c1"], flags=LIVE_FLAGS)
    with pytest.raises(SystemExit, match="load_opencode_keys"):
        run_round.main(argv)
    assert not out.exists()


def test_live_policy_without_basis_fails(tmp_path, monkeypatch):
    argv, out, _ = setup_round(tmp_path, monkeypatch, ["c1"], flags=LIVE_FLAGS, key="k1")
    argv = [a for a in argv if a != "authorized for tests"]
    argv.remove("--basis")
    with pytest.raises(SystemExit, match="transfer basis"):
        run_round.main(argv)


def test_cases_file_and_max_cases(tmp_path, monkeypatch):
    ids = [f"c{i}" for i in range(5)]
    listing = tmp_path / "cases.txt"
    listing.write_text("\n".join(ids) + "\n")
    argv, out, _ = setup_round(tmp_path, monkeypatch, ids, known_extra=("--max-cases", "3"),
                               cases_arg=[str(listing)])
    assert run_round.main(argv) == 0
    assert sorted(p.name for p in out.iterdir() if p.is_dir()) == ["c0", "c1", "c2"]


def test_missing_case_spec_fails_before_any_run(tmp_path, monkeypatch):
    argv, out, _ = setup_round(tmp_path, monkeypatch, ["c1"], cases_arg=["c1", "ghost"])
    with pytest.raises(SystemExit, match="ghost"):
        run_round.main(argv)
    assert not out.exists()


def test_jobs_above_the_cap_refused(tmp_path, monkeypatch):
    argv, _, _ = setup_round(tmp_path, monkeypatch, ["c1"], known_extra=("--jobs", str(run_round.MAX_JOBS + 1)))
    with pytest.raises(SystemExit, match="--jobs"):
        run_round.main(argv)


def test_validate_out_locations(tmp_path):
    main_root = (tmp_path / "main").resolve()
    other_worktree = (tmp_path / "wt").resolve()
    worktrees = [main_root, other_worktree]
    with pytest.raises(SystemExit, match="main checkout"):
        run_round.validate_out(tmp_path / "elsewhere" / "r1", main_root, worktrees)
    with pytest.raises(SystemExit, match="worktree"):
        run_round.validate_out(other_worktree / "work" / "r1", main_root, worktrees)
    existing = main_root / "work" / "r1"
    existing.mkdir(parents=True)
    with pytest.raises(SystemExit, match="already exists"):
        run_round.validate_out(existing, main_root, worktrees)
    run_round.validate_out(main_root / "work" / "r2", main_root, worktrees)  # accepted


def test_extra_options_must_be_pairs(tmp_path, monkeypatch):
    argv, _, _ = setup_round(tmp_path, monkeypatch, ["c1"], flags=("--policy",))
    with pytest.raises(SystemExit, match="pairs"):
        run_round.main(argv)



def test_worker_python_symlink_is_not_resolved(tmp_path):
    """A venv python is a symlink; the command must keep the venv path, not the base interpreter."""
    import argparse
    target = tmp_path / "base-python"
    target.write_text("")
    link = tmp_path / "venv" / "bin" / "python"
    link.parent.mkdir(parents=True)
    link.symlink_to(target)
    args = argparse.Namespace(binary=tmp_path / "bin", out=tmp_path / "out", inputs=tmp_path / "in",
                              worker_python=link, worker_source=tmp_path / "src", basis=None, extra=[])
    command = run_round.build_command(args, "case-1")
    assert command[command.index("--worker-python") + 1] == str(link)
