"""Synthetic contract tests; no dataset or excluded geometry is loaded."""
import importlib.util
from pathlib import Path

import numpy as np
import pytest

SPEC = importlib.util.spec_from_file_location(
    "shipd_validation", Path(__file__).parents[1] / "scripts/validate_thin_ship_shipd.py")
validation = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(validation)


def test_selection_is_deterministic_and_excludes_ids():
    excluded = {"shipd-1-00003", "shipd-1-00007"}
    selected = validation.select_ids(1, 20, excluded, size=10)
    assert selected == validation.select_ids(1, 20, excluded, size=10)
    assert len(set(selected)) == 10
    assert not set(selected) & excluded
    with pytest.raises(ValueError):
        validation.select_ids(1, 3, excluded, size=4)


def test_reference_conversion_uses_loa_squared():
    assert hasattr(validation, "cw_from_rw")
    assert validation.cw_from_rw(100, 2, 10) == pytest.approx(0.0005)


def test_fixed_denominator_keeps_failures_and_missing_conditions():
    assert hasattr(validation, "summarize_errors")
    result = validation.summarize_errors([1.0, 2.0, None], expected=4)
    assert result["conditions"] == 4
    assert result["finite_conditions"] == 2
    assert result["median_percent"] is None
    assert result["p90_percent"] is None
    assert result["gate_pass"] is False


def test_gate_boundaries_and_invalid_reference():
    assert hasattr(validation, "relative_error")
    assert validation.relative_error(1.03, 1) == pytest.approx(3)
    assert validation.relative_error(1, 0) is None
    assert validation.relative_error(float("nan"), 1) is None
    result = validation.summarize_errors([3.0] * 10, expected=10)
    assert result["gate_pass"] is True


def test_offsets_preserve_open_ends_as_unsupported():
    assert hasattr(validation, "evaluate_offsets")
    x = np.linspace(0, 10, 5)
    z = np.linspace(-1, 0, 3)
    y = np.ones((5, 3))
    result = validation.evaluate_offsets(x, z, y, 10, 10, 0.3)
    assert result["cw"] is None
    assert "closed ends" in result["error"]
    y[[0, -1]] = 0
    result = validation.evaluate_offsets(x, z, y, 10, 10, 0.3)
    assert result["cw"] > 0
    y[1, 1] = -0.1
    assert "nonnegative" in validation.evaluate_offsets(x, z, y, 10, 10, 0.3)["error"]
