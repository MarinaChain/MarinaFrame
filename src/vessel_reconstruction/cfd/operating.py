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
