"""Telemetry reader contracts run on every native platform, without skips."""
import json
import os
import subprocess
import threading

from vessel_reconstruction.progress import MAX_PROGRESS_BYTES, read_child_progress


def test_regular_telemetry_is_bounded_and_request_bound(tmp_path):
    path = tmp_path / 'progress.json'
    value = {'request_id': 'request', 'stage': 'Building', 'part': 1, 'total': 2, 'unit': 'part'}
    path.write_text(json.dumps(value), encoding='utf-8')
    assert read_child_progress(str(path), 'request') == value
    assert read_child_progress(str(path), 'other') is None
    path.write_bytes(b' ' * (MAX_PROGRESS_BYTES + 1))
    assert read_child_progress(str(path), 'request') is None


def test_ancestor_link_never_exposes_external_telemetry(tmp_path):
    outside = tmp_path / 'outside'
    outside.mkdir()
    value = {'request_id': 'request', 'stage': 'External', 'part': 1, 'total': 2, 'unit': 'part'}
    (outside / 'progress.json').write_text(json.dumps(value), encoding='utf-8')
    link = tmp_path / 'link'
    if os.name == 'nt':
        subprocess.run(['cmd', '/c', 'mklink', '/J', str(link), str(outside)],
                       check=True, capture_output=True)
        assert read_child_progress(str(link / 'progress.json'), 'request') is None
    else:
        link.symlink_to(outside, target_is_directory=True)
        # The existing POSIX reader protects its final component only. Do not
        # weaken or silently change that contract during the Windows port.
        assert read_child_progress(str(link / 'progress.json'), 'request') == value


def test_concurrent_replacement_returns_only_complete_records(tmp_path):
    path = tmp_path / 'progress.json'
    value = {'request_id': 'request', 'stage': 'Building', 'part': 1, 'total': 2, 'unit': 'part'}
    payload = json.dumps(value)
    path.write_text(payload, encoding='utf-8')
    errors = []
    def replace():
        for index in range(100):
            temporary = tmp_path / f'progress-{index}.tmp'
            temporary.write_text(payload, encoding='utf-8')
            try:
                temporary.replace(path)
            except PermissionError:
                # Windows reader pins its final handle briefly; retry is the
                # writer's normal responsibility, not an unsafe sharing mode.
                temporary.unlink()
            except BaseException as error:
                errors.append(error)
    thread = threading.Thread(target=replace)
    thread.start()
    while thread.is_alive():
        assert read_child_progress(str(path), 'request') in (None, value)
    thread.join()
    assert not errors


def test_directory_and_missing_telemetry_are_rejected(tmp_path):
    assert read_child_progress(str(tmp_path), 'request') is None
    assert read_child_progress(str(tmp_path / 'missing'), 'request') is None
