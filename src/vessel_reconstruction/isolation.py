"""Linux/macOS local worker lifecycle. Resource limits are not a hostile-code sandbox."""
from __future__ import annotations

from dataclasses import asdict, dataclass
import ctypes
import json
import logging
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
from . import progress


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

# Security backstop for sandboxed model code, not a laptop speed limit. Even
# fabricated progress and repeated waiting cannot extend a child beyond four hours.
# Own-code CAD workers supervised by Rust retain no default absolute wall limit.
SANDBOX_MODEL_WALL_SECONDS = 4 * 60 * 60
# SIGKILL delivery can race group exit on macOS. Retry briefly, keeping the
# leader unreaped until no live group member remains; never infer that from the leader alone.
SANDBOX_KILL_ATTEMPTS = 5
SANDBOX_KILL_RETRY_SECONDS = 0.02


def safe_worker_environment() -> dict[str, str]:
    # Explicit allowlist: provider credentials and unrelated inherited secrets
    # must not enter native worker descendants.
    # MARINAFRAME_HULL_FAIRING is a build setting (fairing.SETTING), not a secret.
    env = {key: os.environ[key] for key in ('PATH', 'LANG', 'LC_ALL', 'TZ', 'MARINAFRAME_HULL_FAIRING',
           'MARINAFRAME_PROGRESS_PATH', 'MARINAFRAME_PROGRESS_REQUEST')
           if key in os.environ}
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


