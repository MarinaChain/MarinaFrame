"""Find the drawn chine line of a hard-chine body plan and read each station's chine point from it.

On a hard-chine hull the draughtsman draws the chine as its own heavy, gently curved line across
the body plan. Each station curve changes direction where it meets that line. The station curves
themselves may stop short of the line, so joining their pieces to each other cannot work; the
line gives the chine position directly.

The module needs only the ink mask, the host calibration (SheetLayout/SideLayout) and the frozen
reader's measurement of that side. It reads no truth, vessel names or benchmark constants.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from vessel_reconstruction import body_plan_crossings as bpc
from vessel_reconstruction import body_plan_reader as bpr

# The chine is drawn heavier than a station curve: a flat stretch shows a vertical ink run of
# 1.5 to 2.0 curve widths. Station curves at a steep angle also give such runs, so these are only
# seeds; the tracer below discards anything that is not a long shallow line.
SEED_MIN_WIDTHS = 1.5
SEED_MAX_WIDTHS = 2.0
SEED_STEP_PX = 25
# A line run this many times thicker than the seed is another line crossing it (a station curve
# or a grid line); the trace passes it on its predicted course.
CROSSING_RUN_RATIO = 1.7
# The tracer predicts the next row from a straight line fitted over this many columns.
FIT_COLUMNS = 60
# Longest stretch (columns) the trace may coast without finding its own ink.
MAX_COAST_COLUMNS = 40
# The row prediction may be missed by this many pixels, plus a share of the local slope.
REACH_PX = 3.0
# A chine line spans at least this share of the half body plan's width.
MIN_SPAN_SHARE = 0.25
# A chine line is shallow: it never changes row by more than this share of its column span.
MAX_RISE_SHARE = 0.35
# A station curve ends on the line when one of its path ends is this many curve widths away.
TOUCH_WIDTHS = 2.5
# At least this many station curves must end on the line for it to be the chine.
MIN_TOUCHING_CHAINS = 3
# The stroke is continued this share of the half plan's width beyond each traced end.
EXTENSION_SHARE = 0.15
# Columns at each stroke end used to continue it, and path points used to continue a station curve.
FIT_END_COLUMNS = 150
FIT_END_POINTS = 100
# A station curve whose ink was lost is continued at most this many waterline spacings.
EXTRAPOLATION_SPACINGS = 1.5
# A measured crossing this close (px) to the stroke is on it, not on either side.
SIDE_MARGIN_PX = 12.0
# Meetings closer than this (px) along the line are one station point.
DISTINCT_POINT_PX = 3.0
# Stroke points closer than this to a known stroke are the same stroke (px).
DUPLICATE_PX = 6.0


@dataclass
class ChineLine:
    """The traced line as (row, column) points ordered by column."""

    points: np.ndarray
    touching_chains: int
    thickness_px: float

    def row_at(self, column: float) -> float | None:
        columns = self.points[:, 1]
        if column < columns[0] or column > columns[-1]:
            return None
        return float(np.interp(column, columns, self.points[:, 0]))


@dataclass
class StationChinePoint:
    """Where one station's curve pieces meet the chine line, in image pixels."""

    chain: int
    row: float
    column: float


def _runs(ink: np.ndarray, column: int, low: int, high: int) -> list[tuple[int, int]]:
    return [(a + low, b + low) for a, b in bpc.ink_runs(ink[low:high, column])]


def _trace(ink: np.ndarray, column: int, row: float, thickness: float, direction: int,
           limit: int) -> list[tuple[float, float]]:
    """Follow a shallow line column by column, passing lines that cross it."""
    points: list[tuple[float, float]] = [(row, float(column))]
    coasting = 0
    x = column
    while True:
        x += direction
        if not (0 <= x < ink.shape[1]) or abs(x - column) > limit:
            break
        recent = points[-FIT_COLUMNS:]
        if len(recent) >= 5 and np.ptp([p[1] for p in recent]) >= 3:
            slope, intercept = np.polyfit([p[1] for p in recent], [p[0] for p in recent], 1)
            predicted = slope * x + intercept
        else:
            slope, predicted = 0.0, points[-1][0]
        reach = REACH_PX + thickness / 2 + 2.0 * abs(slope)
        low, high = max(0, int(predicted - reach - 2 * thickness)), int(predicted + reach + 2 * thickness) + 1
        best = None
        for start, end in _runs(ink, x, low, high):
            distance = max(0.0, start - predicted, predicted - (end - 1))
            if distance <= reach and (best is None or distance < best[0]):
                best = (distance, start, end)
        if best is None:
            coasting += 1
        else:
            _, start, end = best
            if end - start > CROSSING_RUN_RATIO * thickness * np.sqrt(1 + slope ** 2) + 2:
                coasting += 1
            else:
                coasting = 0
                points.append(((start + end - 1) / 2, float(x)))
                continue
        if coasting > MAX_COAST_COLUMNS:
            break
        points.append((float(predicted), float(x)))
    while len(points) > 1 and coasting:  # drop the coasted tail: no ink supports it
        points.pop()
        coasting -= 1
    return points


