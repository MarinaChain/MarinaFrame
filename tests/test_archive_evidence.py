"""The evidence packer keeps small files, packs large text files, and records their hashes."""
from __future__ import annotations

import hashlib
import importlib.util
import tarfile
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts' / 'archive_evidence.py'
spec = importlib.util.spec_from_file_location('archive_evidence', SCRIPT)
archive_evidence = importlib.util.module_from_spec(spec)
spec.loader.exec_module(archive_evidence)


def test_large_text_files_are_packed_with_hashes_and_small_files_stay(tmp_path):
    big = tmp_path / 'receipts.json'
    big.write_text('[' + ','.join(['{"a": 1}'] * 20_000) + ']')
    small = tmp_path / 'summary.json'
    small.write_text('{"ok": true}')
    report = tmp_path / 'REPORT.md'
    report.write_text('# report')
    digest = hashlib.sha256(big.read_bytes()).hexdigest()

    rows = archive_evidence.pack(tmp_path)

    assert [r[0] for r in rows] == ['receipts.json']
    assert not big.exists() and small.exists() and report.exists()
    assert digest in (tmp_path / 'EVIDENCE.md').read_text()
    with tarfile.open(tmp_path / 'evidence.tar.gz') as tar:
        data = tar.extractfile('receipts.json').read()
    assert hashlib.sha256(data).hexdigest() == digest


def test_the_same_files_give_the_same_archive_bytes(tmp_path):
    for name in ('one', 'two'):
        folder = tmp_path / name
        folder.mkdir()
        (folder / 'big.jsonl').write_text('{"x": 1}\n' * 20_000)
        archive_evidence.pack(folder)
    assert (tmp_path / 'one/evidence.tar.gz').read_bytes() == (tmp_path / 'two/evidence.tar.gz').read_bytes()
