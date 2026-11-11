"""Pack large evidence files of an outputs/ round into one compressed archive.

Each round folder keeps its reports, scripts, images and small files as they are. Text files
(.json, .jsonl) larger than LIMIT_BYTES move into `<round>/evidence.tar.gz`, and
`<round>/EVIDENCE.md` lists each packed file with its size and SHA-256 and says how to unpack it.

Usage: python scripts/archive_evidence.py outputs/w14 [outputs/w11 ...]
Unpack: tar -xzf outputs/w14/evidence.tar.gz -C outputs/w14
"""
from __future__ import annotations

import argparse
import hashlib
import io
import tarfile
from pathlib import Path

LIMIT_BYTES = 100 * 1024  # Smaller files stay readable in the repository and in diffs.
PACKED_SUFFIXES = {'.json', '.jsonl'}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def large_text_files(round_dir: Path) -> list[Path]:
    return sorted(p for p in round_dir.rglob('*')
                  if p.is_file() and p.suffix in PACKED_SUFFIXES and p.stat().st_size > LIMIT_BYTES)


def add_deterministic(archive: tarfile.TarFile, path: Path, name: str) -> None:
    """Fixed owner, mode and time, so the same files always give the same archive bytes."""
    info = tarfile.TarInfo(name)
    data = path.read_bytes()
    info.size, info.mode, info.mtime, info.uid, info.gid = len(data), 0o644, 0, 0, 0
    archive.addfile(info, io.BytesIO(data))


def pack(round_dir: Path) -> list[tuple[str, int, str]]:
    files = large_text_files(round_dir)
    if not files:
        return []
    rows = [(str(p.relative_to(round_dir)), p.stat().st_size, sha256(p)) for p in files]
    buffer = io.BytesIO()
    import gzip
    with gzip.GzipFile(fileobj=buffer, mode='wb', mtime=0) as gz, tarfile.open(fileobj=gz, mode='w') as tar:
        for path, (name, _, _) in zip(files, rows):
            add_deterministic(tar, path, name)
    (round_dir / 'evidence.tar.gz').write_bytes(buffer.getvalue())
    lines = [f'# Packed evidence: {round_dir.name}', '',
             'These files are packed in `evidence.tar.gz` to keep the repository small. Unpack with',
             f'`tar -xzf {round_dir.as_posix()}/evidence.tar.gz -C {round_dir.as_posix()}`.', '',
             '| File | Bytes | SHA-256 |', '|---|---:|---|']
    lines += [f'| `{name}` | {size} | `{digest}` |' for name, size, digest in rows]
    (round_dir / 'EVIDENCE.md').write_text('\n'.join(lines) + '\n')
    for path in files:
        path.unlink()
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('rounds', nargs='+', type=Path)
    for round_dir in parser.parse_args().rounds:
        rows = pack(round_dir)
        print(f'{round_dir}: packed {len(rows)} files, {sum(r[1] for r in rows)} bytes')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
