"""Tests for scripts/round_digest.py, using small synthetic event folders."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "round_digest.py"
spec = importlib.util.spec_from_file_location("round_digest", SCRIPT)
round_digest = importlib.util.module_from_spec(spec)
spec.loader.exec_module(round_digest)


def decision(tool, args=None, reason="r"):
    return ("decision", {"actor": "live_model", "decision": {"tool": tool, "arguments": args or {}, "reason": reason}})


def worker(operation, status="ok", code=None, message=None, candidate=None):
    result = {"status": status, "error_code": code, "message": message}
    if candidate is not None:
        result["candidate"] = candidate
    return ("worker_result", {"operation": operation, "response": {"result": result}})


def make_case(root: Path, name: str, events, stdout=None, result=None) -> Path:
    case = root / name
    events_dir = case / "task" / "events"
    events_dir.mkdir(parents=True)
    for number, (kind, payload) in enumerate(events, start=1):
        (events_dir / f"{number:08d}.json").write_text(json.dumps({"sequence": number, "kind": kind, "payload": payload}))
    if stdout is not None:
        (case / "stdout.log").write_text(json.dumps(stdout))
    if result is not None:
        (case / "result.json").write_text(json.dumps(result))
    return case


def stuck_events():
    return [
        decision("read_region", {"id": "s01"}),
        worker("read_region"),
        decision("read_region", {"id": "s01"}),
        worker("read_region"),
        decision("read_region", {"id": "s01"}, reason="last one"),
        ("task_terminated", {"reason": "repeated_identical_action_refusals"}),
    ]


def test_compress_tools():
    assert round_digest.compress_tools(["a", "a", "a", "b", "a"]) == "a x3 > b > a"
    assert round_digest.compress_tools([]) == "(none)"


def test_first_repeated_action_is_blocker(tmp_path):
    case = make_case(tmp_path, "c1", stuck_events(), stdout={"status": "no_progress"})
    digest = round_digest.digest_case(case)
    assert digest["reason"] == "repeated_identical_action_refusals"
    assert digest["decisions"] == 3
    assert digest["tool_sequence"] == "read_region x3"
    assert digest["first_blocker"]["code"] == "repeated_identical_action"
    assert digest["draft"] == "no draft"
    assert digest["last_reasons"][-1] == "last one"


def test_failed_worker_result_beats_later_repeat(tmp_path):
    events = [
        decision("inspect_source"),
        worker("inspect_source", status="failed", code="inspection_worker_failed", message="boom"),
        decision("inspect_source"),
    ]
    digest = round_digest.digest_case(make_case(tmp_path, "c", events))
    assert digest["first_blocker"]["code"] == "inspection_worker_failed"
    assert digest["first_blocker"]["message"] == "boom"


def test_draft_requests_and_cost(tmp_path):
    events = [decision("build_draft"), worker("build_draft", status="built", candidate={"valid": True})]
    stdout = {"status": "completed", "counters": {"requests_completed": 7, "builds": 1}}
    case = make_case(tmp_path, "c", events, stdout=stdout, result={"list_cost_usd": 0.5})
    digest = round_digest.digest_case(case)
    assert digest["draft"] == "valid draft"
    assert digest["requests"] == 7
    assert digest["list_cost_usd"] == 0.5
    assert digest["first_blocker"] is None


def test_blocked_build_is_not_a_draft_and_receipt_cost_is_summed(tmp_path):
    events = [decision("build_draft"), worker("build_draft", status="blocked", candidate={"valid": False})]
    case = make_case(tmp_path, "c", events, stdout={"status": "no_progress"})
    receipts = case / "task" / "receipts"
    receipts.mkdir()
    for index, cost in enumerate((0.25, 0.5)):
        (receipts / f"request-{index}.json").write_text(json.dumps({"usage": {"list_cost": cost}}))
    digest = round_digest.digest_case(case)
    assert digest["draft"] == "build attempted 1x, none valid"
    assert digest["list_cost_usd"] == 0.75


def test_missing_files_do_not_crash(tmp_path):
    (tmp_path / "empty").mkdir()
    digest = round_digest.digest_case(tmp_path / "empty")
    assert digest["status"] == "unknown"
    assert digest["decisions"] == 0


def test_round_summary_and_early_stop(tmp_path):
    cases = [
        make_case(tmp_path, f"c{i}", stuck_events(), stdout={"status": "no_progress"}) for i in range(3)
    ]
    digests = [round_digest.digest_case(c) for c in cases]
    summary = round_digest.summarize(digests)
    assert summary["termination_reasons"] == [("repeated_identical_action_refusals", 3)]
    assert summary["tool_totals"] == [("read_region", 9)]
    assert "first 3 cases fail the same way" in summary["early_stop_hint"]


def test_cli_markdown_and_json(tmp_path, capsys):
    case = make_case(tmp_path, "c1", stuck_events(), stdout={"status": "no_progress"})
    assert round_digest.main([str(case)]) == 0
    assert "## c1" in capsys.readouterr().out
    assert round_digest.main([str(case), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["cases"][0]["case"] == "c1"
