"""Asset links, tank spaces and frame references of a portable draft package."""
from __future__ import annotations

import math
from pathlib import Path

import numpy as np

from ..provenance import digest_file, write_json
from ..resources import ResourceLimitError
from .glb import copy_metres_glb
from .source import DraftBuild, ExportError, inside, read_json

def display_sources(build: DraftBuild, structure_dir: Path | None) -> list[tuple[Path, str, str]]:
    """Existing display models, in link-preference order; paths in the package are relative."""
    sources = []
    exports = build.result.get("exports") or {}
    for key, target in (("glb", "glb/hull.glb"),
                        ("whole_vessel_glb", "glb/whole-vessel-draft.glb"),
                        ("tanks_glb", "glb/tanks.glb")):
        if not exports.get(key):
            continue
        candidate = inside(build.build_dir, exports[key])
        if candidate.is_file() and not candidate.is_symlink():
            sources.append((candidate, target, exports.get(f"{key}_units", "mm")))
    if structure_dir is not None:
        for candidate in sorted(Path(structure_dir).glob("*_structure.glb")):
            if candidate.is_file() and not candidate.is_symlink():
                sources.append((candidate, f"glb/{candidate.name}", "mm"))
    names = [relative for _, relative, _ in sources]
    if len(names) != len(set(names)):
        raise ExportError("Display GLB files have conflicting package names.")
    return sources


def units_axes(whole_vessel: bool, stl_units: str) -> dict:
    """Distinguish the ship's Z-up coordinates from the GLB's actual Y-up coordinates."""
    return {
        "model": {"units": "m", "up": "z", "x": "forward" if whole_vessel else "along_length_as_drawn",
                  "y": "port" if whole_vessel else "transverse_sign_not_recorded", "z": "up_from_baseline"},
        "glb": {"units": "m", "up": "y", "model_to_glb": ["x", "z", "-y"],
                "glb_to_model": ["x", "-z", "y"]},
        "cad": {"units": "mm", "up": "z", "axes": "model", "formats": ["step", "iges", "3dm"]},
        "stl": {"units": stl_units, "up": "z", "axes": "model"},
    }


def _combined_label(labels) -> str:
    values = {label for label in labels if label}
    return next(iter(values)) if len(values) == 1 else "mixed" if values else "unknown"


def _node_links(document: dict, relative: str) -> dict:
    links = {}
    meshes = document.get("meshes", [])
    for node in document.get("nodes", []):
        if "mesh" not in node or not node.get("name"):
            continue
        name = node["name"]
        if name in links:
            raise ExportError(f"GLB {relative} has duplicate part node {name!r}.")
        extras = {**meshes[node["mesh"]].get("extras", {}), **node.get("extras", {})}
        links[name] = {"glb_file": relative, "node_name": name, "extras": extras}
    return links


def asset_records(build: DraftBuild, identity: dict, tanks: list | None, links: dict) -> dict:
    tank_by_id = {tank.id: tank for tank in tanks or []}
    hull_by_id = {part["id"]: part for part in build.result.get("parts", [])}
    records = {}
    for asset in identity["assets"]:
        part_id, kind = asset["part_id"], asset["kind"]
        link = links.get(part_id) or {}
        extras = link.get("extras") or {}
        sources = dict(extras.get("source_labels") or {})
        label = extras.get("label") or extras.get("group_label") or part_id
        source_label = extras.get("source_label") or _combined_label(sources.values())
        if kind == "tank" and part_id in tank_by_id:
            tank = tank_by_id[part_id]
            label, sources = tank.name, dict(tank.source_labels)
            source_label = sources.get("geometry", "unknown")
        elif kind == "hull":
            label = hull_by_id.get(part_id, {}).get("name") or "Hull"
            source_label = _combined_label(section.get("source_label") for section in build.sections)
        elif kind == "steel_group":
            source_label = _combined_label(member.get("thickness_source") for member in extras.get("members", []))
        records[asset["asset_id"]] = {"part_id": part_id, "kind": kind, "label": label,
                                      "source_label": source_label, "source_labels": sources,
                                      "glb_file": link.get("glb_file"), "node_name": link.get("node_name")}
    return records


