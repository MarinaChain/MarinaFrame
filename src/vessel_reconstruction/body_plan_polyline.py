"""Body-plan reader for hard-chine (V-bottom) hulls: each station traced along its own ink.

The crossing reader (`body_plan_reader`) measures station curves where they cross horizontal
rows. On a low-deadrise V-bottom the bottom lines run nearly horizontal: they barely cross the
rows and are dismissed as shallow strokes, so the bottom and the chine knuckle are not read.
This module reads each station as a polyline instead:

    sheer -> side -> chine knuckle -> bottom -> rabbet

1. Seeds: on each measuring row of the half, narrow ink runs whose line is steep (a station side).
2. Side: from each seed the line is followed along its own ink, up to its top end (the sheer
   end) and down to its lower end. Lines that cross it are passed straight through.
3. Bottom: at the lower end of the side the line turns. Every ink branch that leaves the end
   inward (toward the centreline) is followed; the bottom is the branch that descends, all the
   way, toward the centreline. A branch that rises (the drawn chine curve between knuckles) is
   not a bottom.
4. Knuckle: the corner of the traced polyline, where its turn is sharp: the same turn is seen
   with short and with long arms. A smooth round bilge turns gradually and gives no knuckle.
5. Names: the traced stations are ranked by nesting (outermost first) and take the host
   calibration's station order. The knuckles of a half must form one smooth chine curve:
   moving inward, each knuckle is nearer the centreline than the one outside it; a station
   whose knuckle breaks that order is not named.

A half is read only when enough stations have a knuckle; otherwise it is declined (round bilge,
or ink too ambiguous) and the caller keeps the existing reader. Truth, vessel names and
benchmark constants are never read. The frozen modules are not edited.

Coordinates are image pixels (row, column). Half-breadths are metres from the centre column;
heights stay in image rows, because the base line and its slope are the host's calibration.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from vessel_reconstruction import body_plan_reader as bpr

# ---------------------------------------------------------------- tracing constants
# Step along the line, pixels.
STEP_PX = 2.0
# The perpendicular search for the line's ink reaches this many line widths each way.
SEARCH_WIDTHS = 3.0
# The ink run nearest the predicted point is the line if it is within this many line widths
# (and at least MIN_TOLERANCE_PX) of the prediction.
TOLERANCE_WIDTHS = 0.6
MIN_TOLERANCE_PX = 2.0
# A run longer than this many line widths is another line crossing or merging: the trace keeps
# its own prediction inside it.
WIDE_RUN_WIDTHS = 1.8
# The direction is the principal axis of the real ink points in the last this many line widths.
DIRECTION_WINDOW_WIDTHS = 8.0
# A trace ends after this many line widths without ink.
MAX_GAP_WIDTHS = 2.5
# Ink runs separated by gaps up to this many pixels are one run (scans break lines into specks).
RUN_JOIN_GAP_PX = 2
# A trace stops after this many pixels (a guard; body-plan station lines are much shorter).
MAX_TRACE_PX = 6000.0

# ---------------------------------------------------------------- seeds
# A seed is a run no wider than this many line widths whose line is steeper than SEED_MAX_SLOPE
# columns per row (a station side, not a bottom, rail or waterline).
SEED_MAX_RUN_WIDTHS = 2.5
SEED_MAX_SLOPE = 1.0
# Rows above and below the seed row used to measure its slope.
SEED_SLOPE_ROWS = 8
# Runs this close to the centre column (line widths) are the centreline or keel, not stations.
CENTRE_CLEAR_WIDTHS = 4.0

# ---------------------------------------------------------------- bottom branches
# Branch directions tried at the lower end of a side, degrees from the inward horizontal,
# positive downward. A bottom leaves the knuckle inward; the drawn chine curve may leave it
# inward too, but rising.
BRANCH_ANGLES_DEG = np.arange(-60.0, 80.1, 2.0)
# The branch must start on ink: its first this many line widths are inked.
BRANCH_START_WIDTHS = 2.0
# A branch starts from points within this many line widths of the side's lower end.
BRANCH_REACH_WIDTHS = 3.0
# A bottom descends: over its length its rows increase by at least this share of its length
# (sin of about 1 degree). It is long: at least this share of the knuckle's half-breadth.
BOTTOM_MIN_DESCENT_SHARE = 0.02
BOTTOM_MIN_LENGTH_SHARE = 0.5
# ... and at least this many line widths long (a keel or stem outline near the centreline is not).
MIN_BOTTOM_WIDTHS = 15.0

# ---------------------------------------------------------------- knuckle
# Turn is measured with arms of KNUCKLE_ARM_WIDTHS line widths, skipping KNUCKLE_SKIP_WIDTHS at
# the corner (where crossing lines thicken the ink).
KNUCKLE_ARM_WIDTHS = 10.0
KNUCKLE_SKIP_WIDTHS = 2.0
# A knuckle turns by at least this many degrees ...
KNUCKLE_MIN_TURN_DEG = 25.0
# ... and is sharp: with half-length arms the turn is at least this share of the full turn (a
# round bilge turns gradually: with half-length arms it turns about half as much).
KNUCKLE_SHARPNESS = 0.75
# The fitted corner lies within this many line widths of the traced ink.
KNUCKLE_REACH_WIDTHS = 2.0

# ---------------------------------------------------------------- stations of a half
# The side above the knuckle is at least this many line widths long.
MIN_SIDE_WIDTHS = 15.0
# The bottom reaches in to at most this share of the knuckle's half-breadth.
BOTTOM_INNER_SHARE = 0.35
# A half is read only when at least this many stations, and this share of the calibration's
# stations, have a knuckle.
MIN_STATIONS = 3
MIN_STATION_SHARE = 0.5
# Two traces within this many line widths of each other over most of their side are one line.
SAME_LINE_WIDTHS = 1.5


# Trace point states.
NO_INK, IN_CROSSING, ON_INK = 0, 1, 2


@dataclass
class Trace:
    """Points followed along one ink line, and how each was seen."""

    points: np.ndarray  # (n, 2) row, column
    states: np.ndarray  # (n,) NO_INK (coasted), IN_CROSSING (inside a wide run) or ON_INK


@dataclass
class StationPolyline:
    """One station of one half, from the rabbet (low, inner end) up to the sheer (top end)."""

    side: str
    sign: int
    points: np.ndarray  # (n, 2) row, column; rows strictly decrease from the rabbet to the sheer
    knuckle_index: int  # index of the chine knuckle in `points`
    chine: tuple[float, float]  # (row, column) of the knuckle: intersection of the side and bottom fits
    turn_deg: float
    station: int | None = None
    notes: list = field(default_factory=list)

    @property
    def rabbet(self) -> tuple[float, float]:
        return float(self.points[0, 0]), float(self.points[0, 1])

    @property
    def sheer(self) -> tuple[float, float]:
        """The top end of the traced side (the drawing's line may run on into a rail above the deck)."""
        return float(self.points[-1, 0]), float(self.points[-1, 1])

    def offset_px(self, column: float, centre_column: float) -> float:
        return self.sign * (column - centre_column)

    def column_at_row(self, row: float) -> float | None:
        """Column where the polyline crosses image row `row`; None outside it."""
        rows, columns = self.points[:, 0], self.points[:, 1]
        if not rows.min() <= row <= rows.max():
            return None
        # Rows strictly decrease along the polyline, so it crosses a row once.
        return float(np.interp(row, rows[::-1], columns[::-1]))

    def half_breadth_m(self, row: float, sheet: bpr.SheetLayout) -> float | None:
        """Half-breadth (m) at image row `row`, or None where the station is not traced."""
        column = self.column_at_row(row)
        if column is None:
            return None
        return self.offset_px(column, sheet.centre_column) / sheet.pixels_per_metre

    def yz_m(self, sheet: bpr.SheetLayout, height_m) -> np.ndarray:
        """(half-breadth, height) in metres for every point; `height_m(row, column)` is the host's."""
        return np.array([[self.offset_px(c, sheet.centre_column) / sheet.pixels_per_metre, height_m(r, c)]
                         for r, c in self.points])


@dataclass
class HalfReading:
    """The stations of one half, or the reason the half was declined."""

    side: str
    read: bool
    stations: list[StationPolyline] = field(default_factory=list)  # named stations, outermost first
    unnamed: list[StationPolyline] = field(default_factory=list)  # traced with a knuckle, not named
    line_width_px: float = 0.0
    notes: list = field(default_factory=list)

    def station(self, number: int) -> StationPolyline | None:
        return next((s for s in self.stations if s.station == number), None)


# ---------------------------------------------------------------- ink tracing

def _unit(vector) -> np.ndarray:
    vector = np.asarray(vector, dtype=float)
    return vector / np.hypot(*vector)


def _joined_runs(values: np.ndarray) -> list[tuple[int, int]]:
    """Runs of True as (start, end + 1), joining runs split by gaps up to RUN_JOIN_GAP_PX."""
    padded = np.concatenate(([False], np.asarray(values, dtype=bool), [False]))
    edges = np.flatnonzero(np.diff(padded.astype(np.int8)))
    runs: list[list[int]] = []
    for start, end in zip(edges[::2], edges[1::2]):
        if runs and start - runs[-1][1] <= RUN_JOIN_GAP_PX:
            runs[-1][1] = int(end)
        else:
            runs.append([int(start), int(end)])
    return [(start, end) for start, end in runs]


def _perpendicular_runs(ink: np.ndarray, centre: np.ndarray, normal: np.ndarray,
                        reach: float) -> list[tuple[float, float]]:
    """Ink runs on the line `centre + t * normal`, |t| <= reach, as (first t, last t)."""
    t = np.arange(-np.floor(reach), np.floor(reach) + 1.0)
    rows = np.rint(centre[0] + t * normal[0]).astype(int)
    columns = np.rint(centre[1] + t * normal[1]).astype(int)
    inside = (rows >= 0) & (rows < ink.shape[0]) & (columns >= 0) & (columns < ink.shape[1])
    values = np.zeros(len(t), dtype=bool)
    values[inside] = ink[rows[inside], columns[inside]]
    return [(float(t[start]), float(t[end - 1])) for start, end in _joined_runs(values)]


def _direction(points: list, states: list, window_px: float, current: np.ndarray) -> np.ndarray:
    """Principal direction of the points seen on narrow ink in the last `window_px` of the trace."""
    chosen = []
    end = points[-1]
    for point, state in zip(reversed(points), reversed(states)):
        if np.hypot(*(point - end)) > window_px:
            break
        if state == ON_INK:
            chosen.append(point)
    if len(chosen) < 4:
        return current
    array = np.asarray(chosen)
    _, _, vt = np.linalg.svd(array - array.mean(axis=0), full_matrices=False)
    axis = vt[0]
    return axis if axis @ current >= 0 else -axis


def trace_line(ink: np.ndarray, start, direction, width: float, keep=None) -> Trace:
    """Follow one ink line from `start` along `direction` until its ink ends.

    `keep(row, column)` may stop the trace early (for example at the centreline). Where another
    line crosses or merges, the trace keeps its own straight prediction inside the wide run, and
    its direction is updated only from narrow runs. The trace ends at its last narrow-run point.
    """
    position = np.asarray(start, dtype=float)
    heading = _unit(direction)
    points, states = [position.copy()], [ON_INK]
    tolerance = max(MIN_TOLERANCE_PX, TOLERANCE_WIDTHS * width)
    reach = SEARCH_WIDTHS * width + 2.0
    window = DIRECTION_WINDOW_WIDTHS * width
    misses = 0
    for _ in range(int(MAX_TRACE_PX / STEP_PX)):
        predicted = position + STEP_PX * heading
        if not (0 <= predicted[0] < ink.shape[0] and 0 <= predicted[1] < ink.shape[1]):
            break
        if keep is not None and not keep(predicted[0], predicted[1]):
            break
        normal = np.array([-heading[1], heading[0]])
        runs = _perpendicular_runs(ink, predicted, normal, reach)
        distances = [0.0 if a <= 0.0 <= b else min(abs(a), abs(b)) for a, b in runs]
        nearest = int(np.argmin(distances)) if runs else -1
        if nearest >= 0 and distances[nearest] <= tolerance:
            first, last = runs[nearest]
            if last - first + 1.0 <= WIDE_RUN_WIDTHS * width:
                offset, state = 0.5 * (first + last), ON_INK
            else:  # another line crosses or merges here: keep the prediction within the run
                low, high = first + 0.5 * width, last - 0.5 * width
                offset = float(np.clip(0.0, low, high)) if low <= high else 0.5 * (first + last)
                state = IN_CROSSING
            position = predicted + offset * normal
            misses = 0
        else:
            position = predicted
            state = NO_INK
            misses += 1
            if misses * STEP_PX > MAX_GAP_WIDTHS * width:
                break
        points.append(position.copy())
        states.append(state)
        if state == ON_INK:
            heading = _direction(points, states, window, heading)
    last = max(i for i, state in enumerate(states) if state == ON_INK)
    return Trace(np.asarray(points[:last + 1]), np.asarray(states[:last + 1]))


# ---------------------------------------------------------------- seeds

def _row_runs(ink: np.ndarray, row: int, low: int, high: int) -> list[tuple[int, int]]:
    """Ink runs of one image row between `low` and `high` as (first column, last column + 1)."""
    return [(low + start, low + end) for start, end in _joined_runs(ink[row, low:high])]


def line_width(ink: np.ndarray, sheet: bpr.SheetLayout, side: bpr.SideLayout) -> float:
    """Typical horizontal width of the half's narrow ink runs on the measuring rows (pixels)."""
    low, high = _span(sheet, side)
    widths = []
    for row in sheet.waterline_rows.values():
        for row_offset in (-15, 15):  # beside the measuring row, off any drawn waterline
            r = int(row) + row_offset
            if 0 <= r < ink.shape[0]:
                widths += [end - start for start, end in _row_runs(ink, r, low, high) if end - start <= 40]
    return float(np.median(widths)) if widths else 4.0


def _span(sheet: bpr.SheetLayout, side: bpr.SideLayout) -> tuple[int, int]:
    edge = sheet.centre_column + side.sign * sheet.max_offset_px
    return int(min(sheet.centre_column, edge)), int(max(sheet.centre_column, edge)) + 1


def _run_centre(ink: np.ndarray, row: int, column: float, width: float) -> float | None:
    """Centre of the narrow run nearest `column` on `row`, within one width."""
    low = max(0, int(column - 3 * width) - 2)
    high = min(ink.shape[1], int(column + 3 * width) + 3)
    best = None
    for start, end in _row_runs(ink, row, low, high):
        if end - start > SEED_MAX_RUN_WIDTHS * width:
            continue
        centre = 0.5 * (start + end - 1)
        if abs(centre - column) <= width and (best is None or abs(centre - column) < abs(best - column)):
            best = centre
    return best


def seeds(ink: np.ndarray, sheet: bpr.SheetLayout, side: bpr.SideLayout, width: float) -> list[tuple[float, float]]:
    """Steep narrow runs on the measuring rows of one half: (row, column) seeds of station sides."""
    low, high = _span(sheet, side)
    found = []
    for nominal in sorted(sheet.waterline_rows.values()):
        for row_offset in (-int(2 * width) - 3, int(2 * width) + 3):  # off a drawn measuring line
            row = int(nominal) + row_offset
            if not SEED_SLOPE_ROWS <= row < ink.shape[0] - SEED_SLOPE_ROWS:
                continue
            for start, end in _row_runs(ink, row, low, high):
                if end - start > SEED_MAX_RUN_WIDTHS * width:
                    continue
                column = 0.5 * (start + end - 1)
                if abs(column - sheet.centre_column) < CENTRE_CLEAR_WIDTHS * width:
                    continue
                above = _run_centre(ink, row - SEED_SLOPE_ROWS, column, width)
                below = _run_centre(ink, row + SEED_SLOPE_ROWS, column, width)
                if above is None or below is None:
                    continue
                if abs(below - above) / (2 * SEED_SLOPE_ROWS) <= SEED_MAX_SLOPE:
                    found.append((float(row), column))
    return found


# ---------------------------------------------------------------- corners

def _arc(points: np.ndarray) -> np.ndarray:
    return np.concatenate(([0.0], np.cumsum(np.hypot(*np.diff(points, axis=0).T))))


def _fit_line(points: np.ndarray, toward: np.ndarray) -> tuple[np.ndarray, np.ndarray] | None:
    """(mean, unit axis) of a straight fit, the axis oriented along `toward`."""
    if len(points) < 3:
        return None
    mean = points.mean(axis=0)
    _, _, vt = np.linalg.svd(points - mean, full_matrices=False)
    axis = vt[0]
    return mean, (axis if axis @ toward >= 0 else -axis)


def _intersection(first: tuple, second: tuple) -> np.ndarray | None:
    (mean_a, axis_a), (mean_b, axis_b) = first, second
    matrix = np.column_stack([axis_a, -axis_b])
    if abs(np.linalg.det(matrix)) < 1e-6:
        return None
    s, _ = np.linalg.solve(matrix, mean_b - mean_a)
    return mean_a + s * axis_a


def _angle(first: np.ndarray, second: np.ndarray) -> float:
    return float(np.degrees(np.arccos(np.clip(first @ second, -1.0, 1.0))))


def turn_at(points: np.ndarray, arc: np.ndarray, index: int, arm: float, skip: float) -> float:
    """Turn (degrees) at `index` between straight fits of the points `skip`..`arm` before and after."""
    here = arc[index]
    before = points[(arc >= here - arm) & (arc <= here - skip)]
    after = points[(arc >= here + skip) & (arc <= here + arm)]
    if len(before) < 3 or len(after) < 3:
        return 0.0
    fit_before = _fit_line(before, before[-1] - before[0])
    fit_after = _fit_line(after, after[-1] - after[0])
    return _angle(fit_before[1], fit_after[1])


def is_sharp(points: np.ndarray, arc: np.ndarray, index: int, width: float) -> tuple[bool, float]:
    """(sharp knuckle?, turn degrees) at `index`: a large turn that short arms see as well."""
    arm, skip = KNUCKLE_ARM_WIDTHS * width, KNUCKLE_SKIP_WIDTHS * width
    turn = turn_at(points, arc, index, arm, skip)
    if turn < KNUCKLE_MIN_TURN_DEG:
        return False, turn
    short = turn_at(points, arc, index, 0.5 * (arm + skip), skip)
    return short >= KNUCKLE_SHARPNESS * turn, turn


def first_corner(points: np.ndarray, start: int, step: int, width: float) -> int | None:
    """Index of the first sharp corner from `start` in direction `step` (+1 or -1), or None.

    The corner is the largest turn within one arm length after the turn first exceeds the limit.
    """
    arc = _arc(points)
    arm = KNUCKLE_ARM_WIDTHS * width
    index = start
    while 0 <= index < len(points):
        sharp, _ = is_sharp(points, arc, index, width)
        if sharp:
            window = [i for i in range(index, index + step * len(points), step)
                      if 0 <= i < len(points) and abs(arc[i] - arc[index]) <= arm]
            turns = [turn_at(points, arc, i, arm, KNUCKLE_SKIP_WIDTHS * width) for i in window]
            return window[int(np.argmax(turns))]
        index += step
    return None


# ---------------------------------------------------------------- one station

def _distance_to(points: np.ndarray, point) -> float:
    return float(np.min(np.hypot(points[:, 0] - point[0], points[:, 1] - point[1])))


def _length(points: np.ndarray) -> float:
    return float(_arc(points)[-1]) if len(points) > 1 else 0.0


def _inward(sign: int, angle_deg: float) -> np.ndarray:
    """Direction pointing toward the centreline, `angle_deg` below the horizontal."""
    angle = np.radians(angle_deg)
    return np.array([np.sin(angle), -sign * np.cos(angle)])


def _bottom(ink: np.ndarray, side_points: np.ndarray, sheet: bpr.SheetLayout, sign: int,
            width: float) -> np.ndarray | None:
    """Points of the bottom leaving the lower end of a side (outer end first), or None.

    Every branch that leaves the end inward on ink is followed to its first corner. A bottom
    descends over its whole length and reaches in toward the centreline. Of those, the one that
    reaches nearest the centreline is the bottom, the longest if several reach equally far. A
    start further back up the side is tried only when no branch leaves from nearer its end (a
    branch from higher up can cut across to the bottom and miss the corner).
    """
    end = side_points[-1]
    knuckle_offset = sign * (end[1] - sheet.centre_column)
    centre = sheet.centre_column

    def keep(row, column):
        return sign * (column - centre) > 0.0

    start_steps = int(np.ceil(BRANCH_START_WIDTHS * width / STEP_PX))
    starts = [side_points[max(0, len(side_points) - 1 - int(back / STEP_PX))]
              for back in np.arange(0.0, BRANCH_REACH_WIDTHS * width + 0.1, width)]
    candidates = []
    for back, start in enumerate(starts):
        for angle in BRANCH_ANGLES_DEG:
            heading = _inward(sign, angle)
            trace = trace_line(ink, start, heading, width, keep)
            if len(trace.points) <= start_steps or (trace.states[1:start_steps + 1] == NO_INK).any():
                continue
            points = trace.points
            # The corner search starts one arm past the start, clear of the knuckle itself.
            clear = int(np.searchsorted(_arc(points), KNUCKLE_ARM_WIDTHS * width))
            corner = first_corner(points, clear, 1, width)
            if corner is not None:
                points = points[:corner + 1]
            length = _length(points)
            if length < max(BOTTOM_MIN_LENGTH_SHARE * knuckle_offset, MIN_BOTTOM_WIDTHS * width):
                continue
            if points[-1, 0] - points[0, 0] < BOTTOM_MIN_DESCENT_SHARE * length:
                continue
            if np.min(points[:, 0]) < points[0, 0] - width:  # rises above its start: not a bottom
                continue
            inner = sign * (points[-1, 1] - centre)
            candidates.append((back, round(inner / width), -length, points))
        if candidates:
            break
    if not candidates:
        return None
    return min(candidates, key=lambda c: c[:3])[3]


def _monotone(points: np.ndarray) -> np.ndarray:
    """Points from low to high with strictly decreasing rows (drops points that do not rise)."""
    kept = [points[0]]
    for point in points[1:]:
        if point[0] < kept[-1][0] - 0.25:
            kept.append(point)
    return np.asarray(kept)


def trace_station(ink: np.ndarray, seed, sheet: bpr.SheetLayout, side: bpr.SideLayout,
                  width: float) -> tuple[StationPolyline | None, np.ndarray, str]:
    """Trace the station whose side passes through `seed`.

    Returns (station or None, the traced side line for de-duplication, the reason when None).
    """
    seed = np.asarray(seed, dtype=float)
    up = trace_line(ink, seed, (-1.0, 0.0), width)
    down = trace_line(ink, seed, (1.0, 0.0), width)
    line = np.concatenate([up.points[::-1], down.points[1:]])  # top to bottom
    seed_index = len(up.points) - 1
    # The side is the straight-run of the line through the seed: cut at the first sharp corner
    # below it (the knuckle, where the trace ran on along the chine curve or the bottom) and
    # above it (where it ran on along a deck or rail line).
    lower = first_corner(line, seed_index, 1, width)
    upper = first_corner(line, seed_index, -1, width)
    side_points = line[(upper or 0):(lower + 1 if lower is not None else len(line))]
    if _length(side_points) < MIN_SIDE_WIDTHS * width:
        return None, line, 'short line'
    bottom = _bottom(ink, side_points, sheet, side.sign, width)
    if bottom is None:
        return None, line, 'no bottom branch'
    # Knuckle: where straight fits of the side's lower end and the bottom's outer end meet.
    arm, skip = KNUCKLE_ARM_WIDTHS * width, KNUCKLE_SKIP_WIDTHS * width
    start_index = int(np.argmin(np.hypot(*(side_points - bottom[0]).T)))
    side_points = side_points[:start_index + 1]
    joined = np.concatenate([side_points, bottom[1:]])
    arc = _arc(joined)
    sharp, turn = is_sharp(joined, arc, len(side_points) - 1, width)
    if not sharp:
        return None, line, 'no sharp knuckle'
    side_arc, bottom_arc = _arc(side_points), _arc(bottom)
    side_end = side_points[side_arc >= side_arc[-1] - arm]
    bottom_start = bottom[(bottom_arc >= skip) & (bottom_arc <= arm)]
    fits = (_fit_line(side_end, side_end[-1] - side_end[0]), _fit_line(bottom_start, bottom_start[-1] - bottom_start[0]))
    corner = None if None in fits else _intersection(*fits)
    if corner is None or _distance_to(joined, corner) > KNUCKLE_REACH_WIDTHS * width:
        return None, line, 'side and bottom do not meet at a corner'
    knuckle_offset = side.sign * (corner[1] - sheet.centre_column)
    inner_offset = side.sign * (bottom[-1, 1] - sheet.centre_column)
    if inner_offset > BOTTOM_INNER_SHARE * knuckle_offset:
        return None, line, 'bottom does not reach the centreline'
    # Low to high: the rabbet (the bottom's inner end) first; the knuckle is the fitted corner.
    low_to_high = np.concatenate([bottom[::-1][:-1], [corner], side_points[::-1][1:]])
    polyline = _monotone(low_to_high)
    knuckle_index = int(np.argmin(np.hypot(*(polyline - corner).T)))
    station = StationPolyline(side.name, side.sign, polyline, knuckle_index,
                              (float(corner[0]), float(corner[1])), turn)
    return station, line, ''


# ---------------------------------------------------------------- one half

def _same_line(first: np.ndarray, second: np.ndarray, width: float) -> bool:
    """Two side traces are one line when most of the shorter lies on the longer."""
    short, long_ = (first, second) if len(first) <= len(second) else (second, first)
    sample = short[:: max(1, len(short) // 40)]
    near = [_distance_to(long_, point) <= SAME_LINE_WIDTHS * width for point in sample]
    return float(np.mean(near)) > 0.5


def _nesting_key(station: StationPolyline, rows: list[float], sheet: bpr.SheetLayout) -> tuple:
    """Outermost first: half-breadth at the shared rows, then at the knuckle."""
    offsets = [station.offset_px(station.column_at_row(row), sheet.centre_column) for row in rows]
    return (-float(np.mean(offsets)) if offsets else 0.0,
            -station.offset_px(station.chine[1], sheet.centre_column))


def _chine_order_breaks(stations: list[StationPolyline], sheet: bpr.SheetLayout) -> list[int]:
    """Indices (outermost-first list) whose knuckle is not between its neighbours' half-breadths."""
    offsets = [s.offset_px(s.chine[1], sheet.centre_column) for s in stations]
    breaks = []
    for i, offset in enumerate(offsets):
        outer = offsets[i - 1] if i > 0 else np.inf
        inner = offsets[i + 1] if i + 1 < len(offsets) else -np.inf
        if not inner < offset < outer:
            breaks.append(i)
    return breaks


def read_half(ink: np.ndarray, sheet: bpr.SheetLayout, side: bpr.SideLayout) -> HalfReading:
    """Trace and name the stations of one half; declined when the half has no hard chine."""
    width = line_width(ink, sheet, side)
    result = HalfReading(side.name, False, line_width_px=width)
    traced_sides: list[np.ndarray] = []
    stations: list[StationPolyline] = []
    reasons: dict = {}
    for seed in seeds(ink, sheet, side, width):
        if any(_distance_to(points, seed) <= SAME_LINE_WIDTHS * width for points in traced_sides):
            continue
        station, side_points, reason = trace_station(ink, seed, sheet, side, width)
        traced_sides.append(side_points)
        if station is None:
            reasons[reason] = reasons.get(reason, 0) + 1
            continue
        if any(_same_line(station.points, other.points, width) for other in stations):
            continue
        stations.append(station)
    result.notes.append(f'traced {len(traced_sides)} lines; {len(stations)} with a knuckle; '
                        f'others: {dict(sorted(reasons.items()))}')
    expected = len(side.stations_outer_first)
    if len(stations) < max(MIN_STATIONS, MIN_STATION_SHARE * expected):
        result.unnamed = stations
        result.notes.append('declined: too few stations with a sharp knuckle (no hard chine read)')
        return result
    result.read = True
    # Nesting rows: rows that every station's side covers above its knuckle.
    top = max(float(s.points[s.knuckle_index:, 0].min()) for s in stations)
    bottom = min(float(s.chine[0]) for s in stations)
    rows = [row for row in sorted(sheet.waterline_rows.values()) if top < row < bottom]
    ordered = sorted(stations, key=lambda s: _nesting_key(s, rows, sheet))
    breaks = _chine_order_breaks(ordered, sheet)
    if breaks:
        result.notes.append(f'knuckles out of chine order at ranks {breaks}')
    if len(ordered) > expected:
        result.unnamed = ordered
        result.read = False
        result.notes.append(f'declined: {len(ordered)} stations traced for {expected} in the calibration')
        return result
    if len(ordered) < expected:
        # Names run from the outermost station, the widest and clearest line of the half. The
        # stations not traced are taken to be the innermost (the small sections at the stem or
        # transom, whose sides merge with the stem, keel or transom outline).
        missing = side.stations_outer_first[len(ordered):]
        result.notes.append(f'{len(ordered)} stations traced for {expected}; innermost {list(missing)} not read')
    for i, (station, number) in enumerate(zip(ordered, side.stations_outer_first)):
        if i in breaks:
            station.notes.append(f'traced at rank {i} (station {number}); knuckle breaks the chine order; not named')
            result.unnamed.append(station)
        else:
            station.station = number
            result.stations.append(station)
    return result


def read_sheet(ink: np.ndarray, sheet: bpr.SheetLayout) -> dict[str, HalfReading]:
    return {side.name: read_half(ink, sheet, side) for side in sheet.sides}


def waterline_table(halves: dict[str, HalfReading], sheet: bpr.SheetLayout) -> dict:
    """{(station, waterline): half-breadth m} at the sheet's waterline rows, read halves only."""
    table = {}
    for half in halves.values():
        if not half.read:
            continue
        for station in half.stations:
            for label, row in sheet.waterline_rows.items():
                value = station.half_breadth_m(row, sheet)
                if value is not None:
                    table[(station.station, label)] = value
    return table
