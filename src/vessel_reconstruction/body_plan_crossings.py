"""Measure where the drawn curves of a scanned body plan cross each waterline.

This is the code half of the "code measures, model identifies" body-plan reader (plan section
3.5.8). A low-cost vision model cannot place thin, overlapping lines to a few pixels, but code can:
along each waterline, it traces every ink line through a narrow band of rows above and below the
waterline at full resolution, fits the line, and gives the crossing column to sub-pixel accuracy
with the line's slope and width. It also sorts each crossing into a kind (station curve, thin grid
line, lettering stroke, long straight line such as a diagonal, two curves drawn on top of each
other) and links the curve crossings of neighbouring waterlines into chains by nesting order and
direction.

A model then answers only small, discrete questions about these crossings (see
`body_plan_identity`); the half-breadth values always come from the code measurement.

Image convention: a 2D array, row 0 at the top; `ink` is True where the drawing has ink.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

# Rows above and below the waterline that the tracer reads.
BAND_ROWS = 40
# The drawn waterline is searched this many rows either side of its nominal row, in blocks of
# columns; its own ink plus this margin is masked out before tracing.
WATERLINE_SEARCH_ROWS = 20
WATERLINE_BLOCK_PX = 256
WATERLINE_MARGIN_PX = 2.0
# A track must have this many measured rows on each side of the waterline to count as a crossing.
MIN_ROWS_PER_SIDE = 5
# Rows a track may coast without ink before it ends (small breaks in a scanned line).
MAX_COAST_ROWS = 3
# Runs of one row closer than this (px) are one line split by scan noise.
RUN_JOIN_GAP_PX = 1
# Line kinds by perpendicular width, as multiples of the typical curve width on the sheet.
GRID_MAX_WIDTH_RATIO = 0.70
DOUBLE_MIN_WIDTH_RATIO = 1.55  # reported only: chains find curves drawn on top of each other
LETTERING_MIN_WIDTH_RATIO = 2.2
# A diagonal is an oblique straight line (|columns per row| in STRAIGHT_SLOPES) that runs at
# least DIAGONAL_MIN_LENGTH_PX to within DIAGONAL_CENTRE_REACH_PX of the centreline; a station
# curve may be nearly straight for a long way, but it does not run straight to the centreline.
STRAIGHT_SLOPES = (0.3, 3.0)
STRAIGHT_MAX_DEVIATION_PX = 2.5
DIAGONAL_MIN_LENGTH_PX = 1500
DIAGONAL_MAX_DEVIATION_PX = 5.0
DIAGONAL_CENTRE_REACH_PX = 60
# Vertical lines this close to the centreline are the stem, keel or sternpost outline.
CENTRELINE_STRUCTURE_PX = 70
# A stem or sternpost may be drawn further out (its siding, or the outside of the planking): it is
# then a long, straight, near-vertical line (|columns per row| below POST_MAX_SLOPE) that runs for
# at least POST_MIN_SPACINGS waterline spacings within DIAGONAL_MAX_DEVIATION_PX of one straight
# line (a post is drawn thick, and station curves join it), in the inner POST_INNER_FRACTION of the
# half body plan. A station curve on the flat of the side can be as straight and vertical, but it lies at
# the outer edge of the plan, never near the centreline.
POST_MAX_SLOPE = 0.05
POST_MIN_SPACINGS = 2.5
POST_INNER_FRACTION = 0.25
# A line that ends within SHORT_STROKE_SPACINGS waterline spacings both above and below its
# crossing is a stroke of lettering or a short leader line, not a station curve (a station curve
# runs on to a neighbouring waterline, the keel or the sheer). A digit stroke ends within about
# 0.15 spacings of a waterline it crosses (C.A. Thayer sheet 4); a station curve that ends at the
# deck edge just above a waterline still runs 0.3 spacings or more below it (Balclutha sheet 7).
SHORT_STROKE_SPACINGS = 0.25
# Following a curve from one waterline to the next: rows left out at the start and before the
# target (waterline ink), rows in the moving line fit, rows without ink allowed, rows passed on the
# prediction where another line crosses (a run wider than FOLLOW_WIDE_RUN_RATIO line widths).
FOLLOW_START_OFFSET_ROWS = 10
FOLLOW_STOP_MARGIN_ROWS = 10
FOLLOW_FIT_ROWS = 20
FOLLOW_MAX_MISSES = 8
FOLLOW_MAX_COAST_ROWS = 60
FOLLOW_WIDE_RUN_RATIO = 2.0
# A followed curve links to a crossing of the next waterline within this many columns.
LINK_TOLERANCE_PX = 8.0
# Slope (columns per row) above which a crossing is too shallow to place well.
SHALLOW_SLOPE = 6.0

KIND_CURVE = 'curve'
KIND_DOUBLE = 'double'
KIND_GRID = 'grid'
KIND_LETTERING = 'lettering'
KIND_STRAIGHT = 'straight'
KIND_SHALLOW = 'shallow'
STATION_KINDS = (KIND_CURVE, KIND_DOUBLE)


@dataclass
class Crossing:
    """One ink line crossing one waterline."""

    row: float  # row of the crossing on the drawn waterline
    x_px: float  # crossing column, sub-pixel
    slope: float  # d(column) / d(row) at the waterline
    width_px: float  # perpendicular line width (median over the measured rows)
    rows_above: int
    rows_below: int
    fit_residual_px: float
    kind: str = KIND_CURVE
    notes: list[str] = field(default_factory=list)

    def offset_px(self, centre_column: float, sign: int) -> float:
        """Signed distance out from the centreline (positive on the side that `sign` names)."""
        return sign * (self.x_px - centre_column)


def ink_runs(row_pixels: np.ndarray, offset: int = 0) -> list[tuple[int, int]]:
    """Ink runs of one row as (first column, last column + 1)."""
    padded = np.concatenate(([False], row_pixels.astype(bool), [False]))
    edges = np.flatnonzero(np.diff(padded.astype(np.int8)))
    return [(int(start) + offset, int(end) + offset) for start, end in zip(edges[::2], edges[1::2])]


@dataclass
class _Track:
    points: list[tuple[int, float, float, bool]] = field(default_factory=list)  # row, centre, run width, shared
    last_interval: tuple[float, float] = (0.0, 0.0)
    last_row: int = 0
    misses: int = 0

    def clean(self) -> list[tuple[int, float, float]]:
        return [(r, c, w) for r, c, w, shared in self.points if not shared]

    def slope(self) -> float | None:
        clean = self.clean()[-12:]
        if len(clean) < 3:
            return None
        rows = np.array([p[0] for p in clean], dtype=float)
        if np.ptp(rows) < 2:
            return None
        return float(np.polyfit(rows, [p[1] for p in clean], 1)[0])

    def predicted_interval(self, row: int) -> tuple[float, float]:
        step = row - self.last_row
        slope = self.slope()
        low, high = self.last_interval
        if slope is None:  # young track: the next run must touch the last one (8-connected)
            slack = 1.5 + 2.0 * (step - 1)
            return low - slack, high + slack
        shift = slope * step
        slack = 2.0 + 0.25 * abs(slope) * step + (3.0 if step > 1 else 0.0)
        return low + shift - slack, high + shift + slack


def _merged_runs(row_pixels: np.ndarray, offset: int) -> list[tuple[int, int]]:
    """Ink runs of one row, with runs split by a 1 px break joined (scan noise inside one line)."""
    merged: list[tuple[int, int]] = []
    for start, end in ink_runs(row_pixels, offset):
        if merged and start - merged[-1][1] <= RUN_JOIN_GAP_PX:
            merged[-1] = (merged[-1][0], end)
        else:
            merged.append((start, end))
    return merged


def _same_line(first: _Track, second: _Track, row: int) -> bool:
    """Two tracks that follow one line (one was started by a scan break): same place, same slope."""
    first_slope, second_slope = first.slope(), second.slope()
    first_low, first_high = first.predicted_interval(row)
    second_low, second_high = second.predicted_interval(row)
    near = abs((first_low + first_high) / 2 - (second_low + second_high) / 2) <= 3.0
    if first_slope is None or second_slope is None:
        return near
    return near and abs(first_slope - second_slope) <= 0.15 * (1 + abs(first_slope))


def _claim_runs(active: list[_Track], runs: list[tuple[int, int]], r: int) -> dict[int, list[int]]:
    """Run index -> indices of the active tracks that continue into it (nearest prediction first)."""
    candidates = []
    for t_index, track in enumerate(active):
        low, high = track.predicted_interval(r)
        centre = (low + high) / 2
        for r_index, (start, end) in enumerate(runs):
            if end - 1 >= low and start <= high:
                candidates.append((abs((start + end - 1) / 2 - centre), t_index, r_index))
    candidates.sort()
    claims: dict[int, list[int]] = {}
    taken: set[int] = set()
    for _, t_index, r_index in candidates:
        if t_index not in taken:
            taken.add(t_index)
            claims.setdefault(r_index, []).append(t_index)
    return claims


@dataclass
class WaterlineTrace:
    """Where the waterline's own ink lies: row = intercept + gradient * (x - x_origin)."""

    intercept: float
    gradient: float
    x_origin: float
    half_thickness: float

    def row_at(self, x: float) -> float:
        return self.intercept + self.gradient * (x - self.x_origin)


