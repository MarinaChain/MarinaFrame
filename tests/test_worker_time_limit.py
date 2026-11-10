"""Supervisors count validated work boundaries, never a child's heartbeat."""
from vessel_reconstruction import progress


def record(part=0, **changes):
    return {'stage': 'Making the mesh', 'part': part, 'counter': 1, 'timestamp_ms': 1} | changes


def test_work_boundaries_reset_the_stall_clock():
    watch = progress.ProgressWatchdog()
    assert not watch.update(0, record())
    assert watch.update(300, record(counter=999, timestamp_ms=300_000))
    assert not watch.update(301, record(part=1))
    assert not watch.update(600, record(part=1))
    assert watch.update(601, record(part=1))


def test_missing_or_invalid_records_cannot_hide_a_stall():
    watch = progress.ProgressWatchdog()
    assert not watch.update(299, None)
    assert watch.update(300, None)
    assert watch.stage == 'CAD work'


def test_child_cannot_refill_the_advance_budget(monkeypatch):
    monkeypatch.setattr(progress, 'MAX_PROGRESS_ADVANCES_PER_STEP', 3)
    watch = progress.ProgressWatchdog()
    for part in range(3):
        assert not watch.update(part, record(part))
    assert watch.update(302, record(3))
    assert watch.advances == 3
    assert watch.last_pair == ('Making the mesh', 2)
