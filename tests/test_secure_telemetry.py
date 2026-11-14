"""Telemetry reader contracts run on every native platform, without skips."""
import json

from vessel_reconstruction.progress import MAX_PROGRESS_BYTES, read_child_progress


def test_regular_telemetry_is_bounded_and_request_bound(tmp_path):
    path = tmp_path / 'progress.json'
    value = {'request_id': 'request', 'stage': 'Building', 'part': 1, 'total': 2, 'unit': 'part'}
    path.write_text(json.dumps(value), encoding='utf-8')
    assert read_child_progress(str(path), 'request') == value
    assert read_child_progress(str(path), 'other') is None
    path.write_bytes(b' ' * (MAX_PROGRESS_BYTES + 1))
    assert read_child_progress(str(path), 'request') is None


def test_directory_and_missing_telemetry_are_rejected(tmp_path):
    assert read_child_progress(str(tmp_path), 'request') is None
    assert read_child_progress(str(tmp_path / 'missing'), 'request') is None
