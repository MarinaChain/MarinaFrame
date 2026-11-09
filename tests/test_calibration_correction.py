"""Person corrections use synthetic ink, no model calls or source drawings."""
import copy
import json

import pytest

from tests.test_sheet_calibration import FakeReading, synthetic_sheet
from vessel_reconstruction import body_plan_intake as bpi
from vessel_reconstruction import calibration_correction as cc


def original():
    return bpi.read_body_plan(synthetic_sheet(), FakeReading(), dpi=100.0)[0]


def test_swap_moves_station_groups_to_opposite_physical_halves():
    record = original()
    before = copy.deepcopy(record)
    fixed = cc.correct_reading(synthetic_sheet(), record, {'kind': 'swap_sides'})
    assert record == before
    assert fixed['engineering_approved'] is False
    assert fixed['usable_for_build']
    for old, new in zip(record['calibration']['sides'], fixed['calibration']['sides']):
        assert old['name'] == new['name']
        assert old['stations_outer_first'] == new['stations_outer_first']
        assert old['sign'] == -new['sign']
    assert fixed['stations'] != record['stations']
    # Reading again with the same corrected calibration gives exactly the same mapping.
    cal = bpi.calibration_from_record(fixed['calibration'])
    reread = cc.read_with_calibration(synthetic_sheet(), cal)
    assert fixed['stations'] == reread['stations']


def test_reverse_changes_only_the_named_halfs_station_mapping():
    record = original()
    fixed = cc.correct_reading(synthetic_sheet(), record, {'kind': 'reverse_order', 'half': 'fore'})
    old = {s['station']: s for s in record['stations']}
    new = {s['station']: s for s in fixed['stations']}
    for side in record['calibration']['sides']:
        numbers = side['stations_outer_first']
        mapped = list(reversed(numbers)) if side['name'] == 'fore' else numbers
        for a, b in zip(numbers, mapped):
            assert old[a]['curve_y_z_m'] == new[b]['curve_y_z_m']


def test_other_disables_reader_and_keeps_note_for_the_check():
    record = original()
    fixed = cc.correct_reading(None, record, {'kind': 'other', 'text': 'Wrong scale'})
    assert not fixed['usable_for_build']
    assert 'Wrong scale' in fixed['reason']
    anchors = [object()]
    assert bpi.reader_anchors([], anchors, fixed)[0] is anchors
    assert fixed['engineering_approved'] is False


def test_only_the_corrected_flag_is_closed():
    record = original()
    record['calibration']['flags'] = [{'field': 'sides', 'message': 'disagree'}, {'field': 'scale', 'message': 'disagree'}]
    fixed = cc.correct_reading(synthetic_sheet(), record, {'kind': 'swap_sides'})
    assert fixed['calibration']['flags'] == [{'field': 'scale', 'message': 'disagree'}]
    assert not fixed['usable_for_build']


@pytest.mark.parametrize('fix', [{}, {'kind': 'reverse_order', 'half': 'both'}, {'kind': 'other', 'text': ''}, {'kind': 'magic'}])
def test_invalid_choices_are_refused(fix):
    with pytest.raises(ValueError):
        cc.correct_reading(None, original(), fix)


class Tools:
    def __init__(self, root):
        self.root = root
        self.state = {'revision': 3, 'builds': [{'revision_id': 'r0003', 'path': 'old'}],
                      'last_valid_candidate': {'path': 'old'}, 'vessel_table': {'old': True},
                      'validation': {'old': True}}
        self.record = original()
        self.saved = []
    @property
    def revision_id(self):
        return f'r{self.state["revision"]:04d}'
    def body_plan_reading(self):
        return self.state.get('body_plan_reading_override', self.record)
    def _source(self):
        import numpy as np
        return np.where(synthetic_sheet(), 0, 255).astype('uint8'), None, None
    def _save(self):
        self.saved.append(copy.deepcopy(self.state))
    def _observation(self, ok, status, **extra):
        return dict(ok=ok, status=status, **extra)


def test_rebuild_records_revision_and_history_and_sets_old_builds_aside(tmp_path, monkeypatch):
    from vessel_reconstruction import first_hull_tools
    tools = Tools(tmp_path)
    def build(current):
        assert current.state['revision'] == 4
        assert current.state['builds'] == []
        assert current.state['body_plan_reading_override']['correction'] == {'kind': 'swap_sides'}
        current.state['builds'] = [{'revision_id': 'r0004', 'path': 'new'}]
        return {'ok': True, 'candidate': current.state['builds'][0]}
    monkeypatch.setattr(first_hull_tools, 'build_first_hull', build)
    result = cc.rebuild(tools, {'kind': 'swap_sides'})
    assert result['ok']
    assert tools.state['set_aside_builds'] == [{'revision_id': 'r0003', 'path': 'old'}]
    history = tools.state['calibration_history'][-1]
    assert history['message'] == 'calibration corrected by a person: bow/stern swapped'
    assert history['previous_revision_id'] == 'r0003' and history['revision_id'] == 'r0004'
    assert history['engineering_approved'] is False
    assert json.loads((tmp_path / history['previous_state']).read_text())['revision'] == 3


def test_failed_rebuild_restores_old_state_and_check_files(tmp_path, monkeypatch):
    from vessel_reconstruction import first_hull_tools
    tools = Tools(tmp_path)
    before = copy.deepcopy(tools.state)
    (tmp_path / bpi.CHECK_JSON).write_text('old check')
    def fail(current):
        (tmp_path / bpi.CHECK_JSON).write_text('new check')
        return {'ok': False}
    monkeypatch.setattr(first_hull_tools, 'build_first_hull', fail)
    assert not cc.rebuild(tools, {'kind': 'swap_sides'})['ok']
    assert tools.state == before
    assert (tmp_path / bpi.CHECK_JSON).read_text() == 'old check'
