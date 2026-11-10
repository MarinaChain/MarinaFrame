"""Controlled process/queue faults; all fixtures have small host budgets."""
from dataclasses import asdict, replace
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time

from vessel_reconstruction.isolation import WorkerLimits, kill_process_tree, process_identity, safe_worker_environment, supervise_process
from vessel_reconstruction.resources import native_resource_profile


LIMITS = WorkerLimits(wall_seconds=3, cpu_seconds=2, memory_bytes=256*1024**2, file_bytes=1024**2, output_bytes=1024**2, termination_grace_seconds=0.05)


def stopped(pid):
    """Check POSIX liveness without treating a missing procfs as an exit."""
    try:
        reaped_pid, _ = os.waitpid(pid, os.WNOHANG)
    except ChildProcessError:
        pass  # Descendants are not necessarily children of the test process.
    else:
        return reaped_pid == pid

    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return True
    except PermissionError:
        return False

    # An orphan may remain a zombie until its new parent reaps it. ps works on
    # both macOS and Linux; an inspection error must fail the cleanup check.
    result = subprocess.run(['/bin/ps', '-o', 'stat=', '-p', str(pid)],
                            capture_output=True, text=True, timeout=3)
    state = result.stdout.strip()
    if result.returncode == 1 and not state and not result.stderr.strip():
        return True  # The process exited between kill(0) and ps.
    assert result.returncode == 0 and state, f'cannot inspect process {pid}: {result}'
    return state.startswith('Z')


def test_stopped_distinguishes_a_live_child_from_a_reaped_child():
    child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'])
    try:
        assert child.poll() is None
        assert not stopped(child.pid), 'a live child must not pass a cleanup check'
    finally:
        child.kill()
        child.wait(timeout=3)
    assert stopped(child.pid)


def test_stopped_recognizes_an_unreaped_child():
    child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'])
    try:
        child.kill()
        deadline = time.monotonic() + 3
        while not stopped(child.pid):
            assert time.monotonic() < deadline, 'killed child did not stop'
            time.sleep(0.01)
    finally:
        child.wait(timeout=3)


def test_stopped_does_not_treat_permission_denial_as_an_exit(monkeypatch):
    def deny_signal(pid, sig):
        raise PermissionError('signal permission denied')

    monkeypatch.setattr(os, 'kill', deny_signal)
    assert not stopped(os.getpid())


def test_sandbox_stall_kills_child_process_group(tmp_path, monkeypatch):
    from vessel_reconstruction import progress
    monkeypatch.delenv('MARINAFRAME_PROGRESS_PATH', raising=False)
    monkeypatch.setattr(progress, 'NO_PROGRESS_SECONDS', 0.5)
    child = tmp_path/'child.pid'
    code = f"import subprocess,sys,time; from pathlib import Path; p=subprocess.Popen([sys.executable,'-c','import time; time.sleep(20)']); Path({str(child)!r}).write_text(str(p.pid)); time.sleep(20)"
    result = supervise_process([sys.executable,'-c',code], limits=LIMITS, sandboxed_model_code=True)
    assert result['state'] == 'stalled'
    assert result['elapsed_seconds'] < 2
    assert stopped(int(child.read_text()))


def test_cancel_kills_worker_and_descendant(tmp_path):
    child = tmp_path/'child.pid'; cancel = threading.Event()
    code = f"import subprocess,sys,time; from pathlib import Path; p=subprocess.Popen([sys.executable,'-c','import time; time.sleep(20)']); Path({str(child)!r}).write_text(str(p.pid)); time.sleep(20)"
    timer = threading.Timer(0.35, cancel.set); timer.start()
    try:
        result = supervise_process([sys.executable,'-c',code], limits=LIMITS, cancel_event=cancel)
    finally:
        timer.cancel()
    assert result['state'] == 'cancelled'
    assert stopped(int(child.read_text()))


def test_exited_parent_does_not_leave_descendant(tmp_path):
    child = tmp_path/'child.pid'
    code = f"import subprocess,sys; from pathlib import Path; p=subprocess.Popen([sys.executable,'-c','import time; time.sleep(20)']); Path({str(child)!r}).write_text(str(p.pid))"
    result = supervise_process([sys.executable,'-c',code], limits=LIMITS)
    assert result['state'] == 'exited' and result['exit_code'] == 0
    assert stopped(int(child.read_text()))


