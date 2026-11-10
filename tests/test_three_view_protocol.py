"""The three-view split and targets must be fixed before measurement."""
import json
from pathlib import Path


def test_protocol_keeps_all_readings_in_their_case_and_freezes_targets():
    protocol = json.loads(Path("benchmarks/hull_fairing/three_view_protocol.json").read_text())
    fit, check = set(protocol["fit_cases"]), set(protocol["check_cases"])
    assert len(fit) == 5 and len(check) == 6
    assert not fit & check
    assert {case[:-1] + "1" for case in fit} == check - {"bue_girl"}
    assert all(case.endswith("-L0") for case in fit)
    assert protocol["plan_weight_candidates"] == [0.5, 2.0, 8.0]
    targets = protocol["targets"]
    assert targets["cell_0.1m_max_follow_share"] == targets["cell_0.2m_max_follow_share"] == 0.25
    assert targets["station_5pct_max_follow_share"] == 0.6
    assert targets["max_rms_regression_points"] == 0.1
    assert targets["max_volume_regression_points"] == 0.5