def locate_waterline(ink: np.ndarray, row: int, x_range: tuple[int, int], search: int = WATERLINE_SEARCH_ROWS,
                     block: int = WATERLINE_BLOCK_PX) -> WaterlineTrace:
    """Fit the drawn waterline near the nominal `row` (a scanned sheet is slightly skewed).

    In each block of columns, the waterline rows are the rows within `search` of the nominal row
    whose ink fills at least half the block; a straight line is fitted through the block centres.
    Falls back to the nominal row when no block shows the line.
    """
    x_low, x_high = x_range
    top = max(0, row - search)
    centres, thicknesses = [], []
    for left in range(x_low, x_high, block):
        right = min(x_high, left + block)
        if right - left < block // 4:
            continue
        fill = ink[top:row + search + 1, left:right].mean(axis=1)
        full = np.flatnonzero(fill >= 0.5)
        if full.size:
            centres.append(((left + right) / 2, top + float(np.mean(full))))
            thicknesses.append(float(full.max() - full.min() + 1))
    if not centres:
        return WaterlineTrace(float(row), 0.0, float(x_low), 3.0)
    xs, rows = np.array(centres).T
    gradient, intercept = np.polyfit(xs - x_low, rows, 1) if len(centres) >= 2 else (0.0, rows[0])
    return WaterlineTrace(float(intercept), float(gradient), float(x_low), float(np.median(thicknesses)) / 2)


