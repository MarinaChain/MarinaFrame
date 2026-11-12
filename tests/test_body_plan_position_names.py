"""Independent shape identity must survive gaps without shifting other names."""
import numpy as np

from vessel_reconstruction import body_plan_position_names as names


def shape(value):
    return {'low': value, 'middle': value + 0.1, 'high': value + 0.2}


def test_missed_station_does_not_shift_names():
    result = names.match_sections([shape(1), shape(0.4)], {7: shape(1), 5: shape(0.7), 2: shape(0.4)})
    assert result.names == {0: 7, 1: 2}


def test_extra_section_is_unnamed_without_shifting_following_sections():
    result = names.match_sections([shape(1), shape(0.8), shape(0.4)], {7: shape(1), 2: shape(0.4)})
    assert result.names == {0: 7, 2: 2}
    assert result.unnamed == [1]


def test_uneven_station_positions_are_not_interpolated():
    result = names.match_sections([shape(0.91), shape(0.3)], {10: shape(1), 9: shape(0.91), 1: shape(0.3)})
    assert result.names == {0: 9, 1: 1}


def test_near_tie_is_unnamed():
    result = names.match_sections([shape(0.99)], {7: shape(1), 6: shape(0.97)})
    assert result.names == {}
    assert result.unnamed == [0]


def test_equal_global_claims_are_both_unnamed():
    result = names.match_sections([shape(1), shape(1)], {7: shape(1)})
    assert result.names == {}
    assert result.unnamed == [0, 1]


def test_alignment_preserves_order_instead_of_independent_nearest_matching():
    result = names.match_sections([shape(0.4), shape(1)], {7: shape(1), 2: shape(0.4)})
    assert len(result.names) <= 1


def test_missing_evidence_never_falls_back_to_rank():
    assert names.match_sections([shape(1)], {}).names == {}
    assert names.match_sections([{'low': 1}], {7: shape(1)}).names == {}


def test_nonfinite_samples_are_not_evidence():
    assert names.match_sections([shape(np.nan)], {7: shape(1)}).names == {}


def test_labels_require_unique_geometric_claims():
    sides = [np.array([[0., 10.], [10., 10.]]), np.array([[0., 30.], [10., 30.]])]
    assert names.match_labels(sides, [(7, 5., 11.), (2, 5., 29.)], {7, 2}, 1.) == {0: 7, 1: 2}
    assert names.match_labels(sides, [(7, 5., 11.), (7, 5., 29.)], {7, 2}, 1.) == {}
    assert names.match_labels(sides, [(99, 5., 11.)], {7, 2}, 1.) == {}


def test_plan_vectors_use_drawn_station_columns_without_filling_abstentions():
    from types import SimpleNamespace
    plan = SimpleNamespace(x_m=np.array([0., 0.2, 1.8]), curves={
        'wl0': {'z_m': 0., 'y_m': np.array([1., 2., 3.]), 'status': ['tracked'] * 3},
        'wl1': {'z_m': 1., 'y_m': np.array([2., 3., 4.]), 'status': ['tracked', 'abstain_shared_ink', 'tracked']},
        'deck': {'z_m': None, 'y_m': np.array([9., 9., 9.]), 'status': ['tracked'] * 3}})
    assert names.plan_vectors(plan, {7: 0.2, 2: 1.8, 1: 3.}) == {7: {0.: 2.}, 2: {0.: 3., 1.: 4.}, 1: {}}


def test_half_adapter_clears_rank_names_when_evidence_is_missing():
    from vessel_reconstruction import body_plan_polyline as polyline
    from vessel_reconstruction import body_plan_reader as reader
    section = polyline.StationPolyline('fore', 1, np.array([[30., 10.], [0., 20.]]),
                                      0, (30., 10.), 70., station=7)
    half = polyline.HalfReading('fore', True, stations=[section], line_width_px=1.)
    layout = reader.SheetLayout(0., 10., {'a': 25., 'b': 15., 'c': 5.}, 30, ())
    result, report = names.name_half(half, layout, {0.: 25., 1.: 15., 2.: 5.}, {}, [])
    assert result.read
    assert result.stations == []
    assert result.unnamed[0].station is None
    assert section.station == 7  # experimental route must not mutate the baseline
    assert report['unnamed_sections'] == 1
    assert report['source'] == 'no independent identity evidence'


def test_half_adapter_handles_levels_outside_a_short_section():
    from vessel_reconstruction import body_plan_polyline as polyline
    from vessel_reconstruction import body_plan_reader as reader
    section = polyline.StationPolyline('fore', 1, np.array([[30., 10.], [20., 20.]]),
                                      0, (30., 10.), 70., station=7)
    half = polyline.HalfReading('fore', True, stations=[section], line_width_px=1.)
    layout = reader.SheetLayout(0., 10., {}, 30, ())
    result, report = names.name_half(half, layout, {0.: 25., 1.: 15., 2.: 5.}, {}, [])
    assert result.stations == []
    assert report['unnamed_sections'] == 1


def test_label_between_two_sides_stays_unnamed():
    sides = [np.array([[0., 10.], [10., 10.]]), np.array([[0., 12.], [10., 12.]])]
    assert names.match_labels(sides, [(7, 5., 11.)], {7}, 1.) == {}
