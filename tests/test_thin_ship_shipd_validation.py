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


def test_public_summary_omits_hull_ids_and_keeps_aggregate_diagnostics():
    assert hasattr(validation, "public_summary")
    records = [{"id": "synthetic", "cw": 1.0, "error_percent": 2.0,
                "elapsed_ms": 7.0, "generated_wl_m": 10.0, "published_wl_m": 10.001,
                "draft_fraction": 0.5, "fn": 0.3}]
    summary = {"primary": {"gate_pass": False}, "convergence": [
        {"id": "synthetic", "fn": 0.3, "cw": 1.01}]}
    result = validation.public_summary(summary, records)
    assert "synthetic" not in str(result)
    assert result["primary"] == {"gate_pass": False}
    assert result["convergence_9_conditions_percent"]["median"] == pytest.approx(1.0)
    assert result["diagnostics"]["median_evaluation_ms"] == 7.0


def test_selected_rows_does_not_parse_unselected_values(tmp_path):
    path = tmp_path / "rows.csv"
    path.write_text("a,b\nnot-a-number,unselected\n2,3\n")
    assert validation.selected_rows(path, {1})[1].tolist() == [2.0, 3.0]
    with pytest.raises(ValueError, match="Selected rows missing"):
        validation.selected_rows(path, {2})


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
