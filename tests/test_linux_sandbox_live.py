"""Kernel tests: skipped only on non-Linux, never for absent kernel features."""
import json
import os
from pathlib import Path
import sys
import threading

import pytest

from vessel_reconstruction import ship_cad_worker as worker
from vessel_reconstruction.isolation import SANDBOX_MODEL_LIMITS, supervise_process

pytestmark = pytest.mark.skipif(sys.platform != 'linux', reason='Linux kernel sandbox only')


def make_probe(tmp_path, script):
    task = tmp_path/'task'
    (task/'work').mkdir(parents=True)
    worker.require_sandbox()
    command, _ = worker.sandbox_command(task, SANDBOX_MODEL_LIMITS)
    # Keep the trusted launcher/config, replacing only the interpreter payload.
    return task, [*command[:5], '-I', '-c', script]


def test_linux_supervisor_stop_kills_sandbox_group(tmp_path):
    task, command = make_probe(tmp_path,
        "import signal,time\nfrom pathlib import Path\nsignal.signal(signal.SIGTERM, signal.SIG_IGN)\nPath('ready').write_text('ready')\nwhile True: time.sleep(.05)")
    cancel = threading.Event()
    def cancel_when_ready():
        # Bound the test helper, not production own-code CAD work.
        import time
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            if (task/'work'/'ready').exists():
                break
            time.sleep(.02)
        cancel.set()
    helper = threading.Thread(target=cancel_when_ready)
    helper.start()
    outcome = supervise_process(command, limits=SANDBOX_MODEL_LIMITS,
                                cancel_event=cancel, sandboxed_model_code=True)
    helper.join()
    assert (task/'work'/'ready').exists(), outcome
    assert outcome['state'] == 'cancelled'
    assert outcome['exit_code'] == -9
    with pytest.raises(ProcessLookupError):
        os.killpg(outcome['process']['pgid'], 0)


def test_live_run_denies_model_read_outside_task(monkeypatch, tmp_path):
    outside = tmp_path/'private-input'
    outside.write_text('host private data')
    original_command = worker.sandbox_command
    def probe_command(task, limits):
        command, label = original_command(task, limits)
        # Inject only the model executor for this test. run(), the actual native
        # launcher, child main/attestation and result reader remain production code.
        code = ("import json\nfrom pathlib import Path\n"
                "from vessel_reconstruction import ship_cad,ship_cad_worker\n"
                "def execute(program, measurements, output, **kwargs):\n"
                f" try: Path({str(outside)!r}).read_text()\n"
                " except PermissionError: pass\n"
                " else: raise AssertionError('model read escaped')\n"
                " output.mkdir()\n"
                " (output/'provenance.json').write_text(json.dumps({'read_denied':True}))\n"
                "ship_cad.execute=execute\n"
                "raise SystemExit(ship_cad_worker.main())\n")
        return [*command[:5], '-c', code, *command[7:]], label
    monkeypatch.setattr(worker, 'sandbox_command', probe_command)
    outcome = worker.run({'schema': 'ship-cad/v1', 'components': []}, {}, tmp_path/'task')
    assert outcome['exit_code'] == 0, outcome
    assert outcome['result'] == {'read_denied': True}


def test_wrong_launcher_cannot_reach_executor(monkeypatch, tmp_path):
    launcher = tmp_path/'not-a-sandbox'
    launcher.write_text('#!/bin/sh\nshift 3\nexec "$@"\n')
    launcher.chmod(0o700)
    monkeypatch.setenv('MARINAFRAME_SANDBOX_LAUNCHER', str(launcher))
    outcome = worker.run({'schema': 'ship-cad/v1', 'components': []}, {}, tmp_path/'task')
    assert outcome['exit_code'] != 0
    assert outcome['result'] is None
    assert not (tmp_path/'task'/'work'/'output').exists()


def test_linux_runtime_imports_real_cad(tmp_path):
    import subprocess
    task, command = make_probe(tmp_path,
        "import sys,json\nimport site,os\nprint(json.dumps({'prefix':sys.prefix,'executable':sys.executable,'path':sys.path,'flags':str(sys.flags),'site':getattr(site,'__file__',None),'sites':site.getsitepackages(),'directories':[os.path.isdir(p) for p in site.getsitepackages()]}),flush=True)\nimport cadquery\nfrom pathlib import Path\nshape=cadquery.Workplane('XY').box(1,2,3)\nassert shape.val().Volume() == 6\nPath('cad-ok').write_text('ok')")
    result = subprocess.run(command, capture_output=True, text=True,
                            env={**worker.safe_worker_environment(), 'PYTHONDONTWRITEBYTECODE': '1',
                                 'HOME': str(task/'work'), 'TMPDIR': str(task/'work')})
    assert result.returncode == 0, f'{result.stdout}\n{result.stderr}\nconfig={(task/"worker-linux.json").read_text()}'
    assert (task/'work'/'cad-ok').read_text() == 'ok'
