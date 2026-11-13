"""Remote safety contracts; never contact a real host in tests."""
import pytest

from vessel_reconstruction.cfd.remote import RemoteHost, RemoteSolverRun, sustained_high_load


@pytest.mark.parametrize('changes', [
    {'host': '-oProxyCommand=bad'}, {'host': 'user@host;bad'},
    {'root': '/tmp/work'}, {'root': '~/marinaframe-cfd/../other'},
    {'image': 'untrusted/solver:latest'}, {'image': 'opencfd/openfoam-default:latest'},
])
def test_remote_configuration_rejects_unsafe_values(changes):
    values = dict(host='worker@example.test', image='opencfd/openfoam-default:2412', root='~/marinaframe-cfd')
    values.update(changes)
    with pytest.raises(ValueError):
        RemoteHost(**values)


def test_sustained_load_requires_ten_minutes():
    assert not sustained_high_load([(0, 8), (599, 9)])
    assert sustained_high_load([(0, 8), (600, 9)])
    assert not sustained_high_load([(0, 8), (600, 6), (1200, 9)])
    assert not sustained_high_load([(0, 7), (600, 7)])


def test_remote_launch_is_confined_and_resource_limited():
    host = RemoteHost('worker@example.test', 'opencfd/openfoam-default:2412')
    script = host.launch_script('kcs-coarse', ['simpleFoam'])
    for required in ['--cpus 5', '--memory 12g', 'nice -n 10', 'mf-cfd-kcs-coarse',
                     'flock', 'uptime', '600', 'docker pause', '40000000000',
                     '--network none', '--cap-drop ALL', '--security-opt no-new-privileges']:
        assert required in script
    assert 'sudo' not in script
    assert 'docker system' not in script
    assert 'docker rm' not in script
    assert '/var/run/docker.sock' not in script
    assert script.index('high_since=') < script.index('docker run')
    assert 'trap ' in script
    assert 'planned_peak_bytes' in script
    assert 'docker ps --filter' in script
    assert 'mf-cfd-' in script
    assert 'docker image inspect' in script
    assert 'free - planned_peak_bytes' in script
    assert 'find ' not in script  # Never search another remote workspace.
    assert 'exec 9>&-' in script  # The container must not inherit the lane lock.
    assert 'src=$PWD/data,dst=/case' in script
    assert '--read-only' in script
    assert '--log-opt max-size=10m' in script
    assert '--log-opt max-file=2' in script
    assert '--tmpfs /tmp:rw,noexec,nosuid,size=256m' in script
    assert 'set -C' in script
    assert '"$free" -lt 10000000000' in script
    assert '500000000' in script  # Conservative bounded scratch/log allowance.


@pytest.mark.parametrize('name', ['../other', 'name;kill', '-bad', ''])
def test_run_names_confined(name):
    with pytest.raises(ValueError):
        RemoteHost('worker@example.test', 'opencfd/openfoam-default:2412').launch_script(name, ['simpleFoam'])


def test_only_solver_argument_lists_not_shell_strings():
    host = RemoteHost('worker@example.test', 'opencfd/openfoam-default:2412')
    with pytest.raises(ValueError):
        host.launch_script('kcs', ['bash', '-c', 'untrusted'])
    assert 'snappyHexMesh' in host.launch_script('kcs', ['snappyHexMesh', '-overwrite'])


def test_surface_check_accepts_only_confined_relative_path():
    host = RemoteHost('worker@example.test', 'opencfd/openfoam-default:2412')
    assert 'surfaceCheck' in host.launch_script('surface-check', ['surfaceCheck', 'kcs-full.stl'])
    with pytest.raises(ValueError):
        host.launch_script('surface-check', ['surfaceCheck', '/etc/passwd'])
    with pytest.raises(ValueError):
        host.launch_script('surface-check', ['surfaceCheck', '../other/file.stl'])


def test_remote_wait_accounts_five_cores(monkeypatch, tmp_path):
    host = RemoteHost('worker@example.test', 'opencfd/openfoam-default:2412')
    run = RemoteSolverRun(host, 'kcs-coarse', tmp_path)
    monkeypatch.setattr(RemoteSolverRun, 'progress', lambda self: {'state': 'completed', 'wall_seconds': 720, 'exit_code': 0})
    assert run.wait()['allocated_core_hours'] == 1


def test_remote_progress_parses_last_solver_time(monkeypatch, tmp_path):
    host = RemoteHost('worker@example.test', 'opencfd/openfoam-default:2412')
    run = RemoteSolverRun(host, 'kcs-coarse', tmp_path)
    monkeypatch.setattr(RemoteHost, 'execute', lambda self, script: '{"state":"running","last_time":3.5}')
    result = run.progress()
    assert result['last_time'] == 3.5


def test_upload_rejects_repository_and_symlinks(tmp_path):
    (tmp_path / 'private-data').write_text('must not upload')
    host = RemoteHost('worker@example.test', 'opencfd/openfoam-default:2412')
    with pytest.raises(ValueError, match='generated case'):
        RemoteSolverRun.start(['interFoam'], tmp_path, host=host, name='kcs-coarse')


def test_upload_rejects_executable_dictionary(tmp_path):
    (tmp_path / 'system').mkdir()
    (tmp_path / 'system' / 'controlDict').write_text('functions { bad { type coded; code #{ dangerous #}; } }')
    host = RemoteHost('worker@example.test', 'opencfd/openfoam-default:2412')
    with pytest.raises(ValueError, match='executable'):
        RemoteSolverRun.start(['interFoam'], tmp_path, host=host, name='kcs-coarse')


def test_cartesian_mesh_allows_only_plain_command():
    host = RemoteHost('worker@example.test', 'opencfd/openfoam-default:2412')
    assert 'nice -n 10 cartesianMesh' in host.launch_script('cfmesh', ['cartesianMesh'])
    for options in (['-lib', 'evil.so'], ['-case', '../other']):
        with pytest.raises(ValueError):
            host.launch_script('cfmesh', ['cartesianMesh', *options])
    with pytest.raises(ValueError):
        host.launch_script('cfmesh', ['tetMesh'])


def test_dynamic_library_options_rejected():
    host = RemoteHost('worker@example.test', 'opencfd/openfoam-default:2412')
    with pytest.raises(ValueError):
        host.launch_script('kcs', ['interFoam', '-lib', 'constant/evil.so'])


def test_cancel_targets_only_own_named_container(monkeypatch, tmp_path):
    calls = []
    host = RemoteHost('worker@example.test', 'opencfd/openfoam-default:2412')
    run = RemoteSolverRun(host, 'kcs-coarse', tmp_path)
    monkeypatch.setattr(RemoteHost, 'execute', lambda self, script: calls.append(script) or '')
    run.cancel()
    assert len(calls) == 1
    assert 'mf-cfd-kcs-coarse' in calls[0]
    assert 'docker kill' in calls[0]
    assert '$(docker' not in calls[0]
