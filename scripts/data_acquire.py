"""Bounded, auditable acquisition of explicitly listed research assets.

The manifest is an operator input, never a model-generated tool request. Rights
are recorded separately from successful HTTP transport. No authentication or
access-control bypass, alternate mirror, or implicit retry is performed.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import time
import urllib.error
import urllib.parse
import urllib.request


class DeclaredHostRedirect(urllib.request.HTTPRedirectHandler):
    def __init__(self, hosts):
        self.hosts = frozenset(hosts)

    def redirect_request(self, request, response, code, message, headers, newurl):
        target = urllib.parse.urlsplit(newurl)
        if (target.scheme != 'https' or target.hostname not in self.hosts
                or target.username or target.password or target.port not in (None, 443)):
            raise ValueError('Redirect outside declared source hosts')
        return super().redirect_request(request, response, code, message, headers, newurl)


def atomic_json(path: Path, value: dict) -> None:
    temporary = path.with_suffix(path.suffix + '.pending')
    with temporary.open('x', encoding='utf-8') as handle:
        json.dump(value, handle, indent=2, allow_nan=False)
        handle.write('\n')
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def acquire(manifest: Path, out: Path, *, max_file_bytes: int = 200_000_000,
            max_total_bytes: int = 1_200_000_000, timeout: float = 30,
            file_wall_seconds: float = 240) -> dict:
    raw = manifest.read_bytes()
    if len(raw) > 1_000_000:
        raise ValueError('Acquisition manifest is too large')
    config = json.loads(raw)
    if config.get('schema_version') != 'marinaframe-acquisition-1':
        raise ValueError('Unknown acquisition manifest version')
    hosts = set(config['allowed_hosts'])
    items = config['items']
    if not 1 <= len(items) <= 128 or not hosts or any(not isinstance(h, str) for h in hosts):
        raise ValueError('Invalid bounded acquisition manifest')
    if any(type(v) is not int or v <= 0 for v in (max_file_bytes, max_total_bytes)):
        raise ValueError('Byte limits must be positive integers')
    if not 1 <= timeout <= 90 or not 1 <= file_wall_seconds <= 600:
        raise ValueError('Invalid finite timeout')
    names = set()
    for item in items:
        name = item['local_filename']
        url = urllib.parse.urlsplit(item['download_url'])
        if (url.scheme != 'https' or url.hostname not in hosts or url.username or url.password
                or url.port not in (None, 443) or url.fragment):
            raise ValueError('Only declared HTTPS public asset URLs are supported')
        if any(re.search(r'token|signature|credential|secret|api.?key', k, re.I)
               for k, _ in urllib.parse.parse_qsl(url.query)):
            raise ValueError('Credential-bearing or signed URLs must not be serialized')
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,180}', name) or name in names:
            raise ValueError('Output filename must be unique and local')
        names.add(name)
        if item['rights'].get('local_processing') != 'owner_authorized':
            raise ValueError('Local processing authorization is required for acquisition')

    out.mkdir(parents=True, exist_ok=False)
    (out / 'originals').mkdir()
    (out / 'failed').mkdir()
    (out / 'request-manifest.json').write_bytes(raw)
    report = {
        'schema_version': 'marinaframe-acquisition-receipts-1',
        'started_utc': datetime.now(timezone.utc).isoformat(),
        'request_manifest_sha256': hashlib.sha256(raw).hexdigest(),
        'limits': {'max_file_bytes': max_file_bytes, 'max_total_bytes': max_total_bytes,
                   'socket_timeout_seconds': timeout, 'file_wall_seconds': file_wall_seconds,
                   'concurrent_requests': 1, 'automatic_retries': 0},
        'receipts': [], 'bytes_downloaded': 0,
    }
    atomic_json(out / 'receipts.json', report)
    opener = urllib.request.build_opener(DeclaredHostRedirect(hosts))
    for item in items:
        started = time.monotonic()
        receipt = {
            'item_id': item['item_id'], 'download_url': item['download_url'],
            'source_url': item['source_url'], 'local_filename': item['local_filename'],
            'requested_utc': datetime.now(timezone.utc).isoformat(), 'status': 'intent_recorded',
            'rights': item['rights'], 'bytes': 0,
        }
        report['receipts'].append(receipt)
        atomic_json(out / 'receipts.json', report)
        temporary = out / 'failed' / (item['local_filename'] + '.incomplete')
        digest = hashlib.sha256()
        try:
            request = urllib.request.Request(item['download_url'], headers={
                'User-Agent': 'MarinaFrame research asset acquisition; bounded single request'})
            with opener.open(request, timeout=timeout) as response:
                final_url = urllib.parse.urlsplit(response.url)
                if final_url.scheme != 'https' or final_url.hostname not in hosts:
                    raise ValueError('Redirect outside declared source hosts')
                receipt['http_status'] = response.status
                receipt['content_type'] = response.headers.get('Content-Type')
                receipt['reported_content_length'] = response.headers.get('Content-Length')
                length = response.headers.get('Content-Length')
                if length and (int(length) > max_file_bytes or int(length) + report['bytes_downloaded'] > max_total_bytes):
                    raise ValueError('Asset exceeds admitted byte limit')
                with temporary.open('xb') as handle:
                    while True:
                        chunk = response.read(256 * 1024)
                        if not chunk:
                            break
                        receipt['bytes'] += len(chunk)
                        report['bytes_downloaded'] += len(chunk)
                        if (receipt['bytes'] > max_file_bytes or report['bytes_downloaded'] > max_total_bytes
                                or time.monotonic() - started > file_wall_seconds):
                            raise ValueError('Asset exceeded execution/byte budget')
                        handle.write(chunk)
                        digest.update(chunk)
                    handle.flush()
                    os.fsync(handle.fileno())
            if receipt['bytes'] == 0:
                raise ValueError('Empty asset')
            if length and int(length) != receipt['bytes']:
                raise ValueError('Incomplete Content-Length transport')
            receipt['sha256'] = digest.hexdigest()
            expected = item.get('expected_sha256')
            if expected is not None and expected != receipt['sha256']:
                raise ValueError('Expected source hash mismatch')
            # Header inspection only: acquisition does not decode unbounded pixels.
            from PIL import Image
            with Image.open(temporary) as image:
                width, height = image.size
                if width * height > 150_000_000 or min(width, height) < 1:
                    raise ValueError('Image header exceeds acquisition pixel bound')
                receipt.update(width_px=width, height_px=height, format=image.format,
                               mode=image.mode, pixel_decode_performed=False)
            final_path = out / 'originals' / item['local_filename']
            os.replace(temporary, final_path)
            receipt.update(status='downloaded', file=str(final_path.relative_to(out)))
        except urllib.error.HTTPError as exc:
            receipt.update(status='http_denied_or_failed', http_status=exc.code,
                           error_type=type(exc).__name__, no_alternate_route_attempted=True)
        except Exception as exc:
            receipt.update(status='failed', error_type=type(exc).__name__)
            if isinstance(exc, ValueError):
                receipt['reason'] = str(exc)
        receipt['elapsed_seconds'] = time.monotonic() - started
        receipt['completed_utc'] = datetime.now(timezone.utc).isoformat()
        if temporary.exists():
            receipt['partial_file'] = str(temporary.relative_to(out))
            receipt['partial_sha256'] = hashlib.sha256(temporary.read_bytes()).hexdigest()
        atomic_json(out / 'receipts.json', report)
        print(json.dumps({k: receipt[k] for k in ('item_id', 'status', 'bytes', 'elapsed_seconds')}), flush=True)
    report['completed_utc'] = datetime.now(timezone.utc).isoformat()
    report['downloaded_items'] = sum(r['status'] == 'downloaded' for r in report['receipts'])
    atomic_json(out / 'receipts.json', report)
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--max-file-bytes', type=int, default=200_000_000)
    parser.add_argument('--max-total-bytes', type=int, default=1_200_000_000)
    parser.add_argument('--timeout', type=float, default=30)
    parser.add_argument('--file-wall-seconds', type=float, default=240)
    args = parser.parse_args()
    result = acquire(args.manifest, args.out, max_file_bytes=args.max_file_bytes,
                     max_total_bytes=args.max_total_bytes, timeout=args.timeout,
                     file_wall_seconds=args.file_wall_seconds)
    print(json.dumps({'downloaded_items': result['downloaded_items'], 'attempted_items': len(result['receipts'])}))
    raise SystemExit(0 if result['downloaded_items'] == len(result['receipts']) else 1)
