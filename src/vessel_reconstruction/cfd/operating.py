"""Time-weighted rolling estimate; Linux has no native ten-minute load."""
from collections import deque
import math


class RollingLoad:
    def __init__(self):
        self.history = deque()
        self.high_since = None

    def sample(self, timestamp, load):
        if not math.isfinite(timestamp) or not math.isfinite(load) or load < 0:
            raise ValueError('Load sample must be finite and nonnegative')
        if self.history and timestamp <= self.history[-1][0]:
            raise ValueError('Load timestamps must increase')
        self.history.append((timestamp, load))
        cutoff = timestamp - 600
        while len(self.history) > 1 and self.history[1][0] <= cutoff:
            self.history.popleft()
        if self.history[0][0] > cutoff:
            return None, False
        samples = list(self.history)
        integral = sum(value * (right - max(left, cutoff))
                       for (left, value), (right, _) in zip(samples, samples[1:]))
        rolling = integral / 600
        if rolling > 9:
            if self.high_since is None:
                self.high_since = timestamp
        else:
            self.high_since = None
        pause = self.high_since is not None and timestamp - self.high_since >= 600
        return rolling, pause


class OtherLoad:
    """PM other-load hysteresis, subtracting current rank load after averaging.

    Running own load is the fixed five-rank allocation; paused own load is zero.
    The rolling host estimate remains continuous across state transitions.
    """
    def __init__(self):
        self.host = RollingLoad()
        self.high_since = None
        self.low_since = None

    def sample(self, timestamp, load, state):
        if state not in ('running', 'paused'):
            raise ValueError('Expected running or paused lane container')
        rolling, _ = self.host.sample(timestamp, load)
        own = 5 if state == 'running' else 0
        other = None if rolling is None else rolling - own
        if other is not None and other > 9:
            if self.high_since is None:
                self.high_since = timestamp
        else:
            self.high_since = None
        if other is not None and other < 6:
            if self.low_since is None:
                self.low_since = timestamp
        else:
            self.low_since = None
        return {'rolling600': rolling, 'own_load': own, 'other_load': other,
                'pause': state == 'running' and self.high_since is not None
                         and timestamp - self.high_since >= 600,
                'resume': state == 'paused' and self.low_since is not None
                          and timestamp - self.low_since >= 600}


class ResumeLoad:
    """PM standing resume permission: rolling ten-minute load <6 for600s.

    This supplies eligibility only. The supervisor must still restrict the
    target to its own load-paused container and enforce all resource checks.
    """
    def __init__(self):
        self.rolling = RollingLoad()
        self.low_since = None

    def sample(self, timestamp, load):
        rolling, _ = self.rolling.sample(timestamp, load)
        if rolling is not None and rolling < 6:
            if self.low_since is None:
                self.low_since = timestamp
        else:
            self.low_since = None
        return self.low_since is not None and timestamp - self.low_since >= 600
