"""Synthetic tests for the 'code measures, model identifies' body-plan reader (plan section 3.5.8).

The drawings are made here: nested station curves (two drawn on top of each other near the top),
waterlines, thin vertical grid lines, a diagonal that runs to the centreline and a block of
lettering. No sheet, no truth table and no model call.
"""
import io
import json
import math

import numpy as np
import pytest
from PIL import Image, ImageDraw

from benchmarks.balclutha import crossing_value as cv
from vessel_reconstruction import body_plan_crossings as bpc
from vessel_reconstruction import body_plan_identity as bpi
from vessel_reconstruction import body_plan_reader as bpr

WIDTH, HEIGHT = 1700, 2300
CENTRE = 100
BASE_ROW = 2100
WATERLINE_ROWS = {1: 1850, 2: 1600, 3: 1350, 4: 1100, 5: 850, 6: 600}
GRID_COLUMNS = (CENTRE + 500, CENTRE + 1000)
STATIONS_OUTER_FIRST = (5, 6, 7, 8, 9)
LINE_WIDTH = 5


def station_offset(rank_from_inside: int, row: float) -> float:
    """Half-breadth (px) of a synthetic station curve at an image row; larger rank lies outside.

    The two outermost curves (ranks 3 and 4) meet near the top (drawn on top of each other).
    """
    height = (BASE_ROW - row) / (BASE_ROW - 400)  # 0 at the base, 1 at row 400
    offset = (220 + 230 * rank_from_inside) * math.sqrt(max(height, 0.0))
    if rank_from_inside == 4:
        offset = station_offset(3, row) + 60 * max(0.0, 1 - height) ** 1.5
    return offset


def synthetic_drawing() -> np.ndarray:
    image = Image.new('L', (WIDTH, HEIGHT), 255)
    draw = ImageDraw.Draw(image)
    for row in WATERLINE_ROWS.values():
        draw.line([(0, row), (WIDTH - 1, row)], fill=0, width=5)
    for column in GRID_COLUMNS:
        draw.line([(column, 300), (column, BASE_ROW)], fill=0, width=3)
    for rank in range(5):
        points = [(CENTRE + station_offset(rank, row), row) for row in range(BASE_ROW - 30, 399, -2)]
        draw.line(points, fill=0, width=LINE_WIDTH, joint='curve')
    draw.line([(CENTRE, 500), (CENTRE + 1500, 2000)], fill=0, width=LINE_WIDTH)  # a diagonal
    draw.rectangle((CENTRE + 1300, 1330, CENTRE + 1340, 1370), fill=0)  # a blob of lettering
    return np.asarray(image)


@pytest.fixture(scope='module')
def drawing() -> np.ndarray:
    return synthetic_drawing()


@pytest.fixture(scope='module')
def reading(drawing) -> bpr.SideReading:
    return bpr.measure_side(drawing < 128, sheet_layout(), side_layout())


def side_layout() -> bpr.SideLayout:
    return bpr.SideLayout('fore', 1, STATIONS_OUTER_FIRST, GRID_COLUMNS)


def sheet_layout() -> bpr.SheetLayout:
    return bpr.SheetLayout(CENTRE, 100.0, WATERLINE_ROWS, 1550, (side_layout(),))


def test_crossings_are_measured_to_a_pixel_and_sorted_into_kinds(drawing):
    ink = drawing < 128
    row = WATERLINE_ROWS[3]
    crossings = bpc.find_crossings(ink, row + 3, (CENTRE + 10, CENTRE + 1550))  # nominal row 3 px off
    bpc.classify(ink, crossings, bpc.typical_width(crossings), CENTRE, grid_columns=GRID_COLUMNS)
    kinds = {}
    for crossing in crossings:
        kinds.setdefault(crossing.kind, []).append(crossing)
    curves = sorted(c.x_px for c in kinds[bpc.KIND_CURVE])
    assert len(curves) == 5
    expected = sorted(CENTRE + station_offset(rank, row) for rank in range(5))
    assert np.max(np.abs(np.array(curves) - expected)) <= 1.0
    assert [abs(c.x_px - (CENTRE + row - 500)) <= 2 for c in kinds[bpc.KIND_STRAIGHT]] == [True]
    assert len(kinds[bpc.KIND_GRID]) == 2
    assert bpc.KIND_LETTERING in kinds  # the blob is not a station curve


