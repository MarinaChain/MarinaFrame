"""Parts above the hull that follow the hull: decks, bulwarks and deckhouses.

Plan: docs/plans/2026-11-09-whole-vessel-scope.md, section 3.8.

Before this module every part above the hull was its GA plan outline extruded straight up.
The GA outline is the outermost line of the plan view (often the rail or the forecastle top), so
where the hull side is narrower at the deck (bow, stern) the part stood out past the hull.

``HullSide`` is the hull's half-breadth as a function of x and z, read from the same lines-plan
station sections that the hull loft uses. Above a station's drawn top the side continues with
the flare of its top rows (a labelled extrapolation, at most ``MAX_EXTRAPOLATION_M``).

The builders (``build_shaped``) describe each part by its plan shape at a height ``z``: the GA
outline's port and starboard extent at each x, cut to the hull side at that same height, between
end positions that may change with z (a raked end wall). A solid is a ruled loft through these
plan polygons at a few heights; every polygon has the same number of points, so the ruling stays
between corresponding points. A deck with camber is a ruled loft of transverse sections instead.

Coordinates: x from frame 0 (positive forward), y to port, z from the baseline, metres.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from itertools import pairwise

import numpy as np

# Height step of the half-breadth grid. The station rows are about 0.05 m apart near the deck.
HULL_GRID_M = 0.05
# The flare above a station's top is the slope of its rows over this height below the top.
FLARE_FIT_M = 0.5
# The side is continued with the flare at most this far above the drawn top; higher, it is
# constant (a bulwark or rail stands at most about 1.5 m above the drawn sheer).
MAX_EXTRAPOLATION_M = 1.5
# Two stations closer than this in x are one station (the larger half-breadth wins).
SAME_STATION_M = 1e-6
# A plan shape is cut where it is narrower than this (the bow tip). Narrower ends would make the
# port and starboard points meet; and lines plans draw the stem bar about 0.1 m wide, so a hull
# narrower than 0.3 m is the stem bar, whose end jumps between heights (a ragged loft).
MIN_WIDTH_M = 0.60
# Point spacing along x of the plan polygons (the GA outline is read to about 0.02 m; 0.2 m
# keeps a 20 m deckhouse at about 200 faces per level band).
PLAN_SPACING_M = 0.2
# Grid spacing used to find where a plan shape is wide enough (finer than PLAN_SPACING_M).
SEARCH_SPACING_M = 0.02
# Loft levels at most this far apart, so the sides follow the hull's curved flare.
LEVEL_STEP_M = 0.6
# Points across a cambered deck section (a parabola is within 1 mm at this count for B/50).
CAMBER_POINTS = 21
# A GA outline outside the hull side by more than this becomes a check item.
CHECK_TOLERANCE_M = 0.02
# A window recess when the drawings give no depth (a window set into its frame).
DEFAULT_WINDOW_RECESS_M = 0.05
# A window is cut only this far or more from the ends of the wall at its height.
WINDOW_END_MARGIN_M = 0.1
# The cutting box reaches this far outside the wall, past any flare.
WINDOW_TOOL_REACH_M = 1.0
# Plan points that lie this close to a straight edge at every level are left out of the loft.
SIMPLIFY_TOLERANCE_M = 0.005
# Two loft levels closer than this are one level.
SAME_LEVEL_M = 0.001
# A level band is split while its ruled surface is further than this outside the hull side at
# heights inside it (a quarter of the containment tolerance), down to bands of 2 x MIN_BAND_M.
REFINE_TOLERANCE_M = 0.01
MIN_BAND_M = 0.005
# Heights (as fractions of a band) where the ruled loft is checked against the hull side.
CHORD_CHECK_FRACTIONS = (0.1, 0.3, 0.5, 0.7, 0.9)
# A plan side is on the hull where the hull side is narrower than the GA outline by more than
# this; a part with such a side gets smooth walls (``smooth_body``), others stay ruled and flat.
ON_HULL_M = 0.001
# How a part's walls are made (``build_shaped`` reports it): smooth B-spline surfaces through
# the hull side, ruled bands between plan sections, or flat (a deck plate).
SMOOTH_WALLS = 'smooth_bspline'
RULED_WALLS = 'ruled_bands'
PLANAR_WALLS = 'planar'
# Smooth walls: section heights at most this far apart (a cubic through the hull side's
# rows; the flare of Gunnerus bends over about 1 m of height).
SMOOTH_LEVEL_STEP_M = 0.3
# Rounds of adding a section height in each band whose surface leaves the hull side by more
# than REFINE_TOLERANCE_M; after that the part is built from ruled bands (``smooth_fallback``).
SMOOTH_REFINE_ROUNDS = 6
# Surface points per lateral face for that check (along the side, up the side).
SURFACE_CHECK_SAMPLES = (240, 48)
# Smooth ends: x as a polynomial of this degree in z, fitted to plans with this many points.
END_FIT_DEGREE = 3
END_FIT_SAMPLES = 8
# Faces of a smooth bulwark wall are sewn at this tolerance (metres; their edges are shared
# copies of the same curves).
SEWING_TOLERANCE_M = 1e-6
# A sewn wall's volume must be within this share of (outer loft - inner loft); a wrongly sewn
# shell is off by whole parts.
WALL_VOLUME_TOLERANCE = 0.001


class HullSide:
    """Half-breadth of the hull side on a grid of stations (x) and heights (z)."""

    def __init__(self, x_m, z_m, half_breadth_m):
        self.x = np.asarray(x_m, dtype=float)
        self.z = np.asarray(z_m, dtype=float)
        self.half_breadth_grid = np.asarray(half_breadth_m, dtype=float)
        if self.half_breadth_grid.shape != (len(self.x), len(self.z)) or len(self.x) < 2 or len(self.z) < 2:
            raise ValueError('hull side grid shape')

    @classmethod
    def from_sections(cls, sections: list[dict]) -> HullSide:
        """Grid from station sections: ``{'x_m', 'regions': [{'rows_m': [[z, y_in, y_out], ...]}]}``."""
        stations = sorted(sections, key=lambda section: section['x_m'])
        rows = [np.asarray(region['rows_m'], dtype=float) for s in stations for region in s['regions']]
        z_low = min(r[:, 0].min() for r in rows)
        z_high = max(r[:, 0].max() for r in rows) + MAX_EXTRAPOLATION_M
        z = np.arange(np.floor(z_low / HULL_GRID_M), np.ceil(z_high / HULL_GRID_M) + 1) * HULL_GRID_M
        xs, grid = [], []
        for section in stations:
            values = station_half_breadths(section['regions'], z)
            if xs and section['x_m'] - xs[-1] < SAME_STATION_M:
                grid[-1] = np.maximum(grid[-1], values)
                continue
            xs.append(float(section['x_m']))
            grid.append(values)
        return cls(xs, z, np.array(grid))

    def to_dict(self) -> dict:
        return {'x_m': self.x.round(4).tolist(), 'z_m': self.z.round(4).tolist(),
                'half_breadth_m': self.half_breadth_grid.round(4).tolist()}

    @classmethod
    def from_dict(cls, data: dict) -> HullSide:
        return cls(data['x_m'], data['z_m'], data['half_breadth_m'])

    @property
    def x_range(self) -> tuple[float, float]:
        return float(self.x[0]), float(self.x[-1])

    def half_breadth(self, x, z) -> np.ndarray:
        """Half-breadth at (x, z), linear in both; zero outside the station range in x."""
        x, z = np.broadcast_arrays(np.asarray(x, dtype=float), np.asarray(z, dtype=float))
        shape = x.shape
        x, z = x.ravel(), np.clip(z.ravel(), self.z[0], self.z[-1])
        position = (z - self.z[0]) / (self.z[1] - self.z[0])
        lower = np.clip(np.floor(position).astype(int), 0, len(self.z) - 2)
        weight = position - lower
        station = np.clip(np.searchsorted(self.x, x, side='right') - 1, 0, len(self.x) - 2)
        t = np.clip((x - self.x[station]) / (self.x[station + 1] - self.x[station]), 0.0, 1.0)

        def at(stations):
            grid = self.half_breadth_grid
            return grid[stations, lower] * (1 - weight) + grid[stations, lower + 1] * weight

        result = at(station) * (1 - t) + at(station + 1) * t
        inside = (x >= self.x[0]) & (x <= self.x[-1])
        return np.where(inside, result, 0.0).reshape(shape)

    def outside_distance(self, x, y, z, *, x_step_m: float = 0.02) -> np.ndarray:
        """Plan distance of each point outside the hull side at its own height (0 when inside).

        The distance is the smaller of the lateral distance (``|y|`` less the half-breadth at x)
        and the longitudinal distance to the nearest x where the side is at least ``|y|`` wide
        (the bow and stern ends). Points: arrays of the same length.
        """
        x, y, z = (np.asarray(v, dtype=float).ravel() for v in (x, y, z))
        half_breadth = self.half_breadth(x, z)
        # Where the hull has no side at this x and z (beyond its ends) only the x distance counts.
        lateral = np.where(half_breadth > 0, np.maximum(np.abs(y) - half_breadth, 0.0), np.inf)
        result = np.where(np.isfinite(lateral), lateral, 0.0)
        outside = np.nonzero(lateral > 0)[0]
        grid_x = np.arange(self.x[0], self.x[-1] + x_step_m, x_step_m)
        for index in outside:
            wide = grid_x[self.half_breadth(grid_x, np.full_like(grid_x, z[index])) >= max(abs(y[index]), 1e-9)]
            longitudinal = float(np.abs(wide - x[index]).min()) if len(wide) else np.inf
            best = min(lateral[index], longitudinal)
            # No side at this height at all: the point is as far out as it is from the centreline.
            result[index] = best if np.isfinite(best) else abs(y[index])
        return result


def station_half_breadths(regions: list[dict], z: np.ndarray) -> np.ndarray:
    """Outer half-breadth of one station at each height of ``z``.

    Inside the drawn rows: the largest outer offset over the regions. Above the drawn top: the
    top offset plus the flare of the top rows, for at most ``MAX_EXTRAPOLATION_M``. Below the
    lowest row: zero.
    """
    values = np.zeros_like(z)
    top_z, top_rows = -np.inf, None
    for region in regions:
        rows = np.asarray(region['rows_m'], dtype=float)
        rows = rows[np.argsort(rows[:, 0], kind='stable')]
        inside = (z >= rows[0, 0]) & (z <= rows[-1, 0])
        values[inside] = np.maximum(values[inside], np.interp(z[inside], rows[:, 0], rows[:, 2]))
        if rows[-1, 0] > top_z:
            top_z, top_rows = rows[-1, 0], rows
    above = z > top_z
    if top_rows is not None and above.any():
        top_y = top_rows[-1, 2]
        below = top_rows[top_rows[:, 0] <= top_z - FLARE_FIT_M]
        flare = 0.0
        if len(below):
            reference_z = top_z - FLARE_FIT_M
            reference_y = np.interp(reference_z, top_rows[:, 0], top_rows[:, 2])
            flare = (top_y - reference_y) / FLARE_FIT_M
        rise = np.minimum(z[above] - top_z, MAX_EXTRAPOLATION_M)
        values[above] = np.maximum(top_y + flare * rise, 0.0)
    return values


def outline_extent(outline, xs) -> tuple[np.ndarray, np.ndarray]:
    """Smallest and largest y of the outline on the vertical line at each x (NaN: no crossing).

    A notch in the outline is filled: the plan shape keeps one port and one starboard edge.
    """
    points = np.asarray(outline, dtype=float)
    a, b = points, np.roll(points, -1, axis=0)
    x = np.asarray(xs, dtype=float)[:, None]
    low_x, high_x = np.minimum(a[:, 0], b[:, 0]), np.maximum(a[:, 0], b[:, 0])
    crosses = (x >= low_x) & (x <= high_x)
    span = np.where(b[:, 0] == a[:, 0], 1.0, b[:, 0] - a[:, 0])
    t = np.clip((x - a[:, 0]) / span, 0.0, 1.0)
    y = a[:, 1] + t * (b[:, 1] - a[:, 1])
    vertical = b[:, 0] == a[:, 0]
    low_y = np.where(vertical, np.minimum(a[:, 1], b[:, 1]), y)
    high_y = np.where(vertical, np.maximum(a[:, 1], b[:, 1]), y)
    with np.errstate(invalid='ignore'):
        low = np.where(crosses, low_y, np.inf).min(axis=1)
        high = np.where(crosses, high_y, -np.inf).max(axis=1)
    return np.where(np.isfinite(low), low, np.nan), np.where(np.isfinite(high), high, np.nan)


@dataclass
class PlanShape:
    """A part's plan: the GA outline, end positions by height and plan corner rounding."""
    outline: list
    # End wall position by height: {'aft': [[z, x], ...], 'fwd': [[z, x], ...]}; a missing end is
    # vertical at the outline's end.
    ends: dict = field(default_factory=dict)
    # Plan corner radius at each end: {'aft': r, 'fwd': r} (metres; 0 is a square corner).
    corner_radius_m: dict = field(default_factory=dict)

    def end_x(self, side: str, z: float) -> float:
        contour = self.ends.get(side)
        if contour:
            contour = sorted(contour)
            return float(np.interp(z, [p[0] for p in contour], [p[1] for p in contour]))
        xs = np.asarray(self.outline, dtype=float)[:, 0]
        return float(xs.min() if side == 'aft' else xs.max())

    def end_breakpoints(self) -> list[float]:
        return [p[0] for side in ('aft', 'fwd') for p in (self.ends.get(side) or [])]


