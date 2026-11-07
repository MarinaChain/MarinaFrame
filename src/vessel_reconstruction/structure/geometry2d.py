"""Small plane-geometry helpers for strokes in drawing millimetres."""
from __future__ import annotations

from collections import defaultdict
import math

from .model import Point, Stroke

# Grid cell for the spatial index. Most strokes in a section are a few
# millimetres long, so a 10 mm cell keeps each query to a few candidates.
GRID_CELL_MM = 10.0


def point_segment_distance(p: Point, a: Point, b: Point) -> float:
    ax, az = a
    dx, dz = b[0] - ax, b[1] - az
    length_sq = dx * dx + dz * dz
    if length_sq == 0:
        return math.dist(p, a)
    t = max(0.0, min(1.0, ((p[0] - ax) * dx + (p[1] - az) * dz) / length_sq))
    return math.dist(p, (ax + t * dx, az + t * dz))


def point_stroke_distance(p: Point, stroke: Stroke) -> float:
    return min(point_segment_distance(p, a, b) for a, b in zip(stroke.points, stroke.points[1:]))


def _segments_cross(a: Point, b: Point, c: Point, d: Point) -> bool:
    def orient(p, q, r):
        return (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])
    o1, o2, o3, o4 = orient(a, b, c), orient(a, b, d), orient(c, d, a), orient(c, d, b)
    return o1 * o2 < 0 and o3 * o4 < 0


def stroke_distance(s: Stroke, t: Stroke) -> float:
    best = math.inf
    for a, b in zip(s.points, s.points[1:]):
        for c, d in zip(t.points, t.points[1:]):
            if _segments_cross(a, b, c, d):
                return 0.0
            best = min(best, point_segment_distance(a, c, d), point_segment_distance(b, c, d),
                       point_segment_distance(c, a, b), point_segment_distance(d, a, b))
    return best


def is_straight(stroke: Stroke, tolerance: float) -> bool:
    a, b = stroke.start, stroke.end
    if math.dist(a, b) <= tolerance:
        return False
    return all(point_segment_distance(p, a, b) <= tolerance for p in stroke.points)


def direction_deg(stroke: Stroke) -> float:
    """Direction of the chord, 0 to 180 degrees (0 = horizontal)."""
    (x0, z0), (x1, z1) = stroke.start, stroke.end
    return math.degrees(math.atan2(z1 - z0, x1 - x0)) % 180.0


def angle_between_deg(a: float, b: float) -> float:
    difference = abs(a - b) % 180.0
    return min(difference, 180.0 - difference)


def orientation(stroke: Stroke, tolerance_deg: float = 2.0) -> str:
    angle = direction_deg(stroke)
    if angle_between_deg(angle, 0.0) <= tolerance_deg:
        return "horizontal"
    if angle_between_deg(angle, 90.0) <= tolerance_deg:
        return "vertical"
    return "inclined"


class StrokeIndex:
    """Grid index of stroke boxes for neighbourhood queries."""

    def __init__(self, strokes, margin: float):
        self.strokes = list(strokes)
        self.margin = margin
        self.cells: dict[tuple[int, int], list[int]] = defaultdict(list)
        for position, stroke in enumerate(self.strokes):
            for cell in self._cells(stroke.bbox, margin):
                self.cells[cell].append(position)

    @staticmethod
    def _cells(bbox, margin):
        x0, z0, x1, z1 = bbox
        for i in range(math.floor((x0 - margin) / GRID_CELL_MM), math.floor((x1 + margin) / GRID_CELL_MM) + 1):
            for j in range(math.floor((z0 - margin) / GRID_CELL_MM), math.floor((z1 + margin) / GRID_CELL_MM) + 1):
                yield i, j

    def near_point(self, p: Point) -> list[Stroke]:
        cell = (math.floor(p[0] / GRID_CELL_MM), math.floor(p[1] / GRID_CELL_MM))
        return [self.strokes[i] for i in sorted(set(self.cells.get(cell, [])))]

    def near_stroke(self, stroke: Stroke) -> list[Stroke]:
        found = set()
        for cell in self._cells(stroke.bbox, self.margin):
            found.update(self.cells.get(cell, []))
        return [self.strokes[i] for i in sorted(found) if self.strokes[i].index != stroke.index]
