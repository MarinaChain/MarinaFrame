"""Small Windows process observation primitives, without PID signalling."""
import ctypes
from ctypes import wintypes


def windows_process_has_exited(pid: int) -> bool:
    """Wait on a query/synchronize handle; never treat access denial as exit."""
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
    kernel.WaitForSingleObject.restype = wintypes.DWORD
    kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel.CloseHandle.restype = wintypes.BOOL
    handle = kernel.OpenProcess(0x00100000, False, pid)  # SYNCHRONIZE only
    if not handle:
        error = ctypes.get_last_error()
        if error == 87:  # ERROR_INVALID_PARAMETER: no such PID
            return True
        if error == 5:  # ERROR_ACCESS_DENIED: liveness remains unproven
            return False
        raise OSError(error, 'Cannot observe process lifetime')
    try:
        result = kernel.WaitForSingleObject(handle, 0)
        if result == 0:
            return True
        if result == 258:  # WAIT_TIMEOUT: still running
            return False
        raise OSError(ctypes.get_last_error(), 'Cannot query process lifetime')
    finally:
        kernel.CloseHandle(handle)
