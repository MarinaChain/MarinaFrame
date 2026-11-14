"""Progress is work completed, not a timer that can hide a stuck CAD call."""
import json
import os
import subprocess
import sys
import time

import pytest

from vessel_reconstruction import progress


def test_heartbeat_refreshes_timestamp_without_inventing_progress(tmp_path, monkeypatch):
    path = tmp_path / 'progress.json'
    monkeypatch.setenv('MARINAFRAME_PROGRESS_PATH', str(path))
    monkeypatch.setenv('MARINAFRAME_PROGRESS_REQUEST', 'worker-test')
    progress.report('Building the hull', 31, 72, unit='section')
    first = json.loads(path.read_text())
    time.sleep(0.01)
    progress.refresh()
    beat = json.loads(path.read_text())
    assert beat['counter'] == first['counter']
    assert beat['timestamp_ms'] > first['timestamp_ms']
    assert (beat['stage'], beat['part'], beat['total'], beat['request_id']) == (
        'Building the hull', 31, 72, 'worker-test')
    progress.report('Exporting STEP', 1, 4, unit='format')
    assert json.loads(path.read_text())['counter'] > first['counter']


def test_heartbeat_thread_writes_during_a_long_operation(tmp_path, monkeypatch):
    path = tmp_path / 'progress.json'
    monkeypatch.setenv('MARINAFRAME_PROGRESS_PATH', str(path))
    monkeypatch.setenv('MARINAFRAME_PROGRESS_REQUEST', 'worker-test')
    with progress.Heartbeat('Building the hull', interval=0.01):
        first = json.loads(path.read_text())
        deadline = time.monotonic() + 1
        while json.loads(path.read_text())['timestamp_ms'] <= first['timestamp_ms']:
            assert time.monotonic() < deadline
            time.sleep(0.01)
    last = json.loads(path.read_text())
    assert last['counter'] == first['counter']


def test_progress_is_optional_outside_a_controller_worker(monkeypatch):
    monkeypatch.delenv('MARINAFRAME_PROGRESS_PATH', raising=False)
    progress.report('Building the hull', 1, 2)


def test_sandbox_progress_relay_keeps_newest_stage(tmp_path, monkeypatch):
    path = tmp_path / 'progress.json'
    child = tmp_path / 'child.json'
    monkeypatch.setenv('MARINAFRAME_PROGRESS_PATH', str(path))
    monkeypatch.setenv('MARINAFRAME_PROGRESS_REQUEST', 'worker-test')
    progress.report('Preparing vessel parts')
    record = json.loads(path.read_text())
    record.update(stage='Building vessel parts', part=2, total=4, counter=record['counter'] + 1)
    child.write_text(json.dumps(record))
    relay = progress.ProgressRelay()
    relay.relay(str(child))
    assert json.loads(path.read_text())['stage'] == 'Building vessel parts'
    progress.report('Exporting vessel parts', 1, 4)
    relay.relay(str(child))
    assert json.loads(path.read_text())['stage'] == 'Exporting vessel parts'


def test_nested_worker_defers_time_limit_to_controller(tmp_path, monkeypatch):
    import sys
    from dataclasses import replace
    from vessel_reconstruction.isolation import DEFAULT_LIMITS, supervise_process
    monkeypatch.setenv('MARINAFRAME_PROGRESS_PATH', str(tmp_path / 'progress.json'))
    monkeypatch.setenv('MARINAFRAME_PROGRESS_REQUEST', 'worker-test')
    result = supervise_process([sys.executable, '-c', 'import time; time.sleep(0.3)'],
                               limits=replace(DEFAULT_LIMITS, wall_seconds=0.01))
    assert result['state'] == 'exited'
    assert result['exit_code'] == 0


