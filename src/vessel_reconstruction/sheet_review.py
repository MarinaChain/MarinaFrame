"""Sheet recovery state. No sheet typing or classification belongs here."""
from __future__ import annotations

import copy
import time
from pathlib import Path
from uuid import uuid4

from .provenance import digest_file, safe_relative_file, write_json
from .schema import load_bounded_json, validate_spec

HULL_STAGES = ('read', 'build', 'render', 'check')
STAGES = ('sheet_read', *HULL_STAGES)
OPERATIONS = {'inspect_source': 'read', 'build_draft': 'build', 'build_provisional': 'build',
              'build_first_hull': 'build', 'render_candidate': 'render', 'validate_candidate': 'check'}


def initial_state(sources: dict) -> dict:
    sheets = [{'id': role, 'label': role.replace('_', ' ').capitalize(), 'status': 'ok',
               'reason': '', 'file': value['file'], 'sha256': value['sha256'], 'version': 1}
              for role, value in sources.items()]
    ids = [sheet['id'] for sheet in sheets]
    outputs = [{'id': f'hull-{stage}', 'stage': stage, 'sheet_ids': ids,
                'depends_on': [f'hull-{HULL_STAGES[index - 1]}'] if index else [],
                'status': 'stale'} for index, stage in enumerate(HULL_STAGES)] if ids else []
    return {'sheets': sheets, 'outputs': outputs, 'requests': [], 'history': []}


def capture_intake(review: dict, record: dict, input_folder: Path, spec_folder: Path):
    """Keep page identity and read failures supplied by intake; do not infer type."""
    from .pipeline import _copy_source

    for page in record.get('pages', []):
        if page.get('page_id') == record.get('spec_page_id'):
            primary = next((s for s in review['sheets'] if s['id'] == 'source'), None)
            if primary:
                primary['label'] = page.get('file_name') or 'Source'
            continue
        sheet_id = page['page_id']
        path = safe_relative_file(spec_folder, page['source_file'])
        name, sha = _copy_source(path, input_folder, f'sheet-{sheet_id}')
        review['sheets'].append({'id': sheet_id, 'label': page.get('file_name') or sheet_id,
            'status': 'ok', 'reason': '', 'file': name, 'sha256': sha, 'version': 1,
            'page_index': page.get('page_index', 0)})
        review['outputs'].append({'id': f'sheet-{sheet_id}', 'stage': 'sheet_read',
            'sheet_ids': [sheet_id], 'depends_on': [], 'status': 'draft'})
    preview = spec_folder / 'sheet_review_preview.json'
    warnings = load_bounded_json(preview).get('warnings', []) if preview.is_file() else []
    for index, warning in enumerate(warnings):
        if warning.get('code') != 'unreadable_file':
            continue
        sheet_id = f'unreadable-{index}'
        sheet = {'id': sheet_id, 'label': Path(warning.get('file') or 'Sheet').name,
            'status': 'unreadable', 'reason': 'The file could not be read.',
            'file': None, 'sha256': None, 'version': 0}
        output = {'id': f'sheet-{sheet_id}', 'stage': 'sheet_read', 'sheet_ids': [sheet_id],
                  'depends_on': [], 'status': 'failed'}
        review['sheets'].append(sheet)
        review['outputs'].append(output)
        request_for(review, sheet, output, sheet['reason'])


def affected_outputs(review: dict, sheet_id: str) -> list[dict]:
    """Return the source and transitive output dependents in execution order."""
    affected = {item['id'] for item in review['outputs'] if sheet_id in item['sheet_ids']}
    while True:
        following = {item['id'] for item in review['outputs'] if affected.intersection(item['depends_on'])}
        if following <= affected:
            break
        affected |= following
    pending = {item['id']: item for item in review['outputs'] if item['id'] in affected}
    ordered = []
    while pending:
        ready = [item for item in pending.values() if not set(item['depends_on']).intersection(pending)]
        if not ready:
            raise ValueError('Output dependencies contain a cycle.')
        ready.sort(key=lambda item: STAGES.index(item['stage']) if item['stage'] in STAGES else len(STAGES))
        for item in ready:
            ordered.append(item)
            del pending[item['id']]
    return ordered


def request_for(review: dict, sheet: dict, output: dict, reason: str):
    if any(r['status'] == 'open' and r['sheet_id'] == sheet['id']
           and r['output_id'] == output['id'] for r in review['requests']):
        return
    review['requests'].append({'id': uuid4().hex, 'sheet_id': sheet['id'],
        'output_id': output['id'], 'who': 'Drawing sender', 'status': 'open',
        'text': f"Send a clearer {sheet['label'].lower()}.", 'reason': reason})


