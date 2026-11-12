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
   not a bottom. On a flat-bottom hull (a skiff) the bottom is drawn level to the centreline:
   when no branch descends, a level branch is the bottom.
4. Knuckle: the corner of the traced polyline, where its turn is sharp: the same turn is seen
   with short and with long arms. A smooth round bilge turns gradually and gives no knuckle.
5. Names: the traced stations are ranked by nesting (outermost first) and take the host
   calibration's station order. The knuckles of a half must form one smooth chine curve:
   moving inward, each knuckle is nearer the centreline than the one outside it; a station
   whose knuckle breaks that order is not named. Rank naming is only right when every drawn
   station outside a named one holds its rank, so a station is never left out of the order
   for its bottom alone: crowded stations run their bottoms into one line near the keel, and
   a station whose bottom is an outer station's keeps its side and knuckle. A traced side much
   shorter than the others (a transom or other outline with a corner) is not a station and
   takes no rank.

A half is read as a whole only when enough stations have a knuckle. Otherwise it is declined
as a whole, and engagement is per station (`engage_stations`): a traced station with a clear
knuckle takes the name that the existing reader gave the same curve, and its polyline replaces
that station's cells; every other station keeps the existing reader's cells, and a cell of
another station that lies on an engaged station's ink is dropped (no double cells). A round
bilge gives no clear knuckle, so its table is the existing reader's table unchanged. Truth,
vessel names and benchmark constants are never read. The frozen modules are not edited.

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

# ---------------------------------------------------------------- the top of a side (sheer)
# A station line ends on the drawn sheer line, whose top edge is the deck top at the side. When the
# trace up a side stops inside the line it meets, the side's top end is carried on along its
# direction to the far edge of that line's ink, at most END_INTO_LINE_WIDTHS line widths (a sheer
# line is drawn up to about three widths heavy; a line met at a grazing angle is not followed).
END_INTO_LINE_WIDTHS = 3.0
# A side whose top runs on along a calibrated grid column for this many line widths is cut where it
# joins the column.
GRID_RUN_WIDTHS = 5.0
# Station lines are drawn with one pen. A top part of the side, at least THIN_RUN_WIDTHS line widths
# long, whose median ink width is under THIN_SHARE of the side's own median width (measured on its
# lower half) is a thinner line the trace ran on into (a label leader, a grid line): the side ends
# below it.
THIN_RUN_WIDTHS = 5.0
THIN_SHARE = 0.75

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
# A V-bottom descends: over its length its rows increase by at least this share of its length
# (sin of about 1 degree). It is long: at least this share of the knuckle's half-breadth.
BOTTOM_MIN_DESCENT_SHARE = 0.02
# A flat bottom (a skiff's) is drawn level from the knuckle to the centreline. A branch that neither
# descends by that share nor rises above its start, and ends within CENTRE_CLEAR_WIDTHS of the
# centre column, is a level bottom; it is taken only when no
# descending branch leaves the side, so a level line through a V-bottom knuckle is never preferred.
# The polyline keeps rows strictly decreasing: a level bottom is stored as the knuckle and its
# rabbet end, the rabbet put at least LEVEL_ROW_STEP_PX below the knuckle row (twice the 0.25 px
# rise `_monotone` needs to keep the knuckle; far below drawing precision).
LEVEL_ROW_STEP_PX = 0.5
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
# A line is a drawn grid line (a waterline or a buttock), not a station part, when more than
# GRID_SHARE of its points lie within GRID_BAND_WIDTHS line widths (plus 3 px) of one calibrated
# waterline row or grid column.
GRID_BAND_WIDTHS = 2.0
GRID_SHARE = 0.5
# A grid column is drawn vertical: within this many columns per row.
GRID_MAX_SLOPE = 0.02
# A failed side-like line at least this share of the median station side length, lying between
# two traced stations, marks a possible station that was not read.
GAP_SIDE_SHARE = 0.5
# Two traces within this many line widths of each other over most of their side are one line.
SAME_LINE_WIDTHS = 1.5
# Two traces that share their bottom are one line only when their sides are one line too, or when
# one side is shorter than this share of the median side of the half (a fragment).
FRAGMENT_SIDE_SHARE = 0.5

# ---------------------------------------------------------------- per-station engagement
# On a half that is not read as a whole, a traced station is engaged only when its knuckle is
# clear: it turns by at least CLEAR_TURN_DEG (a chine between a steep side and a low-deadrise
# bottom; the tight bilge of a round-bilge section seen with short arms turns less) and lies at
# least CLEAR_OFFSET_SHARE of the half's reach from the centreline (corners where lines meet the
# keel or stem outline are nearer).
CLEAR_TURN_DEG = 45.0
CLEAR_OFFSET_SHARE = 0.2
# The station takes the existing reader's name for the same curve: that station's cells lie within
# NAME_MATCH_WIDTHS line widths of the traced side at NAME_MIN_ROWS or more measuring rows, and at
# NAME_ROW_SHARE or more of the rows they share above the knuckle. Exactly one name must match.
NAME_MATCH_WIDTHS = 1.5
NAME_MIN_ROWS = 2
NAME_ROW_SHARE = 0.75
# A cell of the existing reader within this many line widths of an engaged polyline on the same
# row is the same ink: keeping it would give one drawn line two stations.
SAME_INK_WIDTHS = 1.0


