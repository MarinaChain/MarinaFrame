"""Huddell holdout scorer (docs/TANKS_V2.md section 4): synthetic truth rows and built tanks."""
from __future__ import annotations

import json

import pytest

from benchmarks.tanks import holdout_score as hs
from benchmarks.tanks.raster_run import plan_view_roles
from vessel_reconstruction.tank_plan_raster import SheetSpec, ViewSpec

ROLES = {'inner_bottom': 'double_bottom', 'deck': 'above'}


def row(number, side, kind, content, cu_ft, name=None, unit='cu ft', note=None):
    entry = {'name': name or f'No. {number} {kind}', 'number': number, 'side': side, 'kind': kind,
             'content': content, 'printed_value': cu_ft, 'printed_unit': unit}
    if note is not None:
        entry['note'] = note
    return entry


def truth_of(rows, tmp_path):
    path = tmp_path / 'truth.json'
    path.write_text(json.dumps({'source': 'synthetic', 'rows': rows}))
    return hs.load_truth(path)


def tank(label, volume_m3, view='inner_bottom', built=True):
    return {'label': label, 'view': view, 'volume_m3': volume_m3, 'built': built}


# --------------------------------------------------------------------------- truth loader

def test_loader_converts_cubic_feet_and_us_gallons(tmp_path):
    truth = truth_of([row(1, 'C', 'double bottom', 'ballast', 1000.0),
                      row(2, 'C', 'deep tank', 'fuel oil', 1728.0, unit='US gal')], tmp_path)
    assert truth['rows'][0]['volume_m3'] == pytest.approx(28.3168)
    assert truth['rows'][1]['volume_m3'] == pytest.approx(231.0 * 0.0283168)  # 1728 gal = 231 ft3
    assert hs.US_GALLON_CU_FT == pytest.approx(0.1336805556, abs=1e-10)


def test_loader_leaves_out_rows_without_a_value_and_keeps_notes(tmp_path):
    truth = truth_of([row(5, 'P', 'double bottom', 'ballast', 900.0),
                      row(5, 'S', 'double bottom', 'ballast', 900.0, note='printed 5P'),
                      row(6, 'C', 'other', 'other', None)], tmp_path)
    assert len(truth['rows']) == 2
    assert truth['rows_without_capacity'] == 1
    assert truth['rows'][1]['side'] == 'S' and truth['rows'][1]['note'] == 'printed 5P'


@pytest.mark.parametrize('change', [
    {'side': 'X'}, {'kind': 'tank'}, {'content': 'water'}, {'printed_unit': 'bbl'},
    {'printed_value': -1}, {'number': 0}, {'number': '3'}, {'name': ''}, {'extra': 1}, {'note': 5},
])
def test_loader_rejects_malformed_rows(tmp_path, change):
    with pytest.raises(ValueError):
        truth_of([{**row(1, 'C', 'peak', 'ballast', 100.0), **change}], tmp_path)


def test_loader_rejects_a_missing_field(tmp_path):
    entry = row(1, 'C', 'peak', 'ballast', 100.0)
    del entry['printed_unit']
    with pytest.raises(ValueError):
        truth_of([entry], tmp_path)


# --------------------------------------------------------------------------- built identity

@pytest.mark.parametrize('label, role, kind', [
    ('No 2 Deep Tank', 'double_bottom', 'deep tank'),
    ('Fore Peak No 1', 'above', 'peak'),
    ('No 1 Settling Tank P', 'above', 'settling'),
    ('No 4 D.B. Tank', 'above', 'double bottom'),
    ('No 4 Double Bottom', 'above', 'double bottom'),
    ('No 4 P', 'double_bottom', 'double bottom'),
    ('No 4 P', 'above', 'other'),
])
def test_built_kind_from_label_words_then_plan_role(label, role, kind):
    assert hs.built_kind(label, role) == kind


def test_built_identity_number_and_side():
    assert hs.built_identity(tank('No 3 SB', 1.0), 'double_bottom') == \
        {'number': 3, 'side': 'S', 'kind': 'double bottom'}
    assert hs.built_identity(tank('No. 11p', 1.0), 'double_bottom')['side'] == 'P'
    assert hs.built_identity(tank('No 2', 1.0), 'double_bottom')['side'] is None
    assert hs.built_identity(tank('Fresh water', 1.0), 'above')['number'] is None


