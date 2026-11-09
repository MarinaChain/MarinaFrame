"""Synthetic tests for the round-5 tiled Balclutha reading (no drawing, no model call)."""
import json

import numpy as np
import pytest
from benchmarks.balclutha import tiled_value as tv


def by_id():
    return {tile['id']: tile for tile in tv.tile_boxes()}


def test_tiles_cover_both_sides_every_waterline_within_the_provider_limit():
    tiles = tv.tile_boxes()
    assert len(tiles) == 32 and len(by_id()) == 32
    for tile in tiles:
        left, top, right, bottom = tile['box']
        assert right - left == tv.TILE_WIDTH <= 2048 and bottom - top == tv.TILE_HEIGHT <= 2048
        assert top < tv.WATERLINE_ROWS[tile['waterline']] < bottom
    inner, outer = by_id()['fore-wl16-inner']['box'], by_id()['fore-wl16-outer']['box']
    assert inner[0] < tv.CENTRE_COLUMN < inner[2] and outer[0] < inner[2]  # overlap
    assert outer[2] > tv.BUTTOCK_COLUMNS['fore'][-1]
    aft_outer = by_id()['aft-wl16-outer']['box']
    assert aft_outer[0] < tv.BUTTOCK_COLUMNS['aft'][-1] and aft_outer[2] < tv.CENTRE_COLUMN


def test_grid_and_prompt_name_only_lines_inside_the_tile():
    tile = by_id()['fore-wl16-outer']
    grid = tv.tile_grid(tile)
    assert set(grid['waterlines']) == {16} and grid['target_row'] == tv.TILE_HEIGHT // 2
    assert grid['centreline_x'] < 0 and 2 not in grid['buttocks'] and 20 in grid['buttocks']
    prompt = tv.tile_prompt(tile)
    assert 'stations 11 to 20' in prompt and 'y = 512' in prompt and str(grid['centreline_x']) in prompt


def reply(crossings):
    return '```json\n' + json.dumps({'source': 'ai_inferred', 'crossings': crossings}) + '\n```'


def test_parse_crossings_rejects_wrong_side_repeats_and_outside_x():
    tile = by_id()['aft-wl08-inner']
    assert tv.parse_crossings(reply([{'station': 3, 'x_px': 100}]), tile) == {3: 100.0}
    for bad in ([{'station': 15, 'x_px': 100}], [{'station': 3, 'x_px': 1}, {'station': 3, 'x_px': 2}],
                [{'station': 3, 'x_px': 5000}], [{'station': True, 'x_px': 1}]):
        with pytest.raises(ValueError):
            tv.parse_crossings(reply(bad), tile)


def test_merge_converts_to_half_breadth_means_overlap_and_counts_disagreement():
    tiles = by_id()
    inner, outer = tiles['fore-wl16-inner'], tiles['fore-wl16-outer']
    one_metre = tv.CENTRE_COLUMN + tv.PIXELS_PER_M  # sheet column 1 m out
    reading, disagreements = tv.merge([
        (inner, {12: one_metre - inner['box'][0], 13: 100.0}),
        (outer, {12: one_metre + 0.1 * tv.PIXELS_PER_M - outer['box'][0]})])
    assert reading[(12, 16)] == pytest.approx(1.05)
    assert disagreements == 0
    aft = tiles['aft-wl16-inner']
    reading, _ = tv.merge([(aft, {5: tv.CENTRE_COLUMN - 2 * tv.PIXELS_PER_M - aft['box'][0]})])
    assert reading[(5, 16)] == pytest.approx(2.0)
    _, disagreements = tv.merge([(inner, {12: 0.0}), (outer, {12: 0.0})])
    assert disagreements == 1


def test_r0_spec_keeps_the_waterline_in_range_and_value_lookup():
    tile = by_id()['fore-wl20-inner']
    section = tv.r0_spec(tile)['sections'][0]
    z = 20 * 0.3048
    assert section['z_min_m'] < z < section['z_max_m']
    assert 0 <= section['calibration']['centerline_px'] < tv.TILE_WIDTH
    points = [[-1.0, 5.0], [-2.0, 7.0]]
    assert tv.value_at_waterline(points, 20) == pytest.approx(1 + (z - 5) / 2)
    assert tv.value_at_waterline(points, 4) is None
    truth = {(11, 20): 5.8, (12, 20): 5.7}
    assert tv.nearest_station(5.72, tile, truth) == 12


def test_run_repeat_scores_a_fake_model_without_network(tmp_path):
    tiles = [t for t in tv.tile_boxes() if t['id'] in ('fore-wl16-inner', 'fore-wl16-outer')]
    truth = {(12, 16): 1.0, (13, 16): 0.5}
    images = {t['id']: (b'c', b't') for t in tiles}

    def fake_call(messages, receipts, settings):
        tile_id = 'fore-wl16-inner' if 'x = 48 px' in messages[0]['content'][0]['text'] else 'fore-wl16-outer'
        tile = next(t for t in tiles if t['id'] == tile_id)
        x = tv.CENTRE_COLUMN + tv.PIXELS_PER_M - tile['box'][0]
        text = reply([{'station': 12, 'x_px': x}] if 0 <= x <= tv.TILE_WIDTH else [])
        return text, {'state': 'completed', 'usage': {'prompt_tokens': 10, 'completion_tokens': 2}}

    result = tv.run_repeat(tiles, images, truth, tmp_path / 'R1-1', fake_call)
    assert result['cells_given'] == 1 and result['rms_m'] == pytest.approx(0.0, abs=1e-9)
    assert result['calls'] == 2 and result['invalid_replies'] == 0 and result['prompt_tokens'] == 20
    assert np.isclose(result['coverage'], 0.5)
