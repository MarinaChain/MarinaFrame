"""Convergence selection is fixed before dataset runs."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from commission_thin_ship_gate import convergence_summary
from run_thin_ship_gate2 import select_fresh


def test_fresh_selection_is_disjoint_deterministic_and_stratified():
    old = {f"shipd-1-{i:05d}" for i in range(100)}
    excluded = {f"shipd-2-{i:05d}" for i in range(100)}
    selected = select_fresh(old, excluded)
    assert selected == select_fresh(old, excluded)
    assert len(selected) == len(set(selected)) == 300
    assert not set(selected) & (old | excluded)
    for subset in (1, 2, 3):
        assert sum(i.startswith(f"shipd-{subset}-") for i in selected) == 100


def test_select_smallest_converged_count():
    result = convergence_summary([{"161": 1.0005, "321": 1., "641": 1.}] * 10)
    assert result["selected_angle_count"] == 161


def test_no_selection_without_next_level_convergence():
    result = convergence_summary([{"161": 1.2, "321": 1.1, "641": 1.}] * 10)
    assert result["selected_angle_count"] is None


def test_missing_values_cannot_pass():
    result = convergence_summary([{"161": None, "321": None, "641": 1.}] * 10)
    assert result["selected_angle_count"] is None
    assert result["pairs"]["161_to_321"]["p90_change_percent"] is None
