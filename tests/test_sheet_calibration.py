"""Automatic body-plan calibration on a synthetic drawing; no sheets, truth or model calls."""
import json
import subprocess

import numpy as np
import pytest

from vessel_reconstruction import calibration_reading as cr
from vessel_reconstruction import sheet_calibration as sc

PX_FT = 100.0
CENTRE = 1000
BASE = 1400
BOX = [500, 500, 1500, 1450]


def synthetic_sheet() -> np.ndarray:
    """A body plan: centreline, buttocks every 1 ft both sides, waterlines every 1 ft, a baseline,
    and three station curves per half that run from the keel to the 6 ft waterline."""
    ink = np.zeros((1600, 2000), dtype=bool)
    ink[550:BASE + 2, CENTRE - 1:CENTRE + 2] = True  # centreline, ends at the baseline
    for feet in range(1, 5):
        for sign in (-1, 1):
            column = CENTRE + sign * int(feet * PX_FT)
            ink[600:BASE, column - 1:column + 1] = True
    for feet in range(1, 7):
        row = BASE - int(feet * PX_FT)
        ink[row - 1:row + 1, 520:1480] = True
    ink[BASE - 1:BASE + 2, 520:1480] = True  # baseline
    rows = np.arange(BASE - 600, BASE - 20)
    for sign in (-1, 1):
        for fullness in (1.5, 2.5, 3.5):
            breadth = fullness * PX_FT * np.sqrt(np.clip((BASE - 20 - rows) / 580, 0, 1))
            for row, offset in zip(rows, breadth):
                column = int(CENTRE + sign * (offset + 12))
                ink[row, column - 2:column + 3] = True
    return ink


class FakeReading:
    """Answers the label questions as a model would on the synthetic sheet."""

    def __init__(self, shape_fore='right', lowest_at='bow', tag_centre=True):
        self.shape_fore, self.lowest_at, self.tag_centre = shape_fore, lowest_at, tag_centre

    def locate(self, ink):
        return {'body_plan_box_px': BOX, 'scale_text': '1" = 1\'-0"', 'source': 'test'}

    def label_lines(self, ink, box, horizontals, verticals):
        centre = next(line for line in verticals if abs(line.position - CENTRE) < 3)
        heights = [(line, (BASE - line.position) / PX_FT) for line in horizontals
                   if abs(line.position - BASE) > 3]
        return {'horizontal_ft': heights, 'base_lines': [], 'vertical_ft': [],
                'centreline': centre if self.tag_centre else None,
                'stations_left': [4, 5, 6], 'stations_right': [1, 2, 3]}

    def read_notes(self, ink):
        return {'buttock_spacing_ft': 1.0}

    def read_scale_bar(self, ink, box):
        return {}

    def numbering_direction(self, ink):
        return {'lowest_at': self.lowest_at}

    def fore_half_by_shape(self, ink, box, centre):
        return {'fore_half': self.shape_fore}


def test_calibrates_synthetic_body_plan_with_agreeing_checks():
    ink = synthetic_sheet()
    cal = sc.calibrate(ink, FakeReading(), dpi=100.0)
    assert cal.flags == []
    assert cal.usable and cal.engineering_approved is False
    assert abs(cal.centre_column - CENTRE) <= 1
    assert abs(cal.pixels_per_ft - PX_FT) / PX_FT < 0.01
    assert abs(cal.baseline_row - BASE) <= 1
    fore = next(s for s in cal.sides if s['name'] == 'fore')
    aft = next(s for s in cal.sides if s['name'] == 'aft')
    assert (fore['sign'], fore['stations_outer_first']) == (1, [3, 2, 1])
    assert (aft['sign'], aft['stations_outer_first']) == (-1, [4, 5, 6])
    assert len(fore['grid_columns']) == 4
    assert sorted(round(w['height_ft']) for w in cal.waterlines) == [1, 2, 3, 4, 5, 6]
    assert all(cal.sources[key] for key in ('centre_column', 'pixels_per_ft', 'baseline_row', 'sides'))
    assert set(cal.measures['scale']) >= {'scale_ratio', 'waterline_labels', 'buttock_grid'}
    layout = cal.layout()
    assert layout.pixels_per_metre == pytest.approx(cal.pixels_per_ft / 0.3048)
    assert cal.row_at(3.0) == BASE - 300
    json.dumps(cal.to_json())


