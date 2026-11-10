"""Synthetic tests for the WHITE GULL and COLLEEN calibrations and scorer (no sheet, no truth)."""
from __future__ import annotations

import hashlib
import json
from types import SimpleNamespace

import numpy as np
import pytest

from benchmarks.colleen import holdout_value as colleen
from benchmarks.deadrise_holdout import score as sc
from benchmarks.white_gull import holdout_value as gull

FT = 0.3048


# ---------------------------------------------------------------- calibration

@pytest.mark.parametrize('cal', [gull, colleen])
def test_sides_cover_every_station_once_and_rows_run_low_to_high(cal):
    layout = cal.sheet_layout()
    names = sorted(side.name for side in layout.sides)
    assert names == ['aft', 'fore']
    assert sorted(sum((side.stations_outer_first for side in layout.sides), ())) == list(cal.STATIONS)
    assert layout.waterlines_low_to_high() == list(cal.WATERLINES)
    heights = [cal.height_ft(cal.WATERLINE_ROWS[label], cal.CENTRE_COLUMN) for label in cal.WATERLINES]
    for label, height in zip(cal.WATERLINES, heights):
        assert height == pytest.approx(cal.WATERLINE_HEIGHTS_FT[label], abs=0.01)
    assert cal.TRUTH_SHA256 is None  # given by the PM before the run


def test_white_gull_sides_and_waterlines():
    fore, aft = gull.sheet_layout().sides
    assert (fore.name, fore.sign, fore.stations_outer_first) == ('fore', -1, (5, 4, 3, 2, 1))
    assert (aft.name, aft.sign, aft.stations_outer_first) == ('aft', 1, (6, 7, 8, 9, 10))
    assert gull.WATERLINES == ('W1', 'W2', 'W3', 'W4', 'W5', 'W6')
    assert all(abs(abs(c - gull.CENTRE_COLUMN) % gull.PIXELS_PER_FT) < 1e-9
               for c in gull.FORE_GRID_COLUMNS + gull.AFT_GRID_COLUMNS)


def test_colleen_grid_goes_below_the_base_line():
    aft, fore = colleen.sheet_layout().sides
    assert (aft.name, aft.sign, fore.name, fore.sign) == ('aft', -1, 'fore', 1)
    assert colleen.WATERLINES[0] == '-2-0-0' and colleen.WATERLINES[-1] == '3-6-0'
    assert colleen.WATERLINE_HEIGHTS_FT['-0-6-0'] == pytest.approx(-0.5)
    assert colleen.height_ft(colleen.BASE_ROW + 300, 100.0) == pytest.approx(-1.0)
    for label in colleen.WATERLINES:  # every label states its own signed height
        assert sc.signed_height_ft(label) == pytest.approx(colleen.WATERLINE_HEIGHTS_FT[label])


# ---------------------------------------------------------------- printed values

def test_signed_height_and_waterline_matching():
    assert sc.signed_height_ft('1-6-4') == pytest.approx(1 + 6.5 / 12)
    assert sc.signed_height_ft('-0-9-0') == pytest.approx(-0.75)
    assert sc.match_waterline('W3', gull) == 'W3'
    assert sc.match_waterline('3-0-0', gull) == 'W3'
    assert sc.match_waterline('-1-0-0', colleen) == '-1-0-0'
    assert sc.match_waterline('-1 0 0', colleen) == '-1-0-0'
    with pytest.raises(ValueError):
        sc.match_waterline('1-3-0', colleen)  # 1.25 ft is not a measuring row
    with pytest.raises(ValueError):
        sc.match_waterline('WL A', gull)


# ---------------------------------------------------------------- truth

def _gull_truth(**changes):
    data = {'units': 'ft-in-eighths', 'stations': list(range(1, 11)),
            'waterlines': {'W2': ['3-0-0'] * 9 + [None], 'W3': ['4-0-0'] * 10},
            'heights': {'Sheer': ['5-6-0'] * 10, 'Chine': ['2-3-0'] * 10, 'Rabbet': [None] + ['0-9-0'] * 9},
            'half_breadths': {'Sheer': ['6-0-0'] * 10, 'Chine': ['5-0 0'] * 9 + [None], 'Rabbet': ['0-2-0'] * 10},
            'unsure': []}
    data.update(changes)
    return data


def test_truth_format_with_blanks_and_point_names_in_any_case():
    truth = sc.parse_truth(_gull_truth(), gull)
    assert truth['waterlines'][(1, 'W2')] == pytest.approx(3 * FT)
    assert truth['waterlines'][(10, 'W2')] is None
    assert truth['points'][(2, 'chine')] == {'height': pytest.approx(2.25 * FT), 'half_breadth': pytest.approx(5 * FT)}
    assert truth['points'][(1, 'rabbet')]['height'] is None