# Trace point states.
NO_INK, IN_CROSSING, ON_INK = 0, 1, 2


@dataclass
class Trace:
    """Points followed along one ink line, and how each was seen."""

    points: np.ndarray  # (n, 2) row, column
    states: np.ndarray  # (n,) NO_INK (coasted), IN_CROSSING (inside a wide run) or ON_INK
    # Points inside a wide run right after the last narrow-run point: the trace ended in a line it met.
    tail: np.ndarray = field(default_factory=lambda: np.zeros((0, 2)))


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
    shared_knuckle: bool = False  # another traced side reaches the same knuckle point
    seed: tuple[float, float] | None = None  # (row, column) the side was traced from
    # Other lines that leave the knuckle and reach the centreline: the bottom could be any of them.
    bottom_alternatives: int = 0
    # A level (flat) bottom as traced, outer end first; the polyline keeps only its two ends.
    level_bottom: np.ndarray | None = None

    @property
    def rabbet(self) -> tuple[float, float]:
        return float(self.points[0, 0]), float(self.points[0, 1])

    @property
    def sheer(self) -> tuple[float, float]:
        """The top end of the traced side (`trace_side_up`): where the station line ends on the
        drawn sheer line, or the top of a rail tick drawn on from the side."""
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

    def side_points(self) -> np.ndarray:
        """The traced side: the knuckle up to the sheer end."""
        return self.points[self.knuckle_index:]

    def bottom_points(self) -> np.ndarray:
        """The traced bottom: the rabbet up to the knuckle (a level bottom as traced)."""
        if self.level_bottom is not None:
            return self.level_bottom[::-1]
        return self.points[:self.knuckle_index + 1]

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
    # On a declined half: stations engaged one by one, named by the existing reader (`engage_stations`).
    engaged: list[StationPolyline] = field(default_factory=list)
    # Existing cells above the top of their own station's traced side (`unsupported_cells`).
    unsupported: list = field(default_factory=list)
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
    tail = []
    for point, state in zip(points[last + 1:], states[last + 1:]):
        if state != IN_CROSSING:
            break
        tail.append(point)
    return Trace(np.asarray(points[:last + 1]), np.asarray(states[:last + 1]),
                 np.asarray(tail).reshape(-1, 2))


# ---------------------------------------------------------------- the top of a side

def trace_side_up(ink: np.ndarray, seed, width: float) -> np.ndarray:
    """Points from `seed` up the side to its top end, the sheer.

    The sheer is where the station line ends on the drawn sheer line, at the line's top edge (the
    deck top at the side). The trace passes lines that cross the side and stops where the ink ends.
    When it stops inside the line it meets (a wide run), the end is carried on along the side's
    direction to the far edge of that line's ink.
    """
    trace = trace_line(ink, seed, (-1.0, 0.0), width)
    points = trace.points
    if len(trace.tail):
        heading = _direction(list(points), list(trace.states), DIRECTION_WINDOW_WIDTHS * width,
                             np.array([-1.0, 0.0]))
        edge = _ink_edge(ink, points[-1], heading, END_INTO_LINE_WIDTHS * width)
        if edge > 0.0:
            points = np.concatenate([points, [points[-1] + edge * heading]])
    return points


def _ink_widths(ink: np.ndarray, points: np.ndarray, width: float) -> np.ndarray:
    """Width of the narrow ink run across the line at each point; NaN inside crossings or gaps."""
    widths = np.full(len(points), np.nan)
    for k, point in enumerate(points):
        ahead, behind = points[min(len(points) - 1, k + 3)], points[max(0, k - 3)]
        if np.allclose(ahead, behind):
            continue
        heading = _unit(ahead - behind)
        normal = np.array([-heading[1], heading[0]])
        for first, last in _perpendicular_runs(ink, point, normal, SEARCH_WIDTHS * width + 2.0):
            if first <= 0.5 and last >= -0.5 and last - first + 1.0 <= WIDE_RUN_WIDTHS * width:
                widths[k] = last - first + 1.0
    return widths