def test_restart_cleanup_can_identify_orphan_group(tmp_path):
    marker = 'owned-runtime-test-marker'
    childfile = tmp_path/'child.pid'
    env = safe_worker_environment(); env['MARINAFRAME_JOB_TOKEN'] = marker
    code = f"import subprocess,sys; from pathlib import Path; p=subprocess.Popen([sys.executable,'-c','import time; time.sleep(20)']); Path({str(childfile)!r}).write_text(str(p.pid))"
    parent = subprocess.Popen([sys.executable,'-c',code], start_new_session=True, env=env)
    identity = process_identity(parent.pid); identity['token'] = marker
    parent.wait(timeout=3)
    try:
        assert kill_process_tree(identity, 0.05)
        time.sleep(0.1)
        assert stopped(int(childfile.read_text()))
    finally:
        try: os.killpg(identity['pgid'], signal.SIGKILL)
        except ProcessLookupError: pass


def test_reused_pid_identity_is_never_signalled():
    identity = process_identity(os.getpid()); identity['start_ticks'] -= 1
    assert not kill_process_tree(identity, 0.01)


def test_worker_environment_excludes_provider_credentials(monkeypatch):
    monkeypatch.setenv('OPENCODE_API_KEY', 'unit-test-placeholder')
    monkeypatch.setenv('OPENAI_API_KEY', 'unit-test-placeholder')
    environment = safe_worker_environment()
    assert 'OPENCODE_API_KEY' not in environment and 'OPENAI_API_KEY' not in environment
    assert environment['OPENBLAS_NUM_THREADS'] == '1'


def test_actual_cpu_address_space_and_file_limits(tmp_path):
    # Each probe applies the same worker bootstrap before the bounded operation.
    prefix = f"import os,json,resource; from vessel_reconstruction.worker import apply_limits; apply_limits(json.loads({json.dumps(asdict(LIMITS))!r}), os.getppid()); "
    memory = prefix + "\ntry:\n x=bytearray(512*1024**2)\nexcept MemoryError:\n raise SystemExit(0)\nraise SystemExit(3)"
    # macOS cannot lower RLIMIT_AS (an alias of the unenforced RLIMIT_RSS), so the
    # memory limit is enforced on Linux only; see docs/CONTINUATION_STATUS.md.
    if sys.platform == 'linux':
        assert supervise_process([sys.executable,'-c',memory], limits=LIMITS)['exit_code'] == 0
    target = tmp_path/'bounded.bin'
    file_probe = prefix + f"\ntry:\n open({str(target)!r},'wb').write(b'x'*(2*1024**2))\nexcept OSError:\n raise SystemExit(0)\nraise SystemExit(3)"
    assert supervise_process([sys.executable,'-c',file_probe], limits=LIMITS)['exit_code'] in (0, -signal.SIGXFSZ)
    assert target.stat().st_size <= LIMITS.file_bytes
    cpu_limits = replace(LIMITS, cpu_seconds=1, wall_seconds=3)
    cpu_prefix = f"import os,json; from vessel_reconstruction.worker import apply_limits; apply_limits(json.loads({json.dumps(asdict(cpu_limits))!r}), os.getppid()); "
    result = supervise_process([sys.executable,'-c',cpu_prefix+'\nwhile True: pass'], limits=cpu_limits)
    assert result['state'] == 'resource_limited' and result['exit_code'] == -signal.SIGXCPU


def test_quick_exit_still_checks_aggregate_output_budget(tmp_path):
    out=tmp_path/'run';out.mkdir()
    code=f"from pathlib import Path; Path({str(out/'file.bin')!r}).write_bytes(b'x'*2048)"
    result=supervise_process([sys.executable,'-c',code],limits=replace(LIMITS,output_bytes=1024),output_dir=out)
    assert result['state']=='resource_limited'


def test_real_isolated_blocked_job_and_worker_telemetry(tmp_path):
    from vessel_reconstruction.isolation import run_isolated
    spec=tmp_path/'invalid.json';spec.write_text('{"input_mode":[]}')
    outcome=run_isolated(spec,tmp_path/'run',export_cad=False)
    assert outcome['state']=='blocked' and outcome['result']['status']=='blocked'
    assert outcome['result']['review']['engineering_approved'] is False
    assert outcome['resources']['peak_rss_kib']>0 and outcome['resources']['cpu_seconds']>0
    assert outcome['resources']['resource_profile']==native_resource_profile()
    assert outcome['exit_code']==0


