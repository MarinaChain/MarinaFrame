"""Windows shell discovery must not silently select the WSL launcher."""
from pathlib import Path

import pytest

from vessel_reconstruction import platform_shell


def test_windows_selects_git_bash_beside_git_executable(monkeypatch, tmp_path):
    root = tmp_path / 'Git'
    (root / 'cmd').mkdir(parents=True)
    shell = root / 'bin' / 'bash.exe'
    shell.parent.mkdir()
    shell.touch()
    monkeypatch.setattr(platform_shell, '_IS_WINDOWS', True)
    monkeypatch.setattr(platform_shell.shutil, 'which', lambda name: str(root / 'cmd' / 'git.exe'))
    monkeypatch.setattr(platform_shell, '_program_files', lambda: [])
    assert Path(platform_shell.bash_executable()) == shell


def test_windows_without_git_bash_refuses_wsl_fallback(monkeypatch):
    monkeypatch.setattr(platform_shell, '_IS_WINDOWS', True)
    monkeypatch.setattr(platform_shell.shutil, 'which', lambda name: None)
    monkeypatch.setattr(platform_shell, '_program_files', lambda: [])
    with pytest.raises(RuntimeError, match='Git Bash'):
        platform_shell.bash_executable()