def _longest_run(mask: np.ndarray) -> tuple[int, int] | None:
    best, start = None, None
    for index, value in enumerate(list(mask) + [False]):
        if value and start is None:
            start = index
        elif not value and start is not None:
            if best is None or index - start > best[1] - best[0] + 1:
                best = (start, index - 1)
            start = None
    return best


def _round_corners(xs, low, high, radius: dict):
    """Pull the plan in near each end along a quarter circle of that end's radius."""
    pull = np.zeros_like(xs)
    for side, distance in (('aft', xs - xs[0]), ('fwd', xs[-1] - xs)):
        r = float(radius.get(side, 0.0))
        near = distance < r
        pull[near] = np.maximum(pull[near], r - np.sqrt(r ** 2 - (r - distance[near]) ** 2))
    pull = np.minimum(pull, np.maximum((high - low - MIN_WIDTH_M) / 2, 0.0))
    return low + pull, high - pull


def _chord_excess(xs, ys, dense_x, dense_y) -> np.ndarray:
    """How far to pull each point in so that the straight edges stay inside the true edge.

    Between two points the plan edge is straight; where the true edge bends inwards (a hull
    station between them), the straight edge would cut outside it. Each point moves in by the
    largest such excess of its two edges, which keeps both edges inside.
    """
    chord = np.interp(dense_x, xs, ys)
    excess = np.maximum(chord - dense_y, 0.0)
    edge = np.clip(np.searchsorted(xs, dense_x, side='right') - 1, 0, len(xs) - 2)
    per_edge = np.zeros(len(xs) - 1)
    np.maximum.at(per_edge, edge, excess)
    return np.maximum(np.concatenate([[0.0], per_edge]), np.concatenate([per_edge, [0.0]]))


