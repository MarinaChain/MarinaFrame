"""Choose a native Bash installation without accidentally invoking Windows WSL."""
import os
from pathlib import Path
import shutil

_IS_WINDOWS = os.name == 'nt'


def _program_files() -> list[Path]:
    return [Path(value) for key in ('ProgramFiles', 'ProgramFiles(x86)')
            if (value := os.environ.get(key))]


def bash_executable() -> str:
    """Use PATH Bash on POSIX; Git Bash on Windows (not System32's WSL launcher)."""
    if not _IS_WINDOWS:
        return 'bash'
    roots = []
    git = shutil.which('git')
    if git:
        roots.append(Path(git).parent.parent)
    roots.extend(folder / 'Git' for folder in _program_files())
    for root in roots:
        for relative in ('bin/bash.exe', 'usr/bin/bash.exe'):
            candidate = root / relative
            if candidate.is_file():
                return str(candidate)
    raise RuntimeError('Git Bash is required on this platform; the WSL launcher is not a native Bash runtime.')
