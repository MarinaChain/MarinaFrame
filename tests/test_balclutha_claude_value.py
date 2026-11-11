"""Synthetic tests for the round-7 Claude pack and scorer (no drawing, no truth, no model call)."""
import json

import pytest
from benchmarks.balclutha import claude_value as cv
from benchmarks.balclutha import model_value as round4
from benchmarks.balclutha import tiled_value as tv

SHEET_WIDTH, SHEET_HEIGHT = 9632, 14442  # the full-resolution sheet 7 (protocol 3.5.4)


def synthetic_truth():
    """Invented half-breadths (m): 21 stations x 8 waterlines, a smooth made-up shape."""
    return {(s, w): 1.0 + 0.1 * s + 0.05 * (w // 4) for s in round4.STATIONS for w in round4.WATERLINES_FT}


def write_answer(path, truth, offset=0.0, null_stations=()):
    stations = {str(s): [None if s in null_stations else truth[(s, w)] + offset for w in round4.WATERLINES_FT]
                for s in round4.STATIONS}
    path.write_text(json.dumps({'source': 'ai_inferred', 'waterlines_ft': list(round4.WATERLINES_FT),
                                'stations': stations}))


def test_layout_has_three_tiles_per_side_and_waterline_within_claude_limit_and_the_sheet():
    tiles = tv.tile_boxes(cv.CLAUDE_LAYOUT)
    assert len(tiles) == 48
    for tile in tiles:
        width, height = tv.tile_size(tile)
        left, top, right, bottom = tile['box']
        assert max(width, height) <= cv.CLAUDE_MAX_EDGE
        assert 0 <= left and right <= SHEET_WIDTH and 0 <= top and bottom <= SHEET_HEIGHT
        assert top < tv.WATERLINE_ROWS[tile['waterline']] < bottom


def test_tiles_of_one_waterline_overlap_and_reach_past_the_20_ft_buttock():
    for side in ('aft', 'fore'):
        boxes = sorted(t['box'] for t in tv.tile_boxes(cv.CLAUDE_LAYOUT) if t['side'] == side and t['waterline'] == 16)
        for first, second in zip(boxes, boxes[1:]):
            assert first[2] > second[0]
        outermost = boxes[-1][2] if side == 'fore' else boxes[0][0]
        buttock = tv.BUTTOCK_COLUMNS[side][-1]
        assert outermost > buttock if side == 'fore' else outermost < buttock


def test_tile_text_gives_calibration_and_grid_and_names_its_files():
    tile = next(t for t in tv.tile_boxes(cv.CLAUDE_LAYOUT) if t['id'] == 'fore-wl16-mid')
    text = cv.tile_text(tile)
    assert 'tiles/fore-wl16-mid.png' in text and 'context/fore-wl16-mid.png' in text
    assert '(1568 x 784 px)' in text and 'y = 392 px' in text and '491.48' in text


def test_task_text_lists_every_tile_and_the_answer_schema_without_values():
    tiles = tv.tile_boxes(cv.CLAUDE_LAYOUT)
    text = cv.task_text(tiles)
    assert all(tile['id'] in text for tile in tiles)
    assert 'ai_inferred' in text and '"stations"' in text and 'truth' not in text.lower()


def test_score_folder_groups_repeats_by_model_and_applies_the_decision_rule(tmp_path):
    truth = synthetic_truth()
    for repeat, offset in enumerate((0.01, -0.02, 0.03), 1):
        write_answer(tmp_path / f'good-{repeat}.json', truth, offset=offset)
        write_answer(tmp_path / f'bad-{repeat}.json', truth, offset=0.5)
    (tmp_path / 'notes.txt').write_text('ignored')
    summary = cv.score_folder(tmp_path, truth)
    assert set(summary['models']) == {'good', 'bad'}
    good, bad = summary['models']['good'], summary['models']['bad']
    assert good['model_adds_value'] is True and good['median_rms_m'] == pytest.approx(0.02, abs=1e-6)
    assert all(r['coverage'] == 1.0 for r in good['repeats'])
    assert bad['model_adds_value'] is False and bad['median_rms_m'] == pytest.approx(0.5)


def test_low_coverage_invalid_file_and_missing_repeat_fail_the_rule(tmp_path):
    truth = synthetic_truth()
    write_answer(tmp_path / 'sparse-1.json', truth)
    write_answer(tmp_path / 'sparse-2.json', truth)
    write_answer(tmp_path / 'sparse-3.json', truth, null_stations=range(10))
    (tmp_path / 'broken-1.json').write_text('not json')
    summary = cv.score_folder(tmp_path, truth)
    assert summary['models']['sparse']['repeats'][2]['coverage'] < round4.MIN_COVERAGE
    assert summary['models']['sparse']['model_adds_value'] is False
    broken = summary['models']['broken']['repeats'][0]
    assert broken['cells_given'] == 0 and 'invalid' in broken
    assert summary['models']['broken']['model_adds_value'] is False
