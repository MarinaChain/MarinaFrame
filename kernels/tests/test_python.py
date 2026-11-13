import importlib.util
import math
import os
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location("mf_kernels", Path(__file__).parents[1] / "python/mf_kernels.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


@unittest.skipUnless(os.environ.get("MF_KERNEL_LIBRARY"), "explicit native library path required")
class BindingTests(unittest.TestCase):
    def setUp(self):
        self.kernels = module.Kernels(os.environ["MF_KERNEL_LIBRARY"])

    def test_volume(self):
        self.assertEqual(self.kernels.box_volume(2, 3, 4), 24)
        self.assertEqual(self.kernels.box_volume(0, 3, 4), 0)

    def test_invalid(self):
        for value in (-1, math.nan, math.inf, 1.7976931348623157e308):
            with self.assertRaises(ValueError):
                self.kernels.box_volume(value, 3, 4)


if __name__ == "__main__":
    if not os.environ.get("MF_KERNEL_LIBRARY"):
        raise SystemExit("MF_KERNEL_LIBRARY must name the built shared library")
    unittest.main()