def planform(shape: PlanShape, hull: HullSide | None, z: float, samples: int, *, inset: float = 0.0,
             x_limits: tuple[float, float] | None = None) -> dict | None:
    """The plan polygon at height z with ``samples`` points per side, or None when nothing is left.

    ``x_limits`` (aft, forward) shortens the plan to that x range (smooth ends, ``EndCurves``).

    Also returns how far the GA outline is outside the hull side at this height (``excess_m``,
    lateral) and how much of its x range the hull cuts off (``cut_m``, aft and forward).
    """
    outline_x = np.asarray(shape.outline, dtype=float)[:, 0]
    first, last = outline_x.min(), outline_x.max()
    x_aft, x_fwd = shape.end_x('aft', z) + inset, shape.end_x('fwd', z) - inset
    if x_fwd - x_aft < MIN_WIDTH_M:
        return None

    def extent(xs):
        # Beyond the outline's own ends (a raked end that reaches past it) the end breadth holds.
        low, high = outline_extent(shape.outline, np.clip(xs, first + 1e-6, last - 1e-6))
        ga_low, ga_high = low + inset, high - inset
        if hull is None:
            return ga_low, ga_high, ga_low, ga_high
        side = hull.half_breadth(xs, np.full_like(xs, z)) - inset
        return np.maximum(ga_low, -side), np.minimum(ga_high, side), ga_low, ga_high

    dense = np.linspace(x_aft, x_fwd, max(2, int(np.ceil((x_fwd - x_aft) / SEARCH_SPACING_M)) + 1))
    low, high, ga_low, ga_high = extent(dense)
    with np.errstate(invalid='ignore'):
        run = _longest_run(high - low >= MIN_WIDTH_M)
        excess = np.nan_to_num(np.maximum(ga_high - high, low - ga_low), nan=0.0)
    if hull is not None:
        # Beyond the hull's ends the disagreement is longitudinal (``cut_m``), not lateral.
        excess[hull.half_breadth(dense, np.full_like(dense, z)) <= 0] = 0.0
    if run is None:
        return None
    x0, x1 = dense[run[0]], dense[run[1]]
    if x_limits is not None:
        x0, x1 = max(x0, x_limits[0]), min(x1, x_limits[1])
        if x1 - x0 < MIN_WIDTH_M:
            return None
    worst = int(np.argmax(excess))
    # Cosine spacing: points crowd towards both ends, where a hull end narrows fastest (a chord
    # between two far-apart points there would cut outside the stem). Mid-length spacing is
    # about pi/2 times the mean spacing.
    xs = x0 + (x1 - x0) * (1 - np.cos(np.linspace(0.0, np.pi, samples))) / 2
    low, high, _, _ = extent(xs)
    inside = (dense >= x0) & (dense <= x1)
    dense_low, dense_high, _, _ = extent(dense[inside])
    high = high - _chord_excess(xs, high, dense[inside], dense_high)
    low = low + _chord_excess(xs, -low, dense[inside], -dense_low)
    low, high = _round_corners(xs, low, high, shape.corner_radius_m)
    polygon = np.concatenate([np.column_stack([xs, high]), np.column_stack([xs, low])[::-1]])
    on_hull = False
    if hull is not None:
        sample_low, sample_high, sample_ga_low, sample_ga_high = extent(xs)
        with np.errstate(invalid='ignore'):
            on_hull = bool(np.any(sample_high < sample_ga_high - ON_HULL_M)
                           or np.any(sample_low > sample_ga_low + ON_HULL_M))
    return {'polygon': polygon, 'x': xs, 'low': low, 'high': high, 'x_range': [float(x0), float(x1)],
            'on_hull': on_hull,
            'excess_m': float(excess[worst]), 'excess_x_m': float(dense[worst]),
            'cut_m': [float(x0 - x_aft), float(x_fwd - x1)]}


