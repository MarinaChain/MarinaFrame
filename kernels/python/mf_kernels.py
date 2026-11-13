"""Explicit-path ctypes binding to the neutral sample C ABI."""
import ctypes
from pathlib import Path


class Kernels:
    def __init__(self, library_path):
        self._library = ctypes.CDLL(str(Path(library_path).resolve(strict=True)))
        self._volume = self._library.mf_box_volume
        self._volume.argtypes = [ctypes.c_double, ctypes.c_double, ctypes.c_double,
                                 ctypes.POINTER(ctypes.c_double)]
        self._volume.restype = ctypes.c_int

    def box_volume(self, length_m, breadth_m, depth_m):
        result = ctypes.c_double()
        if self._volume(length_m, breadth_m, depth_m, ctypes.byref(result)) != 0:
            raise ValueError("dimensions must be finite, nonnegative and not overflow")
        return result.value
