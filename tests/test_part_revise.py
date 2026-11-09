"""Re-run one whole-vessel part from a mark (vessel_reconstruction.part_revise). No model calls."""
from __future__ import annotations

import json
import re
import sys

import pytest

from vessel_reconstruction import part_revise
from vessel_reconstruction.part_revise import PartReviseError

SQUARE = [[14.0, -3.5], [21.0, -3.5], [21.0, 3.5], [14.0, 3.5]]


def inline(value):
    return {'value': value, 'source': 'ai_inferred', 'basis': 'test'}


def write_dxf(path):
    """A drawing in millimetres: a profile box (z 9 to 11.5 m) above a plan box (y +-3.5 m)."""
    import ezdxf

    document = ezdxf.new()
    space = document.modelspace()
    # Profile view: origin (0, 50000); the wheelhouse side from x 14 to 21 m, z 9 to 11.5 m.
    space.add_lwpolyline([(14000, 59000), (21000, 59000), (21000, 61500), (14000, 61500)], close=True)
    space.add_text('WHEELHOUSE', dxfattribs={'insert': (15000, 60000), 'height': 300})
    # Plan view: origin (0, 20000); the wheelhouse plan, y from -3.5 to 3.5 m.
    space.add_lwpolyline([(14000, 16500), (21000, 16500), (21000, 23500), (14000, 23500)], close=True)
    document.saveas(path)


def views_manifest(drawing, **extra):
    return {'schema': part_revise.VIEWS_SCHEMA, 'views': {
        'profile': {'kind': 'profile', 'file': drawing, 'bounds': [0, 45000, 40000, 65000],
                    'origin': [0, 50000], 'metres_per_unit': 0.001, 'layers': None, **extra},
        'plan_adeck': {'kind': 'plan', 'file': drawing, 'bounds': [0, 14000, 40000, 26000],
                       'origin': [0, 20000], 'metres_per_unit': 0.001, 'layers': None, **extra}}}


def make_task(tmp_path, entry_extra=None):
    task = tmp_path / 'task'
    parts = task / 'whole_vessel'
    parts.mkdir(parents=True)
    write_dxf(task / 'ga.dxf')
    (parts / 'views.json').write_text(json.dumps(views_manifest('ga.dxf')))
    entries = [{'id': 'hull', 'op': 'hull', 'built': True, 'status': 'measured_draft'},
               {'id': 'wheelhouse', 'op': 'deckhouse', 'label': 'Wheelhouse', 'built': True,
                'status': 'draft_guess', 'geometry': {'outline': SQUARE, 'height': [9.0, 11.5]},
                'source_labels': {'outline': 'guessed', 'height': 'traced'},
                'provenance': {'wheelhouse_height': {'view': 'profile'},
                               'outline': {'source': 'guessed', 'basis': 'tier-2 breadth'}},
                'bbox_m': {'min': [14.0, -3.5, 9.0], 'max': [21.0, 3.5, 11.5]}, **(entry_extra or {})}]
    (parts / 'execution.json').write_text(json.dumps(
        {'exit_code': 0, 'result': {'engineering_approved': False, 'components': entries}}))
    (parts / 'wheelhouse.step').write_text('old')
    return task


def metres(formula, pixel):
    start, step = (float(v) for v in re.match(r'(-?[\d.]+) [+-] ([\d.]+) \* p[xy]', formula).groups())
    return start + step * pixel if '+' in formula else start - step * pixel


def test_pack_crops_the_part_from_each_view_with_a_calibration(tmp_path):
    task = make_task(tmp_path)
    entry = json.loads((task / 'whole_vessel/execution.json').read_text())['result']['components'][1]
    pack = part_revise.build_pack(task, entry, tmp_path / 'pack')
    assert [m['view'] for m in pack['images']] == ['profile', 'plan_adeck']
    for meta in pack['images']:
        assert meta['width'] * meta['height'] <= part_revise.MAX_IMAGE_PIXELS
        # The crop holds the part plus context, not the whole view (40 m long).
        left = metres(meta['calibration']['x_m'], 0)
        right = metres(meta['calibration']['x_m'], meta['width'])
        assert left < 14.0 and right > 21.0 and right - left < 20.0
    profile = pack['images'][0]['calibration']
    top, bottom = metres(profile['z_m'], 0), metres(profile['z_m'], pack['images'][0]['height'])
    assert bottom < 9.0 < 11.5 < top
    plan = pack['images'][1]['calibration']
    assert metres(plan['y_m'], 0) > 3.5 and metres(plan['y_m'], pack['images'][1]['height']) < -3.5


