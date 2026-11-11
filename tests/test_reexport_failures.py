import pytest

from vessel_reconstruction import reexport
from vessel_reconstruction.file_lock import try_lock_exclusive, unlock
from test_reexport import finished, snapshot


def test_failed_rollback_preserves_original_snapshot(tmp_path, monkeypatch):
    task = finished(tmp_path)
    before = snapshot(task)
    exchange = reexport._exchange_directories
    calls = 0
    def fail_rollback(a, b):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError('rollback unavailable')
        exchange(a, b)
    def fail(phase):
        if phase == 'after_publish':
            raise RuntimeError('injected')
    monkeypatch.setattr(reexport, '_exchange_directories', fail_rollback)
    monkeypatch.setattr(reexport, '_checkpoint', fail)
    with pytest.raises(OSError, match='rollback unavailable'):
        reexport.refresh(task, 'r1')
    stages = list(task.parent.glob('.task.reexport-*'))
    assert len(stages) == 1
    assert snapshot(stages[0]) == before
    with (task / 'controller.lock').open('r+b') as lock:
        try_lock_exclusive(lock)
        unlock(lock)


def test_cleanup_failure_does_not_leak_lock(tmp_path, monkeypatch):
    task = finished(tmp_path)
    def fail(phase):
        if phase == 'records':
            raise RuntimeError('injected')
    def fail_cleanup(*args, **kwargs):
        raise OSError('cleanup unavailable')
    monkeypatch.setattr(reexport, '_checkpoint', fail)
    monkeypatch.setattr(reexport.shutil, 'rmtree', fail_cleanup)
    with pytest.raises(OSError, match='cleanup unavailable'):
        reexport.refresh(task, 'r1')
    with (task / 'controller.lock').open('r+b') as lock:
        try_lock_exclusive(lock)
        unlock(lock)
