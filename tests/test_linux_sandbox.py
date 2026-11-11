"""Platform selection is portable; live kernel policy probes are Linux-only."""
from dataclasses import asdict
import json
import os
from pathlib import Path
import sys
import sysconfig

# Initialize host build metadata before tests mock sys.platform.
sysconfig.get_paths()

import pytest

from vessel_reconstruction import ship_cad_worker as worker
from vessel_reconstruction.isolation import SANDBOX_MODEL_LIMITS


def test_linux_library_path_comes_from_interpreter_not_environment(monkeypatch, tmp_path):
    from vessel_reconstruction.isolation import safe_worker_environment
    monkeypatch.setattr(sys, 'platform', 'linux')
    library = tmp_path/'runtime-lib'
    library.mkdir()
    monkeypatch.setattr(sysconfig, 'get_config_var', lambda key: str(library) if key == 'LIBDIR' else None)
    monkeypatch.setenv('LD_LIBRARY_PATH', '/untrusted/inherited')
    assert safe_worker_environment()['LD_LIBRARY_PATH'] == str(library)


def test_linux_launcher_missing_fails_closed(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, 'platform', 'linux')
    monkeypatch.setenv('MARINAFRAME_SANDBOX_LAUNCHER', str(tmp_path/'missing'))
    with pytest.raises(RuntimeError, match='Linux sandbox launcher'):
        worker.require_sandbox()


def test_linux_command_uses_native_launcher(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, 'platform', 'linux')
    launcher = tmp_path/'launcher'
    launcher.write_text('#!/bin/sh\nexit 125\n')
    launcher.chmod(0o700)
    monkeypatch.setenv('MARINAFRAME_SANDBOX_LAUNCHER', str(launcher))
    task = tmp_path/'task'
    (task/'work').mkdir(parents=True)
    command, label = worker.sandbox_command(task, SANDBOX_MODEL_LIMITS)
    assert command[:3] == [str(launcher), '--config', str(task/'worker-linux.json')]
    assert command[3:5] == ['--', sys.executable]
    assert label == 'linux-landlock-seccomp-deny-default'
    config = json.loads((task/'worker-linux.json').read_text())
    assert config['task'] == str(task)
    assert config['work'] == str(task/'work')
    assert config['limits'] == asdict(SANDBOX_MODEL_LIMITS)
    assert config['parent_pid'] == os.getpid()


def test_linux_runtime_never_grants_system_prefix_or_home(monkeypatch):
    monkeypatch.setattr(sys, 'prefix', '/usr')
    monkeypatch.setattr(sys, 'base_prefix', '/usr')
    paths = worker.linux_runtime_paths()
    assert Path('/usr') not in paths
    assert Path('/') not in paths
    assert Path.home() not in paths
    assert Path('/etc') not in paths


def test_unsupported_platform_fails_closed(monkeypatch):
    monkeypatch.setattr(sys, 'platform', 'win32')
    with pytest.raises(RuntimeError, match='no unsafe fallback'):
        worker.require_sandbox()


def test_linux_setup_failure_is_not_a_successful_empty_result(monkeypatch, tmp_path):
    from vessel_reconstruction import ship_cad
    monkeypatch.setattr(sys, 'platform', 'linux')
    monkeypatch.setattr(ship_cad, 'triage_program', lambda value: None)
    monkeypatch.setattr(worker, 'require_sandbox', lambda: None)
    monkeypatch.setattr(worker, 'sandbox_command', lambda *args: (['launcher'], 'linux-test'))
    monkeypatch.setattr(worker, 'supervise_process', lambda *args, **kwargs:
                        {'state': 'exited', 'exit_code': 125})
    task = tmp_path/'task'
    with pytest.raises(RuntimeError, match='Linux sandbox setup failed'):
        worker.run({}, {}, task)
    receipt = json.loads((task/'worker-receipt.json').read_text())
    assert receipt['error_code'] == 'sandbox_setup_failed'
    assert receipt['result'] is None
