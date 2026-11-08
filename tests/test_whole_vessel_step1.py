"""Synthetic tests for whole-vessel step 1: labelled gap fills, GA reader, metrics, A/B parsing."""
import numpy as np
import pytest

from vessel_reconstruction import ga_reader
from vessel_reconstruction.ship_cad import resolve_program, validate_program


def house_program(outline='house_outline', height='house_height'):
    return {'schema': 'ship-cad/v1', 'components': [
        {'id': 'house', 'op': 'deckhouse', 'source': {'view': 'plan', 'region': 'house', 'method': 'enclosed_region'},
         'args': {'outline': outline, 'height': height}}]}


SQUARE = [[0.0, 0.0], [2.0, 0.0], [2.0, 1.0], [0.0, 1.0]]


def inline(value, source='ai_inferred', basis='read from the profile'):
    return {'value': value, 'source': source, 'basis': basis}


def test_inline_values_with_source_label_build_as_draft_guess():
    program = house_program(inline(SQUARE), inline([4.0, 6.5], 'guessed'))
    component = resolve_program(program, {})[0]
    assert component['status'] == 'draft_guess'
    assert component['geometry'] == {'outline': SQUARE, 'height': [4.0, 6.5]}
    assert component['source_labels'] == {'outline': 'ai_inferred', 'height': 'guessed'}


@pytest.mark.parametrize('bad', [2.5, {'value': [1, 2], 'source': 'traced', 'basis': 'x'},
                                 {'value': [1, 2], 'source': 'guessed', 'basis': ''},
                                 {'value': [2, 1], 'source': 'guessed', 'basis': 'reversed'},
                                 {'value': [1, 2], 'source': 'guessed', 'basis': 'x', 'code': 'import os'}])
def test_unlabelled_or_invalid_inline_value_is_rejected(bad):
    with pytest.raises(ValueError):
        validate_program(house_program(height=bad))


def test_host_guess_fills_failed_measurement():
    measurements = {'house_outline': {'status': 'measured', 'kind': 'outline', 'value': SQUARE, 'view': 'plan',
                                      'region': 'house', 'method': 'enclosed_region', 'source_sha256': 'a' * 64,
                                      'entity_ids': ['e1']},
                    'house_height': {'status': 'failed', 'reason': 'three levels'}}
    guesses = {'house_height': {'kind': 'interval', 'value': [4.0, 6.5], 'source': 'guessed', 'basis': 'hint'}}
    component = resolve_program(house_program(), measurements, guesses)[0]
    assert component['geometry'] == {'outline': SQUARE, 'height': [4.0, 6.5]}
    assert component['source_labels'] == {'outline': 'traced', 'height': 'guessed'}
    assert component['status'] == 'draft_guess'
    assert component['provenance']['house_height']['replaces'].startswith('house_height')


def test_no_measurement_and_no_valid_guess_stays_unbuilt():
    guesses = {'house_height': {'kind': 'outline', 'value': [4.0, 6.5], 'source': 'guessed', 'basis': 'wrong kind'}}
    component = resolve_program(house_program(), {}, guesses)[0]
    assert component['geometry'] is None


def test_profile_levels_merge_collinear_pieces_and_snap():
    view = ga_reader.View('profile', 'profile', [0, 0, 50000, 20000], [1000, 500])
    entities = [{'id': 'a', 'points': [[1000, 4787], [9000, 4787]]},
                {'id': 'b', 'points': [[9200, 4787], [15000, 4787]]},
                {'id': 'c', 'points': [[1000, 7187], [12000, 7187]]},
                {'id': 'short', 'points': [[1000, 6000], [1500, 6000]]}]
    levels = ga_reader.profile_levels(entities, view)
    assert [level.z_m for level in levels] == [4.287, 6.687]
    assert levels[0].intervals == [[0.0, 14.0]]
    assert levels[0].entity_ids == ['a', 'b']
    assert ga_reader.snap_level(levels, 4.3).z_m == 4.287
    assert ga_reader.snap_level(levels, 5.5) is None


def rectangle(entity_id, x0, y0, x1, y1):
    return {'id': entity_id, 'points': [[x0, y0], [x1, y0], [x1, y1], [x0, y1], [x0, y0]]}


def test_plan_footprint_outer_and_inner():
    view = ga_reader.View('plan', 'plan', [-1000, -6000, 31000, 6000], [0, 0])
    deck = rectangle('deck', 0, -5000, 30000, 5000)
    house = rectangle('house', 10000, -3000, 20000, 3000)
    raster = ga_reader.PlanRaster([deck, house], view, pixel_m=0.05)
    outer = raster.footprint([5.0, 25.0], 'outer')
    assert ga_reader.polygon_area(outer) == pytest.approx(20 * 10, rel=0.02)
    inner = raster.footprint([0.0, 30.0], 'inner')
    # The footprint runs to the outer side of the drawn wall line (about 0.1 m here).
    assert ga_reader.polygon_area(inner) == pytest.approx(10 * 6, rel=0.08)
    assert ga_reader.y_extent(inner) == pytest.approx(3.0, abs=0.15)


