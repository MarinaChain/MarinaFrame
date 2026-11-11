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
shape = cq.Workplane('XY').box(2, 3, 4).faces('>Z').workplane().hole(0.5)
cq.exporters.export(shape, 'fixture.step')
cq.exporters.export(shape, 'fixture.stl')
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
    summary = root/'syscalls.txt'
    result = subprocess.run(['strace', '-f', '-c', '-o', str(summary), '--', *payload], env=environment)
    print(f'Architecture: {platform.machine()}; policy: {label}; exit: {result.returncode}', flush=True)
    print(summary.read_text(), flush=True)
    if result.returncode or not (task/'work'/'finished').is_file():
        raise SystemExit('Contained CAD trace fixture failed')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
