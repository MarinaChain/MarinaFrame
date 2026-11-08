"""Mark and revise: a revision edit must not worsen its own section's ink fit."""
from vessel_reconstruction.agent_tools import revision_ink_worse


def test_the_recorded_station_3_revision_is_not_kept():
    # Live run: the whole-sheet fit rose 0.1336 -> 0.1364 while station 3's ink RMS rose 1.38 -> 2.03 m.
    assert revision_ink_worse({"rms_m": 1.38}, {"rms_m": 2.03})


def test_a_small_ink_change_or_no_measured_ink_leaves_the_decision_to_the_overall_fit():
    assert not revision_ink_worse({"rms_m": 1.38}, {"rms_m": 1.40})  # within 5 %
    assert not revision_ink_worse({"rms_m": 0.20}, {"rms_m": 0.24})  # within 0.05 m
    assert not revision_ink_worse({"rms_m": 1.38}, {"rms_m": 0.90})  # better
    assert not revision_ink_worse({}, {"rms_m": 3.0})  # nothing measured before
    assert revision_ink_worse({"rms_m": 0.20}, {})  # the edit lost its ink measurement
