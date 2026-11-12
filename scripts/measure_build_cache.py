"""Measure quick-tier elapsed time and target disk usage without a time limit."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import time


def disk_kib(path: Path) -> int:
    if not path.exists():
        return 0
    result = subprocess.run(["du", "-sk", str(path)], check=True, capture_output=True, text=True)
    return int(result.stdout.split()[0])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--python", required=True)
    parser.add_argument("--runs", type=int, default=2)
    args = parser.parse_args()
    if args.runs < 1:
        parser.error("--runs must be positive")
    args.out.mkdir(parents=True, exist_ok=True)
    target = args.target.resolve()
    environment = {**os.environ, "CARGO_TARGET_DIR": str(target),
                   "MARINAFRAME_TEST_PYTHON": args.python}
    measurements = []
    for index in range(1, args.runs + 1):
        log_path = args.out / f"run-{index}.log"
        before = disk_kib(target)
        started = time.monotonic()
        with log_path.open("w") as log:
            result = subprocess.run(["make", "test-quick", f"PY={args.python}"],
                                    env=environment, stdout=log, stderr=subprocess.STDOUT)
        row = {"run": index, "elapsed_seconds": round(time.monotonic() - started, 3),
               "exit_code": result.returncode, "target_kib_before": before,
               "target_kib_after": disk_kib(target),
               "lock_wait_messages": log_path.read_text().count("Blocking waiting for file lock"),
               "log": str(log_path)}
        measurements.append(row)
        (args.out / "measurements.json").write_text(json.dumps(
            {"target": str(target), "runs": measurements}, indent=2) + "\n")
        print(json.dumps(row), flush=True)
        if result.returncode:
            return result.returncode
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
