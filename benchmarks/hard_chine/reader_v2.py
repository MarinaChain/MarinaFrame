"""Hard-chine body-plan reader, version 2: station pieces below the drawn chine line.

The frozen reader (`body_plan_reader`) keeps only chains that cross two or more waterlines. On a
hard-chine hull the pieces below the chine are short: many cross a single waterline, so the
frozen reader drops them, and the long pieces that it keeps take station numbers by nesting
rank, which shifts the numbers of the stations that follow. This module reuses the frozen
measurement and the chine-line finder and then:

1. checks that the traced line is a chine (a flat waterline or a diagonal also looks like a
   heavy shallow stroke), and finds the part of it that is the chine: not where it runs on along
   a drawn waterline or out along a label leader (`chine_columns`);
2. names the stations from the pieces ABOVE the line, ranked by nesting at one waterline, and
   gives each station its chine point;
3. re-traces every crossing BELOW the line locally, up its own ink to the line, and names it
   after the chine point where it arrives. A crossing whose arrival is not clearly nearest to
   one chine point, or whose cell more than one crossing claims, is left out (listed in the
   result as abstained); the module never picks a branch by looking at a neighbouring value.

It reads the ink mask, the host calibration and the frozen measurement only. No truth, vessel
names or benchmark constants. A side without a verified chine line keeps the frozen reader's
rank identities, so a round-bilge sheet gives the frozen result unchanged.

The frozen modules (`body_plan_crossings`, `body_plan_reader`, `body_plan_identity`) are not
edited; they are pinned by hash in the holdout tests.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from benchmarks.hard_chine import chine_line as chine_line
from vessel_reconstruction import body_plan_crossings as bpc
from vessel_reconstruction import body_plan_reader as bpr

# A chine point and the arrival of a re-traced lower piece must lie within this share of a
# waterline spacing (about 30 px on a 300 px spacing) to be the same point.
MATCH_SPACING_SHARE = 0.10
# The nearest chine point must be at least this many times nearer than the next one.
MATCH_CLEARANCE = 2.0
# A lower piece is re-traced this share of a waterline spacing beyond the line, so that a piece
# that reaches the line is seen to cross it.
OVERSHOOT_SPACING_SHARE = 0.25
# A piece below the line needs this many measured crossings above the line to name a station.
MIN_UPPER_CROSSINGS = 2
# A crossing on the line whose direction is within this many degrees of the line's own direction
# is the line itself crossing the waterline, not a station curve.
PARALLEL_DEGREES = 10.0
# The line is a flat waterline (not a chine) when most of it lies within this many curve widths
# of a drawn waterline row.
WATERLINE_BAND_WIDTHS = 2.0
WATERLINE_SHARE = 0.5
# A drawn waterline (a measuring row or not, such as a painted waterline) is a straight horizontal
# ink run at least LONG_RUN_SHARE of the half's reach long. A chine is curved: it crosses such a
# line over a short stretch, but never runs along one for ALONG_SHARE of the reach.
LONG_RUN_SHARE = 0.5
ALONG_SHARE = 0.1
# A label leader runs out beyond the hull: line points more than this many curve widths beyond the
# outermost measured station crossing of the half are not the chine.
BEYOND_HULL_WIDTHS = 2.0


@dataclass
class ChinePoint:
    """Where the pieces of one station meet the chine line (image pixels)."""

    station: int
    row: float
    column: float
    chains: list[int]


@dataclass
class Claim:
    """One measured crossing named for a station cell, and how it was named."""

    waterline: str
    index: int  # index into reading.stations[waterline]
    source: str  # 'upper' (a chain above the line) or 'lower' (re-traced to the line)


@dataclass
class SideReadingV2:
    """The frozen reading of a side plus the chine-based station naming."""

    base: bpr.SideReading
    line: chine_line.ChineLine | None
    verified: bool
    identities: dict  # frozen rank identities, used when no chine line is verified
    chine_points: list[ChinePoint] = field(default_factory=list)
    # Column range of the line that is the chine (`chine_columns`); None: all of it.
    columns: tuple | None = None
    cells: dict = field(default_factory=dict)  # (station, waterline) -> Claim
    abstained: list = field(default_factory=list)  # {'waterline', 'index', 'reason', ...}
    notes: list = field(default_factory=list)

    @property
    def uses_chine(self) -> bool:
        return self.line is not None and self.verified


# ---------------------------------------------------------------- chine line checks

def _line_row(line: chine_line.ChineLine, column: float) -> float:
    return float(np.interp(column, line.points[:, 1], line.points[:, 0], left=np.nan, right=np.nan))


def lies_on_waterline(line: chine_line.ChineLine, sheet: bpr.SheetLayout) -> bool:
    """True when the traced stroke follows a drawn waterline rather than a chine."""
    rows = np.array(list(sheet.waterline_rows.values()), dtype=float)
    band = WATERLINE_BAND_WIDTHS * line.thickness_px + 3.0
    distance = np.min(np.abs(line.points[:, 0][:, None] - rows[None, :]), axis=1)
    return float(np.mean(distance <= band)) > WATERLINE_SHARE


def _horizontal_run(ink: np.ndarray, row: float, column: float) -> int:
    """Length of the longest horizontal ink run through (row +- 1, column)."""
    longest = 0
    for r in (int(round(row)) - 1, int(round(row)), int(round(row)) + 1):
        c = int(round(column))
        if not (0 <= r < ink.shape[0] and 0 <= c < ink.shape[1]) or not ink[r, c]:
            continue
        values = ink[r]
        left = c
        while left > 0 and (values[left - 1] or (left > 2 and values[left - 2])):
            left -= 1
        right = c
        while right < len(values) - 1 and (values[right + 1] or (right < len(values) - 2 and values[right + 2])):
            right += 1
        longest = max(longest, right - left + 1)
    return longest


def chine_columns(ink: np.ndarray, line: chine_line.ChineLine, sheet: bpr.SheetLayout,
                  reading: bpr.SideReading) -> tuple[float, float] | None:
    """(first, last) column of the part of the line that is the chine, or None when too little is.

    The finder traces a heavy shallow stroke and may run on from the chine onto a horizontal drawn
    line (a waterline, including a painted one that is not a measuring row) or out beyond the hull
    along a label leader. Those points are not the chine; the longest remaining stretch is. It must
    still span MIN_SPAN_SHARE of the half's reach, or the line is not a chine (None).
    """
    sign = reading.layout.sign
    crossings = [c for found in reading.stations.values() for c in found]
    outermost = max((c.offset_px(sheet.centre_column, sign) for c in crossings), default=sheet.max_offset_px)
    long_run = LONG_RUN_SHARE * sheet.max_offset_px
    beyond = outermost + BEYOND_HULL_WIDTHS * line.thickness_px
    on_long_run = np.array([_horizontal_run(ink, row, column) >= long_run for row, column in line.points])
    along = np.zeros(len(on_long_run), dtype=bool)
    start = None
    for index, marked in enumerate(np.append(on_long_run, False)):
        if marked and start is None:
            start = index
        elif not marked and start is not None:
            if np.ptp(line.points[start:index, 1]) >= ALONG_SHARE * sheet.max_offset_px:
                along[start:index] = True
            start = None
    inside = np.array([sign * (column - sheet.centre_column) <= beyond for _, column in line.points])
    keep = ~along & inside
    if keep.all():
        return float(line.points[0, 1]), float(line.points[-1, 1])
    best, start = (0, 0), None
    for index, kept in enumerate(np.append(keep, False)):
        if kept and start is None:
            start = index
        elif not kept and start is not None:
            if index - start > best[1] - best[0]:
                best = (start, index)
            start = None
    points = line.points[best[0]:best[1]]
    if len(points) < 2 or np.ptp(points[:, 1]) < chine_line.MIN_SPAN_SHARE * sheet.max_offset_px:
        return None
    return float(points[0, 1]), float(points[-1, 1])


# ---------------------------------------------------------------- upper pieces

@dataclass
class _UpperGroup:
    chains: list[int]
    top: tuple  # (waterline, index) of the highest crossing
    above: dict  # waterline -> {indices} of measured crossings above the line


def _above_line(crossing: bpc.Crossing, line: chine_line.ChineLine) -> bool:
    row = _line_row(line, crossing.x_px)
    return not np.isnan(row) and crossing.row < row - chine_line.SIDE_MARGIN_PX


def _upper_groups(reading: bpr.SideReading, line: chine_line.ChineLine, meetings: dict,
                  waterlines_high_to_low: list) -> list[_UpperGroup]:
    """Station curves above the line: chains that reach it, merged when they share a top crossing.

    The frozen builder forks one drawn curve into several chains where two links meet one
    crossing; chains that share the same highest crossing are one curve above the line.
    """
    by_top: dict = {}
    for index, chain in enumerate(reading.chains):
        if index not in meetings:
            continue
        above = {}
        for waterline, node in chain.nodes.items():
            if _above_line(reading.stations[waterline][node], line):
                above.setdefault(waterline, set()).add(node)
        if sum(len(nodes) for nodes in above.values()) < MIN_UPPER_CROSSINGS:
            continue
        top_waterline = next(w for w in waterlines_high_to_low if w in above)
        top = (top_waterline, chain.nodes[top_waterline])
        group = by_top.setdefault(top, _UpperGroup([], top, {}))
        group.chains.append(index)
        for waterline, nodes in above.items():
            group.above.setdefault(waterline, set()).update(nodes)
    return list(by_top.values())


def _order_groups(groups: list[_UpperGroup], reading: bpr.SideReading,
                  centre_column: float) -> list[_UpperGroup]:
    """Outermost first, by nesting at one waterline that all groups cross; otherwise frozen order.

    The frozen chain order compares chains by shared waterlines pair by pair and can place a
    chain out of nesting order; the offset at a single common waterline cannot.
    """
    if not groups:
        return groups
    common = set.intersection(*(set(group.above) for group in groups))
    if common:
        reference = max(common, key=lambda w: -reading.stations[w][0].row)  # highest waterline
        def offset(group: _UpperGroup) -> float:
            nodes = group.above[reference]
            return min(reading.stations[reference][n].offset_px(centre_column, reading.layout.sign)
                       for n in nodes)
        return sorted(groups, key=lambda group: -offset(group))
    return sorted(groups, key=lambda group: min(group.chains))


# ---------------------------------------------------------------- lower pieces

def _is_the_line_itself(crossing: bpc.Crossing, line: chine_line.ChineLine) -> bool:
    """A crossing on the line, running along it: the heavy line crossing the waterline."""
    row = _line_row(line, crossing.x_px)
    if np.isnan(row) or abs(crossing.row - row) > chine_line.SIDE_MARGIN_PX:
        return False
    columns = line.points[:, 1]
    near = np.abs(columns - crossing.x_px) <= 30
    if near.sum() < 3:
        return False
    line_rows_per_column = np.polyfit(columns[near], line.points[near, 0], 1)[0]
    line_angle = np.degrees(np.arctan2(line_rows_per_column, 1.0))  # from the column axis
    curve_angle = np.degrees(np.arctan2(1.0, crossing.slope))  # slope is columns per row
    difference = abs((curve_angle - line_angle + 90.0) % 180.0 - 90.0)
    return difference <= PARALLEL_DEGREES


def retrace_to_line(ink: np.ndarray, crossing: bpc.Crossing, line: chine_line.ChineLine,
                    curve_width: float, spacing: float) -> tuple[float, float] | None:
    """(row, column) where the curve through `crossing` first reaches the line, following its ink."""
    start_row = _line_row(line, crossing.x_px)
    if np.isnan(start_row):
        return None
    path: list = []
    bpc.follow_curve(ink, crossing, start_row - OVERSHOOT_SPACING_SHARE * spacing, curve_width,
                     stop_margin=0, path=path)
    if not path:
        return None
    points = np.asarray(path, dtype=float)
    offsets = points[:, 0] - np.array([_line_row(line, column) for column in points[:, 1]])
    reached = np.nonzero(offsets <= chine_line.SIDE_MARGIN_PX)[0]
    if not len(reached):
        return None
    row, column = points[reached[0]]
    return float(row), float(column)


def match_chine_point(arrival: tuple[float, float], points: list[ChinePoint],
                      spacing: float) -> ChinePoint | None:
    """The chine point clearly nearest to `arrival`, within MATCH_SPACING_SHARE of a spacing."""
    if not points:
        return None
    distances = sorted((float(np.hypot(arrival[0] - p.row, arrival[1] - p.column)), i)
                       for i, p in enumerate(points))
    nearest, index = distances[0]
    if nearest > MATCH_SPACING_SHARE * spacing:
        return None
    if len(distances) > 1 and distances[1][0] < MATCH_CLEARANCE * max(nearest, 1.0):
        return None
    return points[index]


# ---------------------------------------------------------------- the side reading

def read_side(ink: np.ndarray, sheet: bpr.SheetLayout, reading: bpr.SideReading,
              line: chine_line.ChineLine | None, verified: bool,
              columns: tuple | None = None) -> SideReadingV2:
    """Name the stations of one side from the frozen reading and its chine line.

    A station whose pieces meet the line outside `columns` (where the line runs along a waterline
    or a leader) keeps its upper cells but has no chine point, so no lower piece is named by it.
    """
    identities = bpr.identities_by_rank(reading.chains, reading.layout.stations_outer_first)
    result = SideReadingV2(reading, line, verified, identities, columns=columns)
    if line is None or not verified:
        return result
    spacing = reading.waterline_spacing_px
    curve_width = bpc.typical_width([c for found in reading.crossings.values() for c in found])
    waterlines = sheet.waterlines_low_to_high()
    meetings = {m.chain: m for m in chine_line.station_meetings(line.points, reading,
                                                                chine_line.EXTRAPOLATION_SPACINGS * spacing)}
    groups = _order_groups(_upper_groups(reading, line, meetings, waterlines[::-1]), reading,
                           sheet.centre_column)
    stations = reading.layout.stations_outer_first
    claims: dict = {}

    def claim(station: int, waterline: str, index: int, source: str) -> None:
        claims.setdefault((station, waterline), {}).setdefault(index, source)

    for group, station in zip(groups, stations):
        member_meetings = [meetings[c] for c in group.chains]
        point = ChinePoint(station, float(np.median([m.row for m in member_meetings])),
                           float(np.median([m.column for m in member_meetings])), list(group.chains))
        if columns is None or min(columns) <= point.column <= max(columns):
            result.chine_points.append(point)
        else:
            result.notes.append(f'station {station} meets the line where it is not the chine; no chine point')
        for waterline, nodes in group.above.items():
            for node in nodes:
                claim(station, waterline, node, 'upper')
    if len(groups) < len(stations):
        result.notes.append(f'{len(groups)} upper pieces for {len(stations)} stations')
    for waterline in waterlines:
        for index, crossing in enumerate(reading.stations[waterline]):
            if _above_line(crossing, line):
                continue
            where = {'waterline': waterline, 'index': index, 'column': crossing.x_px}
            if _is_the_line_itself(crossing, line):
                result.abstained.append(dict(where, reason='the chine line itself'))
                continue
            arrival = retrace_to_line(ink, crossing, line, curve_width, spacing)
            if arrival is None:
                result.abstained.append(dict(where, reason='ink does not reach the line'))
                continue
            point = match_chine_point(arrival, result.chine_points, spacing)
            if point is None:
                result.abstained.append(dict(where, reason='no single nearest chine point',
                                             arrival=[arrival[0], arrival[1]]))
                continue
            claim(point.station, waterline, index, 'lower')
    for (station, waterline), found in sorted(claims.items()):
        if len(found) == 1:
            ((index, source),) = found.items()
            result.cells[(station, waterline)] = Claim(waterline, index, source)
        else:
            result.abstained.append({'station': station, 'waterline': waterline,
                                     'indices': sorted(found), 'reason': 'more than one crossing for the cell'})
    return result


def read_sheet(ink: np.ndarray, sheet: bpr.SheetLayout,
               readings: dict[str, bpr.SideReading] | None = None) -> dict[str, SideReadingV2]:
    """Both halves of a sheet; a half takes the chine reading when its traced line is not a waterline."""
    if readings is None:
        readings = {side.name: bpr.measure_side(ink, sheet, side) for side in sheet.sides}
    lines, columns = {}, {}
    for name, reading in readings.items():
        stations = [c for found in reading.stations.values() for c in found]
        line = chine_line.find_chine_line(ink, sheet, reading) if stations else None
        if line is not None and lies_on_waterline(line, sheet):
            line = None
        columns[name] = None if line is None else chine_columns(ink, line, sheet, reading)
        lines[name] = None if columns[name] is None else line
    hard_chine = any(line is not None for line in lines.values())
    return {name: read_side(ink, sheet, reading, lines[name], hard_chine and lines[name] is not None, columns[name])
            for name, reading in readings.items()}


# ---------------------------------------------------------------- table

def side_table(side: SideReadingV2, pixels_per_metre: float, centre_column: float) -> dict:
    """{(station, waterline): half-breadth m}. Without a verified chine line this is the frozen table."""
    if not side.uses_chine:
        return bpr.table_from_identities(side.base, side.identities, pixels_per_metre, centre_column)
    sign = side.base.layout.sign
    return {key: side.base.stations[claim.waterline][claim.index].offset_px(centre_column, sign) / pixels_per_metre
            for key, claim in side.cells.items()}


def sheet_table(readings: dict[str, SideReadingV2], sheet: bpr.SheetLayout) -> tuple[dict, list]:
    """Table and fairness flags of both halves (the flags are the frozen reader's own checks)."""
    table, flags = {}, []
    for name, side in readings.items():
        part = side_table(side, sheet.pixels_per_metre, sheet.centre_column)
        flags += [dict(flag, side=name) for flag in bpr.fairness_flags(
            part, side.base.layout.stations_outer_first, sheet.waterlines_low_to_high())]
        table.update(part)
    return table, flags