@pytest.mark.parametrize('model_code', [False, True])
def test_standalone_stall_policy_uses_trust_not_child_heartbeat(tmp_path, monkeypatch, caplog, model_code):
    from dataclasses import replace
    from vessel_reconstruction import isolation
    clock = [0.0]
    killed = []
    path = tmp_path / 'progress.json'
    path.write_text(json.dumps(child_record(stage='Making the mesh', part=0, total=0)))

    class Child:
        pid = 12345

        def wait(self, timeout):
            return -9 if model_code and killed else 0

    monkeypatch.delenv('MARINAFRAME_PROGRESS_PATH', raising=False)
    monkeypatch.setattr(isolation.subprocess, 'Popen', lambda *a, **k: Child())
    monkeypatch.setattr(isolation, 'process_identity', lambda pid: None)
    monkeypatch.setattr(isolation, 'child_has_exited', lambda pid: clock[0] >= 900)
    monkeypatch.setattr(isolation, 'kill_process_tree', lambda *a: killed.append(True))
    monkeypatch.setattr(isolation.time, 'monotonic', lambda: clock[0])

    def heartbeat(_):
        clock[0] += 100
        record = json.loads(path.read_text())
        record.update(counter=record['counter'] + 1, timestamp_ms=int(clock[0] * 1000))
        path.write_text(json.dumps(record))

    monkeypatch.setattr(isolation.time, 'sleep', heartbeat)
    result = isolation.supervise_process(
        ['controlled-child'], limits=replace(isolation.DEFAULT_LIMITS, wall_seconds=10),
        env={'MARINAFRAME_PROGRESS_PATH': str(path), 'MARINAFRAME_PROGRESS_REQUEST': 'worker-test'},
        sandboxed_model_code=model_code)
    if model_code:
        assert result['state'] == 'stalled'
        assert result['error_code'] == 'sandbox_worker_stalled'
        assert 'Making the mesh' in result['error'] and '5 min' in result['error']
        assert result['elapsed_seconds'] == 300
    else:
        assert result['state'] == 'exited' and result['exit_code'] == 0
        assert result['elapsed_seconds'] == 900
        assert 'Making the mesh' in caplog.text and '5 min' in caplog.text


def test_isolated_recovery_keeps_specific_stop_reason(tmp_path, monkeypatch):
    from vessel_reconstruction import isolation, pipeline
    from vessel_reconstruction.transaction import RunTransaction
    output = tmp_path / 'run'
    transaction = RunTransaction(output)
    transaction.checkpoint('cad_exports')
    transaction.close()
    message = 'The sandboxed CAD worker stopped at Making the mesh after 5 min without progress.'
    monkeypatch.setattr(isolation, 'supervise_process', lambda *a, **k: {
        'state': 'stalled', 'exit_code': -9, 'error_code': 'sandbox_worker_stalled', 'error': message})
    outcome = isolation.run_isolated(tmp_path / 'spec.json', output)
    assert outcome['result']['gaps'][0]['message'] == message
    assert pipeline.verify_run(output)['valid']


def child_record(**changes):
    return {'request_id': 'worker-test', 'stage': 'Building the hull', 'part': 1,
            'total': 72, 'unit': 'section', 'counter': 1, 'timestamp_ms': 1} | changes


@pytest.mark.parametrize('kind', ['symlink', 'fifo', 'oversized', 'non_object'])
def test_untrusted_progress_files_do_not_block_or_follow_links(tmp_path, kind):
    child = tmp_path / 'child.json'
    if kind == 'symlink':
        target = tmp_path / 'private.json'
        target.write_text(json.dumps(child_record()))
        child.symlink_to(target)
    elif kind == 'fifo':
        os.mkfifo(child)
    elif kind == 'oversized':
        child.write_text(json.dumps(child_record()) + ' ' * 2048)
    else:
        child.write_text('[]')
    # An isolated test process bounds a broken FIFO reader instead of hanging pytest.
    code = '''import sys
from vessel_reconstruction.progress import read_child_progress
assert read_child_progress(sys.argv[1], 'worker-test') is None
'''
    result = subprocess.run([sys.executable, '-c', code, str(child)],
                            capture_output=True, text=True, timeout=2)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize('changes', [
    {'stage': 'x' * 121}, {'stage': 'hull\nexport'}, {'stage': 'hull\x85export'},
    {'unit': 'shell'}, {'part': -1}, {'part': True}, {'part': 73},
    {'total': 100001}, {'total': False}, {'request_id': 'another-worker'},
])
def test_relay_rejects_invalid_display_fields(tmp_path, changes):
    child = tmp_path / 'child.json'
    child.write_text(json.dumps(child_record(**changes)))
    assert progress.read_child_progress(child, 'worker-test') is None


