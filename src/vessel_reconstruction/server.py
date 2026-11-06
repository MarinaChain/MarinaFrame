"""Authenticated, loopback-only local workbench with a durable bounded queue."""
from __future__ import annotations
import argparse
import base64
import binascii
import hashlib
import hmac
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import math
import mimetypes
import os
from pathlib import Path
import re
import secrets
import socket
import threading
import time
from typing import Any
from urllib.parse import unquote, urlsplit

from .jobs import AdmissionError, JobQueue
from .resources import DEFAULT_POLICY

MAX_REQUEST_BYTES = 2 * 1024**2
MAX_LEGACY_REQUEST_BYTES = 46 * 1024**2
MAX_IMAGE_BYTES = DEFAULT_POLICY.source_bytes
MAX_REFERENCE_BYTES = DEFAULT_POLICY.reference_bytes
MAX_IMAGE_PIXELS = DEFAULT_POLICY.pixels
COOKIE_NAME = 'marinaframe_session'


def _run_id(relative: str) -> str:
    return base64.urlsafe_b64encode(relative.encode()).decode().rstrip('=')


def _decode_run_id(value: str) -> str:
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,1200}', value):
        raise ValueError('Invalid run identifier')
    return base64.urlsafe_b64decode(value + '=' * (-len(value) % 4)).decode('utf-8')


def _contained(root: Path, target: Path) -> Path:
    root = root.resolve()
    if target.is_absolute():
        candidate = target
    else:
        candidate = root / target
    try:
        relative = candidate.relative_to(root)
    except ValueError:
        raise ValueError('Requested path is outside the artifact root')
    if any(part in ('..', '.') or part.startswith('.') for part in relative.parts):
        raise ValueError('Hidden or traversing paths are not served')
    cursor = root
    for part in relative.parts:
        cursor /= part
        if cursor.is_symlink():
            raise ValueError('Symbolic links are not served')
    resolved = candidate.resolve()
    if resolved != root and root not in resolved.parents:
        raise ValueError('Requested path is outside the artifact root')
    return resolved


def strict_json(raw: bytes) -> dict:
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError('Duplicate JSON keys are not allowed')
            result[key] = value
        return result
    def finite(token):
        value = float(token)
        if not math.isfinite(value):
            raise ValueError('JSON numbers must be finite')
        return value
    def integer(token):
        if len(token) > 64:
            raise ValueError('JSON integer magnitude exceeds the input limit')
        return int(token)
    def constant(_):
        raise ValueError('JSON numbers must be finite')
    try:
        value = json.loads(raw, object_pairs_hook=pairs, parse_float=finite, parse_int=integer, parse_constant=constant)
    except (UnicodeError, RecursionError) as exc:
        raise ValueError('JSON encoding or nesting is invalid') from exc
    if not isinstance(value, dict):
        raise ValueError('Expected a JSON object')
    count = 0
    stack = [(value, 0)]
    while stack:
        item, depth = stack.pop(); count += 1
        if depth > 16 or count > 30_000:
            raise ValueError('JSON nesting or item count exceeds the input budget')
        if isinstance(item, dict):
            stack.extend((child, depth + 1) for child in item.values())
        elif isinstance(item, list):
            stack.extend((child, depth + 1) for child in item)
    return value


def _load_json(path: Path) -> dict:
    if path.stat().st_size > 32 * 1024**2:
        raise ValueError('Artifact JSON exceeds the local viewer budget')
    from .schema import loads_bounded_json
    value = loads_bounded_json(path.read_bytes(), max_bytes=32 * 1024**2, max_nodes=3_000_000, max_depth=40)
    if not isinstance(value, dict):
        raise ValueError('Expected a JSON object')
    return value


def _verification(root: Path) -> dict:
    from .pipeline import verify_run
    try:
        return verify_run(root)
    except (OSError, ValueError, TypeError, KeyError, RecursionError):
        return {'valid': False, 'assurance': 'invalid', 'exports_allowed': False}


