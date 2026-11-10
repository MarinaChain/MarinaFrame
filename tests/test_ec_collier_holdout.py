"""Synthetic tests for the E. C. COLLIER calibration and point-offset scorer (no sheet, no truth)."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from benchmarks.ec_collier import holdout_value as cal
from benchmarks.ec_collier import point_score as ps

LABELS = ('a', 'b', 'c', 'd')


def _truth(**points):
    """points: name=(station, point, height m or None, half-breadth m or None)."""
    return {(s, p): {'height': h, 'half_breadth': y} for s, p, h, y in points.values()}


# ---------------------------------------------------------------- calibration

def test_measuring_rows_are_a_fixed_grid_from_the_base():
    heights = [cal.MEASURING_HEIGHTS_FT[label] for label in cal.WATERLINES]
    assert heights == sorted(heights)
    steps = [b - a for a, b in zip(heights, heights[1:])]
    assert max(abs(step - cal.MEASURING_STEP_FT) for step in steps) < 0.01
    for label in cal.WATERLINES:  # each label states its own grid height
        assert ps.printed.printed_half_breadth(label) / 0.3048 == pytest.approx(cal.MEASURING_HEIGHTS_FT[label],
                                                                                abs=0.01)


def test_sides_cover_every_station_once():
    layout = cal.sheet_layout()
    aft, fore = layout.sides
    assert (aft.name, aft.sign, fore.name, fore.sign) == ('aft', -1, 'fore', 1)
    assert sorted(aft.stations_outer_first + fore.stations_outer_first) == list(cal.STATIONS)
    assert layout.waterlines_low_to_high() == list(cal.WATERLINES)


def test_height_uses_the_sloped_base_line():
    assert cal.height_ft(cal.BASE_ROW, cal.CENTRE_COLUMN) == 0
    assert cal.height_ft(cal.BASE_ROW - cal.PIXELS_PER_FT, cal.CENTRE_COLUMN) == pytest.approx(1.0)
    far = cal.CENTRE_COLUMN + 1000
    assert cal.height_ft(cal.base_row_at(far), far) == pytest.approx(0.0)


# ---------------------------------------------------------------- interpolation

def test_value_is_interpolated_between_neighbouring_rows():
    cells = {'a': (1.0, 2.0), 'b': (2.0, 3.0), 'c': (3.0, 3.5)}
    assert ps.value_at(cells, 1.5, LABELS) == pytest.approx(2.5)
    assert ps.value_at(cells, 2.5, LABELS) == pytest.approx(3.25)
    assert ps.value_at(cells, 2.0, LABELS) == pytest.approx(3.0)


def test_no_extrapolation_outside_the_measured_rows():
    cells = {'a': (1.0, 2.0), 'b': (2.0, 3.0)}
    assert ps.value_at(cells, 0.9, LABELS) is None
    assert ps.value_at(cells, 2.1, LABELS) is None


def test_a_missing_row_gives_no_cell():
    cells = {'a': (1.0, 2.0), 'c': (3.0, 4.0)}  # row b has no crossing for this station
    assert ps.value_at(cells, 2.0, LABELS) is None


def test_measured_rows_not_nominal_rows_set_the_weights():
    cells = {'a': (1.1, 2.0), 'b': (2.1, 3.0)}  # a drawn line moved both crossings up
    assert ps.value_at(cells, 1.6, LABELS) == pytest.approx(2.5)
    assert ps.value_at(cells, 1.05, LABELS) is None


# ---------------------------------------------------------------- truth

def test_truth_tables_of_strings_and_blanks():
    data = {'stations': list(range(11)),
            'heights_above_base': {'SHEER': ['5-0-0'] * 11, 'CHINE': ['2-0-0'] * 10 + [None],
                                   'RABBET': [None] + ['1-0-0'] * 10},
            'half_breadths': {'SHEER': ['6-0-0'] * 11, 'CHINE': ['5-0 0'] * 10 + [''],
                              'RABBET': [None] + ['0-2-0'] * 10}}
    truth = ps.parse_truth(data)
    assert truth[(0, 'chine')]['half_breadth'] == pytest.approx(5 * 0.3048)
    assert truth[(10, 'chine')] == {'height': None, 'half_breadth': None}
    assert len(ps.truth_cells(truth)) == 31


def test_truth_records_in_metres_and_feet():
    truth = ps.parse_truth({'cells': [
        {'station': 3, 'point': 'Chine', 'height_m': 0.8, 'half_breadth_m': 2.3},
        {'station': 4, 'point': 'sheer', 'height_ft': 6.0, 'half_breadth_ft': 8.5}]})
    assert truth[(3, 'chine')] == {'height': 0.8, 'half_breadth': 2.3}
    assert truth[(4, 'sheer')]['height'] == pytest.approx(6.0 * 0.3048)


def test_truth_in_wrong_units_is_refused():
    with pytest.raises(ValueError):
        ps.parse_truth({'cells': [{'station': 3, 'point': 'chine', 'height': 30.0, 'half_breadth': 70.0}]})


# ---------------------------------------------------------------- scoring

def test_score_counts_cells_wrong_chine_extra_and_missing():
    truth = _truth(s1=(1, 'sheer', 2.5, 3.0), c1=(1, 'chine', 1.5, 2.6), r1=(1, 'rabbet', 0.5, 0.1),
                   c2=(2, 'chine', 1.5, None), r2=(2, 'rabbet', None, 0.1))
    samples = {1: {'a': (1.0, 2.0), 'b': (2.0, 3.0), 'c': (3.0, 3.2)},
               2: {'a': (1.0, 2.0), 'b': (2.0, 3.0)}}
    result = ps.score(samples, truth, LABELS)
    assert result['truth_cells'] == 3
    assert result['cells_given'] == 2  # the rabbet height 0.5 is below the lowest row
    assert result['errors_m']['1/sheer'] == pytest.approx(0.1)
    assert result['errors_m']['1/chine'] == pytest.approx(-0.1)
    assert result['rms_m'] == pytest.approx(0.1)
    assert result['wrong_cells'] == 0
    assert result['chine_only'] == {'cells_given': 1, 'rms_m': pytest.approx(0.1),
                                    'max_abs_m': pytest.approx(0.1), 'wrong_cells': 0, 'truth_cells': 1}
    assert result['missing_cell_keys'] == [[1, 'rabbet']]
    assert result['extra_cell_keys'] == [[2, 'chine']]
    assert result['unevaluable_blank_points'] == [[2, 'rabbet']]


def test_wrong_cell_band_is_0_15_m():
    truth = _truth(s=(1, 'sheer', 1.5, 2.0), c=(1, 'chine', 1.25, 2.0))
    samples = {1: {'a': (1.0, 2.2), 'b': (2.0, 2.2)}}
    assert ps.score(samples, truth, LABELS)['wrong_cells'] == 2


def test_identity_error_when_a_curve_fits_the_neighbour():
    truth = _truth(s1=(1, 'sheer', 2.0, 3.0), c1=(1, 'chine', 1.0, 2.0),
                   s2=(2, 'sheer', 2.0, 2.5), c2=(2, 'chine', 1.0, 1.5))
    swapped = {1: {'a': (1.0, 1.5), 'b': (2.0, 2.5)}, 2: {'a': (1.0, 2.0), 'b': (2.0, 3.0)}}
    right = {1: {'a': (1.0, 2.0), 'b': (2.0, 3.0)}, 2: {'a': (1.0, 1.5), 'b': (2.0, 2.5)}}
    assert ps.score(swapped, truth, LABELS)['identity_errors'] == [1, 2]
    assert ps.score(right, truth, LABELS)['identity_errors'] == []


def test_gates():
    frozen = {'cells_given': 10, 'rms_m': 0.10, 'wrong_cells': 2}
    good = {'cells_given': 12, 'rms_m': 0.05, 'wrong_cells': 1, 'extra_cell_keys': []}
    assert ps.gates(frozen, good)['all_code_gates']
    bad = dict(good, wrong_cells=2)  # 2 of 12 is above 10 percent
    assert not ps.gates(frozen, bad)['all_code_gates']
    extra = dict(good, extra_cell_keys=[[10, 'chine']])
    assert not ps.gates(frozen, extra)['v2_no_extra_on_blank_truth']


# ---------------------------------------------------------------- reader adapters

def _crossing(row, x):
    return SimpleNamespace(row=row, x_px=x, offset_px=lambda centre, sign: sign * (x - centre))


def test_samples_from_frozen_identities_keep_the_outer_chain():
    layout = SimpleNamespace(centre_column=cal.CENTRE_COLUMN, pixels_per_metre=cal.PIXELS_PER_M)
    label = cal.WATERLINES[0]
    row = cal.MEASURING_ROWS[label]
    stations = {label: [_crossing(row, cal.CENTRE_COLUMN + 600), _crossing(row, cal.CENTRE_COLUMN + 300)]}
    chains = [SimpleNamespace(nodes={label: 0}), SimpleNamespace(nodes={label: 1})]
    reading = SimpleNamespace(chains=chains, stations=stations, layout=SimpleNamespace(sign=1))
    found = ps.samples_from_identities(reading, {0: 5, 1: 5}, layout)
    height, half_breadth = found[5][label]
    assert half_breadth == pytest.approx(600 / cal.PIXELS_PER_M)
    assert height == pytest.approx(cal.height_ft(row, cal.CENTRE_COLUMN + 600) * 0.3048)


def test_samples_v2_use_cells_on_a_chine_side_and_identities_otherwise():
    layout = SimpleNamespace(centre_column=cal.CENTRE_COLUMN, pixels_per_metre=cal.PIXELS_PER_M)
    label = cal.WATERLINES[2]
    row = cal.MEASURING_ROWS[label]
    base = SimpleNamespace(stations={label: [_crossing(row, cal.CENTRE_COLUMN - 450)]},
                           chains=[SimpleNamespace(nodes={label: 0})], layout=SimpleNamespace(sign=-1))
    chine_side = SimpleNamespace(uses_chine=True, base=base, identities={0: 4},
                                 cells={(2, label): SimpleNamespace(waterline=label, index=0)})
    plain_side = SimpleNamespace(uses_chine=False, base=base, identities={0: 4}, cells={})
    assert set(ps.samples_v2({'aft': chine_side}, layout)) == {2}
    assert set(ps.samples_v2({'aft': plain_side}, layout)) == {4}
    assert ps.samples_v2({'aft': chine_side}, layout)[2][label][1] == pytest.approx(450 / cal.PIXELS_PER_M)
