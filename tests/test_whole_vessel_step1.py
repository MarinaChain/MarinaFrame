"""Synthetic tests for whole-vessel step 1: labelled gap fills, GA reader, metrics, A/B parsing."""
import sys

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
    pytest.importorskip('cv2', reason='PlanRaster needs the plan-raster extra (OpenCV)')
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


def raster_with_lines():
    """A 0.05 m/px raster: one deck line, one short detail and one transverse wall."""
    ink = np.zeros((200, 400), np.uint8)
    ink[100:102, 20:300] = 255  # 14 m long horizontal line
    ink[50:52, 20:30] = 255  # 0.5 m detail
    ink[110:190, 150:152] = 255  # 4 m transverse line
    return ink


def test_raster_levels_and_walls():
    ink = raster_with_lines()
    x_of_column = lambda c: -1.0 + 0.05 * c
    z_of_row = lambda r: 10.0 - 0.05 * r
    levels = ga_reader.raster_levels(ink, x_of_column, z_of_row, 0.05)
    assert len(levels) == 1
    assert levels[0].z_m == pytest.approx(4.975)
    assert levels[0].intervals == [pytest.approx([0.0, 13.95])]
    walls = ga_reader.raster_transverse_walls(ink, x_of_column, [0, 20], 3.0, 0.05)
    assert [round(wall['x_m'], 3) for wall in walls] == [6.525]
    assert walls[0]['length_m'] == pytest.approx(4.0)


def test_plan_raster_from_ink_footprint():
    pytest.importorskip('cv2', reason='PlanRaster needs the plan-raster extra (OpenCV)')
    ink = np.zeros((120, 220), np.uint8)
    ink[10:12, 10:210] = 255
    ink[108:110, 10:210] = 255
    ink[10:110, 10:12] = 255
    ink[10:110, 208:210] = 255
    plan = ga_reader.PlanRaster.from_ink(ink, x_min=0.0, y_max=3.0, pixel_m=0.05, evidence='test')
    outline = plan.footprint([0.0, 20.0])
    assert ga_reader.polygon_area(outline) == pytest.approx(10.0 * 5.0, rel=0.03)


def test_is_simple_polygon():
    assert ga_reader.is_simple_polygon(SQUARE)
    assert not ga_reader.is_simple_polygon([[0, 0], [2, 2], [2, 0], [0, 2]])  # bow tie
    assert not ga_reader.is_simple_polygon([[0, 0], [2, 0], [1, 0], [1, 1]])  # spur back on an edge


def test_app_parts_folder_matches_the_worker_shape(tmp_path):
    import json

    from benchmarks.gunnerus.whole_vessel_assembly import (
        hull_component,
        write_app_parts,
    )

    step1 = tmp_path / 'step1'
    step1.mkdir()
    (step1 / 'execution.json').write_text(json.dumps({'result': {'components': [
        {'id': 'house_t1', 'op': 'deckhouse', 'status': 'draft_guess', 'built': True, 'volume_m3': 4.0,
         'bbox_m': {'min': [0, 0, 0], 'max': [1, 1, 1]}, 'source_labels': {'outline': 'traced', 'height': 'guessed'},
         'provenance': {'house_t1_outline': {'view': 'plan', 'method': 'enclosed_region'},
                        'house_t1_height': {'source': 'guessed', 'basis': 'hint'}}},
        {'id': 'rail', 'op': 'bulwark', 'status': 'draft_guess', 'built': False, 'source_labels': {}}]}}))
    program = {'schema': 'ship-cad/v1', 'components': [
        {'id': 'house_t1', 'op': 'deckhouse',
         'source': {'view': 'plan', 'region': 'house_t1', 'method': 'enclosed_region'},
         'args': {'outline': 'house_t1_outline', 'height': 'house_t1_height'}}]}
    inputs = {'program': program, 'measurements': {}, 'guesses': {
        'house_t1_outline': {'kind': 'outline', 'value': SQUARE, 'source': 'guessed', 'basis': 'box'},
        'house_t1_height': {'kind': 'interval', 'value': [4.0, 6.5], 'source': 'guessed', 'basis': 'hint'}}}
    cap = {'split_x_m': 15.5, 'aft_deck_z_m': 4.114, 'main_deck_z_m': 4.287}
    hull = hull_component(900.0, {'min': [0, 0, 0], 'max': [1, 1, 1]}, cap, {'stations': 68})
    folder = write_app_parts(step1, inputs, tmp_path, hull)
    record = json.loads((folder / 'execution.json').read_text())
    items = {item['id']: item for item in record['result']['components']}
    assert record['result']['engineering_approved'] is False
    assert items['hull']['op'] == 'hull' and items['hull']['label'].startswith('Hull')
    assert items['house_t1']['label'] == 'Superstructure tier 1 (1-deck to A-deck)'
    assert items['house_t1']['provenance']['height'] == {'source': 'guessed', 'basis': 'hint'}
    assert items['house_t1']['provenance']['outline']['basis'] == 'enclosed_region in the plan view'
    assert items['rail']['built'] is False
    assert items['house_t1']['args'] == {'outline': 'house_t1_outline', 'height': 'house_t1_height'}
    assert items['house_t1']['geometry'] == {'outline': SQUARE, 'height': [4.0, 6.5]}
    assert items['hull']['geometry']['deck_at_side'] == [4.114, 4.287]