def find_runs(artifacts: Path) -> list[dict]:
    artifacts = artifacts.resolve()
    found = []
    visited = 0
    for directory, dirs, files in os.walk(artifacts, followlinks=False):
        dirs[:] = [name for name in dirs if not name.startswith('.') and not (Path(directory) / name).is_symlink()]
        visited += 1
        if visited > 4096 or len(found) >= 500:
            break
        if 'result.json' not in files:
            continue
        try:
            file = _contained(artifacts, Path(directory) / 'result.json')
            result = _load_json(file)
            if 'status' not in result or 'vessel_id' not in result:
                continue
            verification = _verification(file.parent)
            relative = file.parent.relative_to(artifacts).as_posix()
            metrics = result.get('metrics') or {}
            if not isinstance(result.get('vessel_id'), str) or not isinstance(result.get('status'), str) or not isinstance(metrics, dict) or not isinstance(result.get('sections', []), list):
                continue
            found.append({'id': _run_id(relative), 'name': result.get('vessel_id', file.parent.name),
                          'run_id': result.get('run_id'), 'status': result.get('status', 'unknown'),
                          'path': relative, 'modified': file.stat().st_mtime,
                          'sections': len(result.get('sections') or []), 'volume_m3': metrics.get('volume_m3') if verification.get('valid') else None,
                          'has_mesh': bool(verification.get('exports_allowed') and (result.get('exports') or {}).get('mesh')),
                          'integrity': verification.get('assurance'), 'viewable': bool(verification.get('valid'))})
        except (OSError, ValueError, TypeError):
            continue
    return sorted(found, key=lambda value: value['modified'], reverse=True)


def _declared_assets(result: dict) -> set[str]:
    files = {'result.json', 'manifest.json', 'input_spec.json', 'replay_spec.json', 'extracted_sections.json', 'cad_sections.json'}
    files.update(value for value in (result.get('exports') or {}).values() if isinstance(value, str))
    for source in result.get('sources') or []:
        files.update(source[key] for key in ('file', 'preview_file') if isinstance(source.get(key), str))
    return files


class WorkbenchServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address: tuple[str, int], artifacts: Path, web_root: Path, *,
                 queue_options: dict | None = None, request_seconds: float = 20, max_connections: int = 16):
        host, port = address
        if host not in {'127.0.0.1', 'localhost', '::1'}:
            raise ValueError('Remote binding is unsupported. Use 127.0.0.1 or ::1 for the authenticated local workbench.')
        if host == 'localhost':
            host = '127.0.0.1'
        if host == '::1':
            self.address_family = socket.AF_INET6
        self.artifacts = Path(artifacts).resolve()
        self.web_root = Path(web_root).resolve()
        self.request_seconds = request_seconds
        self.connections = threading.BoundedSemaphore(max_connections)
        self.legacy_requests = threading.BoundedSemaphore(1)
        self.sessions: dict[str, dict] = {}
        self.session_lock = threading.Lock()
        self.bootstrap_token = secrets.token_urlsafe(32)
        self.bootstrap_expires = time.monotonic() + 600
        self.bootstrap_used = False
        self._closed = False
        super().__init__((host, port), WorkbenchHandler)
        actual_port = self.server_address[1]
        authorities = [f'127.0.0.1:{actual_port}', f'localhost:{actual_port}'] if host == '127.0.0.1' else [f'[::1]:{actual_port}']
        self.trusted_hosts = frozenset(authorities)
        self.trusted_origins = frozenset('http://' + authority for authority in authorities)
        self.login_url = f'http://{authorities[0]}/#session={self.bootstrap_token}'
        try:
            self.queue = JobQueue(self.artifacts, **(queue_options or {}))
        except BaseException:
            super().server_close(); raise
        self._closed = False

    def get_request(self):
        request, address = super().get_request()
        request.settimeout(self.request_seconds)
        return request, address

    def process_request(self, request, client_address):
        if not self.connections.acquire(blocking=False):
            try:
                request.sendall(b'HTTP/1.0 503 Service Unavailable\r\nContent-Length: 0\r\nConnection: close\r\n\r\n')
            except OSError:
                pass
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self.connections.release(); raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.connections.release()

    def server_close(self):
        if not self._closed:
            self._closed = True
            super().server_close()
            if hasattr(self, 'queue'):
                self.queue.close()


