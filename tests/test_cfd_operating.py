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


def test_low_rolling_load_resets_sustained_interval():
    from vessel_reconstruction.cfd.operating import RollingLoad
    rule = RollingLoad()
    for stamp in range(0, 901, 30):
        rule.sample(stamp, 10 if stamp < 600 else 0)
    assert rule.sample(1200, 0)[1] is False
    with pytest.raises(ValueError):
        rule.sample(1190, 10)