def test_side_checks_that_disagree_are_flagged_not_silent():
    cal = sc.calibrate(synthetic_sheet(), FakeReading(shape_fore='left'), dpi=100.0)
    assert cal.flagged('sides')
    assert cal.usable  # provisional layout for the person to correct
    assert all(side['source'].startswith('provisional') for side in cal.sides)


def test_single_scale_measure_is_flagged():
    value, source, problems = sc.choose_scale({'buttock_grid': {'px_per_ft': 100.0}})
    assert value == 100.0 and problems and 'only one' in problems[0]


def test_disagreeing_scales_are_flagged_and_a_third_agreeing_pair_wins():
    _, _, problems = sc.choose_scale({'buttock_grid': {'px_per_ft': 100.0}, 'scale_ratio': {'px_per_ft': 110.0}})
    assert problems and 'disagree' in problems[0]
    value, source, problems = sc.choose_scale({'scale_bar': {'px_per_ft': 400.0}, 'buttock_grid': {'px_per_ft': 399.0},
                                               'waterline_spacing': {'px_per_ft': 534.0}})
    assert value == 400.0 and 'agrees' in source
    assert any('waterline_spacing disagrees' in p for p in problems)


def test_missing_centreline_tag_uses_grid_symmetry_with_a_flag():
    cal = sc.calibrate(synthetic_sheet(), FakeReading(tag_centre=False), dpi=100.0)
    assert abs(cal.centre_column - CENTRE) <= 1
    assert cal.flagged('centre_column')


@pytest.mark.parametrize('text, feet', [("3'-7\"", 3 + 7 / 12), ('17\'-7" WL', 17 + 7 / 12), ('2-6-0', 2.5),
                                        ('4 Ft.', 4.0), ('8-1/16"', 8.0625 / 12), ('9"', 0.75), ('-1-0-0', -1.0),
                                        ('12', 12.0), (None, None), ('STA', None)])
def test_parse_feet(text, feet):
    value = sc.parse_feet(text)
    assert value == pytest.approx(feet) if feet is not None else value is None


def test_scale_ratio_and_station_order_helpers():
    assert sc.parse_scale_ratio('3/8" = 1\'-0"') == pytest.approx(0.375)
    assert sc.parse_scale_ratio('SCALE: 3/4"=1\'-0"') == pytest.approx(0.75)
    assert sc.parse_scale_ratio(None) is None
    assert sc.stations_outer_first([1, 2, 3, 4, 5, 6], [7, 8]) == (6, 5, 4, 3, 2, 1)
    assert sc.stations_outer_first([12, 13, 14], [1, 2]) == (12, 13, 14)
    assert sc.fore_half_from_numbering([0, 1], [11, 12], 'stern') == 'right'
    assert sc.fore_half_from_numbering([1, 2], [7, 8], 'bow') == 'left'
    assert sc.fore_half_from_numbering([1], [7], 'unsure') is None
    assert sc.feet_inches(2.5) == '2-6-0' and sc.feet_inches(-1.0) == '-1-0-0'
    assert sc.common_spacing([0, 100, 201, 300, 350]) == pytest.approx(100.5, abs=1)


def test_scale_bar_ticks_on_a_stepped_bar():
    crop = np.zeros((200, 1000), dtype=bool)
    crop[50:56, 100:300] = True
    crop[80:86, 300:500] = True
    crop[50:56, 500:700] = True
    for column in (100, 300, 500, 700):
        crop[50:86, column - 1:column + 2] = True
    assert cr.scale_bar_ticks(crop) == pytest.approx([100, 300, 500, 700], abs=1)


