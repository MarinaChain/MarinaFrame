"""Evaluation must keep controller failures and pre-build model choices."""
import json

from PIL import Image

from benchmarks.investigation.arms import summarize


def test_summary_keeps_a_run_that_failed_before_domain_initialization(tmp_path):
    inputs = tmp_path / "input"
    inputs.mkdir()
    Image.new("RGB", (20, 20), "white").save(inputs / "drawing.png")
    (inputs / "spec.json").write_text(json.dumps({"sections": [{"id": "s0"}]}))
    run = tmp_path / "run"
    run.mkdir()
    (run / "arm_record.json").write_text(json.dumps({"arm": "llm", "exit": 2,
                                                   "wall_seconds": 1.2, "commit": "test"}))
    (run / "controller_stdout.json").write_text("")
    result = summarize(run, inputs, None, None)
    assert result["status"] == "cli_error"
    assert result["exit"] == 2
    assert result["sections_with_line"] == 0
    assert result["sections_without_line"] == 1
    assert result["prompt_tokens"] == 0
    assert result["domain_state_missing"] is True