def _near(points: np.ndarray, known: list[np.ndarray]) -> bool:
    for other in known:
        columns = other[:, 1]
        rows = np.interp(points[:, 1], columns, other[:, 0], left=np.nan, right=np.nan)
        close = np.abs(rows - points[:, 0]) <= DUPLICATE_PX
        if close.mean() > 0.5:
            return True
    return False


def candidate_strokes(ink: np.ndarray, sheet: bpr.SheetLayout, side: bpr.SideLayout,
                      curve_width: float) -> list[np.ndarray]:
    """Long shallow heavy strokes of this half body plan, as (row, column) points by column."""
    rows = sorted(sheet.waterline_rows.values())
    spacing = bpr.waterline_spacing(sheet)
    top, bottom = int(rows[0] - 2 * spacing), int(rows[-1] + 2 * spacing)
    centre = sheet.centre_column
    near, far = int(centre + side.sign * 10), int(centre + side.sign * sheet.max_offset_px)
    first, last = sorted((near, far))
    strokes: list[np.ndarray] = []
    for column in range(first, last, SEED_STEP_PX):
        for start, end in _runs(ink, column, max(top, 0), min(bottom, ink.shape[0])):
            length = end - start
            if not SEED_MIN_WIDTHS * curve_width <= length <= SEED_MAX_WIDTHS * curve_width:
                continue
            seed = np.array([[(start + end - 1) / 2, float(column)]])
            if _near(np.vstack([seed, seed + [0, 1]]), strokes):
                continue
            span = last - first
            both = _trace(ink, column, seed[0, 0], length, -1, span)[::-1]
            both += _trace(ink, column, seed[0, 0], length, 1, span)[1:]
            points = np.array(both)
            points = points[(points[:, 1] >= first) & (points[:, 1] <= last)]
            if len(points) < 2:
                continue
            width = np.ptp(points[:, 1])
            if width < MIN_SPAN_SHARE * sheet.max_offset_px:
                continue
            if np.ptp(points[:, 0]) > MAX_RISE_SHARE * width:
                continue
            strokes.append(points)
    return strokes


def _extended(stroke: np.ndarray, extension_px: float) -> np.ndarray:
    """The stroke with each end continued on its fitted line (the heavy line merges with other
    lines near the knuckles, where the trace coasts and stops)."""
    pieces = []
    for end, step in ((0, -1), (-1, 1)):
        part = stroke[:FIT_END_COLUMNS] if end == 0 else stroke[-FIT_END_COLUMNS:]
        slope, intercept = np.polyfit(part[:, 1], part[:, 0], 1)
        columns = stroke[end, 1] + step * np.arange(1, int(extension_px) + 1)
        pieces.append(np.column_stack([slope * columns + intercept, columns]))
    return np.vstack([pieces[0][::-1], stroke, pieces[1]])


@dataclass
class Meeting:
    """Where one station curve meets the stroke, and how much of the curve lies on each side."""

    chain: int
    row: float
    column: float
    nodes_above: int  # measured waterline crossings of the curve on the smaller-row side
    nodes_below: int
    extrapolated: bool  # the meeting lies beyond the traced ink


def _stroke_rows(stroke: np.ndarray, columns: np.ndarray) -> np.ndarray:
    return np.interp(columns, stroke[:, 1], stroke[:, 0], left=np.nan, right=np.nan)


