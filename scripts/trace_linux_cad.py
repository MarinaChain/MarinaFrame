"""Trace trusted CAD fixtures under the existing sandbox, never disable policy.

Summaries include launcher setup and failed calls. They are evidence for manual
review, NOT an automatically generated permission list.
"""
from pathlib import Path
import argparse
import platform
import subprocess
import sys

from vessel_reconstruction.ship_cad_worker import sandbox_command, safe_worker_environment
from vessel_reconstruction.isolation import SANDBOX_MODEL_LIMITS


CAD_PROBE = """
import cadquery as cq
from pathlib import Path
from vessel_reconstruction.ship_cad_worker import confirm_linux_sandbox
confirm_linux_sandbox()
print('TRACE_STAGE: CAD import and attestation complete', flush=True)
shape = cq.Workplane('XY').box(2, 3, 4)
print('TRACE_STAGE: solid complete', flush=True)
cq.exporters.export(shape, 'fixture.step')
print('TRACE_STAGE: STEP export complete', flush=True)
shape.val().exportStl('fixture.stl', parallel=False)
print('TRACE_STAGE: serial STL export complete', flush=True)
restored = cq.importers.importStep('fixture.step')
assert restored.val().Volume() > 20
Path('finished').write_text('ok')
"""


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    root = args.out.resolve()
    root.mkdir(parents=True, exist_ok=False)
    task = root/'task'
    (task/'work').mkdir(parents=True)
    command, label = sandbox_command(task, SANDBOX_MODEL_LIMITS)
    payload = [*command[:5], '-c', CAD_PROBE]
    environment = safe_worker_environment()
    environment.update(HOME=str(task/'work'), TMPDIR=str(task/'work'), PYTHONDONTWRITEBYTECODE='1')
    # CI traces this trusted supervisor with -f, preserving the launcher's
    # expected parent PID. Wrapping only the launcher would insert strace as parent.
    result = subprocess.run(payload, env=environment)
    print(f'Architecture: {platform.machine()}; policy: {label}; exit: {result.returncode}', flush=True)
    if result.returncode or not (task/'work'/'finished').is_file():
        raise SystemExit('Contained CAD trace fixture failed')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
