"""Scorer for the WHITE GULL and COLLEEN hard-chine holdouts (docs/BODY_PLAN_CHINE.md,
"Holdout protocol: WHITE GULL and COLLEEN").

Two kinds of truth cell, scored separately:

(a) Waterline cells: printed (station, waterline) half-breadths. The reader value is the arm's
    table at that waterline's measuring row (frozen: `table_from_identities`; v2: `sheet_table`;
    polyline: `waterline_table` on read halves, the frozen table on declined halves). Metrics are
    the waterline harness scorer (`benchmarks.balclutha.model_value.score`: identity check with 3
    shared waterlines) plus wrong cells (> 0.15 m) and missing / extra keys. Only printed
    waterline rows are scored; an extra cell is a reader value where the printed cell is blank.
(b) Point cells: printed (station, SHEER / CHINE / RABBET) height and half-breadth pairs. The
    reader value is the station's half-breadth at the printed height, interpolated between two
    consecutive samples of its curve that enclose the height (E. C. COLLIER point-scorer rules,
    `benchmarks.ec_collier.point_score`): frozen and v2 samples are the station's crossings on
    the measuring rows (a row without a crossing breaks the curve); polyline samples are the
    traced polyline's own points. No extrapolation. Identity check with 2 shared points.

Product rule (polyline arm): a half read as a whole gives its polylines; a declined half gives the
frozen curves, with the stations engaged one by one (`body_plan_polyline.engage_stations`, named by
the frozen rank identities) in place of their frozen curves.

The calibration module (`benchmarks.white_gull.holdout_value` or `benchmarks.colleen.holdout_value`)
is passed in; nothing here knows a vessel. Truth is read only when scoring, after a sha256 check.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import numpy as np

from benchmarks.balclutha import model_value as harness
from benchmarks.ec_collier import point_score as collier
from vessel_reconstruction import body_plan_polyline as polyline
from vessel_reconstruction import body_plan_reader as reader

POINTS = collier.POINTS  # ('sheer', 'chine', 'rabbet')
WRONG_BAND_M = collier.WRONG_BAND_M  # 0.15 m
IDENTITY_MIN_POINTS = collier.IDENTITY_MIN_POINTS  # 2
TRUTH_UNITS = 'ft-in-eighths'
# Plausible ranges (m): a sanity check on the truth file's units. Both boats are under 3 m in
# half-breadth; Colleen's keel is about 0.63 m below its base line, neither sheer is above 2 m.
HALF_BREADTH_RANGE_M = (0.0, 4.0)
HEIGHT_RANGE_M = (-1.5, 4.0)
# A printed waterline ("WL <height>") is scored on the measuring row whose nominal height is within
# this of the printed height. A printed waterline on no measuring row is listed, not scored.
WATERLINE_MATCH_FT = 0.02
# Printed row names (whitespace removed) that give point truth: point -> (heights row, half-breadth
# rows in order of preference). COLLEEN prints the rabbet half-breadth as "KEEL RABBET".
POINT_ROWS = {'sheer': ('SHEER', ('SHEER',)), 'chine': ('CHINE', ('CHINE',)),
              'rabbet': ('RABBET', ('RABBET', 'KEELRABBET'))}
WATERLINE_PREFIX = 'WL'
VALUE_PATTERN = re.compile(r'(-)?(\d+)-(\d+)-([0-7])(\+)?')


# ---------------------------------------------------------------- printed values

def printed_feet(value: str) -> float:
    """A printed feet-inches-eighths value in feet.

    "5-2-4+" is 5 ft 2 4/8 in plus 1/16 in; a leading "-" makes the whole value negative
    ("-0-4-1" is -(4 1/8) in). Whitespace inside the value is ignored.
    """
    if not isinstance(value, str):
        raise ValueError('truth: every cell must be a feet-inches-eighths string or null')
    match = VALUE_PATTERN.fullmatch(re.sub(r'\s+', '', value))
    if match is None:
        raise ValueError(f'truth: invalid feet-inches-eighths value {value!r}')
    feet, inches, eighths = int(match[2]), int(match[3]), int(match[4])
    if inches >= 12:
        raise ValueError(f'truth: inches out of range in {value!r}')
    magnitude = feet + (inches + eighths / 8 + (1 / 16 if match[5] else 0)) / 12
    return -magnitude if match[1] else magnitude


def printed_metres(value) -> float | None:
    """A printed cell in metres; None for a blank (null) cell."""
    return None if value is None else printed_feet(value) * 0.3048


def row_key(name: str) -> str:
    """A printed row name with all whitespace removed ("WL -1- 0-0" -> "WL-1-0-0")."""
    return re.sub(r'\s+', '', name).upper()


def match_waterline(height_ft: float, cal) -> str | None:
    """The measuring-row label at a printed waterline height, or None if there is none."""
    for label, known in cal.WATERLINE_HEIGHTS_FT.items():
        if abs(known - height_ft) <= WATERLINE_MATCH_FT:
            return label
    return None


# ---------------------------------------------------------------- truth

def _check_range(value: float | None, limits: tuple, what: str) -> None:
    if value is not None and not limits[0] <= value <= limits[1]:
        raise ValueError(f'truth: {what} is outside the plausible range')


def _station_columns(names: list, cal) -> list[tuple[int, int]]:
    """(column index, station number) of the numbered stations; other columns (TRANSOM) are ignored."""
    columns = [(index, int(name)) for index, name in enumerate(names) if str(name).strip().isdigit()]
    if [station for _, station in columns] != list(cal.STATIONS):
        raise ValueError(f'truth: numbered stations must be {list(cal.STATIONS)} in order')
    return columns


def parse_truth(data: dict, cal) -> dict:
    """{'waterlines': {(station, label): m or None}, 'points': {(station, point): {...}},
    'unmatched_waterlines': [printed names]}.

    Format (PM): {"units": "ft-in-eighths", "stations": ["1", ..., "TRANSOM"], "x_positions": [...],
    "heights": {ROW NAME: [one per station]}, "half_breadths": {ROW NAME: [...]}, "notes": {...},
    "unsure": [...]}. Waterline truth: half-breadth rows named "WL <height>". Point truth: SHEER,
    CHINE, RABBET (half-breadth "KEEL RABBET" when no "RABBET"). Other rows (BUTTOCK, KEEL, STEM
    EDGE) and non-numbered station columns are ignored.
    """
    if data.get('units') != TRUTH_UNITS:
        raise ValueError(f'truth: units must be {TRUTH_UNITS!r}')
    names = list(data.get('stations', []))
    columns = _station_columns(names, cal)
    heights = {row_key(name): values for name, values in (data.get('heights') or {}).items()}
    breadths = {row_key(name): values for name, values in (data.get('half_breadths') or {}).items()}
    for table, values in ((heights, 'heights'), (breadths, 'half_breadths')):
        for name, row in table.items():
            if len(row) != len(names):
                raise ValueError(f'truth: {values} row {name} must list {len(names)} cells')

    waterlines: dict = {}
    unmatched = []
    for name, row in breadths.items():
        if not name.startswith(WATERLINE_PREFIX):
            continue
        label = match_waterline(printed_feet(name[len(WATERLINE_PREFIX):]), cal)
        if label is None:
            unmatched.append(name)
            continue
        if any(w == label for _, w in waterlines):
            raise ValueError(f'truth: waterline {name} repeats a measuring row')
        for index, station in columns:
            metres = printed_metres(row[index])
            _check_range(metres, HALF_BREADTH_RANGE_M, f'station {station} {name}')
            waterlines[(station, label)] = metres

    points: dict = {}
    for point, (height_row, breadth_rows) in POINT_ROWS.items():
        breadth_row = next((name for name in breadth_rows if name in breadths), None)
        if height_row not in heights or breadth_row is None:
            continue
        for index, station in columns:
            height_m = printed_metres(heights[height_row][index])
            breadth_m = printed_metres(breadths[breadth_row][index])
            _check_range(height_m, HEIGHT_RANGE_M, f'station {station} {point} height')
            _check_range(breadth_m, HALF_BREADTH_RANGE_M, f'station {station} {point} half-breadth')
            points[(station, point)] = {'height': height_m, 'half_breadth': breadth_m}
    if not waterlines and not points:
        raise ValueError('truth: no cells')
    return {'waterlines': waterlines, 'points': points, 'unmatched_waterlines': unmatched}


def load_truth(path: Path, cal) -> dict:
    """Parse the frozen truth file after checking its fingerprint; a different file stops the run."""
    expected = getattr(cal, 'TRUTH_SHA256', None)
    if not expected:
        raise SystemExit('no frozen truth sha256 in the calibration; the PM records it before the run; stop')
    raw = Path(path).read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if digest != expected:
        raise SystemExit(f'truth sha256 {digest} does not match the frozen {expected}; stop')
    return parse_truth(json.loads(raw), cal)


# ---------------------------------------------------------------- waterline cells

def score_waterlines(table: dict, truth: dict, cal) -> dict:
    """Waterline harness metrics on the printed rows. `table` is {(station, label): m}."""
    printed_cells = truth['waterlines']
    values = {key: value for key, value in printed_cells.items() if value is not None}
    rows = tuple(label for label in cal.WATERLINES if any(w == label for _, w in printed_cells))
    on_printed_rows = {key: value for key, value in table.items() if key in printed_cells}
    if not values:
        return {'truth_cells': 0, 'cells_given': 0}
    result = harness.score(on_printed_rows, values, cal.STATIONS, rows)
    common = [key for key in values if key in on_printed_rows]
    errors = {key: on_printed_rows[key] - values[key] for key in common}
    result['wrong_cells'] = int(sum(abs(e) > WRONG_BAND_M for e in errors.values()))
    result['missing_cell_keys'] = [[s, w] for s, w in sorted(values) if (s, w) not in on_printed_rows]
    result['extra_cell_keys'] = [[s, w] for s, w in sorted(on_printed_rows) if (s, w) not in values]
    result['errors_m'] = {f'{s}/{w}': errors[(s, w)] for s, w in sorted(errors)}
    return result


# ---------------------------------------------------------------- point cells

def value_at(curve: list, height_m: float) -> float | None:
    """Half-breadth of one station at `height_m` from its ordered samples.

    `curve` lists (height m, half-breadth m) from low to high, with None where a measuring row has
    no crossing. Only two consecutive samples that both exist and enclose the height are used.
    """
    for lower, upper in zip(curve, curve[1:]):
        if lower is None or upper is None:
            continue
        (z_low, y_low), (z_high, y_high) = lower, upper
        if z_low < z_high and z_low <= height_m <= z_high:
            weight = (height_m - z_low) / (z_high - z_low)
            return y_low + weight * (y_high - y_low)
    return None


def _summary(errors: list) -> dict:
    if not errors:
        return {'cells_given': 0}
    array = np.abs(np.array(errors))
    return {'cells_given': len(errors), 'rms_m': float(np.sqrt(np.mean(array ** 2))),
            'max_abs_m': float(array.max()), 'wrong_cells': int(np.sum(array > WRONG_BAND_M))}


def point_identity_errors(curves: dict, cells: dict, stations: tuple) -> list[int]:
    """Stations whose curve fits a neighbouring station's printed points better than its own."""
    def station_rms(curve: list, other: int) -> float | None:
        pairs = []
        for point in POINTS:
            if (other, point) in cells:
                height, breadth = cells[(other, point)]
                value = value_at(curve, height)
                if value is not None:
                    pairs.append(value - breadth)
        return float(np.sqrt(np.mean(np.square(pairs)))) if len(pairs) >= IDENTITY_MIN_POINTS else None

    errors = []
    for station in sorted(curves):
        own = station_rms(curves[station], station)
        if own is None:
            continue
        neighbours = [station_rms(curves[station], other) for other in (station - 1, station + 1) if other in stations]
        if any(rms is not None and rms < own for rms in neighbours):
            errors.append(station)
    return errors


