"""Check measurement accounting using a tiny fake Make, never a Rust build."""

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/measure_build_cache.py"


@pytest.mark.parametrize("exit_code,runs", [(0, 2), (7, 1)])
def test_measurement_records_status_disk_and_lock_messages(tmp_path, exit_code, runs):
    tools = tmp_path / "bin"
    tools.mkdir()
    make = tools / "make"
    make.write_text(
        "#!/bin/sh\n"
        'mkdir -p "$CARGO_TARGET_DIR"\n'
        'printf artifact > "$CARGO_TARGET_DIR/artifact"\n'
        'printf "Blocking waiting for file lock on build directory\\n"\n'
        f"exit {exit_code}\n")
    make.chmod(0o755)
    output = tmp_path / "measurements"
    target = tmp_path / "target"
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--target", str(target), "--out", str(output),
         "--python", sys.executable],
        env={**os.environ, "PATH": str(tools) + os.pathsep + os.environ["PATH"]},
        capture_output=True, text=True)
    assert result.returncode == exit_code
    data = json.loads((output / "measurements.json").read_text())
    assert data["target"] == str(target.resolve())
    assert len(data["runs"]) == runs
    assert data["runs"][0]["target_kib_before"] == 0
    for row in data["runs"]:
        assert row["exit_code"] == exit_code
        assert row["target_kib_after"] > 0
        assert row["elapsed_seconds"] >= 0
        assert row["lock_wait_messages"] == 1
        assert Path(row["log"]).read_text().startswith("Blocking waiting")
