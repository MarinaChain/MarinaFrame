"""Platform boundaries must be importable without Unix-only Python modules."""
import os
from pathlib import Path
import subprocess
import sys
import textwrap


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
