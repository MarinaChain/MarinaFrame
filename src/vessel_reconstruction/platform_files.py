"""Small native filesystem boundaries; POSIX callers retain their existing controls."""
from __future__ import annotations

import ctypes
from ctypes import wintypes
from pathlib import Path

INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
_GENERIC_READ = 0x80000000
_GENERIC_WRITE = 0x40000000
_SHARE_READ_WRITE_DELETE = 0x00000007
_OPEN_EXISTING = 3
_FILE_FLAG_BACKUP_SEMANTICS = 0x02000000
# Directory flush is not a portable Win32 guarantee. Common filesystems reject
# it with INVALID_FUNCTION, ACCESS_DENIED (no writable directory handles), or
# NOT_SUPPORTED. File contents are still fsynced before publication. We cannot
# promise POSIX directory-entry crash durability on those filesystems.
_UNSUPPORTED_DIRECTORY_FLUSH = {1, 5, 50}


def _kernel32():
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateFileW.argtypes = (wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                  ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD,
                                  wintypes.HANDLE)
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.FlushFileBuffers.argtypes = (wintypes.HANDLE,)
    kernel.FlushFileBuffers.restype = wintypes.BOOL
    kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel.CloseHandle.restype = wintypes.BOOL
    return kernel


def _last_error() -> int:
    return ctypes.get_last_error()


def sync_windows_directory(path: Path) -> None:
    """Attempt a directory flush; documented no-op only where Win32 rejects it.

    Backup semantics permit opening a directory, not bypassing its ACL. Open
    failures and unexpected flush errors propagate. No volume-wide flush or
    administrator access is requested. POSIX uses its unchanged fsync path.
    """
    kernel = _kernel32()
    handle = kernel.CreateFileW(str(path.absolute()), _GENERIC_READ | _GENERIC_WRITE,
                               _SHARE_READ_WRITE_DELETE, None, _OPEN_EXISTING,
                               _FILE_FLAG_BACKUP_SEMANTICS, None)
    if handle == INVALID_HANDLE_VALUE:
        error = _last_error()
        if error == 5:
            # Windows commonly disallows GENERIC_WRITE on directories. Prove
            # that the directory can still be opened before accepting this
            # documented absence of a directory flush API. Other ACL failures
            # remain errors, not a successful no-op.
            handle = kernel.CreateFileW(str(path.absolute()), _GENERIC_READ,
                                       _SHARE_READ_WRITE_DELETE, None, _OPEN_EXISTING,
                                       _FILE_FLAG_BACKUP_SEMANTICS, None)
            if handle != INVALID_HANDLE_VALUE:
                kernel.CloseHandle(handle)
                return
            error = _last_error()
        raise OSError(error, 'Cannot open directory for durability flush', str(path))
    try:
        if not kernel.FlushFileBuffers(handle):
            error = _last_error()
            if error not in _UNSUPPORTED_DIRECTORY_FLUSH:
                raise OSError(error, 'Directory durability flush failed', str(path))
    finally:
        kernel.CloseHandle(handle)
