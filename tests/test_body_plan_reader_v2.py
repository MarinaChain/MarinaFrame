"""Reader v2 on a synthetic hard-chine drawing made with PIL; no scan or truth table."""
import numpy as np
import pytest

from tests.test_body_plan_chine_line import CENTRE, STATION_COLUMNS, WATERLINES, chine_row, drawing
from vessel_reconstruction import body_plan_reader as bpr
from vessel_reconstruction import body_plan_reader_v2 as v2


def read(sign=1, **options):
    ink, sheet, side = drawing(sign, **options)
    return v2.read_sheet(ink, sheet), sheet


@pytest.mark.parametrize('sign', [1, -1])
def test_one_waterline_pieces_below_the_chine_get_their_station(sign):
    readings, sheet = read(sign)
    table, _ = v2.sheet_table(readings, sheet)
    stations = len(STATION_COLUMNS)
    for rank, column in enumerate(reversed(STATION_COLUMNS)):
        station = stations - rank  # outermost first: the largest number
        lower_column = column - 250 * (1000 - chine_row(column)) / (1100 - chine_row(column))
        expected = (lower_column - CENTRE) / sheet.pixels_per_metre
        assert table[(station, 'bottom')] == pytest.approx(expected, abs=0.08)
        assert (station, 'top') in table and (station, 'middle') in table


def test_no_heavy_line_keeps_the_frozen_table():
    ink, sheet, side = drawing(1, heavy_line=False)
    readings = v2.read_sheet(ink, sheet)
    assert not readings['fore'].uses_chine
    reading = readings['fore'].base
    identities = bpr.identities_by_rank(reading.chains, side.stations_outer_first)
    frozen = bpr.table_from_identities(reading, identities, sheet.pixels_per_metre, sheet.centre_column)
    assert v2.side_table(readings['fore'], sheet.pixels_per_metre, sheet.centre_column) == frozen


def test_a_stroke_along_a_waterline_is_not_a_chine():
    ink, sheet, side = drawing(1)
    reading = bpr.measure_side(ink, sheet, side)
    line = v2.chine_line.find_chine_line(ink, sheet, reading)
    flat = v2.chine_line.ChineLine(np.column_stack([np.full(200, 550.0), np.arange(200) + 300.0]), 3, 5.0)
    assert v2.lies_on_waterline(flat, sheet)
    assert not v2.lies_on_waterline(line, sheet)


def test_two_crossings_claiming_one_cell_are_left_out():
    ink, sheet, side = drawing(1)
    readings = v2.read_sheet(ink, sheet)
    side_reading = readings['fore']
    assert side_reading.uses_chine
    assert all(a['reason'] for a in side_reading.abstained)
