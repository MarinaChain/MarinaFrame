"""Content-addressed evidence snapshots and replay metadata."""
from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import stat
import tempfile
from importlib import metadata
from pathlib import Path


def digest_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            hasher.update(block)
    return hasher.hexdigest()


def canonical_json(data) -> bytes:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()


def digest_object(data) -> str:
    return hashlib.sha256(canonical_json(data)).hexdigest()


def write_json(path: Path, data) -> None:
    """Durably replace a single JSON file without exposing partial bytes.

    A run is published separately by an atomic directory rename. This primitive
    also protects mutable review history and transaction checkpoints.
    """
    path = Path(path)
    payload = (json.dumps(data, indent=2, ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")
    descriptor, name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        if path.is_symlink():
            raise OSError("Refusing to replace a symbolic-link evidence path.")
        os.replace(temporary, path)
        sync_directory(path.parent)
    finally:
        temporary.unlink(missing_ok=True)


def sync_directory(path: Path) -> None:
    """Linux/POSIX durability boundary for an atomic rename."""
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def sync_file(path: Path) -> None:
    with path.open("rb") as stream:
        os.fsync(stream.fileno())


def safe_relative_file(root: Path, name: str) -> Path:
    """Resolve only ordinary files under the run; never follow any symlink."""
    if (not isinstance(name, str) or not name or len(name) > 4096 or "\\" in name
            or "\x00" in name or name.startswith("/") or any(part in ("", ".", "..") for part in name.split("/"))):
        raise ValueError("Unsafe evidence path.")
    candidate = Path(root)
    for component in name.split("/"):
        candidate = candidate / component
        mode = candidate.lstat().st_mode
        if stat.S_ISLNK(mode):
            raise ValueError("Symbolic links are not evidence files.")
    if not stat.S_ISREG(candidate.stat().st_mode):
        raise ValueError("Evidence must be an ordinary file.")
    return candidate


def implementation_hash() -> str:
    h = hashlib.sha256()
    for path in sorted(Path(__file__).parent.glob("*.py")):
        h.update(path.name.encode())
        h.update(path.read_bytes())
    return h.hexdigest()


def snapshot_implementation(output_dir: Path) -> dict:
    """Retain the exact inference code alongside each replayable result."""
    target = output_dir / "implementation_source" / "vessel_reconstruction"
    target.mkdir(parents=True, exist_ok=True)
    files = {}
    for source in sorted(Path(__file__).parent.glob("*.py")):
        destination = target / source.name
        shutil.copyfile(source, destination)
        files[str(destination.relative_to(output_dir))] = digest_file(destination)
    return {"directory": "implementation_source", "files_sha256": files,
            "implementation_sha256": snapshot_hash(output_dir, files),
            "replay_note": "Set PYTHONDONTWRITEBYTECODE=1 and PYTHONPATH to this implementation_source directory to replay with the recorded Python source and installed recorded dependencies. Write the new run outside this immutable evidence directory. The bytecode flag prevents __pycache__ additions from mutating the original evidence. UI assets and third-party binaries are separately packaged."}


def environment_record() -> dict:
    versions = {}
    for package in ("cadquery", "numpy", "scipy", "pillow"):
        try:
            versions[package] = metadata.version(package)
        except metadata.PackageNotFoundError:
            versions[package] = "not_installed"
    return {"python": platform.python_version(), **versions, "platform": platform.platform()}


def snapshot_hash(root: Path, files: dict) -> str:
    hasher = hashlib.sha256()
    for name in sorted(files):
        path = safe_relative_file(root, name)
        hasher.update(path.name.encode())
        hasher.update(path.read_bytes())
    return hasher.hexdigest()

