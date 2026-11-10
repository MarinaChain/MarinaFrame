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

from dataclasses import dataclass
from itertools import pairwise
from pathlib import Path

import numpy as np
from .progress import report as report_progress


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
    from OCP.GeomAbs import GeomAbs_BSplineSurface
    from OCP.GeomAdaptor import GeomAdaptor_Surface

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


# Smooth B-spline faces (degree above 1: the smooth walls of the parts above the hull) are
# meshed on a grid of their own parameters, not by the kernel mesher, which gives such long,
# many-span faces up to hundreds of thousands of triangles and slivers with flipped normals.
# Grid lines start at the knots; a span is halved while its middle is further than the chord
# tolerance from the chord, or the surface normal turns more than this across it.
SMOOTH_ANGULAR_RAD = 0.1
# At most this many halvings of one knot span.
MAX_SPAN_HALVINGS = 6


def _smooth_bspline(face):
    """The B-spline surface of an untrimmed face of degree above 1, else None."""
    from OCP.BRep import BRep_Tool
    from OCP.BRepTools import BRepTools
    from OCP.GeomAbs import GeomAbs_BSplineSurface
    from OCP.GeomAdaptor import GeomAdaptor_Surface

    adaptor = GeomAdaptor_Surface(BRep_Tool.Surface_s(face.wrapped))
    if adaptor.GetType() != GeomAbs_BSplineSurface:
        return None
    spline = adaptor.BSpline()
    if spline.UDegree() < 2 and spline.VDegree() < 2:
        return None
    u0, u1, v0, v1 = BRepTools.UVBounds_s(face.wrapped)
    first_u, last_u, first_v, last_v = spline.Bounds()
    untrimmed = np.allclose([u0, u1, v0, v1], [first_u, last_u, first_v, last_v], atol=1e-9)
    return spline if untrimmed else None


def _grid_params(spline, along_u: bool, tolerance_mm: float, angular_rad: float) -> np.ndarray:
    """Grid lines in one parameter direction: the knots, spans halved where they are not flat."""
    from OCP.gp import gp_Pnt, gp_Vec

    first_u, last_u, first_v, last_v = spline.Bounds()
    knots = [spline.UKnot(i) for i in range(1, spline.NbUKnots() + 1)] if along_u else \
        [spline.VKnot(i) for i in range(1, spline.NbVKnots() + 1)]
    across = np.linspace(*((first_v, last_v) if along_u else (first_u, last_u)), 9)

    def point_and_normal(t, s):
        u, v = (t, s) if along_u else (s, t)
        point, du, dv = gp_Pnt(), gp_Vec(), gp_Vec()
        spline.D1(u, v, point, du, dv)
        normal = np.cross(du.Coord(), dv.Coord())
        length = np.linalg.norm(normal)
        return np.array(point.Coord()), normal / length if length > 0 else normal

    def flat(a, b):
        for s in across:
            (pa, na), (pm, _), (pb, nb) = (point_and_normal(t, s) for t in (a, (a + b) / 2, b))
            if np.linalg.norm(pm - (pa + pb) / 2) > tolerance_mm:
                return False
            # A zero normal (a degenerate edge) gives a dot of 0: only a real turn counts.
            if np.linalg.norm(na) and np.linalg.norm(nb) and np.dot(na, nb) < np.cos(angular_rad):
                return False
        return True

    params = [knots[0]]
    for a, b in pairwise(knots):
        stack = [(a, b, 0)]
        while stack:
            low, high, depth = stack.pop()
            if depth < MAX_SPAN_HALVINGS and not flat(low, high):
                middle = (low + high) / 2
                stack += [(middle, high, depth + 1), (low, middle, depth + 1)]
                continue
            params.append(high)
    return np.array(params)