def test_a_raster_view_is_cropped_with_rows_going_down(tmp_path):
    from PIL import Image

    Image.new('L', (400, 200), 255).save(tmp_path / 'profile.png')
    view = {'kind': 'profile', 'file': tmp_path / 'profile.png', 'bounds': [0, 0, 400, 200],
            'origin': [0, 150], 'metres_per_unit': 0.1, 'y_down': True}
    box = {'x': [10.0, 20.0], 'z': [2.0, 4.0]}
    window = part_revise.crop_window(view, box)
    image, scale, window = part_revise._render_raster(view, window)
    formula = part_revise.calibration(view, window, scale)
    assert metres(formula['x_m'], 0) < 10.0 < 20.0 < metres(formula['x_m'], image.width)
    assert metres(formula['z_m'], image.height) < 2.0 < 4.0 < metres(formula['z_m'], 0)
    assert part_revise.crop_window(view, {'x': [100.0, 120.0], 'z': [2.0, 4.0]}) is None


def test_views_must_be_complete_and_unchanged(tmp_path):
    task = make_task(tmp_path)
    entry = json.loads((task / 'whole_vessel/execution.json').read_text())['result']['components'][1]
    (task / 'whole_vessel/views.json').write_text(json.dumps(views_manifest('ga.dxf', sha256='0' * 64)))
    with pytest.raises(PartReviseError, match='changed after the run read it'):
        part_revise.build_pack(task, entry, tmp_path / 'pack')
    (task / 'whole_vessel/views.json').write_text(json.dumps({'schema': 'other', 'views': {}}))
    with pytest.raises(PartReviseError, match='unknown form'):
        part_revise.build_pack(task, entry, tmp_path / 'pack')
    (task / 'whole_vessel/views.json').unlink()
    with pytest.raises(PartReviseError, match='views.json'):
        part_revise.build_pack(task, entry, tmp_path / 'pack')


def test_prompt_has_the_note_values_and_the_argument_forms(tmp_path):
    entry = {'id': 'skeg_ps', 'op': 'appendage', 'label': 'Skeg', 'geometry': {'outline': SQUARE, 'span': [1, 2]},
             'source_labels': {'outline': 'traced', 'span': 'guessed'},
             'provenance': {'span': {'source': 'guessed', 'basis': 'half breadth guessed'}}}
    pack = {'images': []}
    text = part_revise.revision_prompt(entry, 'Make it 0.5 m deeper', pack)[0]['content'][0]['text']
    assert 'Make it 0.5 m deeper' in text and 'half breadth guessed' in text
    assert 'profile polygon [[x, z]' in text and '"view":"profile"' in text
    assert '- span (guessed): [1, 2]' in text


def test_refusals_change_nothing(tmp_path):
    task = make_task(tmp_path)
    before = (task / 'whole_vessel/execution.json').read_text()
    model = part_revise.scripted_model([])
    with pytest.raises(PartReviseError, match='cannot be re-run'):
        part_revise.revise_part(task, 'hull', 'lower it', call=model)
    with pytest.raises(PartReviseError, match='1 to 500'):
        part_revise.revise_part(task, 'wheelhouse', ' ', call=model)
    with pytest.raises(PartReviseError, match='1 to 500'):
        part_revise.revise_part(task, 'wheelhouse', 'x' * 501, call=model)
    with pytest.raises(PartReviseError, match='no such part'):
        part_revise.revise_part(task, '../escape', 'lower it', call=model)
    with pytest.raises(PartReviseError, match='no new revision'):
        part_revise.undo_revision(task, 'wheelhouse')
    assert (task / 'whole_vessel/execution.json').read_text() == before


def test_an_unchanged_value_keeps_its_label_and_evidence():
    old = {'id': 'w', 'op': 'deckhouse', 'geometry': {'outline': SQUARE, 'height': [9.0, 11.5]},
           'source_labels': {'outline': 'guessed', 'height': 'traced'},
           'provenance': {'height': {'source': 'traced', 'basis': 'profile levels'}}}
    built = {'id': 'w', 'op': 'deckhouse', 'geometry': {'outline': SQUARE[:3], 'height': [9.0, 11.5]},
             'source_labels': {'outline': 'ai_inferred', 'height': 'ai_inferred'},
             'provenance': {'outline': {'source': 'ai_inferred', 'basis': 'mark'},
                            'height': {'source': 'ai_inferred', 'basis': 'kept'}}}
    entry = part_revise.updated_entry(old, built, 'narrower', 1, [])
    assert entry['source_labels'] == {'outline': 'ai_inferred', 'height': 'traced'}
    assert entry['provenance']['height']['basis'] == 'profile levels'
    assert entry['revision_history'] == [old]


