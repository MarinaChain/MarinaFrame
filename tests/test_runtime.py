"""Controlled process/queue faults; all fixtures have small host budgets."""
from dataclasses import asdict, replace
import hashlib
import io
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time

import pytest
from PIL import Image

from vessel_reconstruction.isolation import WorkerLimits, _proc_path, kill_process_tree, process_identity, safe_worker_environment, supervise_process
from vessel_reconstruction.jobs import AdmissionError, JobQueue


LIMITS = WorkerLimits(wall_seconds=3, cpu_seconds=2, memory_bytes=256*1024**2, file_bytes=1024**2, output_bytes=1024**2, termination_grace_seconds=0.05)


def image_bytes():
    buffer = io.BytesIO(); Image.new('RGB',(8,8),'white').save(buffer, format='PNG'); return buffer.getvalue()


def reserve(queue, key=None):
    raw = image_bytes()
    descriptor = {'primary': {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}}
    job, created = queue.reserve({'source': {}, 'vessel_id': 'runtime-fixture'}, descriptor, idempotency_key=key)
    return job, raw


def upload(queue, job, raw):
    part, descriptor = queue.begin_source(job['id'], 'primary', len(raw)); part.write_bytes(raw)
    queue.finish_source(job['id'], 'primary', part, hashlib.sha256(raw).hexdigest())
    return queue.submit(job['id'])


def stopped(pid):
    try:
        directory = _proc_path(pid)
        if directory is None: return True
        fields = (directory/'stat').read_text().rsplit(')',1)[1].split()
        return fields[0] == 'Z'
    except FileNotFoundError:
        return True


def test_wall_timeout_kills_child_process_group(tmp_path):
    child = tmp_path/'child.pid'
    code = f"import subprocess,sys,time; from pathlib import Path; p=subprocess.Popen([sys.executable,'-c','import time; time.sleep(20)']); Path({str(child)!r}).write_text(str(p.pid)); time.sleep(20)"
    result = supervise_process([sys.executable,'-c',code], limits=replace(LIMITS, wall_seconds=0.4))
    assert result['state'] == 'timed_out'
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
    assert supervise_process([sys.executable,'-c',memory], limits=LIMITS)['exit_code'] == 0
    target = tmp_path/'bounded.bin'
    file_probe = prefix + f"\ntry:\n open({str(target)!r},'wb').write(b'x'*(2*1024**2))\nexcept OSError:\n raise SystemExit(0)\nraise SystemExit(3)"
    assert supervise_process([sys.executable,'-c',file_probe], limits=LIMITS)['exit_code'] in (0, -signal.SIGXFSZ)
    assert target.stat().st_size <= LIMITS.file_bytes
    cpu_limits = replace(LIMITS, cpu_seconds=1, wall_seconds=3)
    cpu_prefix = f"import os,json; from vessel_reconstruction.worker import apply_limits; apply_limits(json.loads({json.dumps(asdict(cpu_limits))!r}), os.getppid()); "
    result = supervise_process([sys.executable,'-c',cpu_prefix+'\nwhile True: pass'], limits=cpu_limits)
    assert result['state'] == 'resource_limited' and result['exit_code'] == -signal.SIGXCPU


def test_queue_saturation_idempotency_and_cancel_before_work(tmp_path):
    queue = JobQueue(tmp_path/'artifacts', limits=LIMITS, max_pending=1, min_free_bytes=0, start_worker=False)
    try:
        job, raw = reserve(queue, 'idempotent-key-1')
        duplicate, again = reserve(queue, 'idempotent-key-1')
        assert duplicate['id'] == job['id']
        with pytest.raises(AdmissionError, match='full'):
            reserve(queue)
        descriptors = {'primary': {'bytes': 2, 'sha256': 'a'*64}}
        with pytest.raises(AdmissionError) as conflict:
            queue.reserve({'source': {}}, descriptors, idempotency_key='idempotent-key-1')
        assert conflict.value.status == 409
        queued = upload(queue, job, raw); assert queued['state'] == 'queued'
        assert queue.cancel(job['id'])['state'] == 'cancelled'
        assert not (queue.runs/job['id']).exists()
        reserve(queue)
    finally:
        queue.close()


