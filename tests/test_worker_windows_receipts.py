"""Both workers check the platform first: on Windows they do no work and still write a receipt."""
import json
import sys

from vessel_reconstruction import rust_worker, worker


def _windows():
    raise RuntimeError('Windows')  # what process_limits.posix_resource does on Windows


def test_rust_worker_fails_closed_on_windows_before_any_work(monkeypatch, tmp_path):
    monkeypatch.setattr(rust_worker, 'posix_resource', _windows)
    monkeypatch.setattr(rust_worker, 'execute', lambda *a: (_ for _ in ()).throw(AssertionError('work ran')))
    response = tmp_path / 'response.json'
    code = rust_worker.main(['--task-root', str(tmp_path), '--source-spec', str(tmp_path / 's'),
                             '--response', str(response)])
    envelope = json.loads(response.read_text())
    assert code == 2 and envelope['execution_state'] == 'failed'
    assert envelope['error_code'] == 'worker_boundary_runtimeerror'


def test_cad_worker_writes_a_receipt_on_windows_before_any_work(monkeypatch, tmp_path):
    monkeypatch.setattr(worker, 'posix_resource', _windows)
    from vessel_reconstruction import pipeline
    monkeypatch.setattr(pipeline, 'reconstruct', lambda *a, **k: (_ for _ in ()).throw(AssertionError('work ran')))
    receipt = tmp_path / 'receipt.json'
    monkeypatch.setattr(sys, 'argv', ['worker', '--spec', 'spec', '--out', str(tmp_path / 'out'),
                                      '--receipt', str(receipt), '--limits', '{}', '--parent', '1'])
    assert worker.main() == 1
    assert json.loads(receipt.read_text())['error_code'] == 'worker_exception'
