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


def test_buttock_grid_lines_are_not_stations():
    ink, sheet, side = v_bottom()
    image = Image.fromarray(np.where(ink, 0, 255).astype(np.uint8))
    draw = ImageDraw.Draw(image)
    grid = (sheet.centre_column + 300, sheet.centre_column + 600)
    for column in grid:  # vertical buttock lines from above the sheer to below the keel
        draw.line([(column, 100), (column, 900)], fill=0, width=2)
    ink = np.asarray(image) < 128
    side = bpr.SideLayout('fore', 1, side.stations_outer_first, grid)
    sheet = bpr.SheetLayout(sheet.centre_column, sheet.pixels_per_metre, sheet.waterline_rows,
                            sheet.max_offset_px, (side,))
    half = bpp.read_half(ink, sheet, side)
    assert [s.station for s in half.stations] == [4, 3, 2, 1]
    for station, (_, knuckle, knuckle_row, _) in zip(half.stations, STATIONS):
        assert station.chine[0] == pytest.approx(knuckle_row, abs=3)


# ---------------------------------------------------------------- per-station engagement

def _existing_values(sheet, side, drawn):
    """An existing reader's table for drawn (name, (sheer, knuckle, knuckle_row, rabbet_row)) sides."""
    table = {}
    for name, (sheer, knuckle, knuckle_row, _) in drawn:
        for label, row in sheet.waterline_rows.items():
            if SHEER_ROW <= row < knuckle_row:
                column = _side_column(sheet, side, sheer, knuckle, knuckle_row, row)
                table[(name, label)] = side.sign * (column - sheet.centre_column) / sheet.pixels_per_metre
    return table


@pytest.mark.parametrize('sign', [1, -1])
def test_a_declined_half_engages_clear_knuckles_by_the_existing_names(sign):
    drawn = (STATIONS[0], STATIONS[2])  # two stations drawn: too few to read the half as a whole
    ink, sheet, side = v_bottom(sign, stations=drawn)
    sheet, side = _layout(sheet.centre_column, sign, 4)
    half = bpp.read_half(ink, sheet, side)
    assert not half.read and len(half.unnamed) == 2
    existing = _existing_values(sheet, side, ((4, drawn[0]), (2, drawn[1])))
    existing[(3, 'r250')] = 0.123  # a station the polyline reader did not trace
    engaged = bpp.engage_stations(half, side, existing, sheet)
    assert sorted(s.station for s in engaged) == [2, 4]
    table = bpp.half_table(half, existing, sheet)
    assert table[(3, 'r250')] == 0.123  # kept from the existing reader
    station = next(s for s in engaged if s.station == 4)
    assert table[(4, 'r775')] == pytest.approx(station.half_breadth_m(775, sheet))  # the bottom, below the knuckle
    assert (4, 'r775') not in existing


def test_an_existing_cell_on_an_engaged_line_under_another_name_is_dropped():
    drawn = (STATIONS[0], STATIONS[2])
    ink, sheet, side = v_bottom(1, stations=drawn)
    sheet, side = _layout(sheet.centre_column, 1, 4)
    half = bpp.read_half(ink, sheet, side)
    existing = _existing_values(sheet, side, ((4, drawn[0]), (2, drawn[1])))
    # The existing reader also gave station 3 a crossing that lies on station 4's ink.
    existing[(3, 'r325')] = existing[(4, 'r325')]
    bpp.engage_stations(half, side, existing, sheet)
    table = bpp.half_table(half, existing, sheet)
    assert (3, 'r325') not in table
    assert table[(4, 'r325')] == pytest.approx(existing[(4, 'r325')], abs=0.03)


def test_no_engagement_without_a_single_matching_existing_name():
    drawn = (STATIONS[0], STATIONS[2])
    ink, sheet, side = v_bottom(1, stations=drawn)
    sheet, side = _layout(sheet.centre_column, 1, 4)
    half = bpp.read_half(ink, sheet, side)
    assert bpp.engage_stations(half, side, {}, sheet) == []
    assert bpp.half_table(half, {}, sheet) == {}


def test_round_bilge_engages_nothing_and_keeps_the_existing_table():
    ink, sheet, side = round_bilge()
    half = bpp.read_half(ink, sheet, side)
    existing = {(4, 'r400'): 12.0, (3, 'r400'): 9.99}
    assert bpp.engage_stations(half, side, existing, sheet) == []
    assert bpp.half_table(half, existing, sheet) == existing


