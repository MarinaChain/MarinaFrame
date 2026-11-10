"""V-bottom polyline reader on synthetic body plans drawn with PIL; no scan or truth table."""
import numpy as np
import pytest
from PIL import Image, ImageDraw

from vessel_reconstruction import body_plan_polyline as bpp
from vessel_reconstruction import body_plan_reader as bpr

WIDTH, HEIGHT = 1600, 1000
LINE = 5
SHEER_ROW = 200
# Outermost station first: (side offset at the sheer, knuckle offset, knuckle row, rabbet row).
STATIONS = ((1260, 1200, 700, 800), (1050, 1000, 690, 795), (790, 750, 670, 790), (480, 450, 640, 785))
RABBET_OFFSET = 30
MEASURING_ROWS = {f'r{row}': row for row in range(250, 900, 75)}


def _canvas(sign):
    image = Image.new('L', (WIDTH, HEIGHT), 255)
    centre = 100 if sign == 1 else WIDTH - 100
    return image, ImageDraw.Draw(image), centre, (lambda offset, row: (centre + sign * offset, row))


def _layout(centre, sign, count):
    side = bpr.SideLayout('fore', sign, tuple(range(count, 0, -1)))
    return bpr.SheetLayout(centre, 100.0, dict(MEASURING_ROWS), 1400, (side,)), side


def v_bottom(sign=1, stations=STATIONS, chine_curve=True):
    """Hard-chine half: straight sides, knuckles, straight low-deadrise bottoms to a keel."""
    image, draw, centre, point = _canvas(sign)
    draw.line([(centre, 50), (centre, 950)], fill=0, width=2)  # centreline
    for offset in (-RABBET_OFFSET, RABBET_OFFSET):  # keel outline
        draw.line([point(offset, 760), point(offset, 900)], fill=0, width=LINE)
    draw.line([(0, 500), (WIDTH - 1, 500)], fill=0, width=2)  # a drawn waterline crossing the sides
    for sheer, knuckle, knuckle_row, rabbet_row in stations:
        draw.line([point(sheer, SHEER_ROW), point(knuckle, knuckle_row)], fill=0, width=LINE)
        draw.line([point(knuckle, knuckle_row), point(RABBET_OFFSET, rabbet_row)], fill=0, width=LINE)
    if chine_curve:
        draw.line([point(k, r) for _, k, r, _ in stations], fill=0, width=LINE)
    sheet, side = _layout(centre, sign, len(stations))
    return np.asarray(image) < 128, sheet, side


def round_bilge(sign=1):
    """Round-bilge half: vertical sides turning through a 250 px radius into a flat bottom."""
    image, draw, centre, point = _canvas(sign)
    draw.line([(centre, 50), (centre, 950)], fill=0, width=2)
    for offset in (1200, 1000, 750, 450):
        radius = min(250, offset - 60)
        side = [point(offset, SHEER_ROW), point(offset, 800 - radius)]
        angles = np.linspace(0.0, np.pi / 2, 60)
        arc = [point(offset - radius + radius * np.cos(a), 800 - radius + radius * np.sin(a)) for a in angles]
        bottom = [point(RABBET_OFFSET, 800)]
        draw.line(side + arc + bottom, fill=0, width=LINE, joint='curve')
    sheet, side = _layout(centre, sign, 4)
    return np.asarray(image) < 128, sheet, side


def _side_column(sheet, side, sheer, knuckle, knuckle_row, row):
    offset = sheer + (knuckle - sheer) * (row - SHEER_ROW) / (knuckle_row - SHEER_ROW)
    return sheet.centre_column + side.sign * offset


@pytest.mark.parametrize('sign', [1, -1])
def test_v_bottom_stations_are_traced_named_and_knuckled(sign):
    ink, sheet, side = v_bottom(sign)
    half = bpp.read_half(ink, sheet, side)
    assert half.read
    assert [s.station for s in half.stations] == [4, 3, 2, 1]
    for station, (sheer, knuckle, knuckle_row, rabbet_row) in zip(half.stations, STATIONS):
        row, column = station.chine
        assert row == pytest.approx(knuckle_row, abs=3)
        assert sign * (column - sheet.centre_column) == pytest.approx(knuckle, abs=3)
        assert station.turn_deg > 45
        # Half-breadths on the side and on the low-deadrise bottom, against the drawn lines.
        expected = sign * (_side_column(sheet, side, sheer, knuckle, knuckle_row, 450) - sheet.centre_column)
        assert station.half_breadth_m(450, sheet) == pytest.approx(expected / 100.0, abs=0.03)
        bottom_row = knuckle_row + 0.5 * (rabbet_row - knuckle_row)
        bottom_offset = knuckle + 0.5 * (RABBET_OFFSET - knuckle)
        assert station.half_breadth_m(bottom_row, sheet) == pytest.approx(bottom_offset / 100.0, abs=0.15)
        # The rabbet is the bottom's inner end, near the keel.
        assert sign * (station.rabbet[1] - sheet.centre_column) < 0.1 * knuckle


def test_polyline_rows_rise_once_from_rabbet_to_sheer():
    ink, sheet, side = v_bottom()
    for station in bpp.read_half(ink, sheet, side).stations:
        assert np.all(np.diff(station.points[:, 0]) < 0)
        assert station.points[0, 0] > station.chine[0] > station.points[-1, 0]


def test_round_bilge_half_is_declined():
    ink, sheet, side = round_bilge()
    half = bpp.read_half(ink, sheet, side)
    assert not half.read
    assert not half.stations
    assert bpp.waterline_table({'fore': half}, sheet) == {}


def test_missing_inner_station_names_from_the_outermost():
    ink, sheet, side = v_bottom(stations=STATIONS[:3])
    sheet, side = _layout(sheet.centre_column, 1, 4)  # the calibration lists four stations
    half = bpp.read_half(ink, sheet, side)
    assert half.read
    assert [s.station for s in half.stations] == [4, 3, 2]
    assert any('not read' in note for note in half.notes)


def test_waterline_table_reads_each_station_at_each_row_it_spans():
    ink, sheet, side = v_bottom()
    table = bpp.waterline_table({'fore': bpp.read_half(ink, sheet, side)}, sheet)
    assert (4, 'r475') in table and (1, 'r775') in table
    assert (1, 'r850') not in table  # below the rabbet of station 1
    assert table[(4, 'r475')] > table[(3, 'r475')] > table[(2, 'r475')] > table[(1, 'r475')]


def test_trace_passes_a_crossing_line_and_stops_where_the_ink_ends():
    image = Image.new('L', (400, 400), 255)
    draw = ImageDraw.Draw(image)
    draw.line([(200, 50), (200, 300)], fill=0, width=LINE)
    draw.line([(50, 150), (350, 150)], fill=0, width=LINE)
    ink = np.asarray(image) < 128
    trace = bpp.trace_line(ink, (60.0, 200.0), (1.0, 0.0), LINE)
    assert trace.points[-1, 0] == pytest.approx(300, abs=4)
    assert np.allclose(trace.points[:, 1], 200, atol=1.5)
    assert (trace.states == bpp.IN_CROSSING).any()
