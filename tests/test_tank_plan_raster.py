"""Raster tank-plan reader (docs/TANKS_V2.md): synthetic drawings with exact answers."""
from __future__ import annotations

import cv2
import numpy as np
import pytest

from vessel_reconstruction import tank_plan_raster as raster

DPI = 200
PX_PER_MM = DPI / 25.4


def blank(height: int, width: int) -> np.ndarray:
    return np.zeros((height, width), np.uint8)


def dash_dot_line(image, start, end, dash=40, gap=10, thickness=2):
    """A dash-dot line: dash, gap, dot, gap."""
    start, end = np.asarray(start, float), np.asarray(end, float)
    length = np.linalg.norm(end - start)
    direction = (end - start) / length
    at = 0.0
    while at < length:
        a = start + direction * at
        b = start + direction * min(at + dash, length)
        cv2.line(image, tuple(int(v) for v in a), tuple(int(v) for v in b), 1, thickness)
        dot = start + direction * min(at + dash + gap, length)
        cv2.circle(image, tuple(int(v) for v in dot), 1, 1, -1)
        at += dash + 2 * gap


def crossed_box(image, x0, y0, x1, y1, dashed=False):
    cv2.rectangle(image, (x0, y0), (x1, y1), 1, 2)
    if dashed:
        dash_dot_line(image, (x0, y0), (x1, y1))
        dash_dot_line(image, (x0, y1), (x1, y0))
    else:
        cv2.line(image, (x0, y0), (x1, y1), 1, 2)
        cv2.line(image, (x0, y1), (x1, y0), 1, 2)


@pytest.mark.parametrize('dashed', [False, True])
def test_cross_mark_is_erased_and_the_tank_is_one_region(dashed):
    image = blank(700, 1200)
    crossed_box(image, 200, 150, 900, 550, dashed=dashed)
    view = raster.parse_view(image.astype(bool), raster.ViewSpec('plan', 'plan', (0, 0, 1, 1)), (0, 0), PX_PER_MM)
    assert len(view.crosses) == 1
    region = view.regions[350, 550]
    area = (view.regions == region).sum()
    inside = (900 - 200 - 2) * (550 - 150 - 2)
    assert area == pytest.approx(inside, rel=0.03)


def test_two_crossing_lines_without_a_box_are_not_a_cross_mark():
    image = blank(700, 1200)
    cv2.rectangle(image, (100, 100), (1100, 600), 1, 2)
    # Two boundary lines that cross; nothing joins their ends.
    cv2.line(image, (400, 100), (800, 600), 1, 2)
    cv2.line(image, (400, 600), (800, 100), 1, 2)
    view = raster.parse_view(image.astype(bool), raster.ViewSpec('plan', 'plan', (0, 0, 1, 1)), (0, 0), PX_PER_MM)
    assert view.crosses == []


def test_regular_ticks_count_hidden_ticks_and_skip_stray_marks():
    columns = [100, 200, 300, 350, 500, 600, 700, 800]  # 400 hidden, 350 stray
    ticks, spacing = raster.regular_ticks(columns)
    assert spacing == pytest.approx(100)
    assert [(t.column, t.ordinal) for t in ticks] == [(100, 0), (200, 1), (300, 2), (500, 4), (600, 5),
                                                     (700, 6), (800, 7)]


def test_frame_axis_with_inserted_lettered_frames():
    """Frames 0..27, then A..J (lengthening), then 28...: frame 0 from the low numbers."""
    labels = [str(n) for n in range(28)] + list('ABCDEFGHIJ') + [str(n) for n in range(28, 40)]
    ticks = [raster.Tick(100.0 + 50 * i, i, label if label in ('0', '5', '20', '27', 'A', '28', '35') else '')
             for i, label in enumerate(labels)]
    axis = raster.fit_frame_axis(10.0, ticks, 0.5)
    assert axis.ordinal_of_zero == 0
    assert axis.x_m([100.0 + 50 * 28])[0] == pytest.approx(14.0)  # frame A
    assert axis.x_m([100.0 + 50 * 38])[0] == pytest.approx(19.0)  # frame 28 after the ten letters
    assert axis.px_per_m == pytest.approx(100.0)


def test_scale_bar_fit():
    ticks = [raster.Tick(1000.0 + 25 * value, i, str(value)) for i, value in enumerate(range(0, 100, 10))]
    axis = raster.fit_scale_bar(0.0, ticks, raster.FEET_M)
    assert axis.px_per_m == pytest.approx(25 / raster.FEET_M)


