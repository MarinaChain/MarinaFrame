"""Automatic calibration of a scanned body-plan sheet for the frozen body-plan reader.

Plan: docs/AUTO_CALIBRATION.md. Code does the geometry: straight grid lines, the centreline (the
symmetry axis of the vertical grid), the baseline and waterline rows, buttock offsets, scale-bar
ticks and the reader's search half-span. A model only reads printed labels and numbers, through a
`reading` object (see `calibration_reading`): the station numbers in each half, the height labels
of numbered lines, buttock offsets or spacings, the scale text and scale-bar values, and two
independent side checks. Every value carries a source label. Two scale measures must agree and the
two side checks must agree; otherwise the calibration is flagged for a person, never silently
accepted. A flagged calibration still gives a provisional layout, so that the person sees it.

The reader modules (`body_plan_reader`, `body_plan_crossings`, `body_plan_identity`) are frozen;
this module only builds their `SheetLayout` and calls them.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from fractions import Fraction

import numpy as np

from vessel_reconstruction import body_plan_reader as bpr

FEET_M = 0.3048
# A straight grid line covers at least this share of the body-plan box along its length.
LINE_MIN_FILL = 0.2
# A frame line (sheet or view border) covers almost all of the box; grid lines inside a framed
# grid may too, so this only separates frames when other lines are lighter.
FRAME_MIN_FILL = 0.98
# A grid symmetry axis that contradicts the tagged centreline needs this many mirrored pairs (a
# grid drawn on one half only mirrors about its own middle).
MIN_AXIS_PAIRS = 3
# Mirror tolerance of a vertical grid line about the centreline: px, or a share of its offset.
SYMMETRY_TOL_PX = 4.0
SYMMETRY_TOL_SHARE = 0.004
# Vertical lines closer than this share of the box width to the centreline are keel or post
# structure, not buttocks.
GRID_MIN_OFFSET_SHARE = 0.02
# Two scale measures agree when they differ by at most this share.
SCALE_AGREEMENT = 0.01
# Margin outside the outermost station crossing for the reader's search half-span (px); the hand
# calibrations used 70 to 160 px.
MAX_OFFSET_MARGIN_PX = 120
# A waterline row lies on a drawn horizontal line within this many rows (the reader searches as far).
SNAP_ROWS = 20
# Gaps of a dashed or dash-dot line, in rows.
DASH_GAP_ROWS = 40
# Rows below the baseline where the centreline's own ink may stop (dash-dot lines have gaps).
CENTRELINE_END_TOLERANCE_ROWS = 40
# A labelled height fit needs this many labelled lines to set the baseline by itself.
MIN_LABELLED_FOR_FIT = 3
# Purpose-drawn scales first, then labelled grids, then grids with a printed (rounded) spacing.
SCALE_PRIORITY = ('scale_bar', 'scale_ratio', 'waterline_labels', 'buttock_grid', 'waterline_spacing')


# ---------------------------------------------------------------- results

@dataclass
class Line:
    """One straight grid line: centre (column or row), width (px), fill share of the box."""

    position: float
    width: int
    fill: float


@dataclass
class Flag:
    field: str
    message: str


@dataclass
class Calibration:
    """A body-plan calibration with a source label for every value."""

    box: list
    centre_column: float | None = None
    baseline_row: float | None = None
    pixels_per_ft: float | None = None
    waterlines: list = field(default_factory=list)  # {label, row, height_ft, source}
    sides: list = field(default_factory=list)  # {name, sign, stations_outer_first, grid_columns, source}
    max_offset_px: int | None = None
    grid_rows: list = field(default_factory=list)  # rows of every drawn horizontal line in the box
    sources: dict = field(default_factory=dict)  # field -> source label
    measures: dict = field(default_factory=dict)  # scale measures and side checks, as found
    flags: list = field(default_factory=list)  # open problems: a person must look before use
    notes: list = field(default_factory=list)  # weaker sources and side remarks, not blocking
    engineering_approved: bool = False

    def flag(self, name: str, message: str) -> None:
        self.flags.append(Flag(name, message[:400]))

    @property
    def usable(self) -> bool:
        """Every reader input is present (flags may still be open)."""
        return (self.centre_column is not None and self.pixels_per_ft is not None and self.baseline_row is not None
                and len(self.sides) == 2 and all(s['stations_outer_first'] for s in self.sides)
                and self.max_offset_px is not None)

    def flagged(self, name: str) -> bool:
        return any(flag.field == name for flag in self.flags)

    def row_at(self, height_ft: float) -> int:
        """Image row of a height above the baseline, on the drawn line when one is that close."""
        row = self.baseline_row - height_ft * self.pixels_per_ft
        near = [r for r in self.grid_rows if abs(r - row) <= SNAP_ROWS]
        if near:
            row = min(near, key=lambda r: abs(r - row))
        return int(round(row))

    def layout(self, waterline_heights_ft: dict | None = None) -> bpr.SheetLayout:
        """The reader's SheetLayout; waterline heights (label -> ft) default to the found waterlines."""
        if waterline_heights_ft is None:
            rows = {w['label']: int(round(w['row'])) for w in self.waterlines}
        else:
            rows = {label: self.row_at(height) for label, height in waterline_heights_ft.items()}
        sides = tuple(bpr.SideLayout(s['name'], s['sign'], tuple(s['stations_outer_first']),
                                     tuple(s['grid_columns'])) for s in self.sides)
        return bpr.SheetLayout(self.centre_column, self.pixels_per_ft / FEET_M, rows, int(self.max_offset_px),
                               sides)

    def to_json(self) -> dict:
        data = asdict(self)
        data['flags'] = [asdict(f) for f in self.flags]
        data['usable'] = self.usable
        return data


