"""Immutable package generations with one atomic, durable current-pointer update.

Readers resolve once and keep that generation path for their whole operation.
Old generations are deliberately retained; garbage collection needs a separate
reader-lifetime contract and is not part of publication.
"""
from pathlib import Path
import re
import stat
from uuid import uuid4

from ..provenance import sync_directory, sync_file, write_json
from ..schema import load_bounded_json
from ..transaction import rename_no_replace

_GENERATION = re.compile(r'g-[0-9a-f]{32}')


def _ordinary_directory(path: Path) -> None:
    info = path.lstat()
    if (not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode)
            or getattr(info, 'st_file_attributes', 0) & 0x400):
        raise ValueError('Package generation directories must not be reparse points or links')


def resolve_generation(root: Path) -> Path:
    """Read one bounded pointer and return its immutable generation directory."""
    root = Path(root)
    _ordinary_directory(root)
    pointer = root / 'current.json'
    info = pointer.lstat()
    if (not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode)
            or getattr(info, 'st_file_attributes', 0) & 0x400):
        raise ValueError('Package pointer must be an ordinary file')
    value = load_bounded_json(pointer, max_bytes=4096, max_nodes=10)
    name = value.get('generation') if isinstance(value, dict) else None
    if not isinstance(name, str) or not _GENERATION.fullmatch(name):
        raise ValueError('Invalid package generation pointer')
    folder = root / name
    _ordinary_directory(folder)
    return folder


def resolve_package_folder(root: Path) -> Path:
    """Resolve once; accept a legacy flat package only when no pointer exists."""
    import os
    root = Path(root)
    _ordinary_directory(root)
    if os.path.lexists(root / 'current.json'):
        return resolve_generation(root)
    return root


def publish_generation(root: Path, stage: Path) -> Path:
    """Install a complete sibling stage, then switch readers with one file swap.

    Caller must finish and flush package contents before this operation. A
    failed pointer write retains both the previous pointer and all old files.
    The supplied stage must share the destination volume; no copy fallback.
    """
    root, stage = Path(root), Path(stage)
    root.mkdir(parents=True, exist_ok=True)
    _ordinary_directory(root)
    _ordinary_directory(stage)
    for item in stage.rglob('*'):
        info = item.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
            raise ValueError('Package generations must not contain links or reparse points')
        if stat.S_ISREG(info.st_mode):
            sync_file(item)
    name = 'g-' + uuid4().hex
    destination = root / name
    sync_directory(stage)
    rename_no_replace(stage, destination)
    sync_directory(root)
    write_json(root / 'current.json', {'schema_version': 1, 'generation': name})
    return destination
