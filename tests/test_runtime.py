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

from vessel_reconstruction.isolation import WorkerLimits, _proc_path, kill_process_tree, process_identity, safe_worker_environment, supervise_process
from vessel_reconstruction.resources import native_resource_profile


LIMITS = WorkerLimits(wall_seconds=3, cpu_seconds=2, memory_bytes=256*1024**2, file_bytes=1024**2, output_bytes=1024**2, termination_grace_seconds=0.05)


def stopped(pid):
    try:
        directory = _proc_path(pid)
        if directory is None: return True
        fields = (directory/'stat').read_text().rsplit(')',1)[1].split()
        return fields[0] == 'Z'
    except FileNotFoundError:
        return True


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