# ---------------------------------------------------------------- straight lines

def straight_lines(ink: np.ndarray, box: list, axis: str) -> list[Line]:
    """Vertical ('v') or horizontal ('h') straight lines in the box, by their ink fill share."""
    x0, y0, x1, y1 = box
    window = ink[y0:y1, x0:x1]
    fill = window.mean(axis=0 if axis == 'v' else 1)
    origin = x0 if axis == 'v' else y0
    found = np.flatnonzero(fill >= LINE_MIN_FILL)
    lines = []
    if found.size == 0:
        return lines
    for group in np.split(found, np.flatnonzero(np.diff(found) > 1) + 1):
        weights = fill[group]
        centre = float((group * weights).sum() / weights.sum())
        lines.append(Line(round(origin + centre, 1), int(group.size), round(float(weights.max()), 3)))
    return lines


def _mirror_tolerance(offset: float) -> float:
    return max(SYMMETRY_TOL_PX, SYMMETRY_TOL_SHARE * abs(offset))


def mirrored_pairs(lines: list[Line], centre: float) -> list[tuple[Line, Line]]:
    """Pairs (left, right) of lines mirrored about `centre`, each line used once, nearest first."""
    left = [line for line in lines if line.position < centre - 1]
    right = [line for line in lines if line.position > centre + 1]
    pairs, used = [], set()
    for line in sorted(left, key=lambda l: centre - l.position):
        target = 2 * centre - line.position
        candidates = [r for r in right if id(r) not in used
                      and abs(r.position - target) <= _mirror_tolerance(centre - line.position)]
        if candidates:
            best = min(candidates, key=lambda r: abs(r.position - target))
            used.add(id(best))
            pairs.append((line, best))
    return pairs


def find_centreline(verticals: list[Line], box: list) -> tuple[float | None, str, dict]:
    """The centreline column: the vertical line about which most vertical grid lines mirror.

    Returns (column, source, evidence). The evidence holds the median midpoint of the mirrored
    pairs, an independent estimate of the axis.
    """
    width = box[2] - box[0]
    best, best_key = None, None
    for line in verticals:
        pairs = [p for p in mirrored_pairs(verticals, line.position)
                 if line.position - p[0].position >= GRID_MIN_OFFSET_SHARE * width]
        key = (len(pairs), line.fill)
        if best_key is None or key > best_key:
            best, best_key = line, key
    if best is None or best_key[0] == 0:
        return None, 'code:none', {'pairs': 0}
    pairs = [p for p in mirrored_pairs(verticals, best.position)
             if best.position - p[0].position >= GRID_MIN_OFFSET_SHARE * width]
    midpoints = [(a.position + b.position) / 2 for a, b in pairs]
    evidence = {'pairs': len(pairs), 'line_fill': best.fill,
                'pair_midpoint_median': round(float(np.median(midpoints)), 1)}
    return best.position, 'code:vertical line at the symmetry axis of the buttock grid', evidence


