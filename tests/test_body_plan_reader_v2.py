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


def test_the_chine_part_stops_where_the_line_runs_on_along_a_drawn_waterline():
    from types import SimpleNamespace
    from PIL import Image, ImageDraw
    image = Image.new('L', (1700, 900), 255)
    draw = ImageDraw.Draw(image)
    draw.line([(50, 600), (1650, 600)], fill=0, width=3)  # a drawn (painted) waterline, not a measuring row
    chine = [(c, 650 - 40 * (c - 300) / 500) for c in range(300, 801)]  # the chine, rising to the waterline
    draw.line(chine, fill=0, width=5)
    ink = np.asarray(image) < 128
    side = bpr.SideLayout('fore', 1, (3, 2, 1))
    sheet = bpr.SheetLayout(100.0, 100.0, {'w': 300}, 1500, (side,))
    points = np.array([(row, c) for c, row in chine] + [(600.0, c) for c in range(801, 1400)], dtype=float)
    line = v2.chine_line.ChineLine(points, 3, 5.0)
    reading = SimpleNamespace(layout=side, stations={})
    first, last = v2.chine_columns(ink, line, sheet, reading)
    assert first == pytest.approx(300, abs=2)
    assert 790 <= last <= 1000  # not along the waterline to column 1400
    straight = v2.chine_line.ChineLine(np.array([(650 - 40 * (c - 300) / 500, c) for c in range(300, 801)],
                                                dtype=float), 3, 5.0)
    assert v2.chine_columns(ink, straight, sheet, reading) == (300.0, 800.0)