def test_waterline_rows_given_as_heights_and_negative_point_heights():
    data = {'units': 'ft-in-eighths', 'stations': list(range(1, 10)),
            'waterlines': {'-1-0-0': ['1-0-0'] * 9, '1-0-0': ['3-0-0'] * 9},
            'heights': {'rabbet': ['-1-9-0'] * 9}, 'half_breadths': {'rabbet': ['0-1-4'] * 9}}
    truth = sc.parse_truth(data, colleen)
    assert set(w for _, w in truth['waterlines']) == {'-1-0-0', '1-0-0'}
    assert truth['points'][(3, 'rabbet')]['height'] == pytest.approx(-1.75 * FT)


def test_bad_truth_is_refused():
    with pytest.raises(ValueError):
        sc.parse_truth(_gull_truth(units='m'), gull)
    with pytest.raises(ValueError):
        sc.parse_truth(_gull_truth(stations=list(range(0, 11))), gull)
    with pytest.raises(ValueError):
        sc.parse_truth(_gull_truth(waterlines={'W2': ['3-0-0'] * 9}), gull)  # one station short
    with pytest.raises(ValueError):
        sc.parse_truth(_gull_truth(waterlines={'W2': ['3-0-0'] * 10, '2-0-0': ['3-0-0'] * 10}), gull)
    with pytest.raises(ValueError):
        sc.parse_truth(_gull_truth(heights={'sheer': ['5-0-0'] * 10}), gull)  # points differ
    with pytest.raises(ValueError):
        sc.parse_truth(_gull_truth(heights={'keel': ['5-0-0'] * 10}, half_breadths={'keel': ['1-0-0'] * 10}), gull)
    with pytest.raises(ValueError):
        sc.parse_truth(_gull_truth(waterlines={'W2': ['15-0-0'] * 10}), gull)  # 4.6 m half-breadth


def test_truth_fingerprint(tmp_path):
    path = tmp_path / 'truth.json'
    path.write_text(json.dumps(_gull_truth()))
    with pytest.raises(SystemExit):  # no sha256 recorded yet
        sc.load_truth(path, gull)
    with pytest.raises(SystemExit):
        sc.load_truth(path, SimpleNamespace(**{**vars(gull), 'TRUTH_SHA256': '0' * 64}))
    frozen = SimpleNamespace(**{**vars(gull), 'TRUTH_SHA256': hashlib.sha256(path.read_bytes()).hexdigest()})
    assert len(sc.load_truth(path, frozen)['waterlines']) == 20


# ---------------------------------------------------------------- waterline cells

def test_waterline_score_counts_wrong_missing_and_extra_on_printed_rows_only():
    truth = {'waterlines': {(1, 'W2'): 1.0, (2, 'W2'): 0.8, (3, 'W2'): None, (1, 'W3'): 1.2, (2, 'W3'): 1.0},
             'points': {}}
    table = {(1, 'W2'): 1.02, (2, 'W2'): 1.0, (3, 'W2'): 0.5, (1, 'W3'): 1.2, (1, 'W5'): 2.0}
    result = sc.score_waterlines(table, truth, gull)
    assert result['truth_cells'] == 4
    assert result['cells_given'] == 3
    assert result['wrong_cells'] == 1  # station 2 W2 is 0.2 m out
    assert result['missing_cell_keys'] == [[2, 'W3']]
    assert result['extra_cell_keys'] == [[3, 'W2']]  # W5 is not a printed row, so it is not extra
    assert result['extra_cells'] == 1


# ---------------------------------------------------------------- point cells

def test_value_at_uses_consecutive_samples_only():
    curve = [(-0.6, 0.05), (-0.3, 0.4), None, (0.3, 1.0), (0.6, 1.1)]
    assert sc.value_at(curve, -0.45) == pytest.approx(0.225)
    assert sc.value_at(curve, 0.0) is None  # a row without a crossing breaks the curve
    assert sc.value_at(curve, 0.45) == pytest.approx(1.05)
    assert sc.value_at(curve, 0.7) is None  # no extrapolation