def test_plan_view_roles_follow_the_reader_view_names():
    one = SheetSpec([ViewSpec('profile', 'profile', (0, 0, 1, 1)),
                     ViewSpec('plan', 'plan', (0, 0, 1, 1), role='double_bottom')])
    two = SheetSpec([ViewSpec('deck', 'plan', (0, 0, 1, 1), role='above')])
    assert plan_view_roles([one]) == {'plan': 'double_bottom'}
    assert plan_view_roles([one, two]) == {'sheet1_plan': 'double_bottom', 'sheet2_deck': 'above'}


# --------------------------------------------------------------------------- matching

def match(rows, tanks, tmp_path):
    truth = truth_of(rows, tmp_path)
    result = hs.score(truth, tanks, ROLES)
    return [(entry['matched'], entry['built_label']) for entry in result['rows']]


def test_numbers_must_agree(tmp_path):
    assert match([row(3, 'C', 'double bottom', 'ballast', 100.0)], [tank('No 4', 2.8)], tmp_path) == \
        [(False, None)]


def test_a_row_without_a_number_does_not_match(tmp_path):
    assert match([row(None, 'C', 'peak', 'ballast', 100.0, name='Fore Peak')],
                 [tank('Fore Peak', 2.8, view='deck')], tmp_path) == [(False, None)]


def test_sides_must_agree_when_both_are_given(tmp_path):
    rows = [row(3, 'P', 'double bottom', 'ballast', 100.0), row(3, 'S', 'double bottom', 'ballast', 100.0)]
    assert match(rows, [tank('No 3 S', 2.8), tank('No 3 P', 2.8)], tmp_path) == \
        [(True, 'No 3 P'), (True, 'No 3 S')]
    assert match([row(3, 'C', 'double bottom', 'ballast', 100.0)], [tank('No 3 P', 2.8)], tmp_path) == \
        [(False, None)]


def test_a_label_without_a_side_matches_a_centre_line_row(tmp_path):
    rows = [row(1, 'C', 'double bottom', 'ballast', 100.0)]
    assert match(rows, [tank('No 1', 2.8)], tmp_path) == [(True, 'No 1')]


def test_a_label_without_a_side_matches_the_single_row_of_its_number_and_kind(tmp_path):
    rows = [row(2, 'P', 'deep tank', 'fuel oil', 100.0), row(2, 'P', 'double bottom', 'ballast', 100.0),
            row(2, 'S', 'double bottom', 'ballast', 100.0)]
    built = [tank('No 2 Deep', 2.8, view='deck'), tank('No 2', 2.8)]
    # The deep tank row is single for (2, deep tank); the double bottom rows are a P/S pair.
    assert match(rows, built, tmp_path) == [(True, 'No 2 Deep'), (False, None), (False, None)]


def test_kinds_must_agree(tmp_path):
    rows = [row(1, 'C', 'deep tank', 'fuel oil', 100.0)]
    assert match(rows, [tank('No 1', 2.8)], tmp_path) == [(False, None)]  # inner-bottom plan: double bottom
    assert match(rows, [tank('No 1', 2.8, view='deck')], tmp_path) == [(False, None)]  # above, no word: other
    assert match(rows, [tank('No 1 Deep Tank', 2.8)], tmp_path) == [(True, 'No 1 Deep Tank')]


def test_each_row_and_each_tank_match_at_most_once(tmp_path):
    rows = [row(1, 'C', 'double bottom', 'ballast', 100.0), row(1, 'C', 'double bottom', 'ballast', 100.0)]
    assert match(rows, [tank('No 1', 2.8)], tmp_path) == [(True, 'No 1'), (False, None)]
    one_row = [row(1, 'C', 'double bottom', 'ballast', 100.0)]
    result = hs.score(truth_of(one_row, tmp_path), [tank('No 1', 2.8), tank('No 1', 9.0)], ROLES)
    assert result['rows'][0]['built_m3'] == 2.8
    assert result['unmatched_tanks'] == ['No 1']


def test_tanks_not_built_are_ignored(tmp_path):
    rows = [row(1, 'C', 'double bottom', 'ballast', 100.0)]
    assert match(rows, [tank('No 1', 0.0, built=False)], tmp_path) == [(False, None)]


# --------------------------------------------------------------------------- metrics and decision

def ten_rows():
    """Ten truth rows of 1000 cu ft each (28.3168 m3): 4 fuel oil (2 'fuel oil or ballast'),
    3 ballast, 1 fresh water, 1 feed water, 1 other."""
    contents = ['fuel oil', 'fuel oil', 'fuel oil or ballast', 'fuel oil or ballast', 'ballast', 'ballast',
                'ballast', 'fresh water', 'feed water', 'other']
    return [row(n + 1, 'C', 'double bottom', content, 1000.0) for n, content in enumerate(contents)]


