"""Point-offset scorer for the hard-chine holdout amendment (E. C. COLLIER).

The sheet prints, for each station, the height above base and the half-breadth of three points:
SHEER, CHINE and RABBET. A truth cell is one printed (station, point) pair with both numbers
given. The reader value of a truth cell is the reader's half-breadth of that station at the
printed height, linearly interpolated between the station's crossings on the two neighbouring
measuring rows that enclose the height. No extrapolation: a height outside the station's
measured rows, or between two rows of which one has no crossing for the station, gives no cell.

Interpolation uses each crossing's own measured image row (the reader measures where the curve
crosses the row, which may be a few pixels from the nominal row where a drawn line is near),
converted to a height above the sloped base line by the sheet calibration.

Metrics follow docs/BODY_PLAN_CHINE.md "Metrics and acceptance" and the protocol: cells given /
truth cells, RMS and maximum error on common cells, wrong cells (> 0.15 m), a chine-only line,
identity errors, extra and missing cells. Truth is read only when scoring.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import numpy as np

from benchmarks.bue_girl import holdout_value as printed  # the existing feet-inches-eighths parser
from benchmarks.ec_collier import holdout_value as cal

POINTS = ('sheer', 'chine', 'rabbet')
WRONG_BAND_M = 0.15
# Identity check: the harness asks for three shared waterlines, but a station here has at most
# three printed points (and the rabbet is often out of reach), so two shared points are enough.
IDENTITY_MIN_POINTS = 2
# Plausible range of any printed height or half-breadth on this sheet, metres (a sanity check
# on the truth file's units; the boat is about 6 m to the rail and 2.7 m in half-breadth).
TRUTH_RANGE_M = (0.0, 4.0)


# ---------------------------------------------------------------- truth

def _metres(value, key: str) -> float | None:
    """A printed value in metres: a feet-inches-eighths string, or a number in metres.

    A number is metres unless its key names feet ('ft') or inches ('in').
    """
    if value is None or (isinstance(value, str) and value.strip() in ('', '-', '—', '–')):
        return None
    if isinstance(value, str):
        text = re.sub(r'(?<=\d)\s+(?=\d)', '-', value.strip())  # "5-0 0" -> "5-0-0"
        return printed.printed_half_breadth(text)
    number = float(value)
    lowered = key.lower()
    if lowered.endswith('_ft') or lowered.endswith('feet'):
        return number * 0.3048
    if lowered.endswith('_in') or lowered.endswith('inches'):
        return number * 0.0254
    return number


def _find(mapping: dict, *fragments: str):
    """The first key of `mapping` whose lower-case name contains all `fragments`."""
    for key in mapping:
        if all(fragment in key.lower() for fragment in fragments):
            return key
    return None


def _from_tables(data: dict) -> dict:
    """{"stations": [...], "<height...>": {point: [...]}, "<half breadth...>": {point: [...]}}."""
    stations = [int(s) for s in data['stations']]
    height_key = _find(data, 'height')
    breadth_key = _find(data, 'half') or _find(data, 'breadth')
    if height_key is None or breadth_key is None:
        raise ValueError('truth: expected a height table and a half-breadth table')
    truth = {}
    for kind, key in (('height', height_key), ('half_breadth', breadth_key)):
        table = {name.lower(): values for name, values in data[key].items()}
        for point in POINTS:
            values = table.get(point)
            if values is None or len(values) != len(stations):
                raise ValueError(f'truth: {key}.{point} must list one value per station')
            for station, value in zip(stations, values):
                truth.setdefault((station, point), {})[kind] = _metres(value, key)
    return truth


def _from_records(records: list) -> dict:
    """[{"station": 0, "point": "sheer", "height...": v, "half...breadth...": v}, ...]."""
    truth = {}
    for record in records:
        height_key = _find(record, 'height')
        breadth_key = _find(record, 'half') or _find(record, 'breadth')
        point = str(record['point']).lower()
        if point not in POINTS:
            raise ValueError(f'truth: unknown point name {record["point"]!r}')
        truth[(int(record['station']), point)] = {
            'height': _metres(record.get(height_key), height_key or ''),
            'half_breadth': _metres(record.get(breadth_key), breadth_key or '')}
    return truth


def _from_nested(data: dict) -> dict:
    """{"<station>": {"<point>": {"height...": v, "half...breadth...": v}}}."""
    records = [dict(values, station=station, point=point)
               for station, points in data.items() for point, values in points.items()]
    return _from_records(records)


def parse_truth(data) -> dict:
    """{(station, point): {'height': m or None, 'half_breadth': m or None}} for every printed point."""
    if isinstance(data, list):
        truth = _from_records(data)
    elif 'stations' in data:
        truth = _from_tables(data)
    elif _find(data, 'cell') or _find(data, 'point'):
        truth = _from_records(data[_find(data, 'cell') or _find(data, 'point')])
    else:
        truth = _from_nested({k: v for k, v in data.items() if str(k).lstrip('-').isdigit()})
    for (station, point), values in truth.items():
        if station not in cal.STATIONS:
            raise ValueError(f'truth: station {station} is not on the sheet')
        for value in values.values():
            if value is not None and not TRUTH_RANGE_M[0] <= value <= TRUTH_RANGE_M[1]:
                raise ValueError(f'truth: a value of station {station} {point} is outside the plausible '
                                 'range; check the units')
    return truth


def load_truth(path: Path) -> dict:
    return parse_truth(json.loads(Path(path).read_text()))


def truth_cells(truth: dict) -> dict:
    """{(station, point): (height m, half-breadth m)} for points with both numbers printed."""
    return {key: (v['height'], v['half_breadth']) for key, v in truth.items()
            if v['height'] is not None and v['half_breadth'] is not None}


# ---------------------------------------------------------------- reader samples

def sample(row: float, column: float, half_breadth_m: float) -> tuple[float, float]:
    """(height above base m, half-breadth m) of a measured crossing."""
    return cal.height_ft(row, column) * 0.3048, half_breadth_m


def _crossing_sample(crossing, layout, sign: int) -> tuple[float, float]:
    half_breadth = crossing.offset_px(layout.centre_column, sign) / layout.pixels_per_metre
    return sample(crossing.row, crossing.x_px, half_breadth)


def samples_from_identities(reading, identities: dict, layout) -> dict:
    """{station: {waterline label: (height m, half-breadth m)}}; as `table_from_identities`, the
    outer chain keeps a cell that two chains claim."""
    found: dict = {}
    for chain_index, station in sorted(identities.items(), reverse=True):
        for label, node in reading.chains[chain_index].nodes.items():
            crossing = reading.stations[label][node]
            found.setdefault(station, {})[label] = _crossing_sample(crossing, layout, reading.layout.sign)
    return found


def samples_frozen(readings: dict, identities: dict, layout) -> dict:
    """Both halves of the frozen reader with its rank identities."""
    found: dict = {}
    for name, reading in readings.items():
        for station, cells in samples_from_identities(reading, identities[name], layout).items():
            found.setdefault(station, {}).update(cells)
    return found


def samples_v2(sides: dict, layout) -> dict:
    """Both halves of reader v2 (the frozen identities on a half without a verified chine line)."""
    found: dict = {}
    for side in sides.values():
        if not side.uses_chine:
            part = samples_from_identities(side.base, side.identities, layout)
        else:
            part = {}
            for (station, label), claim in side.cells.items():
                crossing = side.base.stations[claim.waterline][claim.index]
                part.setdefault(station, {})[label] = _crossing_sample(crossing, layout, side.base.layout.sign)
        for station, cells in part.items():
            found.setdefault(station, {}).update(cells)
    return found


# ---------------------------------------------------------------- scoring

def value_at(cells: dict, height_m: float, labels: tuple = cal.WATERLINES) -> float | None:
    """Half-breadth of one station at `height_m`, interpolated between two neighbouring rows.

    `cells` is {label: (height m, half-breadth m)}; `labels` lists the measuring rows from low to
    high. Only two consecutive rows that both have a crossing may enclose the height.
    """
    for lower, upper in zip(labels, labels[1:]):
        if lower not in cells or upper not in cells:
            continue
        (z_low, y_low), (z_high, y_high) = cells[lower], cells[upper]
        if not z_low < z_high:
            continue
        if z_low <= height_m <= z_high:
            weight = (height_m - z_low) / (z_high - z_low)
            return y_low + weight * (y_high - y_low)
    return None


def reader_values(samples: dict, truth: dict, labels: tuple = cal.WATERLINES) -> dict:
    """{(station, point): reader half-breadth m} at every printed height that the reader encloses."""
    values = {}
    for (station, point), printed_values in truth.items():
        if printed_values['height'] is None or station not in samples:
            continue
        value = value_at(samples[station], printed_values['height'], labels)
        if value is not None:
            values[(station, point)] = value
    return values


def _summary(errors: list) -> dict:
    if not errors:
        return {'cells_given': 0}
    array = np.abs(np.array(errors))
    return {'cells_given': len(errors), 'rms_m': float(np.sqrt(np.mean(array ** 2))),
            'max_abs_m': float(array.max()), 'wrong_cells': int(np.sum(array > WRONG_BAND_M))}


def identity_errors(samples: dict, cells: dict, labels: tuple = cal.WATERLINES) -> list[int]:
    """Stations whose curve fits a neighbouring station's printed points better than its own."""
    def station_rms(curve: dict, other: int) -> float | None:
        pairs = []
        for point in POINTS:
            if (other, point) in cells:
                height, half_breadth = cells[(other, point)]
                value = value_at(curve, height, labels)
                if value is not None:
                    pairs.append(value - half_breadth)
        return float(np.sqrt(np.mean(np.square(pairs)))) if len(pairs) >= IDENTITY_MIN_POINTS else None

    errors = []
    for station in sorted(samples):
        own = station_rms(samples[station], station)
        if own is None:
            continue
        neighbours = [station_rms(samples[station], other) for other in (station - 1, station + 1)
                      if other in cal.STATIONS]
        if any(rms is not None and rms < own for rms in neighbours):
            errors.append(station)
    return errors


