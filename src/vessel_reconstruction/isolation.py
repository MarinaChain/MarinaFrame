"""Linux local worker lifecycle. Resource limits are not a hostile-code sandbox."""
from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import math
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import threading
import time
from typing import Callable
from uuid import uuid4


@dataclass(frozen=True)
class WorkerLimits:
    wall_seconds: float = 180
    cpu_seconds: int = 120
    memory_bytes: int = 4 * 1024**3
    file_bytes: int = 128 * 1024**2
    output_bytes: int = 256 * 1024**2
    open_files: int = 64
    termination_grace_seconds: float = 0.5

    def validate(self) -> None:
        for name, value in asdict(self).items():
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
                raise ValueError(f'{name} must be a positive finite number')
        if self.cpu_seconds != int(self.cpu_seconds) or self.open_files < 16:
            raise ValueError('Invalid CPU/open-file worker limit')


DEFAULT_LIMITS = WorkerLimits()


def safe_worker_environment() -> dict[str, str]:
    # Explicit allowlist: provider credentials and unrelated inherited secrets
    # must not enter OCR/native worker descendants.
    env = {key: os.environ[key] for key in ('PATH', 'LANG', 'LC_ALL', 'TZ', 'TESSDATA_PREFIX') if key in os.environ}
    env.update(PYTHONPATH=str(Path(__file__).resolve().parent.parent), PYTHONUNBUFFERED='1',
               OPENBLAS_NUM_THREADS='1', OMP_NUM_THREADS='1', OMP_THREAD_LIMIT='1', MKL_NUM_THREADS='1')
    return env


def _proc_path(pid: int) -> Path | None:
    """Map our PID namespace to procfs, including an outer-mounted /proc."""
    try:
        namespace = os.readlink('/proc/self/ns/pid')
    except OSError:
        return None
    def matches(candidate):
        try:
            if os.readlink(candidate / 'ns/pid') != namespace:
                return False
            for line in (candidate / 'status').read_text().splitlines():
                if line.startswith('NSpid:'):
                    return int(line.split()[-1]) == pid
            return int(candidate.name) == pid
        except (OSError, ValueError):
            return False
    direct = Path(f'/proc/{pid}')
    if matches(direct):
        return direct
    examined = 0
    for entry in os.scandir('/proc'):
        if entry.name.isdigit():
            examined += 1
            if examined > 16384:
                break
            candidate = Path(entry.path)
            if matches(candidate):
                return candidate
    return None


def process_identity(pid: int) -> dict | None:
    """Linux process birth identity prevents signalling a reused PID after restart."""
    try:
        directory = _proc_path(pid)
        if directory is None:
            return None
        fields = (directory / 'stat').read_text().rsplit(')', 1)[1].split()
        pgid = int(fields[2])
        for line in (directory / 'status').read_text().splitlines():
            if line.startswith('NSpgid:'):
                pgid = int(line.split()[-1])
        return {'pid': pid, 'pgid': pgid, 'start_ticks': int(fields[19])}
    except (OSError, ValueError, IndexError):
        return None


def kill_process_tree(identity: dict | None, grace_seconds: float = 0.5) -> bool:
    if not identity or identity.get('pid') == os.getpid() or identity.get('pgid') != identity.get('pid'):
        return False
    current = process_identity(int(identity['pid']))
    expected = {key: identity.get(key) for key in ('pid', 'pgid', 'start_ticks')}
    owned = current == expected
    if current is not None and not owned:
        return False
    if not owned and identity.get('token'):
        # On abrupt controller exit PDEATHSIG kills the worker, but an OCR
        # descendant can remain. Prove group ownership using a random inherited
        # marker plus uid/pgid before signalling that group. Never print environ.
        marker = ('MARINAFRAME_JOB_TOKEN=' + identity['token']).encode()
        examined = 0
        for entry in os.scandir('/proc'):
            if not entry.name.isdigit():
                continue
            examined += 1
            if examined > 16384:
                break
            try:
                if entry.stat().st_uid != os.getuid():
                    continue
                directory = Path(entry.path)
                if os.readlink(directory / 'ns/pid') != os.readlink('/proc/self/ns/pid'):
                    continue
                pgid = None
                for line in (directory / 'status').read_text().splitlines():
                    if line.startswith('NSpgid:'):
                        pgid = int(line.split()[-1])
                if pgid != identity['pgid']:
                    continue
                with (directory / 'environ').open('rb') as stream:
                    environment = stream.read(64 * 1024)
                if marker in environment.split(b'\0'):
                    owned = True; break
            except (OSError, ValueError):
                continue
    if not owned:
        return False
    for sig in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.killpg(identity['pgid'], sig)
        except ProcessLookupError:
            return True
        if sig == signal.SIGTERM:
            deadline = time.monotonic() + min(2.0, grace_seconds)
            while time.monotonic() < deadline:
                time.sleep(0.02)
    return True


