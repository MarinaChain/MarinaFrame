"""Development evidence must remain in this worktree's ignored work folder."""
import importlib.util
from pathlib import Path

import pytest

MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "measure_view_detection.py"
spec = importlib.util.spec_from_file_location("measure_view_detection", MODULE_PATH)
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


def test_output_rejects_unrelated_work_directory(tmp_path):
    with pytest.raises(ValueError, match="local work"):
        runner.check_output_directory(tmp_path / "work" / "evidence")


def test_output_accepts_local_ignored_work():
    target = MODULE_PATH.parents[1] / "work" / "view-detection" / "tests"
    assert runner.check_output_directory(target) == target.resolve()
