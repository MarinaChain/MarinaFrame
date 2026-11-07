"""Synthetic-only tests for the measured ship language."""
from copy import deepcopy
import importlib
from pathlib import Path

import pytest


def api():
    spec = importlib.util.find_spec('vessel_reconstruction.ship_cad')
    assert spec is not None, 'The restricted measured ship language is not implemented'
    return importlib.import_module('vessel_reconstruction.ship_cad')


def program():
    return {'schema': 'ship-cad/v1', 'components': [
        {'id': 'house', 'op': 'deckhouse', 'source': {'view': 'plan', 'region': 'house',
         'method': 'closed_outline'}, 'args': {'outline': 'house_outline', 'height': 'house_height'}}]}


def test_program_accepts_only_measurement_references():
    assert api().validate_program(program()) == program()


@pytest.mark.parametrize('change', ['code', 'literal', 'path', 'approval', 'unknown_op', 'duplicate'])
def test_rejects_language_escape(change):
    p = program()
    c = p['components'][0]
    if change == 'code':
        c['code'] = '__import__("os").system("true")'
    elif change == 'literal':
        c['args']['height'] = 2.5
    elif change == 'path':
        c['args']['outline'] = '/etc/passwd'
    elif change == 'approval':
        p['engineering_approved'] = True
    elif change == 'unknown_op':
        c['op'] = 'exec'
    else:
        p['components'].append(deepcopy(c))
    with pytest.raises(ValueError):
        api().validate_program(p)


def test_duplicate_json_keys_rejected():
    with pytest.raises(ValueError, match='duplicate'):
        api().parse_program('{"schema":"ship-cad/v1","schema":"ship-cad/v1","components":[]}')


def test_missing_measurement_is_unbuilt_guess():
    result = api().resolve_program(program(), {})
    assert result[0]['status'] == 'draft_guess'
    assert result[0]['geometry'] is None
    assert 'house_outline' in result[0]['reason']


def test_provider_sorted_arguments_do_not_change_primary_source():
    p = program()
    p['components'][0]['args'] = {'height':'house_height','outline':'house_outline'}
    measurements = {
        'house_outline': {'status':'measured','kind':'outline','value':[[0,0],[1,0],[0,1]],
                          'view':'plan','region':'house','method':'closed_outline','source_sha256':'a'*64,'entity_ids':['a']},
        'house_height': {'status':'measured','kind':'interval','value':[1,2],
                         'view':'profile','region':'height','method':'parallel_lines','source_sha256':'b'*64,'entity_ids':['b']}}
    assert api().resolve_program(p,measurements)[0]['status'] == 'measured_draft'


def test_profile_outline_cannot_be_used_as_plan_deckhouse():
    p = program()
    p['components'][0]['source']['view'] = 'profile'
    m = {'house_outline':{'status':'measured','kind':'outline','value':[[0,0],[1,0],[0,1]],
          'view':'profile','region':'house','method':'closed_outline','source_sha256':'a'*64,'entity_ids':['a']},
         'house_height':{'status':'measured','kind':'interval','value':[0,2],
          'view':'profile','region':'height','method':'parallel_lines','source_sha256':'b'*64,'entity_ids':['b']}}
    assert api().resolve_program(p,m)[0]['geometry'] is None


def test_failed_or_wrong_source_measurement_is_not_geometry():
    records = {'house_outline': {'status': 'failed', 'reason': 'ambiguous outline'}}
    assert api().resolve_program(program(), records)[0]['geometry'] is None


def measurement_api():
    spec = importlib.util.find_spec('vessel_reconstruction.ship_measure')
    assert spec is not None, 'Deterministic ship measurements are not implemented'
    return importlib.import_module('vessel_reconstruction.ship_measure')


def test_closed_outline_is_measured_not_region_box():
    m = measurement_api()
    entities = [{'id': 'A', 'points': [[1, 1], [5, 1], [4, 3], [1, 1]], 'closed': True}]
    record = m.measure_outline(entities, [0, 0, 6, 4], scale=0.1, origin=[0, 0],
                               view='plan', region='house', source_sha256='a' * 64)
    assert record['status'] == 'measured'
    assert record['value'] == [[0.1, 0.1], [0.5, 0.1], [0.4, 0.30000000000000004]]
    assert record['entity_ids'] == ['A']


