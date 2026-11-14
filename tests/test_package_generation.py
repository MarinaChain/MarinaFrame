"""Immutable export generations publish through one current-pointer replacement."""
import json

import pytest

from vessel_reconstruction.exports.generations import publish_generation, resolve_generation


def test_export_replacement_integrates_generation_resolution(monkeypatch, tmp_path):
    from vessel_reconstruction.exports import package
    from vessel_reconstruction.exports.generations import resolve_package_folder
    from test_exports import make_box_task
    monkeypatch.setattr(package, '_USE_GENERATIONS', True)
    task = make_box_task(tmp_path, with_cad=False)
    root = tmp_path / 'out'
    first = package.export_draft(task, 'r1', root)
    assert resolve_package_folder(root) == root
    second = package.export_draft(task, 'r1', root)
    generation = resolve_package_folder(root)
    assert generation != root
    assert (generation / second['package']['file']).is_file()
    assert (root / first['package']['file']).is_file()
    assert first['package']['sha256'] == second['package']['sha256']


def test_pointer_keeps_old_generation_available(tmp_path):
    root = tmp_path / 'package'
    first = tmp_path / 'first'
    first.mkdir()
    (first / 'report').write_bytes(b'old')
    old = publish_generation(root, first)
    second = tmp_path / 'second'
    second.mkdir()
    (second / 'report').write_bytes(b'new')
    new = publish_generation(root, second)
    assert resolve_generation(root) == new
    assert (old / 'report').read_bytes() == b'old'
    assert (new / 'report').read_bytes() == b'new'


def test_failed_pointer_write_keeps_current_generation(monkeypatch, tmp_path):
    from vessel_reconstruction.exports import generations
    root = tmp_path / 'package'
    first = tmp_path / 'first'
    first.mkdir()
    old = publish_generation(root, first)
    second = tmp_path / 'second'
    second.mkdir()
    def fail(*args):
        raise OSError('controlled pointer failure')
    monkeypatch.setattr(generations, 'write_json', fail)
    with pytest.raises(OSError):
        publish_generation(root, second)
    assert resolve_generation(root) == old
    assert old.is_dir()


def test_generation_files_are_flushed_before_pointer_switch(monkeypatch, tmp_path):
    from vessel_reconstruction.exports import generations
    root, stage = tmp_path / 'package', tmp_path / 'stage'
    stage.mkdir()
    payload = stage / 'report'
    payload.write_bytes(b'complete')
    operations = []
    original = generations.write_json
    monkeypatch.setattr(generations, 'sync_file', lambda path: operations.append(('flush', path.name)))
    def pointer(path, value):
        operations.append(('pointer', path.name))
        original(path, value)
    monkeypatch.setattr(generations, 'write_json', pointer)
    publish_generation(root, stage)
    assert operations == [('flush', 'report'), ('pointer', 'current.json')]


def test_pointer_cannot_escape_generation_root(tmp_path):
    root = tmp_path / 'package'
    root.mkdir()
    (root / 'current.json').write_text(json.dumps({'generation': '../outside'}))
    with pytest.raises(ValueError):
        resolve_generation(root)
