from pathlib import Path

from vessel_reconstruction import reexport
from test_reexport import finished, snapshot


def test_requested_conversion_uses_step_without_changing_build(tmp_path, monkeypatch):
    task = finished(tmp_path)
    for suffix in ('iges', '3dm'):
        for path in (task / 'domain/builds').rglob(f'*.{suffix}'):
            path.unlink()
    before = snapshot(task)
    calls = []
    def convert(step, destination, formats):
        assert step.read_bytes() == next((task / 'domain/builds').rglob('*.step')).read_bytes()
        calls.extend(formats)
        paths = {}
        for fmt in formats:
            paths[fmt] = destination / f'model.{fmt}'
            paths[fmt].write_bytes(b'derived format')
        return paths
    monkeypatch.setattr(reexport, '_convert_step', convert)
    reexport.refresh(task, 'r1', cad_formats=['iges', '3dm'])
    assert calls == ['iges', '3dm']
    assert all(snapshot(task)[n] == b for n, b in before.items())
    assert next((task / 'exports').glob('*_model.iges')).read_bytes() == b'derived format'