def score_points(curves: dict, truth: dict, cal) -> dict:
    """Point-cell metrics for one arm. `curves` is {station: ordered samples} (see `value_at`)."""
    printed_points = truth['points']
    cells = {key: (v['height'], v['half_breadth']) for key, v in printed_points.items()
             if v['height'] is not None and v['half_breadth'] is not None}
    if not printed_points:
        return {'truth_cells': 0, 'cells_given': 0}
    values = {}
    for (station, point), v in printed_points.items():
        if v['height'] is not None and station in curves:
            value = value_at(curves[station], v['height'])
            if value is not None:
                values[(station, point)] = value
    errors = {key: values[key] - cells[key][1] for key in cells if key in values}
    result = {'truth_cells': len(cells), **_summary(list(errors.values()))}
    result['coverage'] = len(errors) / len(cells) if cells else 0.0
    for point in POINTS:
        result[f'{point}_only'] = dict(_summary([e for (s, p), e in errors.items() if p == point]),
                                       truth_cells=sum(1 for _, p in cells if p == point))
    result['identity_errors'] = point_identity_errors(curves, cells, cal.STATIONS)
    result['missing_cell_keys'] = [[s, p] for s, p in sorted(cells) if (s, p) not in values]
    # Extra: a value at a printed height whose half-breadth is printed blank.
    result['extra_cell_keys'] = [[s, p] for s, p in sorted(printed_points)
                                 if printed_points[(s, p)]['half_breadth'] is None and (s, p) in values]
    result['unevaluable_blank_points'] = [[s, p] for s, p in sorted(printed_points)
                                          if printed_points[(s, p)]['height'] is None]
    result['errors_m'] = {f'{s}/{p}': errors[(s, p)] for s, p in sorted(errors)}
    return result


