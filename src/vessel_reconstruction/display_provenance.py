"""Bind a produced display model to one explicitly selected draft build."""
from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile

from .provenance import digest_file

# Display records contain only short identity and hash fields.
MAX_DISPLAY_RECORD_BYTES = 16 * 1024


def display_record_path(model: Path) -> Path:
    return model.with_name(model.name + ".json")


def check_display_record(model: Path, binding: dict) -> tuple[dict | None, str | None]:
    """Return the record only when it identifies this build and the present bytes."""
    path = display_record_path(model)
    if model.is_symlink() or path.is_symlink():
        return None, "display model or record is a symbolic link"
    if not path.is_file():
        return None, "display model has no build record"
    try:
        if path.stat().st_size > MAX_DISPLAY_RECORD_BYTES:
            return None, "display model record is too large"
        record = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(record, dict) or record.get("schema_version") != "1.0":
            return None, "display model record is invalid"
        if record.get("revision") != binding["revision"]:
            return None, f"display model belongs to revision {record.get('revision')!r}"
        if record.get("build") != binding["build"] or record.get("result_sha256") != binding["result_sha256"]:
            return None, "display model belongs to a different build"
        if record.get("units") not in ("mm", "m") or record.get("sha256") != digest_file(model):
            return None, "display model hash or units do not match its record"
    except (OSError, ValueError, TypeError):
        return None, "display model record cannot be read"
    return record, None


def capture_build(task: Path, revision: str) -> dict:
    """Capture the selected build before producing the model."""
    from .exports.source import load_build

    build = load_build(task, revision)
    return {"task": build.task_dir.resolve(), "revision": build.revision_id,
            "build": build.build_dir.resolve().relative_to(build.task_dir.resolve()).as_posix(),
            "result_sha256": digest_file(build.build_dir / "result.json")}


def bind_display_output(model: Path, task: Path | None, revision: str | None) -> dict | None:
    """Require an explicit binding for a model written inside a task."""
    if (task is None) != (revision is None):
        raise ValueError("Supply both task and revision to bind the display model.")
    model = Path(model).absolute()
    enclosing_task = next((parent for parent in (model.parent, model.parent.parent)
                           if (parent / "domain/state.json").is_file()), None)
    if enclosing_task is not None and task is None:
        raise ValueError("A task display model needs an explicit task and revision.")
    if task is None:
        return None
    binding = capture_build(task, revision)
    if enclosing_task is not None and enclosing_task.resolve() != binding["task"]:
        raise ValueError("The display destination belongs to a different task.")
    return binding


def write_display_record(model: Path, binding: dict) -> None:
    """Record the model bytes only if the same build is still selected."""
    current = capture_build(binding["task"], binding["revision"])
    if current != binding:
        raise ValueError("The selected build changed while making the display model.")
    record = {key: value for key, value in binding.items() if key != "task"}
    record.update(schema_version="1.0", sha256=digest_file(model), units="mm")
    path = display_record_path(model)
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(record, stream, sort_keys=True, indent=2)
            stream.write("\n")
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)
