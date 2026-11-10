"""Generate the whole-vessel and steel GLB files for the UI mock (?mockglb&mockstructure&mocktanks).

Synthetic shapes for the 24 m survey launch: the hull of mock/files/model.stl, four tanks and a
few steel member groups (shell side plates, deck, five bulkheads, floors, stiffeners). The GLB
files are written to mock/files and are git-ignored (see .gitignore); run this to see the 3D
part tools on the mock.

Run from the repository root:  PYTHONPATH=src .venv/bin/python app/ui/mock/make_whole_vessel_mock.py
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import trimesh

from vessel_reconstruction.display_mesh import PartStyle, tank_style, write_glb
from vessel_reconstruction.structure.display import MEMBER_GROUPS, group_colour

FILES = Path(__file__).resolve().parent / "files"
MM = 1000.0

# (id, name, content, x range, y range, z range) in metres, ship frame (x forward, y port, z up).
TANKS = [
    ("tank_fw1", "No 1 fresh water", "fresh water", (4.0, 7.0), (-1.5, 1.5), (0.2, 1.4)),
    ("tank_wb1", "No 1 ballast port", "water ballast", (13.0, 16.0), (0.2, 2.4), (0.2, 1.3)),
    ("tank_wb2", "No 1 ballast starboard", "water ballast", (13.0, 16.0), (-2.4, -0.2), (0.2, 1.3)),
    ("tank_do1", "Diesel oil", "diesel oil", (17.0, 19.5), (-2.0, 2.0), (0.2, 1.2)),
]
BULKHEAD_X = [3.5, 7.5, 12.5, 16.5, 20.0]


def box(x, y, z) -> trimesh.Trimesh:
    """An axis-aligned box from (min, max) ranges in metres."""
    mesh = trimesh.creation.box(extents=[x[1] - x[0], y[1] - y[0], z[1] - z[0]])
    mesh.apply_translation([(x[0] + x[1]) / 2, (y[0] + y[1]) / 2, (z[0] + z[1]) / 2])
    return mesh


def merged(boxes) -> tuple[np.ndarray, np.ndarray]:
    mesh = trimesh.util.concatenate(boxes)
    return np.asarray(mesh.vertices) * MM, np.asarray(mesh.faces)


def main() -> None:
    hull = trimesh.load(FILES / "model.stl")
    meshes = {"hull": (np.asarray(hull.vertices) * MM, np.asarray(hull.faces))}
    styles = {"hull": PartStyle((0.55, 0.6, 0.66), "hull", {"kind": "hull", "label": "Hull"}, 1.0)}
    for tank_id, name, content, x, y, z in TANKS:
        vertices, faces = merged([box(x, y, z)])
        meshes[tank_id] = (vertices, faces)
        styles[tank_id] = tank_style(name, content, {"name": "read", "volume": "guessed"})
    write_glb(meshes, FILES / "whole-vessel-draft.glb", styles)

    thin = 0.012
    groups = {
        "shell": [box((0.5, 23.5), (-3.3, -3.3 + thin), (0.4, 3.2)), box((0.5, 23.5), (3.3 - thin, 3.3), (0.4, 3.2))],
        "deck": [box((0.5, 23.5), (-3.2, 3.2), (3.2, 3.2 + thin)), box((3.5, 20.0), (-2.6, 2.6), (0.2, 0.2 + thin))],
        "bulkhead": [box((x - thin / 2, x + thin / 2), (-3.0, 3.0), (0.2, 3.2)) for x in BULKHEAD_X],
        "primary": [box((x, x + thin), (-2.8, 2.8), (0.2, 0.9)) for x in np.arange(2.0, 22.0, 1.0)],
        "stiffener": [box((0.5, 23.5), (y, y + 0.05), (3.15, 3.2)) for y in (-2.0, -1.0, 0.0, 1.0, 2.0)],
    }
    steel, steel_styles = {}, {}
    for group, boxes in groups.items():
        name = f"structure_{group}"
        steel[name] = merged(boxes)
        members = [{"id": f"{group}_{i + 1}", "label": f"{group} {i + 1}", "thickness_mm": 8.0,
                    "thickness_source": "guessed", "profile": None} for i in range(len(boxes))]
        steel_styles[name] = PartStyle(group_colour(group), f"steel_{group}", {
            "kind": "structure", "group": group, "group_label": MEMBER_GROUPS[group][0],
            "members": members, "engineering_approved": False})
    write_glb(steel, FILES / "mock_structure.glb", steel_styles)
    print("wrote", FILES / "whole-vessel-draft.glb", FILES / "mock_structure.glb")


if __name__ == "__main__":
    main()