def test_join_open_outline_without_inventing_closure():
    m = measurement_api()
    entities = [{'id': str(i), 'points': [a,b], 'closed': False} for i,(a,b) in enumerate([
        ([0,0],[2,0]),([2,0],[2,1]),([2,1],[0,1]),([0,1],[0,0])])]
    kwargs = dict(scale=1, origin=[0,0], view='plan', region='house', source_sha256='a'*64)
    assert m.measure_outline(entities, [-1,-1,3,2], **kwargs)['status'] == 'measured'
    assert m.measure_outline(entities[:-1], [-1,-1,3,2], **kwargs)['status'] == 'failed'
    entities.append({'id':'branch','points':[[2,0],[3,0]],'closed':False})
    assert m.measure_outline(entities, [-1,-1,4,2], **kwargs)['status'] == 'failed'


def test_ambiguous_outline_abstains():
    m = measurement_api()
    e = {'id': 'A', 'points': [[1, 1], [5, 1], [4, 3], [1, 1]], 'closed': True}
    assert m.measure_outline([e, {**e, 'id': 'B'}], [0, 0, 6, 4], scale=1, origin=[0, 0],
                             view='plan', region='house', source_sha256='a' * 64)['status'] == 'failed'


def test_cross_view_missing_is_not_a_pass():
    report = api().check_views({}, {})
    assert report['status'] == 'blocked'
    assert set(report['missing']) == {'profile', 'plan', 'body'}


def test_cross_view_detects_offset_and_veto():
    a = api()
    cuts = {v: [[0, 0], [1, 0], [1, 1]] for v in ('profile', 'plan', 'body')}
    drawings = deepcopy(cuts)
    drawings['profile'] = [[0, 2], [1, 2], [1, 3]]
    assert a.check_views(cuts, drawings)['status'] == 'blocked'
    assert a.check_views(cuts, cuts, veto=True)['status'] == 'blocked'
    assert a.check_views(cuts, cuts)['status'] == 'checked_draft'


@pytest.mark.cad
def test_real_cad_deckhouse_export(tmp_path):
    a = api()
    measurements = {
        'house_outline': {'status': 'measured', 'kind': 'outline', 'value': [[0, 0], [2, 0], [2, 1], [0, 1]],
                          'view': 'plan', 'region': 'house', 'method': 'closed_outline', 'source_sha256': 'a'*64,
                          'entity_ids': ['A']},
        'house_height': {'status': 'measured', 'kind': 'interval', 'value': [1, 3],
                         'view': 'profile', 'region': 'height', 'method': 'parallel_lines',
                         'source_sha256': 'b'*64, 'entity_ids': ['B', 'C']}}
    report = a.execute(program(), measurements, tmp_path)
    assert report['engineering_approved'] is False
    assert report['components'][0]['volume_m3'] == pytest.approx(4)
    assert (tmp_path/'model-draft.step').is_file()
    assert report['cross_view']['status'] == 'blocked'


@pytest.mark.cad
def test_sandbox_executes_real_cad(tmp_path):
    import sys
    if sys.platform != 'darwin':
        pytest.skip('Seatbelt requires macOS')
    from vessel_reconstruction.ship_cad_worker import run
    from vessel_reconstruction.ship_measure import measure_outline, measure_interval
    outline = measure_outline([{'id': 'a', 'closed': True, 'points': [[0,0],[2,0],[2,1],[0,1],[0,0]]}],
        [-1,-1,3,2], scale=1, origin=[0,0], view='plan', region='house', source_sha256='a'*64)
    height = measure_interval([{'id': 'b', 'points': [[0,1],[2,1]]}, {'id':'c','points':[[0,3],[2,3]]}],
        [-1,0,3,4], scale=1, origin=[0,0], view='profile', region='height', source_sha256='b'*64)
    result = run(program(), {'house_outline':outline, 'house_height':height}, tmp_path/'task')
    assert result['exit_code'] == 0
    assert result['result']['components'][0]['built']
    assert result['result']['components'][0]['volume_m3'] == pytest.approx(4)


