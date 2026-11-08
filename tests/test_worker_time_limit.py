"""The worker time limit counts CPU time, so results do not depend on machine load."""
import os
import sys
from dataclasses import replace

import pytest

from vessel_reconstruction import isolation as I

LIMITS = replace(I.DEFAULT_LIMITS, wall_seconds=10, cpu_seconds=8)


def test_a_slow_worker_on_a_busy_machine_keeps_running():
    # 15 s of wall time, but only 4 s of CPU time: the machine was busy.
    assert not I.wall_limit_reached(15, LIMITS, lambda: 4.0)


def test_a_worker_that_used_its_budget_times_out():
    assert I.wall_limit_reached(15, LIMITS, lambda: 10.5)


def test_a_stalled_worker_times_out_at_the_stall_limit():
    assert I.wall_limit_reached(I.STALL_WALL_FACTOR * 10, LIMITS, lambda: 0.1)


def test_unknown_cpu_time_keeps_the_wall_limit():
    assert I.wall_limit_reached(10, LIMITS, lambda: None)


def test_cpu_time_is_not_read_before_the_wall_limit():
    def fail():
        raise AssertionError("read too early")
    assert not I.wall_limit_reached(9.9, LIMITS, fail)


@pytest.mark.parametrize("text, seconds", [("0:01.50", 1.5), ("01:02:03", 3723.0), ("1-00:00:02", 86402.0)])
def test_ps_time_field(text, seconds):
    assert I._ps_time_seconds(text) == pytest.approx(seconds)


@pytest.mark.skipif(sys.platform not in ("linux", "darwin"), reason="POSIX ps")
def test_group_cpu_seconds_reads_this_process_group():
    sum(i * i for i in range(300_000))  # use a little CPU time
    used = I.group_cpu_seconds(os.getpgid(0))
    assert used is None or used >= 0.0
