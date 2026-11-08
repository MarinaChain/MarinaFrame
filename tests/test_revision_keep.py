"""Mark and revise: a revision edit must not worsen its own section's ink fit.

Also: a bug inside one tool call is refused and undone instead of ending the run
(the series60-3v-L0 sheet-only run ended with worker_receipt_missing on one).
"""
from vessel_reconstruction.agent_tools import revision_ink_worse


def test_a_tool_bug_is_undone_and_refused_not_fatal(tmp_path):
    from test_mirrored_half import _overlay_drawing
    from vessel_reconstruction.agent_tools import DomainTools
    source = tmp_path / "src"
    source.mkdir()
    _overlay_drawing(source)
    task = tmp_path / "task"
    task.mkdir()
    domain = DomainTools(task, source / "spec.json")
    before = domain.state_path.read_bytes()

    def broken(**_):
        domain.state["half_written"] = True
        domain._save()
        return None.get("x")  # AttributeError, as the null station_ink_fit entry raised

    domain._view_region = broken
    result = domain.execute("view_region", {"region_px": [0, 0, 100, 100]})
    assert result["ok"] is False and result["status"] == "tool_failed"
    assert result["exception_type"] == "AttributeError"
    assert domain.state_path.read_bytes() == before and "half_written" not in domain.state


def test_the_recorded_station_3_revision_is_not_kept():
    # Live run: the whole-sheet fit rose 0.1336 -> 0.1364 while station 3's ink RMS rose 1.38 -> 2.03 m.
    assert revision_ink_worse({"rms_m": 1.38}, {"rms_m": 2.03})


def test_a_small_ink_change_or_no_measured_ink_leaves_the_decision_to_the_overall_fit():
    assert not revision_ink_worse({"rms_m": 1.38}, {"rms_m": 1.40})  # within 5 %
    assert not revision_ink_worse({"rms_m": 0.20}, {"rms_m": 0.24})  # within 0.05 m
    assert not revision_ink_worse({"rms_m": 1.38}, {"rms_m": 0.90})  # better
    assert not revision_ink_worse({}, {"rms_m": 3.0})  # nothing measured before
    assert revision_ink_worse({"rms_m": 0.20}, {})  # the edit lost its ink measurement
