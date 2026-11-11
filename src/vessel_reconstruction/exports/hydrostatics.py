"""Hydrostatics summary of a draft hull at one waterline.

Mesh method (preferred). The exported STL is a closed tessellation of the STEP
solid. The part of the hull below the waterline z = T is bounded by the hull
triangles below T and by the flat waterplane at T. With the divergence theorem
and fields that vanish on z = T, every quantity is an integral over the clipped
hull triangles only, so the waterplane cap is never built:

    V          =  sum over hull below T of  (z - T)       n_z dA
    V * LCB    =  ...                        x (z - T)    n_z dA
    V * VCB    =  ...                        (z^2 - T^2)/2 n_z dA
    Awp        = -...                        1            n_z dA
    Awp * LCF  = -...                        x            n_z dA
    I_T        = -...                        y^2          n_z dA
    I_L(origin)= -...                        x^2          n_z dA

The integrands are at most quadratic, and the edge-midpoint rule is exact for
quadratics on a triangle, so the results are exact for the mesh. The
largest section area (for Cm and Cp) uses even-odd widths of plane cuts.

Table method (fallback when no mesh was exported). Occupied intervals of the built
station sections on a fine height grid, integrated with the trapezoid rule in z
and x. Stations only: the hull between and beyond them is not seen.

This is a sanity check against the drawing and owner data, not a stability
calculation. The naval architect re-runs hydrostatics in approved software.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np

from ..section_regions import piece_ring
from .offsets import section_curves

SEAWATER_DENSITY_T_PER_M3 = 1.025
# Design draft when none is given: this fraction of the moulded depth (the
# benchmark factory convention, benchmarks/factory/truth.py DRAFT_FRACTION).
ASSUMED_DRAFT_FRACTION_OF_DEPTH = 0.6
# Plane cuts used to find the largest section area below the waterline.
SECTION_AREA_CUTS = 81
# Height samples for widths in a section cut and for the table method.
HEIGHT_SAMPLES = 400
MILLIMETRES_PER_METRE = 1000.0
COEFFICIENT_BASIS = ("L = waterline length, B = largest breadth below the waterline, T = draft above the keel, "
                     "Am = largest section area below the waterline")


@dataclass
class Hydrostatics:
    method: str
    draft_m: float
    draft_basis: str
    density_t_per_m3: float
    volume_m3: float
    displacement_t: float
    lcb_m: float | None
    vcb_m: float | None
    kb_m: float | None
    waterplane_area_m2: float
    lcf_m: float | None
    bmt_m: float | None
    bml_m: float | None
    waterline_length_m: float
    waterline_beam_m: float
    keel_z_m: float
    largest_breadth_below_waterline_m: float
    largest_section_area_m2: float | None
    largest_section_x_m: float | None
    wetted_surface_m2: float | None
    cb: float | None
    cp: float | None
    cm: float | None
    cwp: float | None
    coefficient_basis: str = COEFFICIENT_BASIS
    checks: dict = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# Mesh input


def read_stl(path: Path, units: str = "mm") -> np.ndarray:
    """Triangles (T, 3, 3) in metres from a binary or ASCII STL file."""
    data = Path(path).read_bytes()
    scale = 1.0 / MILLIMETRES_PER_METRE if units == "mm" else 1.0
    if len(data) >= 84:
        count = int(np.frombuffer(data, dtype="<u4", count=1, offset=80)[0])
        if 84 + 50 * count == len(data):
            record = np.dtype([("normal", "<f4", 3), ("corners", "<f4", (3, 3)), ("attribute", "<u2")])
            triangles = np.frombuffer(data, dtype=record, count=count, offset=84)["corners"]
            return triangles.astype(float) * scale
    vertices = [line.split()[1:4] for line in data.decode("ascii", errors="replace").splitlines()
                if line.strip().startswith("vertex")]
    if not vertices or len(vertices) % 3:
        raise ValueError(f"{path} is not a readable STL file.")
    return np.asarray(vertices, dtype=float).reshape(-1, 3, 3) * scale


def signed_volume(triangles: np.ndarray) -> float:
    a, b, c = triangles[:, 0], triangles[:, 1], triangles[:, 2]
    return float(np.einsum("ij,ij->i", a, np.cross(b, c)).sum() / 6.0)


def _roll_corners(triangles: np.ndarray, first: np.ndarray) -> np.ndarray:
    """Each triangle with its corners rotated so that corner ``first`` comes first."""
    order = (first[:, None] + np.arange(3)[None, :]) % 3
    return triangles[np.arange(len(triangles))[:, None], order]


def clip_below(triangles: np.ndarray, level: float) -> np.ndarray:
    """Parts of the triangles with z <= level, as triangles with the same orientation."""
    below = triangles[:, :, 2] <= level
    count = below.sum(axis=1)
    pieces = [triangles[count == 3]]

    def edge_point(p, q):
        fraction = (level - p[:, 2]) / (q[:, 2] - p[:, 2])
        return p + fraction[:, None] * (q - p)

    # Rolling the corners keeps the cyclic order, so the orientation is kept.
    one = triangles[count == 1]
    if len(one):
        first = np.argmax(one[:, :, 2] <= level, axis=1)
        rolled = _roll_corners(one, first)
        a, b, c = rolled[:, 0], rolled[:, 1], rolled[:, 2]
        pieces.append(np.stack([a, edge_point(a, b), edge_point(a, c)], axis=1))
    two = triangles[count == 2]
    if len(two):
        first = np.argmax(two[:, :, 2] > level, axis=1)
        rolled = _roll_corners(two, first)
        a, b, c = rolled[:, 0], rolled[:, 1], rolled[:, 2]  # a is above; b and c are below.
        ab, ca = edge_point(b, a), edge_point(c, a)
        pieces.append(np.stack([ab, b, c], axis=1))
        pieces.append(np.stack([ab, c, ca], axis=1))
    return np.concatenate(pieces) if pieces else np.zeros((0, 3, 3))


def _edge_midpoints(triangles: np.ndarray) -> np.ndarray:
    return np.stack([(triangles[:, 0] + triangles[:, 1]) / 2, (triangles[:, 1] + triangles[:, 2]) / 2,
                     (triangles[:, 2] + triangles[:, 0]) / 2], axis=1)


def _flux(triangles: np.ndarray, integrand) -> float:
    """Sum of the integral of integrand(x, y, z) * n_z dA over the triangles (exact to degree 2)."""
    vector_area = 0.5 * np.cross(triangles[:, 1] - triangles[:, 0], triangles[:, 2] - triangles[:, 0])
    mids = _edge_midpoints(triangles)
    mean = integrand(mids[..., 0], mids[..., 1], mids[..., 2]).mean(axis=1)
    return float(np.sum(vector_area[:, 2] * mean))


def section_width_area(triangles: np.ndarray, x_m: float, level: float, keel: float) -> float:
    """Area below ``level`` of the plane cut x = x_m, from even-odd widths on a height grid."""
    corners_x = triangles[:, :, 0] - x_m - 1e-7  # The offset keeps vertices off the plane.
    side = corners_x > 0
    crossing = side.any(axis=1) & ~side.all(axis=1)
    if not crossing.any():
        return 0.0
    cut, signed, side = triangles[crossing], corners_x[crossing], side[crossing]
    points = []
    for a, b in ((0, 1), (1, 2), (2, 0)):
        edge = side[:, a] != side[:, b]
        fraction = signed[:, a] / np.where(edge, signed[:, a] - signed[:, b], 1.0)
        point = cut[:, a] + fraction[:, None] * (cut[:, b] - cut[:, a])
        points.append(np.where(edge[:, None], point, np.nan))
    points = np.stack(points, axis=1)[:, :, 1:]
    segments = points[~np.isnan(points[:, :, 0])].reshape(-1, 2, 2)
    step = (level - keel) / HEIGHT_SAMPLES
    heights = keel + step * (np.arange(HEIGHT_SAMPLES) + 0.5)  # Midpoint rule in z.
    widths = np.zeros(len(heights))
    y0, z0, y1, z1 = segments[:, 0, 0], segments[:, 0, 1], segments[:, 1, 0], segments[:, 1, 1]
    low, high = np.minimum(z0, z1), np.maximum(z0, z1)
    for index, z in enumerate(heights):
        hit = (low <= z) & (z < high)
        if hit.sum() < 2:
            continue
        y = np.sort(y0[hit] + (z - z0[hit]) / (z1[hit] - z0[hit]) * (y1[hit] - y0[hit]))
        y = y[: len(y) // 2 * 2]
        widths[index] = float(np.sum(y[1::2] - y[0::2]))
    return float(np.sum(widths) * step)


def form_coefficients(volume, awp, largest_area, length, beam, draft) -> dict:
    """Cb, Cwp, Cm, Cp with L = waterline length, B = largest breadth below the waterline,
    T = draft above the keel and the largest section area below the waterline."""
    box = length * beam * draft
    return {"cb": volume / box if box > 0 else None,
            "cwp": awp / (length * beam) if length * beam > 0 else None,
            "cm": largest_area / (beam * draft) if largest_area and beam * draft > 0 else None,
            "cp": volume / (largest_area * length) if largest_area and length > 0 else None}


def mesh_hydrostatics(triangles: np.ndarray, draft_m: float, draft_basis: str, *,
                      density: float = SEAWATER_DENSITY_T_PER_M3, reference_volume_m3: float | None = None
                      ) -> Hydrostatics:
    warnings = []
    total = signed_volume(triangles)
    if total < 0:  # Inward-facing mesh: reverse each triangle.
        triangles = triangles[:, ::-1]
        total = -total
    keel = float(triangles[:, :, 2].min())
    level = draft_m
    wet = clip_below(triangles, level)
    # A face on the waterline is the artificial top cap, not wetted shell.
    # Its normal would cancel Awp and its moments at a draft equal to deck z.
    wet = wet[~np.all(wet[:, :, 2] == level, axis=1)]
    volume = _flux(wet, lambda x, y, z: z - level)
    if volume <= 0:
        raise ValueError(f"The hull has no volume below z = {level:.3f} m.")
    lcb = _flux(wet, lambda x, y, z: x * (z - level)) / volume
    vcb = _flux(wet, lambda x, y, z: (z * z - level * level) / 2) / volume
    awp = -_flux(wet, lambda x, y, z: np.ones_like(x))
    lcf = -_flux(wet, lambda x, y, z: x) / awp if awp > 0 else None
    inertia_t = -_flux(wet, lambda x, y, z: y * y)
    inertia_l = -_flux(wet, lambda x, y, z: x * x) - awp * lcf ** 2 if lcf is not None else None
    on_plane = wet.reshape(-1, 3)
    on_plane = on_plane[np.abs(on_plane[:, 2] - level) < 1e-9]
    if len(on_plane):
        length = float(on_plane[:, 0].max() - on_plane[:, 0].min())
        beam = float(2 * np.abs(on_plane[:, 1]).max())
    else:
        length = beam = 0.0
        warnings.append("The waterline does not cut the hull; length and beam on the waterline are zero.")
    breadth = float(2 * np.abs(wet[:, :, 1]).max())
    x_lo, x_hi = float(wet[:, :, 0].min()), float(wet[:, :, 0].max())
    stations = np.linspace(x_lo, x_hi, SECTION_AREA_CUTS)[1:-1]
    areas = [section_width_area(wet, float(x), level, keel) for x in stations]
    largest = int(np.argmax(areas)) if areas else None
    largest_area = float(areas[largest]) if largest is not None else None
    wetted = float(np.sum(np.linalg.norm(np.cross(wet[:, 1] - wet[:, 0], wet[:, 2] - wet[:, 0]), axis=1)) / 2)
    checks = {"mesh_volume_m3": total, "triangles": int(len(triangles))}
    if reference_volume_m3:
        relative = abs(total - reference_volume_m3) / reference_volume_m3
        checks["mesh_vs_build_volume_relative"] = relative
        if relative > 0.01:
            warnings.append(f"Mesh volume {total:.1f} m3 differs from the build volume "
                            f"{reference_volume_m3:.1f} m3 by {relative:.1%}.")
    return Hydrostatics(
        method="mesh: clipped STL tessellation of the STEP solid, divergence theorem",
        draft_m=draft_m, draft_basis=draft_basis, density_t_per_m3=density, volume_m3=volume,
        displacement_t=volume * density, lcb_m=lcb, vcb_m=vcb, kb_m=vcb - keel, waterplane_area_m2=awp,
        lcf_m=lcf, bmt_m=inertia_t / volume, bml_m=inertia_l / volume if inertia_l is not None else None,
        waterline_length_m=length, waterline_beam_m=beam, keel_z_m=keel, largest_section_area_m2=largest_area,
        largest_section_x_m=float(stations[largest]) if largest is not None else None,
        largest_breadth_below_waterline_m=breadth, wetted_surface_m2=wetted,
        **form_coefficients(volume, awp, largest_area, length, breadth, draft_m - keel),
        checks=checks, warnings=warnings)


# ---------------------------------------------------------------------------
# Table input (fallback)


def _section_rings(section: dict) -> list[np.ndarray]:
    """Close each half-section piece using the same boundaries as the CAD build."""
    if "points_yz_m" in section:
        return [piece_ring(section["points_yz_m"])]
    return [piece_ring(piece["points_yz_m"], piece.get("inner_points_yz_m"))
            for piece in section.get("pieces", [])]


def _intervals_at(rings: list[np.ndarray], height: float) -> list[tuple[float, float]]:
    """Occupied intervals on the positive-y side, paired by crossings of each ring."""
    intervals = []
    for ring in rings:
        if len(ring) < 3:
            continue
        # Half-open edges count a shared vertex once and ignore horizontal edges.
        z = height
        start, end = ring, np.roll(ring, -1, axis=0)
        hit = (np.minimum(start[:, 1], end[:, 1]) <= z) & (z < np.maximum(start[:, 1], end[:, 1]))
        a, b = start[hit], end[hit]
        crossings = np.sort(a[:, 0] + (z - a[:, 1]) * (b[:, 0] - a[:, 0]) / (b[:, 1] - a[:, 1]))
        intervals.extend(zip(crossings[::2], crossings[1::2]))
    return intervals


def table_hydrostatics(sections: list[dict], draft_m: float, draft_basis: str, *,
                       density: float = SEAWATER_DENSITY_T_PER_M3) -> Hydrostatics:
    sections = sorted(sections, key=lambda s: float(s["x_m"]))
    if len(sections) < 2:
        raise ValueError("The table method needs at least two stations.")
    curves = [section_curves(s) for s in sections]
    keel = float(min(c[:, 1].min() for group in curves for c in group))
    x = np.array([float(s["x_m"]) for s in sections])
    heights = np.linspace(keel, draft_m, HEIGHT_SAMPLES)
    rings = [_section_rings(section) for section in sections]
    area, moment_z, waterline_intervals, maximum_outer = [], [], [], []
    for group in rings:
        # Split at all vertices so a horizontal step is integrated from each side.
        vertices_z = [z for ring in group for z in ring[:, 1] if keel < z < draft_m]
        levels = np.unique(np.concatenate((heights, vertices_z)))
        lower = [_intervals_at(group, np.nextafter(z, np.inf)) for z in levels[:-1]]
        upper = [_intervals_at(group, np.nextafter(z, -np.inf)) for z in levels[1:]]
        low_width = np.array([2 * sum(right - left for left, right in row) for row in lower])
        high_width = np.array([2 * sum(right - left for left, right in row) for row in upper])
        dz = np.diff(levels)
        area.append(float(np.sum(dz * (low_width + high_width) / 2)))
        moment_z.append(float(np.sum(dz * (low_width * levels[:-1] + high_width * levels[1:]) / 2)))
        waterline_intervals.append(_intervals_at(group, np.nextafter(draft_m, -np.inf)))
        maximum_outer.append(max((right for row in lower + upper for _, right in row), default=0.0))
    area, moment_z = np.asarray(area), np.asarray(moment_z)
    volume = float(np.trapezoid(area, x))
    if volume <= 0:
        raise ValueError(f"The stations have no area below z = {draft_m:.3f} m.")
    waterline = np.array([2 * sum(right - left for left, right in row) for row in waterline_intervals])
    awp = float(np.trapezoid(waterline, x))
    lcf = float(np.trapezoid(waterline * x, x) / awp) if awp > 0 else None
    transverse_moments = [2 * sum((right**3 - left**3) / 3 for left, right in station)
                          for station in waterline_intervals]
    inertia_t = float(np.trapezoid(transverse_moments, x))
    inertia_l = float(np.trapezoid(waterline * x * x, x)) - awp * lcf ** 2 if lcf is not None else None
    wet_x = x[waterline > 0]
    length = float(wet_x.max() - wet_x.min()) if len(wet_x) else 0.0
    beam = float(2 * max((right for row in waterline_intervals for _, right in row), default=0.0))
    breadth = float(2 * max(maximum_outer))
    largest = int(np.argmax(area))
    vcb = float(np.trapezoid(moment_z, x) / volume)
    return Hydrostatics(
        method="table: trapezoid rule over the built station curves (stations only)",
        draft_m=draft_m, draft_basis=draft_basis, density_t_per_m3=density, volume_m3=volume,
        displacement_t=volume * density, lcb_m=float(np.trapezoid(area * x, x) / volume), vcb_m=vcb,
        kb_m=vcb - keel, waterplane_area_m2=awp, lcf_m=lcf, bmt_m=inertia_t / volume,
        bml_m=inertia_l / volume if inertia_l is not None else None, waterline_length_m=length,
        waterline_beam_m=beam, keel_z_m=keel, largest_section_area_m2=float(area[largest]),
        largest_section_x_m=float(x[largest]), wetted_surface_m2=None, largest_breadth_below_waterline_m=breadth,
        **form_coefficients(volume, awp, float(area[largest]), length, breadth, draft_m - keel),
        checks={"stations": len(sections)},
        warnings=["Table method: only the stations are integrated; the shape between and beyond them is "
                  "not measured."])


def design_draft(spec: dict, depth_m: float, keel_z_m: float, requested: float | None) -> tuple[float, str]:
    """Waterline height above the baseline and the reason it was chosen."""
    if requested is not None:
        return float(requested), "given for this export"
    given = spec.get("design_draft_m")
    if isinstance(given, (int, float)) and given > 0:
        source = spec.get("design_draft_source") or {}
        if source.get("status") == "read":
            sheets = dict.fromkeys(r["source"].get("sheet", "unknown") for r in source.get("readings", []))
            return float(given), "read from drawing: " + ", ".join(sheets)
        return float(given), "specification design_draft_m"
    value = keel_z_m + ASSUMED_DRAFT_FRACTION_OF_DEPTH * depth_m
    return value, (f"assumed: {ASSUMED_DRAFT_FRACTION_OF_DEPTH:g} x moulded depth; no design draft was given. "
                   "Give the design draft for a real check")
