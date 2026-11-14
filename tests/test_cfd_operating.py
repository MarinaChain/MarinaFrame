"""PM operating limits for the shared CFD host."""
import pytest


def test_rolling_load_requires_full_window_and_further_ten_minutes():
    from vessel_reconstruction.cfd.operating import RollingLoad
    rule = RollingLoad()
    assert rule.sample(0, 10) == (None, False)
    assert rule.sample(599, 10) == (None, False)
    assert rule.sample(600, 10) == (10, False)
    assert rule.sample(1199, 10) == (10, False)
    assert rule.sample(1200, 10) == (10, True)


def test_resume_requires_complete_low_window_then_further_ten_minutes():
    from vessel_reconstruction.cfd.operating import ResumeLoad
    rule = ResumeLoad()
    assert not rule.sample(0, 5)
    assert not rule.sample(600, 5)
    assert not rule.sample(1199, 5)
    assert rule.sample(1200, 5)
    assert rule.sample(1230, 30)  # Left-held sample changes the next interval.
    assert not rule.sample(1260, 30)


def test_other_load_subtracts_ranks_after_rolling_average():
    from vessel_reconstruction.cfd.operating import OtherLoad
    rule = OtherLoad()
    assert rule.sample(0, 12, 'running')['other_load'] is None
    assert rule.sample(600, 12, 'running')['other_load'] == 7
    assert not rule.sample(1200, 12, 'running')['pause']
    result = rule.sample(1230, 12, 'paused')
    assert result['other_load'] == 12  # Paused own load is zero, not five.
    assert not result['resume']
    with pytest.raises(ValueError):
        rule.sample(1260, 12, 'unknown')


def test_other_load_pause_and_resume_require_sustained_strict_thresholds():
    from vessel_reconstruction.cfd.operating import OtherLoad
    high = OtherLoad()
    high.sample(0, 15, 'running')
    assert not high.sample(600, 15, 'running')['pause']
    assert high.sample(1200, 15, 'running')['pause']
    low = OtherLoad()
    low.sample(0, 5, 'paused')
    assert not low.sample(600, 5, 'paused')['resume']
    assert low.sample(1200, 5, 'paused')['resume']
    boundary = OtherLoad()
    boundary.sample(0, 14, 'running')
    boundary.sample(600, 14, 'running')
    assert not boundary.sample(1200, 14, 'running')['pause']


def test_low_rolling_load_resets_sustained_interval():
    from vessel_reconstruction.cfd.operating import RollingLoad
    rule = RollingLoad()
    for stamp in range(0, 901, 30):
        rule.sample(stamp, 10 if stamp < 600 else 0)
    assert rule.sample(1200, 0)[1] is False
    with pytest.raises(ValueError):
        rule.sample(1190, 10)
