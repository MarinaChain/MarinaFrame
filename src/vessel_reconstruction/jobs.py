"""Bounded durable single-user local queue. No distributed scheduler is implied."""
from __future__ import annotations

import fcntl
import hashlib
import json
import logging
import os
from pathlib import Path
import re
import shutil
import sqlite3
import threading
import time
from uuid import uuid4

from .isolation import DEFAULT_LIMITS, WorkerLimits, _tree_bytes, kill_process_tree, recover_worker_output, run_isolated
from .resources import DEFAULT_POLICY, source_extension

LOG = logging.getLogger(__name__)
TERMINAL = {'succeeded', 'blocked', 'failed', 'cancelled', 'timed_out', 'resource_limited', 'interrupted'}
ACTIVE = {'receiving', 'queued', 'running'}


class AdmissionError(ValueError):
    def __init__(self, message: str, status: int = 429, code: str = 'queue_full'):
        super().__init__(message)
        self.status, self.code = status, code


def atomic_json(path: Path, value: dict) -> None:
    temporary = path.with_name(path.name + '.tmp-' + uuid4().hex)
    try:
        with temporary.open('x', encoding='utf-8') as stream:
            json.dump(value, stream, allow_nan=False, sort_keys=True)
            stream.flush(); os.fsync(stream.fileno())
        temporary.replace(path)
        descriptor = os.open(path.parent, os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    finally:
        temporary.unlink(missing_ok=True)


class JobQueue:
    def __init__(self, artifacts: Path, *, limits: WorkerLimits = DEFAULT_LIMITS,
                 max_pending: int = 4, max_disk_bytes: int = 2 * 1024**3,
                 min_free_bytes: int = 256 * 1024**2, receiving_seconds: float = 120,
                 input_retention_seconds: float = 24 * 3600, start_worker: bool = True):
        self.artifacts = Path(artifacts).resolve()
        self.artifacts.mkdir(parents=True, exist_ok=True)
        self.private = self.artifacts / '.workbench'
        if self.private.is_symlink():
            raise ValueError('Queue state cannot be a symbolic link')
        self.private.mkdir(mode=0o700, exist_ok=True)
        os.chmod(self.private, 0o700)
        self.inputs = self.private / 'inputs'
        self.inputs.mkdir(mode=0o700, exist_ok=True)
        self.runs = self.artifacts / 'runs'; self.runs.mkdir(exist_ok=True)
        for directory in (self.inputs, self.runs):
            if directory.is_symlink():
                raise ValueError('Queue directories cannot be symbolic links')
        self.limits, self.max_pending = limits, max_pending
        self.max_disk_bytes, self.min_free_bytes = max_disk_bytes, min_free_bytes
        self.receiving_seconds, self.input_retention_seconds = receiving_seconds, input_retention_seconds
        self.lock = threading.RLock()
        self.wake, self.stop = threading.Event(), threading.Event()
        self.cancel_events: dict[str, threading.Event] = {}
        self.last_tick = time.time(); self.last_error = None
        self._lock_file = (self.private / 'controller.lock').open('a+b')
        try:
            fcntl.flock(self._lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            self._lock_file.close()
            raise RuntimeError('Another local workbench already owns this artifact root')
        try:
            self.db = sqlite3.connect(self.private / 'jobs.sqlite3', check_same_thread=False, timeout=3)
            self.db.execute('PRAGMA journal_mode=WAL')
            self.db.execute('PRAGMA synchronous=FULL')
            if self.db.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
                raise RuntimeError('Queue state failed its SQLite integrity check; restore a backup')
            self.db.execute('CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, state TEXT NOT NULL, created REAL NOT NULL, updated REAL NOT NULL, data TEXT NOT NULL, idempotency TEXT UNIQUE, fingerprint TEXT NOT NULL)')
            self.db.execute('CREATE TABLE IF NOT EXISTS events (seq INTEGER PRIMARY KEY, job_id TEXT NOT NULL, at REAL NOT NULL, state TEXT NOT NULL, code TEXT)')
            self.db.commit()
            os.chmod(self.private / 'jobs.sqlite3', 0o600)
            self._recover()
        except BaseException:
            if hasattr(self, 'db'):
                self.db.close()
            self._lock_file.close()
            raise
        self.maintenance_thread = threading.Thread(target=self._maintenance_loop, name='marinaframe-maintenance', daemon=True)
        self.thread = threading.Thread(target=self._loop, name='marinaframe-queue', daemon=True)
        self.worker_enabled = start_worker
        if start_worker:
            self.thread.start()
            self.maintenance_thread.start()

    @staticmethod
    def _public(job: dict) -> dict:
        allowed = ('id', 'state', 'created', 'updated', 'started', 'finished', 'elapsed_seconds', 'queued_seconds',
                   'result_status', 'run_path', 'error_code', 'resources', 'received', 'cancel_requested', 'publication_reconciled', 'worker_state')
        return {name: job[name] for name in allowed if name in job}

    def _get(self, job_id: str) -> dict | None:
        row = self.db.execute('SELECT data FROM jobs WHERE id=?', (job_id,)).fetchone()
        return json.loads(row[0]) if row else None

    def get(self, job_id: str, *, internal: bool = False) -> dict | None:
        with self.lock:
            job = self._get(job_id)
            return job if internal or job is None else self._public(job)

    def _save(self, job: dict, *, event: bool = False) -> None:
        job['updated'] = time.time()
        self.db.execute('UPDATE jobs SET state=?,updated=?,data=? WHERE id=?',
                        (job['state'], job['updated'], json.dumps(job, allow_nan=False), job['id']))
        if event:
            self.db.execute('INSERT INTO events(job_id,at,state,code) VALUES (?,?,?,?)',
                            (job['id'], job['updated'], job['state'], job.get('error_code')))
            LOG.info(json.dumps({'event': 'job_state', 'job_id': job['id'], 'state': job['state'], 'error_code': job.get('error_code')}))
        self.db.commit()

    def _recover(self) -> None:
        for (raw,) in self.db.execute("SELECT data FROM jobs WHERE state IN ('running','receiving')").fetchall():
            job = json.loads(raw)
            if job['state'] == 'running':
                kill_process_tree(job.get('process'))
                recover_worker_output(self.runs / job['id'])
            job.update(state='interrupted', error_code='controller_restarted', finished=time.time())
            self._save(job, event=True)
        self.maintain()

    def _admit(self, reserve_bytes: int) -> None:
        count = self.db.execute("SELECT COUNT(*) FROM jobs WHERE state IN ('receiving','queued','running')").fetchone()[0]
        if count >= self.max_pending:
            raise AdmissionError('The local job queue is full; wait for a job or cancel one.')
        if self.db.execute('SELECT COUNT(*) FROM jobs').fetchone()[0] >= 2000:
            raise AdmissionError('Local job history reached its 2,000-record limit; archive this artifact root.', 507, 'history_limit')
        pending_reservations = 0
        for (raw,) in self.db.execute("SELECT data FROM jobs WHERE state IN ('receiving','queued','running')"):
            pending_reservations += json.loads(raw).get('reserved_bytes', 0)
        # Conservative: count reservations in addition to bytes already received.
        required = reserve_bytes + pending_reservations
        used = _tree_bytes(self.artifacts, stop_after=self.max_disk_bytes)
        if used + required > self.max_disk_bytes or shutil.disk_usage(self.artifacts).free - required < self.min_free_bytes:
            raise AdmissionError('Local disk admission budget is exhausted; archive completed runs or free disk space.', 507, 'disk_budget')

    def reserve(self, spec: dict, sources: dict, *, idempotency_key: str | None = None) -> tuple[dict, bool]:
        if not isinstance(spec, dict) or not isinstance(sources, dict) or 'primary' not in sources or set(sources) - {'primary', 'reference'}:
            raise ValueError('A specification and primary source descriptor are required')
        if spec.get('station_reference') is not None:
            if not isinstance(spec['station_reference'], dict) or 'reference' not in sources:
                raise ValueError('This specification requires an uploaded station-reference document; local paths are not accepted')
        elif 'reference' in sources:
            raise ValueError('A reference upload requires station_reference settings')
        if not isinstance(spec.get('source'), dict):
            raise ValueError('source must be an object')
        total = 0
        for role, descriptor in sources.items():
            maximum = DEFAULT_POLICY.source_bytes if role == 'primary' else DEFAULT_POLICY.reference_bytes
            if not isinstance(descriptor, dict) or set(descriptor) != {'bytes', 'sha256'}:
                raise ValueError('Source descriptors require bytes and sha256 only')
            size, digest = descriptor['bytes'], descriptor['sha256']
            if isinstance(size, bool) or not isinstance(size, int) or not 0 < size <= maximum:
                raise AdmissionError('Source exceeds the configured upload byte limit', 413, 'upload_too_large')
            if not isinstance(digest, str) or not re.fullmatch('[a-f0-9]{64}', digest):
                raise ValueError('Source sha256 must be 64 lowercase hexadecimal characters')
            total += size
        if idempotency_key is not None and (not isinstance(idempotency_key, str) or not re.fullmatch('[A-Za-z0-9_-]{8,128}', idempotency_key)):
            raise ValueError('Idempotency-Key must contain 8..128 ASCII letters, digits, underscores or hyphens')
        fingerprint = hashlib.sha256(json.dumps({'spec': spec, 'sources': sources}, allow_nan=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        with self.lock:
            if idempotency_key:
                row = self.db.execute('SELECT data,fingerprint FROM jobs WHERE idempotency=?', (idempotency_key,)).fetchone()
                if row:
                    if row[1] != fingerprint:
                        raise AdmissionError('Idempotency-Key was already used for a different submission', 409, 'idempotency_conflict')
                    return self._public(json.loads(row[0])), False
            self.maintain()
            self._admit(total + self.limits.output_bytes)
            job_id = uuid4().hex
            directory = self.inputs / job_id
            directory.mkdir(mode=0o700)
            job = {'id': job_id, 'state': 'receiving', 'created': time.time(), 'updated': time.time(), 'spec': spec,
                   'sources': sources, 'received': {}, 'reserved_bytes': total + self.limits.output_bytes}
            try:
                self.db.execute('INSERT INTO jobs VALUES (?,?,?,?,?,?,?)',
                                (job_id, job['state'], job['created'], job['updated'], json.dumps(job, allow_nan=False), idempotency_key, fingerprint))
                self._save(job, event=True)
            except BaseException:
                self.db.rollback(); shutil.rmtree(directory); raise
            return self._public(job), True

    def begin_source(self, job_id: str, role: str, length: int) -> tuple[Path, dict]:
        with self.lock:
            job = self._get(job_id)
            if not job or job['state'] != 'receiving' or role not in job['sources']:
                raise AdmissionError('This job is not accepting that source', 409, 'upload_state')
            expected = job['sources'][role]
            if length != expected['bytes']:
                raise AdmissionError('Upload length differs from the reserved source descriptor', 413, 'upload_length')
            target = self.inputs / job_id / (role + '.part')
            # O_EXCL in the handler rejects simultaneous uploads for one slot.
            return target, dict(expected)

    def finish_source(self, job_id: str, role: str, temporary: Path, digest: str) -> dict:
        with self.lock:
            job = self._get(job_id)
            if not job or job['state'] != 'receiving' or role not in job['sources']:
                raise AdmissionError('Job no longer accepts uploads', 409, 'upload_state')
            expected = job['sources'][role]
            if digest != expected['sha256'] or temporary.stat().st_size != expected['bytes']:
                raise ValueError('Uploaded source does not match its declared SHA-256/size')
            with temporary.open('rb') as stream:
                extension = source_extension(stream.read(16))
            name = ('drawing' if role == 'primary' else 'station_reference') + extension
            target = self.inputs / job_id / name
            if role in job['received']:
                temporary.unlink(); return self._public(job)
            temporary.replace(target)
            directory = os.open(target.parent, os.O_DIRECTORY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
            job['received'][role] = name
            self._save(job)
            return self._public(job)

    def submit(self, job_id: str) -> dict:
        with self.lock:
            job = self._get(job_id)
            if not job:
                raise AdmissionError('Job not found', 404, 'not_found')
            if job['state'] != 'receiving':
                return self._public(job)
            if set(job['received']) != set(job['sources']):
                raise AdmissionError('Upload each declared source before submitting', 409, 'incomplete_upload')
            spec = json.loads(json.dumps(job['spec']))
            for role, name in job['received'].items():
                key = 'source' if role == 'primary' else 'station_reference'
                spec[key]['file'] = name
                spec[key]['upload_original_sha256'] = job['sources'][role]['sha256']
            spec_path = self.inputs / job_id / 'spec.json'
            atomic_json(spec_path, spec)
            job['spec_sha256'] = hashlib.sha256(spec_path.read_bytes()).hexdigest()
            job.update(state='queued', queued=time.time())
            self._save(job, event=True)
            self.wake.set()
            return self._public(job)

    def cancel(self, job_id: str) -> dict:
        with self.lock:
            job = self._get(job_id)
            if not job:
                raise AdmissionError('Job not found', 404, 'not_found')
            if job['state'] == 'running':
                job['cancel_requested'] = True
                self.cancel_events.setdefault(job_id, threading.Event()).set()
                self._save(job)
            elif job['state'] in ('queued', 'receiving'):
                job.update(state='cancelled', finished=time.time(), error_code='user_cancelled')
                self._save(job, event=True)
            return self._public(job)

    def maintain(self) -> None:
        with self.lock:
            now = time.time()
            for (raw,) in self.db.execute('SELECT data FROM jobs').fetchall():
                job = json.loads(raw)
                if job['state'] == 'receiving' and now - job['created'] > self.receiving_seconds:
                    job.update(state='interrupted', finished=now, error_code='upload_expired')
                    self._save(job, event=True)
                if job['state'] in TERMINAL and now - job.get('finished', job['updated']) >= self.input_retention_seconds:
                    directory = self.inputs / job['id']
                    if directory.exists() and not directory.is_symlink():
                        shutil.rmtree(directory)

    def _source_integrity(self, job: dict) -> bool:
        directory = self.inputs / job['id']
        spec_path = directory / 'spec.json'
        if spec_path.is_symlink() or not spec_path.is_file() or spec_path.stat().st_size > 2 * 1024**2:
            return False
        if hashlib.sha256(spec_path.read_bytes()).hexdigest() != job.get('spec_sha256'):
            return False
        for role, name in job.get('received', {}).items():
            path = directory / name
            expected = job['sources'][role]
            if path.is_symlink() or not path.is_file() or path.stat().st_size != expected['bytes']:
                return False
            digest = hashlib.sha256()
            with path.open('rb') as stream:
                for chunk in iter(lambda: stream.read(64 * 1024), b''):
                    digest.update(chunk)
            if digest.hexdigest() != expected['sha256']:
                return False
        return set(job.get('received', {})) == set(job['sources'])

    def _maintenance_loop(self) -> None:
        while not self.stop.wait(0.5):
            try:
                self.maintain()
            except (OSError, sqlite3.Error):
                self.last_error = 'maintenance_storage_error'

    def _loop(self) -> None:
        while not self.stop.is_set():
            self.last_tick = time.time()
            with self.lock:
                row = self.db.execute("SELECT data FROM jobs WHERE state='queued' ORDER BY created LIMIT 1").fetchone()
                job = json.loads(row[0]) if row else None
                if job:
                    job.update(state='running', started=time.time(), queued_seconds=round(time.time() - job['queued'], 4))
                    self._save(job, event=True)
                    cancellation = self.cancel_events.setdefault(job['id'], threading.Event())
            if not job:
                self.wake.wait(0.25); self.wake.clear()
                continue
            try:
                if not self._source_integrity(job):
                    outcome = {'state': 'failed', 'error_code': 'queued_input_changed', 'elapsed_seconds': 0}
                else:
                    def started(identity):
                        with self.lock:
                            current = self._get(job['id']); current['process'] = identity; self._save(current)
                    outcome = run_isolated(self.inputs / job['id'] / 'spec.json', self.runs / job['id'],
                                           limits=self.limits, cancel_event=cancellation, stop_event=self.stop, on_start=started)
                with self.lock:
                    job = self._get(job['id'])
                    job.update({key: outcome[key] for key in ('state', 'error_code', 'elapsed_seconds', 'resources', 'publication_reconciled', 'worker_state') if key in outcome})
                    job['finished'] = time.time()
                    if outcome.get('result'):
                        job.update(result_status=outcome['result']['status'], run_path=f'runs/{job["id"]}')
                    self._save(job, event=True)
                    self.cancel_events.pop(job['id'], None)
            except BaseException as exc:
                with self.lock:
                    self.last_error = type(exc).__name__
                    job = self._get(job['id'])
                    job.update(state='failed', error_code='controller_job_error', finished=time.time())
                    self._save(job, event=True)
            self.last_tick = time.time()

    def health(self) -> dict:
        with self.lock:
            counts = {state: count for state, count in self.db.execute('SELECT state,COUNT(*) FROM jobs GROUP BY state')}
            active = self.db.execute("SELECT data FROM jobs WHERE state='running' LIMIT 1").fetchone()
            job = json.loads(active[0]) if active else None
            admission_code = None
            try:
                self._admit(DEFAULT_POLICY.aggregate_bytes + self.limits.output_bytes)
            except AdmissionError as exc:
                admission_code = exc.code
        pending = sum(counts.get(state, 0) for state in ACTIVE)
        disk_free = shutil.disk_usage(self.artifacts).free
        alive = self.thread.is_alive() if self.worker_enabled else False
        ready = alive and not self.stop.is_set() and admission_code is None
        if job and time.time() - job['started'] > self.limits.wall_seconds + 5:
            ready = False; admission_code = 'worker_overdue'
        return {'live': not self.stop.is_set(), 'ready': ready, 'worker_alive': alive,
                'queue_depth': counts.get('queued', 0), 'receiving': counts.get('receiving', 0),
                'running': counts.get('running', 0), 'available_slots': max(0, self.max_pending - pending),
                'active_seconds': round(time.time() - job['started'], 3) if job else None,
                'disk_free_bytes': disk_free, 'admission_blocker': admission_code, 'last_error_code': self.last_error,
                'engineering_approval': False}

    def backup(self, target: Path) -> Path:
        """Quiescent offline-copy backup: includes completed artifacts and inputs."""
        target = Path(target).resolve()
        if target.exists() or self.artifacts == target or self.artifacts in target.parents:
            raise ValueError('Backup must be a new directory outside the artifact root')
        with self.lock:
            if self.db.execute("SELECT COUNT(*) FROM jobs WHERE state IN ('receiving','running')").fetchone()[0]:
                raise RuntimeError('Finish/cancel uploads and active jobs before making a backup')
            for directory, dirs, files in os.walk(self.artifacts, followlinks=False):
                if any((Path(directory) / name).is_symlink() for name in dirs + files):
                    raise ValueError('Backup refuses symbolic links in the artifact root')
            shutil.copytree(self.artifacts, target, ignore=shutil.ignore_patterns('jobs.sqlite3*', 'controller.lock', '*.part'))
            destination = sqlite3.connect(target / '.workbench' / 'jobs.sqlite3')
            try:
                self.db.backup(destination)
            finally:
                destination.close()
        return target

    def close(self) -> None:
        self.stop.set(); self.wake.set()
        if self.thread.is_alive():
            self.thread.join(timeout=8)
        if self.maintenance_thread.is_alive():
            self.maintenance_thread.join(timeout=2)
        if self.thread.is_alive():
            raise RuntimeError('Queue worker did not stop within the bounded shutdown interval')
        with self.lock:
            self.db.close()
            fcntl.flock(self._lock_file, fcntl.LOCK_UN)
            self._lock_file.close()
