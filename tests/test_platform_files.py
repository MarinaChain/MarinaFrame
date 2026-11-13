"""Filesystem platform boundaries preserve errors and close native handles."""
from pathlib import Path
from unittest.mock import Mock

import pytest

from vessel_reconstruction import platform_files


@pytest.mark.parametrize('flush_error', [None, 1, 5, 50])
def test_windows_directory_flush_closes_handle(monkeypatch, flush_error):
    kernel = Mock()
    kernel.CreateFileW.return_value = 42
    kernel.FlushFileBuffers.return_value = flush_error is None
    monkeypatch.setattr(platform_files, '_kernel32', lambda: kernel)
    monkeypatch.setattr(platform_files, '_last_error', lambda: flush_error)
    platform_files.sync_windows_directory(Path('folder'))
    assert kernel.CreateFileW.call_args.args[-2] & 0x02000000  # backup semantics
    assert kernel.CreateFileW.call_args.args[1] & 0x40000000  # flush needs write access
    kernel.FlushFileBuffers.assert_called_once_with(42)
    kernel.CloseHandle.assert_called_once_with(42)


def test_windows_directory_flush_propagates_io_error(monkeypatch):
    kernel = Mock()
    kernel.CreateFileW.return_value = 42
    kernel.FlushFileBuffers.return_value = False
    monkeypatch.setattr(platform_files, '_kernel32', lambda: kernel)
    monkeypatch.setattr(platform_files, '_last_error', lambda: 1117)
    with pytest.raises(OSError, match='1117'):
        platform_files.sync_windows_directory(Path('folder'))
    kernel.CloseHandle.assert_called_once_with(42)


def test_windows_read_only_directory_has_documented_no_flush(monkeypatch):
    kernel = Mock()
    kernel.CreateFileW.side_effect = [platform_files.INVALID_HANDLE_VALUE, 42]
    monkeypatch.setattr(platform_files, '_kernel32', lambda: kernel)
    monkeypatch.setattr(platform_files, '_last_error', lambda: 5)
    platform_files.sync_windows_directory(Path('folder'))
    kernel.FlushFileBuffers.assert_not_called()
    kernel.CloseHandle.assert_called_once_with(42)


def test_windows_directory_open_error_is_not_ignored(monkeypatch):
    kernel = Mock()
    kernel.CreateFileW.return_value = platform_files.INVALID_HANDLE_VALUE
    monkeypatch.setattr(platform_files, '_kernel32', lambda: kernel)
    monkeypatch.setattr(platform_files, '_last_error', lambda: 3)
    with pytest.raises(OSError, match='3'):
        platform_files.sync_windows_directory(Path('missing'))
    kernel.FlushFileBuffers.assert_not_called()
    kernel.CloseHandle.assert_not_called()