def _track_band(ink: np.ndarray, waterline: WaterlineTrace, x_low: int, x_high: int, band: int,
                margin: float) -> list[_Track]:
    """Follow every ink line through the band of rows around the waterline.

    The waterline's own ink (within `margin` rows of the traced line) is masked out. Runs of
    consecutive rows are linked by each track's predicted column (its recent slope). Where one run
    serves two tracks (two lines cross or touch), each track keeps its prediction and the row is
    left out of its fit; a track that is only a copy of another (started at a scan break) is
    dropped. A track coasts through the masked rows and through up to MAX_COAST_ROWS other rows.
    """
    centre_row = int(round(waterline.row_at((x_low + x_high) / 2)))
    first = max(0, centre_row - band - int(abs(waterline.gradient) * (x_high - x_low)))
    last = min(ink.shape[0] - 1, centre_row + band + int(abs(waterline.gradient) * (x_high - x_low)))
    columns = np.arange(x_low, x_high)
    line_rows = waterline.row_at(columns)

    def masked(r: int, x: float) -> bool:
        return abs(r - waterline.row_at(x)) <= margin

    active: list[_Track] = []
    finished: list[_Track] = []
    for r in range(first, last + 1):
        pixels = ink[r, x_low:x_high] & (np.abs(r - line_rows) > margin)
        runs = _merged_runs(pixels, x_low)
        claims = _claim_runs(active, runs, r)
        dropped: set[int] = set()
        for t_indices in claims.values():
            ordered = sorted(t_indices, key=lambda index: -len(active[index].clean()))
            for later in ordered[1:]:
                if any(_same_line(active[earlier], active[later], r) for earlier in ordered if earlier not in dropped
                       and earlier != later and len(active[earlier].clean()) >= len(active[later].clean())):
                    dropped.add(later)
        claimed_tracks: set[int] = set()
        for r_index, t_indices in claims.items():
            start, end = runs[r_index]
            keep = [index for index in t_indices if index not in dropped]
            shared = len(keep) > 1
            for t_index in keep:
                track = active[t_index]
                if shared:
                    low, high = track.predicted_interval(r)
                    half = (track.last_interval[1] - track.last_interval[0]) / 2
                    centre = (low + high) / 2
                    track.points.append((r, centre, 2 * half + 1, True))
                    track.last_interval = (centre - half, centre + half)
                else:
                    track.points.append((r, (start + end - 1) / 2, float(end - start), False))
                    track.last_interval = (float(start), float(end - 1))
                track.last_row = r
                track.misses = 0
                claimed_tracks.add(t_index)
        still = []
        for index, track in enumerate(active):
            if index in dropped:
                continue
            if index not in claimed_tracks:
                low, high = track.predicted_interval(r)
                if not masked(r, (low + high) / 2):
                    track.misses += 1
            (finished if track.misses > MAX_COAST_ROWS else still).append(track)
        active = still
        for r_index, (start, end) in enumerate(runs):
            if r_index not in claims:
                active.append(_Track(points=[(r, (start + end - 1) / 2, float(end - start), False)],
                                     last_interval=(float(start), float(end - 1)), last_row=r))
    return finished + active