def sample_count(shape: PlanShape, levels) -> int:
    """Points per side so that the widest spacing (mid-length, cosine spacing) is PLAN_SPACING_M."""
    length = max(shape.end_x('fwd', z) - shape.end_x('aft', z) for z in levels)
    return max(8, int(np.ceil(np.pi / 2 * length / PLAN_SPACING_M)) + 1)


def loft_heights(low: float, high: float, breakpoints=(), step: float = LEVEL_STEP_M) -> list[float]:
    count = max(1, int(np.ceil((high - low) / step)))
    heights = list(np.linspace(low, high, count + 1)) + [z for z in breakpoints if low < z < high]
    result = []
    for z in sorted(heights):
        if not result or z - result[-1] > SAME_LEVEL_M:
            result.append(float(z))
    result[-1] = float(high)
    return result


def _wire(points3d):
    import cadquery as cq

    return cq.Wire.makePolygon([cq.Vector(*p) for p in points3d], close=True)


def shared_points(polygons: list[np.ndarray], tolerance: float = SIMPLIFY_TOLERANCE_M) -> np.ndarray:
    """Indices of the points to keep in every polygon (the same in all, so the rulings match).

    A point is left out when, at every level, the straight edge between the points kept on each
    side of it passes within ``tolerance`` of it (Douglas-Peucker over all levels at once). The
    polygons are two chains, port then starboard; the four end points always stay.
    """
    stack = np.stack(polygons)  # levels x points x 2
    count = stack.shape[1]
    half = count // 2
    keep = {0, half - 1, half, count - 1}

    def split(first, last):
        if last - first < 2:
            return
        start, end = stack[:, first:first + 1], stack[:, last:last + 1]
        direction = end - start
        length = np.linalg.norm(direction, axis=2, keepdims=True)
        length = np.where(length > 0, length, 1.0)
        offset = stack[:, first + 1:last] - start
        distance = np.abs(direction[..., 0] * offset[..., 1] - direction[..., 1] * offset[..., 0]) / length[..., 0]
        worst = distance.max(axis=0)
        index = int(np.argmax(worst))
        if worst[index] > tolerance:
            middle = first + 1 + index
            keep.add(middle)
            split(first, middle)
            split(middle, last)

    split(0, half - 1)
    split(half, count - 1)
    return np.array(sorted(keep))


def loft_plans(levels: list[tuple[float, np.ndarray]]):
    """Ruled solid through plan polygons ``[(z, polygon)]`` of equal point count.

    Points that every level has on a straight edge are left out first: a parallel body then
    gives one ruled face per band instead of one per point (the STEP is about ten times smaller).
    """
    import cadquery as cq

    kept = shared_points([polygon for _, polygon in levels])
    wires = [_wire([(x, y, z) for x, y in polygon[kept]]) for z, polygon in levels]
    return cq.Solid.makeLoft(wires, True)


