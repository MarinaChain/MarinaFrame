"""Chine-line detection on a synthetic drawing made with PIL; no scan or truth table."""
import numpy as np
import pytest
from PIL import Image, ImageDraw

from benchmarks.hard_chine import chine_line as chine_line
from vessel_reconstruction import body_plan_reader as bpr

CENTRE = 100
STATION_COLUMNS = (600, 900, 1200)
WATERLINES = {'top': 250, 'middle': 550, 'bottom': 1000}


def chine_row(column):
    return 700 + 0.05 * (column - 150)


def drawing(sign=1, heavy_line=True, stations=STATION_COLUMNS):
    """Station curves kinked at a separately drawn heavy chine line, mirrored for sign -1."""
    image = Image.new('L', (1800, 1200), 255)
    draw = ImageDraw.Draw(image)
    centre = CENTRE if sign == 1 else 1700

    def point(offset, row):
        return centre + sign * (offset - CENTRE), row

    for row in WATERLINES.values():
        draw.line([(0, row), (1799, row)], fill=0, width=3)
    if heavy_line:
        draw.line([point(150, chine_row(150)), point(1500, chine_row(1500))], fill=0, width=10)
    for column in stations:
        draw.line([point(column + 60, 150), point(column, chine_row(column))], fill=0, width=5)
        draw.line([point(column, chine_row(column)), point(column - 250, 1100)], fill=0, width=5)
    side = bpr.SideLayout('fore', sign, tuple(range(len(stations), 0, -1)))
    sheet = bpr.SheetLayout(centre, 100, dict(WATERLINES), 1500, (side,))
    return np.asarray(image) < 128, sheet, side


@pytest.mark.parametrize('sign', [1, -1])
def test_finds_heavy_line_and_station_chine_points(sign):
    ink, sheet, side = drawing(sign)
    reading = bpr.measure_side(ink, sheet, side)
    line = chine_line.find_chine_line(ink, sheet, reading)
    assert line is not None
    points = chine_line.station_chine_points(line, reading, bpr.waterline_spacing(sheet))
    assert len(points) == len(STATION_COLUMNS)
    for point, column in zip(points, reversed(STATION_COLUMNS)):
        offset = sign * (point.column - sheet.centre_column)
        assert offset == pytest.approx(column - CENTRE, abs=6)
        assert point.row == pytest.approx(chine_row(column), abs=6)


def test_no_heavy_line_means_no_chine_line():
    ink, sheet, side = drawing(heavy_line=False)
    reading = bpr.measure_side(ink, sheet, side)
    assert chine_line.find_chine_line(ink, sheet, reading) is None
