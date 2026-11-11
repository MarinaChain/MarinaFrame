"""Trusted part workers retain order, errors and the shared worker bound."""
import os
from pathlib import Path

import pytest

from vessel_reconstruction import parallel


def _identity(value):
    return value, os.getpid()


def _fail(value):
    raise ValueError(f'bad part: {value}')


def test_parts_use_processes_in_input_order(tmp_path, monkeypatch):
    monkeypatch.setenv(parallel.POOL_DIRECTORY_ENVIRONMENT_VARIABLE, str(tmp_path / 'pool'))
    result = parallel.process_parts(_identity, [3, 1, 2], tmp_path, workers=2)
    assert [value for value, _ in result] == [3, 1, 2]
    assert all(pid != os.getpid() for _, pid in result)
    assert len({pid for _, pid in result}) == 2
    assert not list(tmp_path.glob('.parts-*'))


def test_parts_respect_occupied_pool(tmp_path, monkeypatch):
    monkeypatch.setenv(parallel.POOL_DIRECTORY_ENVIRONMENT_VARIABLE, str(tmp_path / 'pool'))
    monkeypatch.setattr(parallel, 'pool_size', lambda: 2)
    with parallel.worker_tokens(1):
        result = parallel.process_parts(_identity, [1, 2, 3], tmp_path, workers=8)
        with parallel.worker_tokens(1, wait=False) as free:
            assert free == 1  # only the outer holder remains
    assert len({pid for _, pid in result}) == 1


def test_parts_serial_and_parallel_errors_match(tmp_path, monkeypatch):
    monkeypatch.setenv(parallel.POOL_DIRECTORY_ENVIRONMENT_VARIABLE, str(tmp_path / 'pool'))
    for workers in (1, 2):
        with pytest.raises(ValueError, match='^bad part: first$'):
            parallel.process_parts(_fail, ['first', 'second'], tmp_path, workers=workers)


def test_parts_serial_does_not_spawn(tmp_path):
    assert parallel.process_parts(_identity, [1, 2], tmp_path, workers=1) == [
        (1, os.getpid()), (2, os.getpid())]


def _synthetic_part(spec):
    import cadquery as cq
    from vessel_reconstruction.geometry import precise_volume_mm3
    name, length = spec
    shape = cq.Workplane('XY').box(length, 3, 2).val()
    return name, shape, precise_volume_mm3(shape)


@pytest.mark.cad
def test_synthetic_vessel_exports_are_identical(tmp_path, monkeypatch):
    monkeypatch.setenv(parallel.POOL_DIRECTORY_ENVIRONMENT_VARIABLE, str(tmp_path / 'pool'))
    import subprocess
    import sys
    # Each run needs a fresh STEP writer: OCC keeps process-global product counters.
    for workers in (1, 2):
        subprocess.run([sys.executable, str(Path(__file__).resolve()), str(tmp_path / str(workers)), str(workers)],
                       check=True, env={**os.environ, 'PYTHONPATH': os.pathsep.join(sys.path)})
    a, b = tmp_path / '1', tmp_path / '2'
    for path in a.rglob('*'):
        if not path.is_file():
            continue
        other = b / path.relative_to(a)
        if path.suffix == '.step':
            assert path.read_bytes().split(b'DATA;')[1] == other.read_bytes().split(b'DATA;')[1]
        else:
            assert path.read_bytes() == other.read_bytes()


def _export_synthetic(folder, workers):
    import json
    import numpy as np
    from benchmarks.gunnerus.whole_vessel_assembly import export_all
    folder.mkdir()
    os.environ[parallel.WORKERS_ENVIRONMENT_VARIABLE] = str(workers)
    parts = parallel.process_parts(_synthetic_part, [('deck', 10), ('house', 5)], folder, workers=workers)
    shapes = {name: shape for name, shape, _ in parts}
    _, meshes = export_all(shapes, folder)
    (folder / 'volumes.json').write_text(json.dumps([volume for _, _, volume in parts]))
    for name, (vertices, triangles) in meshes.items():
        np.save(folder / f'{name}-vertices.npy', vertices)
        np.save(folder / f'{name}-triangles.npy', triangles)


@pytest.mark.cad
def test_ship_components_and_failure_reports_match(tmp_path, monkeypatch):
    from copy import deepcopy
    from vessel_reconstruction.ship_cad import execute
    monkeypatch.setenv(parallel.POOL_DIRECTORY_ENVIRONMENT_VARIABLE, str(tmp_path / 'pool'))
    components = []
    for name, op in [('deck', 'deck'), ('house', 'deckhouse'), ('bad', 'deckhouse')]:
        components.append({'id': name, 'op': op,
                           'source': {'view': 'plan', 'region': name, 'method': 'closed_outline'},
                           'args': {'outline': 'outline', 'height': 'height'}})
    program = {'schema': 'ship-cad/v1', 'components': components}
    measurements = {
        'outline': {'status': 'measured', 'kind': 'outline', 'value': [[0, 0], [2, 0], [2, 1], [0, 1]],
                    'view': 'plan', 'region': 'deck', 'method': 'closed_outline',
                    'source_sha256': 'a' * 64, 'entity_ids': ['A']},
        'height': {'status': 'measured', 'kind': 'interval', 'value': [1, 3],
                   'view': 'profile', 'region': 'test', 'method': 'parallel_lines',
                   'source_sha256': 'b' * 64, 'entity_ids': ['B']}}
    components[-1]['args']['outline'] = 'missing'
    a = execute(deepcopy(program), measurements, tmp_path / 'serial', workers=1)
    b = execute(deepcopy(program), measurements, tmp_path / 'parallel', workers=2)
    assert a == b
    assert a['components'][0]['built']
    assert not a['components'][-1]['built']
    assert (tmp_path / 'serial/provenance.json').read_bytes() == (tmp_path / 'parallel/provenance.json').read_bytes()


@pytest.mark.cad
def test_internal_and_steel_builds_match(tmp_path, monkeypatch):
    from benchmarks.gunnerus.whole_vessel_internals import Part, build_internal_part
    from vessel_reconstruction.structure.block3d import _member_part
    monkeypatch.setenv(parallel.POOL_DIRECTORY_ENVIRONMENT_VARIABLE, str(tmp_path / 'pool'))
    outline = [[-1, 0], [1, 0], [1, 2], [-1, 2]]
    parts = [Part(name, 'bulkhead', name, [(0, 0.01, outline)], {}, {}, {}) for name in ('one', 'two')]
    serial = parallel.process_parts(build_internal_part, parts, tmp_path, workers=1)
    concurrent = parallel.process_parts(build_internal_part, parts, tmp_path, workers=2)
    for (a, amesh, arecord), (b, bmesh, brecord) in zip(serial, concurrent):
        assert a.Volume() == b.Volume()
        assert arecord == brecord
        assert all(x.tobytes() == y.tobytes() for x, y in zip(amesh, bmesh))
    members = [(i, {'thickness_mm': 10, 'box': [0, 0, 0, 2, 3, 0]}) for i in range(2)]
    a = parallel.process_parts(_member_part, members, tmp_path, workers=1)
    b = parallel.process_parts(_member_part, members, tmp_path, workers=2)
    assert [p.shape.Volume() for p in a] == [p.shape.Volume() for p in b]


if __name__ == '__main__':
    import sys
    import test_parallel_parts
    test_parallel_parts._export_synthetic(Path(sys.argv[1]), int(sys.argv[2]))
