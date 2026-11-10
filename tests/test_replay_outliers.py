"""Fixed trial selection and paired baseline accounting for detector replay."""
import copy

import numpy as np
import pytest

from benchmarks.hull_fairing import replay_outliers as replay


def sample():
    return [{"id": f"s{i}", "x_m": float(i), "source_label": "read",
             "points_yz_m": [[1., float(z)] for z in np.linspace(0, 2, 41)]} for i in range(9)]


def test_trial_selection_and_injection_are_deterministic_and_preserve_input():
    source = sample()
    before = copy.deepcopy(source)
    assert replay.selected_stations(source) == ["s2", "s4"]
    changed = replay.perturb(source, "s2", .2, whole=False)
    assert changed[2]["points_yz_m"][20][0] == pytest.approx(1.2)
    assert changed[2]["points_yz_m"][0][0] == 1
    assert source == before


def test_paired_accounting_distinguishes_existing_alarm_and_collateral():
    source = sample()
    def check(rows):
        cells = []
        for row in rows:
            for index, (y, z) in enumerate(row["points_yz_m"]):
                cells.append({"station_id": row["id"], "point_index": index,
                              "y_m": y, "z_m": z, "flagged": row["id"] == "s2" and index == 20,
                              "availability": {"plan": "missing", "profile": "missing", "section": "measured"}})
        return {"cells": cells}
    row = replay.measure_trial(source, "s2", "cell_0.2m", .2, check)
    assert row["detected"] is True
    assert row["new_detected"] is False
    assert row["independent_covered"] is False
    assert row["collateral_new_alarms"] == 0


def test_station_trial_counts_any_changed_cell_and_summary_has_zero_safe_rates():
    source = sample()
    def check(rows):
        return {"cells": [{"station_id": r["id"], "point_index": i, "y_m": y, "z_m": z,
                            "flagged": y > 1.01, "availability": {"plan": "measured", "profile": "missing"}}
                           for r in rows for i, (y, z) in enumerate(r["points_yz_m"])]}
    row = replay.measure_trial(source, "s4", "station_5pct", .05, check)
    assert row["detected"] and row["new_detected"]
    assert row["independent_covered"]
    summary = replay.summarize_trials([row])
    assert summary["station_5pct"]["trials"] == 1
    assert summary["station_5pct"]["detection_rate"] == 1
    assert replay.summarize_trials([]) == {}


def test_unmeasured_build_has_explicit_missed_trials_not_invented_readings():
    rows = replay.unavailable_trials("no measured sections")
    assert len(rows) == 6
    for result in replay.summarize_trials(rows).values():
        assert result["trials"] == 2
        assert result["detection_rate"] == 0
        assert result["covered_detection_rate"] is None