def choose_centreline(verticals: list[Line], box: list, tagged: Line | None) -> tuple[float | None, str, dict]:
    """The centreline from two sources: the line the model tagged as the centreline, and the
    symmetry axis of the vertical grid (code). The tagged line wins; a different axis is a flag
    when the grid has at least two mirrored pairs (a one-sided grid has no axis to compare)."""
    axis, axis_source, evidence = find_centreline(verticals, box)
    if tagged is None:
        if axis is not None:
            evidence['disagreement'] = 'centreline from grid symmetry only (no tagged centreline)'
        return axis, axis_source, evidence
    width = box[2] - box[0]
    pairs = [p for p in mirrored_pairs(verticals, tagged.position)
             if tagged.position - p[0].position >= GRID_MIN_OFFSET_SHARE * width]
    evidence = dict(evidence, tagged=tagged.position, pairs_about_tagged=len(pairs))
    source = 'model:tagged centreline / code:line column'
    if pairs:
        source += f', {len(pairs)} grid pairs mirror about it'
    if axis is not None and abs(axis - tagged.position) > SYMMETRY_TOL_PX and evidence['pairs'] >= MIN_AXIS_PAIRS \
            and evidence['pairs'] > len(pairs):
        if abs(axis - tagged.position) <= GRID_MIN_OFFSET_SHARE * width:
            # The model tagged a neighbouring line (keel or post edge); the grid axis is the centreline.
            evidence['note'] = f'model tagged {tagged.position}, a line next to the grid axis {axis}'
            return axis, axis_source + ' (model tagged a neighbouring line)', evidence
        evidence['disagreement'] = (f'tagged centreline {tagged.position} but the grid mirrors best about {axis} '
                                    f'({evidence["pairs"]} pairs vs {len(pairs)})')
    return tagged.position, source, evidence


def grid_lines(verticals: list[Line], centre: float, box: list) -> dict:
    """Vertical grid lines (buttocks) of each half, nearest the centreline first: {-1: [...], 1: [...]}.

    Lines within GRID_MIN_OFFSET_SHARE of the box width are keel or post structure. A grid may be
    drawn on one half only.
    """
    width = box[2] - box[0]
    sides = {-1: [], 1: []}
    for line in verticals:
        offset = line.position - centre
        if abs(offset) >= GRID_MIN_OFFSET_SHARE * width:
            sides[1 if offset > 0 else -1].append(line)
    for sign in sides:
        sides[sign].sort(key=lambda line: abs(line.position - centre))
    return sides


# ---------------------------------------------------------------- printed values

def parse_feet(text) -> float | None:
    """Feet from a printed length: 3'-7", 32'-0", 3-7, 2-6-0 (feet-inches-eighths), 4 Ft, 8-1/16", 9"."""
    if text is None:
        return None
    if isinstance(text, (int, float)) and not isinstance(text, bool):
        return float(text)
    value = str(text).strip().replace('’', "'").replace('”', '"').replace('′', "'")
    value = value.replace('″', '"')
    sign = -1.0 if re.match(r'^\s*-\s*\d', value) else 1.0
    body = value.lstrip(' -')
    match = re.match(r"^(\d+)\s*'\s*-?\s*(\d+)?\s*(?:(\d+)\s*/\s*(\d+))?\s*\"?", body)
    if match:
        feet = int(match[1])
        inches = int(match[2]) if match[2] else 0
        fraction = Fraction(int(match[3]), int(match[4])) if match[3] else 0
        return sign * (feet + (inches + float(fraction)) / 12)
    match = re.match(r'^(\d+)\s*-\s*(\d+)\s*/\s*(\d+)\s*"', body)
    if match:  # 8-1/16"
        return sign * (int(match[1]) + int(match[2]) / int(match[3])) / 12
    match = re.match(r'^(\d+(?:\.\d+)?)\s*"', body)
    if match:  # 9"
        return sign * float(match[1]) / 12
    match = re.match(r'^(\d+)\s*-\s*(\d+)\s*-\s*([0-7])\+?(?:\D|$)', body)
    if match:  # feet-inches-eighths
        return sign * (int(match[1]) + (int(match[2]) + int(match[3]) / 8) / 12)
    match = re.match(r'^(\d+)\s*-\s*(\d+)(?:\D|$)', body)
    if match:  # feet-inches
        return sign * (int(match[1]) + int(match[2]) / 12)
    match = re.match(r'^(\d+(?:\.\d+)?)\s*(?:ft|feet|foot|\'|)\b', body, flags=re.IGNORECASE)
    if match:
        return sign * float(match[1])
    return None