def test_disk_admission_rejects_before_input_spool(tmp_path):
    queue = JobQueue(tmp_path/'artifacts', limits=LIMITS, max_disk_bytes=1, min_free_bytes=0, start_worker=False)
    try:
        with pytest.raises(AdmissionError) as caught: reserve(queue)
        assert caught.value.status == 507
        assert list(queue.inputs.iterdir()) == []
    finally: queue.close()


def test_queue_survives_restart_and_marks_abandoned_work(tmp_path):
    root = tmp_path/'artifacts'
    queue = JobQueue(root, limits=LIMITS, min_free_bytes=0, start_worker=False)
    running, raw = reserve(queue); upload(queue, running, raw)
    waiting, raw = reserve(queue); upload(queue, waiting, raw)
    partial, raw = reserve(queue)
    with queue.lock:
        job = queue._get(running['id']); job['state'] = 'running'; queue._save(job)
    queue.close()
    queue = JobQueue(root, limits=LIMITS, min_free_bytes=0, start_worker=False)
    try:
        assert queue.get(running['id'])['state'] == 'interrupted'
        assert queue.get(partial['id'])['state'] == 'interrupted'
        assert queue.get(waiting['id'])['state'] == 'queued'
        assert queue._source_integrity(queue.get(waiting['id'], internal=True))
        (queue.inputs/waiting['id']/'drawing.png').write_bytes(b'changed')
        assert not queue._source_integrity(queue.get(waiting['id'], internal=True))
    finally: queue.close()


def test_receiving_expiry_input_retention_and_backup_restore(tmp_path):
    root = tmp_path/'artifacts'
    queue = JobQueue(root, limits=LIMITS, min_free_bytes=0, receiving_seconds=0.01, input_retention_seconds=0, start_worker=False)
    job, raw = reserve(queue)
    time.sleep(0.02); queue.maintain()
    assert queue.get(job['id'])['state'] == 'interrupted'
    assert not (queue.inputs/job['id']).exists()
    queued, raw = reserve(queue); upload(queue, queued, raw)
    (queue.runs/'retained.txt').write_text('backup evidence')
    backup = queue.backup(tmp_path/'backup'); queue.close()
    restored = JobQueue(backup, limits=LIMITS, min_free_bytes=0, start_worker=False)
    try:
        assert restored.get(queued['id'])['state'] == 'queued'
        assert restored._source_integrity(restored.get(queued['id'], internal=True))
        assert (restored.runs/'retained.txt').read_text() == 'backup evidence'
    finally: restored.close()


def test_single_controller_and_corrupted_state_fail_closed(tmp_path):
    root = tmp_path/'artifacts'
    queue = JobQueue(root, limits=LIMITS, min_free_bytes=0, start_worker=False)
    try:
        with pytest.raises(RuntimeError, match='already owns'):
            JobQueue(root, limits=LIMITS, start_worker=False)
    finally: queue.close()
    (root/'.workbench'/'jobs.sqlite3').write_bytes(b'not sqlite')
    with pytest.raises(Exception): JobQueue(root, limits=LIMITS, start_worker=False)


def test_quick_exit_still_checks_aggregate_output_budget(tmp_path):
    out=tmp_path/'run';out.mkdir()
    code=f"from pathlib import Path; Path({str(out/'file.bin')!r}).write_bytes(b'x'*2048)"
    result=supervise_process([sys.executable,'-c',code],limits=replace(LIMITS,output_bytes=1024),output_dir=out)
    assert result['state']=='resource_limited'


