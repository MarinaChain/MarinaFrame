"""Platform boundaries must be importable without Unix-only Python modules."""
import os
from pathlib import Path
import subprocess
import sys
import textwrap

import pytest

from vessel_reconstruction import isolation


SRC = str(Path(__file__).resolve().parents[1] / 'src')


def test_parallel_import_does_not_require_unix_modules():
    script = textwrap.dedent('''
        import importlib.abc
        import sys

        class NoUnixModules(importlib.abc.MetaPathFinder):
            def find_spec(self, fullname, path=None, target=None):
                if fullname in ('fcntl', 'pwd', 'resource'):
                    raise ModuleNotFoundError(fullname)

        sys.meta_path.insert(0, NoUnixModules())
        # The lock boundary selects the Windows backend. Supply only that backend
        # when running this regression on POSIX; this is not a Windows OS simulation.
        import types
        sys.modules['vessel_reconstruction.file_lock'] = types.SimpleNamespace(
            try_lock_exclusive=lambda target: None)
        import vessel_reconstruction.parallel
    ''')
    result = subprocess.run([sys.executable, '-c', script], capture_output=True,
                            text=True, env={**os.environ, 'PYTHONPATH': SRC})
    assert result.returncode == 0, result.stderr


def test_atomic_package_exchange_refuses_before_posix_library_load(monkeypatch, tmp_path):
    from vessel_reconstruction.exports import package
    monkeypatch.setattr(package.sys, 'platform', 'win32')
    def unexpected_load(*args, **kwargs):
        pytest.fail('Unsupported atomic exchange must not load POSIX APIs')
    monkeypatch.setattr(package.ctypes, 'CDLL', unexpected_load)
    with pytest.raises(package.ExportError, match='not supported on this platform'):
        package._exchange_directories(tmp_path / 'first', tmp_path / 'second')


def test_private_pool_refuses_without_windows_acl_proof(monkeypatch, caplog):
    from vessel_reconstruction import parallel
    monkeypatch.setattr(parallel.os, 'name', 'nt')
    with pytest.raises(PermissionError, match='not supported on this platform'):
        parallel.pool_directory()
    with parallel.worker_tokens(2, size=2) as granted:
        assert granted == 2
    assert 'Worker pool not used' in caplog.text


def test_unsupported_supervisor_refuses_before_starting_child(monkeypatch):
    monkeypatch.setattr(isolation.sys, 'platform', 'win32')

    def unexpected_spawn(*args, **kwargs):
        pytest.fail('Unsupported supervision must not start a child')

    monkeypatch.setattr(isolation.subprocess, 'Popen', unexpected_spawn)
    with pytest.raises(RuntimeError, match='not supported on this platform'):
        isolation.supervise_process([sys.executable, '-c', 'pass'])


@pytest.mark.parametrize('operation,args', [
    ('process_identity', (123,)),
    ('kill_process_tree', ({'pid': 123, 'pgid': 123, 'start_ticks': 1},)),
    ('child_has_exited', (123,)),
])
def test_posix_lifecycle_calls_refuse_unsupported_platform(monkeypatch, operation, args):
    monkeypatch.setattr(isolation.sys, 'platform', 'win32')
    with pytest.raises(RuntimeError, match='not supported on this platform'):
        getattr(isolation, operation)(*args)