def parse_scale_ratio(text) -> float | None:
    """Drawing inches per real foot from a printed scale such as 3/8" = 1'-0" or 1" = 1'."""
    if not text:
        return None
    value = str(text).replace('”', '"').replace('’', "'")
    match = re.search(r'(\d+(?:\s*/\s*\d+)?|\d+\s+\d+\s*/\s*\d+)\s*"\s*=\s*(\d+)\s*\'', value)
    if not match:
        return None
    left = match[1].replace(' ', '')
    inches = float(Fraction(left)) if '/' in left else float(left)
    feet = int(match[2])
    return inches / feet if feet else None


# ---------------------------------------------------------------- scale

def scale_from_buttocks(grid: dict, centre: float, labelled: dict,
                        spacing_ft: float | None) -> tuple[float | None, str]:
    """px/ft from the buttock grid: labelled offsets (line id -> ft), else the stated spacing."""
    lines = grid[-1] + grid[1]
    ratios = [abs(line.position - centre) / labelled[id(line)] for line in lines if labelled.get(id(line))]
    if len(ratios) >= 2:
        return float(np.median(ratios)), f'code:buttock offsets / model:labels ({len(ratios)} lines)'
    if spacing_ft:
        fullest = max(grid.values(), key=len)
        step = common_spacing([abs(line.position - centre) for line in fullest])
        if step:
            return step / spacing_ft, 'code:buttock spacing / model:printed spacing'
    return None, ''


def scale_from_heights(labelled: list[tuple[float, float]]) -> tuple[float | None, float | None]:
    """(px/ft, baseline row) from (row, height ft) pairs by a least-squares line."""
    if len(labelled) < 2:
        return None, None
    rows, heights = np.array(labelled).T
    if np.ptp(heights) <= 0:
        return None, None
    slope, intercept = np.polyfit(heights, rows, 1)
    return float(-slope), float(intercept)


def common_spacing(positions: list[float], tolerance: float = 0.015) -> float | None:
    """The most common gap between neighbouring lines (at least two gaps agree), or None."""
    gaps = np.diff(sorted(positions))
    best = None
    for gap in gaps:
        close = gaps[np.abs(gaps - gap) <= tolerance * gap]
        if len(close) >= 2 and (best is None or len(close) > len(best)):
            best = close
    return float(np.mean(best)) if best is not None else None


def scale_from_ticks(ticks: list[tuple[float, float]], unit_ft: float) -> float | None:
    """px/ft from (column, labelled value) scale-bar ticks; unit_ft is feet per labelled unit."""
    if len(ticks) < 2:
        return None
    columns, values = np.array(ticks).T
    if np.ptp(values) <= 0:
        return None
    slope = np.polyfit(values, columns, 1)[0]
    return float(abs(slope) / unit_ft)