def test_output_quota_uses_literal_transaction_basename(tmp_path):
    from vessel_reconstruction.isolation import _output_bytes
    unrelated=tmp_path/('.run-a.staging-'+'a'*32);unrelated.mkdir();(unrelated/'file.bin').write_bytes(b'x'*2048)
    requested=tmp_path/'run-[ab]'
    assert _output_bytes(requested,1024)==0
    own=tmp_path/('.run-[ab].staging-'+'b'*32);own.mkdir();(own/'file.bin').write_bytes(b'x'*10)
    assert _output_bytes(requested,1024)==10


def test_deterministic_default_has_no_cpu_limit_and_reports_progress(tmp_path):
    from vessel_reconstruction.isolation import DEFAULT_LIMITS
    assert DEFAULT_LIMITS.cpu_seconds == 0 and DEFAULT_LIMITS.wall_seconds == 0
    progress_file = tmp_path / 'progress.json'
    env = safe_worker_environment()
    env.update(MARINAFRAME_PROGRESS_PATH=str(progress_file), MARINAFRAME_PROGRESS_REQUEST='cpu-test')
    prefix = f"import os,json,time; from vessel_reconstruction.worker import apply_limits; from vessel_reconstruction.progress import report; apply_limits(json.loads({json.dumps(asdict(DEFAULT_LIMITS))!r}), os.getppid()); "
    # One CPU second is the smallest POSIX limit; this loop exceeds it without sleeping.
    code = prefix + "\nstart=time.process_time()\nwhile time.process_time()-start < 1.3:\n report('Making the mesh', 1, 2)\n"
    result = supervise_process([sys.executable, '-c', code], limits=DEFAULT_LIMITS, env=env)
    assert result['state'] == 'exited' and result['exit_code'] == 0
    assert json.loads(progress_file.read_text())['stage'] == 'Making the mesh'


def test_cpu_limit_stop_names_limit_and_progress(tmp_path):
    limits = replace(LIMITS, cpu_seconds=1)
    progress_file = tmp_path / 'progress.json'
    env = safe_worker_environment()
    env.update(MARINAFRAME_PROGRESS_PATH=str(progress_file), MARINAFRAME_PROGRESS_REQUEST='cpu-test')
    prefix = f"import os,json; from vessel_reconstruction.worker import apply_limits; from vessel_reconstruction.progress import report; apply_limits(json.loads({json.dumps(asdict(limits))!r}), os.getppid()); report('Making the mesh', 7, 16); "
    result = supervise_process([sys.executable, '-c', prefix+'\nwhile True: pass'], limits=limits, env=env, sandboxed_model_code=True)
    assert result['state'] == 'resource_limited'
    assert 'CPU' in result['error'] and 'Making the mesh' in result['error'] and '7 of 16' in result['error']


def test_resource_stop_reason_reaches_run_recovery(tmp_path, monkeypatch):
    from vessel_reconstruction import isolation
    message = 'Stopped by the CPU limit (1 seconds) while Making the mesh, 7 of 16 part.'
    monkeypatch.setattr(isolation, 'supervise_process', lambda *args, **kwargs: {
        'state': 'resource_limited', 'exit_code': -signal.SIGXCPU, 'error': message})
    recovered = {}
    def recover(output, *, status, reason):
        recovered.update(status=status, reason=reason)
        return {'published': False}
    monkeypatch.setattr(isolation, 'recover_worker_output', recover)
    isolation.run_isolated(tmp_path / 'spec.json', tmp_path / 'run')
    assert recovered['reason'] == message


def test_worker_receipt_identifies_file_size_limit(tmp_path, monkeypatch):
    import errno
    from vessel_reconstruction import pipeline, worker
    receipt = tmp_path / 'receipt.json'
    monkeypatch.setattr(worker, 'apply_limits', lambda *args: None)
    def exceed_file_limit(*args, **kwargs):
        raise OSError(errno.EFBIG, 'File too large')
    monkeypatch.setattr(pipeline, 'reconstruct', exceed_file_limit)
    monkeypatch.setattr(sys, 'argv', ['worker', '--spec', 'spec', '--out', 'out',
                                      '--receipt', str(receipt), '--limits', '{}', '--parent', '1'])
    assert worker.main() == 1
    assert json.loads(receipt.read_text())['error_code'] == 'worker_file_size_limit'
