"""Deterministic general-arrangement (GA) reader for the whole-vessel envelope.

Plan: docs/plans/2026-11-09-whole-vessel-scope.md, step 1.

This is the earlier geometry reader, separate from the commercial label and frame-scale
pipeline (`ga_commercial` and `ga_scale`). That pipeline does not call this module. Keep
these vector/raster geometry helpers for whole-vessel envelope experiments and their tests.

The reader turns vector GA linework into ship-cad measurements:

- profile view: horizontal deck and roof levels (z) with their x extents;
- plan views: footprints of the region that the linework encloses, clipped to an
  x range from the profile.

A description names each component with selectors (a level hint, a plan view, a
footprint mode). Selectors are not geometry: the reader snaps them to drawn ink.
When the ink does not give a value, the reader writes a labelled guess
(source ``guessed``) so that the component is still built. It never stops a build.

Coordinates: x from frame 0 (positive forward), y positive to port, z from the
baseline, metres. Drawing units convert with ``metres_per_unit`` from the view origin.

``PlanRaster`` draws and traces outlines with OpenCV, which is an optional dependency (the
``plan-raster`` extra): the app's worker runtime does not bundle it, and no app path uses
``PlanRaster`` (docs/DEPENDENCIES_AND_RIGHTS.md).
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .raster_morphology import opening

# Profile lines shorter than this are details (doors, windows, furniture), not deck levels.
MIN_LEVEL_LENGTH_M = 1.5
# Collinear pieces of one level have the same drawn y to within round-off.
LEVEL_TOLERANCE_M = 0.002
# Pieces of one level closer than this along x are one extent (door gaps, hatch breaks).
LEVEL_GAP_M = 0.4
# A level hint selects the nearest drawn level within this distance; else the hint is a guess.
SNAP_TOLERANCE_M = 0.15
# Plan raster: cell size and the line width that closes small gaps between line ends.
PLAN_PIXEL_M = 0.02
PLAN_LINE_PIXELS = 3
# Drawn lines are up to one pixel wider than PLAN_LINE_PIXELS; the band must cover all of them.
EDGE_BAND_PIXELS = 2 * PLAN_LINE_PIXELS
# Outline simplification tolerance (a fraction of a deckhouse wall thickness). When the outline
# is not a simple polygon, the tolerance doubles, at most this many times in all.
OUTLINE_TOLERANCE_M = 0.02
OUTLINE_SIMPLIFY_STEPS = 5


@dataclass
class View:
    """Host calibration of one drawing view (reviewed by a person, not inferred)."""
    name: str
    kind: str  # 'profile' or 'plan'
    bounds: list[float]  # drawing units: x0, y0, x1, y1
    origin: list[float]  # drawing point of x = 0 and z = 0 (profile) or y = 0 (plan)
    metres_per_unit: float = 0.001
    layers: list[str] | None = None

    def to_ship(self, points: np.ndarray) -> np.ndarray:
        return (np.asarray(points, dtype=float) - np.asarray(self.origin)) * self.metres_per_unit

    def contains(self, points) -> bool:
        p = np.asarray(points, dtype=float)
        x0, y0, x1, y1 = self.bounds
        return bool((p[:, 0] >= x0).all() and (p[:, 0] <= x1).all() and (p[:, 1] >= y0).all()
                    and (p[:, 1] <= y1).all())


@dataclass
class Level:
    z_m: float
    intervals: list[list[float]] = field(default_factory=list)  # merged x extents, metres
    entity_ids: list[str] = field(default_factory=list)

    @property
    def x_range(self) -> list[float]:
        return [min(a for a, _ in self.intervals), max(b for _, b in self.intervals)]

    def extent_near(self, x_m: float | None) -> list[float]:
        """The merged extent that contains x (or the longest extent)."""
        if x_m is not None:
            for a, b in self.intervals:
                if a - LEVEL_GAP_M <= x_m <= b + LEVEL_GAP_M:
                    return [a, b]
        return list(max(self.intervals, key=lambda ab: ab[1] - ab[0]))


def _view_entities(entities, view: View):
    for entity in entities:
        if view.layers is not None and entity.get('layer') not in view.layers:
            continue
        if len(entity['points']) >= 2 and view.contains(entity['points']):
            yield entity


def _merge(intervals: list[list[float]], gap: float) -> list[list[float]]:
    merged: list[list[float]] = []
    for a, b in sorted(intervals):
        if merged and a <= merged[-1][1] + gap:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])
    return merged


def profile_levels(entities, view: View) -> list[Level]:
    """Horizontal drawn levels in a profile view, lowest first."""
    pieces = []
    for entity in _view_entities(entities, view):
        points = view.to_ship(entity['points'])
        for a, b in zip(points[:-1], points[1:]):
            if abs(a[1] - b[1]) <= LEVEL_TOLERANCE_M / 2 and abs(a[0] - b[0]) >= MIN_LEVEL_LENGTH_M:
                pieces.append((float((a[1] + b[1]) / 2), sorted([float(a[0]), float(b[0])]), entity['id']))
    pieces.sort(key=lambda piece: piece[0])
    groups: list[list] = []
    for piece in pieces:
        if groups and piece[0] - groups[-1][-1][0] <= LEVEL_TOLERANCE_M:
            groups[-1].append(piece)
        else:
            groups.append([piece])
    levels = []
    for group in groups:
        z = float(np.median([piece[0] for piece in group]))
        levels.append(Level(z_m=round(z, 4), intervals=_merge([piece[1] for piece in group], LEVEL_GAP_M),
                            entity_ids=sorted({piece[2] for piece in group})))
    return levels


def snap_level(levels: list[Level], z_hint: float, x_hint: float | None = None) -> Level | None:
    """Nearest drawn level to the hint (and over x_hint, when given); None if none is near."""
    candidates = [level for level in levels if abs(level.z_m - z_hint) <= SNAP_TOLERANCE_M]
    if x_hint is not None:
        candidates = [level for level in candidates
                      if any(a - LEVEL_GAP_M <= x_hint <= b + LEVEL_GAP_M for a, b in level.intervals)]
    if not candidates:
        return None
    return min(candidates, key=lambda level: (abs(level.z_m - z_hint), -sum(b - a for a, b in level.intervals)))


def transverse_walls(entities, view: View, x_range: list[float], min_length_m: float) -> list[dict]:
    """Straight lines across the ship (constant x) in a plan view, at least min_length_m long.

    A deckhouse end wall is such a line on the plan of the deck it stands on. Its roof can
    reach further (an overhang over an open area), so the walls, not the roof, give the end.
    """
    walls = []
    for entity in _view_entities(entities, view):
        points = view.to_ship(entity['points'])
        for a, b in zip(points[:-1], points[1:]):
            length = abs(float(a[1] - b[1]))
            if (abs(a[0] - b[0]) <= LEVEL_TOLERANCE_M and length >= min_length_m
                    and x_range[0] - LEVEL_GAP_M <= a[0] <= x_range[1] + LEVEL_GAP_M):
                walls.append({'x_m': round(float(a[0] + b[0]) / 2, 4), 'length_m': round(length, 4),
                              'entity_id': entity['id']})
    return sorted(walls, key=lambda wall: wall['x_m'])


def _row_clusters(mask: np.ndarray) -> list[tuple[int, int]]:
    """Runs of consecutive rows that contain ink (one drawn line is a few pixels thick)."""
    rows = np.nonzero(mask.any(axis=1))[0]
    clusters = []
    for row in rows:
        if clusters and row <= clusters[-1][1] + 1:
            clusters[-1][1] = row
        else:
            clusters.append([row, row])
    return [tuple(c) for c in clusters]


def _runs(line: np.ndarray) -> list[tuple[int, int]]:
    padded = np.r_[0, line.astype(np.int8), 0]
    edges = np.diff(padded)
    return list(zip(np.nonzero(edges == 1)[0], np.nonzero(edges == -1)[0] - 1))


def raster_levels(ink: np.ndarray, x_of_column, z_of_row, pixel_m: float) -> list[Level]:
    """Horizontal drawn levels in a raster profile: ink runs at least MIN_LEVEL_LENGTH_M long."""
    length = max(3, int(round(MIN_LEVEL_LENGTH_M / pixel_m))) | 1  # odd: an even kernel shifts by one pixel
    long_runs = opening(ink, (1, length)) > 0
    levels = []
    for top, bottom in _row_clusters(long_runs):
        band = long_runs[top:bottom + 1].any(axis=0)
        intervals = [sorted([float(x_of_column(a)), float(x_of_column(b))]) for a, b in _runs(band)]
        z = float(z_of_row((top + bottom) / 2))
        levels.append(Level(z_m=round(z, 4), intervals=_merge(intervals, LEVEL_GAP_M),
                            entity_ids=[f'raster rows {top}-{bottom}']))
    return sorted(levels, key=lambda level: level.z_m)


def raster_transverse_walls(ink: np.ndarray, x_of_column, x_range, min_length_m: float,
                            pixel_m: float) -> list[dict]:
    """Ink runs across the ship (constant x) at least min_length_m long, in a raster plan."""
    length = max(3, int(round(min_length_m / pixel_m))) | 1  # odd: an even kernel shifts by one pixel
    long_runs = opening(ink, (length, 1)) > 0
    walls = []
    for left, right in _row_clusters(long_runs.T):
        x = float(x_of_column((left + right) / 2))
        if x_range[0] - LEVEL_GAP_M <= x <= x_range[1] + LEVEL_GAP_M:
            run = max(b - a + 1 for column in long_runs.T[left:right + 1] for a, b in _runs(column) or [(0, -1)])
            walls.append({'x_m': round(x, 4), 'length_m': round(run * pixel_m, 4),
                          'entity_id': f'raster columns {left}-{right}'})
    return sorted(walls, key=lambda wall: wall['x_m'])


class PlanRaster:
    """Plan-view linework on a grid; the enclosed region is what the lines surround."""

    @classmethod
    def from_ink(cls, ink: np.ndarray, x_min: float, y_max: float, pixel_m: float, evidence: str) -> PlanRaster:
        """A plan from a scanned or rendered drawing: ink pixels are the lines."""
        plan = cls.__new__(cls)
        plan.view, plan.pixel_m, plan.x_min, plan.y_max = None, pixel_m, x_min, y_max
        plan.lines = (ink > 0).astype(np.uint8) * 255
        plan.entity_ids = [evidence]
        return plan

    def __init__(self, entities, view: View, pixel_m: float = PLAN_PIXEL_M):
        import cv2

        self.view, self.pixel_m = view, pixel_m
        x0, y0, x1, y1 = view.bounds
        corner_low = view.to_ship([[x0, y0]])[0]
        corner_high = view.to_ship([[x1, y1]])[0]
        self.x_min, self.y_max = float(corner_low[0]), float(corner_high[1])
        width = int(np.ceil((corner_high[0] - corner_low[0]) / pixel_m)) + 1
        height = int(np.ceil((corner_high[1] - corner_low[1]) / pixel_m)) + 1
        self.lines = np.zeros((height, width), np.uint8)
        self.entity_ids = []
        for entity in _view_entities(entities, view):
            pixels = self.to_pixels(view.to_ship(entity['points']))
            cv2.polylines(self.lines, [pixels], False, 255, PLAN_LINE_PIXELS)
            self.entity_ids.append(entity['id'])

    def to_pixels(self, ship_points) -> np.ndarray:
        p = np.asarray(ship_points, dtype=float)
        columns = (p[:, 0] - self.x_min) / self.pixel_m
        rows = (self.y_max - p[:, 1]) / self.pixel_m
        return np.round(np.c_[columns, rows]).astype(np.int32)

    def to_ship(self, pixels) -> np.ndarray:
        p = np.asarray(pixels, dtype=float)
        return np.c_[self.x_min + p[:, 0] * self.pixel_m, self.y_max - p[:, 1] * self.pixel_m]

    def _enclosed(self, lines: np.ndarray) -> np.ndarray:
        """Pixels that cannot be reached from the view border without crossing a line."""
        from scipy import ndimage

        free = lines == 0
        labels, _ = ndimage.label(free)
        border = np.unique(np.r_[labels[0], labels[-1], labels[:, 0], labels[:, -1]])
        outside = np.isin(labels, border[border > 0])
        return ~outside

    def region(self, mode: str = 'outer', peel: int = 1) -> np.ndarray:
        """``outer``: all enclosed area. ``inner``: area enclosed by inner walls only.

        ``inner`` removes the line that touches the outside (the deck edge),
        ``peel`` times, and keeps what the remaining lines still enclose, for
        example a deckhouse that stands inside the deck edge and its coaming.
        """
        from scipy import ndimage

        enclosed = self._enclosed(self.lines)
        if mode == 'outer':
            return enclosed
        if mode != 'inner':
            raise ValueError('footprint mode must be outer or inner')
        lines = self.lines.copy()
        outside = ~self._enclosed(lines)
        for _ in range(peel):
            # Remove the line pixels next to the outside; inner walls that meet the edge stay.
            edge_band = ndimage.binary_dilation(outside, iterations=EDGE_BAND_PIXELS)
            lines[edge_band & (lines > 0)] = 0
            outside = ~self._enclosed(lines)
        return ~outside

    def footprint(self, x_range: list[float], mode: str = 'outer', peel: int = 1) -> list[list[float]] | None:
        """Largest enclosed part inside the x range, as a simple polygon (metres)."""
        import cv2
        from scipy import ndimage

        mask = self.region(mode, peel)
        columns = self.x_min + np.arange(mask.shape[1]) * self.pixel_m
        mask = mask & ((columns >= x_range[0]) & (columns <= x_range[1]))[None, :]
        labels, count = ndimage.label(mask)
        if count == 0:
            return None
        sizes = ndimage.sum(mask, labels, index=np.arange(1, count + 1))
        largest = ndimage.binary_fill_holes(labels == (int(np.argmax(sizes)) + 1))
        if largest.sum() * self.pixel_m ** 2 < 1.0:
            return None  # Less than 1 m2 is a detail, not a deck or a deckhouse.
        # One-pixel spurs and necks (common on raster ink) make self-touching outlines: when
        # the outline is not simple, try coarser outlines, then the mask without spurs.
        for shape in (largest, ndimage.binary_opening(largest, iterations=2)):
            contours, _ = cv2.findContours(shape.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            if not contours:
                continue
            contour = max(contours, key=cv2.contourArea)
            tolerance = OUTLINE_TOLERANCE_M
            for _ in range(OUTLINE_SIMPLIFY_STEPS):
                simple = cv2.approxPolyDP(contour, tolerance / self.pixel_m, True)[:, 0, :]
                points = [[round(float(x), 4), round(float(y), 4)] for x, y in self.to_ship(simple)]
                if len(points) >= 3 and is_simple_polygon(points):
                    return points
                tolerance *= 2
        return None


def is_simple_polygon(points) -> bool:
    """True when no two non-adjacent edges touch or cross and no vertex repeats."""
    p = np.asarray(points, dtype=float)
    n = len(p)
    if n < 3 or len({(round(x, 6), round(y, 6)) for x, y in p}) != n or polygon_area(p) <= 0:
        return False

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    def touches(a, b, c, d):
        d1, d2, d3, d4 = cross(c, d, a), cross(c, d, b), cross(a, b, c), cross(a, b, d)
        if ((d1 > 0) != (d2 > 0)) and ((d3 > 0) != (d4 > 0)) and 0 not in (d1, d2, d3, d4):
            return True
        def on(o, a, q):
            return (cross(o, a, q) == 0 and min(o[0], a[0]) <= q[0] <= max(o[0], a[0])
                    and min(o[1], a[1]) <= q[1] <= max(o[1], a[1]))
        return on(c, d, a) or on(c, d, b) or on(a, b, c) or on(a, b, d)

    for i in range(n):
        a, b = p[i], p[(i + 1) % n]
        for j in range(i + 2, n):
            if i == 0 and j == n - 1:
                continue  # Adjacent through the closing edge.
            if touches(a, b, p[j], p[(j + 1) % n]):
                return False
    return True


def polygon_area(points) -> float:
    p = np.asarray(points, dtype=float)
    return float(abs(np.dot(p[:, 0], np.roll(p[:, 1], -1)) - np.dot(p[:, 1], np.roll(p[:, 0], -1))) / 2)


def clip_x(points, x_range) -> list[list[float]] | None:
    """Clip a simple polygon to x_range (Sutherland-Hodgman on two vertical lines)."""
    def clip(polygon, keep, cross_x):
        result = []
        for i, current in enumerate(polygon):
            previous = polygon[i - 1]
            if keep(current):
                if not keep(previous):
                    result.append(_cross(previous, current, cross_x))
                result.append(current)
            elif keep(previous):
                result.append(_cross(previous, current, cross_x))
        return result

    def _cross(a, b, x):
        t = (x - a[0]) / (b[0] - a[0])
        return [x, a[1] + t * (b[1] - a[1])]

    polygon = [list(map(float, p)) for p in points]
    polygon = clip(polygon, lambda p: p[0] >= x_range[0], x_range[0])
    if polygon:
        polygon = clip(polygon, lambda p: p[0] <= x_range[1], x_range[1])
    if len(polygon) < 3 or polygon_area(polygon) <= 0:
        return None
    return [[round(x, 4), round(y, 4)] for x, y in polygon]


def box_outline(x_range, half_breadth) -> list[list[float]]:
    a, b = x_range
    return [[a, -half_breadth], [b, -half_breadth], [b, half_breadth], [a, half_breadth]]


def y_extent(points) -> float:
    return float(np.max(np.abs(np.asarray(points, dtype=float)[:, 1])))


# Midship section deck lines: a deck line starts at most this far (drawing units) left of its
# label's insert point, or this far to the right (the label sits beside the section).
DECK_LABEL_REACH_UNITS = (500.0, 3000.0)
# A deck line lies within this many label heights of its label, and is at least this long.
DECK_LABEL_BAND_HEIGHTS = 3.0
DECK_LINE_MIN_UNITS = 1500.0
# A deck line rises at most this much per unit length (a camber is about B/50 over B/2: 0.04).
DECK_LINE_MAX_SLOPE = 0.1


def _segments_of(entity) -> list[tuple[tuple[float, float], tuple[float, float]]]:
    if entity.dxftype() == 'LINE':
        return [((entity.dxf.start.x, entity.dxf.start.y), (entity.dxf.end.x, entity.dxf.end.y))]
    if entity.dxftype() == 'LWPOLYLINE':
        points = [(p[0], p[1]) for p in entity.get_points()]
        return list(zip(points[:-1], points[1:]))
    return []


def section_deck_camber(path, label: str = '1-DECK', layers=('S0CO5',), metres_per_unit: float = 0.001) -> dict | None:
    """Deck camber from the deck lines that a midship-section drawing labels (None: no line).

    For each printed deck label, the longest moulded deck line beside it; its camber is the rise
    of its highest point above its lowest end (0 for a straight level line). Blocks are exploded
    first (section drawings keep their views in blocks). The result is the median over sections.
    """
    import ezdxf
    from ezdxf.disassemble import recursive_decompose

    entities = list(recursive_decompose(ezdxf.readfile(str(path)).modelspace()))
    labels = []
    for entity in entities:
        if entity.dxftype() in ('TEXT', 'MTEXT'):
            text = entity.dxf.text if entity.dxftype() == 'TEXT' else entity.plain_text()
            if text.strip() == label:
                labels.append((entity.dxf.insert.x, entity.dxf.insert.y, entity.dxf.get('height', 100.0) or 100.0))
    lines = [(entity, _segments_of(entity)) for entity in entities
             if entity.dxf.layer in layers and _segments_of(entity)]
    rises, entity_ids = [], []
    for x, y, height in labels:
        candidates = []
        for entity, segments in lines:
            points = np.array([p for segment in segments for p in segment])
            span = points[:, 0].max() - points[:, 0].min()
            rise = points[:, 1].max() - points[:, 1].min()
            near_y = np.abs(points[:, 1] - y).min() <= DECK_LABEL_BAND_HEIGHTS * height
            beside = x - DECK_LABEL_REACH_UNITS[0] <= points[:, 0].min() <= x + DECK_LABEL_REACH_UNITS[1]
            if span >= DECK_LINE_MIN_UNITS and rise <= DECK_LINE_MAX_SLOPE * span and near_y and beside:
                # Exploded block entities have no handle of their own.
                candidates.append((span, rise, entity.dxf.handle or f'block-line-{points[0][0]:.0f}-{points[0][1]:.0f}'))
        if candidates:
            _, rise, handle = max(candidates)
            rises.append(float(rise) * metres_per_unit)
            entity_ids.append(handle)
    if not rises:
        return None
    return {'camber_m': round(float(np.median(rises)), 4), 'sections': len(rises), 'entity_ids': entity_ids,
            'rises_m': [round(r, 4) for r in rises]}


# Profile end contours: a drawn end line continues where a segment starts within this distance
# of the current point (line ends meet to round-off; curves are flattened at 1 drawing unit).
END_CONTOUR_TOLERANCE_M = 0.03
# An end wall leans at most this far in x from the roof end (a raked front about 1.5:1 over a
# 2.4 m tier is 1.6 m); further, the walk has left the end wall.
END_CONTOUR_MAX_RUN_M = 3.0
# Contour points that a straight line between their neighbours covers within this are dropped.
END_CONTOUR_SIMPLIFY_M = 0.02
# Profile windows: closed outlines inside a tier, between these sizes (doors are taller).
WINDOW_SIZE_M = (0.25, 2.5)
WINDOW_MAX_HEIGHT_M = 1.5


def _profile_segments(entities, view: View):
    segments = []
    for entity in _view_entities(entities, view):
        points = view.to_ship(entity['points'])
        segments += [(a, b, entity['id']) for a, b in zip(points[:-1], points[1:])]
    return segments


def _simplify(points: np.ndarray, tolerance: float) -> np.ndarray:
    """Douglas-Peucker simplification of a polyline."""
    if len(points) <= 2:
        return points
    start, end = points[0], points[-1]
    direction = end - start
    length = np.hypot(*direction) or 1.0
    distance = np.abs(direction[0] * (points[:, 1] - start[1]) - direction[1] * (points[:, 0] - start[0])) / length
    index = int(np.argmax(distance))
    if distance[index] <= tolerance:
        return np.array([start, end])
    left = _simplify(points[:index + 1], tolerance)
    return np.concatenate([left[:-1], _simplify(points[index:], tolerance)])


def end_contour(entities, view: View, start_x: float, z_high: float, z_low: float) -> dict | None:
    """The drawn end line of a deckhouse tier in the profile, from its roof end down to its base.

    Starting at the roof end (start_x, z_high), the walk follows drawn segments that go down
    (a raked front, a curved front, the two faces of a raked wheelhouse front) until it reaches
    the base. Returns ``{'points': [[z, x], ...] (z up), 'reached_base', 'entity_ids'}``; None
    when no drawn line starts at the roof end. Where the line stops above the base, the wall is
    continued vertically down (``reached_base`` False).
    """
    segments = _profile_segments(entities, view)
    current = np.array([start_x, z_high])
    path, ids = [current.copy()], []
    while current[1] > z_low + END_CONTOUR_TOLERANCE_M:
        best = None
        for a, b, entity_id in segments:
            for here, there in ((a, b), (b, a)):
                if (np.hypot(*(here - current)) <= END_CONTOUR_TOLERANCE_M and there[1] < current[1] - 1e-3
                        and there[1] >= z_low - END_CONTOUR_TOLERANCE_M
                        and abs(there[0] - start_x) <= END_CONTOUR_MAX_RUN_M
                        and (best is None or there[1] < best[0][1])):
                    best = (there, entity_id)
        if best is None:
            break
        current = best[0].copy()
        path.append(current)
        if best[1] not in ids:
            ids.append(best[1])
    if len(path) == 1:
        return None
    reached = current[1] <= z_low + END_CONTOUR_TOLERANCE_M
    path[-1] = np.array([current[0], z_low]) if reached else current
    if not reached:
        path.append(np.array([current[0], z_low]))
    points = _simplify(np.array(path), END_CONTOUR_SIMPLIFY_M)
    return {'points': [[round(float(z), 4), round(float(x), 4)] for x, z in points[::-1]],
            'reached_base': bool(reached), 'entity_ids': ids}


def profile_windows(entities, view: View, x_range, z_range) -> list[dict]:
    """Window outlines drawn in the profile inside a tier: closed, window sized, not nested."""
    found = []
    for entity in _view_entities(entities, view):
        if not entity.get('closed'):
            continue
        points = view.to_ship(entity['points'])
        low, high = points.min(axis=0), points.max(axis=0)
        width, height = high - low
        if (x_range[0] <= low[0] and high[0] <= x_range[1] and z_range[0] <= low[1] and high[1] <= z_range[1]
                and WINDOW_SIZE_M[0] <= width <= WINDOW_SIZE_M[1]
                and WINDOW_SIZE_M[0] <= height <= WINDOW_MAX_HEIGHT_M):
            found.append({'x_m': [round(float(low[0]), 3), round(float(high[0]), 3)],
                          'z_m': [round(float(low[1]), 3), round(float(high[1]), 3)], 'entity_id': entity['id']})

    def inside(a, b):
        return (a is not b and b['x_m'][0] <= a['x_m'][0] and a['x_m'][1] <= b['x_m'][1]
                and b['z_m'][0] <= a['z_m'][0] and a['z_m'][1] <= b['z_m'][1])

    # A window frame is drawn as two nested outlines; keep the outer one.
    return sorted([w for w in found if not any(inside(w, other) for other in found)], key=lambda w: w['x_m'])