def _straight_station(sheet, side, corners, knuckle_index):
    """A StationPolyline along straight lines through (offset, row) corners, rabbet first."""
    points = []
    for (offset_a, row_a), (offset_b, row_b) in zip(corners, corners[1:]):
        for t in np.linspace(0.0, 1.0, 200, endpoint=False):
            points.append((row_a + t * (row_b - row_a), sheet.centre_column + side.sign * (offset_a + t * (offset_b - offset_a))))
    points.append((corners[-1][1], sheet.centre_column + side.sign * corners[-1][0]))
    points = np.asarray(points)
    knuckle = points[200 * knuckle_index]
    return bpp.StationPolyline(side.name, side.sign, points, 200 * knuckle_index, (knuckle[0], knuckle[1]), 70.0)


def test_an_inner_station_does_not_keep_the_outer_bottom_through_its_knuckle():
    # The outer bottom runs from its knuckle (1200, 700) to the keel (row 800) and passes through
    # the inner knuckle at offset 1000; the inner station's own bottom runs to row 760 at the keel.
    inner_knuckle_row = 700 + (1200 - 1000) / (1200 - RABBET_OFFSET) * (800 - 700)
    stations = ((1260, 1200, 700, 800), (1050, 1000, inner_knuckle_row, 760))
    ink, sheet, side = v_bottom(stations=stations, chine_curve=False)
    width = bpp.line_width(ink, sheet, side)
    outer = _straight_station(sheet, side, [(RABBET_OFFSET, 800), (1200, 700), (1260, SHEER_ROW)], 1)
    # The inner trace that ran on along the outer bottom from its knuckle.
    hijacked = _straight_station(sheet, side, [(RABBET_OFFSET, 800), (1000, inner_knuckle_row), (1050, SHEER_ROW)], 1)
    hijacked.seed = (400.0, _side_column(sheet, side, 1050, 1000, inner_knuckle_row, 400))
    kept, dropped = bpp._own_bottoms(ink, sheet, side, width, [hijacked, outer])
    assert dropped == 0 and len(kept) == 2
    assert kept[0] is outer  # the outer station keeps the line
    assert kept[1].rabbet[0] == pytest.approx(760, abs=6)  # the inner one is traced again along its own
    assert any('traced again' in note for note in kept[1].notes)


def _on_outer_bottom(offset):
    """Row of the outermost station's bottom (STATIONS[0]) at `offset`: its line from the knuckle to the keel."""
    _, knuckle, knuckle_row, rabbet_row = STATIONS[0]
    return knuckle_row + (knuckle - offset) / (knuckle - RABBET_OFFSET) * (rabbet_row - knuckle_row)


def _crowded(sign=1):
    """Four stations; the second's side ends on the outermost bottom and it has no bottom of its own."""
    second_knuckle = 1000
    second = (1050, second_knuckle, _on_outer_bottom(second_knuckle))
    ink, sheet, side = v_bottom(sign, stations=(STATIONS[0], STATIONS[2], STATIONS[3]), chine_curve=False)
    centre = sheet.centre_column

    def side_only(draw):
        sheer, knuckle, knuckle_row = second
        draw.line([(centre + sign * sheer, SHEER_ROW), (centre + sign * knuckle, knuckle_row)], fill=0, width=LINE)

    sheet, side = _layout(centre, sign, 4)
    return _with(ink, side_only), sheet, side, second


def test_a_station_whose_bottom_is_an_outer_stations_keeps_its_side_and_knuckle():
    ink, sheet, side, (sheer, knuckle, knuckle_row) = _crowded()
    width = bpp.line_width(ink, sheet, side)
    outer_sheer, outer_knuckle, outer_knuckle_row, outer_rabbet_row = STATIONS[0]
    outer = _straight_station(sheet, side, [(RABBET_OFFSET, outer_rabbet_row), (outer_knuckle, outer_knuckle_row),
                                            (outer_sheer, SHEER_ROW)], 1)
    # The inner trace ran on along the outer bottom from its knuckle; there is no other bottom line.
    inner = _straight_station(sheet, side, [(RABBET_OFFSET, STATIONS[0][3]), (knuckle, knuckle_row),
                                            (sheer, SHEER_ROW)], 1)
    inner.seed = (400.0, _side_column(sheet, side, sheer, knuckle, knuckle_row, 400))
    kept, without_bottom = bpp._own_bottoms(ink, sheet, side, width, [inner, outer])
    assert without_bottom == 1 and len(kept) == 2
    assert kept[0] is outer
    assert kept[1].knuckle_index == 0  # side and knuckle only: the polyline starts at the knuckle
    assert kept[1].rabbet[0] == pytest.approx(knuckle_row, abs=3)
    assert kept[1].sheer[0] == pytest.approx(SHEER_ROW, abs=3)


