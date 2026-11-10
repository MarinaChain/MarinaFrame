"""A sheet failure preserves the draft and has a focused recovery path."""
import copy
import json

from PIL import Image

from test_mirrored_half import _overlay_drawing
from vessel_reconstruction.agent_tools import DomainTools


def domain_at(tmp_path):
    source = tmp_path / 'source'
    source.mkdir()
    _overlay_drawing(source)
    task = tmp_path / 'task'
    task.mkdir()
    return DomainTools(task, source / 'spec.json')


def replace(tools, name='new.png'):
    inbox = tools.task_dir / 'sheet-inbox'
    inbox.mkdir(exist_ok=True)
    Image.new('RGB', (300, 240), 'white').save(inbox / name)
    return tools.execute('replace_sheet', {'sheet_id': 'source', 'file': f'sheet-inbox/{name}'})


def test_replacement_preserves_old_input_and_only_runs_dependent_stages(tmp_path, monkeypatch):
    tools = domain_at(tmp_path)
    old_input = tools.spec_path.read_bytes()
    old_source = copy.deepcopy(tools.state['sources']['source'])
    # Real replacement and scheduling; isolate costly native builds.
    calls = []
    def stage(tools, stage):
        calls.append(stage)
        return {'ok': True, 'status': 'draft'}
    import vessel_reconstruction.sheet_review as review
    monkeypatch.setattr(review, 'run_stage', stage)
    review_state = tools.state['sheet_review']
    review_state['outputs'].append({'id': 'unrelated', 'stage': 'read', 'sheet_ids': ['other'],
                                    'depends_on': [], 'status': 'draft'})
    tools._save()
    result = replace(tools)
    assert result['ok'], result
    assert calls == ['read', 'build', 'render', 'check']
    assert tools.state['sheet_review']['outputs'][-1]['status'] == 'draft'
    assert (tools.root / 'input/spec.json').read_bytes() == old_input
    assert (tools.root / 'input' / old_source['file']).is_file()
    assert tools.state['sources']['source']['sha256'] != old_source['sha256']
    history = tools.state['sheet_review']['history'][-1]
    assert history['previous_sha256'] == old_source['sha256']
    assert history['engineering_approved'] is False
    assert (tools.root / history['previous_state']).is_file()
    reopened = DomainTools(tools.task_dir, tools.root / 'input/spec.json')
    assert reopened.spec_path == tools.spec_path
    assert reopened.state['sheet_review']['sheets'][0]['status'] == 'replaced'


def test_bad_replacement_does_not_change_checkpoint(tmp_path):
    tools = domain_at(tmp_path)
    folder = tools.task_dir / 'sheet-inbox'
    folder.mkdir()
    (folder / 'broken.png').write_bytes(b'not an image')
    before = tools.state_path.read_bytes()
    result = tools.execute('replace_sheet', {'sheet_id': 'source', 'file': 'sheet-inbox/broken.png'})
    assert not result['ok']
    assert tools.state_path.read_bytes() == before


def test_failed_resume_keeps_build_and_opens_a_request(tmp_path, monkeypatch):
    tools = domain_at(tmp_path)
    tools.state['builds'] = [{'id': 'old-draft'}]
    tools.state['last_valid_candidate'] = {'id': 'old-draft'}
    tools._save()
    import vessel_reconstruction.sheet_review as review
    monkeypatch.setattr(review, 'run_stage', lambda tools, stage: {'ok': False, 'message': 'Lines are too faint.'})
    result = replace(tools)
    assert result['status'] == 'partial'
    assert tools.state['last_valid_candidate']['id'] == 'old-draft'
    assert tools.state['builds'][0]['id'] == 'old-draft'
    request = tools.state['sheet_review']['requests'][-1]
    assert request['status'] == 'open' and request['who']
    assert request['output_id'] == 'hull-read'
    assert request['sheet_id'] == 'source'


def test_operator_path_cannot_escape_run(tmp_path):
    tools = domain_at(tmp_path)
    before = tools.state_path.read_bytes()
    result = tools.execute('replace_sheet', {'sheet_id': 'source', 'file': '../source/drawing.png'})
    assert not result['ok']
    assert tools.state_path.read_bytes() == before


def test_higher_resolution_updates_pixel_calibration_explicitly(tmp_path, monkeypatch):
    tools = domain_at(tmp_path)
    original_ppm = tools.spec['sections'][0]['calibration']['pixels_per_metre']
    inbox = tools.task_dir / 'sheet-inbox'
    inbox.mkdir()
    Image.new('RGB', (600, 480), 'white').save(inbox / 'clear.png')
    import vessel_reconstruction.sheet_review as review
    monkeypatch.setattr(review, 'run_stage', lambda tools, stage: {'ok': True})
    result = tools.execute('replace_sheet', {'sheet_id': 'source', 'file': 'sheet-inbox/clear.png'})
    assert result['ok'], result
    assert tools.spec['sections'][0]['calibration']['pixels_per_metre'] == original_ppm * 2
    assert tools.state['sheet_review']['history'][-1]['pixel_scale_factor'] == 2