def test_chains_follow_each_curve_and_rank_numbering_matches_the_drawing(reading):
    assert len(reading.chains) == 5
    identities = bpr.identities_by_rank(reading.chains, STATIONS_OUTER_FIRST)
    table = bpr.table_from_identities(reading, identities, 100.0, CENTRE)
    for station, rank in zip(STATIONS_OUTER_FIRST, (4, 3, 2, 1, 0)):
        for waterline, row in WATERLINE_ROWS.items():
            # 1 px is 0.01 m; where two curves are drawn together the crossing is their mean column.
            tolerance = 0.02 if waterline == 6 and rank >= 3 else 0.01
            assert table[(station, waterline)] == pytest.approx(station_offset(rank, row) / 100.0, abs=tolerance)
    # The two outer curves are drawn together at the top waterline: both chains pass through it.
    outer, second = reading.chains[0], reading.chains[1]
    assert outer.nodes[6] == second.nodes[6]
    flags = bpr.fairness_flags(table, STATIONS_OUTER_FIRST, [1, 2, 3, 4, 5, 6])
    assert [flag for flag in flags if flag['check'] == 'nesting'] == []


def test_fairness_flags_catch_a_swapped_pair():
    table = {(5, 1): 3.0, (6, 1): 2.5, (7, 1): 2.6, (8, 1): 1.0}
    flags = bpr.fairness_flags(table, (5, 6, 7, 8), [1])
    assert {'check': 'nesting', 'station': 7, 'waterline': 1} == {k: flags[0][k] for k in ('check', 'station', 'waterline')}


def test_enclosed_unlinked_crossings_pair_in_order_or_join_the_nearer_neighbour():
    def crossing(x, slope=0.0, row=100.0):
        return bpc.Crossing(row=row, x_px=x, slope=slope, width_px=5, rows_above=10, rows_below=10,
                            fit_residual_px=0.1)

    lower = [crossing(x) for x in (900, 800, 700, 600)]
    upper = [crossing(x, row=0.0) for x in (905, 805, 702, 600)]
    links = bpr.infer_enclosed_links([(0, 0, 1.0), (3, 3, 1.0)], lower, upper)
    assert links == [(0, 0, 1.0), (1, 1, None), (2, 2, None), (3, 3, 1.0)]
    merged = [crossing(x, row=0.0) for x in (905, 600)]
    links = bpr.infer_enclosed_links([(0, 0, 1.0), (3, 1, 1.0)], lower, merged)
    assert links == [(0, 0, 1.0), (1, 0, None), (2, 1, None), (3, 1, 1.0)]


def test_question_image_is_a_readable_crop_with_the_curve_in_red(drawing, reading):
    png, geometry = bpi.question_image(drawing, reading.chains[2], column_limits=(CENTRE - 40, WIDTH))
    image = Image.open(io.BytesIO(png))
    assert max(image.size) <= bpi.QUESTION_MAX_SIDE_PX and geometry['box'][0] >= CENTRE - 40
    pixels = np.asarray(image.convert('RGB')).astype(int)
    red = (pixels[..., 0] > 150) & (pixels[..., 1] < 120) & (pixels[..., 2] < 120)
    assert red.sum() > 500


def test_labels_are_parsed_strictly():
    stations = (5, 6, 7)
    assert bpi.parse_label('```json\n{"station": 6, "reason": "label 6"}\n```', stations) == 6
    assert bpi.parse_label('{"station": "7"}', stations) == 7
    assert bpi.parse_label('{"station": null}', stations) is None
    for bad in ('{"station": 12}', '{"station": true}', '{"number": 6}', 'no json'):
        with pytest.raises((ValueError, json.JSONDecodeError)):
            bpi.parse_label(bad, stations)


def test_numbering_follows_the_labels_and_flags_the_odd_one(reading):
    # Labels say the outermost chain is station 6, not 5; one label is wrong; the last is unread.
    labels = {0: 6, 1: 7, 2: 9, 3: 9, 4: None}
    identities, summary = bpi.identities_from_labels(reading, labels)
    assert summary['offset'] == 1 and summary['labels_agreeing'] == 3
    assert identities == {0: 6, 1: 7, 2: 8, 3: 9}
    assert summary['disagreeing_chains'] == [2]
    # No labels at all: the code's own nesting count.
    identities, summary = bpi.identities_from_labels(reading, {})
    assert summary['offset'] == 0 and identities[0] == 5


def test_crouton_falls_back_to_deepseek_after_a_failed_retry(tmp_path, monkeypatch):
    calls = []

    def crouton(messages, receipts, settings):
        calls.append('crouton')
        return '', {'state': 'failed', 'error': 'HTTPError: HTTP Error 429: Too Many Requests'}

    def deepseek(messages, receipts):
        calls.append('deepseek')
        return '{"station": 5}', {'state': 'completed', 'usage': {}}

    monkeypatch.setattr(cv.time, 'sleep', lambda seconds: None)  # no waiting in the test
    call = cv.crouton_with_fallback(crouton, deepseek)
    text, receipt = call([], tmp_path)
    assert calls == ['crouton', 'crouton', 'deepseek'] and receipt['answered_by'] == cv.ab.GO_MODEL
    question = {'id': 'q', 'stations': (5, 6), 'messages': []}
    answer = cv.ask_label(question, tmp_path, call)
    assert answer['label'] == 5 and answer['valid']
