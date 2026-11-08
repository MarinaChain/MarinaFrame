"""Find and read the draft build of one task revision.

A task folder has ``domain/state.json`` with a list of builds. Each build has
a ``revision_id`` (``r0000``, ``r0001``, ...) and a ``path`` to an immutable
build folder with ``result.json`` and, when CAD was made, the STEP and STL
files. A render folder belongs to a build when its ``observation.json`` audits
the same STEP bytes (same SHA-256); it may hold the station scoreboard and the
station overlay images (see ``station_overlay.py``).

This module only reads. It never writes into the task folder.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
import re

from ..provenance import digest_file

# Largest JSON file read from a task (result.json of a big draft is about 2 MB).
MAX_JSON_BYTES = 64 * 1024**2
REVISION_PATTERN = re.compile(r"^r(\d{1,4})$")
# Characters kept in a file-name part; every other character becomes "-".
FILE_NAME_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")


class ExportError(Exception):
    """The task folder has no usable build for the requested export."""


@dataclass
class DraftBuild:
    """Everything the exports read from one built revision."""

    task_dir: Path
    revision_id: str
    vessel: str
    build_dir: Path
    result: dict
    spec: dict
    guesses: list[dict]
    step_path: Path | None = None
    stl_path: Path | None = None
    stl_units: str = "mm"
    scoreboard: dict | None = None
    overlay_images: list[Path] = field(default_factory=list)

    @property
    def sections(self) -> list[dict]:
        """Built sections, sorted by station position."""
        return sorted(self.result.get("sections", []), key=lambda s: float(s["x_m"]))

    @property
    def file_stem(self) -> str:
        """Common start of every export file name: vessel, revision and DRAFT."""
        return f"{safe_name(self.vessel)}_{self.revision_id}_DRAFT"


def safe_name(text: str) -> str:
    cleaned = FILE_NAME_UNSAFE.sub("-", str(text)).strip("-.")
    return cleaned or "vessel"


def normalise_revision(revision: str) -> str:
    """Accept ``r3`` or ``r0003``; return the task's form ``r0003``."""
    match = REVISION_PATTERN.match(str(revision).strip())
    if match is None:
        raise ExportError(f"Revision must look like r3 or r0003, not {revision!r}.")
    return f"r{int(match.group(1)):04d}"


def read_json(path: Path) -> dict:
    if path.stat().st_size > MAX_JSON_BYTES:
        raise ExportError(f"{path.name} is larger than {MAX_JSON_BYTES} bytes.")
    return json.loads(path.read_text(encoding="utf-8"))


def inside(root: Path, relative: str) -> Path:
    """Resolve ``relative`` under ``root`` and refuse a path that leaves it."""
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ExportError(f"Path {relative!r} leaves the task folder.")
    return path


def domain_root(task_dir: Path) -> Path:
    """The task's ``domain`` folder; ``task_dir`` may also be the domain folder itself."""
    task_dir = Path(task_dir)
    for candidate in (task_dir / "domain", task_dir):
        if (candidate / "state.json").is_file() and (candidate / "builds").is_dir():
            return candidate
    raise ExportError(f"No domain/state.json with builds under {task_dir}.")


def select_build(state: dict, revision_id: str) -> dict:
    """The latest valid draft-or-final build made for ``revision_id``."""
    builds = [b for b in state.get("builds", []) if b.get("revision_id") == revision_id]
    if not builds:
        known = sorted({b.get("revision_id") for b in state.get("builds", [])} - {None})
        raise ExportError(f"No build for revision {revision_id}; built revisions: {', '.join(known) or 'none'}.")
    valid = [b for b in builds if b.get("valid") is True]
    if not valid:
        raise ExportError(f"Revision {revision_id} has no valid build (status: {builds[-1].get('status')}).")
    return valid[-1]


def current_guesses(state: dict, result: dict, revision_id: str) -> list[dict]:
    """Guesses of the build; the task's current list when the revision is still current."""
    if f"r{int(state.get('revision', -1)):04d}" == revision_id and isinstance(state.get("guesses"), list):
        return state["guesses"]
    return (result.get("draft") or {}).get("guesses", [])


def find_render(domain: Path, step_path: Path | None) -> tuple[dict | None, list[Path]]:
    """Scoreboard and overlay images of the render that audited this STEP file."""
    renders = domain / "renders"
    if step_path is None or not renders.is_dir():
        return None, []
    step_sha256 = digest_file(step_path)
    for render in sorted(renders.iterdir()):
        observation = render / "observation.json"
        if not observation.is_file():
            continue
        audit = read_json(observation).get("geometry_audit") or {}
        if audit.get("step_sha256") != step_sha256:
            continue
        scoreboard_path = render / "station-scoreboard.json"
        scoreboard = read_json(scoreboard_path) if scoreboard_path.is_file() else None
        return scoreboard, sorted(render.glob("station-overlay-[0-9]*.png"))
    return None, []


def load_build(task_dir: Path, revision: str, vessel: str | None = None) -> DraftBuild:
    domain = domain_root(task_dir)
    revision_id = normalise_revision(revision)
    state = read_json(domain / "state.json")
    entry = select_build(state, revision_id)
    build_dir = inside(domain.parent, entry["path"])  # The path is relative to the task folder.
    result = read_json(build_dir / "result.json")
    spec_path = domain / "revisions" / revision_id / "spec.json"
    spec = read_json(spec_path) if spec_path.is_file() else {}
    exports = result.get("exports") or {}
    step = inside(build_dir, exports["step"]) if exports.get("step") else None
    stl = inside(build_dir, exports["stl"]) if exports.get("stl") else None
    step = step if step is not None and step.is_file() else None
    stl = stl if stl is not None and stl.is_file() else None
    scoreboard, images = find_render(domain, step)
    name = vessel or spec.get("vessel_name") or result.get("vessel_id") or domain.parent.name
    return DraftBuild(task_dir=domain.parent, revision_id=revision_id, vessel=name, build_dir=build_dir,
                      result=result, spec=spec, guesses=current_guesses(state, result, revision_id),
                      step_path=step, stl_path=stl, stl_units=exports.get("stl_units", "mm"),
                      scoreboard=scoreboard, overlay_images=images)