def choose_scale(measures: dict) -> tuple[float | None, str, list[str]]:
    """The accepted px/ft and its source, and the problems: two measures must agree."""
    present = [(name, measures[name]['px_per_ft']) for name in SCALE_PRIORITY
               if name in measures and measures[name].get('px_per_ft')]
    if not present:
        return None, '', ['no scale measure found']
    if len(present) == 1:
        name, value = present[0]
        return value, f'{name} (single measure)', [f'only one scale measure ({name}); a second must agree']
    problems = []
    for i, (first, a) in enumerate(present):
        for second, b in present[i + 1:]:
            if abs(a - b) / max(a, b) <= SCALE_AGREEMENT:
                others = [n for n, v in present if abs(v - a) / max(v, a) > SCALE_AGREEMENT]
                for other in others:
                    problems.append(f'{other} disagrees ({measures[other]["px_per_ft"]:.2f} px/ft); noted, not used')
                return a, f'{first}, agrees with {second} within {SCALE_AGREEMENT:.0%}', problems
    listed = ', '.join(f'{n} {v:.2f}' for n, v in present)
    return present[0][1], f'{present[0][0]} (provisional)', [f'scale measures disagree: {listed} px/ft']


# ---------------------------------------------------------------- sides

def stations_outer_first(numbers: list[int], other: list[int]) -> tuple[int, ...]:
    """Nesting order of one half: the station nearest midship (the other half's numbers) first."""
    numbers = sorted(set(numbers))
    if not numbers:
        return ()
    other_mean = float(np.mean(other)) if other else None
    descending = other_mean is not None and np.mean(numbers) < other_mean
    return tuple(sorted(numbers, reverse=descending))


def fore_half_from_numbering(left: list[int], right: list[int], lowest_at: str) -> str | None:
    """Check A: the half that holds the lowest station number is fore when numbering starts at the bow."""
    if not left or not right or lowest_at not in ('bow', 'stern'):
        return None
    lowest_half = 'left' if min(left) < min(right) else 'right'
    if lowest_at == 'bow':
        return lowest_half
    return 'right' if lowest_half == 'left' else 'left'


# ---------------------------------------------------------------- calibrate

def vertical_extent(ink: np.ndarray, column: float, box: list, gap: int = DASH_GAP_ROWS) -> tuple[int, int]:
    """(top, bottom) rows of the longest ink run on a column (+-1 px) in the box; dashes join."""
    x = int(round(column))
    rows = np.flatnonzero(ink[box[1]:box[3], max(0, x - 1):x + 2].any(axis=1))
    if rows.size == 0:
        return box[3], box[1]
    runs = np.split(rows, np.flatnonzero(np.diff(rows) > gap) + 1)
    longest = max(runs, key=lambda run: run[-1] - run[0])
    return int(box[1] + longest[0]), int(box[1] + longest[-1])


def centreline_bottom(ink: np.ndarray, column: float, box: list, frames: list[Line] = ()) -> int:
    """Lowest row in the box with ink on the centreline column (+-2 px), frame lines left out."""
    x = int(round(column))
    strip = ink[box[1]:box[3], max(0, x - 2):x + 3].any(axis=1)
    for frame in frames:
        low = int(frame.position - box[1] - frame.width)
        strip[max(0, low):max(0, low + 2 * frame.width + 2)] = False
    found = np.flatnonzero(strip)
    return int(box[1] + found[-1]) if found.size else box[3]