def _tree_bytes(root: Path, *, stop_after: int) -> int:
    total = 0
    if root.is_symlink():
        return stop_after + 1
    if not root.exists():
        return 0
    count = 0
    for directory, dirs, files in os.walk(root, followlinks=False):
        dirs[:] = [name for name in dirs if not (Path(directory) / name).is_symlink()]
        for name in files:
            path = Path(directory) / name
            count += 1
            if count > 4096:
                return stop_after + 1
            try:
                if not path.is_symlink():
                    total += path.stat().st_size
            except FileNotFoundError:
                continue
            if total > stop_after:
                return total
    return total


def _output_bytes(output: Path, maximum: int) -> int:
    total = _tree_bytes(output, stop_after=maximum)
    prefix = f'.{output.name}.staging-'
    for index, stage in enumerate(output.parent.iterdir()):
        if index >= 4096:
            return maximum + 1
        if not stage.name.startswith(prefix):
            continue
        token = stage.name[len(prefix):]
        if len(token) != 32 or any(char not in '0123456789abcdef' for char in token):
            continue
        total += _tree_bytes(stage, stop_after=maximum)
        if total > maximum:
            break
    return total


def supervise_process(command: list[str], *, limits: WorkerLimits = DEFAULT_LIMITS,
                      cancel_event: threading.Event | None = None,
                      stop_event: threading.Event | None = None,
                      on_start: Callable[[dict], None] | None = None,
                      output_dir: Path | None = None, env: dict | None = None) -> dict:
    """Supervise a trusted argv. Child must apply POSIX limits before native work.

    Public web requests never provide commands. This factored supervisor permits
    small controlled hang/crash regressions without running an expensive CAD job.
    """
    limits.validate()
    started = time.monotonic()
    child_environment = dict(env if env is not None else safe_worker_environment())
    child_environment['MARINAFRAME_JOB_TOKEN'] = uuid4().hex
    process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL, start_new_session=True,
                               env=child_environment, close_fds=True)
    identity = process_identity(process.pid)
    if identity:
        identity['token'] = child_environment['MARINAFRAME_JOB_TOKEN']
    state = 'exited'
    try:
        if on_start:
            on_start(identity or {'pid': process.pid, 'pgid': process.pid, 'start_ticks': -1})
        while True:
            # Do not reap before killing the process group: OCR descendants may
            # outlive an exited worker and the leader's zombie retains identity.
            exited = os.waitid(os.P_PID, process.pid, os.WEXITED | os.WNOHANG | os.WNOWAIT)
            if exited is not None:
                break
            if cancel_event is not None and cancel_event.is_set():
                state = 'cancelled'; break
            if stop_event is not None and stop_event.is_set():
                state = 'interrupted'; break
            if time.monotonic() - started >= limits.wall_seconds:
                state = 'timed_out'; break
            if output_dir is not None and _output_bytes(output_dir, limits.output_bytes) > limits.output_bytes:
                state = 'resource_limited'; break
            time.sleep(0.05)
    except BaseException:
        kill_process_tree(identity, limits.termination_grace_seconds)
        process.wait(timeout=3)
        raise
    kill_process_tree(identity, 0.02 if state == 'exited' else limits.termination_grace_seconds)
    returncode = process.wait(timeout=3)
    if output_dir is not None and _output_bytes(output_dir, limits.output_bytes) > limits.output_bytes:
        state = 'resource_limited'
    if state == 'exited' and returncode in (-signal.SIGXCPU, -signal.SIGXFSZ):
        state = 'resource_limited'
    return {'state': state, 'exit_code': returncode, 'elapsed_seconds': round(time.monotonic() - started, 4),
            'process': identity, 'limits': asdict(limits)}


def recover_worker_output(output: Path, *, status: str = 'interrupted') -> dict:
    try:
        from .pipeline import recover_interrupted_run
        return recover_interrupted_run(output, status=status)
    except (ImportError, OSError, ValueError, RuntimeError):
        return {'recovered': False, 'status': 'interrupted'}