def test_interval_measures_two_levels_and_abstains_on_three():
    m = measurement_api()
    entities = [{'id':'a','points':[[0,1],[2,1]]},{'id':'b','points':[[0,3],[2,3]]}]
    kwargs = dict(scale=0.1, origin=[0,0], view='profile', region='height', source_sha256='a'*64)
    assert m.measure_interval(entities, [-1,0,3,4], **kwargs)['value'] == pytest.approx([0.1,0.3])
    entities.append({'id':'c','points':[[0,2],[2,2]]})
    assert m.measure_interval(entities, [-1,0,3,4], **kwargs)['status'] == 'failed'


@pytest.mark.cad
def test_os_sandbox_blocks_file_and_network(tmp_path):
    import subprocess
    import sys
    if sys.platform != 'darwin':
        pytest.skip('Seatbelt integration requires macOS')
    from vessel_reconstruction.ship_cad_worker import sandbox_profile, runtime_paths
    task = tmp_path/'task'
    task.mkdir()
    outside = tmp_path/'secret.txt'
    outside.write_text('synthetic sentinel')
    profile = task/'profile.sb'
    profile.write_text(sandbox_profile(task, runtime_paths()))
    script = ('import pathlib,socket; '
              f'pathlib.Path({str(outside)!r}).read_text()')
    read = subprocess.run(['/usr/bin/sandbox-exec', '-f', str(profile), sys.executable, '-I', '-c', script],
                          capture_output=True, text=True)
    assert read.returncode != 0 and 'PermissionError' in read.stderr
    net = subprocess.run(['/usr/bin/sandbox-exec', '-f', str(profile), sys.executable, '-I', '-c',
                          'import socket; socket.socket().bind(("127.0.0.1", 0))'], capture_output=True, text=True)
    assert net.returncode != 0 and 'PermissionError' in net.stderr


@pytest.mark.cad
def test_execute_reimports_step_for_bound_view_audit(tmp_path):
    a = api()
    import inspect
    assert 'audit' in inspect.signature(a.execute).parameters, 'Host-bound STEP audit is missing'
    p = program()
    m = {'house_outline':{'status':'measured','kind':'outline','value':[[0,0],[2,0],[2,1],[0,1]],
         'view':'plan','region':'house','method':'closed_outline','source_sha256':'a'*64,'entity_ids':['a']},
         'house_height':{'status':'measured','kind':'interval','value':[0,2],
         'view':'profile','region':'height','method':'parallel_lines','source_sha256':'b'*64,'entity_ids':['b']}}
    report = a.execute(p,m,tmp_path,audit={'planes':{'profile':0.5,'plan':1,'body':1},'drawings':{}})
    assert report['cross_view']['step_sha256']
    assert set(report['cross_view']['cut_points']) == {'profile','plan','body'}
    assert report['cross_view']['status'] == 'blocked'


@pytest.mark.cad
def test_appendage_asymmetric_span_keeps_measured_side():
    shape = api()._prism([[0,0],[2,0],[2,1],[0,1]],[1,3],'XZ')
    assert shape.BoundingBox().ymin == pytest.approx(1)
    assert shape.BoundingBox().ymax == pytest.approx(3)


@pytest.mark.cad
def test_opening_cannot_erase_its_target(tmp_path):
    a = api()
    p = program()
    p['components'].append({'id':'window','op':'opening','source':{'view':'plan','region':'house',
        'method':'closed_outline'},'args':{'outline':'house_outline','height':'house_height','target':'house'}})
    m = {'house_outline':{'status':'measured','kind':'outline','value':[[0,0],[2,0],[2,1],[0,1]],
          'view':'plan','region':'house','method':'closed_outline','source_sha256':'a'*64,'entity_ids':['a']},
         'house_height':{'status':'measured','kind':'interval','value':[0,2],
          'view':'profile','region':'h','method':'parallel_lines','source_sha256':'b'*64,'entity_ids':['b']}}
    report = a.execute(p,m,tmp_path)
    assert report['components'][0]['built']
    assert not report['components'][1]['built']
    assert 'empty' in report['components'][1]['reason']


