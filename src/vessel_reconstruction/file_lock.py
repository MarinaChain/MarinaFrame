"""Exclusive, non-waiting file locks that behave the same on macOS, Linux and Windows.

The run transaction and the domain tools take a lock on a small lock file so that two processes
never change the same run at once. On POSIX this is `fcntl.flock`; Windows has no `fcntl`, so it
uses `msvcrt.locking` on the first byte of the file. In both cases a lock that another process
holds raises `BlockingIOError` at once (the callers turn that into "already running").
"""
from __future__ import annotations

import os
from typing import IO, Union

FileOrDescriptor = Union[int, IO]

if os.name == 'nt':
    import msvcrt

    # msvcrt locks a byte range from the current file position; one byte at offset 0 is enough,
    # because every caller locks a whole lock file and never its content.
    _LOCKED_BYTES = 1

    def _descriptor(target: FileOrDescriptor) -> int:
        return target if isinstance(target, int) else target.fileno()

    def try_lock_exclusive(target: FileOrDescriptor) -> None:
        """Take an exclusive lock now, or raise BlockingIOError if another process holds it."""
        descriptor = _descriptor(target)
        os.lseek(descriptor, 0, os.SEEK_SET)
        try:
            msvcrt.locking(descriptor, msvcrt.LK_NBLCK, _LOCKED_BYTES)
        except OSError as exc:
            raise BlockingIOError(str(exc)) from exc

    def unlock(target: FileOrDescriptor) -> None:
        descriptor = _descriptor(target)
        os.lseek(descriptor, 0, os.SEEK_SET)
        msvcrt.locking(descriptor, msvcrt.LK_UNLCK, _LOCKED_BYTES)
else:
    import fcntl

    def try_lock_exclusive(target: FileOrDescriptor) -> None:
        """Take an exclusive lock now, or raise BlockingIOError if another process holds it."""
        fcntl.flock(target, fcntl.LOCK_EX | fcntl.LOCK_NB)

    def unlock(target: FileOrDescriptor) -> None:
        fcntl.flock(target, fcntl.LOCK_UN)
