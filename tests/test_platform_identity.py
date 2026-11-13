"""Admission metadata must not invent a Windows equivalent of a POSIX lock."""
from pathlib import Path

import pytest

from vessel_reconstruction import platform_identity


def test_windows_admission_metadata_has_no_fabricated_lock(monkeypatch):
    monkeypatch.setattr(platform_identity, '_IS_WINDOWS', True)
    assert platform_identity.native_admission_lock_metadata() == {
        'native_admission_lock': None,
        'native_admission_lock_reason': 'POSIX native admission locking is not supported on this platform.',
    }


@pytest.mark.skipif(__import__('os').name == 'nt', reason='POSIX user IDs are not supported on this platform.')
def test_posix_admission_metadata_preserves_controller_path(monkeypatch, tmp_path):
    monkeypatch.setattr(platform_identity, '_IS_WINDOWS', False)
    monkeypatch.setattr(platform_identity.os, 'geteuid', lambda: 123)
    monkeypatch.setenv('TMPDIR', str(tmp_path))
    assert platform_identity.native_admission_lock_metadata() == {
        'native_admission_lock': str((tmp_path / 'marinaframe-native-admission-123.lock').resolve()),
    }
