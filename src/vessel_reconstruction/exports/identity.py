"""Persistent vessel identity and revision-independent package asset identifiers."""
from __future__ import annotations

import csv
import json
from pathlib import Path
import re
import struct
from uuid import UUID, uuid4, uuid5

from ..file_lock import try_lock_exclusive
from ..provenance import write_json
from .source import MAX_JSON_BYTES, DraftBuild, ExportError, domain_root, inside, read_json

MANIFEST_SCHEMA_VERSION = "1.0"
# The first six IMO digits have these weights; the seventh is the sum modulo ten.
IMO_WEIGHTS = (7, 6, 5, 4, 3, 2)
PARTICULAR_FIELDS = ("vessel_name", "loa_m", "lpp_m", "beam_m", "depth_m", "draft_m", "scale")


def checked_imo(value) -> str | None:
    """Return a typed IMO as seven ASCII digits; never infer or repair a number."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    if not isinstance(value, str):
        raise ExportError("IMO must be typed as seven digits, optionally prefixed with IMO.")
    match = re.fullmatch(r"(?:IMO\s*)?([0-9]{7})", value.strip(), re.IGNORECASE)
    if match is None:
        raise ExportError("IMO must contain seven ASCII digits, optionally prefixed with IMO.")
    number = match.group(1)
    checksum = sum(int(digit) * weight for digit, weight in zip(number[:6], IMO_WEIGHTS)) % 10
    if checksum != int(number[-1]):
        raise ExportError("IMO check digit does not match the first six digits.")
    return number


def _checked_uuid(value) -> str:
    try:
        return str(UUID(value))
    except (ValueError, TypeError, AttributeError) as error:
        raise ExportError("The stored vessel identity is not a UUID.") from error


def vessel_uuid(domain: Path, state: dict) -> str:
    """Use the domain UUID; give legacy runs a sidecar without changing their pinned state."""
    if "vessel_uuid" in state:
        return _checked_uuid(state["vessel_uuid"])
    path = inside(domain, "vessel_identity.json")
    lock_path = inside(domain, ".vessel_identity.lock")
    try:
        with lock_path.open("a+b") as lock:
            try_lock_exclusive(lock)
            if path.exists():
                return _checked_uuid(read_json(path).get("vessel_id"))
            identity = str(uuid4())
            write_json(path, {"vessel_id": identity})
            return identity
    except (OSError, ValueError) as error:
        raise ExportError(f"Cannot read or store vessel identity: {error}") from error


def known_particulars(build: DraftBuild, domain: Path, state: dict) -> dict:
    """Typed intake values, with known spec constraints as fallbacks; no model guesses."""
    intake_file = (state.get("intake") or {}).get("file", "intake.json")
    intake_path = inside(domain / "input", intake_file)
    typed = {}
    if intake_path.is_file():
        typed = read_json(intake_path).get("particulars") or {}
    particulars = {field: typed[field] for field in PARTICULAR_FIELDS if typed.get(field) not in (None, "")}
    if "vessel_name" not in particulars and build.spec.get("vessel_name"):
        particulars["vessel_name"] = build.spec["vessel_name"]
    constraints = build.spec.get("constraints") or {}
    for field in ("length_m", "beam_m", "depth_m"):
        if constraints.get(field) is not None:
            particulars.setdefault(field, constraints[field])
    if build.spec.get("design_draft_m") is not None:
        particulars.setdefault("draft_m", build.spec["design_draft_m"])
    imo = checked_imo(typed.get("imo"))
    if imo is not None:
        particulars["imo"] = imo
    return particulars


def _glb_part_ids(path: Path) -> set[str]:
    """Read node IDs from the GLB JSON chunk without loading its mesh buffers."""
    try:
        with path.open("rb") as stream:
            magic, version, total_bytes, json_bytes, chunk_type = struct.unpack("<4sIII4s", stream.read(20))
            if (magic != b"glTF" or version != 2 or chunk_type != b"JSON"
                    or total_bytes != path.stat().st_size or not 0 < json_bytes <= MAX_JSON_BYTES
                    or json_bytes > total_bytes - 20):
                raise ValueError("invalid GLB JSON header")
            document = json.loads(stream.read(json_bytes))
        return {node["name"] for node in document.get("nodes", [])
                if "mesh" in node and node.get("name", "").startswith("structure_")}
    except (OSError, ValueError, struct.error) as error:
        raise ExportError(f"Cannot read steel asset identity from {path.name}: {error}") from error


def _steel_part_ids(structure_dir: Path | None) -> set[str]:
    """Use existing display node IDs, or table labels when no display GLB exists."""
    from ..structure.display import member_group

    groups = set()
    if structure_dir is not None:
        models = [path for path in sorted(Path(structure_dir).glob("*_structure.glb")) if not path.is_symlink()]
        if models:
            for model in models:
                groups.update(_glb_part_ids(model))
            return groups
        for table in sorted(Path(structure_dir).glob("*_steel_members.csv")):
            if table.is_symlink():
                continue
            with table.open(encoding="utf-8", newline="") as stream:
                rows = csv.DictReader(line for line in stream if not line.startswith("#"))
                for row in rows:
                    if row.get("member_id"):
                        member = {"label": row.get("label"), "profile": row.get("profile"),
                                  "trace": bool(row.get("profile"))}
                        groups.add("structure_" + member_group(member))
    return groups


def manifest_identity(build: DraftBuild, tanks: list | None, structure_dir: Path | None) -> dict:
    domain = domain_root(build.task_dir)
    state = read_json(domain / "state.json")
    # Validate the typed IMO before creating an identity or any export files.
    particulars = known_particulars(build, domain, state)
    identity = vessel_uuid(domain, state)
    hull_ids = {part["id"] for part in build.result.get("parts", []) if part.get("kind") == "hull_envelope"}
    parts = [("hull", part_id) for part_id in sorted(hull_ids or {"hull"})]
    parts += [("tank", tank.id) for tank in tanks or []]
    parts += [("steel_group", part_id) for part_id in sorted(_steel_part_ids(structure_dir))]
    if len(set(parts)) != len(parts):
        raise ExportError("Asset part IDs must be unique within each kind.")
    assets = [{"asset_id": str(uuid5(UUID(identity), f"{kind}:{part_id}")), "kind": kind, "part_id": part_id}
              for kind, part_id in sorted(parts)]
    # Domain edits increment a linear counter, including revisions that did not build.
    revision_number = int(build.revision_id[1:])
    parent = f"r{revision_number - 1:04d}" if revision_number else None
    record = {"schema_version": MANIFEST_SCHEMA_VERSION, "vessel_id": identity,
              "parent_revision": parent, "particulars": particulars, "assets": assets}
    if "imo" in particulars:
        record["imo"] = particulars["imo"]
    return record