class WorkbenchHandler(BaseHTTPRequestHandler):
    server: WorkbenchServer
    server_version = 'MarinaFrameLocal/2'

    def log_message(self, fmt, *args):
        # HTTP paths, cookies, fragments and document content never enter logs.
        pass

    def handle_one_request(self):
        self.deadline = time.monotonic() + self.server.request_seconds
        def expire():
            try:
                self.connection.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
        timer = threading.Timer(self.server.request_seconds, expire); timer.daemon = True; timer.start()
        try:
            super().handle_one_request()
        finally:
            timer.cancel()

    def _headers(self, status, length, content_type, *, cookie=None):
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(length))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('Cross-Origin-Resource-Policy', 'same-origin')
        self.send_header('Content-Security-Policy', "default-src 'self'; img-src 'self' data: blob:; script-src 'self'; style-src 'self' 'unsafe-inline'; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'")
        if cookie:
            self.send_header('Set-Cookie', cookie)
        self.end_headers()

    def _json(self, value, status=200, *, cookie=None):
        raw = json.dumps(value, allow_nan=False).encode()
        self._headers(status, len(raw), 'application/json; charset=utf-8', cookie=cookie)
        if self.command != 'HEAD':
            self.wfile.write(raw)

    def _file(self, path):
        if not path.is_file() or path.is_symlink():
            self._json({'error': 'File not found'}, 404); return
        content_type = mimetypes.guess_type(path.name)[0] or 'application/octet-stream'
        if path.suffix == '.js':
            content_type = 'text/javascript; charset=utf-8'
        with path.open('rb') as stream:
            self._headers(200, os.fstat(stream.fileno()).st_size, content_type)
            if self.command != 'HEAD':
                for chunk in iter(lambda: stream.read(64 * 1024), b''):
                    self.wfile.write(chunk)

    def _job_admitted(self, root: Path, result: dict) -> bool:
        relative = root.relative_to(self.server.artifacts).as_posix()
        if not re.fullmatch('runs/[a-f0-9]{32}', relative):
            return True
        job = self.server.queue.get(root.name)
        if not job:
            return True
        if job['state'] in {'receiving', 'queued', 'running'}:
            return False
        return result.get('status') != 'review_required' or job['state'] == 'succeeded'

    def _boundary(self):
        hosts = self.headers.get_all('Host', [])
        origins = self.headers.get_all('Origin', [])
        if len(hosts) != 1 or hosts[0] not in self.server.trusted_hosts:
            self._json({'error': 'Untrusted Host header'}, 403); return False
        if origins and (len(origins) != 1 or origins[0] not in self.server.trusted_origins):
            self._json({'error': 'Untrusted Origin header'}, 403); return False
        if self.headers.get('Sec-Fetch-Site') == 'cross-site':
            self._json({'error': 'Cross-site requests are not allowed'}, 403); return False
        if not self.path.startswith('/') or self.path.startswith('//'):
            self._json({'error': 'Invalid request target'}, 400); return False
        return True

    def _session(self, *, mutation=False):
        try:
            cookie = SimpleCookie(self.headers.get('Cookie', ''))
            token = cookie[COOKIE_NAME].value if COOKIE_NAME in cookie else ''
        except Exception:
            token = ''
        with self.server.session_lock:
            record = self.server.sessions.get(token)
            if not record or record['expires'] < time.monotonic():
                self.server.sessions.pop(token, None)
                self._json({'error': 'Open the session link printed by the local workbench to sign in.'}, 401); return None
            if mutation and not hmac.compare_digest(self.headers.get('X-MarinaFrame-CSRF', '').encode(), record['csrf'].encode()):
                self._json({'error': 'Session request token is missing or invalid. Reload the workbench.'}, 403); return None
            return record

    def _length(self, maximum):
        values = self.headers.get_all('Content-Length', [])
        if self.headers.get_all('Transfer-Encoding') or len(values) != 1 or not re.fullmatch('[0-9]{1,10}', values[0]):
            raise AdmissionError('A single exact Content-Length is required; chunked request framing is unsupported', 411, 'request_framing')
        length = int(values[0])
        if not 0 < length <= maximum:
            raise AdmissionError('Request exceeds the endpoint byte limit', 413, 'request_too_large')
        return length

    def _chunks(self, length):
        remaining = length
        while remaining:
            seconds = self.deadline - time.monotonic()
            if seconds <= 0:
                raise TimeoutError('Request deadline exceeded')
            self.connection.settimeout(seconds)
            chunk = self.rfile.read(min(64 * 1024, remaining))
            if not chunk:
                raise ValueError('Request body ended before Content-Length')
            remaining -= len(chunk)
            yield chunk

    def _body(self, maximum=MAX_REQUEST_BYTES):
        if self.headers.get_content_type() != 'application/json':
            raise AdmissionError('Send application/json', 415, 'content_type')
        return strict_json(b''.join(self._chunks(self._length(maximum))))

    def _error(self, exc):
        if isinstance(exc, AdmissionError):
            self._json({'error': str(exc), 'code': exc.code}, exc.status)
        elif isinstance(exc, (TimeoutError, socket.timeout)):
            self._json({'error': 'Request read deadline exceeded'}, 408)
        elif isinstance(exc, OSError):
            self._json({'error': 'Local storage or connection is unavailable'}, 507)
        else:
            self._json({'error': str(exc) if isinstance(exc, ValueError) else 'Invalid request'}, 400)

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        try:
            if not self._boundary(): return
            path = unquote(urlsplit(self.path).path)
            if path in {'/', '/index.html', '/app.js', '/style.css'}:
                self._file(self.server.web_root / ('index.html' if path == '/' else path[1:])); return
            record = self._session()
            if not record: return
            if path == '/api/session':
                self._json({'csrf': record['csrf'], 'profile': 'authenticated_local_single_user'}); return
            if path == '/api/runs':
                runs = find_runs(self.server.artifacts)
                for run in runs:
                    if not self._job_admitted(self.server.artifacts / run['path'], run):
                        run.update(viewable=False, has_mesh=False, volume_m3=None, integrity='worker_completion_unconfirmed')
                self._json({'runs': runs}); return
            if path in {'/api/health', '/api/ready'}:
                health = self.server.queue.health()
                self._json(health, 503 if path == '/api/ready' and not health['ready'] else 200); return
            if re.fullmatch('/api/jobs/[a-f0-9]{32}', path):
                job = self.server.queue.get(path.rsplit('/', 1)[1])
                if job and job.get('run_path'):
                    job['run_id'] = _run_id(job['run_path'])
                self._json(job or {'error': 'Job not found'}, 200 if job else 404); return
            if path.startswith('/api/review/'):
                root = _contained(self.server.artifacts, self.server.artifacts / _decode_run_id(path.removeprefix('/api/review/')))
                result = _load_json(root / 'result.json')
                if not self._job_admitted(root, result):
                    self._json({'error': 'Worker completion has not been admitted.'}, 409); return
                from .review import review_state
                self._json(review_state(root)); return
            if path.startswith('/api/run/'):
                pieces = path.removeprefix('/api/run/').split('/', 1)
                if len(pieces) != 2: raise ValueError('Missing artifact filename')
                root = _contained(self.server.artifacts, self.server.artifacts / _decode_run_id(pieces[0]))
                asset = _contained(root, root / pieces[1])
                if not (root / 'result.json').is_file():
                    self._json({'error': 'Run not found'}, 404); return
                verified = _verification(root)
                if not verified.get('valid'):
                    self._json({'error': 'Run integrity is unverified. Legacy records require replay; changed records require recovery.', 'assurance': verified.get('assurance')}, 409); return
                result = _load_json(root / 'result.json')
                if not self._job_admitted(root, result):
                    self._json({'error': 'Worker completion has not been admitted; model downloads remain disabled.'}, 409); return
                manifest = _load_json(root / 'manifest.json')
                allowed = set(manifest.get('files', {})) | {'result.json', 'manifest.json', 'review_history.json', 'review_state.json'}
                if pieces[1] not in allowed:
                    raise ValueError('Artifact is not declared by this run')
                if pieces[1] in (result.get('exports') or {}).values() and not verified.get('exports_allowed'):
                    self._json({'error': 'Model exports are not available for this run'}, 409); return
                self._file(asset); return
            self._json({'error': 'Not found'}, 404)
        except (ValueError, binascii.Error, UnicodeError, OSError, TimeoutError) as exc:
            try: self._error(exc)
            except OSError: pass

    def do_POST(self):
        legacy_acquired = False
        try:
            if not self._boundary(): return
            path = urlsplit(self.path).path
            if path == '/api/session':
                payload = self._body(4096)
                token = payload.get('token')
                with self.server.session_lock:
                    if not isinstance(token, str) or self.server.bootstrap_used or time.monotonic() > self.server.bootstrap_expires or not hmac.compare_digest(token.encode(), self.server.bootstrap_token.encode()):
                        self._json({'error': 'Session link is expired or already used. Restart the local workbench to issue a new link.'}, 403); return
                    self.server.bootstrap_used = True
                    session, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
                    self.server.sessions[session] = {'csrf': csrf, 'expires': time.monotonic() + 3600}
                self._json({'csrf': csrf, 'profile': 'authenticated_local_single_user'}, cookie=f'{COOKIE_NAME}={session}; HttpOnly; SameSite=Strict; Path=/; Max-Age=3600'); return
            if not self._session(mutation=True): return
            if path == '/api/uploads':
                payload = self._body()
                job, created = self.server.queue.reserve(payload.get('spec'), payload.get('sources'), idempotency_key=self.headers.get('Idempotency-Key'))
                self._json(job, 201 if created else 200); return
            match = re.fullmatch('/api/jobs/([a-f0-9]{32})/(submit|cancel)', path)
            if match:
                self._body(4096)
                operation = self.server.queue.submit if match[2] == 'submit' else self.server.queue.cancel
                self._json(operation(match[1]), 202); return
            if path == '/api/reconstruct':
                # Bounded compatibility API. New UI uses streamed binary uploads;
                # old clients still get the same durable admission/worker gates.
                legacy_acquired = self.server.legacy_requests.acquire(blocking=False)
                if not legacy_acquired:
                    raise AdmissionError('The compatibility upload slot is busy. Use streamed uploads or retry shortly.')
                payload = self._body(MAX_LEGACY_REQUEST_BYTES)
                spec = payload.get('spec')
                if not isinstance(spec, dict): raise ValueError('A drawing specification object is required')
                bodies = {}
                for role, key in (('primary', 'image_base64'), ('reference', 'station_reference_base64')):
                    if role == 'reference' and spec.get('station_reference') is None: continue
                    encoded = payload.get(key)
                    if not isinstance(encoded, str):
                        raise ValueError('An uploaded station-reference document is required' if role == 'reference' else 'A drawing upload is required')
                    if encoded.startswith('data:') and ',' in encoded: encoded = encoded.split(',', 1)[1]
                    bodies[role] = base64.b64decode(encoded, validate=True)
                sources = {role: {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()} for role, raw in bodies.items()}
                job, created = self.server.queue.reserve(spec, sources, idempotency_key=self.headers.get('Idempotency-Key'))
                if created:
                    try:
                        for role, raw in bodies.items():
                            temporary, expected = self.server.queue.begin_source(job['id'], role, len(raw))
                            with temporary.open('xb') as stream:
                                stream.write(raw); stream.flush(); os.fsync(stream.fileno())
                            self.server.queue.finish_source(job['id'], role, temporary, expected['sha256'])
                        job = self.server.queue.submit(job['id'])
                    except BaseException:
                        self.server.queue.cancel(job['id']); raise
                self._json(job, 202); return
            self._json({'error': 'Not found'}, 404)
        except (ValueError, binascii.Error, UnicodeError, OSError, TimeoutError) as exc:
            try: self._error(exc)
            except OSError: pass
        finally:
            if legacy_acquired:
                self.server.legacy_requests.release()

    def do_PUT(self):
        temporary = None
        owns_temporary = False
        try:
            if not self._boundary() or not self._session(mutation=True): return
            match = re.fullmatch('/api/jobs/([a-f0-9]{32})/sources/(primary|reference)', urlsplit(self.path).path)
            if not match:
                self._json({'error': 'Not found'}, 404); return
            if self.headers.get_content_type() != 'application/octet-stream':
                raise AdmissionError('Send application/octet-stream', 415, 'content_type')
            length = self._length(MAX_IMAGE_BYTES if match[2] == 'primary' else MAX_REFERENCE_BYTES)
            temporary, expected = self.server.queue.begin_source(match[1], match[2], length)
            digest = hashlib.sha256()
            with temporary.open('xb') as stream:
                owns_temporary = True
                for chunk in self._chunks(length):
                    digest.update(chunk); stream.write(chunk)
                stream.flush(); os.fsync(stream.fileno())
            self._json(self.server.queue.finish_source(match[1], match[2], temporary, digest.hexdigest()), 200)
        except (ValueError, OSError, TimeoutError) as exc:
            try: self._error(exc)
            except OSError: pass
        finally:
            if temporary is not None and owns_temporary:
                temporary.unlink(missing_ok=True)


