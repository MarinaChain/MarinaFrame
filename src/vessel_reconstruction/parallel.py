"""Worker processes for independent pieces of work: how many, a machine-wide pool, and order.

Each piece runs in its own supervised worker process (isolation.supervise_process), so
the threads here only wait on processes; results come back in the order of the pieces,
whatever order the processes end in.

The worker pool (``worker_tokens``) shares max(1, cores - RESERVED_CORES) worker processes
between every inspection running on the machine, whichever controller, app or script runs
it: a lone run gets all of them, concurrent runs share them. A token is an exclusive
``flock`` on one file of a private folder in the user's home cache, where other users cannot
create files. The kernel drops the lock when its process ends, so the tokens of a crashed
run come back at once; nothing expires on a clock. When the folder cannot be used safely,
the run works without the shared limit (its own bound) and says so in the log; the pool
never makes an inspection fail.
"""
from __future__ import annotations

import fcntl
import logging
import os
import pwd
import stat
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
from typing import Callable, Iterator, Sequence, TypeVar

# Worker processes at once. Unset: the cores less RESERVED_CORES (the controller,
# the app and the system keep some), at least 1.
WORKERS_ENVIRONMENT_VARIABLE = "MARINAFRAME_WORKERS"
RESERVED_CORES = 2
# An explicit setting above this is refused (taken as unset): each worker can
# hold a full drawing in memory.
MAX_WORKERS = 32
# The pool folder, under the user's home cache (other users cannot create files there).
# The home comes from the password database, not HOME or XDG_RUNTIME_DIR: the controller
# clears the worker environment, and every process of the user must find the same pool.
MACOS_POOL_FOLDER = "Library/Caches/io.marinachain.marinaframe/worker-pool"
OTHER_POOL_FOLDER = ".cache/marinaframe/worker-pool"
# Tests move the pool to their own folder with this variable.
POOL_DIRECTORY_ENVIRONMENT_VARIABLE = "MARINAFRAME_WORKER_POOL_DIR"
# How often a run that holds no token looks for a free one (seconds).
POOL_POLL_SECONDS = 0.025

Piece = TypeVar("Piece")
Result = TypeVar("Result")


def worker_count(pieces: int, workers: int | None = None) -> int:
    """Most processes for ``pieces`` independent pieces, 1 to ``pieces``.

    ``workers`` is the caller's bound (the controller passes the app setting). Without it:
    MARINAFRAME_WORKERS (command-line scripts), else the pool size.
    """
    if workers is not None and 1 <= workers <= MAX_WORKERS:
        return max(1, min(workers, pieces))
    configured = os.environ.get(WORKERS_ENVIRONMENT_VARIABLE, "").strip()
    workers = int(configured) if configured.isdigit() and 1 <= int(configured) <= MAX_WORKERS else 0
    return max(1, min(workers or pool_size(), pieces))


def pool_size() -> int:
    """Tokens of the machine-wide worker pool: max(1, cores - RESERVED_CORES)."""
    return max(1, (os.cpu_count() or 1) - RESERVED_CORES)


def pool_directory() -> Path:
    """The user's pool folder: created with mode 0700; never a link, another user's or a shared folder.

    Raises PermissionError (or another OSError) when the folder cannot be used safely.
    """
    configured = os.environ.get(POOL_DIRECTORY_ENVIRONMENT_VARIABLE)
    if configured:
        folder = Path(configured)
    else:
        home = Path(pwd.getpwuid(os.getuid()).pw_dir)
        folder = home / (MACOS_POOL_FOLDER if sys.platform == "darwin" else OTHER_POOL_FOLDER)
        folder.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        folder.mkdir(mode=0o700)
    except FileExistsError:
        pass
    info = os.lstat(folder)
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise PermissionError("The worker pool folder is not a private folder of this user.")
    return folder


def _open_token(folder: Path, index: int) -> int:
    descriptor = os.open(folder / f"token-{index}.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    if not stat.S_ISREG(os.fstat(descriptor).st_mode):
        os.close(descriptor)
        raise PermissionError("A worker pool token is not a regular file.")
    return descriptor


def _take_free_tokens(folder: Path, size: int, wanted: int) -> list[int]:
    """Lock up to ``wanted`` free tokens now; return their descriptors (maybe none).

    On an unusable token file (OSError) the tokens taken so far are given back and the
    error is raised.
    """
    held = []
    try:
        for index in range(size):
            if len(held) == wanted:
                break
            descriptor = _open_token(folder, index)
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                os.close(descriptor)
                continue
            held.append(descriptor)
    except OSError:
        for descriptor in held:
            os.close(descriptor)
        raise
    return held


def _unshared(wanted: int, error: OSError) -> int:
    """The worker count of a run that cannot use the pool: its own bound, logged."""
    logging.getLogger(__name__).warning(
        "Worker pool not used (%s); this inspection uses %d workers without the shared limit.",
        type(error).__name__, wanted)
    return wanted


@contextmanager
def worker_tokens(wanted: int, cancel_event=None, *, size: int | None = None,
                  wait: bool = True) -> Iterator[int]:
    """Hold up to ``wanted`` tokens of the machine-wide pool; yield how many (at least 1).

    Takes every free token up to ``wanted``; waits while none is free (``wait=False``
    yields 0 instead). A set ``cancel_event`` stops the wait with InterruptedError. The
    tokens go back when the block ends, or when this process ends. When the pool folder
    or a token file cannot be used safely, it yields ``wanted`` without tokens (the run's
    own bound, without the shared limit) and logs a warning: the pool never fails a run.
    """
    size = size or pool_size()
    wanted = max(1, min(wanted, size))
    held: list[int] = []
    try:
        folder = pool_directory()
        held = _take_free_tokens(folder, size, wanted)
        while not held and wait:
            if cancel_event is not None and cancel_event.is_set():
                raise InterruptedError("Cancelled while waiting for a worker.")
            time.sleep(POOL_POLL_SECONDS)
            held = _take_free_tokens(folder, size, wanted)
    except InterruptedError:
        raise  # cancellation (an OSError subclass) is not a pool fault
    except OSError as error:
        yield _unshared(wanted, error)
        return
    try:
        yield len(held)
    finally:
        for descriptor in held:
            os.close(descriptor)  # closing the only descriptor drops its lock


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
