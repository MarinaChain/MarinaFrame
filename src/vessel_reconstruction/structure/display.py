"""Display meshes of structure members for the app's 3D view and the structure GLB.

Members use the block-member dictionary of ``extrude`` (ship metres): a plate has a ``contour``
(3D points in order) and a thickness; a stiffener has a ``trace`` (3D polyline), a ``profile``
(``FlatBar``, ``BulbFlat``, ``TBar`` or ``LBar``) and a ``web_direction``. A plate becomes a slab
of its thickness about its contour; a stiffener becomes its section swept along its trace. The
meshes are for viewing only: contours and traces are thinned to DISPLAY_TOLERANCE_M and a bulb is
drawn as a small flange. Weights and the OCX file keep using the members themselves.

The GLB has one node per member group (shell, decks, bulkheads, primary members, stiffeners), each
one merged mesh with a material by group, so the view stays light. Its extras list the members of
the group with their thickness and its source label; ``engineering_approved`` is false.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

from ..tanks import triangulate_polygon

# Contours and traces are thinned to this chord tolerance (m) for display.
DISPLAY_TOLERANCE_M = 0.002
# A bulb flat is drawn as a web with a small flange on one side: this share of the web thickness
# wide and this share of the height deep (a display shape, not a section table).
BULB_WIDTH_SHARE = 1.2
BULB_DEPTH_SHARE = 0.18
# Member groups in legend order: label words of the members (``extrude``/``structure_3d``), the
# legend text and the colour (app tokens ``--steel-<group>`` in app/ui/styles.css hold the same).
MEMBER_GROUPS = {
    "shell": ("Shell plating", "#7F96AE", ("shell", "strake", "keel")),
    "deck": ("Decks and inner bottom", "#C9B47E", ("deck", "inner_bottom", "tank_top", "platform")),
    "bulkhead": ("Bulkheads", "#A58BB5", ("bulkhead",)),
    "primary": ("Floors, girders, web frames", "#CF8562", ("floor", "girder", "web", "stringer")),
    "stiffener": ("Frames, beams, stiffeners", "#4F7A64", ("frame", "beam", "stiffener", "longitudinal")),
}


def member_group(member: dict) -> str:
    """Display group of a member: a stiffener by its profile, else by its label words."""
    label = (member.get("label") or "").lower()
    if member.get("trace") and member.get("profile"):
        # A girder or a web frame drawn as a profile is still a primary member.
        return "primary" if "girder" in label or "web" in label else "stiffener"
    for group, (_, _, words) in MEMBER_GROUPS.items():
        if group != "stiffener" and any(word in label for word in words):
            return group
    return "primary"


def group_colour(group: str) -> tuple[float, float, float]:
    hex_colour = MEMBER_GROUPS[group][1]
    return tuple(int(hex_colour[i:i + 2], 16) / 255 for i in (1, 3, 5))


# --- thinning ------------------------------------------------------------------------------

def thin_polyline(points: np.ndarray, tolerance: float) -> np.ndarray:
    """Douglas-Peucker: the points of an open polyline that keep it within ``tolerance``."""
    if len(points) <= 2:
        return points
    keep = np.zeros(len(points), bool)
    keep[[0, -1]] = True
    stack = [(0, len(points) - 1)]
    while stack:
        first, last = stack.pop()
        if last - first < 2:
            continue
        a, b = points[first], points[last]
        chord = b - a
        length2 = float(chord @ chord)
        inner = points[first + 1:last]
        if length2 < 1e-18:
            distances = np.linalg.norm(inner - a, axis=1)
        else:
            t = np.clip((inner - a) @ chord / length2, 0.0, 1.0)
            distances = np.linalg.norm(inner - (a + t[:, None] * chord), axis=1)
        worst = int(np.argmax(distances))
        if distances[worst] > tolerance:
            middle = first + 1 + worst
            keep[middle] = True
            stack += [(first, middle), (middle, last)]
    return points[keep]


def thin_polygon(points: np.ndarray, tolerance: float) -> np.ndarray:
    """A closed polygon thinned like ``thin_polyline``, split at its point farthest from the first."""
    if len(points) <= 4:
        return points
    far = int(np.argmax(np.linalg.norm(points - points[0], axis=1)))
    first = thin_polyline(points[:far + 1], tolerance)
    second = thin_polyline(np.concatenate([points[far:], points[:1]]), tolerance)
    return np.concatenate([first, second[1:-1]])


# --- plates --------------------------------------------------------------------------------

def _newell_normal(points: np.ndarray) -> np.ndarray:
    following = np.roll(points, -1, axis=0)
    normal = np.array([
        np.sum((points[:, 1] - following[:, 1]) * (points[:, 2] + following[:, 2])),
        np.sum((points[:, 2] - following[:, 2]) * (points[:, 0] + following[:, 0])),
        np.sum((points[:, 0] - following[:, 0]) * (points[:, 1] + following[:, 1])),
    ])
    length = np.linalg.norm(normal)
    return normal / length if length > 0 else np.array([0.0, 0.0, 1.0])


def plate_triangles(contour, thickness_m: float) -> np.ndarray:
    """A plate as a closed slab: the contour offset by half the thickness to each side of its
    mean plane (Newell normal), the faces triangulated in that plane. Empty for a degenerate one."""
    points = np.asarray(contour, dtype=float)
    points = points[np.r_[True, np.linalg.norm(np.diff(points, axis=0), axis=1) > 1e-9]]
    if len(points) > 1 and np.linalg.norm(points[0] - points[-1]) <= 1e-9:
        points = points[:-1]
    points = thin_polygon(points, DISPLAY_TOLERANCE_M)
    if len(points) < 3:
        return np.zeros((0, 3, 3))
    normal = _newell_normal(points)
    u = np.cross(normal, [1.0, 0.0, 0.0] if abs(normal[0]) < 0.9 else [0.0, 1.0, 0.0])
    u /= np.linalg.norm(u)
    v = np.cross(normal, u)
    flat = np.column_stack([points @ u, points @ v])  # counter-clockwise about the normal
    result = triangulate_polygon(flat)
    if result.fallback_reason:
        raise ValueError(result.fallback_reason)
    faces = np.array(result.triangles)
    half = normal * max(thickness_m, 1e-4) / 2
    top, bottom = points + half, points - half
    triangles = [top[faces], bottom[faces][:, ::-1]]
    following = np.roll(np.arange(len(points)), -1)
    triangles.append(np.stack([bottom, bottom[following], top[following]], axis=1))
    triangles.append(np.stack([bottom, top[following], top], axis=1))
    return np.concatenate(triangles)


# --- stiffeners ----------------------------------------------------------------------------

def section_outline(profile: dict) -> np.ndarray:
    """Section polygon (s across the web, w along the web from the plate) in metres, counter-clockwise."""
    height = profile["height_mm"] / 1000
    web = profile["web_mm"] / 1000
    kind = profile.get("kind")
    if kind == "TBar":
        flange, thick = profile["flange_width_mm"] / 1000, profile["flange_thickness_mm"] / 1000
        return np.array([[-web / 2, 0], [web / 2, 0], [web / 2, height - thick], [flange / 2, height - thick],
                         [flange / 2, height], [-flange / 2, height], [-flange / 2, height - thick],
                         [-web / 2, height - thick]])
    if kind in ("LBar", "BulbFlat"):
        if kind == "LBar":
            flange, thick = profile["flange_width_mm"] / 1000, profile["flange_thickness_mm"] / 1000
        else:
            flange, thick = web * (1 + BULB_WIDTH_SHARE), height * BULB_DEPTH_SHARE
        return np.array([[-web / 2, 0], [web / 2, 0], [web / 2, height - thick], [flange - web / 2, height - thick],
                         [flange - web / 2, height], [-web / 2, height]])
    return np.array([[-web / 2, 0], [web / 2, 0], [web / 2, height], [-web / 2, height]])  # flat bar


def stiffener_triangles(trace, profile: dict, web_direction) -> np.ndarray:
    """A stiffener as its section swept along its trace (the web along ``web_direction``)."""
    points = thin_polyline(np.asarray(trace, dtype=float), DISPLAY_TOLERANCE_M)
    points = points[np.r_[True, np.linalg.norm(np.diff(points, axis=0), axis=1) > 1e-9]]
    if len(points) < 2:
        return np.zeros((0, 3, 3))
    segments = np.diff(points, axis=0)
    segments /= np.linalg.norm(segments, axis=1)[:, None]
    # Tangent at each point: the mean of its segments (a mitre at a bend).
    tangents = np.concatenate([segments[:1], segments[:-1] + segments[1:], segments[-1:]])
    tangents /= np.maximum(np.linalg.norm(tangents, axis=1), 1e-12)[:, None]
    section = section_outline(profile)
    rings = []
    for point, tangent in zip(points, tangents):
        w = np.asarray(web_direction, dtype=float) - (np.dot(web_direction, tangent)) * tangent
        if np.linalg.norm(w) < 1e-9:  # web along the trace: take any perpendicular
            w = np.cross(tangent, [0.0, 0.0, 1.0] if abs(tangent[2]) < 0.9 else [1.0, 0.0, 0.0])
        w /= np.linalg.norm(w)
        s = np.cross(tangent, w)
        rings.append(point + section[:, :1] * s + section[:, 1:] * w)
    rings = np.stack(rings)
    count = len(section)
    k, k_next = np.arange(count), (np.arange(count) + 1) % count
    triangles = []
    for a, b in zip(rings, rings[1:]):
        triangles.append(np.stack([a[k], b[k], b[k_next]], axis=1))
        triangles.append(np.stack([a[k], b[k_next], a[k_next]], axis=1))
    result = triangulate_polygon(section)
    if result.fallback_reason:
        raise ValueError(result.fallback_reason)
    cap = np.array(result.triangles)
    triangles += [rings[0][cap], rings[-1][cap][:, ::-1]]
    return np.concatenate(triangles)


def member_triangles(member: dict) -> np.ndarray:
    if member.get("trace") and member.get("profile"):
        return stiffener_triangles(member["trace"], member["profile"], member.get("web_direction") or (0, 0, 1))
    if member.get("contour"):
        return plate_triangles(member["contour"], (member.get("thickness_mm") or 0.0) / 1000)
    return np.zeros((0, 3, 3))


# --- GLB -----------------------------------------------------------------------------------

def group_meshes(members: list[dict]) -> dict[str, tuple[np.ndarray, np.ndarray, list[dict]]]:
    """Per member group: vertices (mm), triangles and the member records of the merged mesh."""
    pieces: dict[str, list] = {}
    records: dict[str, list] = {}
    for member in members:
        triangles = member_triangles(member)
        if not len(triangles):
            continue
        group = member_group(member)
        pieces.setdefault(group, []).append(triangles)
        profile = member.get("profile") or {}
        records.setdefault(group, []).append({
            "id": member["member_id"], "label": member.get("label"), "thickness_mm": member.get("thickness_mm"),
            "thickness_source": member.get("thickness_source"), "profile": profile.get("name")})
    meshes = {}
    for group in MEMBER_GROUPS:
        if group not in pieces:
            continue
        triangles = np.concatenate(pieces[group]) * 1000.0
        meshes[group] = (triangles.reshape(-1, 3), np.arange(len(triangles) * 3).reshape(-1, 3), records[group])
    return meshes


def write_structure_glb(members: list[dict], path: Path) -> dict[str, int]:
    """The structure GLB (mm, glTF Y-up): one node ``structure_<group>`` per member group, with a
    material by group and extras (kind "structure", group, members with their thickness source).
    Returns the member count per group."""
    from ..display_mesh import PartStyle, write_glb

    meshes, styles, counts = {}, {}, {}
    for group, (vertices, faces, records) in group_meshes(members).items():
        name = f"structure_{group}"
        meshes[name] = (vertices, faces)
        styles[name] = PartStyle(group_colour(group), f"steel_{group}", {
            "kind": "structure", "group": group, "group_label": MEMBER_GROUPS[group][0],
            "members": records, "engineering_approved": False})
        counts[group] = len(records)
    write_glb(meshes, Path(path), styles)
    return counts
