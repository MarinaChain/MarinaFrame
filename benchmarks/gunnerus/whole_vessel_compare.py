"""Compare two whole-vessel build folders: identical outputs except timing fields and paths.

Used to show that a speed change keeps the outputs (docs/plans/2026-11-11-build-speed.md)::

    python -m benchmarks.gunnerus.whole_vessel_compare BEFORE AFTER

Exit status 1 when a file differs or exists in only one folder.

STEP: bytes of the DATA section (the HEADER holds a timestamp). GLB, PNG, BREP: whole bytes.
JSON: parsed, with timing keys removed and the run folder path replaced.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

TIMING_KEYS = {'seconds', 'hull_seconds', 'elapsed_s', 'elapsed_seconds', 'wall_seconds', 'cpu_seconds',
               'started_at', 'finished_at', 'max_rss_bytes', 'peak_rss_bytes', 'duration_s', 'process'}
SKIP_NAMES = {'worker-receipt.json', 'progress.json', 'worker.sb'}


def step_body(path: Path) -> bytes:
    data = path.read_bytes()
    return data[data.index(b'DATA;'):]


def clean(value, roots):
    if isinstance(value, dict):
        return {k: clean(v, roots) for k, v in value.items() if k not in TIMING_KEYS}
    if isinstance(value, list):
        return [clean(v, roots) for v in value]
    if isinstance(value, str):
        for root, token in roots:
            value = value.replace(root, token)
    return value


def digest(path: Path, roots) -> str:
    if path.suffix == '.step':
        data = step_body(path)
    elif path.suffix == '.json':
        try:
            data = json.dumps(clean(json.loads(path.read_text()), roots), sort_keys=True).encode()
        except ValueError:
            data = path.read_bytes()
    else:
        data = path.read_bytes()
    return hashlib.sha256(data).hexdigest()


def files(root: Path) -> dict:
    return {p.relative_to(root): p for p in sorted(root.rglob('*'))
            if p.is_file() and p.name not in SKIP_NAMES and '.cache' not in p.parts and not p.name.endswith('.log')
            and not p.name.endswith('-timings.json') and not p.name.endswith('.prof')}


def differences(before: Path, after: Path) -> tuple[int, list[str]]:
    """(files compared, one line per file that differs or exists in one folder only)."""
    before, after = before.resolve(), after.resolve()
    a, b = files(before), files(after)
    differ = []
    for rel in sorted(set(a) | set(b)):
        if rel not in a or rel not in b:
            differ.append(f'{rel}: only in {"before" if rel in a else "after"}')
            continue
        if digest(a[rel], [(str(before), 'RUN')]) != digest(b[rel], [(str(after), 'RUN')]):
            differ.append(f'{rel}: differs')
    return len(set(a) | set(b)), differ


def main() -> None:
    compared, differ = differences(Path(sys.argv[1]), Path(sys.argv[2]))
    print(f'{compared} files compared, {len(differ)} differ')
    for line in differ:
        print('  ' + line)
    raise SystemExit(1 if differ else 0)


if __name__ == '__main__':
    main()
