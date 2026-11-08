"""Deterministic general-arrangement (GA) reader for the whole-vessel envelope.

Plan: docs/plans/2026-11-09-whole-vessel-scope.md, step 1.

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
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

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
# Outline simplification tolerance (a fraction of a deckhouse wall thickness).
OUTLINE_TOLERANCE_M = 0.02


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


class PlanRaster:
    """Plan-view linework on a grid; the enclosed region is what the lines surround."""

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
        contours, _ = cv2.findContours(largest.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        contour = max(contours, key=cv2.contourArea)
        simple = cv2.approxPolyDP(contour, OUTLINE_TOLERANCE_M / self.pixel_m, True)[:, 0, :]
        if len(simple) < 3:
            return None
        points = self.to_ship(simple)
        return [[round(float(x), 4), round(float(y), 4)] for x, y in points]


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
