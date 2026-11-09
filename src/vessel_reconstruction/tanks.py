"""Tanks and compartments: solids, fill properties, sounding tables and the capacity plan.

A tank is a closed, outward-oriented triangle mesh in the ship frame (metres; x forward from
frame 0, y to port, z up from the baseline). A tank built from drawings (a plan outline with
vertical limits, clipped to the hull) and an exact solid read from OCX go through the same code.

Fill properties at a level h use the divergence theorem on the mesh clipped below h, as the hull
hydrostatics do (``exports/hydrostatics.py``): with fields that vanish on z = h the free surface
cap is never built, and the results are exact for the mesh.

    V             =  sum over the tank below h of  (z - h) n_z dA
    V * (x, y)    =  ...                           (x, y) (z - h) n_z dA
    V * VCG       =  ...                           (z^2 - h^2) / 2 n_z dA
    free surface  = -...                           1, x, y, x^2, y^2 times n_z dA

Every value carries a source label: ``traced`` (measured from drawing linework), ``read``
(printed text) or ``guessed`` (a default or a convention). Every result is a draft:
``engineering_approved`` is false. The naval architect re-runs the tables in approved software.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import math
import re

import numpy as np

from .exports.hydrostatics import _flux, clip_below, signed_volume

SOURCE_LABELS = ("traced", "read", "guessed")
# Capacity plans list the volume at 98 % fill (room for expansion).
WORKING_FILL = 0.98
# Default sounding-table interval (m) when the caller gives none.
SOUNDING_INTERVAL_M = 0.10
# The free surface at the very top or bottom of a tank is a face of the tank, not a liquid
# surface; it is taken this far inside the tank (m).
FREE_SURFACE_INSET_M = 1e-6
# Densities (t/m3) used when the drawing prints none (source label "guessed").
DEFAULT_DENSITY_T_M3 = {
    "water ballast": 1.025,  # sea water
    "fresh water": 1.000,
    "fuel oil": 0.85,  # marine gas oil, typical
    "fuel oil or water ballast": 1.025,  # dual-use tank: the heavier use (sea water)
    "lube oil": 0.90,
    "sewage": 1.00,
    "sludge": 0.90,
    "bilge": 1.00,
    "misc": 1.00,
}


# ---------------------------------------------------------------------------
# Colours by content (capacity-plan convention; docs/TANKS_V1.md section 6)

# One palette for the GLB materials, the app's 3D view and its 2D sketches. There is no single
# standard; this follows common capacity-plan practice (NAPA and Maxsurf compartment views use
# the same families): oils warm (fuel brown-amber, diesel yellow, lube orange, residues dark
# brown), waters cool (ballast green, fresh blue, feed light blue), sewage grey-violet, void and
# cargo spaces light grey. The app keeps the same values as tokens in app/ui/styles.css
# (``--tank-<class>``); a test checks that they agree.
CONTENT_CLASSES = {
    "fuel_oil": ("Fuel oil", "#B8742A"),
    "diesel_oil": ("Diesel / gas oil", "#E3C440"),
    "lube_oil": ("Lube oil", "#EE8A2C"),
    "oily_residue": ("Sludge, bilge, waste oil", "#6E4B36"),
    "water_ballast": ("Water ballast", "#4E9F57"),
    "fresh_water": ("Fresh water", "#3E7FD0"),
    "feed_water": ("Feed / distilled water", "#93C8EC"),
    "sewage": ("Sewage, grey, black water", "#8C7FAE"),
    "cargo": ("Cargo", "#C9CDD3"),
    "void": ("Void / dry", "#EEF0F2"),
    "other": ("Other", "#A3A7AD"),
}
# Words of a tank name or content (lower case; first match wins) -> content class. The name is
# read first: a "misc" tank named "Black water" is sewage.
CONTENT_CLASS_WORDS = (
    ("diesel", "diesel_oil"), ("gas oil", "diesel_oil"), ("gasoil", "diesel_oil"), ("mgo", "diesel_oil"),
    ("mdo", "diesel_oil"), ("d.o", "diesel_oil"),
    ("lub", "lube_oil"), ("l.o", "lube_oil"),
    ("sludge", "oily_residue"), ("bilge", "oily_residue"), ("waste oil", "oily_residue"),
    ("dirty oil", "oily_residue"), ("oily", "oily_residue"),
    ("sewage", "sewage"), ("grey", "sewage"), ("gray", "sewage"), ("black water", "sewage"),
    ("sanitary", "sewage"),
    ("feed", "feed_water"), ("distill", "feed_water"), ("boiler water", "feed_water"),
    ("ballast", "water_ballast"),
    ("fresh water", "fresh_water"), ("drinking", "fresh_water"), ("potable", "fresh_water"),
    ("fuel", "fuel_oil"), ("f.o", "fuel_oil"),
    ("cargo", "cargo"), ("hold", "cargo"),
    ("void", "void"), ("cofferdam", "void"), ("dry", "void"), ("empty", "void"),
)


def content_class(content: str | None, name: str | None = None) -> str:
    """Content class of a tank (a key of CONTENT_CLASSES) from its name, else its content."""
    for text in (name, content):
        lower = (text or "").lower()
        for word, cls in CONTENT_CLASS_WORDS:
            if re.search(r"(?<![a-z0-9])" + re.escape(word), lower):
                return cls
    return "other"


def content_colour(cls: str) -> tuple[float, float, float]:
    """sRGB colour (0 to 1) of a content class."""
    hex_colour = CONTENT_CLASSES.get(cls, CONTENT_CLASSES["other"])[1]
    return tuple(int(hex_colour[i:i + 2], 16) / 255 for i in (1, 3, 5))


# ---------------------------------------------------------------------------
# Fill properties


@dataclass
class FillState:
    level_m: float
    volume_m3: float
    centroid_m: tuple[float, float, float] | None  # LCG, TCG, VCG of the liquid
    free_surface_m2: float
    i_transverse_m4: float  # free surface inertia about its own longitudinal axis
    i_longitudinal_m4: float  # free surface inertia about its own transverse axis


def outward(triangles: np.ndarray) -> np.ndarray:
    """The mesh with outward normals (positive signed volume)."""
    triangles = np.asarray(triangles, dtype=float)
    return triangles[:, ::-1] if signed_volume(triangles) < 0 else triangles


def fill_state(triangles: np.ndarray, level_m: float) -> FillState:
    """Liquid volume, centroid and free surface of an outward closed mesh filled to ``level_m``."""
    low, high = float(triangles[:, :, 2].min()), float(triangles[:, :, 2].max())
    level = min(max(level_m, low), high)
    wet = clip_below(triangles, level)
    volume = _flux(wet, lambda x, y, z: z - level) if len(wet) else 0.0
    centroid = None
    if volume > 0:
        centroid = (_flux(wet, lambda x, y, z: x * (z - level)) / volume,
                    _flux(wet, lambda x, y, z: y * (z - level)) / volume,
                    _flux(wet, lambda x, y, z: (z * z - level * level) / 2) / volume)
    surface_level = min(max(level, low + FREE_SURFACE_INSET_M), high - FREE_SURFACE_INSET_M)
    area, i_t, i_l = free_surface(triangles, surface_level)
    return FillState(level, volume, centroid, area, i_t, i_l)


def free_surface(triangles: np.ndarray, level_m: float) -> tuple[float, float, float]:
    """Area and inertias (transverse, longitudinal; about its centroid) of the section z = level."""
    wet = clip_below(triangles, level_m)
    if not len(wet):
        return 0.0, 0.0, 0.0
    area = -_flux(wet, lambda x, y, z: np.ones_like(x))
    if area <= 0:
        return 0.0, 0.0, 0.0
    x_c = -_flux(wet, lambda x, y, z: x) / area
    y_c = -_flux(wet, lambda x, y, z: y) / area
    i_t = -_flux(wet, lambda x, y, z: y * y) - area * y_c ** 2
    i_l = -_flux(wet, lambda x, y, z: x * x) - area * x_c ** 2
    return area, i_t, i_l


def sounding_levels(low_m: float, high_m: float, interval_m: float) -> list[float]:
    """Levels from the tank bottom at a fixed interval, ending with the tank top."""
    count = int(math.floor((high_m - low_m) / interval_m + 1e-9))
    levels = [low_m + step * interval_m for step in range(count + 1)]
    if high_m - levels[-1] > 1e-9:
        levels.append(high_m)
    return levels


def sounding_table(triangles: np.ndarray, interval_m: float = SOUNDING_INTERVAL_M) -> list[dict]:
    """Sounding/ullage table: one row per level from the lowest point of the tank (even keel)."""
    triangles = outward(triangles)
    low, high = float(triangles[:, :, 2].min()), float(triangles[:, :, 2].max())
    full = fill_state(triangles, high).volume_m3
    rows = []
    for level in sounding_levels(low, high, interval_m):
        state = fill_state(triangles, level)
        lcg, tcg, vcg = state.centroid_m or (None, None, None)
        rows.append({"sounding_m": round(level - low, 6), "ullage_m": round(high - level, 6),
                     "level_z_m": level, "volume_m3": state.volume_m3,
                     "fill_pct": 100.0 * state.volume_m3 / full if full > 0 else 0.0,
                     "lcg_m": lcg, "tcg_m": tcg, "vcg_m": vcg,
                     "free_surface_m2": state.free_surface_m2,
                     "i_transverse_m4": state.i_transverse_m4, "i_longitudinal_m4": state.i_longitudinal_m4})
    return rows


# ---------------------------------------------------------------------------
# Tank model and capacity plan


@dataclass
class Tank:
    id: str
    name: str
    content: str  # "water ballast", "fresh water", "fuel oil", "misc", "dry", ...
    triangles: np.ndarray | None  # closed mesh; None when the tank was not built
    frames: tuple[str, str] | None = None
    density_t_m3: float | None = None
    # Keys: geometry, content, frames, density, sounding_origin. Values from SOURCE_LABELS.
    source_labels: dict[str, str] = field(default_factory=dict)
    printed_volume_m3: float | None = None
    notes: list[str] = field(default_factory=list)

    def density(self) -> tuple[float | None, str]:
        """Density and its source label: the printed value, else a content default."""
        if self.density_t_m3 is not None:
            return self.density_t_m3, self.source_labels.get("density", "read")
        default = DEFAULT_DENSITY_T_M3.get(self.content)
        return default, "guessed"


def capacity_row(tank: Tank) -> dict:
    """One capacity-plan row: volumes at 100 % and 98 %, weight at 98 %, centroid at 100 %."""
    density, density_source = tank.density()
    labels = {"name": tank.source_labels.get("name", "read"),
              "content": tank.source_labels.get("content", "read"),
              "frames": tank.source_labels.get("frames", "read") if tank.frames else None,
              "volume": tank.source_labels.get("geometry", "guessed"),
              "density": density_source if density is not None else None,
              "centroid": tank.source_labels.get("geometry", "guessed")}
    row = {"id": tank.id, "name": tank.name, "content": tank.content,
           "frames": "...".join(tank.frames) if tank.frames else "", "built": tank.triangles is not None,
           "volume_100_m3": None, "volume_98_m3": None, "density_t_m3": density, "weight_98_t": None,
           "lcg_m": None, "tcg_m": None, "vcg_m": None, "max_free_surface_moment_tm": None,
           "printed_volume_m3": tank.printed_volume_m3, "source_labels": labels,
           "engineering_approved": False, "notes": "; ".join(tank.notes)}
    if tank.triangles is None or len(tank.triangles) == 0:  # not built, or an empty mesh
        return row
    triangles = outward(tank.triangles)
    top = float(triangles[:, :, 2].max())
    full = fill_state(triangles, top)
    row["volume_100_m3"] = full.volume_m3
    row["volume_98_m3"] = WORKING_FILL * full.volume_m3
    if density is not None:
        row["weight_98_t"] = density * row["volume_98_m3"]
    if full.centroid_m:
        row["lcg_m"], row["tcg_m"], row["vcg_m"] = full.centroid_m
    if density is not None:
        largest_i_t = max(r["i_transverse_m4"] for r in sounding_table(triangles))
        row["max_free_surface_moment_tm"] = density * largest_i_t
    return row


def capacity_plan(tanks: list[Tank]) -> list[dict]:
    return [capacity_row(tank) for tank in tanks]


def group_totals(rows: list[dict]) -> dict[str, dict]:
    """Volume (100 %) and weight (98 %) totals per content group; unbuilt tanks count as 0."""
    totals: dict[str, dict] = {}
    for row in rows:
        group = totals.setdefault(row["content"], {"volume_100_m3": 0.0, "weight_98_t": 0.0,
                                                   "tanks": 0, "built": 0})
        group["tanks"] += 1
        if row["built"]:
            group["built"] += 1
            group["volume_100_m3"] += row["volume_100_m3"]
            group["weight_98_t"] += row["weight_98_t"] or 0.0
    return totals


# ---------------------------------------------------------------------------
# Solids from outlines


def _cross_2d(a, b, c) -> float:
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def clean_polygon(points) -> np.ndarray:
    """Counter-clockwise polygon without repeated or collinear vertices."""
    polygon = [tuple(map(float, p)) for p in points]
    polygon = [p for i, p in enumerate(polygon) if math.dist(p, polygon[i - 1]) > 1e-9]
    changed = True
    while changed and len(polygon) > 3:
        changed = False
        for i in range(len(polygon)):
            a, b, c = polygon[i - 1], polygon[i], polygon[(i + 1) % len(polygon)]
            if abs(_cross_2d(a, b, c)) < 1e-12:
                del polygon[i]
                changed = True
                break
    array = np.asarray(polygon)
    signed_area = 0.5 * np.sum(array[:, 0] * np.roll(array[:, 1], -1) - np.roll(array[:, 0], -1) * array[:, 1])
    return array[::-1] if signed_area < 0 else array


def triangulate_polygon(polygon: np.ndarray) -> list[tuple[int, int, int]]:
    """Ear clipping of a simple counter-clockwise polygon; indices into ``polygon``."""
    remaining = list(range(len(polygon)))
    triangles = []
    while len(remaining) > 3:
        for k in range(len(remaining)):
            i, j, m = remaining[k - 1], remaining[k], remaining[(k + 1) % len(remaining)]
            a, b, c = polygon[i], polygon[j], polygon[m]
            if _cross_2d(a, b, c) <= 0:
                continue  # reflex or flat corner: not an ear
            others = polygon[[r for r in remaining if r not in (i, j, m)]]
            if len(others) and _points_in_triangle(others, a, b, c).any():
                continue
            triangles.append((i, j, m))
            del remaining[k]
            break
        else:  # no ear found (a self-touching outline): fan the rest
            triangles.extend((remaining[0], remaining[n], remaining[n + 1]) for n in range(1, len(remaining) - 1))
            return triangles
    triangles.append(tuple(remaining))
    return triangles


def _points_in_triangle(points, a, b, c) -> np.ndarray:
    def side(p, q):
        return (q[0] - p[0]) * (points[:, 1] - p[1]) - (q[1] - p[1]) * (points[:, 0] - p[0])
    return (side(a, b) >= 0) & (side(b, c) >= 0) & (side(c, a) >= 0)


def prism_triangles(x0: float, x1: float, outline_yz) -> np.ndarray:
    """Closed outward mesh of a polygon in the (y, z) plane extruded from x0 to x1."""
    polygon = clean_polygon(outline_yz)
    if len(polygon) < 3 or x1 <= x0:
        return np.zeros((0, 3, 3))
    caps = triangulate_polygon(polygon)
    triangles = []
    for i, j, k in caps:
        # Counter-clockwise in (y, z) has its normal along +x: the forward cap.
        triangles.append([(x1, *polygon[i]), (x1, *polygon[j]), (x1, *polygon[k])])
        triangles.append([(x0, *polygon[i]), (x0, *polygon[k]), (x0, *polygon[j])])
    for n in range(len(polygon)):
        a, b = polygon[n], polygon[(n + 1) % len(polygon)]
        triangles.append([(x0, *a), (x0, *b), (x1, *b)])
        triangles.append([(x0, *a), (x1, *b), (x1, *a)])
    return np.asarray(triangles, dtype=float)


def slabs_triangles(slabs) -> np.ndarray | None:
    """Mesh of a stack of slabs (x0, x1, outline [[y, z], ...]). Touching slabs need not merge:
    their shared caps cancel in every integral above."""
    pieces = [prism_triangles(x0, x1, outline) for x0, x1, outline in slabs]
    pieces = [p for p in pieces if len(p)]
    return np.concatenate(pieces) if pieces else None


class HullSlicer:
    """Cross-sections of a closed hull triangle mesh (metres) by planes x = const."""

    def __init__(self, triangles: np.ndarray):
        self.t = np.asarray(triangles, dtype=float)
        self.xmin = self.t[:, :, 0].min(axis=1)
        self.xmax = self.t[:, :, 0].max(axis=1)

    def segments(self, x: float) -> np.ndarray:
        """Section segments [[y0, z0], [y1, z1]] at x."""
        tri = self.t[(self.xmin <= x) & (self.xmax >= x)]
        # Nudge vertices that lie exactly on the plane so each crossing edge is counted once.
        d = tri[:, :, 0] - x
        d = np.where(d == 0, 1e-9, d)
        crossings, points = [], []
        for i, j in ((0, 1), (1, 2), (2, 0)):
            cross = (d[:, i] * d[:, j]) < 0
            t = np.where(cross, d[:, i] / np.where(cross, d[:, i] - d[:, j], 1), 0)
            crossings.append(cross)
            points.append(tri[:, i, 1:] + t[:, None] * (tri[:, j, 1:] - tri[:, i, 1:]))
        crossings = np.stack(crossings, axis=1)
        points = np.stack(points, axis=1)
        two = crossings.sum(axis=1) == 2
        order = np.argsort(~crossings[two], axis=1, kind="stable")[:, :2]
        return np.take_along_axis(points[two], order[:, :, None], axis=1)

    def intervals(self, x: float, zs: np.ndarray) -> list[list[tuple[float, float]]]:
        """Inside y-intervals of the section at x for each z (even-odd rule)."""
        segs = self.segments(x)
        result = []
        for z in zs:
            if len(segs) == 0:
                result.append([])
                continue
            z0, z1 = segs[:, 0, 1], segs[:, 1, 1]
            hit = (np.minimum(z0, z1) <= z) & (np.maximum(z0, z1) > z)
            s = segs[hit]
            t = (z - s[:, 0, 1]) / (s[:, 1, 1] - s[:, 0, 1])
            ys = np.sort(s[:, 0, 0] + t * (s[:, 1, 0] - s[:, 0, 0]))
            result.append([(float(ys[i]), float(ys[i + 1])) for i in range(0, len(ys) - 1, 2)])
        return result


@dataclass
class SectionChains:
    """The hull section at one x inside a y and a z range, as two chains from bottom to top.

    ``z`` holds the bottom, the row centres and the top; ``left`` and ``right`` the outermost
    inside y at those heights (the bottom and top take the first and last row). ``area`` is the
    inside area of the rows (gaps between pieces left out).
    """
    z: np.ndarray
    left: np.ndarray
    right: np.ndarray
    area: float

    def outline(self) -> list[list[float]]:
        """Closed outline [[y, z], ...]: up the left chain, down the right chain."""
        return ([[float(y), float(z)] for y, z in zip(self.left, self.z)]
                + [[float(y), float(z)] for y, z in zip(self.right[::-1], self.z[::-1])])


def section_chains(slicer: HullSlicer, x: float, y_range, z_range, dz: float) -> SectionChains | None:
    """The hull section at x inside the y and z ranges, sampled in rows of height ``dz``.

    A thin plate is one row. Per row the section spans the leftmost to the rightmost inside piece.
    Returns None when no row is inside the hull.
    """
    height = z_range[1] - z_range[0]
    if height <= 0:
        return None
    rows = max(1, int(np.ceil(height / dz - 1e-9)))
    step = height / rows
    zs = z_range[0] + (np.arange(rows) + 0.5) * step
    centres, left, right, area = [], [], [], 0.0
    for z, intervals in zip(zs, slicer.intervals(x, zs)):
        pieces = [(max(a, y_range[0]), min(b, y_range[1])) for a, b in intervals]
        pieces = [p for p in pieces if p[1] > p[0]]
        if not pieces:
            continue
        area += sum(b - a for a, b in pieces) * step
        centres.append(float(z))
        left.append(min(p[0] for p in pieces))
        right.append(max(p[1] for p in pieces))
    if not centres:
        return None
    z = np.array([centres[0] - step / 2, *centres, centres[-1] + step / 2])
    return SectionChains(z, np.array([left[0], *left, left[-1]]), np.array([right[0], *right, right[-1]]), area)


def clipped_outline(slicer: HullSlicer, x: float, y_range, z_range, dz: float):
    """Area of the hull section at x inside the y and z ranges, and its outline [[y, z], ...]
    (``section_chains``; None when nothing is inside)."""
    chains = section_chains(slicer, x, y_range, z_range, dz)
    if chains is None:
        return 0.0, None
    return chains.area, chains.outline()


def tank_slabs_in_hull(slicer: HullSlicer, x_range, y_of_x, z_of_x, slab_m: float, row_dz_m: float):
    """Slabs of a tank: plan extent ``y_of_x(x)`` and vertical limits ``z_of_x(x)`` (each a
    (low, high) pair or None), clipped to the hull, one slab per ``slab_m`` in x."""
    slabs = []
    edges = list(np.arange(x_range[0], x_range[1], slab_m)) + [x_range[1]]
    for xa, xb in zip(edges, edges[1:]):
        if xb - xa < 1e-3:
            continue
        middle = (xa + xb) / 2
        y_range, z_range = y_of_x(middle), z_of_x(middle)
        if not (y_range and z_range):
            continue
        _, outline = clipped_outline(slicer, middle, y_range, z_range, row_dz_m)
        if outline:
            slabs.append((float(xa), float(xb), outline))
    return slabs


# The most levels per chain of a lofted tank section (a 4 m tank at 0.02 m rows needs 202).
MAX_LOFT_LEVELS = 400


@dataclass
class TankLoft:
    """A tank solid lofted through hull sections: one or more runs of rings.

    Each run is an array (stations, ring points, 3) in ship metres. A ring is the section at one
    x resampled at the same share of its height on both chains (up the left chain, down the
    right chain), so ring point k of one station joins ring point k of the next by a straight
    line. The side between two stations is ruled; the solid has no steps.
    """
    runs: list[np.ndarray]

    def triangles(self) -> np.ndarray | None:
        """Closed outward triangle mesh of all runs (None when there is no run)."""
        pieces = [loft_run_triangles(run) for run in self.runs]
        return outward(np.concatenate(pieces)) if pieces else None

    def outlines(self, digits: int = 3) -> dict[str, list[list[list[float]]]]:
        """Profile and plan outlines for 2D views: per run, the lowest and highest point of each
        station section (profile [[x, z], ...]) and its outermost breadths (plan [[x, y], ...]),
        as closed polygons going forward along the bottom (or starboard) edge and back along the
        top (or port) edge. Rounded to ``digits`` decimals (mm by default)."""
        def polygon(xs, low, high):
            points = list(zip(xs, low)) + list(zip(xs[::-1], high[::-1]))
            return [[round(float(a), digits), round(float(b), digits)] for a, b in points]

        profile, plan = [], []
        for run in self.runs:
            xs = run[:, 0, 0]
            profile.append(polygon(xs, run[:, :, 2].min(axis=1), run[:, :, 2].max(axis=1)))
            plan.append(polygon(xs, run[:, :, 1].min(axis=1), run[:, :, 1].max(axis=1)))
        return {"profile_m": profile, "plan_m": plan}


def _ring(x: float, chains: SectionChains, levels: int) -> np.ndarray:
    """Ring of 2 x ``levels`` points: the chains resampled at equal shares of the section height."""
    z = np.linspace(chains.z[0], chains.z[-1], levels)
    left = np.interp(z, chains.z, chains.left)
    right = np.interp(z, chains.z, chains.right)
    ring_y = np.concatenate([left, right[::-1]])
    ring_z = np.concatenate([z, z[::-1]])
    return np.column_stack([np.full(2 * levels, x), ring_y, ring_z])


def cap_triangles(ring_size: int) -> np.ndarray:
    """Ring indices of a cap: a strip of quads between the left and the right chain, in ring order."""
    levels = ring_size // 2
    k = np.arange(levels - 1)
    left_low, left_high = k, k + 1
    right_low, right_high = 2 * levels - 1 - k, 2 * levels - 2 - k
    return np.concatenate([np.column_stack([left_low, left_high, right_high]),
                           np.column_stack([left_low, right_high, right_low])])


def loft_run_triangles(run: np.ndarray) -> np.ndarray:
    """Closed mesh of one run (stations x ring x 3): ruled sides and two flat end caps.

    The side triangles hold each ring edge in ring order at the lower station and reversed at the
    higher one, so the first cap is reversed and the last cap keeps the ring order.
    """
    stations, ring_size = run.shape[:2]
    j = np.arange(ring_size)
    j_next = (j + 1) % ring_size
    sides = []
    for i in range(stations - 1):
        a, b = run[i], run[i + 1]
        sides.append(np.stack([a[j], a[j_next], b[j_next]], axis=1))
        sides.append(np.stack([a[j], b[j_next], b[j]], axis=1))
    cap = cap_triangles(ring_size)
    first = run[0][cap][:, ::-1]
    last = run[-1][cap]
    return np.concatenate([*sides, first, last])


def tank_loft_in_hull(slicer: HullSlicer, x_range, y_of_x, z_of_x, station_m: float,
                      row_dz_m: float) -> TankLoft:
    """Tank solid lofted through hull sections: plan extent ``y_of_x(x)`` and vertical limits
    ``z_of_x(x)`` (each a (low, high) pair or None), clipped to the hull.

    Sections are taken at both ends of ``x_range`` and at most ``station_m`` apart, each sampled in
    rows of ``row_dz_m``. Stations with no section split the tank into runs; a run needs two
    stations. Compared with slabs (``tank_slabs_in_hull``), the side is smooth in x and the
    section is not stepped in z.
    """
    count = max(1, int(np.ceil((x_range[1] - x_range[0]) / station_m - 1e-9)))
    stations = []
    for x in np.linspace(x_range[0], x_range[1], count + 1):
        y_range, z_range = y_of_x(x), z_of_x(x)
        chains = section_chains(slicer, x, y_range, z_range, row_dz_m) if (y_range and z_range) else None
        stations.append((float(x), chains))
    runs, current = [], []
    for x, chains in stations + [(None, None)]:
        if chains is not None:
            current.append((x, chains))
            continue
        if len(current) >= 2:
            levels = min(MAX_LOFT_LEVELS, max(len(c.z) for _, c in current))
            runs.append(np.stack([_ring(x_i, c, levels) for x_i, c in current]))
        current = []
    return TankLoft(runs)


# ---------------------------------------------------------------------------
# Tank model file (one .npz: meshes plus JSON metadata)


def save_tanks(tanks: list[Tank], path) -> None:
    """Write tanks to an .npz file: ``meta`` (JSON) and one ``mesh_<n>`` array per built tank."""
    import json

    meta, arrays = [], {}
    for number, tank in enumerate(tanks):
        meta.append({"id": tank.id, "name": tank.name, "content": tank.content,
                     "frames": list(tank.frames) if tank.frames else None, "density_t_m3": tank.density_t_m3,
                     "source_labels": tank.source_labels, "printed_volume_m3": tank.printed_volume_m3,
                     "notes": tank.notes, "mesh": f"mesh_{number}" if tank.triangles is not None else None})
        if tank.triangles is not None:
            arrays[f"mesh_{number}"] = np.asarray(tank.triangles, dtype=float)
    np.savez_compressed(path, meta=np.array(json.dumps({"engineering_approved": False, "tanks": meta})),
                        **arrays)


def load_tanks(path) -> list[Tank]:
    import json

    with np.load(path, allow_pickle=False) as data:
        meta = json.loads(str(data["meta"]))
        return [Tank(entry["id"], entry["name"], entry["content"],
                     np.asarray(data[entry["mesh"]]) if entry["mesh"] else None,
                     tuple(entry["frames"]) if entry["frames"] else None, entry["density_t_m3"],
                     dict(entry["source_labels"]), entry["printed_volume_m3"], list(entry["notes"]))
                for entry in meta["tanks"]]
