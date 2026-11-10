"""Small, request-bound progress records shared by the trusted worker tree.

The counter advances only at work boundaries. The two-second heartbeat updates
the timestamp without advancing the counter, so a stuck kernel call stays visible.
"""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import threading
import time


@contextmanager
def _record():
    name = os.environ.get('MARINAFRAME_PROGRESS_PATH')
    if not name:
        yield None, None
        return
    import fcntl
    path = Path(name)
    # Descendants and the heartbeat use one lock so an old heartbeat cannot
    # overwrite a newer stage. These files are telemetry, never CAD receipts.
    with path.with_suffix('.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            value = json.loads(path.read_text()) if path.exists() else {}
            yield path, value
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


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


def relay(child_path):
    """Bring sandbox-local telemetry out through its existing trusted supervisor."""
    if not child_path or child_path == os.environ.get('MARINAFRAME_PROGRESS_PATH'):
        return
    try:
        with Path(child_path).open() as stream:
            value = json.loads(stream.read(2049))
        with _record() as (path, previous):
            if (path is not None and value.get('request_id') == os.environ.get('MARINAFRAME_PROGRESS_REQUEST')
                    and value.get('counter', 0) > previous.get('counter', 0)):
                _write(path, value)
    except (OSError, ValueError, TypeError):
        return  # A not-yet-written progress file is normal during worker startup.


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