# ---------------------------------------------------------------- reader samples

def sample(row: float, column: float, half_breadth: float, cal) -> tuple[float, float]:
    """(height above base m, half-breadth m) of an image point."""
    return cal.height_ft(row, column) * 0.3048, half_breadth


def _row_curves(found: dict, cal) -> dict:
    """{station: {label: sample}} -> {station: [sample or None per measuring row, low to high]}."""
    return {station: [cells.get(label) for label in cal.WATERLINES] for station, cells in found.items()}


def _crossing_sample(crossing, layout, sign: int, cal) -> tuple[float, float]:
    breadth = crossing.offset_px(layout.centre_column, sign) / layout.pixels_per_metre
    return sample(crossing.row, crossing.x_px, breadth, cal)


def _identity_crossings(reading, identities: dict) -> dict:
    """{station: {label: crossing}}; as `table_from_identities`, the outer chain keeps a shared cell."""
    found: dict = {}
    for chain_index, station in sorted(identities.items(), reverse=True):
        for label, node in reading.chains[chain_index].nodes.items():
            found.setdefault(station, {})[label] = reading.stations[label][node]
    return found


def _identity_cells(reading, identities: dict, layout, cal) -> dict:
    """{station: {label: sample}} of the frozen reader's rank identities."""
    return {station: {label: _crossing_sample(crossing, layout, reading.layout.sign, cal)
                      for label, crossing in cells.items()}
            for station, cells in _identity_crossings(reading, identities).items()}