def test_clip_x_and_box():
    clipped = ga_reader.clip_x(ga_reader.box_outline([0, 10], 2), [2, 5])
    assert ga_reader.polygon_area(clipped) == pytest.approx(12)
    assert ga_reader.clip_x(SQUARE, [5, 6]) is None


def box_triangles(x0, x1, y0, y1, z0, z1):
    import trimesh

    mesh = trimesh.creation.box(extents=[x1 - x0, y1 - y0, z1 - z0])
    mesh.apply_translation([(x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2])
    return mesh.vertices[mesh.faces]


def test_top_height_map_of_a_box():
    from benchmarks.gunnerus.whole_vessel_metrics import CELL_M, top_height_map

    top = top_height_map(box_triangles(0, 10, -2, 2, 4.287, 6.687))
    assert np.nanmax(top) == pytest.approx(6.687)
    assert np.isfinite(top).sum() * CELL_M ** 2 == pytest.approx(40, rel=0.01)


def test_score_maps_on_synthetic_vessel():
    from benchmarks.gunnerus.whole_vessel_metrics import score_maps, top_height_map

    deck = box_triangles(-1, 15, -4.8, 4.8, 0, 4.1)
    house = box_triangles(15, 34, -4.8, 4.8, 0, 6.62)
    truth = top_height_map(np.concatenate([deck, house]))
    built = {'aft_deck': top_height_map(box_triangles(-1, 15, -4.8, 4.8, 4.09, 4.10)),
             'house_t1': top_height_map(box_triangles(15, 34, -4.8, 4.8, 4.287, 6.687))}
    result = score_maps(truth, built, {'aft_bulwark': 5.1})
    assert result['M1_deck_level_error_m'] == pytest.approx(0.0, abs=1e-6)
    assert result['M2_footprint_iou'] == pytest.approx(1.0, abs=0.01)
    assert result['M3_roof_height_error_m'] == pytest.approx(0.067, abs=1e-6)
    assert result['M5_x_end_error_m'] == pytest.approx([0.0, 0.0], abs=0.06)
    assert isinstance(result['M6_bulwark_top_error_m'], str)


def test_ab_reply_parsing():
    from benchmarks.gunnerus.whole_vessel_ab import extract_code, extract_json

    assert extract_json('Here:\n```json\n{"schema": "ship-cad/v1"}\n```') == {'schema': 'ship-cad/v1'}
    assert extract_json('{"a": 1}') == {'a': 1}
    assert 'def build' in extract_code('```python\ndef build():\n    return {}\n```')
    with pytest.raises(ValueError):
        extract_code('no code')


def test_ab_round_two_disables_thinking_and_round_one_does_not():
    from benchmarks.gunnerus.whole_vessel_ab import ROUNDS, request_body

    second = request_body([], ROUNDS['2'])
    assert second['thinking'] == {'type': 'disabled'} and second['max_tokens'] == 32_000
    assert second['stream'] is False
    assert 'thinking' not in request_body([], ROUNDS['1'])


@pytest.mark.cad
def test_arm_b_code_sees_no_credentials(tmp_path, monkeypatch):
    from benchmarks.gunnerus.whole_vessel_ab import build_arm_b

    monkeypatch.setenv('OPENCODE_API_KEY', 'secret-test-value')
    monkeypatch.setenv('OTHER_TOKEN', 'secret-test-value')
    code = ('```python\nimport os, cadquery as cq\n'
            'def build():\n'
            '    assert not any("secret" in v for v in os.environ.values())\n'
            '    return {"aft_deck": cq.Workplane("XY").box(1, 1, 1).val()}\n```')
    result = build_arm_b(code, tmp_path)
    assert result['result']['components'][0]['built'] is True


def test_transverse_walls_find_long_end_walls_only():
    view = ga_reader.View('plan', 'plan', [-1000, -6000, 31000, 6000], [0, 0])
    entities = [{'id': 'end', 'points': [[15500, -4800], [15500, 1900]]},
                {'id': 'locker', 'points': [[14500, 2000], [14500, 4800]]},
                {'id': 'side', 'points': [[15500, 4800], [30000, 4800]]}]
    walls = ga_reader.transverse_walls(entities, view, [12.3, 34.6], min_length_m=3.84)
    assert [(wall['x_m'], wall['entity_id']) for wall in walls] == [(15.5, 'end')]