@pytest.mark.parametrize('sign', [1, -1])
def test_crowded_stations_sharing_one_bottom_keep_their_ranks(sign):
    ink, sheet, side, (sheer, knuckle, knuckle_row) = _crowded(sign)
    half = bpp.read_half(ink, sheet, side)
    assert half.read
    assert [s.station for s in half.stations] == [4, 3, 2, 1]
    offsets = [s.offset_px(s.chine[1], sheet.centre_column) for s in half.stations]
    expected = [STATIONS[0][1], knuckle, STATIONS[2][1], STATIONS[3][1]]
    assert offsets == pytest.approx(expected, abs=4)
    assert half.station(3).knuckle_index == 0  # its bottom is station 4's
    assert any('side and knuckle only' in note for note in half.notes)


def test_a_short_side_outline_with_a_corner_takes_no_station_rank():
    # A transom-like outline inside the innermost station: a short side, a corner, a bottom to the keel.
    # Without the rule the half has five knuckled lines for four stations and is declined.
    ink, sheet, side = v_bottom(stations=STATIONS)
    centre = sheet.centre_column

    def outline(draw):
        draw.line([(centre + 300, 520), (centre + 280, 650), (centre + RABBET_OFFSET, 700)], fill=0, width=LINE)

    ink = _with(ink, outline)
    half = bpp.read_half(ink, sheet, side)
    assert half.read
    assert [s.station for s in half.stations] == [4, 3, 2, 1]
    offsets = [s.offset_px(s.chine[1], centre) for s in half.stations]
    assert offsets == pytest.approx([knuckle for _, knuckle, _, _ in STATIONS], abs=4)
    assert any('an outline, not a station' in note for s in half.unnamed for note in s.notes)


def test_an_engaged_station_with_other_lines_through_its_knuckle_gives_its_side_only():
    drawn = (STATIONS[0], STATIONS[2])
    ink, sheet, side = v_bottom(1, stations=drawn)
    sheet, side = _layout(sheet.centre_column, 1, 4)
    half = bpp.read_half(ink, sheet, side)
    existing = _existing_values(sheet, side, ((4, drawn[0]), (2, drawn[1])))
    for station in half.unnamed:
        station.bottom_alternatives = 1
    engaged = bpp.engage_stations(half, side, existing, sheet)
    table = bpp.half_table(half, existing, sheet)
    for station in engaged:
        assert station.knuckle_index == 0
        assert station.rabbet[0] == pytest.approx(station.chine[0], abs=3)  # the polyline starts at the knuckle
    assert (4, 'r775') not in table and (4, 'r475') in table


# ---------------------------------------------------------------- the sheer (top of the side)

def _with(ink, draw_more):
    image = Image.fromarray(np.where(ink, 0, 255).astype(np.uint8))
    draw_more(ImageDraw.Draw(image))
    return np.asarray(image) < 128


def test_the_sheer_is_the_top_edge_of_the_heavy_sheer_line_the_side_ends_in():
    ink, sheet, side = v_bottom()
    heavy = 12  # a sheer line drawn heavy across the tops of the sides, centred on SHEER_ROW
    ink = _with(ink, lambda draw: draw.line([(0, SHEER_ROW), (WIDTH - 1, SHEER_ROW)], fill=0, width=heavy))
    half = bpp.read_half(ink, sheet, side)
    assert [s.station for s in half.stations] == [4, 3, 2, 1]
    for station in half.stations:
        assert station.sheer[0] == pytest.approx(SHEER_ROW - heavy / 2, abs=3)


def test_a_thin_label_leader_beyond_the_sheer_is_not_the_side():
    ink, sheet, side = v_bottom()
    top = sheet.centre_column + STATIONS[1][0]  # the top of station 3's side
    # A thin leader drawn on from the top of station 3's side, almost in line with it, to a label.
    ink = _with(ink, lambda draw: draw.line([(top, SHEER_ROW), (top + 30, SHEER_ROW - 140)], fill=0, width=2))
    half = bpp.read_half(ink, sheet, side)
    station = half.station(3)
    assert station is not None
    assert station.sheer[0] == pytest.approx(SHEER_ROW, abs=2 * LINE + 2)  # the junction, within two widths
    assert station.sheer[0] >= SHEER_ROW - LINE


