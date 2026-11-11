"""Product body-plan side reading (polyline where it engages, crossing reader otherwise) on synthetic drawings."""
import numpy as np

from tests.test_body_plan_polyline import STATIONS, _crowded, round_bilge, v_bottom
from vessel_reconstruction import body_plan_polyline as bpp
from vessel_reconstruction import body_plan_reader as bpr
from vessel_reconstruction import body_plan_sides as sides


def _crossing_reading(ink, sheet, side):
    reading = bpr.measure_side(ink, sheet, side)
    identities = bpr.identities_by_rank(reading.chains, side.stations_outer_first)
    table = bpr.table_from_identities(reading, identities, sheet.pixels_per_metre, sheet.centre_column)
    return reading, identities, table


def test_round_bilge_half_is_the_crossing_readers_reading_unchanged():
    ink, sheet, side = round_bilge()
    reading, identities, table = _crossing_reading(ink, sheet, side)
    result = sides.read_side(ink, sheet, reading)
    assert not result.polyline_used
    assert result.table == table
    assert set(result.curves) == set(identities.values())
    for chain_index, station in identities.items():
        assert np.array_equal(result.curves[station], np.asarray(reading.chains[chain_index].path, dtype=float))
        assert result.identity_source[station] == sides.IDENTITY_RANK
    assert result.fairness_flags == bpr.fairness_flags(table, side.stations_outer_first,
                                                       sheet.waterlines_low_to_high())


def test_v_bottom_half_is_read_by_the_polyline_reader():
    ink, sheet, side = v_bottom()
    reading, _, _ = _crossing_reading(ink, sheet, side)
    result = sides.read_side(ink, sheet, reading)
    assert result.half.read and result.polyline_used
    assert sorted(result.curves) == [1, 2, 3, 4]
    assert set(result.identity_source.values()) == {sides.IDENTITY_POLYLINE}
    assert result.table == bpp.waterline_table({side.name: result.half}, sheet)
    # Each curve is the traced station: it reaches the knuckle and the low-deadrise bottom.
    for station, (_, knuckle, knuckle_row, _) in zip((4, 3, 2, 1), STATIONS):
        curve = result.curves[station]
        corner = np.hypot(curve[:, 0] - knuckle_row, curve[:, 1] - (sheet.centre_column + knuckle))
        assert corner.min() < 4


def test_crowded_stations_keep_their_names_through_the_product_reading():
    ink, sheet, side, (_, knuckle, _) = _crowded()
    reading, _, _ = _crossing_reading(ink, sheet, side)
    result = sides.read_side(ink, sheet, reading)
    assert sorted(result.curves) == [1, 2, 3, 4]
    knuckles = {s.station: s.offset_px(s.chine[1], sheet.centre_column) for s in result.half.stations}
    assert abs(knuckles[3] - knuckle) < 4 and abs(knuckles[2] - STATIONS[2][1]) < 4


def test_read_sheet_reads_every_half():
    ink, sheet, side = round_bilge()
    readings = {side.name: bpr.measure_side(ink, sheet, side)}
    assert set(sides.read_sheet(ink, sheet, readings)) == {side.name}