def _cut_at_thin_line(ink: np.ndarray, side_points: np.ndarray, width: float) -> np.ndarray:
    """`side_points` (top first) without a thinner line the trace ran on into at the top.

    The thin part runs from the top end down to the junction: the lowest point at which both the
    whole part above it and the last THIN_RUN_WIDTHS above it have a median ink width under
    THIN_SHARE of the side's lower half.
    """
    widths = _ink_widths(ink, side_points, width)
    lower = widths[len(widths) // 2:]
    if np.sum(~np.isnan(lower)) < 5:
        return side_points
    limit = THIN_SHARE * float(np.nanmedian(lower))
    span = max(3, int(THIN_RUN_WIDTHS * width / STEP_PX))
    junction = None
    def thin(part: np.ndarray) -> bool:
        return np.sum(~np.isnan(part)) >= 0.6 * len(part) and np.nanmedian(part) < limit

    for end in range(span, len(side_points) // 2):
        if thin(widths[:end]) and thin(widths[end - span:end]):
            junction = end
    return side_points if junction is None else side_points[junction:]


def _ink_edge(ink: np.ndarray, start: np.ndarray, heading: np.ndarray, limit: float) -> float:
    """Distance from `start` along `heading` to the far edge of the ink run there (gaps up to
    RUN_JOIN_GAP_PX are ink); 0 when the run goes on beyond `limit`."""
    edge, gap = 0.0, 0
    for step in range(1, int(limit) + RUN_JOIN_GAP_PX + 2):
        row, column = np.rint(start + step * heading).astype(int)
        inside = 0 <= row < ink.shape[0] and 0 <= column < ink.shape[1]
        if inside and ink[row, column]:
            edge, gap = float(step), 0
        else:
            gap += 1
            if gap > RUN_JOIN_GAP_PX:
                return edge if edge <= limit else 0.0
    return 0.0


def _cut_at_grid(points: np.ndarray, width: float, grid_columns) -> np.ndarray:
    """`points` (bottom first, upward) cut where they join a grid column and run on along it to the top.

    A trace up a side beside a buttock line can leave the hull where they meet and run on up the
    buttock; the side's top is then the junction.
    """
    band = GRID_BAND_WIDTHS * width + 3.0
    arc = _arc(points)
    for column in grid_columns:
        near = np.abs(points[:, 1] - column) <= band
        if not near[-1]:
            continue
        join = len(points) - 1
        while join > 0 and near[join - 1]:
            join -= 1
        if join > 0 and arc[-1] - arc[join] >= GRID_RUN_WIDTHS * width:
            return points[:join + 1]
    return points


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

def on_grid_line(points: np.ndarray, values, axis: int, width: float) -> bool:
    """True when most of `points` lie along one grid line: a row (axis 0) or a column (axis 1)."""
    band = GRID_BAND_WIDTHS * width + 3.0
    for value in values:
        if float(np.mean(np.abs(points[:, axis] - value) <= band)) > GRID_SHARE:
            return True
    return False


def drawn_rows(ink: np.ndarray, sheet: bpr.SheetLayout) -> list[float]:
    """The calibrated rows that are drawn lines: on each half, ink on the row (one pixel either side,
    for the calibration's rounding) at more than GRID_SHARE of the half's columns.

    A drawn waterline is inked on its calibrated row across the body plan. A measuring row that the
    calibration adds between drawn lines is not, though level bottoms of both halves may lie a few
    pixels from it. Columns off the image count as no ink.
    """
    centre, reach = int(round(sheet.centre_column)), sheet.max_offset_px
    drawn = []
    for row in sheet.waterline_rows.values():
        top, bottom = max(0, int(round(row)) - 1), min(ink.shape[0], int(round(row)) + 2)
        if top >= bottom:
            continue
        band = ink[top:bottom]
        halves = (band[:, max(0, centre - reach):max(0, centre)], band[:, centre + 1:centre + reach + 1])
        if all(np.count_nonzero(half.any(axis=0)) > GRID_SHARE * reach for half in halves):
            drawn.append(row)
    return drawn


def _distance_to(points: np.ndarray, point) -> float:
    return float(np.min(np.hypot(points[:, 0] - point[0], points[:, 1] - point[1])))


def _length(points: np.ndarray) -> float:
    return float(_arc(points)[-1]) if len(points) > 1 else 0.0


def _inward(sign: int, angle_deg: float) -> np.ndarray:
    """Direction pointing toward the centreline, `angle_deg` below the horizontal."""
    angle = np.radians(angle_deg)
    return np.array([np.sin(angle), -sign * np.cos(angle)])


def _bottom(ink: np.ndarray, side_points: np.ndarray, sheet: bpr.SheetLayout, sign: int,
            width: float, exclude: tuple = ()) -> tuple[np.ndarray | None, int, bool]:
    """(Points of the bottom leaving the lower end of a side, outer end first, or None; the number
    of other lines that leave the end and reach the centreline elsewhere; True for a level bottom).

    Every branch that leaves the end inward on ink is followed to its first corner. A bottom
    descends over its whole length and reaches in toward the centreline. Of those, the one that
    reaches nearest the centreline is the bottom, the longest if several reach equally far. A
    start further back up the side is tried only when no branch leaves from nearer its end (a
    branch from higher up can cut across to the bottom and miss the corner). A branch that runs
    along one of the `exclude` lines (another station's bottom) is not taken. When no branch
    descends, a level branch (a flat bottom) is taken by the same rule, from the nearest start
    that has one; it must run on to the centreline (within CENTRE_CLEAR_WIDTHS line widths).
    """
    end = side_points[-1]
    knuckle_offset = sign * (end[1] - sheet.centre_column)
    centre = sheet.centre_column

    def keep(row, column):
        return sign * (column - centre) > 0.0

    start_steps = int(np.ceil(BRANCH_START_WIDTHS * width / STEP_PX))
    starts = [side_points[max(0, len(side_points) - 1 - int(back / STEP_PX))]
              for back in np.arange(0.0, BRANCH_REACH_WIDTHS * width + 0.1, width)]
    candidates, level_candidates = [], []
    drawn = None  # the drawn calibrated rows, found when a level branch first needs them
    for back, start in enumerate(starts):
        level_here = []
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
            if np.min(points[:, 0]) < points[0, 0] - width:  # rises above its start: not a bottom
                continue
            if any(_same_line(points, other, width) for other in exclude):
                continue
            inner = sign * (points[-1, 1] - centre)
            candidate = (back, round(inner / width), -length, points)
            if points[-1, 0] - points[0, 0] >= BOTTOM_MIN_DESCENT_SHARE * length:
                if not on_grid_line(points, sheet.waterline_rows.values(), 0, width):
                    candidates.append(candidate)
            elif inner <= CENTRE_CLEAR_WIDTHS * width:
                # A flat bottom is drawn level on to the centreline; a level line that stops short of it is
                # another line (a frame or box border below the hull). A level branch is a drawn waterline
                # only where one is drawn: measuring rows the calibration adds between drawn lines are not
                # on the paper, and a flat bottom may lie on one.
                if drawn is None:
                    drawn = drawn_rows(ink, sheet)
                if not on_grid_line(points, drawn, 0, width):
                    level_here.append(candidate)
        if candidates:
            break
        if not level_candidates:
            level_candidates = level_here
    level = not candidates
    if level:
        candidates = level_candidates
    if not candidates:
        return None, 0, False
    chosen = min(candidates, key=lambda c: c[:3])[3]
    # Other branches that also reach the centreline but end elsewhere: lines of other stations that
    # pass the knuckle, any of which could be this station's bottom.
    reach = BOTTOM_INNER_SHARE * knuckle_offset
    ends = [c[3][-1] for c in candidates if sign * (c[3][-1, 1] - centre) <= reach]
    alternatives = [end for end in ends if np.hypot(*(end - chosen[-1])) > SAME_LINE_WIDTHS * width]
    distinct: list = []
    for end in alternatives:
        if all(np.hypot(*(end - other)) > SAME_LINE_WIDTHS * width for other in distinct):
            distinct.append(end)
    return chosen, len(distinct), level


def _monotone(points: np.ndarray) -> np.ndarray:
    """Points from low to high with strictly decreasing rows (drops points that do not rise)."""
    kept = [points[0]]
    for point in points[1:]:
        if point[0] < kept[-1][0] - 0.25:
            kept.append(point)
    return np.asarray(kept)


def _ends_on_grid_column(side_points: np.ndarray, side: bpr.SideLayout, width: float) -> bool:
    """True when the side's lower arm runs straight down a calibrated grid column.

    A trace can leave a station side for a buttock line where they cross; the knuckle it then
    finds is where the buttock meets a waterline. A station side beside a buttock is slanted.
    """
    arc = _arc(side_points)
    arm = side_points[arc >= arc[-1] - KNUCKLE_ARM_WIDTHS * width]
    if len(arm) < 3:
        return False
    columns_per_row = np.polyfit(arm[:, 0], arm[:, 1], 1)[0]
    band = GRID_BAND_WIDTHS * width + 3.0
    return abs(columns_per_row) <= GRID_MAX_SLOPE and any(
        float(np.max(np.abs(arm[:, 1] - column))) <= band for column in side.grid_columns)


def trace_station(ink: np.ndarray, seed, sheet: bpr.SheetLayout, side: bpr.SideLayout,
                  width: float, exclude: tuple = ()) -> tuple[StationPolyline | None, np.ndarray, np.ndarray, str]:
    """Trace the station whose side passes through `seed`; its bottom runs along no `exclude` line.

    Returns (station or None, the whole traced line for de-duplication, the side cut at its
    corners, the reason when None).
    """
    seed = np.asarray(seed, dtype=float)
    up = trace_side_up(ink, seed, width)
    down = trace_line(ink, seed, (1.0, 0.0), width)
    line = np.concatenate([up[::-1], down.points[1:]])  # top to bottom
    seed_index = len(up) - 1
    # The side is the straight-run of the line through the seed: cut at the first sharp corner
    # below it (the knuckle, where the trace ran on along the chine curve or the bottom) and
    # above it (where it ran on along a deck or rail line).
    lower = first_corner(line, seed_index, 1, width)
    upper = first_corner(line, seed_index, -1, width)
    side_points = line[(upper or 0):(lower + 1 if lower is not None else len(line))]
    side_points = _cut_at_grid(side_points[::-1], width, side.grid_columns)[::-1]
    side_points = _cut_at_thin_line(ink, side_points, width)
    if _length(side_points) < MIN_SIDE_WIDTHS * width:
        return None, line, side_points, 'short line'
    if on_grid_line(side_points, side.grid_columns, 1, width) or _ends_on_grid_column(side_points, side, width):
        return None, line, side_points, 'grid line'
    bottom, alternatives, level = _bottom(ink, side_points, sheet, side.sign, width, exclude)
    if bottom is None:
        return None, line, side_points, 'no bottom branch'
    # Knuckle: where straight fits of the side's lower end and the bottom's outer end meet.
    arm, skip = KNUCKLE_ARM_WIDTHS * width, KNUCKLE_SKIP_WIDTHS * width
    start_index = int(np.argmin(np.hypot(*(side_points - bottom[0]).T)))
    side_points = side_points[:start_index + 1]
    joined = np.concatenate([side_points, bottom[1:]])
    arc = _arc(joined)
    sharp, turn = is_sharp(joined, arc, len(side_points) - 1, width)
    if not sharp:
        return None, line, side_points, 'no sharp knuckle'
    side_arc, bottom_arc = _arc(side_points), _arc(bottom)
    side_end = side_points[side_arc >= side_arc[-1] - arm]
    bottom_start = bottom[(bottom_arc >= skip) & (bottom_arc <= arm)]
    fits = (_fit_line(side_end, side_end[-1] - side_end[0]), _fit_line(bottom_start, bottom_start[-1] - bottom_start[0]))
    corner = None if None in fits else _intersection(*fits)
    if corner is None or _distance_to(joined, corner) > KNUCKLE_REACH_WIDTHS * width:
        return None, line, side_points, 'side and bottom do not meet at a corner'
    knuckle_offset = side.sign * (corner[1] - sheet.centre_column)
    inner_offset = side.sign * (bottom[-1, 1] - sheet.centre_column)
    if inner_offset > BOTTOM_INNER_SHARE * knuckle_offset:
        return None, line, side_points, 'bottom does not reach the centreline'
    # Low to high: the rabbet (the bottom's inner end) first; the knuckle is the fitted corner.
    if level:
        # Rows must fall from the rabbet to the sheer, but a level bottom does not rise: keep its two ends.
        rabbet = (max(float(bottom[-1, 0]), float(corner[0]) + LEVEL_ROW_STEP_PX), float(bottom[-1, 1]))
        low_to_high = np.concatenate([[rabbet], [corner], side_points[::-1][1:]])
    else:
        low_to_high = np.concatenate([bottom[::-1][:-1], [corner], side_points[::-1][1:]])
    polyline = _monotone(low_to_high)
    knuckle_index = int(np.argmin(np.hypot(*(polyline - corner).T)))
    station = StationPolyline(side.name, side.sign, polyline, knuckle_index,
                              (float(corner[0]), float(corner[1])), turn, seed=(float(seed[0]), float(seed[1])),
                              bottom_alternatives=alternatives, level_bottom=bottom if level else None)
    return station, line, side_points, ''


# ---------------------------------------------------------------- one half

def _same_line(first: np.ndarray, second: np.ndarray, width: float) -> bool:
    """Two traces are one line when most of the shorter lies on the longer."""
    short, long_ = (first, second) if len(first) <= len(second) else (second, first)
    sample = short[:: max(1, len(short) // 40)]
    near = [_distance_to(long_, point) <= SAME_LINE_WIDTHS * width for point in sample]
    return float(np.mean(near)) > 0.5


def _same_station(first: StationPolyline, second: StationPolyline, width: float, fragment_px: float) -> bool:
    """Two traced stations are one when their polylines are one line and their sides are too.

    Neighbouring stations can share most of their bottom where they run into the keel; their
    sides still differ. A side shorter than `fragment_px` is a fragment, not a station of its own.
    """
    if not _same_line(first.points, second.points, width):
        return False
    sides = first.side_points(), second.side_points()
    return _same_line(*sides, width) or min(_length(points) for points in sides) < fragment_px


def side_and_knuckle_only(station: StationPolyline) -> None:
    """Cut the station's polyline to its side: the knuckle up to the sheer end."""
    station.points = station.points[station.knuckle_index:]
    station.knuckle_index = 0
    station.level_bottom = None


def _own_bottoms(ink: np.ndarray, sheet: bpr.SheetLayout, side: bpr.SideLayout, width: float,
                 stations: list[StationPolyline]) -> tuple[list[StationPolyline], int]:
    """Give each bottom line to one station: (stations, number kept without a bottom).

    Where the bottoms of neighbouring stations cross near a knuckle, the trace from an inner
    knuckle can run on along the outer station's bottom. A bottom starts at its own knuckle and
    runs inward, so a bottom that two stations claim belongs to the outer one (its knuckle is
    further out); the inner station is traced again without that line. A station with no other
    bottom keeps its side and knuckle only: its side is a drawn station of its own (crowded
    stations run their bottoms into one line near the keel), and leaving it out would take one
    station from the nesting order and shift the name of every station inside it.
    """
    kept: list[StationPolyline] = []
    without_bottom = 0
    for station in sorted(stations, key=lambda s: -s.offset_px(s.chine[1], sheet.centre_column)):
        taken = tuple(other.bottom_points() for other in kept)
        if any(_same_line(station.bottom_points(), bottom, width) for bottom in taken):
            again, *_ = trace_station(ink, station.seed, sheet, side, width, taken)
            if again is None:
                side_and_knuckle_only(station)
                station.notes.append('bottom is an outer station\'s and no other was found; side and knuckle only')
                without_bottom += 1
            else:
                again.notes.append('bottom traced again: the first one was an outer station\'s bottom')
                station = again
        kept.append(station)
    return kept, without_bottom


def _fragments(stations: list[StationPolyline]) -> list[StationPolyline]:
    """Traced stations whose side is shorter than FRAGMENT_SIDE_SHARE of the half's median side.

    A station side runs from the chine up to the sheer. A much shorter side with a knuckle is part
    of another outline (a transom, a stem or keel corner, a rail), not a station of the nesting
    order.
    """
    if len(stations) < MIN_STATIONS:
        return []
    median = float(np.median([_length(s.side_points()) for s in stations]))
    return [s for s in stations if _length(s.side_points()) < FRAGMENT_SIDE_SHARE * median]


def _mark_shared_knuckles(stations: list[StationPolyline], width: float) -> None:
    """Flag stations whose knuckle another (different) traced station reaches as well.

    Different sides that end at one corner ran into one line (curves crowded on a heavy line);
    the corner cannot be given to either.
    """
    for i, first in enumerate(stations):
        for second in stations[i + 1:]:
            if np.hypot(first.chine[0] - second.chine[0], first.chine[1] - second.chine[1]) <= SAME_LINE_WIDTHS * width:
                first.shared_knuckle = second.shared_knuckle = True


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


def _first_gap(ordered: list[StationPolyline], failed_sides: list[np.ndarray], rows: list[float],
               sheet: bpr.SheetLayout, width: float) -> int | None:
    """Rank k when a long failed side lies between stations k and k+1 at a nesting row, else None.

    Long: at least GAP_SIDE_SHARE of the median station side length (rail ticks, labels and short
    strokes are shorter).
    """
    if len(ordered) < 2 or not rows:
        return None
    lengths = [_length(s.points[s.knuckle_index:]) for s in ordered]
    minimum = GAP_SIDE_SHARE * float(np.median(lengths))
    row = rows[len(rows) // 2]
    offsets = [s.offset_px(s.column_at_row(row), sheet.centre_column) for s in ordered]
    gaps = []
    for points in failed_sides:
        if _length(points) < minimum or not points[:, 0].min() <= row <= points[:, 0].max():
            continue
        order = np.argsort(points[:, 0])
        offset = ordered[0].sign * (np.interp(row, points[order, 0], points[order, 1]) - sheet.centre_column)
        for k in range(len(ordered) - 1):
            clear = SAME_LINE_WIDTHS * width
            if offsets[k + 1] + clear < offset < offsets[k] - clear:
                gaps.append(k)
    return min(gaps) if gaps else None


def read_half(ink: np.ndarray, sheet: bpr.SheetLayout, side: bpr.SideLayout) -> HalfReading:
    """Trace and name the stations of one half; declined when the half has no hard chine."""
    width = line_width(ink, sheet, side)
    result = HalfReading(side.name, False, line_width_px=width)
    traced_sides: list[np.ndarray] = []
    candidates: list[StationPolyline] = []
    failed_sides: list[np.ndarray] = []  # side-like lines that gave no station
    reasons: dict = {}
    for seed in seeds(ink, sheet, side, width):
        if any(_distance_to(points, seed) <= SAME_LINE_WIDTHS * width for points in traced_sides):
            continue
        station, line, side_points, reason = trace_station(ink, seed, sheet, side, width)
        traced_sides.append(line)
        if station is None:
            reasons[reason] = reasons.get(reason, 0) + 1
            if reason not in ('short line', 'grid line'):
                failed_sides.append(side_points)
            continue
        candidates.append(station)
    # One station per drawn line: the trace with the longest side is kept.
    stations: list[StationPolyline] = []
    if candidates:
        fragment = FRAGMENT_SIDE_SHARE * float(np.median([_length(s.side_points()) for s in candidates]))
        for station in sorted(candidates, key=lambda s: -_length(s.side_points())):
            if not any(_same_station(station, other, width, fragment) for other in stations):
                stations.append(station)
    _mark_shared_knuckles(stations, width)
    shared = [s for s in stations if s.shared_knuckle]
    stations, without_bottom = _own_bottoms(ink, sheet, side, width, [s for s in stations if not s.shared_knuckle])
    for station in shared:
        station.notes.append('another traced side reaches the same knuckle; not named')
    fragments = _fragments(stations)
    for station in fragments:
        station.notes.append('side much shorter than the other stations\' sides: an outline, not a station; not named')
    stations = [s for s in stations if not any(s is f for f in fragments)]
    result.notes.append(f'traced {len(traced_sides)} lines; {len(stations)} with a knuckle; '
                        f'others: {dict(sorted(reasons.items()))}'
                        + (f'; {without_bottom} without an own bottom (side and knuckle only)' if without_bottom else '')
                        + (f'; {len(shared)} with a shared knuckle' if shared else '')
                        + (f'; {len(fragments)} short-side outlines' if fragments else ''))
    result.unnamed += shared + fragments
    expected = len(side.stations_outer_first)
    if len(stations) < max(MIN_STATIONS, MIN_STATION_SHARE * expected):
        result.unnamed += stations
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
        result.unnamed += ordered
        result.read = False
        result.notes.append(f'declined: {len(ordered)} stations traced for {expected} in the calibration')
        return result
    named = len(ordered)
    if len(ordered) < expected:
        # Names run from the outermost station, the widest and clearest line of the half. The
        # stations not traced are taken to be the innermost (the small sections at the stem or
        # transom, whose sides merge with the stem, keel or transom outline). A long side-like
        # line that failed between two traced stations may be a station that was not read: the
        # stations inward of it are then not named.
        gap = _first_gap(ordered, failed_sides, rows, sheet, width)
        if gap is not None:
            named = gap + 1
            result.notes.append(f'an untraced side-like line lies inside rank {gap}; stations inward of it not named')
        missing = side.stations_outer_first[len(ordered):]
        result.notes.append(f'{len(ordered)} stations traced for {expected}; innermost {list(missing)} not read')
    for i, (station, number) in enumerate(zip(ordered, side.stations_outer_first)):
        if i >= named:
            station.notes.append(f'traced at rank {i}, inward of an untraced line; not named')
            result.unnamed.append(station)
        elif i in breaks:
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


# ---------------------------------------------------------------- per-station engagement

def is_clear_knuckle(station: StationPolyline, sheet: bpr.SheetLayout) -> bool:
    """A knuckle clear enough to engage one station on its own (see CLEAR_TURN_DEG)."""
    offset = station.offset_px(station.chine[1], sheet.centre_column)
    return (not station.shared_knuckle and station.turn_deg >= CLEAR_TURN_DEG
            and offset >= CLEAR_OFFSET_SHARE * sheet.max_offset_px)


def _existing_name(station: StationPolyline, existing: dict, side: bpr.SideLayout,
                   sheet: bpr.SheetLayout, width: float) -> int | None:
    """The one station name whose existing cells lie on this station's traced side, else None."""
    tolerance = NAME_MATCH_WIDTHS * width / sheet.pixels_per_metre
    names = []
    for name in side.stations_outer_first:
        shared = agree = 0
        for label, row in sheet.waterline_rows.items():
            value = existing.get((name, label))
            if value is None or row >= station.chine[0]:  # the side only: above the knuckle
                continue
            mine = station.half_breadth_m(row, sheet)
            if mine is None:
                continue
            shared += 1
            agree += abs(mine - value) <= tolerance
        if agree >= NAME_MIN_ROWS and agree >= NAME_ROW_SHARE * shared:
            names.append(name)
    return names[0] if len(names) == 1 else None


def engage_stations(half: HalfReading, side: bpr.SideLayout, existing: dict,
                    sheet: bpr.SheetLayout, ink: np.ndarray | None = None) -> list[StationPolyline]:
    """Engage the clear-knuckle stations of a declined half, one by one.

    `existing` is the existing reader's table of this half, {(station, waterline): m}. A traced
    station is named after the existing station whose cells lie on its side; it is left out when
    no name or more than one name matches, or when another engaged station takes the same name.
    When other lines through its knuckle also reach the centreline, its bottom is not engaged.
    With `ink`, existing cells of the other stations that lie above their own traced side are
    listed in `half.unsupported` (`unsupported_cells`).
    Sets and returns `half.engaged`. A half read as a whole engages nothing here.
    """
    half.engaged = []
    if half.read:
        return half.engaged
    named = []
    for station in half.unnamed:
        if not is_clear_knuckle(station, sheet):
            continue
        name = _existing_name(station, existing, side, sheet, half.line_width_px)
        if name is None:
            station.notes.append('clear knuckle; no single existing station on its side; not engaged')
            continue
        named.append((name, station))
    counts = {}
    for name, _ in named:
        counts[name] = counts.get(name, 0) + 1
    for name, station in named:
        if counts[name] > 1:
            station.notes.append(f'clear knuckle; station {name} matched by another trace too; not engaged')
            continue
        station.station = name
        station.notes.append(f'engaged on its own; named {name} by the existing reader')
        if station.bottom_alternatives:
            # Without its neighbours traced, nothing tells which of the lines through the knuckle
            # is this station's bottom: only the side and the knuckle are engaged.
            side_and_knuckle_only(station)
            station.notes.append(f'{station.bottom_alternatives} other bottom lines through the knuckle; '
                                 'side and knuckle only')
        half.engaged.append(station)
    if half.engaged:
        half.notes.append(f'engaged stations {[s.station for s in half.engaged]}; others kept from the existing reader')
        if ink is not None:
            half.unsupported = unsupported_cells(ink, half, side, existing, sheet)
            if half.unsupported:
                half.notes.append(f'existing cells above their station\'s traced side left out: {half.unsupported}')
    return half.engaged


def unsupported_cells(ink: np.ndarray, half: HalfReading, side: bpr.SideLayout, existing: dict,
                      sheet: bpr.SheetLayout) -> list:
    """Existing cells (station, waterline) that lie above the top of their station's traced side.

    A cell is kept only where the hull is drawn: on the station's own line between its ends. Each
    existing station that is not engaged is traced up from its middle cell by height, with the
    sheer rules of `trace_side_up` and the thin-line and grid cuts of a side; its cells more than
    one line width above the top end are listed. A station whose middle cell gives no seed on ink,
    or whose trace rises less than MIN_SIDE_WIDTHS above it, is not checked.
    """
    width = half.line_width_px
    engaged = {station.station for station in half.engaged}
    by_station: dict = {}
    for (name, label), value in existing.items():
        if name not in engaged:
            by_station.setdefault(name, []).append((label, value))
    unsupported = []
    for name, cells in sorted(by_station.items()):
        # The middle cell by height: on the side (the lowest may lie on the bottom, the highest above the sheer).
        ordered = sorted(cells, key=lambda cell: sheet.waterline_rows[cell[0]])
        label, value = ordered[(len(ordered) - 1) // 2]
        column = sheet.centre_column + side.sign * value * sheet.pixels_per_metre
        seed = None
        for row in (sheet.waterline_rows[label] - int(2 * width) - 3, sheet.waterline_rows[label] + int(2 * width) + 3):
            centre = _run_centre(ink, int(row), column, width) if 0 <= row < ink.shape[0] else None
            if centre is not None:
                seed = (float(int(row)), centre)
                break
        if seed is None:
            continue
        upward = _cut_at_grid(trace_side_up(ink, seed, width), width, side.grid_columns)  # seed first
        side_points = _cut_at_thin_line(ink, upward[::-1], width)  # top first
        top = float(side_points[0, 0])
        if seed[0] - top < MIN_SIDE_WIDTHS * width:
            continue  # the trace did not follow a side up from the seed: no evidence either way
        unsupported += [(name, label) for label, _ in cells if sheet.waterline_rows[label] < top - width]
    return sorted(unsupported)


def same_ink(station: StationPolyline, row: float, column: float, width: float) -> bool:
    """True when the point (row, column) lies on the station's polyline at that row."""
    mine = station.column_at_row(row)
    return mine is not None and abs(mine - column) <= SAME_INK_WIDTHS * width


def half_table(half: HalfReading, existing: dict, sheet: bpr.SheetLayout) -> dict:
    """Product table of one half: {(station, waterline): half-breadth m}.

    A half read as a whole gives its polylines' table. A declined half gives the existing table
    with each engaged station's cells replaced by its polyline, and without existing cells of
    other stations that lie on an engaged polyline or above their own traced side.
    """
    if half.read:
        return waterline_table({half.side: half}, sheet)
    table = {key: value for key, value in existing.items() if key not in set(half.unsupported)}
    for station in half.engaged:
        for (name, label), value in list(table.items()):
            row = sheet.waterline_rows[label]
            column = sheet.centre_column + station.sign * value * sheet.pixels_per_metre
            if name == station.station or same_ink(station, row, column, half.line_width_px):
                del table[(name, label)]
    for station in half.engaged:
        for label, row in sheet.waterline_rows.items():
            value = station.half_breadth_m(row, sheet)
            if value is not None:
                table[(station.station, label)] = value
    return table
