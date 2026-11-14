"""Synthetic checks for diagnostic arithmetic; no dataset dependency."""
import importlib.util
from pathlib import Path
import sys

import numpy as np
import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
spec = importlib.util.spec_from_file_location("bulb_diagnostics", SCRIPTS / "investigate_thin_ship_bulbs.py")
diag = importlib.util.module_from_spec(spec)
spec.loader.exec_module(diag)


def test_reference_zero_and_quadratic_scaling():
    x = np.linspace(0, 10, 301)
    z = np.linspace(-1, 0, 51)
    y = (1-(2*x[:, None]/10-1)**2)*(1-z[None, :]**2)
    assert diag.reference_rw(y*0, 3, x, z, 21) == 0
    first = diag.reference_rw(y, 3, x, z, 21)
    assert first > 0
    assert diag.reference_rw(2*y, 3, x, z, 21) == pytest.approx(4*first)


def test_statistics_preserves_failures_and_signed_direction():
    rows = [{"error_percent": 10, "cw": .9, "reference_cw": 1},
            {"error_percent": None, "cw": None, "reference_cw": 1}]
    result = diag.statistics(rows)
    assert result["conditions"] == 2
    assert result["finite"] == 1
    assert result["median_signed_percent"] == pytest.approx(-10)


def test_band_boundaries():
    assert diag.band(.049, (.05, .1)) == "0"
    assert diag.band(.05, (.05, .1)) == "1"
    assert diag.band(.1, (.05, .1)) == "2"