def _plans(shape, hull, placements, samples, inset=0.0, ends=None):
    """Plan polygons at each (placed z, read z); None when a level has no shape.

    ``ends`` (an ``EndCurves``) gives each level's x range.
    """
    plans = []
    for placed, read in placements:
        limits = ends.at(read) if ends is not None else None
        plan = planform(shape, hull, read, samples, inset=inset, x_limits=limits)
        if plan is None:
            return None
        plans.append((placed, plan))
    return plans


def refine_heights(shape, hull, heights, samples, inset=0.0) -> list[float]:
    """Add levels where the ruled loft between two levels would leave the hull side.

    Between two levels each plan point moves on a straight line. Where the middle of such a line
    is outside the hull side at its height by more than ``REFINE_TOLERANCE_M`` (a curved stem or
    flare), the band is split, down to bands of ``MIN_BAND_M``.
    """
    if hull is None:
        return list(heights)
    result = [heights[0]]
    for low, high in zip(heights[:-1], heights[1:]):
        stack = [(low, high)]
        while stack:
            a, b = stack.pop()
            if b - a > 2 * MIN_BAND_M and _chord_outside(shape, hull, a, b, samples, inset) > REFINE_TOLERANCE_M:
                middle = (a + b) / 2
                stack += [(middle, b), (a, middle)]
                continue
            result.append(b)
    return result


def _chord_outside(shape, hull, a, b, samples, inset) -> float:
    """Largest lateral distance outside the hull of the ruling midpoints between levels a and b."""
    plans = [planform(shape, hull, z, samples, inset=inset) for z in (a, b)]
    if not all(plans):
        return 0.0
    worst = -np.inf
    for fraction in CHORD_CHECK_FRACTIONS:
        ruling = plans[0]['polygon'] * (1 - fraction) + plans[1]['polygon'] * fraction
        # Points on the rulings and halfway between neighbouring rulings (the ruled quads).
        points = np.concatenate([ruling, (ruling + np.roll(ruling, -1, axis=0)) / 2])
        z = a + (b - a) * fraction
        side = hull.half_breadth(points[:, 0], np.full(len(points), z)) - inset
        worst = max(worst, float((np.abs(points[:, 1]) - side).max()))
    return worst


def follows_hull(plans) -> bool:
    """True when the hull side shapes the plan of the part at any of its levels."""
    return any(plan['on_hull'] for _, plan in plans)


def _side_edge(xs, ys, z, parameters):
    import cadquery as cq

    return cq.Edge.makeSpline([cq.Vector(float(x), float(y), z) for x, y in zip(xs, ys)],
                              parameters=list(parameters), scale=False)


def smooth_section(plan: dict, z: float):
    """The plan at height z as four edges: port and starboard sides as cubic B-splines through
    the plan points, the ends as straight lines.

    Every level uses the same spline parameters (the point index, scaled to 0..1), so all side
    curves share one knot vector and the loft keeps one B-spline face per side.
    """
    import cadquery as cq

    xs, low, high = plan['x'], plan['low'], plan['high']
    parameters = np.linspace(0.0, 1.0, len(xs))
    port = _side_edge(xs, high, z, parameters)
    starboard = _side_edge(xs[::-1], low[::-1], z, parameters)
    fwd = cq.Edge.makeLine(cq.Vector(float(xs[-1]), float(high[-1]), z), cq.Vector(float(xs[-1]), float(low[-1]), z))
    aft = cq.Edge.makeLine(cq.Vector(float(xs[0]), float(low[0]), z), cq.Vector(float(xs[0]), float(high[0]), z))
    return cq.Wire.assembleEdges([port, fwd, starboard, aft])


def smooth_loft(levels: list[tuple[float, dict]]):
    """A solid through the plan sections ``[(z, plan)]``, smooth (not ruled) between them.

    Each side is one B-spline surface through all sections; the base and top are planar.
    """
    import cadquery as cq

    return cq.Solid.makeLoft([smooth_section(plan, z) for z, plan in levels], False)


def surface_outside(solid, hull: HullSide, inset: float = 0.0) -> tuple[np.ndarray, np.ndarray]:
    """Heights and distances outside the hull side (less ``inset``) of points on every curved
    face of the solid (planar faces lie in a checked plan section): lateral, or past the hull's
    end stations in x."""
    from OCP.BRepAdaptor import BRepAdaptor_Surface

    points = []
    for face in solid.Faces():
        if face.geomType() == 'PLANE':
            continue
        surface = BRepAdaptor_Surface(face.wrapped)
        us = np.linspace(surface.FirstUParameter(), surface.LastUParameter(), SURFACE_CHECK_SAMPLES[0])
        vs = np.linspace(surface.FirstVParameter(), surface.LastVParameter(), SURFACE_CHECK_SAMPLES[1])
        points += [surface.Value(u, v).Coord() for u in us for v in vs]
    if not points:
        return np.zeros(0), np.zeros(0)
    points = np.array(points)
    side = hull.half_breadth(points[:, 0], points[:, 2]) - inset
    lateral = np.abs(points[:, 1]) - side
    # Beyond the hull's end stations there is no side: the distance is how far past the end.
    first, last = hull.x_range
    beyond = np.maximum(first - points[:, 0], points[:, 0] - last)
    return points[:, 2], np.where(beyond > 0, beyond, lateral)


