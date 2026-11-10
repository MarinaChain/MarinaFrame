"""Recommendation requires complete check cases and unchanged frozen gates."""
from benchmarks.hull_fairing import summary_three_view as module

def row(case="a", *, rms=1.7, passes=True):
    score = lambda r, p: {"rms_pct": r, "volume_pct": 0., "passes": p}
    return {"case": case, "scores": {"current": score(1.9, True), "joint": score(rms, passes)}}


def test_missing_check_case_or_lost_pass_cannot_meet_gate_targets():
    assert module.gate_targets([row()], expected_cases={"a", "b"})["T1"] is False
    assert module.gate_targets([row()], expected_cases={"a"}) == {"complete": True, "T1": True, "T2": True}
    assert module.gate_targets([row(passes=False)], expected_cases={"a"})["T2"] is False
    broken = row()
    broken["scores"]["joint"] = None
    assert module.gate_targets([broken], expected_cases={"a"})["complete"] is False