def test_point_score_by_point_identity_extra_and_missing():
    points = {(1, 'sheer'): {'height': 1.5, 'half_breadth': 1.0}, (1, 'chine'): {'height': 0.5, 'half_breadth': 0.9},
              (1, 'rabbet'): {'height': -0.5, 'half_breadth': 0.05},
              (2, 'sheer'): {'height': 1.5, 'half_breadth': 1.2}, (2, 'chine'): {'height': 0.5, 'half_breadth': 1.1},
              (2, 'rabbet'): {'height': None, 'half_breadth': 0.05}, (3, 'chine'): {'height': 0.5, 'half_breadth': None}}
    truth = {'waterlines': {}, 'points': points}
    curves = {1: [(0.0, 0.8), (1.0, 0.95), (2.0, 1.05)],
              2: [(0.0, 1.0), (1.0, 1.15), (2.0, 1.25)], 3: [(0.0, 1.0), (1.0, 1.0)]}
    result = sc.score_points(curves, truth, colleen)
    assert result['truth_cells'] == 5
    assert result['cells_given'] == 4  # rabbet of 1 is below its lowest sample
    assert result['errors_m']['1/chine'] == pytest.approx(-0.025)
    assert result['chine_only']['cells_given'] == 2
    assert result['sheer_only']['truth_cells'] == 2
    assert result['missing_cell_keys'] == [[1, 'rabbet']]
    assert result['extra_cell_keys'] == [[3, 'chine']]
    assert result['unevaluable_blank_points'] == [[2, 'rabbet']]
    assert result['identity_errors'] == []
    swapped = {1: curves[2], 2: curves[1]}
    assert sc.score_points(swapped, truth, colleen)['identity_errors'] == [1, 2]


# ---------------------------------------------------------------- reader adapters

def _crossing(row, x):
    return SimpleNamespace(row=row, x_px=x, offset_px=lambda centre, sign: sign * (x - centre))


def _layout(cal):
    return SimpleNamespace(centre_column=cal.CENTRE_COLUMN, pixels_per_metre=cal.PIXELS_PER_M)


def test_frozen_curves_follow_the_measuring_rows_with_gaps():
    w1, w3 = 'W1', 'W3'
    stations = {w1: [_crossing(gull.WATERLINE_ROWS[w1], gull.CENTRE_COLUMN - 400)],
                w3: [_crossing(gull.WATERLINE_ROWS[w3], gull.CENTRE_COLUMN - 600)]}
    reading = SimpleNamespace(chains=[SimpleNamespace(nodes={w1: 0, w3: 0})], stations=stations,
                              layout=SimpleNamespace(sign=-1))
    curves = sc.frozen_curves({'fore': reading}, {'fore': {0: 3}}, _layout(gull), gull)
    curve = curves[3]
    assert len(curve) == len(gull.WATERLINES) and curve[1] is None
    assert curve[0] == (pytest.approx(1.0 * FT), pytest.approx(400 / gull.PIXELS_PER_M))
    assert curve[2][0] == pytest.approx(3.0 * FT)


def test_polyline_curves_take_read_halves_and_keep_frozen_on_declined_halves():
    label = '0-0-0'
    row = colleen.WATERLINE_ROWS[label]
    reading = SimpleNamespace(chains=[SimpleNamespace(nodes={label: 0})],
                              stations={label: [_crossing(row, colleen.CENTRE_COLUMN - 500)]},
                              layout=SimpleNamespace(sign=-1))
    points = np.array([[row + 300, colleen.CENTRE_COLUMN + 30], [row, colleen.CENTRE_COLUMN + 900]])
    station = SimpleNamespace(station=4, points=points,
                              offset_px=lambda column, centre: column - centre)
    halves = {'aft': SimpleNamespace(read=False, stations=[]), 'fore': SimpleNamespace(read=True, stations=[station])}
    readings = {'aft': reading, 'fore': reading}
    curves = sc.polyline_curves(halves, readings, {'aft': {0: 8}, 'fore': {0: 2}}, _layout(colleen), colleen)
    assert set(curves) == {8, 4}  # the frozen station 2 of the read half is replaced
    assert curves[4][0] == (pytest.approx(-1.0 * FT), pytest.approx(30 / colleen.PIXELS_PER_M))
    assert sc.value_at(curves[4], -0.5 * FT) == pytest.approx(465 / colleen.PIXELS_PER_M)
    assert curves[8][colleen.WATERLINES.index(label)][1] == pytest.approx(500 / colleen.PIXELS_PER_M)


def test_gates():
    frozen = {'cells_given': 10, 'rms_m': 0.10, 'wrong_cells': 2}
    good = {'cells_given': 12, 'rms_m': 0.05, 'wrong_cells': 1, 'extra_cell_keys': []}
    assert sc.gates(frozen, good)['all_code_gates']
    assert not sc.gates(frozen, dict(good, wrong_cells=2))['all_code_gates']  # 2 of 12 > 10 %
    assert not sc.gates(frozen, dict(good, extra_cell_keys=[[3, 'W2']]))['no_extra_on_blank_truth']
    assert not sc.gates(frozen, dict(good, cells_given=9))['cells_at_least_frozen']
