"""Native publication contract, exercised without platform skips on all three OSs."""
from pathlib import Path
from unittest.mock import Mock

import pytest

from vessel_reconstruction import platform_files
from vessel_reconstruction.provenance import write_json
from vessel_reconstruction.transaction import RunTransaction, rename_no_replace, quarantine_interrupted


def test_publish_complete_directory_without_overwrite(tmp_path):
    transaction = RunTransaction(tmp_path / 'run')
    write_json(transaction.stage / 'result.json', {'status': 'awaiting_human_review'})
    transaction.publish()
    transaction.close()
    assert (tmp_path / 'run' / 'result.json').is_file()
    assert not transaction.stage.exists()
    assert not transaction.lock_path.exists()


@pytest.mark.parametrize('existing_file', [False, True])
def test_no_replace_collision_preserves_both_sides(tmp_path, existing_file):
    source, target = tmp_path / 'stage', tmp_path / 'run'
    source.mkdir()
    (source / 'payload').write_bytes(b'complete')
    if existing_file:
        target.write_bytes(b'original')
    else:
        target.mkdir()
    with pytest.raises(FileExistsError):
        rename_no_replace(source, target)
    assert (source / 'payload').read_bytes() == b'complete'
    assert target.exists()
    if existing_file:
        assert target.read_bytes() == b'original'


def test_live_reservation_cannot_be_recovered(tmp_path):
    transaction = RunTransaction(tmp_path / 'run')
    try:
        result = quarantine_interrupted(tmp_path / 'run')
        assert not result['recovered']
        assert result['reason'] == 'active_transaction'
        assert transaction.stage.exists()
    finally:
        transaction.close()


def test_failed_rename_keeps_reservation_and_private_stage(monkeypatch, tmp_path):
    from vessel_reconstruction import transaction as module
    transaction = RunTransaction(tmp_path / 'run')
    def fail_move(*args):
        raise OSError('controlled move failure')
    monkeypatch.setattr(module, 'rename_no_replace', fail_move)
    with pytest.raises(OSError, match='controlled move failure'):
        transaction.publish()
    transaction.close()
    assert not transaction.published
    assert transaction.stage.is_dir()
    assert transaction.lock_path.exists()
    assert not transaction.out.exists()


def test_closed_unpublished_run_recovers_without_live_lock(tmp_path):
    transaction = RunTransaction(tmp_path / 'run')
    transaction.close()
    result = quarantine_interrupted(tmp_path / 'run')
    assert result['recovered']
    assert not transaction.lock_path.exists()


def test_windows_directory_move_is_write_through_and_never_replaces(monkeypatch, tmp_path):
    kernel = Mock()
    kernel.MoveFileExW.return_value = True
    monkeypatch.setattr(platform_files, '_kernel32', lambda: kernel)
    platform_files.move_windows_path(tmp_path / 'stage', tmp_path / 'run', replace=False)
    assert kernel.MoveFileExW.call_args.args[2] == 8


def test_windows_move_collision_is_file_exists(monkeypatch, tmp_path):
    kernel = Mock()
    kernel.MoveFileExW.return_value = False
    monkeypatch.setattr(platform_files, '_kernel32', lambda: kernel)
    monkeypatch.setattr(platform_files, '_last_error', lambda: 183)
    with pytest.raises(FileExistsError):
        platform_files.move_windows_path(tmp_path / 'stage', tmp_path / 'run', replace=False)
