"""OS-contained ship CAD worker. No fallback to an unsandboxed executor.

The existing worker supervisor supplies process cleanup and resource limits.
Seatbelt adds file and network containment. Runtime libraries are read-only;
only the fresh task directory is writable. Linux uses Landlock and seccomp.
"""
from __future__ import annotations

import argparse
import json
import os
import stat
import sys
from dataclasses import asdict
from pathlib import Path

from .isolation import SANDBOX_MODEL_LIMITS, safe_worker_environment, supervise_process


def sandbox_profile(task: Path, runtime_paths: list[Path], executable: Path | None = None) -> str:
    """Seatbelt profile: the task directory is read-only, only task/work is writable.

    The host keeps its input, profile and receipt outside task/work, so the
    worker cannot replace them or plant a symlink where the host writes.
    """
    def quoted(path):
        value = str(path.resolve())
        if any(c in value for c in ('\n', '\r', '\0')):
            raise ValueError('unsafe sandbox path')
        return json.dumps(value)
    paths = [p.resolve() for p in runtime_paths]
    if any(p == Path('/') or p == Path.home() for p in paths):
        raise ValueError('runtime access is too broad')
    executable = Path(executable or sys.executable)
    # A virtualenv python is a symlink; exec needs both the link and its target.
    executables = {str(executable.absolute()), str(executable.resolve())}
    # A python.org framework build's bin/python3.x is a launcher that execs the
    # real interpreter inside the framework's Python.app. Allow only that binary.
    framework_python = executable.resolve().parent.parent / 'Resources/Python.app/Contents/MacOS/Python'
    if framework_python.is_file():
        executables.add(str(framework_python))
    executables = sorted(executables)
    execs = ' '.join(f'(literal {json.dumps(e)})' for e in executables)
    reads = '\n'.join(f'(allow file-read* (subpath {quoted(p)}))' for p in paths)
    # Path lookup needs the metadata of each parent directory, not their contents.
    parents = sorted({str(parent) for p in [*paths, task.resolve()] for parent in p.parents})
    metadata = ' '.join(f'(literal {json.dumps(p)})' for p in parents)
    return f'''(version 1)
(deny default)
(allow process-exec {execs})
(allow signal (target self))
(allow sysctl-read)
(allow file-read-metadata {metadata})
; dyld must read the root directory itself, not its descendants.
(allow file-read* (literal "/"))
(allow file-read* (subpath "/System/Library") (subpath "/usr/lib") (subpath "/usr/share")
  (subpath "/private/var/db/timezone") (literal "/private/etc/localtime")
  (literal "/dev/null") (literal "/dev/urandom") (literal "/dev/random"))
(allow file-write* (literal "/dev/null"))
{reads}
(allow file-read* (subpath {quoted(task)}))
(allow file-read* file-write* (subpath {quoted(task / 'work')}))
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


def linux_runtime_paths() -> list[Path]:
    """Grant library/source trees, never a whole system or user prefix."""
    import sysconfig
    paths = {Path(__file__).resolve().parent.parent}
    for name in ('stdlib', 'platstdlib', 'purelib', 'platlib'):
        value = sysconfig.get_path(name)
        if value:
            paths.add(Path(value))
    # Loader dependencies and distro extension modules. /etc is deliberately
    # absent: hostname, resolver, credentials and other host configuration stay private.
    paths.update(Path(value) for value in ('/lib', '/lib64', '/usr/lib', '/usr/lib64',
                                          '/usr/local/lib', '/etc/ld.so.cache',
                                          '/etc/localtime', '/dev/null', '/dev/urandom', '/dev/random'))
    for prefix in (sys.prefix, sys.base_prefix):
        paths.add(Path(prefix)/'pyvenv.cfg')
    return sorted({path.resolve() for path in paths if path.exists()})


def linux_launcher() -> Path:
    configured = os.environ.get('MARINAFRAME_SANDBOX_LAUNCHER')
    if configured:
        launcher = Path(configured).absolute()
    else:
        # Packaged deployments put both executables together. Source builds can
        # point at their Cargo output explicitly; never search an inherited PATH.
        launcher = Path(sys.executable).absolute().parent/'marinaframe-sandbox'
    if not launcher.is_file() or not os.access(launcher, os.X_OK):
        raise RuntimeError('Linux sandbox launcher is missing; set MARINAFRAME_SANDBOX_LAUNCHER to the built marinaframe-sandbox. No unsafe fallback.')
    return launcher


def require_sandbox() -> None:
    if sys.platform == 'linux':
        linux_launcher()
    elif sys.platform != 'darwin' or not Path('/usr/bin/sandbox-exec').is_file():
        raise RuntimeError('ship CAD requires the supported OS sandbox; no unsafe fallback')


def sandbox_command(task: Path, limits) -> tuple[list[str], str]:
    arguments = [sys.executable, '-m', 'vessel_reconstruction.ship_cad_worker',
                 '--task', str(task), '--limits', json.dumps(asdict(limits)),
                 '--parent', str(os.getpid())]
    if sys.platform == 'linux':
        config = task/'worker-linux.json'
        config.write_text(json.dumps({'task': str(task), 'work': str(task/'work'),
                                     'runtime_paths': [str(p) for p in linux_runtime_paths()],
                                     'executable': sys.executable, 'limits': asdict(limits),
                                     'parent_pid': os.getpid()}))
        return ([str(linux_launcher()), '--config', str(config), '--', *arguments],
                'linux-landlock-seccomp-deny-default')
    require_sandbox()
    profile = task/'worker.sb'
    profile.write_text(sandbox_profile(task, runtime_paths()))
    return ['/usr/bin/sandbox-exec', '-f', str(profile), *arguments], 'macos-seatbelt-deny-default'


MAX_RESULT_BYTES = 16 * 1024 * 1024  # provenance JSON; far above a normal report


def read_worker_json(root: Path, relative: Path) -> dict | None:
    """Read a worker-written JSON file without following any symlink below root."""
    directory = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in relative.parts[:-1]:
            try:
                inner = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
            except FileNotFoundError:
                return None
            os.close(directory)
            directory = inner
        try:
            # O_NONBLOCK: a planted FIFO must not block the open. It has no
            # effect on reads of the regular file required below.
            handle = os.open(relative.parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                             dir_fd=directory)
        except FileNotFoundError:
            return None
    finally:
        os.close(directory)
    with os.fdopen(handle, 'rb') as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise ValueError('worker result is not a regular file')
        data = stream.read(MAX_RESULT_BYTES + 1)
    if len(data) > MAX_RESULT_BYTES:
        raise ValueError('worker result is too large')
    return json.loads(data)


def run(program: dict, measurements: dict, task: Path, *, audit=None, limits=SANDBOX_MODEL_LIMITS,
        guesses: dict | None = None, detail: dict | None = None) -> dict:
    from .ship_cad import triage_program

    triage_program(program)  # Header strict; a bad component is reported, not fatal.
    require_sandbox()
    limits.validate()
    if task.exists():
        raise FileExistsError('Choose a fresh ship task directory')
    task.mkdir(parents=True)
    task = task.resolve()
    (task/'work').mkdir()
    (task/'input.json').write_text(json.dumps({'program': program, 'measurements': measurements, 'audit': audit,
                                               'guesses': guesses or {}, 'detail': detail}))
    command, sandbox = sandbox_command(task, limits)
    env = safe_worker_environment()
    env.update(HOME=str(task/'work'), TMPDIR=str(task/'work'), PYTHONDONTWRITEBYTECODE='1')
    # Keep all sandbox writes inside work, including standalone progress.
    env['MARINAFRAME_PROGRESS_PATH'] = str(task/'work'/'progress.json')
    env.setdefault('MARINAFRAME_PROGRESS_REQUEST', task.name)
    outcome = supervise_process(command, limits=limits, output_dir=task/'work', env=env,
                                sandboxed_model_code=True)
    # supervise_process has killed the worker group, so these files no longer change.
    outcome['result'] = (None if outcome['state'] in ('sandbox_safety_cap', 'stalled') else
                         read_worker_json(task/'work', Path('output/provenance.json')))
    outcome['sandbox'] = sandbox
    setup_failed = sys.platform == 'linux' and outcome.get('exit_code') == 125
    if setup_failed:
        outcome.update(error_code='sandbox_setup_failed',
                       error='Linux sandbox setup failed: Landlock ABI >=3, seccomp and hard limits are required; no unsafe fallback.',
                       result=None)
    (task/'worker-receipt.json').write_text(json.dumps(outcome, indent=2) + '\n')
    if setup_failed:
        raise RuntimeError(outcome['error'])
    return outcome


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--task', type=Path, required=True)
    parser.add_argument('--limits', required=True)
    parser.add_argument('--parent', type=int, required=True)
    args = parser.parse_args(argv)
    if sys.platform == 'linux':
        # The native launcher has already installed hard limits and parent-death
        # handling. Its seccomp policy forbids changing prctl settings afterward.
        if os.getppid() != args.parent:
            raise RuntimeError('Worker parent identity could not be established.')
    else:
        from .worker import apply_limits
        apply_limits(json.loads(args.limits), args.parent)
    from .ship_cad import execute
    data = json.loads((args.task/'input.json').read_text())
    execute(data['program'], data['measurements'], args.task/'work'/'output', audit=data.get('audit'),
            guesses=data.get('guesses'), detail=data.get('detail'))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