def two_component_program(bad_method='invented_method', bad_height=None):
    good = house_program(inline(SQUARE), inline([4.0, 6.5]))['components'][0]
    other = {'id': 'wheelhouse', 'op': 'deckhouse',
             'source': {'view': 'profile', 'region': 'wheelhouse', 'method': bad_method},
             'args': {'outline': inline(SQUARE), 'height': bad_height or inline([6.5, 9.0])}}
    return {'schema': 'ship-cad/v1', 'components': [good, other]}


def test_unknown_source_method_builds_as_labelled_guess():
    from vessel_reconstruction.ship_cad import UNSPECIFIED, triage_program

    with pytest.raises(ValueError, match='wheelhouse'):
        validate_program(two_component_program())
    program, unbuilt, notes = triage_program(two_component_program())
    assert unbuilt == [] and 'invented_method' in notes['wheelhouse']
    component = resolve_program(program, {})[1]
    assert component['source']['method'] == UNSPECIFIED
    assert component['status'] == 'draft_guess' and component['geometry'] is not None
    assert 'source metadata not recognised' in component['reason']


def test_one_invalid_component_does_not_reject_the_others():
    from vessel_reconstruction.ship_cad import triage_program

    bad = {'value': [9.0, 6.5], 'source': 'ai_inferred', 'basis': 'reversed interval'}
    program, unbuilt, _ = triage_program(two_component_program('closed_outline', bad))
    assert [c['id'] for c in program['components']] == ['house']
    assert unbuilt[0]['id'] == 'wheelhouse' and unbuilt[0]['built'] is False
    assert 'not built' in unbuilt[0]['reason']
    with pytest.raises(ValueError, match='no buildable component'):
        triage_program({'schema': 'ship-cad/v1', 'components': [two_component_program('x', bad)['components'][1]]})


@pytest.mark.cad
def test_execute_reports_unbuilt_component_and_builds_the_rest(tmp_path):
    from vessel_reconstruction.ship_cad import execute

    bad = {'value': [9.0, 6.5], 'source': 'ai_inferred', 'basis': 'reversed interval'}
    report = execute(two_component_program('closed_outline', bad), {}, tmp_path)
    built = {c['id']: c.get('built') for c in report['components']}
    assert built == {'house': True, 'wheelhouse': False}
    assert (tmp_path / 'house.step').is_file()
    house = report['components'][0]
    assert house['geometry']['height'] == [4.0, 6.5] and house['args']['outline']['source'] == 'ai_inferred'


