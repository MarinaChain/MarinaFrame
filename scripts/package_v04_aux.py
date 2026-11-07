"""Manifest and verify an explicitly staged runtime or public-data package."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import stat
import zipfile


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root', type=Path, required=True)
    p.add_argument('--kind', choices=['runtime', 'public-data'], required=True)
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--inventory', type=Path, required=True,
                   help='Explicit separately reviewed staging inventory, outside the staged tree')
    p.add_argument('--inventory-sha256', required=True)
    a = p.parse_args()
    root = a.root.resolve(strict=True)
    inventory_path = a.inventory.resolve(strict=True)
    if inventory_path.is_relative_to(root):
        raise SystemExit('Admission inventory must be outside the staged tree')
    inventory_raw = inventory_path.read_bytes()
    if sha(inventory_raw) != a.inventory_sha256:
        raise SystemExit('Reviewed staging inventory identity differs')
    admitted = json.loads(inventory_raw)
    if admitted.get('schema_version') != 'marinaframe.package-admission.v1' or admitted.get('kind') != a.kind:
        raise SystemExit('Wrong staging admission contract or package kind')
    rows = admitted.get('files', [])
    expected = {row['path']: row for row in rows}
    if not rows or len(expected) != len(rows):
        raise SystemExit('Empty or duplicate staging inventory')
    prefix = 'MarinaFrame-0.4-Runtime' if a.kind == 'runtime' else 'MarinaFrame-0.4-Public-Data'
    files = {}
    for path in sorted(root.rglob('*')):
        if path.is_symlink():
            raise SystemExit('Symlink outside explicit package scope')
        if not path.is_file():
            continue
        name = path.relative_to(root).as_posix()
        if 'restricted' in path.relative_to(root).parts or path.name in {'opencode-go-keys.txt', '.env'}:
            raise SystemExit('Restricted or credential input in unrestricted package')
        files[name] = path
    if 'MANIFEST.json' in files or set(files) != set(expected):
        raise SystemExit('Staging tree differs from the exact reviewed inventory')
    for name, path in files.items():
        row = expected[name]
        raw = path.read_bytes()
        if (sha(raw), len(raw), stat.S_IMODE(path.stat().st_mode)) != (row['sha256'], row['bytes'], row['mode']):
            raise SystemExit('Staged file differs from the reviewed identity')
    if a.kind == 'public-data':
        control = 'artifacts/v04/data/release-allowlist.json'
        allowlist = json.loads(files[control].read_text())
        allowed = {row['file']: row for row in allowlist['files']}
        admitted = {name.removeprefix('artifacts/v04/data/'): path for name, path in files.items()
                    if name.startswith('artifacts/v04/data/') and name != control}
        if set(admitted) != set(allowed):
            raise SystemExit('Public-data package inventory differs from exact allowlist')
        for name, path in admitted.items():
            raw = path.read_bytes()
            if sha(raw) != allowed[name]['sha256'] or len(raw) != allowed[name]['bytes']:
                raise SystemExit('Public-data package file identity differs')
    else:
        binary = files['bin/marinaframe']
        if sha(binary.read_bytes()) != '071d76828b845d0134e57a3f4c14e48fc2843027cfa45806de5d67767d5b6f72':
            raise SystemExit('Runtime binary differs from evaluated application freeze')
        if any('.so' in Path(name).suffixes or Path(name).suffix in {'.dll', '.pyd'} for name in files):
            raise SystemExit('Native dependency binary unexpectedly bundled')
    a.out.parent.mkdir(parents=True, exist_ok=True)
    if a.out.exists():
        raise SystemExit('Refusing to overwrite existing package')
    pending = a.out.with_suffix(a.out.suffix + '.pending')
    rows = []
    with zipfile.ZipFile(pending, 'x', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for name, path in sorted(files.items()):
            if path.is_symlink() or not path.is_file():
                raise SystemExit('Staged file changed kind')
            raw = path.read_bytes()
            mode = stat.S_IMODE(path.stat().st_mode)
            identity = expected[name]
            if (sha(raw), len(raw), mode) != (identity['sha256'], identity['bytes'], identity['mode']):
                raise SystemExit('Staged file changed after admission; preserving incomplete archive')
            rows.append({'path': name, 'bytes': len(raw), 'sha256': sha(raw)})
            info = zipfile.ZipInfo(prefix + '/' + name, date_time=(2026, 11, 7, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = (mode | stat.S_IFREG) << 16
            z.writestr(info, raw, compresslevel=6)
        manifest = {'schema_version': 'marinaframe.auxiliary-release.v1', 'kind': a.kind,
                    'application_freeze': '8916e68f4c175bdab291d7c0bf2978862be8915d',
                    'reviewed_inventory_sha256': a.inventory_sha256,
                    'files': rows, 'file_count': len(rows),
                    'restricted_data_included': False, 'engineering_approved': False}
        z.writestr(prefix + '/MANIFEST.json', json.dumps(manifest, indent=2) + '\n')
    with zipfile.ZipFile(pending) as z:
        if set(z.namelist()) != {prefix + '/' + r['path'] for r in rows} | {prefix + '/MANIFEST.json'}:
            raise SystemExit('Archive member inventory differs')
        for row in rows:
            raw = z.read(prefix + '/' + row['path'])
            if len(raw) != row['bytes'] or sha(raw) != row['sha256']:
                raise SystemExit('Archive member hash or length differs')
    pending.rename(a.out)
    receipt = {'file': a.out.name, 'kind': a.kind, 'bytes': a.out.stat().st_size,
               'sha256': sha(a.out.read_bytes()), 'files': len(rows),
               'every_member_hash_and_inventory_verified': True}
    a.out.with_suffix('.json').write_text(json.dumps(receipt, indent=2) + '\n')
    print(json.dumps(receipt), flush=True)


if __name__ == '__main__':
    main()
