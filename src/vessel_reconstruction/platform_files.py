"""Small native filesystem boundaries; POSIX callers retain their existing controls."""
from __future__ import annotations

import ctypes
import os

_IS_WINDOWS = os.name == 'nt'
SECURE_READS_UNSUPPORTED = ('Secure descriptor-relative no-follow reads are not supported on this platform; '
                            'Windows reparse-point and relative-handle protection is not implemented.')


def require_secure_descriptor_reads() -> None:
    """Fail closed instead of substituting a racy path check for no-follow opens."""
    if _IS_WINDOWS:
        raise RuntimeError(SECURE_READS_UNSUPPORTED)

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
    kernel.MoveFileExW.argtypes = (wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD)
    kernel.MoveFileExW.restype = wintypes.BOOL
    kernel.GetFileInformationByHandleEx.argtypes = (wintypes.HANDLE, ctypes.c_int,
                                                   ctypes.c_void_p, wintypes.DWORD)
    kernel.GetFileInformationByHandleEx.restype = wintypes.BOOL
    return kernel


def _last_error() -> int:
    return ctypes.get_last_error()


def move_windows_path(source: Path, target: Path, *, replace: bool) -> None:
    """Same-volume write-through rename; never fall back to copy/delete."""
    flags = 0x8 | (0x1 if replace else 0)  # WRITE_THROUGH, optional REPLACE_EXISTING
    kernel = _kernel32()
    if not kernel.MoveFileExW(str(source.absolute()), str(target.absolute()), flags):
        error = _last_error()
        if error in (80, 183):  # FILE_EXISTS, ALREADY_EXISTS
            raise FileExistsError(error, 'Publication target already exists', str(target))
        # Some filesystems return ACCESS_DENIED for an existing directory.
        if not replace and error == 5 and os.path.lexists(target):
            raise FileExistsError(error, 'Publication target already exists', str(target))
        raise OSError(error, 'Write-through publication rename failed', str(target))


def open_windows_reservation(path: Path, *, create: bool) -> int:
    """Open a non-reparse regular reservation with deletion sharing, still locked by caller."""
    import msvcrt

    kernel = _kernel32()
    handle = kernel.CreateFileW(str(path.absolute()), _GENERIC_READ | _GENERIC_WRITE,
                               _SHARE_READ_WRITE_DELETE, None, 1 if create else _OPEN_EXISTING,
                               0x00200000, None)  # OPEN_REPARSE_POINT; CREATE_NEW when reserving
    if handle == INVALID_HANDLE_VALUE:
        error = _last_error()
        if error in (80, 183):
            raise FileExistsError(error, 'Reservation already exists', str(path))
        raise OSError(error, 'Cannot open publication reservation', str(path))
    try:
        # FileAttributeTagInfo checks the opened object, not a racy path lookup.
        attributes = (wintypes.DWORD * 2)()
        if not kernel.GetFileInformationByHandleEx(handle, 9, ctypes.byref(attributes), ctypes.sizeof(attributes)):
            raise OSError(_last_error(), 'Cannot inspect publication reservation', str(path))
        if attributes[0] & (0x400 | 0x10):  # REPARSE_POINT or DIRECTORY
            raise OSError('Publication reservation must be a non-reparse regular file')
        descriptor = msvcrt.open_osfhandle(handle, os.O_RDWR | os.O_BINARY)
    except BaseException:
        kernel.CloseHandle(handle)
        raise
    return descriptor  # CRT descriptor owns the native handle from here.


def sync_windows_file(path: Path) -> None:
    """Flush an existing file through the writable handle required by Win32.

    Unlike directory syncing, no unsupported-operation result is ignored. The
    file is never created or truncated, and ordinary sharing remains enabled.
    """
    kernel = _kernel32()
    handle = kernel.CreateFileW(str(path.absolute()), _GENERIC_READ | _GENERIC_WRITE,
                               _SHARE_READ_WRITE_DELETE, None, _OPEN_EXISTING, 0, None)
    if handle == INVALID_HANDLE_VALUE:
        raise OSError(_last_error(), 'Cannot open file for durability flush', str(path))
    try:
        if not kernel.FlushFileBuffers(handle):
            raise OSError(_last_error(), 'File durability flush failed', str(path))
    finally:
        kernel.CloseHandle(handle)


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
