"""Planar faces of a closed tank mesh, for the OCX ``CompartmentFace`` elements.

A tank solid is a triangle mesh. OCX describes a compartment by its bounding faces, so adjacent
coplanar triangles are merged into one face and each face gets its boundary loops. A curved
(lofted) tank has many small faces; in the worst case one per triangle.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

# Two triangles are in one plane when their unit normals agree to this dot product (1 - 1e-9 is
# about 0.003 degrees) and their plane offsets differ by less than PLANE_TOLERANCE_M.
NORMAL_DOT_MIN = 1.0 - 1e-9
PLANE_TOLERANCE_M = 1e-6
# Vertices that agree after rounding to this many decimals (1 micrometre) are one vertex.
VERTEX_DIGITS = 6
# A loop vertex is dropped when the turn there is straight to this sine (collinear points).
STRAIGHT_SINE = 1e-9


@dataclass(frozen=True)
class Face:
    normal: tuple[float, float, float]  # unit, pointing out of the tank
    loops: list[list[tuple[float, float, float]]]  # closed loops (first point not repeated); outer loop first


def _vertex_table(triangles: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Shared vertex table of the mesh: (points, triangle corner indices of shape n x 3)."""
    rounded = np.round(triangles.reshape(-1, 3), VERTEX_DIGITS) + 0.0  # + 0.0 turns -0.0 into 0.0
    points, inverse = np.unique(rounded, axis=0, return_inverse=True)
    return points, inverse.reshape(-1, 3)


def _triangle_edges(corner: np.ndarray) -> list[tuple[int, int]]:
    p, q, r = (int(i) for i in corner)
    return [(p, q), (q, r), (r, p)]


def _plane_groups(points: np.ndarray, corners: np.ndarray) -> list[list[int]]:
    """Triangle indices grouped into connected coplanar regions (degenerate triangles are dropped)."""
    a, b, c = (points[corners[:, i]] for i in range(3))
    cross = np.cross(b - a, c - a)
    length = np.linalg.norm(cross, axis=1)
    normals = np.divide(cross, length[:, None], out=np.zeros_like(cross), where=length[:, None] > 0)
    offsets = np.einsum("ij,ij->i", normals, a)
    parent = list(range(len(corners)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    edge_owner: dict[tuple[int, int], int] = {}
    for t, corner in enumerate(corners):
        if length[t] == 0:
            continue
        for edge in _triangle_edges(corner):
            neighbour = edge_owner.get(edge[::-1])
            if (neighbour is not None and normals[t] @ normals[neighbour] >= NORMAL_DOT_MIN
                    and abs(offsets[t] - offsets[neighbour]) <= PLANE_TOLERANCE_M):
                parent[find(t)] = find(neighbour)
            edge_owner[edge] = t
    groups: dict[int, list[int]] = {}
    for t in range(len(corners)):
        if length[t] > 0:
            groups.setdefault(find(t), []).append(t)
    return list(groups.values())


def _boundary_loops(corners: np.ndarray, group: list[int]) -> list[list[int]]:
    """Closed vertex loops around a set of triangles: the edges whose reverse is not in the set."""
    directed = {edge for t in group for edge in _triangle_edges(corners[t])}
    outgoing: dict[int, list[int]] = {}
    for p, q in sorted(edge for edge in directed if edge[::-1] not in directed):
        outgoing.setdefault(p, []).append(q)
    loops = []
    while outgoing:
        start = next(iter(outgoing))
        loop, here = [start], start
        while True:
            targets = outgoing.get(here)
            if not targets:
                break  # an open chain (the mesh is not closed here): keep what was found
            there = targets.pop(0)
            if not targets:
                del outgoing[here]
            if there == start:
                break
            loop.append(there)
            here = there
        loops.append(loop)
    return loops


def _without_collinear(loop: list[np.ndarray]) -> list[np.ndarray]:
    kept = []
    for k, point in enumerate(loop):
        before, after = loop[k - 1], loop[(k + 1) % len(loop)]
        turn = np.linalg.norm(np.cross(point - before, after - point))
        scale = np.linalg.norm(point - before) * np.linalg.norm(after - point)
        if scale > 0 and turn / scale > STRAIGHT_SINE:
            kept.append(point)
    return kept


def _loop_area(loop: list[np.ndarray], normal: np.ndarray) -> float:
    """Area of a loop (positive when it runs counter-clockwise seen from outside along ``normal``)."""
    total = sum(np.cross(p, q) for p, q in zip(loop, loop[1:] + loop[:1]))
    return float(total @ normal) / 2


def planar_faces(triangles: np.ndarray) -> list[Face]:
    """Merge the coplanar triangles of an outward-oriented closed mesh into faces.

    Each face keeps its boundary loops, outer loop (largest area) first; loops have at least 3 points.
    """
    if len(triangles) == 0:
        return []
    points, corners = _vertex_table(triangles)
    faces = []
    for group in _plane_groups(points, corners):
        first = points[corners[group[0]]]
        normal = np.cross(first[1] - first[0], first[2] - first[0])
        normal = normal / np.linalg.norm(normal)
        loops = []
        for loop in _boundary_loops(corners, group):
            cleaned = _without_collinear([points[i] for i in loop])
            if len(cleaned) >= 3:
                loops.append(cleaned)
        if not loops:
            continue
        loops.sort(key=lambda loop: -abs(_loop_area(loop, normal)))
        faces.append(Face(tuple(float(v) for v in normal),
                          [[tuple(float(v) for v in p) for p in loop] for loop in loops]))
    return faces


def patch_corners(face: Face) -> list[tuple[float, float, float]]:
    """Corners of the in-plane bounding rectangle of a face, ordered (u0 v0), (u1 v0), (u0 v1), (u1 v1).

    The rectangle is the bilinear surface the samples give each face (the boundary curve trims it).
    u runs along the first edge of the outer loop; v is the face normal crossed with u.
    """
    outer = np.array(face.loops[0])
    normal = np.array(face.normal)
    u_axis = outer[1] - outer[0]
    u_axis = u_axis / np.linalg.norm(u_axis)
    v_axis = np.cross(normal, u_axis)
    every = np.array([p for loop in face.loops for p in loop])
    u_values, v_values = (every - outer[0]) @ u_axis, (every - outer[0]) @ v_axis
    u0, u1, v0, v1 = u_values.min(), u_values.max(), v_values.min(), v_values.max()
    return [tuple(float(x) for x in outer[0] + u * u_axis + v * v_axis)
            for u, v in ((u0, v0), (u1, v0), (u0, v1), (u1, v1))]