def test_child_counter_alone_cannot_advance_trusted_progress(tmp_path, monkeypatch):
    path, child = tmp_path / 'progress.json', tmp_path / 'child.json'
    monkeypatch.setenv('MARINAFRAME_PROGRESS_PATH', str(path))
    monkeypatch.setenv('MARINAFRAME_PROGRESS_REQUEST', 'worker-test')
    relay = progress.ProgressRelay()
    child.write_text(json.dumps(child_record(counter=10**100)))
    relay.relay(child)
    first = json.loads(path.read_text())
    for counter in range(10):
        child.write_text(json.dumps(child_record(counter=counter)))
        relay.relay(child)
    assert json.loads(path.read_text())['counter'] == first['counter']
    child.write_text(json.dumps(child_record(part=2, counter=0)))
    relay.relay(child)
    assert json.loads(path.read_text())['counter'] == first['counter'] + 1


def test_relay_advance_budget_is_per_step_and_cannot_be_reset_by_the_child(tmp_path, monkeypatch):
    path, child = tmp_path / 'progress.json', tmp_path / 'child.json'
    monkeypatch.setenv('MARINAFRAME_PROGRESS_PATH', str(path))
    monkeypatch.setenv('MARINAFRAME_PROGRESS_REQUEST', 'worker-test')
    monkeypatch.setattr(progress, 'MAX_PROGRESS_ADVANCES_PER_STEP', 3)
    relay = progress.ProgressRelay()
    for part in range(1, 7):
        child.write_text(json.dumps(child_record(part=part)))
        relay.relay(child)
    value = json.loads(path.read_text())
    assert value['part'] == 3
    assert value['counter'] == 3


@pytest.mark.parametrize('model_code', [False, True])
def test_supervisor_absolute_cap_applies_only_to_sandboxed_model_code(monkeypatch, model_code):
    from vessel_reconstruction import isolation
    clock = [0.0]
    killed = []

    class Child:
        pid = 12345

        def wait(self, timeout):
            return -9 if killed else 0

    # This is a simulated POSIX supervisor, including its signal vocabulary.
    monkeypatch.setattr(isolation.sys, 'platform', 'darwin')
    monkeypatch.setattr(isolation.signal, 'SIGKILL', 9, raising=False)
    monkeypatch.setattr(isolation.signal, 'SIGXCPU', 24, raising=False)
    monkeypatch.setattr(isolation.signal, 'SIGXFSZ', 25, raising=False)
    monkeypatch.setattr(isolation.progress, 'read_child_progress', lambda *args: None)
    monkeypatch.setattr(isolation.progress.ProgressRelay, 'relay', lambda *args: None)
    monkeypatch.setenv('MARINAFRAME_PROGRESS_PATH', '/unused/trusted-progress.json')
    monkeypatch.setattr(isolation.subprocess, 'Popen', lambda *a, **k: Child())
    # The cap must still stop our live child when host process inspection is unavailable.
    monkeypatch.setattr(isolation, 'process_identity', lambda pid: None)
    monkeypatch.setattr(isolation, 'child_has_exited', lambda pid: clock[0] > 2 * isolation.SANDBOX_MODEL_WALL_SECONDS)
    monkeypatch.setattr(isolation, 'kill_process_tree', lambda *a: False)
    monkeypatch.setattr(isolation, '_darwin_group_has_live_member', lambda pid: False)
    monkeypatch.setattr(isolation.os, 'killpg', lambda group, sig: killed.append((group, sig)), raising=False)
    monkeypatch.setattr(isolation.time, 'monotonic', lambda: clock[0])
    monkeypatch.setattr(isolation.time, 'sleep', lambda _: clock.__setitem__(0, clock[0] + isolation.SANDBOX_MODEL_WALL_SECONDS))
    result = isolation.supervise_process(['controlled-child'], sandboxed_model_code=model_code)
    if model_code:
        assert result['state'] == 'sandbox_safety_cap'
        assert result['error_code'] == 'sandbox_worker_absolute_safety_cap'
        assert 'security limit' in result['error']
        assert result['elapsed_seconds'] == isolation.SANDBOX_MODEL_WALL_SECONDS
        assert killed == [(Child.pid, isolation.signal.SIGKILL)]
    else:
        assert result['state'] == 'exited'
        assert result['elapsed_seconds'] > isolation.SANDBOX_MODEL_WALL_SECONDS


