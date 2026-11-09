"""Extrude a transverse section along a parallel body, cut to a built hull (docs/STRUCTURE_V2.md section 8).

Coordinates are ship metres: x forward, y from the centre line (starboard positive), z above the
baseline. The hull is a ``tanks.HullSlicer`` (plane sections of its closed triangle mesh). Every
outline is cut to the hull section at each station, so members end where the hull narrows.

Members use the block-member dictionary of ``block3d``, ``steel`` and ``ocx``. A plate carries its
outline as ``contour`` (3D points in order); a stiffener carries a ``trace`` (3D polyline), a
``profile`` and an explicit ``volume_m3`` (its section area times its length).
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import math
import re

import numpy as np

from ..tanks import HullSlicer, clipped_outline

ROW_DZ_M = 0.005  # vertical sampling step of the hull sections
INSIDE_TOLERANCE_M = 0.010  # a point this close to the hull section counts as inside (G11)
# Bulb-flat (HP) section area as a share of its web area (height x thickness). The drawings print
# the HP name only; standard HP tables give about 1.2 to 1.35 for these sizes (guessed value).
BULB_AREA_SHARE = 1.25


# --- profiles ----------------------------------------------------------------------------

@dataclass(frozen=True)
class Profile:
    """A stiffener section as printed: name, OCX section kind and its dimensions in mm."""
    name: str
    kind: str  # "BulbFlat", "FlatBar" or "TBar" (the OCX section element)
    height_mm: float
    web_mm: float
    flange_width_mm: float = 0.0
    flange_thickness_mm: float = 0.0

    def area_m2(self) -> float:
        web = self.height_mm * self.web_mm
        if self.kind == "BulbFlat":
            return web * BULB_AREA_SHARE / 1e6
        return (web + self.flange_width_mm * self.flange_thickness_mm) / 1e6

    def as_dict(self) -> dict:
        return asdict(self)


PROFILE_PATTERNS = (
    (re.compile(r"^HP\s*(\d+)\s*x\s*(\d+(?:[.,]\d+)?)$", re.I), "BulbFlat"),
    (re.compile(r"^(?:FB|FL\.?)?\s*(\d+)\s*x\s*(\d+(?:[.,]\d+)?)$", re.I), "FlatBar"),
)
TEE_PATTERN = re.compile(r"W:?\s*(\d+)\s*x\s*(\d+(?:[.,]\d+)?)\s*/\s*FL:?\s*(\d+)\s*x\s*(\d+(?:[.,]\d+)?)", re.I)


def _number(text: str) -> float:
    return float(text.replace(",", "."))


def parse_profile(text: str) -> Profile | None:
    """'HP 100x6' (bulb flat), 'FB 100x8' or '100x8' (flat bar), 'W:200x8 / FL:150x10' (tee)."""
    text = " ".join(text.split())
    tee = TEE_PATTERN.search(text)
    if tee:
        height, web, width, flange = (_number(g) for g in tee.groups())
        return Profile(text, "TBar", height + flange, web, width, flange)
    for pattern, kind in PROFILE_PATTERNS:
        match = pattern.match(text)
        if match:
            height, web = _number(match.group(1)), _number(match.group(2))
            prefix = "HP" if kind == "BulbFlat" else "FB"
            return Profile(f"{prefix} {height:g}x{web:g}", kind, height, web)
    return None


# --- hull sections ---------------------------------------------------------------------

class HullSections:
    """Cached section queries of a built hull between two heights."""

    def __init__(self, slicer: HullSlicer, z_min: float, z_max: float, dz: float = ROW_DZ_M):
        self.slicer = slicer
        rows = int(math.ceil((z_max - z_min) / dz))
        self.zs = z_min + (np.arange(rows) + 0.5) * dz
        self.dz = dz
        self._cache: dict[float, list[list[tuple[float, float]]]] = {}

    def rows(self, x: float) -> list[list[tuple[float, float]]]:
        key = round(x, 6)
        if key not in self._cache:
            self._cache[key] = self.slicer.intervals(x, self.zs)
        return self._cache[key]

    def area(self, x: float) -> float:
        return sum(b - a for row in self.rows(x) for a, b in row) * self.dz

    def pieces(self, x: float) -> int:
        """Largest number of separate hull pieces on one row (2 or more where skegs hang below)."""
        return max((len(row) for row in self.rows(x)), default=0)

    def _row_index(self, z: float) -> int:
        return int(np.clip(round((z - self.zs[0]) / self.dz), 0, len(self.zs) - 1))

    def half_breadth(self, x: float, z: float, side: int) -> float | None:
        """Outer y of the hull at height z on one side (+1 starboard, -1 port), or None."""
        row = self.rows(x)[self._row_index(z)]
        if not row:
            return None
        return max(b for _, b in row) if side > 0 else min(a for a, _ in row)

    def bottom_z(self, x: float, y: float) -> float | None:
        """Lowest hull height at (x, y): the bottom shell under that point."""
        for z, row in zip(self.zs, self.rows(x)):
            if any(a <= y <= b for a, b in row):
                return float(z - self.dz / 2)
        return None

    def keel_z(self, x: float) -> float | None:
        return self.bottom_z(x, 0.0)

    def outer_contour(self, x: float, side: int, z_top: float) -> list[tuple[float, float]]:
        """Shell line from the keel at the centre line up to z_top on one side, as (y, z) points."""
        keel = self.keel_z(x)
        if keel is None:
            return []
        points = [(0.0, keel)]
        for z, row in zip(self.zs, self.rows(x)):
            if z <= keel or z > z_top or not row:
                continue
            y = max(b for _, b in row) if side > 0 else min(a for a, _ in row)
            points.append((float(y), float(z)))
        top = self.half_breadth(x, z_top - self.dz, side)
        if top is not None:
            points.append((top, z_top))
        return points

    def inside(self, x: float, y: float, z: float, tolerance: float = INSIDE_TOLERANCE_M) -> bool:
        """True when (y, z) lies in the hull section at x or within ``tolerance`` of it."""
        low, high = self._row_index(z - tolerance), self._row_index(z + tolerance)
        rows = self.rows(x)
        return any(a - tolerance <= y <= b + tolerance for row in rows[low:high + 1] for a, b in row)


# --- seams on the shell line ---------------------------------------------------------------

@dataclass(frozen=True)
class Seam:
    """A strake boundary on the shell line: where |y| reaches a value ('y') or z does ('z')."""
    axis: str
    value_m: float
    label: str

    def reached(self, point: tuple[float, float]) -> float:
        """Signed distance past the seam (>= 0 once the shell line has crossed it)."""
        y, z = point
        return (abs(y) if self.axis == "y" else z) - self.value_m


def split_at_seams(points: list[tuple[float, float]], seams: list[Seam]) -> list[list[tuple[float, float]]]:
    """Cut a shell line (keel first) at each seam in order; returns len(seams) + 1 pieces."""
    pieces, current, index = [], [points[0]], 0
    for a, b in zip(points, points[1:]):
        while index < len(seams) and seams[index].reached(b) >= 0 > seams[index].reached(a):
            da, db = seams[index].reached(a), seams[index].reached(b)
            t = da / (da - db)
            cut = (a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1]))
            current.append(cut)
            pieces.append(current)
            current, index = [cut], index + 1
        current.append(b)
    pieces.append(current)
    while len(pieces) < len(seams) + 1:
        pieces.append([])
    return pieces


def polyline_length(points) -> float:
    return sum(math.dist(a, b) for a, b in zip(points, points[1:]))


def _trapezoid(xs: list[float], values: list[float]) -> float:
    return sum((x1 - x0) * (v0 + v1) / 2 for x0, x1, v0, v1 in zip(xs, xs[1:], values, values[1:]))


def _box(points) -> list[float]:
    array = np.asarray(points, dtype=float)
    return [*array.min(axis=0).tolist(), *array.max(axis=0).tolist()]


# --- member builders -------------------------------------------------------------------

def plate_member(member_id: str, label: str, group: str, contour: list, area_m2: float, thickness: dict,
                 sources: dict, basis: str) -> dict:
    """A plate in the block-member format. ``thickness`` holds mm, source and basis."""
    return {"member_id": member_id, "label": label, "group": group, "box": _box(contour),
            "contour": [[round(v, 6) for v in p] for p in contour], "area_m2": area_m2,
            "thickness_mm": thickness["mm"], "thickness_source": thickness["source"],
            "thickness_basis": thickness["basis"], "material": None, "material_source": "guessed",
            "sources": sources, "table_row": None, "basis": basis}


def stiffener_member(member_id: str, label: str, group: str, trace: list, profile: Profile,
                     profile_source: str, profile_basis: str, web_direction, sources: dict, basis: str) -> dict:
    """A stiffener: trace line, printed (or guessed) profile, web area and steel volume."""
    length = polyline_length(trace)
    return {"member_id": member_id, "label": label, "group": group, "box": _box(trace),
            "trace": [[round(v, 6) for v in p] for p in trace], "length_m": length,
            "profile": profile.as_dict(), "web_direction": list(web_direction),
            "area_m2": length * profile.height_mm / 1000, "thickness_mm": profile.web_mm,
            "thickness_source": profile_source, "thickness_basis": profile_basis,
            "volume_m3": length * profile.area_m2(), "material": None, "material_source": "guessed",
            "sources": sources, "table_row": profile.name, "basis": basis}


def horizontal_plate(sections: HullSections, xs: list[float], z: float, y_band: tuple[float, float]):
    """Contour and area of a flat plate at height z between y_band, cut to the hull at each x.

    Returns None when the plate leaves the hull at any station (the caller splits runs there).
    """
    lows, highs = [], []
    for x in xs:
        port, starboard = sections.half_breadth(x, z, -1), sections.half_breadth(x, z, +1)
        if port is None:
            return None
        low, high = max(y_band[0], port), min(y_band[1], starboard)
        if high - low <= 1e-3:
            return None
        lows.append(low)
        highs.append(high)
    contour = [(x, y, z) for x, y in zip(xs, lows)] + [(x, y, z) for x, y in reversed(list(zip(xs, highs)))]
    area = _trapezoid(xs, [h - l for l, h in zip(lows, highs)])
    return contour, area


def vertical_plate(sections: HullSections, xs: list[float], y: float, z_top: float):
    """Contour and area of a longitudinal plate in the plane y, from the bottom shell up to z_top."""
    bottoms = [sections.bottom_z(x, y) for x in xs]
    if any(b is None or b >= z_top - 1e-3 for b in bottoms):
        return None
    contour = [(x, y, b) for x, b in zip(xs, bottoms)] + [(x, y, z_top) for x in reversed(xs)]
    return contour, _trapezoid(xs, [z_top - b for b in bottoms])


def shell_strake(sections: HullSections, xs: list[float], side: int, seams: list[Seam], index: int,
                 z_top: float):
    """Contour and area of strake ``index`` (between seams index-1 and index) on one side."""
    pieces = []
    for x in xs:
        piece = split_at_seams(sections.outer_contour(x, side, z_top), seams)[index]
        if len(piece) < 2:
            return None
        pieces.append(piece)
    girths = [polyline_length(p) for p in pieces]
    lower = [(x, p[0][0], p[0][1]) for x, p in zip(xs, pieces)]
    upper = [(x, p[-1][0], p[-1][1]) for x, p in zip(xs, pieces)]
    last_section = [(xs[-1], y, z) for y, z in pieces[-1][1:-1]]
    first_section = [(xs[0], y, z) for y, z in reversed(pieces[0][1:-1])]
    contour = lower + last_section + list(reversed(upper)) + first_section
    return contour, _trapezoid(xs, girths), girths


def transverse_plate(sections: HullSections, x: float, z_range: tuple[float, float],
                     y_range: tuple[float, float] = (-50.0, 50.0)):
    """Contour and area of a transverse plate at x: the hull section inside z_range (and y_range)."""
    area, outline = clipped_outline(sections.slicer, x, y_range, z_range, sections.dz)
    if not outline or area <= 0:
        return None
    return [(x, y, z) for y, z in outline], area


def runs_of(stations: list, keep) -> list[list]:
    """Contiguous runs of stations for which ``keep(station)`` is true (each run has 2+ stations)."""
    runs, current = [], []
    for station in stations:
        if keep(station):
            current.append(station)
        else:
            if len(current) >= 2:
                runs.append(current)
            current = []
    if len(current) >= 2:
        runs.append(current)
    return runs