def test_cap_region_rows_cuts_at_the_deck():
    from benchmarks.gunnerus.whole_vessel_assembly import cap_region_rows, cap_sections

    rows = [[0.0, 0.0, 1.0], [4.0, 0.0, 3.0], [6.0, 0.0, 4.0]]
    assert cap_region_rows(rows, 5.0) == [[0.0, 0.0, 1.0], [4.0, 0.0, 3.0], [5.0, 0.0, 3.5]]
    assert cap_region_rows([[6.0, 0, 1], [7.0, 0, 1]], 5.0) is None
    deck = {'split_x_m': 10.0, 'aft_deck_z_m': 4.0, 'main_deck_z_m': 5.0}
    sections = [{'id': 'a', 'x_m': 5.0, 'regions': [{'kind': 'centreline', 'rows_m': rows}]},
                {'id': 'b', 'x_m': 15.0, 'regions': [{'kind': 'centreline', 'rows_m': rows}]}]
    capped = cap_sections(sections, deck)
    assert capped[0]['regions'][0]['rows_m'][-1][0] == 4.0 and capped[1]['regions'][0]['rows_m'][-1][0] == 5.0


def revision_folder(tmp_path):
    import json

    from PIL import Image

    parts = tmp_path / 'whole_vessel'
    parts.mkdir()
    entries = [{'id': 'hull', 'op': 'hull', 'built': True, 'status': 'measured_draft'},
               {'id': 'wheelhouse', 'op': 'deckhouse', 'label': 'Wheelhouse', 'built': True,
                'status': 'draft_guess', 'geometry': {'outline': SQUARE, 'height': [9.0, 11.5]},
                'source_labels': {'outline': 'guessed', 'height': 'traced'}, 'provenance': {}}]
    (parts / 'execution.json').write_text(json.dumps({'result': {'components': entries}}))
    (parts / 'wheelhouse.step').write_text('old')
    Image.new('L', (10, 10), 255).save(tmp_path / 'view.png')
    pack = {'images': [{'view': 'profile', 'path': str(tmp_path / 'view.png'), 'width': 10, 'height': 10,
                        'calibration': {'x_m': '0 + 1 * px', 'z_m': '10 - 1 * py'}}]}
    return pack


def fake_model(reply):
    def call(messages, receipts, settings):
        assert settings['thinking'] == 'disabled'
        assert 'narrower' in messages[0]['content'][0]['text']
        return reply, {'request_id': 'test', 'state': 'completed', 'usage': {}, 'seconds': 0.0}
    return call


@pytest.mark.cad
@pytest.mark.skipif(sys.platform != 'darwin', reason='the ship-cad worker needs the macOS sandbox')
def test_revise_rebuilds_only_the_marked_part(tmp_path):
    import json

    from benchmarks.gunnerus.whole_vessel_revise import revise

    pack = revision_folder(tmp_path)
    narrow = [[0.0, -0.5], [2.0, -0.5], [2.0, 0.5], [0.0, 0.5]]
    reply = json.dumps({'schema': 'ship-cad/v1', 'components': [
        {'id': 'wheelhouse', 'op': 'deckhouse', 'source': {'view': 'plan', 'region': 'wheelhouse',
                                                          'method': 'closed_outline'},
         'args': {'outline': inline(narrow), 'height': inline([9.0, 11.5])}}]})
    entry = revise(tmp_path, pack, 'wheelhouse', 'Make it narrower: 1 m wide', call=fake_model(reply))
    assert entry['revision'] == 1 and entry['geometry']['outline'] == narrow
    assert entry['source_labels'] == {'outline': 'ai_inferred', 'height': 'ai_inferred'}
    assert entry['revision_history'][0]['geometry']['outline'] == SQUARE
    saved = json.loads((tmp_path / 'whole_vessel' / 'execution.json').read_text())['result']['components']
    assert saved[0] == {'id': 'hull', 'op': 'hull', 'built': True, 'status': 'measured_draft'}
    assert (tmp_path / 'whole_vessel' / 'wheelhouse.r0.step').read_text() == 'old'


def test_revise_refuses_hull_and_empty_note(tmp_path):
    from benchmarks.gunnerus.whole_vessel_revise import revise

    pack = revision_folder(tmp_path)
    with pytest.raises(ValueError, match='cannot be revised'):
        revise(tmp_path, pack, 'hull', 'lower it', call=fake_model('{}'))
    with pytest.raises(ValueError, match='1 to 500'):
        revise(tmp_path, pack, 'wheelhouse', ' ', call=fake_model('{}'))