def record_operation(tools, operation: str, result: dict):
    stage = OPERATIONS.get(operation)
    if stage is None:
        return
    review = tools.state.setdefault('sheet_review', initial_state(tools.state['sources']))
    for output in review['outputs']:
        if output['stage'] != stage:
            continue
        output['status'] = 'draft' if result.get('ok') else 'failed'
        output['revision_id'] = tools.revision_id
        if not result.get('ok'):
            reason = str(result.get('message') or 'This stage needs a clearer sheet.')[:180]
            for sheet in review['sheets']:
                if sheet['id'] in output['sheet_ids']:
                    if stage == 'read':
                        sheet.update(status='unreadable', reason=reason)
                    request_for(review, sheet, output, reason)
    tools._save()


def run_stage(tools, stage: str) -> dict:
    """Use the normal domain operations, without recursively taking its lock."""
    if stage == 'sheet_read':
        # The replacement was decoded before publication. No hull stage names
        # this sheet, so no hull read or build is needed.
        return {'ok': True, 'status': 'draft'}
    if stage == 'read':
        if tools.state.get('sheet_only'):
            # The old pixel reading must not be reused for a new drawing. A person
            # can supply setup again if the automatic reader cannot recover it.
            from .intake import _body_plan_reading
            source = safe_relative_file(tools.root / 'input', tools.state['sources']['source']['file'])
            reading = _body_plan_reading(source, tools.root)
            tools.state['body_plan_reading_override'] = reading or {
                'usable_for_build': False, 'reason': 'Read the new sheet setup.', 'engineering_approved': False}
            tools._save()
            if not tools.spec.get('sections'):
                tools._materialize_sections()
        ids = [s['id'] for s in tools.spec.get('sections', [])]
        for index in range(0, len(ids), 12):
            result = tools._inspect_source(ids[index:index + 12])
            if not result.get('ok'):
                return result
        return {'ok': bool(ids), 'message': 'Read the new sheet setup before building.'}
    if stage == 'build':
        return tools._build_first_hull() if tools.state.get('sheet_only') else tools._build_draft()
    if stage == 'render':
        return tools._render_candidate('oblique')
    if stage != 'check':
        return {'ok': False, 'message': 'This output needs its own stage run.'}
    if tools.open_guesses:
        return {'ok': True, 'status': 'draft', 'check_state': 'not_run',
                'message': 'Confirm draft guesses before checks.'}
    return tools._validate_candidate()


