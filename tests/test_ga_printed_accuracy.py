"""The accuracy of the GA measuring pass against printed values (scripts/ga_printed_accuracy.py).

Synthetic data only; no model is called and no partner drawing is used.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _script():
    spec = importlib.util.spec_from_file_location("ga_printed_accuracy", ROOT / "scripts" / "ga_printed_accuracy.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_a_printed_hatch_size_is_compared_with_the_measured_box_not_with_itself():
    accuracy = _script()
    arrangement = {"spaces": [
        {"id": "h1", "kind": "cargo_hatch", "extent": {
            "x_m": [10.46, 25.94], "y_m": [-10.3, 10.3], "printed_size": "15.480 x 20.600",
            "measured_box_m": {"x_m": [10.0, 26.4], "y_m": [-11.0, 11.0]}}},
        {"id": "h2", "kind": "cargo_hatch", "extent": {"x_m": [40.0, 56.4], "y_m": [-11.0, 11.0]}},  # no printed size
        {"id": "t1", "kind": "ballast_tank", "extent": {"x_m": [0.0, 10.0], "printed_size": "x",
                                                        "measured_box_m": {"x_m": [0.0, 9.0]}}}]}
    rows = accuracy.printed_rows(arrangement, "S-1")
    assert [(r["kind"], r["printed_m"], r["measured_m"]) for r in rows] == [
        ("hatch length", 15.48, 16.4), ("hatch breadth", 20.6, 22.0)]


def test_a_printed_frame_spacing_is_compared_with_what_its_frame_numbers_show():
    accuracy = _script()
    # 8 px a frame at 10 px a metre: the numbers show 800 mm; frames 50-100 are drawn at 820 mm.
    ticks = [(frame, 100 + 8.0 * frame) for frame in range(0, 51, 5)]
    ticks += [(frame, 100 + 8.0 * 50 + 8.2 * (frame - 50)) for frame in range(55, 101, 5)]
    spans = [{"from_frame": 0, "to_frame": 50, "spacing_mm": 800.0},
             {"from_frame": 50, "to_frame": 100, "spacing_mm": 800.0},
             {"from_frame": 100, "to_frame": 102, "spacing_mm": 1200.0}]  # too few numbers: left out
    rows = accuracy.spacing_rows(ticks, spans, 10.0, "S-1")
    assert [(r["printed_m"], r["measured_m"]) for r in rows] == [(0.8, 0.8), (0.8, 0.82)]


def test_the_summary_gives_count_median_worst_and_shares_within_limits():
    accuracy = _script()
    rows = [{"kind": "hatch length", "printed_m": 10.0, "measured_m": value} for value in (10.05, 10.3, 11.0, 12.0)]
    table = accuracy.summary(rows)["hatch length"]
    assert table["count"] == 4 and table["median_m"] == pytest.approx(0.65) and table["worst_m"] == 2.0
    assert (table["within_0.1_m"], table["within_0.5_m"], table["within_1.0_m"]) == (1, 2, 3)
    assert table["worst_pct"] == 20.0



def test_a_hold_with_a_printed_span_is_compared_through_its_measured_box():
    accuracy = _script()
    arrangement = {"spaces": [{"id": "h", "kind": "cargo_hold", "extent": {
        "x_m": [33.3, 61.3], "printed_span": "28000", "measured_box_m": {"x_m": [32.0, 62.6]}}}]}
    assert [(r["kind"], r["printed_m"], r["measured_m"]) for r in accuracy.printed_rows(arrangement, "S-1")] == [
        ("hold length", 28.0, 30.6)]
