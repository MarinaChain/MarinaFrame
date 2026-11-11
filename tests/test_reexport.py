"""Re-export changes derived records, never build evidence."""
import json
import os
from pathlib import Path

import pytest

from vessel_reconstruction import reexport
from vessel_reconstruction.file_lock import try_lock_exclusive, unlock
from test_exports import make_box_task


def snapshot(task):
    return {p.relative_to(task).as_posix(): p.read_bytes()
            for p in task.rglob('*') if p.is_file()}


def finished(tmp_path):
    task = make_box_task(tmp_path)
    (task / 'state.json').write_text(json.dumps({'state': {
        'status': 'awaiting_human_review', 'pending': None}}))
    (task / 'controller.lock').touch()
    return task


def test_refresh_preserves_every_original_file(tmp_path):
    task = finished(tmp_path)
    before = snapshot(task)
    result = reexport.refresh(task, 'r1')
    after = snapshot(task)
    assert all(after[name] == data for name, data in before.items())
    assert result['engineering_approved'] is False
    records = json.loads((task / 'sources/records.json').read_text())
    assert records['sections']
    assert all(r['kind'] == 'unknown' for r in records['sections'].values())
    assert json.loads((task / 'review/part_reviews.json').read_text()) == {}
    assert (task / 'presentation.json').is_file()
    assert list((task / 'exports').glob('*_package.zip'))
    assert (task / 'reexport/manifest.json').is_file()
    reexport.refresh(task, 'r1')
    history = json.loads((task / 'reexport/history.json').read_text())
    assert len(history) == 2


@pytest.mark.parametrize('point', ['records', 'exports', 'before_publish', 'after_publish'])
def test_failure_leaves_original_bytes(tmp_path, monkeypatch, point):
    task = finished(tmp_path)
    before = snapshot(task)
    def fail(phase):
        if phase == point:
            raise RuntimeError('injected failure')
    monkeypatch.setattr(reexport, '_checkpoint', fail)
    with pytest.raises(RuntimeError, match='injected'):
        reexport.refresh(task, 'r1')
    assert snapshot(task) == before


def test_controller_lock_is_held_on_both_sides_of_exchange(tmp_path, monkeypatch):
    task = finished(tmp_path)
    inode = (task / 'controller.lock').stat().st_ino
    seen = []
    def check(phase):
        if phase in ('before_publish', 'after_publish'):
            assert (task / 'controller.lock').stat().st_ino == inode
            with (task / 'controller.lock').open('r+b') as contender:
                with pytest.raises(BlockingIOError):
                    try_lock_exclusive(contender)
            seen.append(phase)
    monkeypatch.setattr(reexport, '_checkpoint', check)
    reexport.refresh(task, 'r1')
    assert seen == ['before_publish', 'after_publish']


def test_busy_and_symlink_runs_are_refused(tmp_path):
    task = finished(tmp_path)
    with (task / 'controller.lock').open('r+b') as lock:
        try_lock_exclusive(lock)
        try:
            with pytest.raises(BlockingIOError):
                reexport.refresh(task, 'r1')
        finally:
            unlock(lock)
    os.symlink(task / 'state.json', task / 'escape')
    with pytest.raises(ValueError, match='link'):
        reexport.refresh(task, 'r1')