def test_reading_parses_answers_and_caches(tmp_path):
    calls = []

    def ask(prompt, pngs):
        calls.append(prompt)
        assert pngs and pngs[0].startswith(b'\x89PNG')
        return 'Here: ```json\n{"lowest_at": "stern", "evidence": "Transom next to 22"}\n```'

    ink = synthetic_sheet()
    reading = cr.ClaudeReading(ask, tmp_path, 'synthetic')
    assert reading.numbering_direction(ink)['lowest_at'] == 'stern'
    again = cr.ClaudeReading(ask, tmp_path, 'synthetic')
    assert again.numbering_direction(ink)['lowest_at'] == 'stern'
    assert len(calls) == 1 and again.calls == 0


def test_reading_maps_tags_to_lines():
    ink = synthetic_sheet()
    horizontals = sc.straight_lines(ink, BOX, 'h')
    verticals = sc.straight_lines(ink, BOX, 'v')
    answer = {'horizontal': {'H1': "6'-0\" WL", f'H{len(horizontals)}': 'BASE'}, 'vertical': {'V1': '4 Ft.'},
              'centreline': 'V5', 'stations_left': ['STA 4', 5], 'stations_right': [1, '2', 'Transom']}
    reading = cr.ClaudeReading(lambda prompt, pngs: json.dumps(answer))
    labels = reading.label_lines(ink, BOX, horizontals, verticals)
    assert labels['horizontal_ft'][0][1] == pytest.approx(6.0)
    assert labels['base_lines'][0].position == pytest.approx(BASE, abs=1)
    assert labels['vertical_ft'][0][1] == 4.0
    assert labels['centreline'].position == pytest.approx(CENTRE, abs=1)
    assert labels['stations_left'] == [4, 5] and labels['stations_right'] == [1, 2]


def test_claude_transport_removes_api_keys(monkeypatch):
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'not-a-real-key')
    seen = {}

    def runner(command, **kwargs):
        seen.update(command=command, env=kwargs['env'])
        result = {'type': 'result', 'subtype': 'success', 'is_error': False, 'result': '{"a": 1}', 'usage': {}}
        return subprocess.CompletedProcess(command, 0, stdout=json.dumps(result) + '\n', stderr='')

    text = cr.claude_ask(runner=runner)('prompt', [b'\x89PNG'])
    assert text == '{"a": 1}'
    assert 'ANTHROPIC_API_KEY' not in seen['env'] and seen['command'][:2] == ['claude', '-p']


def test_overlay_png_draws_flags():
    ink = synthetic_sheet()
    cal = sc.calibrate(ink, FakeReading(shape_fore='left'), dpi=100.0)
    png = cr.overlay_png(ink, cal)
    assert png.startswith(b'\x89PNG')


def test_reader_modules_are_not_changed_by_this_work():
    import hashlib
    from pathlib import Path
    frozen = {'src/vessel_reconstruction/body_plan_reader.py':
              '327c9f141876dc1945383ebe35023b6e7baaacc34306c5eecf26ffb16ba94e11'}
    root = Path(__file__).resolve().parents[1]
    for name, digest in frozen.items():
        assert hashlib.sha256((root / name).read_bytes()).hexdigest() == digest


def test_longest_line_next_to_a_mistagged_centreline_is_used():
    keel_edge = sc.Line(1000.0 - 15, 3, 0.2)  # within 2 % of the box width
    centre = sc.Line(1000.0, 3, 0.9)
    one_sided = [sc.Line(1000.0 - 100 * k, 3, 0.4) for k in range(1, 5)]
    column, source, evidence = sc.choose_centreline([keel_edge, centre] + one_sided, [500, 0, 1500, 1000], keel_edge)
    assert column == 1000.0 and 'longest' in source and 'note' in evidence


def test_waterline_lattice_drops_lines_off_the_grid():
    lines = [sc.Line(r, 3, 0.4) for r in (6095, 6480, 6880, 7281, 7681, 7887, 8081)]
    kept = [line.position for line in sc.waterline_lattice(lines)]
    assert kept == [6480, 6880, 7281, 7681, 8081]


def test_frame_lines_are_not_buttocks():
    lines = [sc.Line(900.0, 3, 0.4), sc.Line(600.0, 6, 0.97), sc.Line(1100.0, 3, 0.4)]
    grid = sc.grid_lines(lines, 1000.0, [500, 0, 1500, 1000])
    assert [l.position for l in grid[-1]] == [900.0] and [l.position for l in grid[1]] == [1100.0]