def _fit_crossing(track: _Track, waterline: WaterlineTrace, band: int) -> Crossing | None:
    clean = track.clean()
    if len(clean) < 2 * MIN_ROWS_PER_SIDE:
        return None
    x_guess = float(np.median([p[1] for p in clean]))
    line_row = waterline.row_at(x_guess)
    near = [p for p in clean if abs(p[0] - line_row) <= band]
    above = sum(1 for r, _, _ in near if r < line_row)
    below = len(near) - above
    if above < MIN_ROWS_PER_SIDE or below < MIN_ROWS_PER_SIDE:
        return None
    rows = np.array([p[0] for p in near], dtype=float) - line_row
    centres = np.array([p[1] for p in near])
    degree = 2 if np.ptp(rows) >= 30 else 1
    coefficients = np.polyfit(rows, centres, degree)
    residual = float(np.sqrt(np.mean((np.polyval(coefficients, rows) - centres) ** 2)))
    # Intersect the fitted line with the (slightly skewed) waterline.
    offset = 0.0
    for _ in range(3):
        x = float(np.polyval(coefficients, offset))
        offset = waterline.row_at(x) - line_row
    x = float(np.polyval(coefficients, offset))
    slope = float(np.polyval(np.polyder(coefficients), offset))
    run_width = float(np.median([p[2] for p in near]))
    return Crossing(row=line_row + offset, x_px=x, slope=slope,
                    width_px=run_width / float(np.sqrt(1 + slope ** 2)), rows_above=above, rows_below=below,
                    fit_residual_px=residual)


def find_crossings(ink: np.ndarray, row: int, x_range: tuple[int, int], band: int = BAND_ROWS) -> list[Crossing]:
    """Every ink line that crosses the drawn waterline near image row `row` within columns x_range.

    Sorted by column. Kinds are not set here (all `curve`); see `classify`.
    """
    x_low, x_high = max(0, x_range[0]), min(ink.shape[1], x_range[1])
    waterline = locate_waterline(ink, row, (x_low, x_high))
    margin = waterline.half_thickness + WATERLINE_MARGIN_PX
    tracks = _track_band(ink, waterline, x_low, x_high, band, margin)
    crossings = [c for c in (_fit_crossing(t, waterline, band) for t in tracks) if c is not None]
    crossings = [c for c in crossings if x_low <= c.x_px < x_high]
    return sorted(crossings, key=lambda c: c.x_px)


