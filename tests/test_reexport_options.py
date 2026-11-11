import json
import os

import pytest

from vessel_reconstruction import reexport
from vessel_reconstruction.cli import main
from test_reexport import finished, snapshot


def test_cli_refresh_and_missing_revision(tmp_path):
    task = finished(tmp_path)
    assert main(['re-export', str(task), '--revision', 'r1']) == 0
    before = snapshot(task)
    assert main(['re-export', str(task), '--revision', 'r99']) == 2
    assert snapshot(task) == before


def test_post_publication_lock_failure_rolls_back(tmp_path, monkeypatch):
    task = finished(tmp_path)
    before = snapshot(task)
    def lose_lock(phase):
        if phase == 'after_publish':
            (task / 'controller.lock').unlink()
            (task / 'controller.lock').touch()
    monkeypatch.setattr(reexport, '_checkpoint', lose_lock)
    with pytest.raises(RuntimeError, match='lock identity'):
        reexport.refresh(task, 'r1')
    assert snapshot(task) == before


def test_existing_user_choices_and_identity_survive(tmp_path):
    task = finished(tmp_path)
    (task / 'presentation.json').write_text('{"note":"Keep this note"}')
    (task / 'review').mkdir()
    (task / 'review/part_reviews.json').write_text('{"deck":{"state":"needs_review"}}')
    before = snapshot(task)
    reexport.refresh(task, 'r1')
    identity = (task / 'domain/vessel_identity.json').read_bytes()
    reexport.refresh(task, 'r1')
    assert (task / 'domain/vessel_identity.json').read_bytes() == identity
    assert all(snapshot(task)[n] == b for n, b in before.items())


def test_protected_geometry_tampering_is_refused(tmp_path, monkeypatch):
    task = finished(tmp_path)
    before = snapshot(task)
    original = reexport.export_draft
    def corrupt(stage, revision, out, **kwargs):
        result = original(stage, revision, out, **kwargs)
        next((stage / 'domain/builds').rglob('*.step')).write_bytes(b'changed')
        return result
    monkeypatch.setattr(reexport, 'export_draft', corrupt)
    with pytest.raises(ValueError, match='protected evidence'):
        reexport.refresh(task, 'r1')
    assert snapshot(task) == before


@pytest.mark.parametrize('state', [
    {'status': 'running'},
    {'status': 'awaiting_human_review', 'pending': {'id': 'x'}},
])
def test_unfinished_or_pending_is_refused(tmp_path, state):
    task = finished(tmp_path)
    (task / 'state.json').write_text(json.dumps({'state': state}))
    before = snapshot(task)
    with pytest.raises(ValueError, match='finished'):
        reexport.refresh(task, 'r1')
    assert snapshot(task) == before
