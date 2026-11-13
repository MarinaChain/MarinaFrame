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


def test_low_rolling_load_resets_sustained_interval():
    from vessel_reconstruction.cfd.operating import RollingLoad
    rule = RollingLoad()
    for stamp in range(0, 901, 30):
        rule.sample(stamp, 10 if stamp < 600 else 0)
    assert rule.sample(1200, 0)[1] is False
    with pytest.raises(ValueError):
        rule.sample(1190, 10)
