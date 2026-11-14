"""The portable lock helper: an exclusive lock that another open of the same file cannot take."""
import os

import pytest

from vessel_reconstruction import process_limits
from vessel_reconstruction.file_lock import try_lock_exclusive, unlock


def test_a_held_lock_refuses_a_second_holder_until_it_is_released(tmp_path):
    path = tmp_path / 'lock'
    path.write_bytes(b'')
    with path.open('a') as first, path.open('a') as second:
        try_lock_exclusive(first)
        with pytest.raises(BlockingIOError):
            try_lock_exclusive(second)
        unlock(first)
        try_lock_exclusive(second)
        unlock(second)


def test_the_lock_also_takes_a_raw_descriptor(tmp_path):
    descriptor = os.open(tmp_path / 'lock', os.O_RDWR | os.O_CREAT, 0o600)
    try:
        try_lock_exclusive(descriptor)
        unlock(descriptor)
    finally:
        os.close(descriptor)


def test_blocking_lock_waits_until_other_holder_releases(tmp_path):
    import threading
    from vessel_reconstruction.file_lock import lock_exclusive
    path = tmp_path / 'lock'
    acquired = threading.Event()
    with path.open('a') as first, path.open('a') as second:
        try_lock_exclusive(first)
        def acquire():
            lock_exclusive(second)
            acquired.set()
            unlock(second)
        thread = threading.Thread(target=acquire)
        thread.start()
        try:
            assert not acquired.wait(0.05)
        finally:
            unlock(first)
        thread.join()
        assert acquired.is_set()


def test_worker_limits_fail_closed_on_windows(monkeypatch):
    monkeypatch.setattr(process_limits.os, 'name', 'nt')
    with pytest.raises(RuntimeError, match='Windows'):
        process_limits.posix_resource()


def _windows_file_lock(monkeypatch, tmp_path):
    """The module as Windows loads it, with an msvcrt stub that refuses to unlock a free byte."""
    import importlib.util
    import sys
    import types

    held = set()

    def locking(descriptor, mode, count):
        if mode == stub.LK_UNLCK:
            if descriptor not in held:
                raise OSError('not locked')
            held.discard(descriptor)
        elif descriptor in held:
            raise OSError('locked')
        else:
            held.add(descriptor)

    stub = types.SimpleNamespace(LK_NBLCK=2, LK_UNLCK=0, locking=locking)
    monkeypatch.setitem(sys.modules, 'msvcrt', stub)
    spec = importlib.util.spec_from_file_location('file_lock_windows', process_limits.__file__.replace(
        'process_limits.py', 'file_lock.py'))
    module = importlib.util.module_from_spec(spec)
    with monkeypatch.context() as patch:
        patch.setattr(os, 'name', 'nt')
        spec.loader.exec_module(module)
    return module


def test_windows_unlock_of_a_lock_never_taken_is_harmless(monkeypatch, tmp_path):
    lock = _windows_file_lock(monkeypatch, tmp_path)
    descriptor = os.open(tmp_path / 'lock', os.O_RDWR | os.O_CREAT, 0o600)
    try:
        lock.unlock(descriptor)  # not held: must not raise
        lock.try_lock_exclusive(descriptor)
        with pytest.raises(BlockingIOError):
            lock.try_lock_exclusive(descriptor)
        lock.unlock(descriptor)
        lock.try_lock_exclusive(descriptor)
    finally:
        os.close(descriptor)