def test_security_cap_stops_a_live_child_without_process_inspection(monkeypatch):
    from vessel_reconstruction import isolation
    monkeypatch.setattr(isolation, 'SANDBOX_MODEL_WALL_SECONDS', 0.05)
    monkeypatch.setattr(isolation, 'process_identity', lambda pid: None)
    # This controlled child only sleeps and never forks. Simulate the group
    # inspection that the host sandbox blocks; still send and verify a real SIGKILL.
    monkeypatch.setattr(isolation, '_darwin_group_has_live_member', lambda pid: not isolation.child_has_exited(pid))
    result = isolation.supervise_process(
        [sys.executable, '-c', 'import time; time.sleep(20)'], sandboxed_model_code=True)
    assert result['state'] == 'sandbox_safety_cap'
    assert result['exit_code'] == -isolation.signal.SIGKILL
    assert result['elapsed_seconds'] < 3


@pytest.mark.parametrize('child_survives', [False, True])
def test_security_cap_retries_a_group_with_an_exited_leader_and_live_child(monkeypatch, child_survives):
    from vessel_reconstruction import isolation
    clock = [0.0]
    signals, group_checks, reaped = [], [], []

    class Child:
        pid = 12345

        def wait(self, timeout):
            reaped.append(True)
            return 0

    def leader_exited(pid):
        # Alive when supervision first checks; a zombie by the first SIGKILL.
        return bool(signals)

    def refuse_signal(group, sig):
        assert (group, sig) == (Child.pid, isolation.signal.SIGKILL)
        signals.append(True)
        raise PermissionError('controlled signal refusal')

    def group_alive(group):
        assert group == Child.pid and leader_exited(group)
        group_checks.append(True)
        return child_survives or len(signals) < 2

    monkeypatch.setattr(isolation.sys, 'platform', 'darwin')
    monkeypatch.setattr(isolation.subprocess, 'Popen', lambda *a, **k: Child())
    monkeypatch.setattr(isolation, 'process_identity', lambda pid: None)
    monkeypatch.setattr(isolation, 'child_has_exited', leader_exited)
    monkeypatch.setattr(isolation, '_darwin_group_has_live_member', group_alive)
    monkeypatch.setattr(isolation.signal, 'SIGKILL', 9, raising=False)
    monkeypatch.setattr(isolation.signal, 'SIGXCPU', 24, raising=False)
    monkeypatch.setattr(isolation.signal, 'SIGXFSZ', 25, raising=False)
    monkeypatch.setattr(isolation.os, 'killpg', refuse_signal, raising=False)
    monkeypatch.setattr(isolation.time, 'monotonic', lambda: clock[0])
    monkeypatch.setattr(isolation.time, 'sleep', lambda seconds: clock.__setitem__(0, clock[0] + seconds))
    monkeypatch.setattr(isolation.progress, 'read_child_progress', lambda *args: None)
    monkeypatch.setattr(isolation.progress.ProgressRelay, 'relay', lambda *args: None)
    monkeypatch.setattr(isolation, 'SANDBOX_MODEL_WALL_SECONDS', 0)
    if child_survives:
        with pytest.raises(PermissionError, match='live'):
            isolation.supervise_process(['controlled-child'], sandboxed_model_code=True)
        assert len(signals) == isolation.SANDBOX_KILL_ATTEMPTS
        assert not reaped, 'retain group identity while cleanup is unproven'
    else:
        result = isolation.supervise_process(['controlled-child'], sandboxed_model_code=True)
        assert result['state'] == 'sandbox_safety_cap'
        assert len(signals) == 2
        assert reaped
    assert len(group_checks) == len(signals)
