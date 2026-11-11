"""Hull comparison metrics shared by the development and Gunnerus benchmarks.

Truth and reconstruction are measured the same way: both are OpenCascade
shapes in millimetres, cut by planes x = const. Each cut gives polylines in
(y, z) metres. Metric definitions are in docs/BENCHMARK_GUNNERUS.md.

Definitions used here:

- Outer half-breadth hb(x, z): the largest |y| where the cut at x crosses the
  horizontal line at height z; 0 where the cut does not reach z.
- Occupied width w(x, z): total length in y of the section interior at height
  z, from the even-odd rule on the crossings. A half-hull surface (all y >= 0)
  is mirrored to y < 0 before this rule.
- Section area below T: integral of w(x, z) over z <= T.
- Volume below T: integral of the section area over x.
- Waterplane area at T: integral of w(x, T) over x.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

# Chord deviation for sampling cut edges, in model millimetres.
EDGE_DEFLECTION_MM = 0.5


def cut_polylines(shape, x_m: float) -> list[np.ndarray]:
    """Cut ``shape`` (millimetres) at x = x_m; return (y, z) polylines in metres."""
    from OCP.BRepAdaptor import BRepAdaptor_Curve
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Section
    from OCP.GCPnts import GCPnts_QuasiUniformDeflection
    from OCP.gp import gp_Dir, gp_Pln, gp_Pnt
    from OCP.TopAbs import TopAbs_EDGE
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopoDS import TopoDS

    section = BRepAlgoAPI_Section(shape, gp_Pln(gp_Pnt(x_m * 1000.0, 0, 0), gp_Dir(1, 0, 0)), False)
    section.Build()
    if not section.IsDone():
        raise RuntimeError(f"Section operation failed at x = {x_m} m")
    polylines = []
    explorer = TopExp_Explorer(section.Shape(), TopAbs_EDGE)
    while explorer.More():
        curve = BRepAdaptor_Curve(TopoDS.Edge_s(explorer.Current()))
        sampler = GCPnts_QuasiUniformDeflection(curve, EDGE_DEFLECTION_MM)
        if sampler.IsDone() and sampler.NbPoints() >= 2:
            points = [sampler.Value(i) for i in range(1, sampler.NbPoints() + 1)]
        else:
            first, last = curve.FirstParameter(), curve.LastParameter()
            points = [curve.Value(float(t)) for t in np.linspace(first, last, 65)]
        polylines.append(np.array([[p.Y(), p.Z()] for p in points], dtype=float) / 1000.0)
        explorer.Next()
    return polylines


def mesh_triangles(shape, deflection_mm: float, angular_rad: float = 0.2) -> np.ndarray:
    """Tessellate a shape; return triangles (T, 3, 3) in metres.

    Used for the truth model, whose very large B-spline surfaces make direct
    plane sections too slow. ``deflection_mm`` bounds the chord distance from
    the surface, so a cut through the mesh is within it of the exact cut.
    """
    from OCP.BRep import BRep_Tool
    from OCP.BRepMesh import BRepMesh_IncrementalMesh
    from OCP.TopAbs import TopAbs_FACE, TopAbs_REVERSED
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopLoc import TopLoc_Location
    from OCP.TopoDS import TopoDS

    BRepMesh_IncrementalMesh(shape, deflection_mm, False, angular_rad, True)
    blocks = []
    explorer = TopExp_Explorer(shape, TopAbs_FACE)
    while explorer.More():
        face = TopoDS.Face_s(explorer.Current())
        location = TopLoc_Location()
        triangulation = BRep_Tool.Triangulation_s(face, location)
        if triangulation is not None:
            transform = location.Transformation()
            nodes = np.array([[p.X(), p.Y(), p.Z()] for p in
                              (triangulation.Node(i).Transformed(transform) for i in range(1, triangulation.NbNodes() + 1))])
            triangles = np.array([triangulation.Triangle(i).Get() for i in range(1, triangulation.NbTriangles() + 1)]) - 1
            if face.Orientation() == TopAbs_REVERSED:
                triangles = triangles[:, ::-1]
            blocks.append(nodes[triangles])
        explorer.Next()
    return np.vstack(blocks) / 1000.0


def mesh_volume(triangles: np.ndarray) -> float:
    """Enclosed volume of a closed, consistently oriented triangle mesh."""
    a, b, c = triangles[:, 0], triangles[:, 1], triangles[:, 2]
    return float(np.einsum("ij,ij->i", a, np.cross(b, c)).sum() / 6.0)


def cut_mesh(triangles: np.ndarray, x_m: float, x_bounds: tuple[np.ndarray, np.ndarray] | None = None) -> list[np.ndarray]:
    """Cut a triangle mesh at x = x_m; return two-point (y, z) segments.

    The plane is moved by 0.1 micrometre so that no mesh vertex lies on it
    (face boundaries of CAD models often sit exactly on frame positions).
    """
    x_m = x_m + 1.0e-7
    lo, hi = x_bounds if x_bounds is not None else (triangles[:, :, 0].min(axis=1), triangles[:, :, 0].max(axis=1))
    candidates = triangles[(lo < x_m) & (hi > x_m)]
    if not len(candidates):
        return []
    segments = []
    for first, second in ((0, 1), (1, 2), (2, 0)):
        p, q = candidates[:, first], candidates[:, second]
        crosses = (p[:, 0] - x_m) * (q[:, 0] - x_m) < 0
        t = np.where(crosses, (x_m - p[:, 0]) / np.where(crosses, q[:, 0] - p[:, 0], 1.0), np.nan)
        segments.append(p[:, 1:] + t[:, None] * (q[:, 1:] - p[:, 1:]))
    points = np.stack(segments, axis=1)  # (T, 3 edges, 2)
    valid = ~np.isnan(points[:, :, 0])
    result = []
    for row, mask in zip(points, valid):
        if mask.sum() == 2:
            result.append(row[mask])
    return result


def _segments(polylines: list[np.ndarray]) -> np.ndarray:
    pieces = [np.hstack([p[:-1], p[1:]]) for p in polylines if len(p) >= 2]
    return np.vstack(pieces) if pieces else np.zeros((0, 4))


def _mirror_if_half(polylines: list[np.ndarray]) -> list[np.ndarray]:
    if not polylines:
        return polylines
    if min(float(p[:, 0].min()) for p in polylines) >= -1e-6:
        return polylines + [p * [-1.0, 1.0] for p in polylines]
    return polylines


def crossings(polylines: list[np.ndarray], z_grid: np.ndarray) -> list[np.ndarray]:
    """y values where the polylines cross each height (half-open rule)."""
    segments = _segments(polylines)
    result = [[] for _ in z_grid]
    if not len(segments):
        return [np.zeros(0) for _ in z_grid]
    y0, z0, y1, z1 = segments.T
    low, high = np.minimum(z0, z1), np.maximum(z0, z1)
    moving = high > low
    y0, z0, y1, z1, low, high = (a[moving] for a in (y0, z0, y1, z1, low, high))
    for index, z in enumerate(z_grid):
        hit = (low <= z) & (z < high)
        if hit.any():
            t = (z - z0[hit]) / (z1[hit] - z0[hit])
            result[index] = np.sort(y0[hit] + t * (y1[hit] - y0[hit]))
        else:
            result[index] = np.zeros(0)
    return result


def outer_half_breadth(polylines: list[np.ndarray], z_grid: np.ndarray) -> np.ndarray:
    values = crossings(polylines, z_grid)
    return np.array([float(np.abs(v).max()) if len(v) else 0.0 for v in values])


def occupied_width(polylines: list[np.ndarray], z_grid: np.ndarray) -> tuple[np.ndarray, int]:
    """Width by the even-odd rule; also return how many heights had odd counts."""
    values = crossings(_mirror_if_half(polylines), z_grid)
    widths, odd = np.zeros(len(z_grid)), 0
    for index, v in enumerate(values):
        if len(v) % 2:
            odd += 1
            v = v[:-1]
        widths[index] = float(np.sum(v[1::2] - v[0::2])) if len(v) else 0.0
    return widths, odd


@dataclass(frozen=True)
class SectionTable:
    """Per-station quantities on a common height grid."""

    x_m: np.ndarray
    z_m: np.ndarray
    half_breadth: np.ndarray  # (len(x), len(z))
    width: np.ndarray  # (len(x), len(z))
    odd_crossing_heights: np.ndarray


def tabulate(polylines_by_x: list[list[np.ndarray]], x_m, z_m) -> SectionTable:
    x_m, z_m = np.asarray(x_m, float), np.asarray(z_m, float)
    half, width, odd = [], [], []
    for polylines in polylines_by_x:
        half.append(outer_half_breadth(polylines, z_m))
        w, count = occupied_width(polylines, z_m)
        width.append(w)
        odd.append(count)
    return SectionTable(x_m, z_m, np.array(half), np.array(width), np.array(odd))


def _intervals(values: np.ndarray) -> np.ndarray:
    if len(values) % 2:
        values = values[:-1]
    return np.column_stack([values[0::2], values[1::2]])


def tabulate_union(cut_sets_by_x: list[list[list[np.ndarray]]], x_m, z_m) -> SectionTable:
    """Like ``tabulate``, for the union of several cuts at each station.

    A reconstruction made of solids that end on a station plane (one solid
    per region, closed by a flat face there) has a different cut just aft and
    just forward of that plane. The section of the closed solid at the plane
    is the union of both cuts: occupied intervals are merged per height, and
    the outer half-breadth is the larger one.
    """
    x_m, z_m = np.asarray(x_m, float), np.asarray(z_m, float)
    half, width, odd = [], [], []
    for cut_sets in cut_sets_by_x:
        outer = np.zeros(len(z_m))
        per_cut = []
        odd_count = 0
        for polylines in cut_sets:
            outer = np.maximum(outer, outer_half_breadth(polylines, z_m))
            values = crossings(_mirror_if_half(polylines), z_m)
            odd_count += sum(len(v) % 2 for v in values)
            per_cut.append(values)
        total = np.zeros(len(z_m))
        for index in range(len(z_m)):
            merged = np.vstack([_intervals(cut[index]) for cut in per_cut] or [np.zeros((0, 2))])
            if not len(merged):
                continue
            merged = merged[np.argsort(merged[:, 0])]
            start, end = merged[0]
            for low, high in merged[1:]:
                if low > end:
                    total[index] += end - start
                    start, end = low, high
                else:
                    end = max(end, high)
            total[index] += end - start
        half.append(outer)
        width.append(total)
        odd.append(odd_count)
    return SectionTable(x_m, z_m, np.array(half), np.array(width), np.array(odd))


def area_below(table: SectionTable, draft_m: float) -> np.ndarray:
    """Section area below ``draft_m`` for every station (trapezoid in z)."""
    z = table.z_m
    mask = z <= draft_m + 1e-12
    if not mask.any():
        return np.zeros(len(table.x_m))
    return np.trapezoid(table.width[:, mask], z[mask], axis=1)


def width_at(table: SectionTable, z_value: float) -> np.ndarray:
    index = int(np.argmin(np.abs(table.z_m - z_value)))
    if abs(table.z_m[index] - z_value) > 1e-9:
        raise ValueError("The height grid does not contain the requested waterline.")
    return table.width[:, index]


def integrate_x(table: SectionTable, values: np.ndarray, x_range: tuple[float, float] | None = None) -> float:
    x = table.x_m
    mask = np.ones(len(x), dtype=bool) if x_range is None else (x >= x_range[0] - 1e-9) & (x <= x_range[1] + 1e-9)
    return float(np.trapezoid(values[mask], x[mask])) if mask.sum() >= 2 else 0.0


def half_breadth_errors(truth: np.ndarray, reconstruction: np.ndarray, z_m: np.ndarray) -> dict:
    """RMS and maximum absolute error of half-breadth profiles on one grid."""
    error = reconstruction - truth
    worst = int(np.argmax(np.abs(error)))
    return {"rms_m": float(math.sqrt(float(np.mean(error ** 2)))),
            "max_abs_m": float(abs(error[worst])), "z_at_max_m": float(z_m[worst]),
            "signed_at_max_m": float(error[worst]), "mean_signed_m": float(np.mean(error)),
            "samples": int(len(z_m))}


def shape_volume_below(shape, draft_m: float, *, margin_mm: float = 1.0e5) -> tuple[float, float]:
    """Exact volume (m3) and waterplane area (m2) below a draft, by Boolean common."""
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Common
    from OCP.BRepGProp import BRepGProp
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
    from OCP.GProp import GProp_GProps
    from OCP.gp import gp_Pnt
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.GeomAbs import GeomAbs_Plane
    from OCP.TopAbs import TopAbs_FACE
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopoDS import TopoDS

    top = draft_m * 1000.0
    box = BRepPrimAPI_MakeBox(gp_Pnt(-margin_mm, -margin_mm, -margin_mm),
                              gp_Pnt(margin_mm, margin_mm, top)).Shape()
    common = BRepAlgoAPI_Common(shape, box)
    common.Build()
    if not common.IsDone():
        raise RuntimeError("Boolean common failed")
    result = common.Shape()
    props = GProp_GProps()
    BRepGProp.VolumeProperties_s(result, props)
    volume = props.Mass() / 1e9
    area = 0.0
    explorer = TopExp_Explorer(result, TopAbs_FACE)
    while explorer.More():
        face = TopoDS.Face_s(explorer.Current())
        surface = BRepAdaptor_Surface(face)
        if surface.GetType() == GeomAbs_Plane:
            plane = surface.Plane()
            normal = plane.Axis().Direction()
            if abs(abs(normal.Z()) - 1.0) < 1e-9 and abs(plane.Location().Z() - top) < 1e-6:
                face_props = GProp_GProps()
                BRepGProp.SurfaceProperties_s(face, face_props)
                area += face_props.Mass() / 1e6
        explorer.Next()
    return volume, area