def run_isolated(spec_path: str | Path, output_dir: str | Path, *, export_cad: bool = True,
                 limits: WorkerLimits = DEFAULT_LIMITS, cancel_event: threading.Event | None = None,
                 stop_event: threading.Event | None = None,
                 on_start: Callable[[dict], None] | None = None) -> dict:
    """Run/recover one bounded job; return state, result (verified only), telemetry.

    Terminal states: succeeded, blocked, failed, timed_out, resource_limited,
    cancelled, interrupted. A published result remains review_required/blocked.
    Existing output directories are never overwritten.
    """
    if sys.platform != 'linux':
        raise RuntimeError('The isolated local worker profile currently supports Linux only.')
    limits.validate()
    spec, output = Path(spec_path).resolve(), Path(output_dir).resolve()
    if output.exists():
        raise FileExistsError('Output already exists; choose a new run directory.')
    output.parent.mkdir(parents=True, exist_ok=True)
    receipt = output.parent / f'.worker-{uuid4().hex}.json'
    command = [sys.executable, '-m', 'vessel_reconstruction.worker', '--spec', str(spec), '--out', str(output),
               '--receipt', str(receipt), '--limits', json.dumps(asdict(limits)), '--parent', str(os.getpid())]
    if not export_cad:
        command.append('--no-cad')
    try:
        outcome = supervise_process(command, limits=limits, cancel_event=cancel_event, stop_event=stop_event,
                                    on_start=on_start, output_dir=output)
        info = {}
        if receipt.is_file() and receipt.stat().st_size <= 64 * 1024:
            try:
                info = json.loads(receipt.read_text())
            except (OSError, ValueError):
                pass
        outcome['resources'] = info.get('resources', {})
        outcome['result'] = None
        worker_state = outcome['state']
        if worker_state == 'exited' and outcome['exit_code'] != 0:
            outcome.update(state='failed', error_code=info.get('error_code', 'worker_crashed'))
        # A completed durable transaction can race cancellation/worker exit.
        # Reconcile only a fully verified, unreserved record. Never pretend a
        # cancellation withdrew geometry that was committed before it arrived.
        from .pipeline import verify_run
        if output.is_dir() and _output_bytes(output, limits.output_bytes) <= limits.output_bytes:
            try:
                verified = verify_run(output)
                record_path = output / 'result.json'
                if verified.get('valid') and record_path.stat().st_size <= 32 * 1024**2:
                    result = json.loads(record_path.read_text())
                    outcome['result'] = result
                    outcome['state'] = 'succeeded' if result['status'] == 'review_required' else result['status']
                    if worker_state != 'exited' or outcome['exit_code'] != 0:
                        outcome.update(publication_reconciled=True, worker_state=worker_state)
                    outcome.pop('error_code', None)
                elif outcome['state'] == 'exited':
                    outcome.update(state='failed', error_code='invalid_published_evidence')
            except (OSError, ValueError, KeyError, TypeError):
                outcome.update(state='failed', error_code='invalid_published_evidence')
        elif outcome['state'] == 'exited':
            outcome.update(state='failed', error_code='missing_published_evidence')
        if outcome['result'] is None:
            outcome.setdefault('error_code', outcome['state'])
            # Worker-owned output exceeding its aggregate budget must not remain
            # publicly discoverable even if it exited between polling intervals.
            if output.exists() and _output_bytes(output, limits.output_bytes) > limits.output_bytes:
                quarantine = output.parent / f'.{output.name}.resource-exceeded-{uuid4().hex}'
                try:
                    output.rename(quarantine)
                    for name in ('model.step', 'model.stl', 'mesh.json', 'cad_sections.json', 'result.json', 'manifest.json'):
                        (quarantine / name).unlink(missing_ok=True)
                    outcome['quarantine'] = quarantine.name
                except OSError:
                    outcome['error_code'] = 'resource_quarantine_failed'
            recovered_status = 'cancelled' if outcome['state'] == 'cancelled' else 'failed' if outcome['state'] == 'failed' else 'interrupted'
            outcome['recovery'] = recover_worker_output(output, status=recovered_status)
            if outcome['recovery'].get('published'):
                try:
                    if verify_run(output).get('valid'):
                        outcome['result'] = json.loads((output / 'result.json').read_text())
                except (OSError, ValueError):
                    pass
        return outcome
    finally:
        receipt.unlink(missing_ok=True)