def test_a_side_cut_where_it_runs_on_up_a_grid_column():
    width = 5.0
    points = np.array([[row, 300.0 + 0.2 * (500 - row)] for row in range(500, 300, -2)]  # slanted side
                      + [[row, 340.0] for row in range(300, 200, -2)])  # then straight up a grid column
    cut = bpp._cut_at_grid(points, width, (340.0,))
    assert cut[-1, 0] == pytest.approx(300, abs=70)  # the junction (the band reaches below it)
    assert cut[-1, 0] > 250
    assert len(bpp._cut_at_grid(points, width, ())) == len(points)


# ---------------------------------------------------------------- cells only where the hull is drawn

def test_existing_cells_above_their_own_traced_side_are_unsupported():
    drawn = (STATIONS[0], STATIONS[2])
    ink, sheet, side = v_bottom(1, stations=drawn)
    sheet, side = _layout(sheet.centre_column, 1, 4)
    offset = 900  # a station line the polyline reader does not trace: drawn from row 400 down only
    ink = _with(ink, lambda draw: draw.line([(sheet.centre_column + offset, 400), (sheet.centre_column + offset - 30, 700)],
                                           fill=0, width=LINE))
    # The check traces up from the station's middle cell (r625), which must rise at least 15 widths.
    half = bpp.read_half(ink, sheet, side)
    existing = _existing_values(sheet, side, ((4, drawn[0]), (2, drawn[1])))
    for label in ('r325', 'r625', 'r700'):  # station 3: r325 lies above its drawn top
        row = sheet.waterline_rows[label]
        existing[(3, label)] = (offset - 30 * (row - 400) / 300) / sheet.pixels_per_metre
    bpp.engage_stations(half, side, existing, sheet, ink)
    assert half.unsupported == [(3, 'r325')]
    table = bpp.half_table(half, existing, sheet)
    assert (3, 'r325') not in table and (3, 'r625') in table and (3, 'r700') in table


def test_no_unsupported_check_without_engaged_stations():
    ink, sheet, side = round_bilge()
    half = bpp.read_half(ink, sheet, side)
    existing = {(4, 'r250'): 12.0}  # nowhere near any ink
    bpp.engage_stations(half, side, existing, sheet, ink)
    assert half.unsupported == [] and bpp.half_table(half, existing, sheet) == existing


# ---------------------------------------------------------------- flat-bottom hard chine
# Outermost station first: (side offset at the sheer, knuckle offset, knuckle row). Each bottom is drawn
# level from its knuckle to the centreline; the rows differ by station (rocker), and the drawn chine curve
# through the knuckles rises inward. Station 2's bottom lies 5 px from the measuring row r700, which is not
# drawn: a level bottom there is still a bottom.
FLAT_STATIONS = ((1260, 1200, 755), (1050, 1000, 740), (790, 750, 705), (480, 450, 660))


def flat_bottom(sign=1, stations=FLAT_STATIONS):
    """Flat-bottom hard-chine half (a skiff): straight sides, knuckles, level bottoms to the centreline."""
    image, draw, centre, point = _canvas(sign)
    draw.line([(centre, 50), (centre, 950)], fill=0, width=2)  # centreline
    draw.line([(0, 500), (WIDTH - 1, 500)], fill=0, width=2)  # a drawn waterline crossing the sides
    for sheer, knuckle, knuckle_row in stations:
        draw.line([point(sheer, SHEER_ROW), point(knuckle, knuckle_row)], fill=0, width=LINE)
        draw.line([point(knuckle, knuckle_row), point(0, knuckle_row)], fill=0, width=LINE)
    draw.line([point(k, r) for _, k, r in stations], fill=0, width=LINE)  # the chine curve
    sheet, side = _layout(centre, sign, len(stations))
    return np.asarray(image) < 128, sheet, side