def tank_spaces(identity: dict, tanks: list | None) -> list[dict]:
    from ..tanks import content_class

    ids = {asset["part_id"]: asset["asset_id"] for asset in identity["assets"] if asset["kind"] == "tank"}
    spaces = []
    for tank in sorted(tanks or [], key=lambda tank: tank.id):
        if tank.triangles is None or not len(tank.triangles):
            continue
        points = np.asarray(tank.triangles, dtype=float).reshape(-1, 3)
        if not np.isfinite(points).all():
            raise ExportError(f"Tank {tank.id!r} has non-finite space bounds.")
        spaces.append({"asset_id": ids[tank.id], "name": tank.name,
                       "content_class": content_class(tank.content, tank.name),
                       "bounds_m": {"min": points.min(axis=0).tolist(), "max": points.max(axis=0).tolist()},
                       "source": {"geometry": "unknown", **tank.source_labels}})
    return spaces


def frame_record(build: DraftBuild) -> dict:
    """Use a stored frame table; absence is unknown, never the viewer's size-based guess."""
    record = {"spacing_m": None, "zero_x_m": None, "source": "unknown", "source_file": None, "frames": []}
    path = inside(build.task_dir, "frames.json")
    if path.is_file():
        table = read_json(path)
        if not isinstance(table, dict) or table.get("units", "m") != "m":
            raise ExportError("The frame table must be an object with metre units.")
        rows = table.get("frames", [])
        if not isinstance(rows, list):
            raise ExportError("The frame table rows must be a list.")
        for row in rows:
            if (not isinstance(row, dict) or type(row.get("x_m")) not in (int, float)
                    or not math.isfinite(row["x_m"])):
                raise ExportError("Each frame table row must have a finite x_m.")
        for field in ("spacing_m", "zero_x_m"):
            value = table.get(field)
            if value is not None and (type(value) not in (int, float) or not math.isfinite(value)
                                      or (field == "spacing_m" and value <= 0)):
                raise ExportError(f"Invalid frame table {field}.")
            record[field] = value
        record.update(source=table.get("source", "unknown"), frames=rows,
                      source_file="frames.json", source_sha256=digest_file(path))
    return {**record, "units": "m"}


def write_spatial(build: DraftBuild, identity: dict, tanks: list | None, structure_dir: Path | None,
                  out_dir: Path) -> tuple[list[tuple[Path, str, dict]], dict, dict | None]:
    """Write the spatial records and existing GLBs; return manifest entries and units/axes."""
    sources = display_sources(build, structure_dir)
    frames = frame_record(build)
    spaces = tank_spaces(identity, tanks)
    if (out_dir / "frames.json").resolve() == (build.task_dir / "frames.json").resolve():
        raise ExportError("The package frame record must not replace its source table.")
    entries, links, failures = [], {}, []
    copied_whole_vessel = False
    for source, relative, source_units in sources:
        target = out_dir / relative
        if target.parent.is_symlink():
            raise ExportError("The package GLB folder must not be a symbolic link.")
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            document = copy_metres_glb(source, target, source_units)
            node_links = _node_links(document, relative)
            source_hash = digest_file(source)
        except ResourceLimitError:
            raise
        except Exception as error:
            target.unlink(missing_ok=True)
            failures.append(f"{source.name}: {str(error).strip() or type(error).__name__}")
            continue
        for part_id, link in node_links.items():
            links.setdefault(part_id, link)
        copied_whole_vessel |= relative == "glb/whole-vessel-draft.glb"
        entries.append((target, "display_glb", {"units": "m", "source_units": source_units,
                                              "source_sha256": source_hash}))
    records = {"assets.json": ("asset_map", {"assets": asset_records(build, identity, tanks, links)}),
               "spaces.json": ("spaces", {"units": "m", "axes": "model", "spaces": spaces}),
               "frames.json": ("frames", frames)}
    for name, (role, data) in records.items():
        path = out_dir / name
        write_json(path, {"schema_version": "1.0", **data, "engineering_approved": False})
        entries.append((path, role, {}))
    axes = units_axes(copied_whole_vessel, build.stl_units)
    result = ({"status": "failed", "reason": "; ".join(failures)[:1000]} if failures else
              {"status": "ok", "reason": None} if sources else None)
    return entries, axes, result