class SmoothLoftError(ValueError):
    """The smooth walls could not be kept inside the hull side (the ruled bands are used)."""


class EndCurves:
    """Smooth ends of a part where the hull cuts them: x as a cubic in z, inside the plan.

    Where the hull cuts a part's end (a raked stem), the end of the plan jumps between heights
    (the station rows and the stem bar), and a smooth loft through such ends swings outside the
    hull between its sections. The cubic is fitted to the plan's ends at heights
    ``HULL_GRID_M`` apart and moved inwards until it is inside all of them. An end that the
    hull does not cut keeps its drawn position (no limit).
    """

    def __init__(self, shape, hull, low: float, high: float, inset: float = 0.0):
        heights = np.linspace(low, high, max(END_FIT_DEGREE + 1, int(np.ceil((high - low) / HULL_GRID_M)) + 1))
        plans = [planform(shape, hull, z, END_FIT_SAMPLES, inset=inset) for z in heights]
        if any(plan is None for plan in plans):
            raise SmoothLoftError('a height has no plan for the end curves')
        ranges = np.array([plan['x_range'] for plan in plans])
        cut = np.array([plan['cut_m'] for plan in plans])
        self.low, self.high = low, high
        self.aft = self._fit(heights, ranges[:, 0], inside_is_larger=True) if cut[:, 0].max() > ON_HULL_M else None
        self.fwd = self._fit(heights, ranges[:, 1], inside_is_larger=False) if cut[:, 1].max() > ON_HULL_M else None

    @staticmethod
    def _fit(heights, ends, *, inside_is_larger: bool) -> np.polynomial.Polynomial:
        curve = np.polynomial.Polynomial.fit(heights, ends, END_FIT_DEGREE)
        outside = curve(heights) - ends
        shift = outside.min() if inside_is_larger else outside.max()
        return curve - shift

    def at(self, z: float) -> tuple[float, float]:
        z = float(np.clip(z, self.low, self.high))
        aft = float(self.aft(z)) if self.aft is not None else -np.inf
        fwd = float(self.fwd(z)) if self.fwd is not None else np.inf
        return aft, fwd


def smooth_body(shape, hull, placements, samples, inset=0.0, check_inset=None):
    """Smooth-walled solid through plans read at ``placements`` [(placed z, read z)].

    A band whose surface leaves the hull side by more than ``REFINE_TOLERANCE_M`` gets a section
    at its middle, for at most ``SMOOTH_REFINE_ROUNDS`` rounds. Only heights between the lowest
    and highest read height are checked (a cut body may reach past them). ``check_inset``
    (default ``inset``) is the inset the check holds the surface to. Returns (solid, plans).
    """
    check_inset = inset if check_inset is None else check_inset
    from .geometry import precise_volume_mm3

    placements = sorted(placements)
    reads = [read for _, read in placements]
    ends = EndCurves(shape, hull, min(reads), max(reads), inset)
    for _ in range(SMOOTH_REFINE_ROUNDS + 1):
        plans = _plans(shape, hull, placements, samples, inset, ends)
        if plans is None:
            raise SmoothLoftError('a section has no width inside the hull side')
        solid = smooth_loft(plans)
        if not solid.isValid() or precise_volume_mm3(solid) <= 0:
            raise SmoothLoftError('the smooth loft is not a valid solid')
        if hull is None:
            return solid, plans
        z, excess = surface_outside(solid, hull, check_inset)
        checked = (z >= min(reads)) & (z <= max(reads))
        z, excess = z[checked], excess[checked]
        bad = z[excess > REFINE_TOLERANCE_M]
        if not len(bad):
            return solid, plans
        added = []
        for (placed_a, read_a), (placed_b, read_b) in pairwise(placements):
            if np.any((bad >= placed_a) & (bad <= placed_b)):
                added.append(((placed_a + placed_b) / 2, (read_a + read_b) / 2))
        placements = sorted(placements + added)
    raise SmoothLoftError(f'the smooth walls stay {float(excess.max()):.3f} m outside the hull side')


def smooth_heights(low: float, high: float, breakpoints=()) -> list[float]:
    return loft_heights(low, high, breakpoints, SMOOTH_LEVEL_STEP_M)


def _fallback_item(part_id, error) -> dict:
    return {'kind': 'smooth_fallback', 'part': part_id,
            'note': f'Smooth side walls not built ({error}); the walls are ruled bands cut to the hull at '
                    'each height (stepped).'}


def _check_items(part_id, plans, kind='ga_outline_outside_hull') -> list[dict]:
    """GA/hull disagreement with its distance (the geometry follows the hull instead)."""
    worst = max(plans, key=lambda item: item[1]['excess_m'])
    items = []
    if worst[1]['excess_m'] > CHECK_TOLERANCE_M:
        items.append({'kind': kind, 'part': part_id, 'distance_m': round(worst[1]['excess_m'], 3),
                      'at_m': [round(worst[1]['excess_x_m'], 2), round(worst[0], 3)],
                      'note': 'The GA plan outline is outside the hull side here; the part follows the hull. '
                              'Check which drawing is right.'})
    cut = max(plans, key=lambda item: max(item[1]['cut_m']))
    if max(cut[1]['cut_m']) > CHECK_TOLERANCE_M:
        items.append({'kind': 'part_end_beyond_hull', 'part': part_id,
                      'distance_m': round(max(cut[1]['cut_m']), 3), 'at_m': [None, round(cut[0], 3)],
                      'note': 'The part reaches past the hull end at this height; it ends where the hull does.'})
    return items