TRUTH_M3 = 28.3168


def test_metrics_and_a_passing_decision(tmp_path):
    factors = [1.05, 0.95, 1.09, 0.85, 1.15, 1.30, 1.00]  # tanks 1-7 built; 8-10 not read
    built = [tank(f'No {n + 1}', TRUTH_M3 * f) for n, f in enumerate(factors)]
    result = hs.score(truth_of(ten_rows(), tmp_path), built, ROLES)

    h1 = result['H1_coverage']
    assert (h1['matched_rows'], h1['truth_rows'], h1['value'], h1['met']) == (7, 10, 0.7, True)

    h2 = result['H2_volume_median_abs_rel']
    assert h2['value'] == pytest.approx(0.09)  # sorted |e|: 0, .05, .05, .09, .15, .15, .30
    assert (h2['n_matched'], h2['within_10pct'], h2['within_25pct'], h2['met']) == (7, 4, 6, True)

    h3 = result['H3_totals']
    fuel = h3['per_group']['fuel oil']
    assert fuel['rows'] == 4
    assert fuel['truth_m3'] == pytest.approx(4 * TRUTH_M3, abs=1e-3)
    assert fuel['rel_error'] == pytest.approx((1.05 + 0.95 + 1.09 + 0.85) / 4 - 1, abs=1e-4)
    assert h3['per_group']['ballast']['rel_error'] == pytest.approx((1.15 + 1.30 + 1.00) / 3 - 1, abs=1e-4)
    assert h3['per_group']['fresh and feed water']['rows'] == 2
    assert h3['per_group']['fresh and feed water']['rel_error'] == pytest.approx(-1.0)  # unmatched: 0 m3
    # Grand total over all ten rows, unmatched as 0: 7.39 / 10 - 1.
    assert h3['grand_total_rel_error'] == pytest.approx(-0.261, abs=1e-4)
    assert h3['met'] is False
    assert result['decision'] == {'passed': False, 'missed': ['H3']}

    # The same reading with the three missing tanks found at their volume passes all three.
    built += [tank(f'No {n}', TRUTH_M3) for n in (8, 9, 10)]
    result = hs.score(truth_of(ten_rows(), tmp_path), built, ROLES)
    assert result['H1_coverage']['value'] == 1.0
    assert result['H3_totals']['grand_total_rel_error'] == pytest.approx(0.039, abs=1e-4)
    assert result['decision'] == {'passed': True, 'missed': []}
    assert result['engineering_approved'] is False


def test_coverage_and_volume_failures_are_named(tmp_path):
    built = [tank(f'No {n}', TRUTH_M3 * 2.0) for n in (1, 2, 3, 4, 5)]  # 50 % coverage, +100 % each
    result = hs.score(truth_of(ten_rows(), tmp_path), built, ROLES)
    assert result['H1_coverage']['met'] is False
    assert result['H2_volume_median_abs_rel']['value'] == pytest.approx(1.0)
    assert result['H3_totals']['grand_total_rel_error'] == pytest.approx(0.0, abs=1e-4)
    assert result['decision'] == {'passed': False, 'missed': ['H1', 'H2']}


def test_targets_are_met_at_equality(tmp_path):
    rows = [row(1, 'C', 'double bottom', 'ballast', 1000.0), row(2, 'C', 'double bottom', 'ballast', 1000.0),
            row(3, 'C', 'double bottom', 'ballast', 1000.0), row(4, 'C', 'double bottom', 'ballast', 1000.0),
            row(5, 'C', 'double bottom', 'ballast', 1000.0)]
    # 3 of 5 matched (60 %); errors 0.20 each (median 0.20); total 3.6 / 5 - 1 = -0.28 misses H3.
    built = [tank(f'No {n}', TRUTH_M3 * 1.2) for n in (1, 2, 3)]
    result = hs.score(truth_of(rows, tmp_path), built, ROLES)
    assert result['H1_coverage']['met'] is True
    assert result['H2_volume_median_abs_rel']['met'] is True
    assert result['decision']['missed'] == ['H3']


def test_no_match_fails_every_metric(tmp_path):
    result = hs.score(truth_of(ten_rows(), tmp_path), [], ROLES)
    assert result['H2_volume_median_abs_rel']['value'] is None
    assert result['H3_totals']['grand_total_rel_error'] == pytest.approx(-1.0)
    assert result['decision'] == {'passed': False, 'missed': ['H1', 'H2', 'H3']}
