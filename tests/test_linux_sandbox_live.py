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


def test_linux_runtime_imports_real_cad(tmp_path):
    import subprocess
    task, command = make_probe(tmp_path,
        "import sys,json\nimport site,os\nprint(json.dumps({'prefix':sys.prefix,'executable':sys.executable,'path':sys.path,'flags':str(sys.flags),'site':getattr(site,'__file__',None),'sites':site.getsitepackages(),'directories':[os.path.isdir(p) for p in site.getsitepackages()]}),flush=True)\nimport cadquery\nfrom pathlib import Path\nshape=cadquery.Workplane('XY').box(1,2,3)\nassert shape.val().Volume() == 6\nPath('cad-ok').write_text('ok')")
    result = subprocess.run(command, capture_output=True, text=True,
                            env={**worker.safe_worker_environment(), 'PYTHONDONTWRITEBYTECODE': '1'})
    assert result.returncode == 0, f'{result.stdout}\n{result.stderr}\nconfig={(task/"worker-linux.json").read_text()}'
    assert (task/'work'/'cad-ok').read_text() == 'ok'
