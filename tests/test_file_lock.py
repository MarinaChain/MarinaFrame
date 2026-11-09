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


def test_worker_limits_fail_closed_on_windows(monkeypatch):
    monkeypatch.setattr(process_limits.os, 'name', 'nt')
    with pytest.raises(RuntimeError, match='Windows'):
        process_limits.posix_resource()
