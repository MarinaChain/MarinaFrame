"""Progress is work completed, not a timer that can hide a stuck CAD call."""
import json
import time

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
    progress.relay(str(child))
    assert json.loads(path.read_text())['stage'] == 'Building vessel parts'
    progress.report('Exporting vessel parts', 1, 4)
    progress.relay(str(child))
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