def test_a_dash_is_line_ink_and_a_letter_t_is_text():
    image = blank(200, 400)
    cv2.line(image, (20, 50), (20 + int(6 * PX_PER_MM), 50), 1, 2)  # a 6 mm dash
    cv2.line(image, (200, 40), (225, 40), 1, 2)  # a "T", 2.5 mm high
    cv2.line(image, (212, 40), (212, 40 + int(2.5 * PX_PER_MM)), 1, 2)
    text, dashes, _ = raster.small_components(image.astype(bool), PX_PER_MM, 2.0)
    assert dashes[50, 30] and not text[50, 30]
    assert text[45, 212] and not dashes[45, 212]


def test_tank_keys_contents_and_labels():
    assert raster.tank_key('No 3 sb Technical water') == 'no 3 sb'
    assert raster.tank_key('No 11p FO serv') == 'no 11 p'
    assert raster.tank_key('No 3 No 3 p Technical water') == 'no 3 p'
    assert raster.tank_key('Cargo hold') is None
    assert raster.content_of('Dbb fuel oil settling') == 'fuel oil'
    assert raster.content_of('technical water') == 'water ballast'
    assert raster.content_of('F.O. OR S.W. BALLAST TANK NO. 2') == 'fuel oil or water ballast'
    assert raster.content_of('DEEP DRY BALLAST') == 'dry'
    assert raster.is_tank_label('Cargo hold')
    assert not raster.is_tank_label('Void')
    assert not raster.is_tank_label('Engine room')


def test_tank_words_features_kinds_and_sides():
    # A number alone, or a feature beside a tank word, is not a tank.
    assert not raster.is_tank_label('NO.1 HATCH')
    assert not raster.is_tank_label('DEEP TANK HATCH')
    assert not raster.is_tank_label('GIRDER OVER WEB NO.2 HATCH')
    assert not raster.is_tank_label('No 5')
    assert raster.is_tank_label('FORE PEAK TANK') and raster.is_tank_label('F.W. TANK P/S')
    assert raster.label_kind('DEEP TANK NO.3P') == 'deep tank' and raster.label_kind('F.O SETTLING TANK') == 'settling'
    assert raster.label_kind('NO.1 HATCH') is None
    # "P/S" names both sides: no side in the key; a whole-region label splits into two tanks.
    assert raster.tank_key('F.O. OR WATER BALLAST TANK NO.2 P/S') == 'no 2'
    assert raster.split_both_sides('TANK NO.2 P/S', None, True) == [(1, 'TANK NO.2 P'), (-1, 'TANK NO.2 S')]
    assert raster.split_both_sides('TANK NO.2 P/S', 1, True) == [(1, 'TANK NO.2 P/S')]


def test_schedule_items_and_rows_by_number_and_kind():
    rows = [{'key': '5', 'name': 'RESERVE FEED WATER TANK NO.4P', 'sheet': 0},
            {'key': '12', 'name': 'FUEL OIL OR WATER BALLAST TANK NO.1', 'sheet': 0},
            {'key': '3', 'name': 'DEEP TANK NO.3P DRY CARGO', 'sheet': 0},
            {'key': '8', 'name': 'FUEL OIL OR WATER BALLAST TANK NO.3P', 'sheet': 0}]
    assert raster.resolve_items('5 VOID', rows) == '#5 RESERVE FEED WATER TANK NO.4P'
    assert raster.resolve_items('NO.3 FUEL OIL TANK 5', rows) == 'NO.3 FUEL OIL TANK 5'  # stray number
    assert raster.resolve_items('NO.3 FUEL OIL TANK (5)', rows) == '#5 RESERVE FEED WATER TANK NO.4P'  # circled
    assert raster.resolve_items('NO.2 HATCH', rows) == 'NO.2 HATCH'  # a tank number is not an item
    assert raster.schedule_row_for('NO.1 HATCH', rows)['key'] == '12'  # number alone matches ...
    assert not raster.names_tank('NO.1 HATCH', rows)  # ... but a hatch is never a tank
    assert raster.names_tank('No 1', rows)  # a schedule tank row makes a bare number a tank
    assert raster.schedule_row_for('DEEP TANK NO.3P', rows)['key'] == '3'
    assert raster.schedule_row_for('D.B. TANK NO.3P', rows)['key'] == '8'