def calibrate(ink: np.ndarray, reading, dpi: float | None = None) -> Calibration:
    """Calibrate the body plan of one sheet (ink mask, True = ink).

    `reading` answers the label questions (`calibration_reading.ClaudeReading`, or a fake in
    tests); any answer may be missing, which leaves a flag.
    """
    located = reading.locate(ink)
    box = located.get('body_plan_box_px')
    if not box:
        cal = Calibration(box=[])
        cal.flag('body_plan_box', 'the body plan was not located')
        return cal
    cal = Calibration(box=[int(v) for v in box])
    cal.sources['box'] = located.get('source', 'model:coarse box')
    verticals = straight_lines(ink, cal.box, 'v')
    horizontals = straight_lines(ink, cal.box, 'h')
    labels = reading.label_lines(ink, cal.box, horizontals, verticals)
    cal.measures['labels'] = labels.get('raw', {})
    centre, source, evidence = choose_centreline(verticals, cal.box, labels.get('centreline'))
    cal.measures['centreline'] = evidence
    if centre is None:
        cal.flag('centre_column', 'no centreline: no tagged line and no symmetric vertical grid')
        return cal
    cal.centre_column, cal.sources['centre_column'] = centre, source
    if evidence.get('disagreement'):
        cal.flag('centre_column', evidence['disagreement'])
    grid = grid_lines(verticals, centre, cal.box)

    # scale: buttock grid, labelled heights, scale bar, scale ratio x dpi, waterline spacing
    measures = {}
    vertical_feet = {id(line): feet for line, feet in labels.get('vertical_ft', [])}
    notes = reading.read_notes(ink) if not vertical_feet else {}
    cal.measures['notes'] = notes
    value, source = scale_from_buttocks(grid, centre, vertical_feet, notes.get('buttock_spacing_ft'))
    if value:
        measures['buttock_grid'] = {'px_per_ft': value, 'source': source}
    heights = [(line.position, feet) for line, feet in labels.get('horizontal_ft', [])]
    fit_scale, fit_base = scale_from_heights(heights)
    if fit_scale and len(heights) >= MIN_LABELLED_FOR_FIT:
        measures['waterline_labels'] = {'px_per_ft': fit_scale, 'source': 'code:rows / model:height labels',
                                        'baseline_row': fit_base, 'lines': len(heights)}
    scale_text = located.get('scale_text') or notes.get('scale_text')
    ratio = parse_scale_ratio(scale_text)
    if ratio and dpi:
        measures['scale_ratio'] = {'px_per_ft': ratio * dpi, 'source': f'model:scale text {scale_text!r} x {dpi:g} dpi'}
    bar = reading.read_scale_bar(ink, located.get('scale_bar_box_px')) if located.get('scale_bar_box_px') else {}
    if bar.get('ticks'):
        bar_scale = scale_from_ticks(bar['ticks'], bar.get('unit_ft', 1.0))
        if bar_scale:
            measures['scale_bar'] = {'px_per_ft': bar_scale, 'source': 'code:tick columns / model:tick values',
                                     'ticks': bar['ticks'], 'unit_ft': bar.get('unit_ft')}
    spacing = notes.get('waterline_spacing_ft')
    inner = sorted(line.position for line in horizontals if line.fill < FRAME_MIN_FILL)
    common = common_spacing(inner)
    if spacing and common:
        measures['waterline_spacing'] = {'px_per_ft': common / spacing,
                                         'source': 'code:horizontal line spacing / model:printed spacing'}
    cal.measures['scale'] = measures
    scale, source, problems = choose_scale(measures)
    for problem in problems:
        if 'noted' in problem:
            cal.notes.append(problem)
        else:
            cal.flag('pixels_per_ft', problem)
    if scale is None:
        return cal
    cal.pixels_per_ft, cal.sources['pixels_per_ft'] = round(scale, 3), source

    # baseline and waterlines
    labelled_base = [line for line in labels.get('base_lines', [])]
    if 'waterline_labels' in measures:
        cal.baseline_row = round(measures['waterline_labels']['baseline_row'], 1)
        cal.sources['baseline_row'] = 'code:fit of labelled waterline heights'
    elif labelled_base:
        cal.baseline_row = labelled_base[0].position
        cal.sources['baseline_row'] = 'model:label "base" / code:line row'
    else:
        frames = [line for line in horizontals if line.fill >= FRAME_MIN_FILL]
        bottom = centreline_bottom(ink, centre, cal.box, frames)
        below = [line for line in horizontals
                 if line.fill < FRAME_MIN_FILL and abs(line.position - bottom) <= CENTRELINE_END_TOLERANCE_ROWS]
        if below:
            cal.baseline_row = min(below, key=lambda l: abs(l.position - bottom)).position
            cal.sources['baseline_row'] = 'code:line where the centreline ends (no base label)'
            cal.notes.append('baseline is not labelled; taken where the centreline ends')
        else:
            cal.flag('baseline_row', 'no baseline found')
            return cal
    labelled_rows = {id(line): feet for line, feet in labels.get('horizontal_ft', [])}
    grid_top = min((vertical_extent(ink, line.position, cal.box)[0] for line in grid[-1] + grid[1]),
                   default=cal.box[1])
    frames = [l for l in horizontals if l.fill >= FRAME_MIN_FILL]
    lighter = [l for l in horizontals if l.fill < FRAME_MIN_FILL]
    candidates = horizontals if not lighter or len(frames) > len(lighter) else lighter
    if len(labelled_rows) >= MIN_LABELLED_FOR_FIT:
        # The sheet labels its waterlines: read at those, not at frames, rails or table rules.
        candidates = [line for line in horizontals if id(line) in labelled_rows]
    for line in candidates:
        height = (cal.baseline_row - line.position) / cal.pixels_per_ft
        if abs(line.position - cal.baseline_row) < 3 and id(line) not in labelled_rows:
            continue  # the baseline itself, at the keel
        if height < -0.5 * (cal.baseline_row - cal.box[1]) / cal.pixels_per_ft:
            continue
        if line.position < grid_top - SNAP_ROWS and id(line) not in labelled_rows:
            continue  # above the buttock grid: another view or the title, not a waterline
        source = 'model:height label / code:row' if id(line) in labelled_rows else 'code:row, height from scale'
        cal.waterlines.append({'label': feet_inches(height), 'row': line.position, 'height_ft': round(height, 4),
                               'source': source})
    cal.sources['waterlines'] = 'code:horizontal grid lines'
    cal.grid_rows = [line.position for line in horizontals]

    # sides
    left, right = labels.get('stations_left', []), labels.get('stations_right', [])
    direction = reading.numbering_direction(ink)
    check_a = fore_half_from_numbering(left, right, direction.get('lowest_at'))
    check_b = reading.fore_half_by_shape(ink, cal.box, centre).get('fore_half')
    cal.measures['side_checks'] = {'labels': {'left': left, 'right': right, 'lowest_at': direction.get('lowest_at'),
                                              'evidence': direction.get('evidence'), 'fore_half': check_a},
                                   'shape': {'fore_half': check_b}}
    if not left or not right:
        cal.flag('stations', 'station labels were not read on both halves')
        return cal
    if check_a and check_b and check_a == check_b:
        fore, side_source = check_a, 'model:station labels + numbering, agrees with model:shape check'
    else:
        fore = check_a or check_b or 'right'
        side_source = 'provisional: ' + ('station labels' if check_a else 'shape check' if check_b else 'default right')
        cal.flag('sides', f'side checks disagree or are missing: labels say fore {check_a}, shapes say fore {check_b}')
    for name, half, numbers, other, sign in (('left', 'left', left, right, -1), ('right', 'right', right, left, 1)):
        columns = tuple(line.position for line in grid[sign])
        cal.sides.append({'name': 'fore' if half == fore else 'aft', 'sign': sign,
                          'stations_outer_first': list(stations_outer_first(numbers, other)),
                          'grid_columns': [round(c, 1) for c in columns], 'source': side_source})
    cal.sources['sides'] = side_source

    # reader search half-span: outermost station crossing + margin
    cal.max_offset_px = search_half_span(ink, cal)
    cal.sources['max_offset_px'] = f'code:outermost station crossing + {MAX_OFFSET_MARGIN_PX} px'
    return cal


def search_half_span(ink: np.ndarray, cal: Calibration) -> int:
    """Outermost station-curve crossing at the found waterlines (reader, first pass) + margin."""
    limit = int(min(cal.centre_column - cal.box[0], cal.box[2] - cal.centre_column))
    if not cal.waterlines:
        return limit
    cal.max_offset_px = limit
    layout = cal.layout()
    outermost = 0.0
    for side in layout.sides:
        reading = bpr.measure_side(ink, layout, side)
        for chain in reading.chains:
            if len(chain.nodes) < 2:
                continue  # one-waterline chains are lettering, rails or other views, not stations
            for waterline, index in chain.nodes.items():
                crossing = reading.stations[waterline][index]
                outermost = max(outermost, crossing.offset_px(layout.centre_column, side.sign))
    return int(min(limit, outermost + MAX_OFFSET_MARGIN_PX)) if outermost else limit


def feet_inches(height_ft: float) -> str:
    """A waterline label in feet-inches-eighths, as the HAER tables print them."""
    sign = '-' if height_ft < 0 else ''
    eighths = int(round(abs(height_ft) * 96))
    feet, rest = divmod(eighths, 96)
    inches, eighth = divmod(rest, 8)
    return f'{sign}{feet}-{inches}-{eighth}'
