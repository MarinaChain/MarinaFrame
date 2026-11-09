"""Hard-chine drawings made with PIL; no scan, truth table or model calls."""
import numpy as np
import pytest
from PIL import Image, ImageDraw

from vessel_reconstruction import body_plan_reader as bpr


def drawing(sign=1, count=3, chine=True, gap=0):
    image = Image.new('L', (1800, 1100), 255)
    draw = ImageDraw.Draw(image)
    centre = 100 if sign == 1 else 1700
    rows = {'bottom': 850, 'middle': 550, 'top': 250}
    for y in rows.values():
        draw.line([(0, y), (1799, y)], fill=0, width=3)
    for rank in range(count):
        x = 900 + rank * 220
        corner = 700 + rank * 20
        def point(offset, row):
            return centre + sign * offset, row
        if chine:
            draw.line([point(x - 800, 1000), point(x, corner + gap)], fill=0, width=5)
            draw.line([point(x, corner - gap), point(x + 65, 150)], fill=0, width=5)
        else:
            draw.line([point(x - 100, 1000), point(x + 65, 150)], fill=0, width=5)
    side = bpr.SideLayout('fore', sign, tuple(range(count, 0, -1)))
    sheet = bpr.SheetLayout(centre, 100, rows, 1600, (side,))
    return np.asarray(image) < 128, sheet, side


@pytest.mark.parametrize('sign', [1, -1])
def test_joins_one_waterline_bottoms_without_changing_measured_cells(sign):
    from vessel_reconstruction import body_plan_chine as chine
    ink, sheet, side = drawing(sign)
    frozen = bpr.measure_side(ink, sheet, side)
    assert len(bpr.identities_by_rank(frozen.chains, side.stations_outer_first)) == 3
    joined = chine.join_chine(ink, sheet, frozen)
    ids = bpr.identities_by_rank(joined.chains, side.stations_outer_first)
    table = bpr.table_from_identities(joined, ids, 100, sheet.centre_column)
    assert len(table) == 9
    assert all(len(joined.chains[i].nodes) == 3 for i in ids)
    for rank, station in enumerate((1, 2, 3)):
        x = 900 + rank * 220
        corner = 700 + rank * 20
        expected = x - 800 * (850 - corner) / (1000 - corner)
        assert table[station, 'bottom'] == pytest.approx(expected / 100, abs=.02)
    assert all(len(c.nodes) < 3 for c in frozen.chains)


@pytest.mark.parametrize('kwargs', [{'chine': False}, {'count': 1}, {'gap': 35}])
def test_leaves_smooth_isolated_or_separated_pieces_unchanged(kwargs):
    from vessel_reconstruction import body_plan_chine as chine
    ink, sheet, side = drawing(**kwargs)
    frozen = bpr.measure_side(ink, sheet, side)
    assert chine.join_chine(ink, sheet, frozen) is frozen


def test_wrapper_measures_then_joins_station_cells():
    from vessel_reconstruction import body_plan_chine as chine
    ink, sheet, side = drawing()
    reading = chine.measure_side(ink, sheet, side)
    assert len(reading.chains) == 3
    assert all(len(chain.nodes) == 3 for chain in reading.chains)
