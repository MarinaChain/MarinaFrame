"""Explicit person corrections; the frozen body-plan reader is unchanged."""
from __future__ import annotations

import copy
import uuid

import numpy as np

from . import body_plan_intake as bpi
from .provenance import write_json

read_with_calibration = bpi.read_with_calibration


def check_choice(correction: dict) -> str:
    if not isinstance(correction, dict):
        raise ValueError('A calibration correction must be an object.')
    kind = correction.get('kind')
    fields = {'swap_sides': {'kind'}, 'reverse_order': {'kind', 'half'}, 'other': {'kind', 'text'}}
    if kind not in fields or set(correction) != fields[kind]:
        raise ValueError('Unknown calibration correction.')
    if kind == 'reverse_order' and correction['half'] not in ('fore', 'aft'):
        raise ValueError('Choose the bow or stern half.')
    if kind == 'other' and (not isinstance(correction['text'], str)
                            or not 1 <= len(correction['text'].strip()) <= 400):
        raise ValueError('Describe the problem in 1 to 400 characters.')
    return kind


def correction_message(correction: dict) -> str:
    kind = check_choice(correction)
    detail = {'swap_sides': 'bow/stern swapped', 'reverse_order': f'{correction.get("half")} station order reversed',
              'other': 'reader not used (other problem)'}[kind]
    return f'calibration corrected by a person: {detail}'


def correct_reading(ink, record: dict, correction: dict) -> dict:
    kind = check_choice(correction)
    if not record or not record.get('calibration'):
        raise ValueError('This run has no saved body-plan calibration.')
    if kind == 'other':
        fixed = copy.deepcopy(record)
        fixed.update(usable_for_build=False, engineering_approved=False,
                     reason=f'person reported another calibration problem: {correction["text"].strip()}')
    else:
        cal = bpi.calibration_from_record(record['calibration'])
        if not cal.usable:
            raise ValueError('The saved calibration is incomplete; choose Other.')
        if kind == 'swap_sides':
            # Station groups keep their identities; move each group to the opposite ink half,
            # with that half's grid. Do not just rename fore/aft on unchanged station curves.
            physical = {side['sign']: side for side in copy.deepcopy(cal.sides)}
            for side in cal.sides:
                opposite = physical[-side['sign']]
                side.update(sign=opposite['sign'], grid_columns=opposite['grid_columns'], source='person')
            resolved = 'sides'
        else:
            side = next(s for s in cal.sides if s['name'] == correction['half'])
            side['stations_outer_first'] = list(reversed(side['stations_outer_first']))
            side['source'] = 'person'
            resolved = 'station_order'
        cal.flags = [flag for flag in cal.flags if flag.field != resolved]
        cal.sources[resolved] = 'person'
        cal.notes.append(correction_message(correction))
        fixed = read_with_calibration(ink, cal)
        # Preserve independent original evidence for the review and later corrections.
        for key in ('side_checks', 'scale_measures'):
            fixed['calibration'][key] = copy.deepcopy(record['calibration'].get(key))
        if 'spec_page_scale' in record:
            fixed['spec_page_scale'] = record['spec_page_scale']
    fixed['correction'] = copy.deepcopy(correction)
    return fixed


def rebuild(tools, correction: dict) -> dict:
    """Rebuild via the intake hull path. Keep a snapshot and roll back a failed build."""
    from .first_hull_tools import build_first_hull

    check_choice(correction)
    image, _, _ = tools._source()
    gray = image.mean(axis=2) if image.ndim == 3 else image
    record = tools.body_plan_reading()
    # The task source can be a reduced intake page. Correct in those pixels, then save
    # that calibration at scale 1 so later overlays and anchors do not scale it twice.
    working = copy.deepcopy(record)
    scale = working.get('spec_page_scale', 1.0) if working else 1.0
    if working and scale != 1.0:
        working['calibration'] = bpi.calibration_record(bpi.calibration_from_record(working['calibration'], scale))
        working['spec_page_scale'] = 1.0
    fixed = correct_reading(gray < 128, working, correction)
    snapshot = copy.deepcopy(tools.state)
    previous_revision = tools.revision_id
    folder = tools.root / 'calibration-revisions' / uuid.uuid4().hex
    folder.mkdir(parents=True)
    write_json(folder / 'previous-state.json', snapshot)
    mutable_files = [tools.root / name for name in (bpi.CHECK_JSON, bpi.CHECK_PNG, 'vessel.json')]
    previous_files = {path: path.read_bytes() if path.exists() else None for path in mutable_files}

    def restore():
        tools.state = snapshot
        for path, content in previous_files.items():
            if content is None:
                path.unlink(missing_ok=True)
            else:
                path.write_bytes(content)
        tools._save()

    tools.state['revision'] += 1
    tools.state['body_plan_reading_override'] = fixed
    tools.state['set_aside_builds'] = tools.state.get('set_aside_builds', []) + tools.state.get('builds', [])
    tools.state.update(builds=[], validation=None, rendered_views=[], last_valid_candidate=None,
                       best_valid_candidate=None)
    # First-hull fitting uses the model's original candidate anchors, not authored edits
    # from the obsolete reader hull. Those edits remain in the saved revision snapshot.
    tools.state['authored_sections'] = {}
    tools._save()
    try:
        result = build_first_hull(tools)
        if not result.get('ok'):
            restore()
            return result
        entry = {'message': correction_message(correction), 'correction': copy.deepcopy(correction),
                 'previous_revision_id': previous_revision, 'revision_id': tools.revision_id,
                 'previous_state': (folder / 'previous-state.json').relative_to(tools.root).as_posix(),
                 'engineering_approved': False}
        tools.state.setdefault('calibration_history', []).append(entry)
        tools._save()
        return tools._observation(True, 'calibration_corrected', candidate=result.get('candidate'),
                                  calibration_correction=entry, message=entry['message'])
    except Exception:
        restore()
        raise