def score(samples: dict, truth: dict, labels: tuple = cal.WATERLINES) -> dict:
    """All protocol metrics for one arm. `truth` comes from `load_truth`."""
    cells = truth_cells(truth)
    values = reader_values(samples, truth, labels)
    common = [key for key in cells if key in values]
    errors = {key: values[key] - cells[key][1] for key in common}
    blank_breadth = [key for key, v in truth.items() if v['half_breadth'] is None]
    result = {'truth_cells': len(cells), **_summary(list(errors.values()))}
    result['coverage'] = len(common) / len(cells) if cells else 0.0
    result['chine_only'] = dict(_summary([e for (s, p), e in errors.items() if p == 'chine']),
                                truth_cells=sum(1 for _, p in cells if p == 'chine'))
    result['by_point'] = {point: _summary([e for (s, p), e in errors.items() if p == point]) for point in POINTS}
    result['identity_errors'] = identity_errors(samples, cells, labels)
    result['missing_cell_keys'] = [[s, p] for s, p in sorted(cells) if (s, p) not in values]
    # Extra: a value where the half-breadth is printed blank (needs a printed height to evaluate).
    result['extra_cell_keys'] = [[s, p] for s, p in sorted(blank_breadth) if (s, p) in values]
    result['unevaluable_blank_points'] = [[s, p] for s, p in sorted(truth)
                                          if truth[(s, p)]['height'] is None]
    result['errors_m'] = {f'{s}/{p}': errors[(s, p)] for s, p in sorted(errors)}
    return result


def gates(frozen: dict, v2: dict) -> dict:
    """Protocol gates. The chine-line overlay check is made by eye and recorded separately."""
    v2_given = v2.get('cells_given', 0)
    v2_rms = v2.get('rms_m', float('inf')) if v2_given else float('inf')
    frozen_rms = frozen.get('rms_m', float('inf')) if frozen.get('cells_given', 0) else float('inf')
    result = {
        'v2_cells_at_least_frozen': v2_given >= frozen.get('cells_given', 0),
        'v2_rms_not_worse': v2_rms <= frozen_rms + 1e-12,
        'v2_wrong_not_worse': v2.get('wrong_cells', 0) <= frozen.get('wrong_cells', 0),
        'v2_wrong_at_most_10_percent': v2_given > 0 and v2.get('wrong_cells', 0) <= 0.10 * v2_given,
        'v2_no_extra_on_blank_truth': not v2.get('extra_cell_keys'),
    }
    result['all_code_gates'] = all(result.values())
    result['chine_line_on_drawn_chine'] = 'check on the overlay'
    return result