def deck_plate(part_id, shape, hull, low, high, camber_m=0.0):
    """A deck plate whose edge is the hull side at the deck; camber raises its centre."""
    import cadquery as cq

    samples = sample_count(shape, [high])
    plan = planform(shape, hull, high, samples)
    if plan is None:
        raise ValueError('deck has no width inside the hull side')
    checks = _check_items(part_id, [(high, plan)])
    if camber_m <= 0:
        return loft_plans([(low, plan['polygon']), (high, plan['polygon'])]), checks
    thickness = high - low
    sections = []
    for x, y_low, y_high in zip(plan['x'], plan['low'], plan['high']):
        beam = float(hull.half_breadth(x, high)) if hull is not None else 0.0
        beam = beam if beam > 0 else max(abs(y_low), abs(y_high))
        ys = np.linspace(y_low, y_high, CAMBER_POINTS)
        top = high + camber_m * np.clip(1 - (ys / beam) ** 2, 0.0, 1.0)
        points = [(x, y, z) for y, z in zip(ys, top)] + [(x, y, z - thickness) for y, z in zip(ys[::-1], top[::-1])]
        sections.append(_wire(points))
    return cq.Solid.makeLoft(sections, True), checks


def _bulwark_placements(heights, margin):
    """Outer placements, and inner ones that reach past both ends so the cut leaves no skin."""
    outer = [(z, z) for z in heights]
    inner = [(heights[0] - margin, heights[0])] + outer[1:-1] + [(heights[-1] + margin, heights[-1])]
    return outer, inner


# The inner (cut) body of a bulwark reaches this far past its base and top.
BULWARK_CUT_MARGIN_M = 0.01


def _side_and_cap_faces(solid):
    """A loft's curved side faces and its two planar caps (base first)."""
    sides = [face for face in solid.Faces() if face.geomType() != 'PLANE']
    caps = sorted((face for face in solid.Faces() if face.geomType() == 'PLANE'), key=lambda face: face.Center().z)
    if len(caps) != 2:
        raise SmoothLoftError(f'a smooth loft has {len(caps)} planar caps, not 2')
    return sides, caps


def wall_between(outer, inner):
    """The solid between two smooth lofts with the same base and top heights (a bulwark).

    Sewn from both lofts' side faces and two planar ring caps. A Boolean cut of two such
    lofts is not reliable here (on the Gunnerus rail it kept most of the inner body).
    """
    import cadquery as cq
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeSolid, BRepBuilderAPI_Sewing
    from OCP.ShapeFix import ShapeFix_Solid
    from OCP.TopoDS import TopoDS

    from .geometry import precise_volume_mm3

    outer_sides, outer_caps = _side_and_cap_faces(outer)
    inner_sides, inner_caps = _side_and_cap_faces(inner)
    rings = [cq.Face.makeFromWires(o.outerWire(), [i.outerWire()]) for o, i in zip(outer_caps, inner_caps)]
    sewing = BRepBuilderAPI_Sewing(SEWING_TOLERANCE_M)
    for face in outer_sides + inner_sides + rings:
        sewing.Add(face.wrapped)
    sewing.Perform()
    solid = BRepBuilderAPI_MakeSolid(TopoDS.Shell_s(sewing.SewedShape())).Solid()
    fix = ShapeFix_Solid(solid)
    fix.Perform()
    wall = cq.Solid(fix.Solid())
    # The default volume integration is about 1 % off on these B-spline faces.
    expected = precise_volume_mm3(outer) - precise_volume_mm3(inner)
    if not wall.isValid() or abs(precise_volume_mm3(wall) - expected) > WALL_VOLUME_TOLERANCE * expected:
        raise SmoothLoftError('the smooth bulwark wall is not a valid closed solid')
    return wall


def _smooth_bulwark(shape, hull, low, high, thickness, samples):
    """Smooth bulwark walls, or None when the hull side does not shape the bulwark."""
    placements = [(z, z) for z in smooth_heights(low, high, shape.end_breakpoints())]
    outer = _plans(shape, hull, placements, samples)
    if outer is None or not follows_hull(outer):
        return None
    outer_solid, outer = smooth_body(shape, hull, placements, samples)
    # The inner surface only thins the wall where it leaves its inset, so it is held to half
    # the thickness (the wall keeps at least that).
    inner_solid, _ = smooth_body(shape, hull, placements, samples, inset=thickness, check_inset=thickness / 2)
    return wall_between(outer_solid, inner_solid), outer


def bulwark_wall(part_id, shape, hull, low, high, thickness):
    """A wall on the hull side from the deck to the bulwark top; it follows the drawn shell.

    Where the hull side shapes it, its walls are smooth B-spline surfaces (``smooth_body``);
    if those cannot be built inside the hull side, ruled bands are used with a check item.
    """
    heights = loft_heights(low, high, shape.end_breakpoints())
    samples = sample_count(shape, heights)
    fallback = []
    if hull is not None:
        try:
            smooth = _smooth_bulwark(shape, hull, low, high, thickness, samples)
            if smooth is not None:
                return smooth[0], _check_items(part_id, smooth[1]), SMOOTH_WALLS
        except Exception as exc:  # noqa: BLE001 - the ruled bands are the fallback
            fallback.append(_fallback_item(part_id, exc))
    heights = refine_heights(shape, hull, heights, samples)
    outer_at, inner_at = _bulwark_placements(heights, BULWARK_CUT_MARGIN_M)
    outer = _plans(shape, hull, outer_at, samples)
    inner = _plans(shape, hull, inner_at, samples, inset=thickness)
    if outer is None or inner is None:
        raise ValueError('bulwark has no width inside the hull side')
    solid = loft_plans([(z, plan['polygon']) for z, plan in outer]).cut(
        loft_plans([(z, plan['polygon']) for z, plan in inner]))
    return solid, _check_items(part_id, outer) + fallback, RULED_WALLS