def frozen_curves(readings: dict, identities: dict, layout, cal, halves: tuple | None = None) -> dict:
    """Station curves of the frozen reader with its rank identities (only `halves`, if given)."""
    found: dict = {}
    for name, reading in readings.items():
        if halves is None or name in halves:
            found.update(_identity_cells(reading, identities[name], layout, cal))
    return _row_curves(found, cal)


def v2_curves(sides: dict, layout, cal) -> dict:
    """Station curves of reader v2 (frozen identities on a half without a verified chine line)."""
    found: dict = {}
    for side in sides.values():
        if not side.uses_chine:
            found.update(_identity_cells(side.base, side.identities, layout, cal))
            continue
        for (station, label), claim in side.cells.items():
            crossing = side.base.stations[claim.waterline][claim.index]
            found.setdefault(station, {})[label] = _crossing_sample(crossing, layout, side.base.layout.sign, cal)
    return _row_curves(found, cal)


def _polyline_samples(station, layout, cal) -> list:
    """Samples along a traced polyline; its points run from the rabbet (low) up to the sheer."""
    return [sample(row, column, station.offset_px(column, layout.centre_column) / layout.pixels_per_metre, cal)
            for row, column in station.points]


def frozen_half_tables(readings: dict, identities: dict, layout) -> dict:
    """{half: frozen rank-identity table of that half}."""
    return {name: reader.table_from_identities(reading, identities[name], layout.pixels_per_metre,
                                               layout.centre_column)
            for name, reading in readings.items()}