def serve(artifacts_dir: str | Path = 'artifacts', host: str = '127.0.0.1', port: int = 8765) -> None:
    package_root = Path(__file__).resolve().parent
    web_root = package_root / 'web'
    if not (web_root / 'index.html').is_file():
        raise FileNotFoundError('Installed workbench web assets were not found')
    server = WorkbenchServer((host, port), Path(artifacts_dir), web_root)
    print(f'MarinaFrame local session (single use, expires in 10 minutes): {server.login_url}', flush=True)
    print('Local research reconstruction only. Engineering review is required.', flush=True)
    try:
        server.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def main():
    parser = argparse.ArgumentParser(description='Inspect evidence using an authenticated loopback-only workbench')
    parser.add_argument('--artifacts', default='artifacts')
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=8765)
    args = parser.parse_args()
    serve(args.artifacts, args.host, args.port)


if __name__ == '__main__':
    main()


def write_snapshot(run_dir: str | Path, output_file: str | Path) -> Path:
    """Create a self-contained, offline evidence viewer for one real result.

    It embeds the recorded result, mesh and source images. Available CAD exports
    are included up to a generous size limit; omitted downloads are hidden. The
    snapshot never adds geometry, alters metrics or enables engineering approval.
    """
    run_dir = Path(run_dir).resolve()
    result_path = _contained(run_dir, run_dir / "result.json")
    verification = _verification(run_dir)
    if not verification.get("valid"):
        raise ValueError("Snapshot requires a valid versioned manifest. Replay legacy runs before exporting a new snapshot.")
    result = _load_json(result_path)
    package_root = Path(__file__).resolve().parent
    web_root = package_root / "web"
    if not web_root.is_dir():
        web_root = package_root.parents[1] / "web"
    files = {"result.json", "replay_spec.json"}
    exports = (result.get("exports") or {}) if verification.get("exports_allowed") else {}
    for key in ("mesh", "step", "stl"):
        if isinstance(exports.get(key), str):
            files.add(exports[key])
    for source in result.get("sources") or []:
        for key in ("file", "preview_file"):
            if isinstance(source.get(key), str):
                files.add(source[key])
    assets = {}
    omitted = []
    total_bytes = 0
    for name in sorted(files):
        try:
            path = _contained(run_dir, run_dir / name)
            if not path.is_file():
                omitted.append(name)
                continue
            if path.stat().st_size > 20 * 1024 * 1024 or total_bytes + path.stat().st_size > 64 * 1024 * 1024:
                omitted.append(name)
                continue
            total_bytes += path.stat().st_size
            mime = mimetypes.guess_type(name)[0] or "application/octet-stream"
            assets[name] = f"data:{mime};base64," + base64.b64encode(path.read_bytes()).decode("ascii")
        except (OSError, ValueError):
            omitted.append(name)
    if "result.json" not in assets:
        raise ValueError("The immutable result exceeds the portable snapshot byte budget.")
    from .review import review_state
    payload = {
        "review_state": review_state(run_dir),
        "vessel_id": result.get("vessel_id", "Reconstruction"),
        "status": result.get("status", "unknown"),
        "assets": assets,
        "omitted_oversize_artifacts": omitted,
    }
    bootstrap = "window.__VESSEL_SNAPSHOT__=" + json.dumps(payload, ensure_ascii=True, separators=(",", ":")).replace("<", "\\u003c") + ";"
    html = (web_root / "index.html").read_text(encoding="utf-8")
    css = (web_root / "style.css").read_text(encoding="utf-8")
    js = (web_root / "app.js").read_text(encoding="utf-8")
    html = html.replace('<link rel="stylesheet" href="/style.css">', f"<style>\n{css}\n</style>")
    html = html.replace('<script src="/app.js" defer></script>', "")
    html = html.replace('</body>', f"<script>{bootstrap}</script>\n<script>\n{js}\n</script>\n</body>")
    output_file = Path(output_file).resolve()
    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text(html, encoding="utf-8")
    return output_file