def _smooth_house(shape, hull, low, high, samples):
    """Smooth deckhouse walls, or None when the hull side does not shape the deckhouse."""
    placements = [(z, z) for z in smooth_heights(low, high, shape.end_breakpoints())]
    plans = _plans(shape, hull, placements, samples)
    if plans is None or not follows_hull(plans):
        return None
    return smooth_body(shape, hull, placements, samples)


def house_body(part_id, shape, hull, low, high):
    """A deckhouse: base on the deck, sides on the hull where it reaches it, drawn end contours.

    A deckhouse that reaches the hull side gets smooth B-spline side walls (``smooth_body``);
    one inside the hull side keeps flat (ruled, planar) walls.
    """
    heights = loft_heights(low, high, shape.end_breakpoints())
    samples = sample_count(shape, heights)
    fallback = []
    if hull is not None:
        try:
            smooth = _smooth_house(shape, hull, low, high, samples)
            if smooth is not None:
                return smooth[0], _check_items(part_id, smooth[1]), SMOOTH_WALLS
        except Exception as exc:  # noqa: BLE001 - the ruled bands are the fallback
            fallback.append(_fallback_item(part_id, exc))
    heights = refine_heights(shape, hull, heights, samples)
    plans = _plans(shape, hull, [(z, z) for z in heights], samples)
    if plans is None:
        raise ValueError('deckhouse has no width inside the hull side')
    solid = loft_plans([(z, plan['polygon']) for z, plan in plans])
    return solid, _check_items(part_id, plans) + fallback, RULED_WALLS


def window_recesses(solid, shape, hull, windows, depth):
    """Cut each side window as a shallow recess into both side walls. Returns (solid, windows cut).

    A window is ``[x0, x1, z0, z1]`` from the side profile. It is cut only where it lies on a
    side wall at both its sill and its head (not across a raked end, which would cut a corner).
    """
    import cadquery as cq

    cut = []
    for x0, x1, z0, z1 in windows:
        plans = [planform(shape, hull, z, sample_count(shape, [z])) for z in (z0, (z0 + z1) / 2, z1)]
        if not all(plans) or any(not (p['x_range'][0] + WINDOW_END_MARGIN_M <= x0
                                      and x1 <= p['x_range'][1] - WINDOW_END_MARGIN_M) for p in plans):
            continue
        middle = plans[1]
        port = float(np.interp([x0, x1], middle['x'], middle['high']).min())
        starboard = float(np.interp([x0, x1], middle['x'], middle['low']).max())
        reach = WINDOW_TOOL_REACH_M
        for y0 in (port - depth, starboard - reach):
            tool = cq.Solid.makeBox(x1 - x0, depth + reach, z1 - z0, cq.Vector(x0, y0, z0))
            solid = solid.cut(tool)
        cut.append([x0, x1, z0, z1])
    return solid, cut


def build_shaped(part_id: str, op: str, values: dict, hull: HullSide | None, detail: dict | None = None):
    """Build a deck, bulwark or deckhouse that follows the hull. Returns (solid, report).

    ``detail`` holds this part's labelled detail values, each ``{'value', 'source', 'basis'}``:
    ``camber_m`` (decks); ``end_aft`` and ``end_fwd`` (``[[z, x], ...]`` end contours) and
    ``corner_radius_m`` (``{'aft': r, 'fwd': r}``) for the plan shape; ``windows``
    (``[[x0, x1, z0, z1], ...]``) and ``window_recess_m`` for deckhouses.
    The report lists the detail values used, the check items and how the walls are made
    (``walls``: smooth B-spline surfaces, ruled bands or planar).
    """
    detail = detail or {}

    def value(key, default):
        item = detail.get(key)
        return item['value'] if isinstance(item, dict) and 'value' in item else default

    ends = {side: value(f'end_{side}', None) for side in ('aft', 'fwd')}
    shape = PlanShape(values['outline'], ends={side: points for side, points in ends.items() if points},
                      corner_radius_m=value('corner_radius_m', {}) or {})
    low, high = values['height']
    used = [key for key in ('end_aft', 'end_fwd', 'corner_radius_m') if key in detail]
    cut = []
    walls = PLANAR_WALLS
    if op == 'deck':
        camber = float(value('camber_m', 0.0))
        solid, checks = deck_plate(part_id, shape, hull, low, high, camber)
        walls = PLANAR_WALLS if camber <= 0 else RULED_WALLS
        used += ['camber_m'] if 'camber_m' in detail else []
    elif op == 'bulwark':
        solid, checks, walls = bulwark_wall(part_id, shape, hull, low, high, values['thickness'])
    elif op == 'deckhouse':
        solid, checks, walls = house_body(part_id, shape, hull, low, high)
        windows = value('windows', [])
        if windows:
            solid, cut = window_recesses(solid, shape, hull, windows,
                                         float(value('window_recess_m', DEFAULT_WINDOW_RECESS_M)))
            if cut:
                used += [key for key in ('windows', 'window_recess_m') if key in detail]
    else:
        raise ValueError(f'{op} is not a part above the hull')
    return solid, {'detail_used': used, 'check_items': checks, 'windows_cut': cut, 'walls': walls}
