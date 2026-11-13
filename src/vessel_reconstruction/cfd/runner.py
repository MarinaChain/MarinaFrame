"""Local separate-program lifecycle. No solver wall-clock deadline.

Trusted solver only: this is not a sandbox for model-generated code. Serial
execution avoids MPI descendants and provides portable cancellation on Windows.
A remote transport can later implement the same receipt/progress interface.
"""
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import time

from ..isolation import safe_worker_environment


class SolverRun:
    @classmethod
    def start(cls, command: list[str], case: Path):
        if not command or not command[0] or any(not isinstance(v, str) for v in command):
            raise ValueError('Expected an executable argument list')
        self = cls()
        self.case = Path(case).resolve(strict=True)
        self.started = time.monotonic()
        self.cancelled = False
        self.receipt = None
        # Exclusive log creation prevents silently replacing an earlier attempt.
        self.log = (self.case / 'solver.log').open('x')
        try:
            self.process = subprocess.Popen(
                command, cwd=self.case, stdout=self.log, stderr=subprocess.STDOUT,
                env=safe_worker_environment(), start_new_session=os.name != 'nt',
            )
        except BaseException:
            self.log.close()
            raise
        return self

    def progress(self):
        last_time = None
        cells = None
        # Stream instead of loading a potentially large solver log into memory.
        with (self.case / 'solver.log').open(errors='replace') as stream:
            for line in stream:
                match = re.match(r'Time = ([\d.eE+-]+)\s*$', line)
                if match:
                    last_time = float(match[1])
                match = re.search(r'^\s*cells:\s*(\d+)', line)
                if match:
                    cells = int(match[1])
        return dict(running=self.process.poll() is None, last_time=last_time, cells=cells)

    def cancel(self):
        if self.process.poll() is not None:
            return
        self.cancelled = True
        try:
            if os.name == 'nt':
                self.process.kill()
            else:
                os.killpg(self.process.pid, signal.SIGKILL)
        except ProcessLookupError:
            # The process can exit between poll and cancellation.
            pass

    def wait(self):
        if self.receipt is not None:
            return self.receipt
        code = self.process.wait()  # Deliberately no timeout for own-code solver work.
        self.log.close()
        elapsed = time.monotonic() - self.started
        self.receipt = dict(
            state='cancelled' if self.cancelled else ('completed' if code == 0 else 'failed'),
            exit_code=code, wall_seconds=elapsed, allocated_cores=1,
            allocated_core_hours=elapsed / 3600,
            accounting_basis='allocated serial core time, not measured CPU consumption',
            cells=self.progress()['cells'], engineering_approved=False,
        )
        with (self.case / 'run-receipt.json').open('x') as stream:
            json.dump(self.receipt, stream, indent=2)
            stream.write('\n')
        return self.receipt