def test_read_crops_pages_and_numbers_the_cells():
    crops = [np.ones((40, 60), bool) for _ in range(150)]
    calls = []

    def ask(image, prompt):
        calls.append(image.shape)
        count = int(prompt.split('has ')[1].split(' ')[0])
        return {str(n): f'cell {n}' for n in range(1, count + 1)}

    old = raster.QUESTION_MAX_HEIGHT_PX
    raster.QUESTION_MAX_HEIGHT_PX = 300
    try:
        texts = raster.read_crops(crops, 20.0, raster.LABEL_PROMPT, ask)
    finally:
        raster.QUESTION_MAX_HEIGHT_PX = old
    assert len(calls) > 1 and all(shape[0] <= 300 for shape in calls)
    assert len(texts) == 150 and texts[0] == 'cell 1'


def test_reading_order_and_sides_of_a_plan_region():
    def block(r0, c0, text):
        return raster.TextBlock((r0, c0, r0 + 20, c0 + 40), 20.0, text)

    port = raster.RegionLabel(7, 1, [block(10, 0, 'No 6 p')], 'No 6 p Fuel oil')
    starboard = raster.RegionLabel(7, -1, [block(90, 0, 'No 6 sb')], 'No 6 sb Fuel oil')
    assert [g.side for g in raster.resolve_sides([port, starboard])] == [1, -1]
    room = raster.RegionLabel(8, 1, [block(10, 0, 'Engine')], 'Engine')
    room_low = raster.RegionLabel(8, -1, [block(90, 0, 'room')], 'room')
    merged = raster.resolve_sides([room, room_low])
    assert len(merged) == 1 and merged[0].side is None and merged[0].text == 'Engine room'


def test_claude_asker_never_caches_a_failed_call(tmp_path):
    calls = []

    def failing_call(messages, receipts):
        calls.append(1)
        return '', {'state': 'failed'}

    ask = raster.claude_asker(tmp_path, call=failing_call)
    image = np.zeros((4, 4), np.uint8)
    with pytest.raises(RuntimeError):
        ask(image, 'prompt')
    assert not list(tmp_path.glob('*.json'))

    ask = raster.claude_asker(tmp_path, call=lambda messages, receipts: ('{"1": "FO"}', {'state': 'completed'}))
    assert ask(image, 'prompt') == {'1': 'FO'}


def test_scale_bar_fit_drops_a_misread_number():
    ticks = [raster.Tick(1000.0 + 25 * value, i, str(value)) for i, value in enumerate(range(0, 100, 10))]
    ticks[5] = raster.Tick(ticks[5].column, 5, '5')  # "50" misread as "5"
    axis = raster.fit_scale_bar(0.0, ticks, raster.FEET_M)
    assert axis.px_per_m == pytest.approx(25 / raster.FEET_M)
    x = axis.x_m(np.arange(1000, 1250, 5))
    assert np.all(np.diff(x) > 0)


def test_content_words_match_whole_tokens():
    assert raster.content_of('FWD PEAK') == 'water ballast'  # not fresh water through "fw"
    assert raster.content_of("'TWEEN DECK") is None  # not ballast through "tw"
    assert not raster.is_tank_label("'TWEEN DECK")
    assert raster.content_of('FUEL OIL TANK TWIN SCREW') == 'fuel oil'  # not dual-use through "tw"
    assert raster.content_of('FUEL OIL TANK PEAKED') == 'fuel oil'  # not dual-use through "peak"
    assert raster.content_of('F.W. TANK') == 'fresh water'
    assert raster.content_of('NO.2 TW TANK') == 'water ballast'
    assert raster.content_of('FO SERVICE') == 'fuel oil'
    assert raster.content_of('FORE PEAK') == 'water ballast'


def _stub_view(line_columns, width=400, height=100):
    from types import SimpleNamespace
    vertical = np.zeros((height, width), bool)
    vertical[:, line_columns] = True
    return SimpleNamespace(ink=SimpleNamespace(vertical=vertical),
                           axis=SimpleNamespace(x_m=lambda columns: np.asarray(columns, float) / 10))


def test_a_weak_alignment_does_not_shift_the_plan():
    weak_plan, weak_profile = _stub_view([100, 200]), _stub_view([120, 220])
    shift, _, agreeing = raster.align_to_profile(weak_plan, weak_profile)
    assert not agreeing and shift == 0.0
    columns = [50, 100, 150, 200, 250]  # five bulkheads shifted by 2 m agree
    shift, _, agreeing = raster.align_to_profile(_stub_view(columns), _stub_view([c + 20 for c in columns]))
    assert agreeing and shift == pytest.approx(2.0)
