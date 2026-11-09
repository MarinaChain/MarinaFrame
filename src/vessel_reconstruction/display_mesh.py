"""Display meshes and the whole-vessel GLB, separate from the STEP geometry.

The STEP keeps the exact model. The app's 3D view needs only a light mesh. The kernel
mesher is not reliable on a hull side that is one B-spline face of many spans (at a
coarse setting it leaves holes: on Gunnerus, 18 % of the volume was missing). A
degree-1 B-spline face is a grid of bilinear patches, so its mesh comes from its own
poles: ring columns that stay inside the display tolerance at every station are left
out, and each remaining cell gives two triangles. Other faces (planes, ruled panels,
end caps) use the kernel mesher.

The GLB follows the app contract (docs/APP_SPEC.md "Whole-vessel parts"): millimetres,
Y-up (glTF), one node per part named by its id.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np


def _decimated_columns(grid: np.ndarray, tolerance_mm: float) -> list[int]:
    """Ring columns to keep: a dropped column is within tolerance of the chord at every station.

    ``grid`` is ring vertices x stations x 3 (mm). The first and last columns stay.
    """
    count = grid.shape[0]
    kept = [0]
    start = 0
    while start < count - 1:
        end = start + 1
        while end + 1 < count:
            candidate = end + 1
            a, b = grid[start], grid[candidate]  # stations x 3 each
            inner = grid[start + 1:candidate]  # k x stations x 3
            chord = b - a
            length2 = np.maximum((chord ** 2).sum(axis=1), 1e-12)
            t = np.clip(((inner - a) * chord).sum(axis=2) / length2, 0.0, 1.0)
            nearest = a + t[..., None] * chord
            if np.linalg.norm(inner - nearest, axis=2).max() > tolerance_mm:
                break
            end = candidate
        kept.append(end)
        start = end
    return kept


def _bspline_grid(face):
    """Poles of a degree-1 B-spline face (ring x stations x 3) and whether the ring is periodic."""
    from OCP.BRep import BRep_Tool
    from OCP.GeomAdaptor import GeomAdaptor_Surface
    from OCP.GeomAbs import GeomAbs_BSplineSurface

    surface = BRep_Tool.Surface_s(face.wrapped)
    adaptor = GeomAdaptor_Surface(surface)
    if adaptor.GetType() != GeomAbs_BSplineSurface:
        return None
    spline = adaptor.BSpline()
    if spline.UDegree() != 1 or spline.VDegree() != 1:
        return None
    grid = np.array([[spline.Pole(u, v).Coord() for v in range(1, spline.NbVPoles() + 1)]
                     for u in range(1, spline.NbUPoles() + 1)])
    return grid, spline.IsUPeriodic()


def _grid_triangles(grid: np.ndarray, periodic: bool, tolerance_mm: float) -> tuple[np.ndarray, np.ndarray]:
    if periodic:
        grid = np.concatenate([grid, grid[:1]], axis=0)
    columns = _decimated_columns(grid, tolerance_mm)
    kept = grid[columns]
    rings, stations = kept.shape[:2]
    vertices = kept.reshape(-1, 3)
    index = np.arange(rings * stations).reshape(rings, stations)
    a, b = index[:-1, :-1].ravel(), index[1:, :-1].ravel()
    c, d = index[1:, 1:].ravel(), index[:-1, 1:].ravel()
    triangles = np.concatenate([np.column_stack([a, b, c]), np.column_stack([a, c, d])])
    # Leave out triangles of zero area (repeated poles).
    p = vertices[triangles]
    area2 = np.linalg.norm(np.cross(p[:, 1] - p[:, 0], p[:, 2] - p[:, 0]), axis=1)
    return vertices, triangles[area2 > 1e-9]


def _face_triangles(face, tolerance_mm: float, angular_rad: float) -> tuple[np.ndarray, np.ndarray]:
    points, faces = face.tessellate(tolerance_mm, angular_rad)
    return np.array([[p.x, p.y, p.z] for p in points]).reshape(-1, 3), np.asarray(faces, dtype=int).reshape(-1, 3)


def _polygon_cap(face):
    """A planar face bounded by one degree-1 B-spline curve, as a polygon face (or None).

    The kernel mesher puts few points on such a long curve at display tolerances, so the
    cap would not meet the side. The curve's poles are the polygon vertices.
    """
    import cadquery as cq
    from OCP.BRepAdaptor import BRepAdaptor_Curve
    from OCP.GeomAbs import GeomAbs_BSplineCurve

    edges = face.Edges()
    if face.geomType() != 'PLANE' or len(edges) != 1:
        return None
    curve = BRepAdaptor_Curve(edges[0].wrapped)
    if curve.GetType() != GeomAbs_BSplineCurve or curve.BSpline().Degree() != 1:
        return None
    spline = curve.BSpline()
    points = [spline.Pole(i).Coord() for i in range(1, spline.NbPoles() + 1)]
    clean = [points[0]]
    for point in points[1:]:
        if np.linalg.norm(np.subtract(point, clean[-1])) > 1e-7:
            clean.append(point)
    if np.linalg.norm(np.subtract(clean[0], clean[-1])) <= 1e-7:
        clean.pop()
    if len(clean) < 3:
        return None
    return cq.Face.makeFromWires(cq.Wire.makePolygon([cq.Vector(*p) for p in clean], close=True))


def shape_mesh(shape, tolerance_mm: float, angular_rad: float) -> tuple[np.ndarray, np.ndarray]:
    """One display mesh (vertices in mm, triangles) for a CadQuery shape, faces oriented outward."""
    from OCP.TopAbs import TopAbs_REVERSED

    all_vertices, all_triangles, offset = [], [], 0
    for face in shape.Faces():
        bspline = _bspline_grid(face)
        if bspline is not None:
            vertices, triangles = _grid_triangles(*bspline, tolerance_mm)
            if face.wrapped.Orientation() == TopAbs_REVERSED:
                triangles = triangles[:, ::-1]
        else:
            vertices, triangles = _face_triangles(_polygon_cap(face) or face, tolerance_mm, angular_rad)
            if _polygon_cap(face) is not None and len(triangles):
                # Keep the outward side of the original cap face.
                p = vertices[triangles[0]]
                if np.dot(np.cross(p[1] - p[0], p[2] - p[0]), face.normalAt().toTuple()) < 0:
                    triangles = triangles[:, ::-1]
        all_vertices.append(vertices)
        all_triangles.append(triangles + offset)
        offset += len(vertices)
    if not all_vertices:
        return np.zeros((0, 3)), np.zeros((0, 3), dtype=int)
    return np.concatenate(all_vertices), np.concatenate(all_triangles)


# A ring corner sharper than this (turning angle) gets its own vertices on each side, so the
# shading shows the edge (a tank top meeting its side); smaller turns are shaded smooth.
CREASE_ANGLE_DEG = 35.0


def _ring_creases(ring_grid: np.ndarray) -> list[int]:
    """Ring indices where the ring turns more than CREASE_ANGLE_DEG at any station."""
    incoming = ring_grid - np.roll(ring_grid, 1, axis=0)  # ring x stations x 3
    outgoing = np.roll(ring_grid, -1, axis=0) - ring_grid
    lengths = np.linalg.norm(incoming, axis=2) * np.linalg.norm(outgoing, axis=2)
    cosine = np.where(lengths > 1e-12, (incoming * outgoing).sum(axis=2) / np.maximum(lengths, 1e-12), 1.0)
    sharp = (cosine < np.cos(np.radians(CREASE_ANGLE_DEG))).any(axis=1)
    return [int(k) for k in np.flatnonzero(sharp)]


def loft_mesh(runs_m: list[np.ndarray], cap_triangles, tolerance_mm: float) -> tuple[np.ndarray, np.ndarray]:
    """Display mesh (vertices in mm, triangles) of a lofted solid, faces outward.

    ``runs_m`` are (stations, ring points, 3) arrays in metres (``tanks.TankLoft.runs``);
    ``cap_triangles(ring_size)`` gives the ring indices of an end cap in ring order. The side is
    split into strips at the ring creases; each strip is a grid mesh whose columns are thinned
    to ``tolerance_mm`` and whose vertices are shared, so the side is shaded smooth.
    """
    all_vertices, all_triangles, offset = [], [], 0

    def add(vertices, triangles):
        nonlocal offset
        all_vertices.append(vertices)
        all_triangles.append(triangles + offset)
        offset += len(vertices)

    for run in runs_m:
        grid = np.transpose(run, (1, 0, 2)) * 1000.0  # ring x stations x 3, mm
        creases = _ring_creases(grid) or [0]
        ring_size = len(grid)
        for start, end in zip(creases, creases[1:] + [creases[0] + ring_size]):
            columns = [k % ring_size for k in range(start, end + 1)]
            add(*_grid_triangles(grid[columns], False, tolerance_mm))
        cap = np.asarray(cap_triangles(ring_size))
        add(grid[:, 0], cap[:, ::-1])
        add(grid[:, -1], cap)
    if not all_vertices:
        return np.zeros((0, 3)), np.zeros((0, 3), dtype=int)
    vertices, triangles = np.concatenate(all_vertices), np.concatenate(all_triangles)
    if mesh_volume_mm3(vertices, triangles) < 0:
        triangles = triangles[:, ::-1]
    return vertices, triangles


def mesh_volume_mm3(vertices: np.ndarray, triangles: np.ndarray) -> float:
    """Signed volume of a closed triangle mesh (divergence theorem)."""
    p = vertices[triangles]
    return float(np.einsum('ij,ij->i', p[:, 0], np.cross(p[:, 1], p[:, 2])).sum() / 6.0)


def write_glb(meshes: dict[str, tuple[np.ndarray, np.ndarray]], path: Path) -> None:
    """GLB with one node per part (named by its id), millimetres, glTF Y-up."""
    import trimesh

    scene = trimesh.Scene()
    for name, (vertices, triangles) in meshes.items():
        # The model is Z-up; glTF is Y-up: (x, y, z) -> (x, z, -y).
        y_up = np.column_stack([vertices[:, 0], vertices[:, 2], -vertices[:, 1]])
        # No vertex merge: faces meshed apart keep their own vertices, so the vertex normals
        # stay sharp at CAD edges (the app replaces the material and needs the normals).
        mesh = trimesh.Trimesh(vertices=y_up, faces=triangles, process=False)
        scene.add_geometry(mesh, node_name=name, geom_name=name)
    path.write_bytes(scene.export(file_type='glb', include_normals=True))
