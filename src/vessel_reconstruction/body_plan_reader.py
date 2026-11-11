"""Read a half-breadth table from a scanned body plan: code measures, a model only identifies.

Plan section 3.5.8. Code does all the measuring (`body_plan_crossings`): every ink crossing of
each waterline at full resolution, sorted into kinds, and the station-curve crossings of
neighbouring waterlines linked into chains by following each curve's ink. A chain is one drawn
station curve. The station number of each chain comes either from nesting order alone (code
only) or from a model's answer to one small visual question per chain ("which station number
labels the red curve?", see `body_plan_identity`). The half-breadth values are always the
code-measured columns; the model never places a line.

Fairness checks (monotone nesting, smoothness along the height and along the length) flag cells
for a person or for a second question.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from functools import cmp_to_key

import numpy as np

from vessel_reconstruction import body_plan_crossings as bpc

# A chain's path is followed past its last waterline crossing by at most this many rows, so that a
# station label drawn above or below the waterlines lies on the highlighted curve.
PATH_EXTENSION_ROWS = 1200
# The reader's search on each half starts this many columns out from the centreline.
CENTRE_CLEARANCE_PX = 10
# Fairness: largest second difference of a station's half-breadth over three waterlines, and
# largest departure of a cell from the mean of its two neighbouring stations, in metres. A bilge
# turn or a stern counter bends by up to about 0.9 m between waterlines 4 ft apart (1.2 m), so
# these flag only bends larger than a hull makes there; they are a prompt to look, not a gate.
HEIGHT_SMOOTHNESS_M = 1.0
LENGTH_SMOOTHNESS_M = 0.60
# A chain that crosses only one waterline is a station candidate only when its drawn curve spans at
# least this many waterline spacings in height. A station that crosses one waterline (near the
# stem, under the counter) runs on to the keel or the sheer; the rail, bulwark and deck lines above
# the top waterline are low, nearly level curves.
ONE_WATERLINE_MIN_SPACINGS = 1.0


@dataclass(frozen=True)
class SideLayout:
    """One half of the body plan."""

    name: str
    sign: int  # +1 when this half is drawn at larger columns than the centreline
    stations_outer_first: tuple[int, ...]  # nesting order at a waterline, outermost first
    grid_columns: tuple[float, ...] = ()  # vertical grid lines (buttocks) of this half


@dataclass(frozen=True)
class SheetLayout:
    """The host calibration of one body-plan sheet (a person confirms it once per sheet)."""

    centre_column: float
    pixels_per_metre: float
    waterline_rows: dict  # waterline label -> nominal image row, any order
    max_offset_px: int  # how far out from the centreline the station curves can lie
    sides: tuple[SideLayout, ...]

    def waterlines_low_to_high(self) -> list:
        return sorted(self.waterline_rows, key=lambda label: -self.waterline_rows[label])


@dataclass
class Chain:
    """One drawn curve: its crossing index at each waterline it crosses."""

    side: str
    nodes: dict  # waterline label -> index into that waterline's station list
    inferred_links: int = 0
    path: list = field(default_factory=list)  # (row, column) points along the curve, for display


@dataclass
class SideReading:
    layout: SideLayout
    crossings: dict  # waterline -> every crossing (all kinds)
    stations: dict  # waterline -> station-kind crossings, outermost first
    links: dict  # (lower waterline, upper waterline) -> [(lower index, upper index, error px or None)]
    chains: list  # Chain, outermost first
    waterline_spacing_px: float = 0.0


# ---------------------------------------------------------------- measuring

def measure_side(ink: np.ndarray, sheet: SheetLayout, side: SideLayout,
                 curve_width: float | None = None) -> SideReading:
    """Crossings, links and chains of one half of the body plan (code only).

    The pixel thresholds follow the drawn stroke width (`side_threshold_scale`): a first pass at
    the tuned thresholds measures the stroke; the crossings are measured again only when the
    scale is not 1.0.
    """
    centre = sheet.centre_column
    waterlines = sheet.waterlines_low_to_high()
    crossings = _find_side_crossings(ink, sheet, side, 1.0)
    scale = bpc.threshold_scale(bpc.stroke_width_px([c for found in crossings.values() for c in found]))
    if scale != 1.0:
        crossings = _find_side_crossings(ink, sheet, side, scale)
    if curve_width is None:
        curve_width = bpc.typical_width([c for found in crossings.values() for c in found], scale)
    spacing = waterline_spacing(sheet)
    for found in crossings.values():
        bpc.classify(ink, found, curve_width, centre, grid_columns=side.grid_columns,
                     waterline_spacing_px=spacing, max_offset_px=sheet.max_offset_px, scale=scale)
    stations = {w: bpc.station_crossings(crossings[w], centre, side.sign) for w in waterlines}
    links = {}
    for lower, upper in zip(waterlines, waterlines[1:]):
        found = bpc.link_waterlines(stations[lower], stations[upper], ink, curve_width, scale)
        links[(lower, upper)] = infer_enclosed_links(found, stations[lower], stations[upper])
    chains = build_chains(side.name, waterlines, stations, links)
    chains = order_chains(chains, stations, centre, side.sign)
    for chain in chains:
        chain.path = chain_path(ink, chain, stations, waterlines, curve_width, scale)
    return SideReading(side, crossings, stations, links, chains, spacing)


def _find_side_crossings(ink: np.ndarray, sheet: SheetLayout, side: SideLayout, scale: float) -> dict:
    """Every crossing at each waterline of one half, with the pixel thresholds at `scale`."""
    centre = sheet.centre_column
    clearance = bpc.scaled_pixels(CENTRE_CLEARANCE_PX, scale)
    span = sorted((int(centre + side.sign * clearance), int(centre + side.sign * sheet.max_offset_px)))
    return {w: bpc.find_crossings(ink, sheet.waterline_rows[w], (span[0], span[1]), scale=scale)
            for w in sheet.waterlines_low_to_high()}


def side_stroke_width(reading: SideReading) -> float | None:
    """The drawn stroke width (px) of one measured half (see `body_plan_crossings.stroke_width_px`)."""
    return bpc.stroke_width_px([c for found in reading.crossings.values() for c in found])


def waterline_spacing(sheet: SheetLayout) -> float:
    """Median row distance between neighbouring waterlines (the sheet's own length scale)."""
    rows = sorted(sheet.waterline_rows.values())
    return float(np.median(np.diff(rows))) if len(rows) >= 2 else float(bpc.BAND_ROWS * 8)


def infer_enclosed_links(links: list, lower: list, upper: list) -> list:
    """Add links for unlinked crossings enclosed by two links (the follower lost their ink).

    Between two links (a, b) and (c, d) the curves cannot cross. If every crossing between them is
    unlinked and both waterlines have the same number there, they pair in order. If the lower
    waterline has crossings there but the upper has none, each joins the nearer of b and d by its
    slope (two curves drawn together at the upper waterline); the same holds downwards. Inferred
    links carry the error None.
    """
    linked_lower = {i for i, _, _ in links}
    linked_upper = {j for _, j, _ in links}
    inferred = []

    def nearer(source: bpc.Crossing, first: bpc.Crossing, second: bpc.Crossing) -> int:
        arrive_first = source.x_px + source.slope * (first.row - source.row)
        arrive_second = source.x_px + source.slope * (second.row - source.row)
        return 0 if abs(arrive_first - first.x_px) <= abs(arrive_second - second.x_px) else 1

    ordered = sorted(links)
    for (a, b, _), (c, d, _) in zip(ordered, ordered[1:]):
        free_lower = [i for i in range(a + 1, c) if i not in linked_lower]
        free_upper = [j for j in range(b + 1, d) if j not in linked_upper]
        if len(free_lower) != c - a - 1 or len(free_upper) != d - b - 1:
            continue
        if free_lower and len(free_lower) == len(free_upper):
            inferred.extend((i, j, None) for i, j in zip(free_lower, free_upper))
        elif free_lower and not free_upper:
            inferred.extend((i, (b, d)[nearer(lower[i], upper[b], upper[d])], None) for i in free_lower)
        elif free_upper and not free_lower:
            inferred.extend(((a, c)[nearer(upper[j], lower[a], lower[c])], j, None) for j in free_upper)
    return sorted(links + inferred)


def build_chains(side: str, waterlines: list, stations: dict, links: dict) -> list[Chain]:
    """Chains of linked crossings, swept from the lowest waterline up.

    A chain starts at every crossing with no link from below. The chains at one crossing (two
    or more curves drawn together there) leave it, outermost first, along its links above in
    order; if there are more chains than links, the inner chains share the innermost link (they
    stay drawn together); if there are more links than chains, the innermost chain forks (a curve
    that was hidden below appears).
    """
    outgoing: dict = {}
    has_incoming: set = set()
    inferred: set = set()
    for (lower, upper), found in links.items():
        for i, j, error in found:
            outgoing.setdefault((lower, i), []).append(j)
            has_incoming.add((upper, j))
            if error is None:
                inferred.add((lower, i, upper, j))
    finished: list[Chain] = []
    active: list[Chain] = []  # chains that reach the current waterline
    for level, w in enumerate(waterlines):
        for index in range(len(stations[w])):
            if (w, index) not in has_incoming:
                active.append(Chain(side, {w: index}))
        if level + 1 == len(waterlines):
            finished.extend(active)
            break
        upper = waterlines[level + 1]
        at_node: dict = {}
        for chain in active:
            at_node.setdefault(chain.nodes[w], []).append(chain)
        moved: list[Chain] = []
        for index, chains in sorted(at_node.items()):
            targets = sorted(outgoing.get((w, index), []))
            if not targets:
                finished.extend(chains)
                continue
            chains.sort(key=lambda chain: _history_key(chain, waterlines[:level + 1]))
            if len(targets) > len(chains):
                last = chains[-1]
                chains = chains + [Chain(side, dict(last.nodes), last.inferred_links)
                                   for _ in range(len(targets) - len(chains))]
            for position, chain in enumerate(chains):
                target = targets[min(position, len(targets) - 1)]
                chain.nodes[upper] = target
                chain.inferred_links += (w, index, upper, target) in inferred
                moved.append(chain)
        active = moved
    return finished


def _history_key(chain: Chain, waterlines_so_far: list) -> tuple:
    """Sort key for chains that meet at one crossing: their crossing indices below, nearest first."""
    return tuple(chain.nodes.get(w, -1) for w in reversed(waterlines_so_far))


def order_chains(chains: list[Chain], stations: dict, centre_column: float, sign: int) -> list[Chain]:
    """Chains outermost first.

    Two chains that share a waterline compare by crossing index there (the first waterline where
    they differ, from the bottom); otherwise by their mean offset from the centreline.
    """
    def mean_offset(chain: Chain) -> float:
        return float(np.mean([stations[w][i].offset_px(centre_column, sign) for w, i in chain.nodes.items()]))

    def compare(first: Chain, second: Chain) -> int:
        shared = sorted(set(first.nodes) & set(second.nodes), key=lambda w: stations[w][0].row, reverse=True)
        for w in shared:
            if first.nodes[w] != second.nodes[w]:
                return -1 if first.nodes[w] < second.nodes[w] else 1
        difference = mean_offset(second) - mean_offset(first)
        return -1 if difference < 0 else (1 if difference > 0 else 0)

    return sorted(chains, key=cmp_to_key(compare))


def chain_path(ink: np.ndarray, chain: Chain, stations: dict, waterlines: list, curve_width: float,
               scale: float = 1.0) -> list:
    """Points along the drawn curve of a chain, from below its lowest crossing to above its highest."""
    ordered = [w for w in waterlines if w in chain.nodes]
    lowest, highest = stations[ordered[0]][chain.nodes[ordered[0]]], stations[ordered[-1]][chain.nodes[ordered[-1]]]
    extension = bpc.scaled_pixels(PATH_EXTENSION_ROWS, scale)
    path: list = []
    bpc.follow_curve(ink, lowest, lowest.row + extension, curve_width, stop_margin=0, path=path, scale=scale)
    path.reverse()
    for lower, upper in zip(ordered, ordered[1:]):
        start = stations[lower][chain.nodes[lower]]
        end = stations[upper][chain.nodes[upper]]
        path.append((start.row, start.x_px))
        bpc.follow_curve(ink, start, end.row, curve_width, path=path, scale=scale)
    path.append((highest.row, highest.x_px))
    bpc.follow_curve(ink, highest, highest.row - extension, curve_width, stop_margin=0, path=path, scale=scale)
    return path


# ---------------------------------------------------------------- identity and table

def rows_spanned(chain: Chain) -> float:
    """Height (rows) of a chain's drawn curve, from its path."""
    rows = [point[0] for point in chain.path]
    return float(max(rows) - min(rows)) if rows else 0.0


def station_candidates(reading: SideReading) -> list[int]:
    """Indices of the chains that may be station curves, outermost first.

    Every chain that crosses two or more waterlines; a one-waterline chain only when its drawn
    curve is tall enough (ONE_WATERLINE_MIN_SPACINGS), so that rail, bulwark and deck lines are
    not asked about. Code-only numbering still leaves all one-waterline chains out.
    """
    minimum = ONE_WATERLINE_MIN_SPACINGS * reading.waterline_spacing_px
    return [index for index, chain in enumerate(reading.chains)
            if len(chain.nodes) >= 2 or rows_spanned(chain) >= minimum]


def identities_by_rank(chains: list[Chain], stations_outer_first: tuple[int, ...]) -> dict[int, int]:
    """Code-only identity: chain index -> station, by nesting order (the outermost chain is the
    first station). A chain that crosses only one waterline is not counted as a station curve (an
    edge or construction line that the links could not tie to a neighbour)."""
    kept = [index for index, chain in enumerate(chains) if len(chain.nodes) >= 2]
    return {index: station for index, station in zip(kept, stations_outer_first)}


def table_from_identities(reading: SideReading, identities: dict[int, int], pixels_per_metre: float,
                          centre_column: float) -> dict:
    """{(station, waterline): half-breadth m} from code-measured crossings and chain identities.

    Two chains given one station (should not happen) keep the outer value.
    """
    table = {}
    for chain_index, station in sorted(identities.items(), reverse=True):
        chain = reading.chains[chain_index]
        for w, i in chain.nodes.items():
            crossing = reading.stations[w][i]
            table[(station, w)] = crossing.offset_px(centre_column, reading.layout.sign) / pixels_per_metre
    return table


def fairness_flags(table: dict, stations_outer_first: tuple[int, ...], waterlines_low_to_high: list) -> list[dict]:
    """Cells that break nesting or smoothness, for a second look.

    nesting: at a waterline, a station lies outside the station before it in nesting order;
    height: a station's half-breadth bends sharply between three waterlines;
    length: a cell departs from the mean of its two neighbouring stations.
    """
    flags = []
    for w in waterlines_low_to_high:
        values = [(s, table[(s, w)]) for s in stations_outer_first if (s, w) in table]
        for (outer, outer_value), (inner, inner_value) in zip(values, values[1:]):
            if inner_value > outer_value + 1e-6:
                flags.append({'check': 'nesting', 'station': inner, 'waterline': w,
                              'detail': f'outside station {outer} by {inner_value - outer_value:.3f} m'})
        for (_, before), (station, value), (_, after) in zip(values, values[1:], values[2:]):
            departure = value - (before + after) / 2
            if abs(departure) > LENGTH_SMOOTHNESS_M:
                flags.append({'check': 'length', 'station': station, 'waterline': w,
                              'detail': f'{departure:+.3f} m from the mean of its neighbours'})
    for s in stations_outer_first:
        values = [(w, table[(s, w)]) for w in waterlines_low_to_high if (s, w) in table]
        for (_, below), (w, value), (_, above) in zip(values, values[1:], values[2:]):
            bend = below - 2 * value + above
            if abs(bend) > HEIGHT_SMOOTHNESS_M:
                flags.append({'check': 'height', 'station': s, 'waterline': w,
                              'detail': f'second difference {bend:+.3f} m'})
    return flags
