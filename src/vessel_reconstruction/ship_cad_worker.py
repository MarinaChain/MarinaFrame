"""OS-contained ship CAD worker. No fallback to an unsandboxed executor.

The existing worker supervisor supplies process cleanup and resource limits.
Seatbelt adds file and network containment. Runtime libraries are read-only;
only the fresh task directory is writable. Linux requires a future equivalent.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
import json
import os
from pathlib import Path
import sys

from .isolation import DEFAULT_LIMITS, safe_worker_environment, supervise_process


def sandbox_profile(task: Path, runtime_paths: list[Path]) -> str:
    def quoted(path):
        value = str(path.resolve())
        if any(c in value for c in ('\n', '\r', '\0')):
            raise ValueError('unsafe sandbox path')
        return json.dumps(value)
    paths = [p.resolve() for p in runtime_paths]
    if any(p == Path('/') or p == Path.home() for p in paths):
        raise ValueError('runtime access is too broad')
    reads = '\n'.join(f'(allow file-read* (subpath {quoted(p)}))' for p in paths)
    return f'''(version 1)
(deny default)
(allow process* signal)
(allow sysctl-read mach-lookup)
(allow file-read-metadata)
; dyld must read the root directory itself, not its descendants.
(allow file-read* (literal "/"))
(allow file-read* (subpath "/System/Library") (subpath "/usr/lib") (subpath "/usr/share")
  (literal "/dev/null") (literal "/dev/urandom") (literal "/dev/random"))
(allow file-write* (literal "/dev/null"))
{reads}
(allow file-read* file-write* (subpath {quoted(task)}))
'''


def runtime_paths() -> list[Path]:
    # Resolve symlinked virtualenv Python and compiled extension dependencies.
    paths = {Path(sys.base_prefix), Path(sys.prefix), Path(__file__).resolve().parent.parent,
             Path(sys.executable).resolve().parent.parent}
    homebrew = Path('/opt/homebrew/Cellar')
    if homebrew.exists():
        paths.add(homebrew)
        paths.add(Path('/opt/homebrew/opt'))
    return sorted(paths)


def run(program: dict, measurements: dict, task: Path, *, audit=None, limits=DEFAULT_LIMITS) -> dict:
    from .ship_cad import validate_program

    validate_program(program)
    if sys.platform != 'darwin' or not Path('/usr/bin/sandbox-exec').is_file():
        raise RuntimeError('ship CAD requires the supported OS sandbox; no unsafe fallback')
    if task.exists():
        raise FileExistsError('Choose a fresh ship task directory')
    task.mkdir(parents=True)
    task = task.resolve()
    (task/'input.json').write_text(json.dumps({'program': program, 'measurements': measurements, 'audit':audit}))
    profile = task/'worker.sb'
    profile.write_text(sandbox_profile(task, runtime_paths()))
    env = safe_worker_environment()
    env.update(HOME=str(task), TMPDIR=str(task), PYTHONDONTWRITEBYTECODE='1')
    command = ['/usr/bin/sandbox-exec', '-f', str(profile), sys.executable, '-m',
               'vessel_reconstruction.ship_cad_worker', '--task', str(task),
               '--limits', json.dumps(asdict(limits)), '--parent', str(os.getpid())]
    outcome = supervise_process(command, limits=limits, output_dir=task, env=env)
    result = task/'output/provenance.json'
    outcome['result'] = json.loads(result.read_text()) if result.is_file() else None
    outcome['sandbox'] = 'macos-seatbelt-deny-default'
    (task/'worker-receipt.json').write_text(json.dumps(outcome, indent=2) + '\n')
    return outcome


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--task', type=Path, required=True)
    parser.add_argument('--limits', required=True)
    parser.add_argument('--parent', type=int, required=True)
    args = parser.parse_args(argv)
    from .worker import apply_limits
    apply_limits(json.loads(args.limits), args.parent)
    from .ship_cad import execute
    data = json.loads((args.task/'input.json').read_text())
    execute(data['program'], data['measurements'], args.task/'output', audit=data.get('audit'))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