def replace_sheet(tools, sheet_id: str, file: str) -> dict:
    """Install an immutable source version, then retry only its output closure.

    The controller holds its task lock; DomainTools holds its domain lock. The
    file is a controller-staged task path and is never exposed as a model tool.
    """
    review = copy.deepcopy(tools.state.get('sheet_review') or initial_state(tools.state['sources']))
    sheet = next((s for s in review['sheets'] if s['id'] == sheet_id), None)
    if sheet is None:
        raise ValueError('This run has no such sheet.')
    affected = affected_outputs(review, sheet_id)
    previous_sha256 = sheet.get('sha256')
    source = safe_relative_file(tools.task_dir, file)
    if not file.startswith('sheet-inbox/') or source.stat().st_size > 256 * 1024 * 1024:
        raise ValueError('Choose a drawing file in the replacement inbox.')
    from .ingest import _read_image
    settings = {'file': source.name}
    if source.suffix.lower() == '.pdf':
        settings.update(page_index=0, render_dpi=tools.captured_spec.get(sheet_id, {}).get('render_dpi', 144))
    selected, _ = _read_image(settings, source.parent)
    height, width = selected.shape[:2]
    pixel_scale_factor = 1.0
    scale_note = ''
    if sheet_id == 'source' and tools.spec.get('sections'):
        try:
            previous, _, _ = tools._source()
        except (ValueError, OSError):
            # An unreadable old source is the reason for replacement. It must
            # not prevent a readable source from entering the draft path.
            scale_note = 'Old sheet unreadable; calibration kept. Check scale.'
        else:
            old_height, old_width = previous.shape[:2]
            pixel_scale_factor = width / old_width
            # Allow one pixel of rounding for a resized scan. A crop or a
            # nonuniform stretch needs new calibration, not an invented scale.
            if abs(pixel_scale_factor - height / old_height) > 1 / max(old_height, old_width):
                raise ValueError('The page shape changed. Correct the scale before replacing it.')

    previous_state = copy.deepcopy(tools.state)
    previous_revision = tools.revision_id
    token = uuid4().hex
    folder = tools.root / 'sheet-revisions' / token
    folder.mkdir(parents=True)
    write_json(folder / 'previous-state.json', previous_state)
    sha = digest_file(source)
    name = f'replacement-{token}{source.suffix.lower()}'
    destination = tools.root / 'input' / name
    # Copy first, hash and decode those exact bytes before publishing a pointer.
    destination.write_bytes(source.read_bytes())
    if digest_file(destination) != sha:
        raise ValueError('The replacement changed while it was copied. Choose it again.')
    spec = copy.deepcopy(tools.captured_spec)
    if pixel_scale_factor != 1:
        for section in spec.get('sections', []):
            section['roi_px'] = [round(value * pixel_scale_factor) for value in section['roi_px']]
            for key in ('centerline_px', 'baseline_px', 'pixels_per_metre'):
                section['calibration'][key] *= pixel_scale_factor
    if sheet_id in tools.state['sources']:
        source_settings = spec[sheet_id]
        source_settings.update(file=name, sha256=sha)
        if source.suffix.lower() != '.pdf':
            source_settings.pop('page_index', None)
            source_settings.pop('render_dpi', None)
        else:
            source_settings.update(page_index=0, render_dpi=settings['render_dpi'])
        spec_name = f'spec-{token}.json'
        write_json(tools.root / 'input' / spec_name, spec)
        tools.state['active_spec_file'] = spec_name
        tools.state['input_spec_sha256'] = digest_file(tools.root / 'input' / spec_name)
        tools.state['sources'][sheet_id] = {'file': name, 'sha256': sha}
    sheet.update(status='replaced', reason=scale_note, file=name, sha256=sha, version=sheet['version'] + 1, page_index=0)
    for request in review['requests']:
        if request['sheet_id'] == sheet_id and request['status'] == 'open':
            request['status'] = 'answered'
    for output in affected:
        output['status'] = 'stale'
    entry = {'sheet_id': sheet_id, 'label': sheet['label'], 'previous_revision_id': previous_revision,
             'previous_sha256': previous_sha256,
             'sha256': sha, 'previous_state': (folder / 'previous-state.json').relative_to(tools.root).as_posix(),
             'stages': [], 'status': 'partial', 'engineering_approved': False}
    entry['pixel_scale_factor'] = pixel_scale_factor
    entry['scale_note'] = scale_note
    entry['time_ms'] = int(time.time() * 1000)
    review['history'].append(entry)
    tools.state['revision'] += 1
    tools.state['sheet_review'] = review
    if affected:
        tools.state.update(validation=None, rendered_views=[])
        if any(o['stage'] == 'read' for o in affected):
            tools.state.update(catalog={}, selected={}, guesses=[], authored_sections={}, model_choices={},
                               inspection_artifacts=[], vessel_table=None, fit_score={}, draft_fit=None)
            for key in ('first_hull_spec', 'kept_reading', 'readings', 'reading_number'):
                tools.state.pop(key, None)
            # Materialized calibration belongs to the previous source. Preserve its
            # bytes in the revision snapshot and require a new reading for sheet-only.
            materialized = tools.root / 'input' / 'materialized_spec.json'
            if tools.state.pop('materialized_spec_sha256', None) and materialized.exists():
                (folder / 'materialized_spec.json').write_bytes(materialized.read_bytes())
            if tools.state.get('sheet_only') and sheet_id == 'source':
                tools.state.update(sheet_setups={}, described_views=[], vessel_description={},
                                   body_plan_reading_override={}, replacement_source=True)
    tools.state['input_errors'] = validate_spec(spec, tools.root / 'input', allow_sheet_only=True)
    tools._save()
    tools._verify_inputs()
    for stage in dict.fromkeys(o['stage'] for o in affected):
        if tools.cancel_event is not None and tools.cancel_event.is_set():
            break
        entry['stages'].append(stage)
        try:
            result = run_stage(tools, stage)
        except Exception:
            result = {'ok': False, 'message': 'The sheet stage stopped. Replace it to retry.'}
        # A stage may replace the in-memory state during a failed draft edit.
        review = tools.state['sheet_review']
        entry = review['history'][-1]
        for output in affected_outputs(review, sheet_id):
            if output['stage'] == stage:
                output.update(status='draft' if result.get('ok') else 'failed', revision_id=tools.revision_id)
                output['detail'] = str(result.get('message') or '')[:180]
                if result.get('check_state'):
                    output['check_state'] = result['check_state']
                if not result.get('ok'):
                    reason = str(result.get('message') or 'The sheet needs a clearer reading.')[:180]
                    sheet = next(s for s in review['sheets'] if s['id'] == sheet_id)
                    sheet.update(status='unreadable' if stage == 'read' else 'replaced', reason=reason)
                    request_for(review, sheet, output, reason)
        tools._save()
        if not result.get('ok'):
            break
    else:
        entry['status'] = 'draft'
    entry['revision_id'] = tools.revision_id
    tools._save()
    return tools._observation(True, entry['status'], sheet_replacement=entry,
                              message='Sheet replaced. Review the draft.' if entry['status'] == 'draft'
                              else 'Sheet replaced. Some outputs still need a reading.')