def engage(halves: dict, readings: dict, identities: dict, layout) -> None:
    """Per-station engagement on the declined halves, named by the frozen rank identities."""
    tables = frozen_half_tables(readings, identities, layout)
    for name, half in halves.items():
        polyline.engage_stations(half, readings[name].layout, tables[name], layout)


def polyline_curves(halves: dict, readings: dict, identities: dict, layout, cal) -> dict:
    """Product rule: traced polylines on read halves; on declined halves the frozen curves, with
    engaged stations' polylines in place of their frozen curves and no frozen sample on an engaged
    polyline's ink (`body_plan_polyline.half_table`)."""
    curves: dict = {}
    for name, reading in readings.items():
        half = halves[name]
        if half.read:
            for station in half.stations:
                curves[station.station] = _polyline_samples(station, layout, cal)
            continue
        found = _identity_crossings(reading, identities[name])
        engaged = getattr(half, 'engaged', [])
        for station in engaged:
            found.pop(station.station, None)
            for cells in found.values():
                for label in [label for label, crossing in cells.items()
                              if polyline.same_ink(station, crossing.row, crossing.x_px, half.line_width_px)]:
                    del cells[label]
        curves.update(_row_curves({station: {label: _crossing_sample(crossing, layout, reading.layout.sign, cal)
                                             for label, crossing in cells.items()}
                                   for station, cells in found.items()}, cal))
        for station in engaged:
            curves[station.station] = _polyline_samples(station, layout, cal)
    return curves


def polyline_table(halves: dict, readings: dict, identities: dict, layout) -> dict:
    """Product rule waterline table (`body_plan_polyline.half_table` per half)."""
    tables = frozen_half_tables(readings, identities, layout)
    table = {}
    for name in readings:
        table.update(polyline.half_table(halves[name], tables[name], layout))
    return table


# ---------------------------------------------------------------- gates

def gates(frozen: dict, arm: dict) -> dict:
    """Code gates of one arm against the frozen reader, for one kind of cell.

    The by-eye gate (every named knuckle on a drawn station corner) is recorded separately.
    """
    given = arm.get('cells_given', 0)
    frozen_given = frozen.get('cells_given', 0)
    rms = arm.get('rms_m', float('inf')) if given else float('inf')
    frozen_rms = frozen.get('rms_m', float('inf')) if frozen_given else float('inf')
    result = {
        'cells_at_least_frozen': given >= frozen_given,
        'rms_not_worse': rms <= frozen_rms + 1e-12,
        'wrong_not_worse': arm.get('wrong_cells', 0) <= frozen.get('wrong_cells', 0),
        'wrong_at_most_10_percent': given > 0 and arm.get('wrong_cells', 0) <= 0.10 * given,
        'no_extra_on_blank_truth': not arm.get('extra_cell_keys'),
    }
    result['all_code_gates'] = all(result.values())
    return result