def test_transitive_output_dependency_does_not_require_duplicate_sheet_ids():
    from vessel_reconstruction.sheet_review import affected_outputs
    review = {'outputs': [
        {'id': 'read', 'stage': 'read', 'sheet_ids': ['a'], 'depends_on': []},
        {'id': 'hull', 'stage': 'build', 'sheet_ids': [], 'depends_on': ['read']},
        {'id': 'image', 'stage': 'render', 'sheet_ids': [], 'depends_on': ['hull']},
        {'id': 'other', 'stage': 'build', 'sheet_ids': ['b'], 'depends_on': []},
    ]}
    assert [o['id'] for o in affected_outputs(review, 'a')] == ['read', 'hull', 'image']


def test_extra_sheet_replacement_does_not_rebuild_hull(tmp_path, monkeypatch):
    tools = domain_at(tmp_path)
    review = tools.state['sheet_review']
    review['sheets'].append({'id': 'p2', 'label': 'GA', 'status': 'unreadable', 'reason': 'Too faint',
                             'file': None, 'sha256': None, 'version': 1})
    review['outputs'].append({'id': 'sheet-p2', 'stage': 'sheet_read', 'sheet_ids': ['p2'],
                              'depends_on': [], 'status': 'failed'})
    tools._save()
    before = copy.deepcopy(tools.state['sources'])
    import vessel_reconstruction.sheet_review as recovery
    calls = []
    monkeypatch.setattr(recovery, 'run_stage', lambda tools, stage: calls.append(stage) or {'ok': True})
    inbox = tools.task_dir / 'sheet-inbox'
    inbox.mkdir()
    Image.new('RGB', (120, 70), 'white').save(inbox / 'ga.png')
    result = tools.execute('replace_sheet', {'sheet_id': 'p2', 'file': 'sheet-inbox/ga.png'})
    assert result['ok'] and result['status'] == 'draft'
    assert calls == ['sheet_read']
    assert tools.state['sources'] == before
    assert review['sheets'][0]['sha256'] == before['source']['sha256']


def test_intake_failure_is_a_sheet_request_while_good_pages_continue(tmp_path):
    from vessel_reconstruction.intake import prepare, write_spec
    source = tmp_path / 'source'
    source.mkdir()
    Image.new('RGB', (300, 240), 'white').save(source / 'good.png')
    (source / 'bad.png').write_bytes(b'bad scan')
    inputs = tmp_path / 'inputs'
    preview = prepare([source / 'good.png', source / 'bad.png'], inputs)
    write_spec(preview, inputs)
    (inputs / 'sheet_review_preview.json').write_text(json.dumps(preview))
    task = tmp_path / 'task'
    task.mkdir()
    tools = DomainTools(task, inputs / 'spec.json')
    sheets = tools.state['sheet_review']['sheets']
    assert len(sheets) == 2
    bad = next(s for s in sheets if s['status'] == 'unreadable')
    assert bad['label'] == 'bad.png'
    assert tools.state['sheet_review']['requests'][0]['sheet_id'] == bad['id']


def test_real_replacement_reads_builds_and_keeps_a_draft(tmp_path):
    from test_agent_tools import drawing
    from vessel_reconstruction.run_record import verify_run
    path, _ = drawing(tmp_path / 'input', grid=False)
    tools = DomainTools(tmp_path / 'task', path)
    inbox = tools.task_dir / 'sheet-inbox'
    inbox.mkdir()
    (inbox / 'new.png').write_bytes((path.parent / 'drawing.png').read_bytes())
    result = tools.execute('replace_sheet', {'sheet_id': 'source', 'file': 'sheet-inbox/new.png'})
    assert result['ok'], result
    history = tools.state['sheet_review']['history'][-1]
    assert history['stages'][:2] == ['read', 'build']
    candidate = tools.state['last_valid_candidate']
    assert candidate and candidate['valid'], result
    assert verify_run(tools.task_dir / candidate['path'])['valid']
    assert history['revision_id'] == tools.revision_id
    assert not result['engineering_approved']


def test_unknown_downstream_stage_is_retained_for_explicit_resume(tmp_path, monkeypatch):
    tools = domain_at(tmp_path)
    review = tools.state['sheet_review']
    review['outputs'].append({'id': 'tables', 'stage': 'tables', 'sheet_ids': [],
                              'depends_on': ['hull-build'], 'status': 'draft'})
    tools._save()
    import vessel_reconstruction.sheet_review as recovery
    monkeypatch.setattr(recovery, 'run_stage', lambda tools, stage: {'ok': stage != 'tables'})
    result = replace(tools)
    assert result['status'] == 'partial'
    output = next(o for o in tools.state['sheet_review']['outputs'] if o['id'] == 'tables')
    assert output['status'] == 'failed'
    assert tools.state['sheet_review']['requests'][-1]['output_id'] == 'tables'


def test_readable_replacement_is_accepted_when_old_sheet_cannot_be_decoded(tmp_path, monkeypatch):
    source = tmp_path / 'source'
    source.mkdir()
    _overlay_drawing(source)
    (source / 'drawing.png').write_bytes(b'\x89PNG\r\n\x1a\n' + b'unreadable old source')
    tools = DomainTools(tmp_path / 'task', source / 'spec.json')
    import vessel_reconstruction.sheet_review as recovery
    calls = []
    monkeypatch.setattr(recovery, 'run_stage', lambda tools, stage: calls.append(stage) or {'ok': True})
    result = replace(tools)
    assert result['ok'], result
    assert calls[:2] == ['read', 'build']
    assert 'Check scale' in tools.state['sheet_review']['sheets'][0]['reason']
    assert tools.state['sheet_review']['history'][-1]['scale_note']