def test_queued_spec_cannot_change_independently_of_descriptor(tmp_path):
    queue=JobQueue(tmp_path/'artifacts',limits=LIMITS,min_free_bytes=0,start_worker=False)
    try:
        job,raw=reserve(queue);upload(queue,job,raw)
        internal=queue.get(job['id'],internal=True)
        assert queue._source_integrity(internal)
        spec=queue.inputs/job['id']/'spec.json'
        value=json.loads(spec.read_text());value['vessel_id']='changed-after-admission';spec.write_text(json.dumps(value))
        assert not queue._source_integrity(internal)
    finally:queue.close()


def test_idle_maintenance_expires_upload_without_new_admission(tmp_path):
    queue=JobQueue(tmp_path/'artifacts',limits=LIMITS,min_free_bytes=0,receiving_seconds=.05,input_retention_seconds=0)
    try:
        job,raw=reserve(queue)
        deadline=time.monotonic()+2
        while queue.get(job['id'])['state']=='receiving' and time.monotonic()<deadline:time.sleep(.05)
        assert queue.get(job['id'])['state']=='interrupted'
        assert not (queue.inputs/job['id']).exists()
    finally:queue.close()


def test_readiness_reflects_storage_admission_not_only_free_disk(tmp_path):
    queue=JobQueue(tmp_path/'artifacts',limits=LIMITS,max_disk_bytes=1024,min_free_bytes=0)
    try:
        health=queue.health()
        assert health['live'] and health['worker_alive'] and not health['ready']
        assert health['admission_blocker']=='disk_budget'
    finally:queue.close()


def test_real_isolated_blocked_job_and_worker_telemetry(tmp_path):
    from vessel_reconstruction.isolation import run_isolated
    spec=tmp_path/'invalid.json';spec.write_text('{"input_mode":[]}')
    outcome=run_isolated(spec,tmp_path/'run',export_cad=False)
    assert outcome['state']=='blocked' and outcome['result']['status']=='blocked'
    assert outcome['result']['review']['engineering_approved'] is False
    assert outcome['resources']['peak_rss_kib']>0 and outcome['resources']['cpu_seconds']>0
    assert outcome['resources']['resource_profile']=='linux_rlimit_process_group_v1'
    assert outcome['exit_code']==0


def test_real_queue_job_reaches_durable_blocked_state(tmp_path):
    queue=JobQueue(tmp_path/'artifacts',min_free_bytes=0)
    try:
        job,raw=reserve(queue);upload(queue,job,raw)
        deadline=time.monotonic()+5
        while queue.get(job['id'])['state'] in {'queued','running'} and time.monotonic()<deadline:time.sleep(.05)
        final=queue.get(job['id'])
        assert final['state']=='blocked' and final['result_status']=='blocked'
        assert final['resources']['peak_rss_kib']>0
    finally:queue.close()
    restored=JobQueue(tmp_path/'artifacts',min_free_bytes=0,start_worker=False)
    try: assert restored.get(job['id'])['state']=='blocked'
    finally:restored.close()


def test_output_quota_uses_literal_transaction_basename(tmp_path):
    from vessel_reconstruction.isolation import _output_bytes
    unrelated=tmp_path/('.run-a.staging-'+'a'*32);unrelated.mkdir();(unrelated/'file.bin').write_bytes(b'x'*2048)
    requested=tmp_path/'run-[ab]'
    assert _output_bytes(requested,1024)==0
    own=tmp_path/('.run-[ab].staging-'+'b'*32);own.mkdir();(own/'file.bin').write_bytes(b'x'*10)
    assert _output_bytes(requested,1024)==10


def test_backup_does_not_follow_symlink_to_external_data(tmp_path):
    root=tmp_path/'artifacts';queue=JobQueue(root,limits=LIMITS,min_free_bytes=0,start_worker=False)
    outside=tmp_path/'outside';outside.mkdir();(outside/'private.txt').write_text('outside artifact root')
    (root/'external').symlink_to(outside,target_is_directory=True)
    try:
        with pytest.raises(ValueError,match='symbolic links'):queue.backup(tmp_path/'backup')
        assert not (tmp_path/'backup').exists()
    finally:queue.close()
