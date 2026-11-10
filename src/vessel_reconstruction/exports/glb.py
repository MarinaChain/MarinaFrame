"""Read display-node metadata and make metre-scale copies of the existing GLBs."""
from __future__ import annotations

import json
from pathlib import Path
import struct

from .source import MAX_JSON_BYTES, ExportError

# GLB v2 starts with a 12-byte header and an 8-byte JSON-chunk header.
GLB_JSON_OFFSET = 20
MM_TO_M = 0.001


def read_glb(path: Path) -> tuple[dict, bytes]:
    """Return the JSON document and untouched later chunks (mesh and image buffers)."""
    try:
        with path.open("rb") as stream:
            magic, version, total, size, kind = struct.unpack("<4sIII4s", stream.read(GLB_JSON_OFFSET))
            if (magic != b"glTF" or version != 2 or kind != b"JSON" or total != path.stat().st_size
                    or not 0 < size <= MAX_JSON_BYTES or size > total - GLB_JSON_OFFSET or size % 4):
                raise ValueError("invalid GLB JSON header")
            document = json.loads(stream.read(size))
            if not isinstance(document, dict) or not isinstance(document.get("nodes", []), list):
                raise ValueError("invalid GLB node document")
            if any("uri" in item for field in ("buffers", "images") for item in document.get(field, [])):
                raise ValueError("display GLB refers to external buffers or images")
            return document, stream.read()
    except (OSError, ValueError, TypeError, struct.error) as error:
        raise ExportError(f"Cannot read GLB {path.name}: {error}") from error


def copy_metres_glb(source: Path, target: Path, source_units: str = "mm") -> dict:
    """Scale scene roots, retaining part node names, transforms, materials and binary data."""
    document, chunks = read_glb(source)
    if source_units not in ("mm", "m"):
        raise ExportError(f"Unknown GLB units {source_units!r} for {source.name}.")
    if source.resolve() == target.resolve() or target.is_symlink():
        raise ExportError("A package GLB must not replace its source or a symbolic link.")
    nodes = document.setdefault("nodes", [])
    if source_units == "mm":
        # The display writer names its non-mesh container "world". Some importers
        # reserve that name for their own scene origin and discard its parent transform.
        # Rename only the container; asset mesh-node names stay unchanged.
        for index, node in enumerate(nodes):
            if node.get("name") == "world" and "mesh" not in node:
                node["name"] = f"MarinaFrame_source_world_{index}"
        # Wrapping each scene scales vertex positions and existing node translations together.
        # Changing mesh vertices alone would leave translated parts in the wrong place.
        for index, scene in enumerate(document.get("scenes", [])):
            root = len(nodes)
            nodes.append({"name": f"MarinaFrame_metres_{index}", "scale": [MM_TO_M] * 3,
                          "children": scene.get("nodes", [])})
            scene["nodes"] = [root]
    payload = json.dumps(document, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    payload += b" " * (-len(payload) % 4)  # Every GLB chunk ends on a four-byte boundary.
    header = struct.pack("<4sIII4s", b"glTF", 2, GLB_JSON_OFFSET + len(payload) + len(chunks), len(payload), b"JSON")
    target.write_bytes(header + payload + chunks)
    return document