def _darwin_process_identity(pid: int) -> dict | None:
    """macOS has no procfs. ps reports the group and start time, zombies included.

    The start time has one-second resolution; it serves the same PID-reuse
    check as the Linux start_ticks value, compared only on the same host.
    """
    try:
        result = subprocess.run(['/bin/ps', '-o', 'pgid=', '-o', 'lstart=', '-p', str(pid)],
                                capture_output=True, text=True, env={'LC_ALL': 'C'}, timeout=5)
        pgid_text, start_text = result.stdout.strip().split(None, 1)
        started = time.mktime(time.strptime(start_text.strip(), '%a %b %d %H:%M:%S %Y'))
        return {'pid': pid, 'pgid': int(pgid_text), 'start_ticks': int(started)}
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def _darwin_group_has_live_member(pgid: int) -> bool:
    """Report whether any non-zombie process is in the group (fails safe to True)."""
    try:
        result = subprocess.run(['/bin/ps', '-A', '-o', 'pgid=', '-o', 'stat='],
                                capture_output=True, text=True, env={'LC_ALL': 'C'}, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return True
    if result.returncode != 0:
        return True
    for line in result.stdout.splitlines():
        fields = line.split()
        if len(fields) == 2 and fields[0] == str(pgid) and not fields[1].startswith('Z'):
            return True
    return False


def _darwin_group_member_has_token(pgid: int, token: str) -> bool:
    """macOS form of the Linux environ scan: ps -E shows a same-user process's
    environment. Require our uid, the expected group and the exact marker."""
    marker = 'MARINAFRAME_JOB_TOKEN=' + token
    try:
        result = subprocess.run(['/bin/ps', '-A', '-E', '-ww', '-o', 'uid=', '-o', 'pgid=', '-o', 'command='],
                                capture_output=True, text=True, env={'LC_ALL': 'C'}, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return False
    for line in result.stdout.splitlines():
        fields = line.split(None, 2)
        if (len(fields) == 3 and fields[0] == str(os.getuid()) and fields[1] == str(pgid)
                and marker in fields[2].split()):
            return True
    return False


def process_identity(pid: int) -> dict | None:
    """Process birth identity prevents signalling a reused PID after restart."""
    if sys.platform == 'darwin':
        return _darwin_process_identity(pid)
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
    if not owned and identity.get('token') and sys.platform == 'darwin':
        owned = _darwin_group_member_has_token(identity['pgid'], identity['token'])
    if not owned and identity.get('token') and sys.platform == 'linux':
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
        except PermissionError:
            # macOS returns EPERM when the group holds only an unreaped zombie
            # leader. The group is already proven ours, so treat it as gone
            # only when no live member remains.
            if sys.platform == 'darwin' and not _darwin_group_has_live_member(identity['pgid']):
                return True
            raise
        if sig == signal.SIGTERM:
            deadline = time.monotonic() + min(2.0, grace_seconds)
            while time.monotonic() < deadline:
                time.sleep(0.02)
    return True


# <sys/wait.h> values on macOS, where Python does not expose os.waitid.
_P_PID_DARWIN = 1
_WNOHANG_DARWIN = 0x1
_WEXITED_DARWIN = 0x4
_WNOWAIT_DARWIN = 0x20
_SIGINFO_PID_OFFSET_DARWIN = 12  # after si_signo, si_errno and si_code (int each)


def child_has_exited(pid: int) -> bool:
    """Report whether a child exited without reaping it (its zombie keeps the PID)."""
    if hasattr(os, 'waitid'):
        return os.waitid(os.P_PID, pid, os.WEXITED | os.WNOHANG | os.WNOWAIT) is not None
    libc = ctypes.CDLL(None, use_errno=True)
    info = ctypes.create_string_buffer(128)  # siginfo_t is 104 bytes on macOS
    flags = _WEXITED_DARWIN | _WNOHANG_DARWIN | _WNOWAIT_DARWIN
    if libc.waitid(_P_PID_DARWIN, ctypes.c_uint(pid), info, flags) != 0:
        raise OSError(ctypes.get_errno(), 'waitid failed')
    offset = _SIGINFO_PID_OFFSET_DARWIN
    return int.from_bytes(info.raw[offset:offset + 4], sys.byteorder, signed=True) != 0


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
                      output_dir: Path | None = None, env: dict | None = None,
                      sandboxed_model_code: bool = False) -> dict:
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
    controller_supervised = bool(os.environ.get('MARINAFRAME_PROGRESS_PATH'))
    relay = progress.ProgressRelay()
    watchdog = progress.ProgressWatchdog()
    stalled = False
    try:
        if on_start:
            on_start(identity or {'pid': process.pid, 'pgid': process.pid, 'start_ticks': -1})
        while True:
            # Do not reap before killing the process group: OCR descendants may
            # outlive an exited worker and the leader's zombie retains identity.
            if child_has_exited(process.pid):
                break
            if cancel_event is not None and cancel_event.is_set():
                state = 'cancelled'; break
            if stop_event is not None and stop_event.is_set():
                state = 'interrupted'; break
            elapsed = time.monotonic() - started
            value = progress.read_child_progress(
                child_environment.get('MARINAFRAME_PROGRESS_PATH'),
                child_environment.get('MARINAFRAME_PROGRESS_REQUEST'))
            next_stalled = watchdog.update(elapsed, value)
            if sandboxed_model_code and elapsed >= SANDBOX_MODEL_WALL_SECONDS:
                state = 'sandbox_safety_cap'; break
            # The Rust controller watches progress for its entire worker tree.
            # Nested supervisors retain cancellation and all resource limits.
            if controller_supervised:
                relay.relay(child_environment.get('MARINAFRAME_PROGRESS_PATH'))
            if not controller_supervised:
                if next_stalled and sandboxed_model_code:
                    state = 'stalled'; break
                if next_stalled != stalled:
                    if next_stalled:
                        logging.getLogger(__name__).warning(
                            'No progress at %s for %g min. The CAD worker keeps running; stop it to cancel.',
                            watchdog.stage, progress.NO_PROGRESS_SECONDS / 60)
                    else:
                        logging.getLogger(__name__).info('Continuing: %s.', watchdog.stage)
                    stalled = next_stalled
            if output_dir is not None and _output_bytes(output_dir, limits.output_bytes) > limits.output_bytes:
                state = 'resource_limited'; break
            time.sleep(0.05)
    except BaseException:
        kill_process_tree(identity, limits.termination_grace_seconds)
        process.wait(timeout=3)
        raise
    if state in ('sandbox_safety_cap', 'stalled'):
        # Popen created this session, and waitid above has not reaped its leader.
        # That unreaped child pins the PID/group identity even when ps is unavailable.
        for attempt in range(SANDBOX_KILL_ATTEMPTS):
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                break
            except PermissionError:
                if sys.platform != 'darwin':
                    raise
            # EPERM can mean only zombies remain, but an exited leader alone
            # cannot prove that. The group check also fails closed if ps fails.
            if sys.platform != 'darwin' or not _darwin_group_has_live_member(process.pid):
                break
            if attempt + 1 == SANDBOX_KILL_ATTEMPTS:
                raise PermissionError('Sandbox security limit reached; the process group still has live members.')
            time.sleep(SANDBOX_KILL_RETRY_SECONDS)
    else:
        kill_process_tree(identity, 0.02 if state == 'exited' else limits.termination_grace_seconds)
    returncode = process.wait(timeout=3)
    if output_dir is not None and _output_bytes(output_dir, limits.output_bytes) > limits.output_bytes:
        state = 'resource_limited'
    if state == 'exited' and returncode in (-signal.SIGXCPU, -signal.SIGXFSZ):
        state = 'resource_limited'
    outcome = {'state': state, 'exit_code': returncode, 'elapsed_seconds': round(time.monotonic() - started, 4),
               'process': identity, 'limits': asdict(limits)}
    if state == 'sandbox_safety_cap':
        outcome.update(error_code='sandbox_worker_absolute_safety_cap',
                       error=f'The sandboxed CAD worker reached the four-hour security limit (240 min) at {watchdog.stage}.')
    elif state == 'stalled':
        outcome.update(error_code='sandbox_worker_stalled',
                       error=f'The sandboxed CAD worker stopped at {watchdog.stage} after {progress.NO_PROGRESS_SECONDS / 60:g} min without progress.')
    elif state in ('cancelled', 'interrupted') and stalled:
        minutes = (time.monotonic() - started - watchdog.last_progress) / 60
        outcome['error'] = f'The worker was stopped at {watchdog.stage} after {minutes:.1f} min without progress.'
    return outcome


def recover_worker_output(output: Path, *, status: str = 'interrupted', reason: str | None = None) -> dict:
    try:
        from .pipeline import recover_interrupted_run
        return recover_interrupted_run(output, status=status, reason=reason)
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
    if sys.platform not in ('linux', 'darwin'):
        raise RuntimeError('The isolated local worker profile supports Linux and macOS only.')
    limits.validate()
    spec, output = Path(spec_path).resolve(), Path(output_dir).resolve()
    if output.exists():
        raise FileExistsError('Output already exists; choose a new run directory.')
    output.parent.mkdir(parents=True, exist_ok=True)
    receipt = output.parent / f'.worker-{uuid4().hex}.json'
    command = [sys.executable, '-m', 'vessel_reconstruction.worker', '--spec', str(spec), '--out', str(output),
               '--receipt', str(receipt), '--limits', json.dumps(asdict(limits)), '--parent', str(os.getpid())]
    env = safe_worker_environment()
    local_progress = None
    if not env.get('MARINAFRAME_PROGRESS_PATH'):
        local_progress = receipt.with_suffix('.progress.json')
        env.update(MARINAFRAME_PROGRESS_PATH=str(local_progress), MARINAFRAME_PROGRESS_REQUEST=receipt.stem)
    if not export_cad:
        command.append('--no-cad')
    try:
        outcome = supervise_process(command, limits=limits, cancel_event=cancel_event, stop_event=stop_event,
                                    on_start=on_start, output_dir=output, env=env)
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
                    for name in ('model.step', 'model.stl', 'model.iges', 'model-draft.step', 'model-draft.stl', 'model-draft.iges',
                                 'model.3dm', 'model-draft.3dm',
                                 'mesh.json', 'cad_sections.json', 'result.json', 'manifest.json'):
                        (quarantine / name).unlink(missing_ok=True)
                    outcome['quarantine'] = quarantine.name
                except OSError:
                    outcome['error_code'] = 'resource_quarantine_failed'
            recovered_status = 'cancelled' if outcome['state'] == 'cancelled' else 'failed' if outcome['state'] == 'failed' else 'interrupted'
            outcome['recovery'] = recover_worker_output(output, status=recovered_status, reason=outcome.get('error'))
            if outcome['recovery'].get('published'):
                try:
                    if verify_run(output).get('valid'):
                        outcome['result'] = json.loads((output / 'result.json').read_text())
                except (OSError, ValueError):
                    pass
        return outcome
    finally:
        receipt.unlink(missing_ok=True)
        if local_progress is not None:
            local_progress.unlink(missing_ok=True)
            local_progress.with_suffix('.lock').unlink(missing_ok=True)
