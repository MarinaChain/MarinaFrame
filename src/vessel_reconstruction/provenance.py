"""Content-addressed evidence snapshots and replay metadata."""
from __future__ import annotations

import hashlib
import json
import platform
import shutil
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
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")


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
            "replay_note": "Set PYTHONPATH to this implementation_source directory to replay inference with the recorded Python source and installed recorded dependencies. UI assets and third-party binaries are separately packaged."}


def environment_record() -> dict:
    import cadquery, numpy, scipy, PIL
    return {"python": platform.python_version(), "cadquery": cadquery.__version__, "numpy": numpy.__version__, "scipy": scipy.__version__, "pillow": PIL.__version__, "platform": platform.platform()}

