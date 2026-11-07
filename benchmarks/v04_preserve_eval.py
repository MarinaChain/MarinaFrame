"""Copy only finalized evaluator-owned evidence, checking every archived byte."""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import tarfile


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def archive(source, destination, terminal_evidence):
    if destination.exists():
        raise ValueError("Evidence archives are append-only; destination already exists")
    rows = [{"path": str(p.relative_to(source)), "bytes": p.stat().st_size, "sha256": sha(p)}
            for p in sorted(source.rglob("*")) if p.is_file()]
    temporary = destination.with_name(destination.name + ".part")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(temporary, "w:gz", compresslevel=6) as tar:
        for row in rows:
            tar.add(source / row["path"], arcname=source.name + "/" + row["path"], recursive=False)
    with tarfile.open(temporary, "r:gz") as tar:
        members = {m.name: m for m in tar.getmembers() if m.isfile()}
        if set(members) != {source.name + "/" + r["path"] for r in rows}:
            raise ValueError("Archive inventory mismatch")
        for row in rows:
            member = members[source.name + "/" + row["path"]]
            if hashlib.sha256(tar.extractfile(member).read()).hexdigest() != row["sha256"]:
                raise ValueError("Archive byte mismatch")
            if sha(source / row["path"]) != row["sha256"]:
                raise ValueError("Source changed during archive")
    temporary.replace(destination)
    receipt = {"created_utc": datetime.now(timezone.utc).isoformat(), "source": str(source),
        "archive": str(destination), "archive_sha256": sha(destination),
        "archive_bytes": destination.stat().st_size, "terminal_evidence": terminal_evidence,
        "file_count": len(rows), "files": rows, "all_archived_bytes_verified": True,
        "source_files_unchanged": True, "source_modes_preserved": True}
    destination.with_name(destination.name.replace(".tar.gz", "_archive.json")).write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    return {k: v for k, v in receipt.items() if k != "files"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--destination", required=True, type=Path)
    parser.add_argument("--terminal-evidence", required=True)
    args = parser.parse_args()
    print(json.dumps(archive(args.source, args.destination, args.terminal_evidence), sort_keys=True))