@pytest.mark.cad
def test_exported_step_cuts_are_compared_to_all_views(tmp_path):
    import cadquery as cq
    a = api()
    shape = cq.Workplane('XY').box(2000, 1000, 1000).val()
    path = tmp_path/'source.step'
    cq.exporters.export(shape, str(path))
    assert hasattr(a, 'step_cuts'), 'Independent STEP cross-view cutting is missing'
    cuts = a.step_cuts(path, {'profile':0, 'plan':0, 'body':0})
    assert set(cuts) == {'profile','plan','body'}
    assert all(len(p) > 4 for p in cuts.values())
    assert max(abs(v) for p in cuts.values() for q in p for v in q) <= 1.00001
    assert a.check_views(cuts,cuts)['status'] == 'checked_draft'


def test_sandbox_profile_denies_network_and_external_files(tmp_path):
    spec = importlib.util.find_spec('vessel_reconstruction.ship_cad_worker')
    assert spec is not None, 'The ship CAD sandbox is not implemented'
    worker = importlib.import_module('vessel_reconstruction.ship_cad_worker')
    profile = worker.sandbox_profile(tmp_path, [Path('/trusted/runtime')])
    assert '(deny default)' in profile
    assert '(allow network' not in profile
    assert '(subpath "/")' not in profile
    assert str(tmp_path) in profile


@pytest.mark.cad
def test_sandbox_worker_cannot_write_host_files_or_exec_other_programs(tmp_path):
    import subprocess
    import sys
    if sys.platform != 'darwin':
        pytest.skip('Seatbelt integration requires macOS')
    from vessel_reconstruction.ship_cad_worker import sandbox_profile, runtime_paths
    task = tmp_path/'task'
    (task/'work').mkdir(parents=True)
    profile = task/'profile.sb'
    profile.write_text(sandbox_profile(task, runtime_paths()))
    def probe(script):
        return subprocess.run(['/usr/bin/sandbox-exec', '-f', str(profile), sys.executable, '-I', '-c', script],
                              capture_output=True, text=True)
    allowed = probe(f'import pathlib; pathlib.Path({str(task/"work"/"ok.txt")!r}).write_text("x")')
    assert allowed.returncode == 0, allowed.stderr
    receipt = probe(f'import pathlib; pathlib.Path({str(task/"worker-receipt.json")!r}).write_text("x")')
    assert receipt.returncode != 0 and 'PermissionError' in receipt.stderr
    other = probe('import subprocess; subprocess.run(["/bin/echo", "x"])')
    assert other.returncode != 0 and 'PermissionError' in other.stderr


def test_worker_result_reader_refuses_symlinks(tmp_path):
    from vessel_reconstruction.ship_cad_worker import read_worker_json
    work = tmp_path/'work'
    (work/'output').mkdir(parents=True)
    outside = tmp_path/'outside.json'
    outside.write_text('{"forged": true}')
    (work/'output'/'provenance.json').symlink_to(outside)
    with pytest.raises(OSError):
        read_worker_json(work, Path('output/provenance.json'))
    (work/'output'/'provenance.json').unlink()
    (work/'output').rmdir()
    (work/'output').symlink_to(tmp_path)
    with pytest.raises(OSError):
        read_worker_json(work, Path('output/provenance.json'))
    (work/'output').unlink()
    assert read_worker_json(work, Path('output/provenance.json')) is None
    (work/'output').mkdir()
    (work/'output'/'provenance.json').write_text('{"ok": true}')
    assert read_worker_json(work, Path('output/provenance.json')) == {'ok': True}


def test_worker_result_reader_refuses_a_fifo_without_blocking(tmp_path):
    import os
    from vessel_reconstruction.ship_cad_worker import read_worker_json
    work = tmp_path/'work'
    (work/'output').mkdir(parents=True)
    os.mkfifo(work/'output'/'provenance.json')
    with pytest.raises(ValueError, match='not a regular file'):
        read_worker_json(work, Path('output/provenance.json'))
