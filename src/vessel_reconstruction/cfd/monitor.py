"""Attach-only host supervisor; never starts or resets a CFD container.

Run on the trusted host outside the writable case mount. The PM-approved load
rule uses the current five-rank allocation as an estimate, not CPU telemetry.
"""
import csv
from datetime import datetime
import fcntl
import json
import os
import stat
from pathlib import Path
import re
import shutil
import subprocess
import time

from .operating import OtherLoad


def supervise(name, *, root=None):
    if not re.fullmatch(r'kvdb2-[a-z0-9-]+', name):
        raise ValueError('Expected exact lane-owned DB2 run name')
    root = Path.home() / 'marinaframe-cfd' if root is None else Path(root)
    attempt = root / name
    container = 'mf-cfd-' + name
    lock = (root / '.solver.lock').open('a')
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)

    def run(*args):
        return subprocess.check_output(args, text=True).strip()

    def save(path, value):
        (attempt / path).write_text(json.dumps(value, indent=2))

    def event(kind, now, **extra):
        with (attempt / 'other-load-events.jsonl').open('a') as output:
            output.write(json.dumps({'event': kind, 'epoch': now, **extra}) + '\n')

    def state_info():
        return json.loads(run('docker', 'inspect', '--format', '{{json .State}}', container))

    def prior_pauses(end):
        events = []
        for filename in ('pause-resume.jsonl', 'other-load-events.jsonl'):
            path = attempt / filename
            if path.exists():
                events.extend(json.loads(line) for line in path.read_text().splitlines() if line)
        paused_at = None
        total = 0
        for item in sorted(events, key=lambda row: row['epoch']):
            kind = item['event']
            if kind in ('pause', 'load pause'):
                paused_at = item['epoch']
            elif kind in ('load unpause', 'unpause') and paused_at is not None:
                total += item['epoch'] - paused_at
                paused_at = None
        if paused_at is not None:
            total += end - paused_at
        return total

    policy = OtherLoad()
    started = time.time()
    initial = state_info()
    container_started = datetime.fromisoformat(initial['StartedAt'].replace('Z', '+00:00')).timestamp()
    image = run('docker', 'inspect', '--format', '{{.Config.Image}}', container)
    image_bytes = int(run('docker', 'image', 'inspect', '--format', '{{.Size}}', image))
    container_id = run('docker', 'inspect', '--format', '{{.Id}}', container)
    pause_record = attempt / 'pause-authority.json'
    authority = json.loads(pause_record.read_text()) if pause_record.exists() else {}
    load_pause = (initial['Status'] == 'paused' and authority.get('container_id') == container_id
                  and authority.get('kind') == 'load' and authority.get('paused') is True)

    def pause_authority(kind, paused):
        save('pause-authority.json', {'container_id': container_id, 'kind': kind,
                                     'paused': paused, 'epoch': time.time()})
    last_resume_check = 0
    event('supervisor attached', started, state=initial['Status'])
    try:
        with (attempt / 'other-load.csv').open('a', buffering=1) as output:
            writer = csv.writer(output)
            writer.writerow(['epoch', 'state', 'load1', 'rolling600', 'own_load', 'other_load', 'free', 'used'])
            while True:
                now = time.time()
                info = state_info()
                state = info['Status']
                if state in ('exited', 'dead'):
                    break
                if state not in ('running', 'paused'):
                    raise RuntimeError('Unexpected lane container state')
                host_load = float(Path('/proc/loadavg').read_text().split()[0])
                decision = policy.sample(now, host_load, state)
                free = shutil.disk_usage(root).free
                used = int(run('du', '-sb', str(root)).split()[0])
                writer.writerow([now, state, host_load, decision['rolling600'],
                                 decision['own_load'], decision['other_load'], free, used])
                if free < 10_000_000_000 or used + image_bytes + 500_000_000 >= 39_000_000_000:
                    pause_authority('resource', True)
                    if state == 'running':
                        run('docker', 'pause', container)
                    save('other-load-resource-stop.json', {'epoch': now, 'free': free, 'used': used})
                    return
                if state == 'running' and decision['pause']:
                    pause_authority('load', True)
                    run('docker', 'pause', container)
                    load_pause = True
                    event('pause', now, reason='other_load>9 sustained600')
                if state == 'paused' and now - last_resume_check >= 600:
                    last_resume_check = now
                    event('resume eligibility check', now, other_load=decision['other_load'])
                    if load_pause and decision['resume']:
                        pause_authority('load', False)
                        run('docker', 'unpause', container)
                        event('unpause', now, reason='other_load<6 sustained600')
                        load_pause = False
                log = attempt / 'data/log.simpleFoam'
                if state == 'running' and log.exists():
                    descriptor = os.open(log, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
                    try:
                        metadata = os.fstat(descriptor)
                        if not stat.S_ISREG(metadata.st_mode):
                            raise ValueError('Solver log must be a regular file')
                        os.lseek(descriptor, max(0, metadata.st_size - 2_000_000), os.SEEK_SET)
                        text = os.read(descriptor, 2_000_000).decode(errors='replace')
                    finally:
                        os.close(descriptor)
                    completed = re.findall(r'Time = (\d+)\s*\n.*?ClockTime = ([0-9.]+) s', text, re.S)
                    if not completed and metadata.st_size >= 2_000_000:
                        raise ValueError('Bounded solver log has no complete timing record')
                    if completed and int(completed[-1][0]) >= 200:
                        iteration, clock = completed[-1]
                        active = max(0, float(clock) - prior_pauses(now))
                        projection = active / (int(iteration) - 100) * 1900
                        save('projection-other-load.json', {'iteration': int(iteration),
                             'projected_active_seconds': projection, 'paused_seconds': prior_pauses(now)})
                        if projection > 86400:
                            run('docker', 'stop', '-t', '10', container)
                            save('other-load-runtime-stop.json', {'epoch': now, 'projection': projection})
                time.sleep(30)
        now = time.time()
        paused = prior_pauses(now)
        wall = now - container_started
        save('other-load-receipt.json', {'state': 'completed' if info['ExitCode'] == 0 else 'failed',
             'exit_code': info['ExitCode'], 'wall_seconds': wall, 'paused_seconds': paused,
             'active_wall_seconds': wall - paused, 'allocated_cores': 5,
             'reserved_core_hours': wall * 5 / 3600, 'active_core_hours': (wall - paused) * 5 / 3600,
             'oom_killed': info['OOMKilled'], 'engineering_approved': False})
    except Exception:
        try:
            pause_authority('monitor-failure', True)
        finally:
            subprocess.run(['docker', 'pause', container], capture_output=True)
        raise
