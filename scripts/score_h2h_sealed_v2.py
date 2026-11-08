"""Score completed frozen arms with the existing independent factory scorer."""
from __future__ import annotations

import argparse
import fcntl
import json
import subprocess
import os
import sys
import tempfile
from pathlib import Path

# The main checkout (not a worktree) holds the ignored campaign data in work/.
MAIN = Path(subprocess.run(['git', 'rev-parse', '--path-format=absolute', '--git-common-dir'],
                           cwd=Path(__file__).parent, check=True, capture_output=True, text=True).stdout.strip()).parent
ROOT = MAIN / 'work/h2h-sealed-v2'
SNAPSHOT = ROOT / 'snapshot'
sys.path.insert(0, str(SNAPSHOT))
from benchmarks.factory import report  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--arm', choices=['abstain', 'draft', 'llm'], required=True)
    args = parser.parse_args()
    assert (ROOT / f'{args.arm}-finished.json').exists(), 'Arm is not complete; scoring forbidden'
    case_dirs = sorted((ROOT / 'runs' / args.arm).iterdir())
    assert len(case_dirs) == 288
    assert all((p / 'result.json').exists() for p in case_dirs)
    lock_path = Path(tempfile.gettempdir()) / f'marinaframe-native-admission-{os.geteuid()}.lock'
    with lock_path.open('a+b') as lock:
        for index, case_dir in enumerate(case_dirs, 1):
            fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                report._score_one((MAIN / 'work/factory-sealed-v2', args.arm, case_dir))
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)
            if index % 24 == 0:
                print(f'{args.arm}: scored {index}/288', flush=True)
    (ROOT / f'{args.arm}-scored.json').write_text(json.dumps({'cases': 288, 'scorer': 'frozen benchmarks.factory.report._score_one',
                                                          'native_lock': str(lock_path)}, indent=2) + '\n')


if __name__ == '__main__':
    main()