@pytest.mark.parametrize('sign', [1, -1])
def test_flat_bottom_stations_are_traced_named_and_knuckled(sign):
    ink, sheet, side = flat_bottom(sign)
    half = bpp.read_half(ink, sheet, side)
    assert half.read, half.notes
    assert [s.station for s in half.stations] == [4, 3, 2, 1]
    for station, (sheer, knuckle, knuckle_row) in zip(half.stations, FLAT_STATIONS):
        row, column = station.chine
        assert row == pytest.approx(knuckle_row, abs=3)
        assert sign * (column - sheet.centre_column) == pytest.approx(knuckle, abs=3)
        assert station.turn_deg > 45
        expected = sign * (_side_column(sheet, side, sheer, knuckle, knuckle_row, 450) - sheet.centre_column)
        assert station.half_breadth_m(450, sheet) == pytest.approx(expected / 100.0, abs=0.03)
        # The rabbet is the level bottom's inner end, at the centreline, on the drawn bottom line (a branch
        # from just above the knuckle can meet the bottom at its lower edge: within one line width).
        assert sign * (station.rabbet[1] - sheet.centre_column) < 0.1 * knuckle
        assert station.rabbet[0] == pytest.approx(knuckle_row, abs=LINE)
        # Rows still rise once from the rabbet to the sheer, through the knuckle.
        assert np.all(np.diff(station.points[:, 0]) < 0)
        assert station.points[station.knuckle_index, 1] == pytest.approx(column, abs=3)


def test_only_calibrated_rows_inked_across_both_halves_are_drawn_rows():
    """Level bottoms of both halves a few pixels either side of a measuring row do not make it drawn."""
    image = Image.new('L', (WIDTH, HEIGHT), 255)
    draw = ImageDraw.Draw(image)
    centre = WIDTH // 2
    draw.line([(centre - 600, 400), (centre + 600, 400)], fill=0, width=2)  # a drawn waterline on r400
    draw.line([(centre - 500, 696), (centre, 696)], fill=0, width=LINE)  # one half's bottom above r700
    draw.line([(centre, 704), (centre + 500, 704)], fill=0, width=LINE)  # the other half's bottom below
    sheet = bpr.SheetLayout(centre, 100.0, {'drawn': 400, 'between': 700, 'empty': 550}, 700, ())
    assert bpp.drawn_rows(np.asarray(image) < 128, sheet) == [400]


def test_a_box_corner_below_the_hull_whose_level_line_stops_short_of_the_centreline_is_not_a_station():
    ink, sheet, side = flat_bottom()
    image = Image.fromarray(np.where(ink, 0, 255).astype(np.uint8))
    draw = ImageDraw.Draw(image)
    centre = sheet.centre_column
    draw.line([(centre + 1400, 790), (centre + 1400, 950)], fill=0, width=LINE)  # a frame edge below the hull
    draw.line([(centre + 1400, 950), (centre + 300, 950)], fill=0, width=LINE)  # its level border, short of the centreline
    half = bpp.read_half(np.asarray(image) < 128, sheet, side)
    assert half.read, half.notes
    assert [s.station for s in half.stations] == [4, 3, 2, 1]
    assert all(s.chine[0] < 800 for s in half.stations + half.unnamed)


def test_a_flat_bottom_half_gives_side_cells_above_each_knuckle():
    ink, sheet, side = flat_bottom()
    table = bpp.waterline_table({'fore': bpp.read_half(ink, sheet, side)}, sheet)
    assert table[(4, 'r475')] > table[(3, 'r475')] > table[(2, 'r475')] > table[(1, 'r475')]
    assert (1, 'r700') not in table  # below station 1's level bottom
    assert (4, 'r700') in table


def test_a_v_bottom_with_a_level_line_through_its_knuckles_keeps_its_descending_bottoms():
    """A level line through the knuckles (a drawn line that is not a measuring row) is not taken as the
    bottom where a descending bottom leaves the same knuckle."""
    stations = tuple((sheer, knuckle, 690, rabbet) for sheer, knuckle, _, rabbet in STATIONS)
    ink, sheet, side = v_bottom(stations=stations, chine_curve=False)
    image = Image.fromarray(np.where(ink, 0, 255).astype(np.uint8))
    ImageDraw.Draw(image).line([(0, 690), (WIDTH - 1, 690)], fill=0, width=2)
    half = bpp.read_half(np.asarray(image) < 128, sheet, side)
    assert half.read, half.notes
    for station, (_, _, _, rabbet_row) in zip(half.stations, stations):
        assert station.rabbet[0] == pytest.approx(rabbet_row, abs=8)
