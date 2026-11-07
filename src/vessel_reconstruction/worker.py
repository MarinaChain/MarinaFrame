"""Private native-work entry point. Apply Linux budgets before parser/CAD imports."""
from __future__ import annotations

import argparse
import ctypes
import json
import os
import resource
import signal
import sys
import time
from pathlib import Path

from .resources import native_resource_profile, peak_rss_kib


def apply_limits(limits: dict, parent_pid: int) -> None:
    linux = sys.platform == 'linux'
    if not linux and sys.platform != 'darwin':
        raise RuntimeError('Linux or macOS is required for the isolated worker profile.')
    # Kill the worker if the controller dies. Supervisor kills its process group
    # on normal exit/cancel; durable recovery handles a surviving group leader.
    # macOS has no parent-death signal: there an orphaned worker is bounded only
    # by RLIMIT_CPU (see docs/CONTINUATION_STATUS.md).
    if linux:
        libc = ctypes.CDLL(None, use_errno=True)
        if libc.prctl(1, signal.SIGKILL, 0, 0, 0) != 0:
            raise RuntimeError('Worker parent identity could not be established.')
    if os.getppid() != parent_pid:
        raise RuntimeError('Worker parent identity could not be established.')
    cpu_seconds = int(limits['cpu_seconds'])
    resource.setrlimit(resource.RLIMIT_CPU, (cpu_seconds, cpu_seconds + 1))
    # On macOS RLIMIT_AS is an alias of RLIMIT_RSS: the kernel rejects lowering
    # it and does not enforce RSS limits, so the memory limit is Linux-only.
    memory_limit = ((resource.RLIMIT_AS, int(limits['memory_bytes'])),) if linux else ()
    for key, value in (*memory_limit,
                       (resource.RLIMIT_FSIZE, int(limits['file_bytes'])),
                       (resource.RLIMIT_NOFILE, int(limits['open_files'])),
                       (resource.RLIMIT_CORE, 0)):
        resource.setrlimit(key, (value, value))
    os.umask(0o077)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--spec', required=True, type=Path)
    parser.add_argument('--out', required=True, type=Path)
    parser.add_argument('--receipt', required=True, type=Path)
    parser.add_argument('--limits', required=True)
    parser.add_argument('--parent', required=True, type=int)
    parser.add_argument('--no-cad', action='store_true')
    args = parser.parse_args()
    started = time.monotonic()
    code = 1
    receipt = {}
    try:
        apply_limits(json.loads(args.limits), args.parent)
        from .pipeline import reconstruct
        result = reconstruct(args.spec, args.out, export_cad=not args.no_cad)
        receipt = {'status': result['status']}
        code = 0
    except MemoryError:
        receipt = {'error_code': 'worker_memory_limit'}
    except FileExistsError:
        receipt = {'error_code': 'output_exists'}
    except BaseException as exc:
        receipt = {'error_code': 'worker_exception', 'exception_type': type(exc).__name__}
    usage = resource.getrusage(resource.RUSAGE_SELF)
    children = resource.getrusage(resource.RUSAGE_CHILDREN)
    receipt['resources'] = {'wall_seconds': round(time.monotonic() - started, 4),
                            'cpu_seconds': round(usage.ru_utime + usage.ru_stime + children.ru_utime + children.ru_stime, 4),
                            'peak_rss_kib': peak_rss_kib(usage.ru_maxrss),
                            'child_peak_rss_kib': peak_rss_kib(children.ru_maxrss),
                            'resource_profile': native_resource_profile()}
    try:
        temporary = args.receipt.with_suffix('.tmp')
        with temporary.open('x', encoding='utf-8') as stream:
            json.dump(receipt, stream, allow_nan=False); stream.flush(); os.fsync(stream.fileno())
        temporary.replace(args.receipt)
    except OSError:
        pass
    return code


if __name__ == '__main__':
    raise SystemExit(main())