def pending_revision(task):
    """The state revise_part leaves: a new entry with the old one in its history, old STEP kept."""
    parts = task / 'whole_vessel'
    record = json.loads((parts / 'execution.json').read_text())
    old = record['result']['components'][1]
    built = dict(old, geometry={'outline': SQUARE[:3], 'height': [9.0, 11.0]},
                 source_labels={'outline': 'ai_inferred', 'height': 'ai_inferred'})
    record['result']['components'][1] = part_revise.updated_entry(old, built, 'narrower', 1, [])
    (parts / 'execution.json').write_text(json.dumps(record))
    (parts / 'wheelhouse.r0.step').write_text('old')
    (parts / 'wheelhouse.step').write_text('new')
    return old


def test_undo_restores_the_previous_entry_and_step(tmp_path):
    task = make_task(tmp_path)
    old = pending_revision(task)
    restored = part_revise.undo_revision(task, 'wheelhouse')
    assert restored == old
    saved = json.loads((task / 'whole_vessel/execution.json').read_text())
    assert saved['result']['components'][1] == old and saved['result']['engineering_approved'] is False
    assert (task / 'whole_vessel/wheelhouse.step').read_text() == 'old'
    assert not (task / 'whole_vessel/wheelhouse.r0.step').exists()


def test_keep_ends_the_choice_and_keeps_the_history(tmp_path):
    task = make_task(tmp_path)
    pending_revision(task)
    kept = part_revise.keep_revision(task, 'wheelhouse')
    assert kept['revision_kept'] is True and kept['revision_history'][0]['geometry']['outline'] == SQUARE
    with pytest.raises(PartReviseError, match='no new revision'):
        part_revise.undo_revision(task, 'wheelhouse')
    assert (task / 'whole_vessel/wheelhouse.step').read_text() == 'new'


def test_command_line_refusal_is_json_on_stderr(tmp_path, capsys):
    task = make_task(tmp_path)
    assert part_revise.main(['--task', str(task), '--part', 'hull', '--note=lower it']) == 2
    assert 'cannot be re-run' in json.loads(capsys.readouterr().err)['error']


@pytest.mark.cad
@pytest.mark.skipif(sys.platform != 'darwin', reason='the ship-cad worker needs the macOS sandbox')
def test_revise_from_the_command_line_with_a_scripted_model(tmp_path, capsys):
    task = make_task(tmp_path)
    narrow = [[14.0, -0.5], [21.0, -0.5], [21.0, 0.5], [14.0, 0.5]]
    good = json.dumps({'schema': 'ship-cad/v1', 'components': [
        {'id': 'wheelhouse', 'op': 'deckhouse', 'source': {'view': 'plan', 'region': 'wheelhouse',
                                                          'method': 'closed_outline'},
         'args': {'outline': inline(narrow), 'height': inline([9.0, 11.5])}}]})
    replies = tmp_path / 'replies.json'
    replies.write_text(json.dumps(['not json', good]))  # the first reply goes back with the reason
    code = part_revise.main(['--task', str(task), '--part', 'wheelhouse', '--note=Make it 1 m wide',
                             '--replies', str(replies)])
    assert code == 0, capsys.readouterr().err
    assert json.loads(capsys.readouterr().out)['revision'] == 1
    entry = json.loads((task / 'whole_vessel/execution.json').read_text())['result']['components'][1]
    assert entry['geometry']['outline'] == narrow and entry['revision_note'] == 'Make it 1 m wide'
    # The height came back unchanged: it stays traced. Only the changed outline is an AI value.
    assert entry['source_labels'] == {'outline': 'ai_inferred', 'height': 'traced'}
    assert entry['revision_kept'] is False and len(entry['revision_receipts']) == 2
    assert (task / 'whole_vessel/wheelhouse.r0.step').read_text() == 'old'
    assert (task / 'whole_vessel/wheelhouse.step').read_text().startswith('ISO-10303-21')
    crops = list((task / 'whole_vessel/revisions').glob('wheelhouse-r1-*/pack/*.png'))
    assert len(crops) == 2