def straight_ends(ink: np.ndarray, row: float, x_px: float, slope: float, step: int = 4,
                  max_gap_steps: int = 1) -> tuple[float, float, float]:
    """Columns of the two ends of the straight ink line through (row, x_px), and its straightness.

    Straightness is the largest distance (columns) of a found point from one line fitted to all.

    The line is followed in both directions; at each step the straight line fitted through all
    points found so far predicts the next column, and ink must lie within
    STRAIGHT_MAX_DEVIATION_PX columns of it. One missing sample (a scan break) is allowed.
    """
    height, width = ink.shape
    start_row = int(round(row))
    points = [(float(start_row), x_px + slope * (start_row - row))]
    ends, everything = [], []
    for direction in (-1, 1):
        misses = 0
        r = start_row
        line = (slope, points[0][1] - slope * start_row)
        reach_x = points[0][1]
        found = list(points)
        while True:
            r += direction * step
            x = line[0] * r + line[1]
            if not (0 <= r < height and 0 <= x < width):
                break
            low = max(0, int(np.floor(x - STRAIGHT_MAX_DEVIATION_PX)))
            high = min(width, int(np.ceil(x + STRAIGHT_MAX_DEVIATION_PX)) + 1)
            columns = np.flatnonzero(ink[r, low:high])
            if columns.size:
                misses = 0
                centre = low + float(np.mean(columns))
                found.append((float(r), centre))
                reach_x = centre
                if len(found) >= 3:
                    rows, xs = np.array(found).T
                    line = tuple(np.polyfit(rows, xs, 1))
            else:
                misses += 1
                if misses > max_gap_steps:
                    break
        ends.append(reach_x)
        everything.extend(found)
    rows, xs = np.array(everything).T
    deviation = float(np.max(np.abs(np.polyval(np.polyfit(rows, xs, 1), rows) - xs)))
    return ends[0], ends[1], deviation


def is_diagonal(ink: np.ndarray, crossing: Crossing, centre_column: float) -> bool:
    """A body-plan diagonal: an oblique straight line that runs to the centreline."""
    if not STRAIGHT_SLOPES[0] <= abs(crossing.slope) <= STRAIGHT_SLOPES[1]:
        return False
    *ends, deviation = straight_ends(ink, crossing.row, crossing.x_px, crossing.slope)
    length = abs(ends[1] - ends[0]) * float(np.sqrt(1 + crossing.slope ** -2))
    reaches_centre = min(abs(end - centre_column) for end in ends) <= DIAGONAL_CENTRE_REACH_PX
    return reaches_centre and length >= DIAGONAL_MIN_LENGTH_PX and deviation <= DIAGONAL_MAX_DEVIATION_PX


def typical_width(crossings: list[Crossing]) -> float:
    """The usual curve width: the median width of the crossings between 3.5 and 8 px wide."""
    widths = [c.width_px for c in crossings if 3.5 <= c.width_px <= 8.0]
    return float(np.median(widths)) if widths else 5.0


def is_post(ink: np.ndarray, crossing: Crossing, centre_column: float, waterline_spacing_px: float,
            max_offset_px: float) -> bool:
    """A stem or sternpost outline: a long, straight, near-vertical line in the inner part of the plan."""
    if abs(crossing.slope) >= POST_MAX_SLOPE:
        return False
    if abs(crossing.x_px - centre_column) > POST_INNER_FRACTION * max_offset_px:
        return False
    top, bottom, deviation = straight_line_rows(ink, crossing)
    return bottom - top >= POST_MIN_SPACINGS * waterline_spacing_px and deviation <= DIAGONAL_MAX_DEVIATION_PX


def straight_line_rows(ink: np.ndarray, crossing: Crossing, step: int = 4,
                       max_gap_steps: int = 1) -> tuple[float, float, float]:
    """First and last row of the near-vertical straight ink line through a crossing, and its straightness.

    Like `straight_ends`, but measured in rows (a vertical line has no extent in columns).
    """
    height, width = ink.shape
    start_row = int(round(crossing.row))
    found = [(float(start_row), crossing.x_px)]
    reach = []
    for direction in (-1, 1):
        r, misses = start_row, 0
        line = (crossing.slope, crossing.x_px - crossing.slope * crossing.row)
        last_row = float(start_row)
        while True:
            r += direction * step
            x = line[0] * r + line[1]
            if not (0 <= r < height and 0 <= x < width):
                break
            low = max(0, int(np.floor(x - STRAIGHT_MAX_DEVIATION_PX)))
            high = min(width, int(np.ceil(x + STRAIGHT_MAX_DEVIATION_PX)) + 1)
            columns = np.flatnonzero(ink[r, low:high])
            if not columns.size:
                misses += 1
                if misses > max_gap_steps:
                    break
                continue
            misses = 0
            found.append((float(r), low + float(np.mean(columns))))
            last_row = float(r)
            if len(found) >= 3:
                rows, xs = np.array(found).T
                line = tuple(np.polyfit(rows, xs, 1))
        reach.append(last_row)
    rows, xs = np.array(found).T
    deviation = float(np.max(np.abs(np.polyval(np.polyfit(rows, xs, 1), rows) - xs))) if len(found) >= 3 else 0.0
    return reach[0], reach[1], deviation


