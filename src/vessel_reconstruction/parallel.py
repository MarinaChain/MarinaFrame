"""How many worker processes run independent pieces of work at once, and running them in order.

Each piece runs in its own supervised worker process (isolation.supervise_process), so
the threads here only wait on processes; results come back in the order of the pieces,
whatever order the processes end in.
"""
from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, Sequence, TypeVar

# Worker processes at once. Unset: the cores less RESERVED_CORES (the controller,
# the app and the system keep some), at least 1.
WORKERS_ENVIRONMENT_VARIABLE = "MARINAFRAME_WORKERS"
RESERVED_CORES = 2
# An explicit setting above this is refused (taken as unset): each worker can
# hold a full drawing in memory.
MAX_WORKERS = 32

Piece = TypeVar("Piece")
Result = TypeVar("Result")


def worker_count(pieces: int) -> int:
    """Processes for ``pieces`` independent pieces: the setting, else cores - 2; 1 to ``pieces``."""
    configured = os.environ.get(WORKERS_ENVIRONMENT_VARIABLE, "").strip()
    workers = int(configured) if configured.isdigit() and 1 <= int(configured) <= MAX_WORKERS else 0
    if not workers:
        workers = max(1, (os.cpu_count() or 1) - RESERVED_CORES)
    return max(1, min(workers, pieces))


def run_in_order(work: Callable[[Piece], Result], pieces: Sequence[Piece], workers: int) -> list[Result]:
    """``work`` on every piece, ``workers`` at once; results in the order of ``pieces``."""
    if workers <= 1 or len(pieces) <= 1:
        return [work(piece) for piece in pieces]
    with ThreadPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(work, pieces))


def split_evenly(items: Sequence[Piece], groups: int) -> list[list[Piece]]:
    """``items`` in ``groups`` contiguous groups whose sizes differ by at most one (earlier groups larger)."""
    groups = max(1, min(groups, len(items)))
    size, extra = divmod(len(items), groups)
    result, start = [], 0
    for index in range(groups):
        stop = start + size + (1 if index < extra else 0)
        result.append(list(items[start:stop]))
        start = stop
    return result
