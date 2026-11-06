"""Generate the platform lock and wheel inventory from an explicitly populated wheelhouse.

First download the reviewed exact requirements into an empty directory. This
script never resolves versions or silently calls a package index.
"""
import argparse
import datetime
import email
import hashlib
import json
from pathlib import Path
import zipfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('wheelhouse', type=Path)
    parser.add_argument('--repo', type=Path, default=Path.cwd())
    args = parser.parse_args()
    rows = []
    for wheel in sorted(args.wheelhouse.glob('*.whl')):
        with zipfile.ZipFile(wheel) as archive:
            entries = [name for name in archive.namelist() if name.endswith('.dist-info/METADATA') and name.count('/') == 1]
            if len(entries) != 1:
                raise ValueError('Wheel must have one metadata record')
            meta = email.message_from_bytes(archive.read(entries[0]))
        rows.append({'name': str(meta['Name']), 'version': str(meta['Version']), 'wheel': wheel.name,
                     'sha256': hashlib.sha256(wheel.read_bytes()).hexdigest(),
                     'license': str(meta.get('License-Expression') or meta.get('License') or 'Not declared')[:500]})
    rows.sort(key=lambda row: row['name'].lower())
    if not rows or len({row['name'].lower().replace('_', '-') for row in rows}) != len(rows):
        raise ValueError('Require exactly one reviewed wheel per package')
    lock = '# Linux x86_64 / CPython 3.12; one exact tested wheel per distribution.\n'
    lock += '# Regenerate through scripts/build_lock_inventory.py after an explicit dependency review.\n'
    lock += '\n'.join(f"{row['name']}=={row['version']} --hash=sha256:{row['sha256']}" for row in rows) + '\n'
    (args.repo/'requirements-linux-py312.lock').write_text(lock)
    docs = args.repo/'docs'
    docs.mkdir(exist_ok=True)
    timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat()
    (docs/'dependency-inventory.json').write_text(json.dumps({
        'scope': 'Python wheels only; system packages and OCR weights are separately fingerprinted',
        'generated_utc': timestamp, 'components': rows}, indent=2))
    components = [{'type': 'library', 'name': row['name'], 'version': row['version'],
        'purl': f"pkg:pypi/{row['name'].lower().replace('_', '-')}@{row['version']}",
        'hashes': [{'alg': 'SHA-256', 'content': row['sha256']}],
        'licenses': [{'license': {'name': row['license']}}]} for row in rows]
    (docs/'sbom.cdx.json').write_text(json.dumps({'bomFormat': 'CycloneDX', 'specVersion': '1.6',
        'version': 1, 'metadata': {'timestamp': timestamp}, 'components': components}, indent=2))
    print(f'Recorded {len(rows)} exact wheels')


if __name__ == '__main__':
    main()