def is_short_stroke(ink: np.ndarray, crossing: Crossing, curve_width: float, waterline_spacing_px: float) -> bool:
    """A line that ends close above and close below its crossing (lettering or a short leader)."""
    distance = SHORT_STROKE_SPACINGS * waterline_spacing_px
    for target in (crossing.row - distance, crossing.row + distance):
        if follow_curve(ink, crossing, target, curve_width, stop_margin=0) is not None:
            return False
    return True


def classify(ink: np.ndarray, crossings: list[Crossing], curve_width: float, centre_column: float,
             grid_columns: tuple[float, ...] = (), waterline_spacing_px: float | None = None,
             max_offset_px: float | None = None) -> None:
    """Set each crossing's kind in place.

    grid_columns: known vertical grid lines (buttocks); a thin, vertical crossing on one is `grid`.
    waterline_spacing_px and max_offset_px (both or neither) turn on the shape rules for a stem or
    sternpost drawn away from the centreline and for short strokes (lettering, leader lines).
    """
    shape_rules = waterline_spacing_px is not None and max_offset_px is not None
    for crossing in crossings:
        ratio = crossing.width_px / curve_width
        on_grid = any(abs(crossing.x_px - column) <= 6 for column in grid_columns)
        if abs(crossing.x_px - centre_column) <= CENTRELINE_STRUCTURE_PX and abs(crossing.slope) < 0.03:
            crossing.kind, crossing.notes = KIND_GRID, ['vertical line at the centreline (stem or sternpost)']
        elif ratio <= GRID_MAX_WIDTH_RATIO or (on_grid and abs(crossing.slope) < 0.02 and ratio < 0.9):
            crossing.kind, crossing.notes = KIND_GRID, ['thin line' if not on_grid else 'on a grid column']
        elif on_grid and abs(crossing.slope) < 0.05:
            crossing.kind, crossing.notes = KIND_CURVE, ['on a grid column: a curve along the grid line?']
        elif shape_rules and is_post(ink, crossing, centre_column, waterline_spacing_px, max_offset_px):
            crossing.kind, crossing.notes = KIND_GRID, ['long straight vertical line (stem or sternpost)']
        elif ratio >= LETTERING_MIN_WIDTH_RATIO:
            crossing.kind, crossing.notes = KIND_LETTERING, [f'width {crossing.width_px:.1f} px']
        elif abs(crossing.slope) > SHALLOW_SLOPE:
            crossing.kind, crossing.notes = KIND_SHALLOW, [f'slope {crossing.slope:.1f} columns per row']
        elif is_diagonal(ink, crossing, centre_column):
            crossing.kind, crossing.notes = KIND_STRAIGHT, ['straight line to the centreline (diagonal)']
        elif shape_rules and is_short_stroke(ink, crossing, curve_width, waterline_spacing_px):
            crossing.kind, crossing.notes = KIND_LETTERING, ['short stroke (lettering or leader line)']
        elif ratio >= DOUBLE_MIN_WIDTH_RATIO:
            crossing.kind, crossing.notes = KIND_DOUBLE, [f'width {crossing.width_px:.1f} px, two curves?']
        else:
            crossing.kind = KIND_CURVE


def station_crossings(crossings: list[Crossing], centre_column: float, sign: int) -> list[Crossing]:
    """Station-curve candidates, outermost first (a `double` counts once here)."""
    kept = [c for c in crossings if c.kind in STATION_KINDS and c.offset_px(centre_column, sign) > 0]
    return sorted(kept, key=lambda c: -c.offset_px(centre_column, sign))