def _meeting(stroke: np.ndarray, index: int, chain: bpr.Chain, reading: bpr.SideReading,
             reach_rows: float) -> Meeting | None:
    """Crossing of a curve's path with the stroke, or its continuation from the nearer end.

    A quadratic through the last FIT_END_POINTS path points continues a curve whose ink was lost
    (its line merges with others at the knuckle), for at most `reach_rows` rows.
    """
    path = np.asarray(chain.path, dtype=float)
    if len(path) < 2 * FIT_END_POINTS:
        return None
    offset = path[:, 0] - _stroke_rows(stroke, path[:, 1])
    valid = ~np.isnan(offset)
    if not valid.any():
        return None
    above = below = 0
    for waterline, node in chain.nodes.items():
        crossing = reading.stations[waterline][node]
        line = _stroke_rows(stroke, np.array([crossing.x_px]))[0]
        if not np.isnan(line):
            above += crossing.row < line - SIDE_MARGIN_PX
            below += crossing.row > line + SIDE_MARGIN_PX
    signs = np.sign(offset[valid])
    flips = np.nonzero(signs[:-1] * signs[1:] < 0)[0]
    if len(flips):
        k = np.nonzero(valid)[0][flips[0]]
        return Meeting(index, float(path[k, 0]), float(path[k, 1]), above, below, False)
    # No crossing: continue from the path end that lies nearer the stroke.
    ends = []
    for end in (path[:FIT_END_POINTS], path[::-1][:FIT_END_POINTS]):
        gap = abs(end[0, 0] - _stroke_rows(stroke, end[:1, 1])[0]) if valid.any() else np.nan
        ends.append((np.inf if np.isnan(gap) else gap, end))
    gap, end = min(ends, key=lambda item: item[0])
    if np.ptp(end[:, 0]) < 10:
        return None
    direction = np.sign(end[0, 0] - end[-1, 0])
    coefficients = np.polyfit(end[:, 0], end[:, 1], 2)
    start_side = np.sign(end[0, 0] - np.interp(end[0, 1], stroke[:, 1], stroke[:, 0]))
    for step in range(int(reach_rows)):
        row = end[0, 0] + direction * step
        column = float(np.polyval(coefficients, row))
        line = _stroke_rows(stroke, np.array([column]))[0]
        if not np.isnan(line) and (row - line) * start_side <= 0:
            return Meeting(index, float(line), column, above, below, True)
    return None


def station_meetings(stroke: np.ndarray, reading: bpr.SideReading, reach_rows: float) -> list[Meeting]:
    found = (_meeting(stroke, i, c, reading, reach_rows) for i, c in enumerate(reading.chains))
    return [m for m in found if m is not None]


def chine_score(meetings: list[Meeting]) -> int:
    """Station curves with measured waterline crossings above the stroke, and those below; the lesser.

    Curves reach the sheer only from below, and the keel or rabbet only from above, so only
    the chine has measured curve pieces on both sides.
    """
    reaches_above = sum(m.nodes_above > 0 for m in meetings)
    reaches_below = sum(m.nodes_below > 0 for m in meetings)
    return min(reaches_above, reaches_below)


def _roughness(stroke: np.ndarray) -> float:
    """RMS departure from a smooth (quadratic) line: a trace that jumped lines has more."""
    fit = np.polyval(np.polyfit(stroke[:, 1], stroke[:, 0], 2), stroke[:, 1])
    return float(np.sqrt(np.mean((stroke[:, 0] - fit) ** 2)))


def find_chine_line(ink: np.ndarray, sheet: bpr.SheetLayout, reading: bpr.SideReading) -> ChineLine | None:
    """The traced stroke that most station curves meet from both sides, or None."""
    stations = [c for cs in reading.stations.values() for c in cs]
    if not stations:
        return None
    curve_width = bpc.typical_width(stations)
    spacing = bpr.waterline_spacing(sheet)
    best = None
    for stroke in candidate_strokes(ink, sheet, reading.layout, curve_width):
        extended = _extended(stroke, EXTENSION_SHARE * sheet.max_offset_px)
        score = chine_score(station_meetings(extended, reading, EXTRAPOLATION_SPACINGS * spacing))
        key = (score, -_roughness(stroke))
        if score >= MIN_TOUCHING_CHAINS and (best is None or key > best[0]):
            best = (key, extended)
    if best is None:
        return None
    return ChineLine(best[1], best[0][0], curve_width)


def station_chine_points(line: ChineLine, reading: bpr.SideReading, spacing: float) -> list[Meeting]:
    """Chine point of each station curve that reaches the line from above, outermost first.

    A curve that crosses the line, or ends on it, has its knuckle there. The pieces below the line
    carry the same station and are not counted twice.
    """
    meetings = station_meetings(line.points, reading, EXTRAPOLATION_SPACINGS * spacing)
    upper = sorted((m for m in meetings if m.nodes_above > 0),
                   key=lambda m: -reading.layout.sign * m.column)
    # Chains drawn on top of each other (or a station and its twin) meet at one point.
    distinct: list[Meeting] = []
    for meeting in upper:
        if not distinct or abs(meeting.column - distinct[-1].column) > DISTINCT_POINT_PX:
            distinct.append(meeting)
    return distinct
