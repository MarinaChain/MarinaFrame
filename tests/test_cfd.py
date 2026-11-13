"""Synthetic contracts; these tests do not claim physical CFD accuracy."""
import math
import sys
import json

import pytest

from vessel_reconstruction.cfd import (
    CaseInput, SolverRun, read_forces, write_case, write_stl,
)


@pytest.fixture
def tetrahedron():
    a, b, c, d = (0., 0., 0.), (1., 0., 0.), (0., 1., 0.), (0., 0., 1.)
    return [(a, c, b), (a, b, d), (a, d, c), (b, c, d)]


def config(**changes):
    return CaseInput(**dict(dict(length_m=7.2786, speed_m_s=1.922,
                                wetted_area_m2=9.4379, sources=('synthetic',)), **changes))


@pytest.mark.parametrize('field', ['length_m', 'speed_m_s', 'wetted_area_m2', 'density_kg_m3', 'viscosity_m2_s'])
@pytest.mark.parametrize('value', [0, -1, math.nan, math.inf])
def test_invalid_physical_inputs(field, value):
    with pytest.raises(ValueError):
        config(**{field: value})


@pytest.mark.parametrize('field,value', [('base_cells', 3), ('base_cells', True), ('refinement_level', 6), ('iterations', 0), ('sources', ())])
def test_configuration_limits(field, value):
    with pytest.raises(ValueError):
        config(**{field: value})


def test_closed_oriented_stl(tmp_path, tetrahedron):
    path = tmp_path / 'hull.stl'
    write_stl(path, tetrahedron)
    assert path.read_text().count('facet normal') == 4
    with pytest.raises(FileExistsError):
        write_stl(path, tetrahedron)


@pytest.mark.parametrize('mutation', ['open', 'reversed', 'degenerate', 'nonfinite'])
def test_bad_surface_does_not_publish(tmp_path, tetrahedron, mutation):
    triangles = tetrahedron.copy()
    if mutation == 'open':
        triangles.pop()
    elif mutation == 'reversed':
        triangles[0] = tuple(reversed(triangles[0]))
    elif mutation == 'degenerate':
        triangles.append((triangles[0][0],) * 3)
    else:
        triangles[0] = ((math.nan, 0., 0.), *triangles[0][1:])
    path = tmp_path / 'hull.stl'
    with pytest.raises(ValueError):
        write_stl(path, triangles)
    assert not path.exists()


def test_case_is_separate_double_body_program(tmp_path, tetrahedron):
    case = tmp_path / 'case'
    write_case(case, config(), tetrahedron, available_bytes=30_000_000_000)
    assert 'simpleFoam' in (case / 'system/controlDict').read_text()
    assert 'hull.stl' in (case / 'system/snappyHexMeshDict').read_text()
    assert 'kOmegaSST' in (case / 'constant/turbulenceProperties').read_text()
    assert 'rhoInf 999.5' in (case / 'system/controlDict').read_text()
    assert 'p p;' in (case / 'system/controlDict').read_text()
    assert 'double_body' in (case / 'case-input.json').read_text()
    for field in ['U', 'p', 'k', 'omega', 'nut']:
        assert (case / '0' / field).is_file()
    with pytest.raises(FileExistsError):
        write_case(case, config(), tetrahedron, available_bytes=30_000_000_000)


def test_symmetry_case_uses_full_width_physical_force(tmp_path, tetrahedron):
    # Closed meshing solid touches z=0 and lies below the symmetry plane.
    triangles = [tuple((x, y, -z) for x, y, z in reversed(t)) for t in tetrahedron]
    case = tmp_path / 'symmetry'
    write_case(case, config(), triangles, available_bytes=30_000_000_000,
               waterplane_symmetry=True)
    metadata = json.loads((case / 'case-input.json').read_text())
    assert metadata['force_multiplier'] == 1
    assert metadata['waterplane_z_m'] == 0
    mesh = (case / 'system/blockMeshDict').read_text()
    assert 'waterplane { type symmetryPlane; faces ((4 5 6 7)); }' in mesh
    for name in ('U', 'p', 'k', 'omega', 'nut'):
        assert 'waterplane { type symmetryPlane; }' in (case / '0' / name).read_text()
    snappy = (case / 'system/snappyHexMeshDict').read_text()
    assert 'addLayers true' in snappy
    assert 'nSurfaceLayers 3' in snappy
    assert 'type yPlus' in (case / 'system/controlDict').read_text()