def follow_curve(ink: np.ndarray, crossing: Crossing, target_row: float, curve_width: float,
                 stop_margin: int = FOLLOW_STOP_MARGIN_ROWS, path: list | None = None) -> float | None:
    """Column where the curve through `crossing` reaches `target_row`, by following its ink.

    Row by row, the line fitted through the last FOLLOW_FIT_ROWS points found predicts the next
    column; the nearest ink run within reach continues the curve. A run much wider than the line
    (another line crosses or touches it here) is passed with the prediction. Following stops
    `stop_margin` rows short of the target (its waterline ink) and extrapolates. Returns None when
    the ink is lost. When `path` is a list, the (row, column) points found are appended to it.
    """
    direction = -1 if target_row < crossing.row else 1
    start = int(round(crossing.row)) + direction * FOLLOW_START_OFFSET_ROWS
    end = int(round(target_row)) - direction * stop_margin
    height, width = ink.shape
    points: list[tuple[float, float]] = [(crossing.row, crossing.x_px)]
    slope = crossing.slope
    misses = coasting = 0
    for r in range(start, end + direction, direction):
        if not 0 <= r < height:
            return None
        recent = points[-FOLLOW_FIT_ROWS:]
        if len(recent) >= 3 and np.ptp([p[0] for p in recent]) >= 2:
            slope, intercept = np.polyfit([p[0] for p in recent], [p[1] for p in recent], 1)
            predicted = slope * r + intercept
        else:
            predicted = points[-1][1] + slope * (r - points[-1][0])
        reach = 3.0 + 0.6 * abs(slope)
        expected_run = curve_width * float(np.sqrt(1 + slope ** 2))
        low = max(0, int(predicted - reach - 4 * expected_run))
        high = min(width, int(predicted + reach + 4 * expected_run) + 1)
        best = None
        for run_start, run_end in _merged_runs(ink[r, low:high], low):
            distance = max(0.0, run_start - predicted, predicted - (run_end - 1))
            if distance <= reach and (best is None or distance < best[0]):
                best = (distance, run_start, run_end)
        if best is None:
            misses += 1
            if misses > FOLLOW_MAX_MISSES:
                return None
            continue
        misses = 0
        _, run_start, run_end = best
        if run_end - run_start > FOLLOW_WIDE_RUN_RATIO * expected_run + 2:
            coasting += 1
            if coasting > FOLLOW_MAX_COAST_ROWS:
                return None
            points.append((float(r), float(predicted)))
            continue
        coasting = 0
        points.append((float(r), (run_start + run_end - 1) / 2))
        if path is not None:
            path.append(points[-1])
    recent = points[-FOLLOW_FIT_ROWS:]
    if len(recent) >= 3:
        slope, intercept = np.polyfit([p[0] for p in recent], [p[1] for p in recent], 1)
        return float(slope * target_row + intercept)
    return float(points[-1][1] + slope * (target_row - points[-1][0]))


def link_waterlines(lower: list[Crossing], upper: list[Crossing], ink: np.ndarray,
                    curve_width: float) -> list[tuple[int, int, float]]:
    """Links (lower index, upper index, error px) between station crossings of two waterlines.

    Both lists are outermost first. Each crossing is followed along its ink to the other
    waterline; it links to the crossing nearest to where it arrives, within LINK_TOLERANCE_PX.
    Two crossings may link to one (curves drawn on top of each other at one waterline). Links
    that would cross (break the nesting order) are removed, worst first.
    """
    links: dict[tuple[int, int], float] = {}

    def link_from(sources: list[Crossing], targets: list[Crossing], upward: bool) -> None:
        if not targets:
            return
        target_row = float(np.mean([t.row for t in targets]))
        for s_index, source in enumerate(sources):
            arrival = follow_curve(ink, source, target_row, curve_width)
            if arrival is None:
                continue
            errors = [(abs(arrival + t.slope * (t.row - target_row) - t.x_px), t_index)
                      for t_index, t in enumerate(targets)]
            error, t_index = min(errors)
            if error <= LINK_TOLERANCE_PX:
                key = (s_index, t_index) if upward else (t_index, s_index)
                links[key] = min(error, links.get(key, error))

    link_from(lower, upper, True)
    link_from(upper, lower, False)
    kept: list[tuple[int, int, float]] = []
    for (i, j), error in sorted(links.items(), key=lambda item: item[1]):
        if all((i - a) * (j - b) >= 0 for a, b, _ in kept):
            kept.append((i, j, error))
    return sorted(kept)