def _smooth_grid_triangles(face, spline, tolerance_mm: float, angular_rad: float):
    """Grid mesh of a smooth B-spline face: shared vertices, so it shades smooth.

    The grid is evaluated densely (``_grid_params``), then rows and columns that stay within
    the tolerance of their neighbours' chords are left out in both directions.
    """
    import cadquery as cq

    angular = min(angular_rad, SMOOTH_ANGULAR_RAD)
    us = _grid_params(spline, True, tolerance_mm, angular)
    vs = _grid_params(spline, False, tolerance_mm, angular)
    grid = np.array([[spline.Value(u, v).Coord() for v in vs] for u in us])
    rows = _decimated_columns(np.transpose(grid, (1, 0, 2)), tolerance_mm)
    vertices, triangles = _grid_triangles(grid[:, rows], False, tolerance_mm)
    if len(triangles):
        # Outward as the face is oriented in its solid.
        p = vertices[triangles[len(triangles) // 2]]
        outward = face.normalAt(cq.Vector(*p.mean(axis=0))).toTuple()
        if np.dot(np.cross(p[1] - p[0], p[2] - p[0]), outward) < 0:
            triangles = triangles[:, ::-1]
    return vertices, triangles


def _discretised_cap(face, tolerance_mm: float):
    """A planar face with smooth B-spline edges as a polygon face (holes kept), or None.

    Its edges are cut into straight pieces within the tolerance, so the kernel meshes it
    exactly and the cap meets the grid-meshed sides to within the tolerance.
    """
    import cadquery as cq
    from OCP.BRepAdaptor import BRepAdaptor_Curve
    from OCP.BRepTools import BRepTools_WireExplorer
    from OCP.GCPnts import GCPnts_QuasiUniformDeflection
    from OCP.GeomAbs import GeomAbs_BSplineCurve
    from OCP.TopAbs import TopAbs_REVERSED

    if face.geomType() != 'PLANE':
        return None
    curves = [BRepAdaptor_Curve(edge.wrapped) for edge in face.Edges()]
    if not any(c.GetType() == GeomAbs_BSplineCurve and c.BSpline().Degree() > 1 for c in curves):
        return None

    def polygon(wire):
        points = []
        # The wire explorer gives the edges in their order along the wire.
        explorer = BRepTools_WireExplorer(wire.wrapped)
        while explorer.More():
            edge = explorer.Current()
            sampler = GCPnts_QuasiUniformDeflection(BRepAdaptor_Curve(edge), tolerance_mm)
            run = [sampler.Value(i).Coord() for i in range(1, sampler.NbPoints() + 1)]
            if edge.Orientation() == TopAbs_REVERSED:
                run = run[::-1]
            points += run[:-1]
            explorer.Next()
        return cq.Wire.makePolygon([cq.Vector(*p) for p in points], close=True)

    outer = face.outerWire()
    inner = [polygon(wire) for wire in face.innerWires()]
    return cq.Face.makeFromWires(polygon(outer), inner)


def shape_mesh(shape, tolerance_mm: float, angular_rad: float,
               smooth_tolerance_mm: float | None = None) -> tuple[np.ndarray, np.ndarray]:
    """One display mesh (vertices in mm, triangles) for a CadQuery shape, faces oriented outward.

    ``smooth_tolerance_mm`` (default ``tolerance_mm``) is the chord tolerance of smooth B-spline
    faces, whose shared-vertex grid shades smooth at a coarser tolerance than flat facets need.
    """
    from OCP.TopAbs import TopAbs_REVERSED

    all_vertices, all_triangles, offset = [], [], 0
    faces = shape.Faces()
    report_progress('Making the display mesh', 0, len(faces))
    for face_index, face in enumerate(faces, 1):
        bspline = _bspline_grid(face)
        smooth = _smooth_bspline(face) if bspline is None else None
        if bspline is not None:
            vertices, triangles = _grid_triangles(*bspline, tolerance_mm)
            if face.wrapped.Orientation() == TopAbs_REVERSED:
                triangles = triangles[:, ::-1]
        elif smooth is not None:
            vertices, triangles = _smooth_grid_triangles(face, smooth, smooth_tolerance_mm or tolerance_mm, angular_rad)
        else:
            cap = _polygon_cap(face) or _discretised_cap(face, tolerance_mm)
            vertices, triangles = _face_triangles(cap or face, tolerance_mm, angular_rad)
            if cap is not None and len(triangles):
                # Keep the outward side of the original cap face.
                p = vertices[triangles[0]]
                if np.dot(np.cross(p[1] - p[0], p[2] - p[0]), face.normalAt().toTuple()) < 0:
                    triangles = triangles[:, ::-1]
        all_vertices.append(vertices)
        all_triangles.append(triangles + offset)
        offset += len(vertices)
        report_progress('Making the display mesh', face_index, len(faces))
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


@dataclass(frozen=True)
class PartStyle:
    """Material and metadata of one GLB part: a base colour (sRGB, 0 to 1), a material name,
    opacity, and JSON ``extras`` (glTF mesh extras; the app reads them as the mesh's userData)."""
    colour: tuple[float, float, float]
    material: str
    extras: dict
    opacity: float = 1.0


def tank_style(name: str, content: str | None, source_labels: dict[str, str]) -> PartStyle:
    """Style of a tank part: its capacity-plan colour by content and its name and content as
    extras (with source labels; ``content_class`` is ``read`` when a word of the name or content
    gave it, else ``guessed``)."""
    from .tanks import CONTENT_CLASSES, content_class, content_colour

    cls = content_class(content, name)
    labels = {**source_labels, 'content_class': 'guessed' if cls == 'other' else 'read'}
    return PartStyle(content_colour(cls), f'tank_{cls}',
                     {'kind': 'tank', 'label': name, 'content': content or '', 'content_class': cls,
                      'content_label': CONTENT_CLASSES[cls][0], 'source_labels': labels,
                      'engineering_approved': False})


def _scene_mesh(vertices: np.ndarray, triangles: np.ndarray, style: PartStyle | None):
    """A trimesh mesh in glTF axes (Y-up), with the style's material and extras."""
    import trimesh

    # The model is Z-up; glTF is Y-up: (x, y, z) -> (x, z, -y).
    y_up = np.column_stack([vertices[:, 0], vertices[:, 2], -vertices[:, 1]])
    # No vertex merge: faces meshed apart keep their own vertices, so the vertex normals
    # stay sharp at CAD edges (the app replaces the material and needs the normals).
    mesh = trimesh.Trimesh(vertices=y_up, faces=triangles, process=False)
    if style is not None:
        material = trimesh.visual.material.PBRMaterial(
            name=style.material, baseColorFactor=[*style.colour, style.opacity], metallicFactor=0.0,
            roughnessFactor=0.7, alphaMode="BLEND" if style.opacity < 1 else "OPAQUE", doubleSided=True)
        mesh.visual = trimesh.visual.TextureVisuals(material=material)
        mesh.metadata.update(style.extras)
    return mesh


def write_glb(meshes: dict[str, tuple[np.ndarray, np.ndarray]], path: Path,
              styles: dict[str, PartStyle] | None = None, base: Path | None = None) -> None:
    """GLB with one node per part (named by its id), millimetres, glTF Y-up.

    ``styles`` gives a material and extras per part id (parts without one keep no material).
    With ``base``, the parts are added to the nodes of that GLB.
    """
    import trimesh

    scene = trimesh.load(base, force='scene') if base is not None else trimesh.Scene()
    for name, (vertices, triangles) in meshes.items():
        scene.add_geometry(_scene_mesh(vertices, triangles, (styles or {}).get(name)),
                           node_name=name, geom_name=name)
    path.write_bytes(scene.export(file_type='glb', include_normals=True))