def test_symmetry_case_rejects_unclipped_surface(tmp_path, tetrahedron):
    with pytest.raises(ValueError, match='waterplane'):
        write_case(tmp_path / 'bad', config(), tetrahedron,
                   available_bytes=30_000_000_000, waterplane_symmetry=True)
    assert not (tmp_path / 'bad').exists()


def test_disk_reserve_before_case(tmp_path, tetrahedron):
    with pytest.raises(OSError, match='reserve'):
        write_case(tmp_path / 'case', config(), tetrahedron, available_bytes=10_000_000_001)
    assert not (tmp_path / 'case').exists()


def test_force_normalization_and_missing_attitude(tmp_path):
    path = tmp_path / 'forces.dat'
    path.write_text('# Time forces moments\n0 ((10 0 0) (2 0 0) (0 0 0)) ((0 0 0) (0 0 0) (0 0 0))\n1 ((14 0 0) (2 0 0) (0 0 0)) ((0 0 0) (0 0 0) (0 0 0))\n')
    result = read_forces(path, config(), start_time=0, force_multiplier=1)
    record = result.to_record_fragment()
    assert record['resistance']['value'] == 14
    assert record['ct']['value'] == pytest.approx(14 / (0.5 * 999.5 * 1.922**2 * 9.4379))
    assert record['sinkage']['value'] is None
    assert record['sinkage']['uncertainty']['reason']
    assert record['ct']['status'] == 'review_required'
    assert record['engineering_approved'] is False
    assert record['regime'] == 'double_body_fixed_attitude'
    assert record['ct']['sources'] == ['synthetic', str(path)]
    assert read_forces(path, config(), start_time=0).resistance_n == 7


def test_failed_run_cannot_read_results(tmp_path):
    path = tmp_path / 'forces.dat'
    path.write_text('0 ((1 0 0) (0 0 0) (0 0 0)) ((0 0 0) (0 0 0) (0 0 0))\n')
    (tmp_path / 'run-receipt.json').write_text(json.dumps({'state': 'failed', 'exit_code': 1}))
    with pytest.raises(ValueError, match='completed'):
        read_forces(path, config(), start_time=0, run_receipt=tmp_path / 'run-receipt.json')


@pytest.mark.parametrize('text', ['', '0 ((nan 0 0) (2 0 0))', '0 broken', '2 ((1 0 0) (2 0 0) (0 0 0)) ((0 0 0) (0 0 0) (0 0 0))\n1 ((1 0 0) (2 0 0) (0 0 0)) ((0 0 0) (0 0 0) (0 0 0))'])
def test_bad_forces_rejected(tmp_path, text):
    path = tmp_path / 'forces.dat'
    path.write_text(text)
    with pytest.raises(ValueError):
        read_forces(path, config(), start_time=0)


def test_runner_failure_and_accounting(tmp_path):
    run = SolverRun.start([sys.executable, '-c', 'print("Time = 3"); raise SystemExit(7)'], tmp_path)
    receipt = run.wait()
    assert receipt['state'] == 'failed'
    assert receipt['exit_code'] == 7
    assert receipt['allocated_core_hours'] == pytest.approx(receipt['wall_seconds'] / 3600)
    assert run.progress()['last_time'] == 3


def test_runner_hides_provider_environment(tmp_path, monkeypatch):
    monkeypatch.setenv('CFD_TEST_SECRET', 'private-test-value')
    run = SolverRun.start([sys.executable, '-c', 'import os; print(os.getenv("CFD_TEST_SECRET", "absent"))'], tmp_path)
    assert run.wait()['state'] == 'completed'
    assert (tmp_path / 'solver.log').read_text().strip() == 'absent'


def test_runner_missing_executable(tmp_path):
    with pytest.raises(FileNotFoundError):
        SolverRun.start(['/does/not/exist/cfd-solver'], tmp_path)
    assert not (tmp_path / 'run-receipt.json').exists()


def test_runner_cancel(tmp_path):
    run = SolverRun.start([sys.executable, '-c', 'import time; time.sleep(3600)'], tmp_path)
    run.cancel()
    assert run.wait()['state'] == 'cancelled'


def test_runner_no_wall_deadline(tmp_path):
    run = SolverRun.start([sys.executable, '-c', 'print("End")'], tmp_path)
    assert run.wait()['state'] == 'completed'
    with pytest.raises(FileExistsError):
        SolverRun.start([sys.executable, '-c', ''], tmp_path)
