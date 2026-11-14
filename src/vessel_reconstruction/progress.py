"""Small, request-bound progress records shared by the trusted worker tree.

The counter advances only at work boundaries. The two-second heartbeat updates
the timestamp without advancing the counter, so a stuck kernel call stays visible.
"""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import stat
import threading
import time
import unicodedata


MAX_PROGRESS_BYTES = 2048
# Normal CAD steps report hundreds of sections/parts and formats, not thousands.
# Bound alternating invented stages so a child cannot postpone stalls forever.
MAX_PROGRESS_ADVANCES_PER_STEP = 10_000
NO_PROGRESS_SECONDS = 300


class ProgressWatchdog:
    """Count validated work boundaries using the supervisor's monotonic clock."""
    def __init__(self):
        self.last_pair = None
        self.advances = 0
        self.last_progress = 0.0

    def update(self, elapsed, value):
        if value is not None:
            pair = (value['stage'], value['part'])
            if pair != self.last_pair and self.advances < MAX_PROGRESS_ADVANCES_PER_STEP:
                self.last_pair = pair
                self.advances += 1
                self.last_progress = elapsed
        return elapsed - self.last_progress >= NO_PROGRESS_SECONDS

    @property
    def stage(self):
        return self.last_pair[0] if self.last_pair else 'CAD work'


@contextmanager
def _record():
    name = os.environ.get('MARINAFRAME_PROGRESS_PATH')
    if not name:
        yield None, None
        return
    from .file_lock import lock_exclusive, unlock
    path = Path(name)
    # Descendants and the heartbeat use one lock so an old heartbeat cannot
    # overwrite a newer stage. These files are telemetry, never CAD receipts.
    with path.with_suffix('.lock').open('a') as lock:
        lock_exclusive(lock)
        try:
            value = json.loads(path.read_text()) if path.exists() else {}
            yield path, value
        finally:
            unlock(lock)


def _write(path, value):
    value['timestamp_ms'] = time.time_ns() // 1_000_000
    temporary = path.with_suffix(f'.{os.getpid()}.tmp')
    temporary.write_text(json.dumps(value, separators=(',', ':')))
    temporary.replace(path)


def report(stage, part=0, total=0, *, unit='part'):
    with _record() as (path, previous):
        if path is None:
            return
        _write(path, {'request_id': os.environ['MARINAFRAME_PROGRESS_REQUEST'],
                      'stage': stage, 'part': part, 'total': total, 'unit': unit,
                      'counter': max(time.monotonic_ns(), previous.get('counter', 0) + 1)})


def refresh():
    with _record() as (path, value):
        if path is not None and value:
            _write(path, value)


def read_child_progress(child_path, request_id):
    """Read untrusted telemetry without following a link or waiting on a FIFO."""
    from .platform_files import require_secure_descriptor_reads
    require_secure_descriptor_reads()
    try:
        handle = os.open(child_path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        try:
            metadata = os.fstat(handle)
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > MAX_PROGRESS_BYTES:
                return None
            data = os.read(handle, MAX_PROGRESS_BYTES + 1)
        finally:
            os.close(handle)
        if len(data) > MAX_PROGRESS_BYTES:
            return None
        value = json.loads(data)
        if type(value) is not dict or value.get('request_id') != request_id:
            return None
        stage, part, total = value.get('stage'), value.get('part'), value.get('total')
        if (type(stage) is not str or not 1 <= len(stage.encode('utf-8')) <= 120
                or any(unicodedata.category(char) == 'Cc' for char in stage)
                or value.get('unit') not in ('part', 'section', 'format')
                or type(part) is not int or type(total) is not int
                or not 0 <= part <= total <= 100_000):
            return None
        # Never copy the child's counter, timestamp or extra fields to trusted state.
        return {'request_id': request_id, 'stage': stage, 'part': part,
                'total': total, 'unit': value['unit']}
    except (OSError, ValueError, TypeError, RecursionError):
        return None


class ProgressRelay:
    """One trusted observer per supervised child, kept for the entire step."""
    def __init__(self):
        self.last_pair = None
        self.advances = 0

    def relay(self, child_path):
        if not child_path or child_path == os.environ.get('MARINAFRAME_PROGRESS_PATH'):
            return
        value = read_child_progress(child_path, os.environ.get('MARINAFRAME_PROGRESS_REQUEST'))
        if value is None:
            return
        pair = (value['stage'], value['part'])
        if pair == self.last_pair or self.advances >= MAX_PROGRESS_ADVANCES_PER_STEP:
            return
        try:
            with _record() as (path, previous):
                if path is None:
                    return
                # The destination belongs to the trusted worker tree. Only it can
                # assign a counter; untrusted input never chooses its magnitude.
                value['counter'] = previous.get('counter', 0) + 1
                _write(path, value)
        except (OSError, ValueError, TypeError):
            return  # Telemetry failure is not permission to stop or adopt CAD output.
        self.last_pair = pair
        self.advances += 1


class Heartbeat:
    def __init__(self, stage, *, interval=2.0):
        self.stage = stage
        self.interval = interval
        self.stop = threading.Event()
        self.thread = None

    def __enter__(self):
        report(self.stage)
        if os.environ.get('MARINAFRAME_PROGRESS_PATH'):
            self.thread = threading.Thread(target=self._beat, daemon=True)
            self.thread.start()
        return self

    def _beat(self):
        while not self.stop.wait(self.interval):
            refresh()

    def __exit__(self, *_):
        self.stop.set()
        if self.thread:
            self.thread.join()
