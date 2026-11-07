"""Controlled byte-integrity probe for workspace and /tmp publication/copy.

Only locally generated fixture bytes are used. This is a filesystem observation,
not a diagnosis of the platform or a replacement for native transaction checks.
Keep the expectation manifest in /tmp and verify it in separate invocations.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import random
import shutil
import subprocess
import time


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x") as stream:
        json.dump(value, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())


def snapshot(root):
    files = {}
    directories = []
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        if path.is_symlink():
            raise ValueError("Unexpected symlink in controlled fixture")
        if path.is_dir():
            directories.append(relative)
        elif path.is_file():
            files[relative] = {"sha256": digest(path), "bytes": path.stat().st_size}
        else:
            raise ValueError("Unexpected nonregular fixture entry")
    return {"files": files, "directories": directories}


def transaction(root, index, payload):
    root.mkdir(parents=True, exist_ok=False)
    lock = root / ".candidate.run-lock"
    stage = root / ".candidate.staging-controlled"
    target = root / "candidate"
    write_json(lock, {"fixture": True, "phase": "writing", "iteration": index})
    stage.mkdir()
    write_json(stage / "transaction.json", {"fixture": True, "phase": "writing", "iteration": index})
    for name, data in payload.items():
        with (stage / name).open("xb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
    (stage / "transaction.json").unlink()
    write_json(stage / "result.json", {"fixture": True, "phase": "complete", "iteration": index,
                                      "files": {n: hashlib.sha256(b).hexdigest() for n, b in payload.items()}})
    os.rename(stage, target)
    lock.unlink()
    fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
    assert not lock.exists() and not stage.exists()
    return target


def initialize(args):
    workspace, temporary = args.workspace.resolve(), args.temporary.resolve()
    for path in (workspace, temporary):
        path.mkdir(parents=True, exist_ok=False)
    randomizer = random.Random(20261106)
    records = []
    start = time.time_ns()
    for index in range(args.iterations):
        payload = {
            "binary.bin": randomizer.randbytes((4096, 16384, 65536)[index % 3]),
            "float-json.json": (json.dumps({"fixture": True, "iteration": index,
                "values": [0.896516, 43.264475, 0.0811489, 4.902467602, 1.2345678901234567]},
                sort_keys=True, separators=(",", ":")) + "\n").encode(),
        }
        tmp_case = temporary / "active-publication" / f"case-{index:03d}"
        work_case = workspace / "active-publication" / f"case-{index:03d}"
        tmp_published = transaction(tmp_case, index, payload)
        work_published = transaction(work_case, index, payload)
        work_copy = workspace / "completed-copy-from-tmp" / f"case-{index:03d}"
        tmp_copy = temporary / "completed-copy-from-workspace" / f"case-{index:03d}"
        shutil.copytree(tmp_published, work_copy)
        shutil.copytree(work_published, tmp_copy)
        for lane, root in (("tmp_active", tmp_case), ("workspace_active", work_case),
                           ("workspace_completed_copy", work_copy), ("tmp_completed_copy", tmp_copy)):
            records.append({"lane": lane, "root": str(root), "expected": snapshot(root)})
    manifest = {"schema_version": "marinaframe.copy-probe.v1", "fixture_only": True,
        "created_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "duration_seconds": (time.time_ns() - start) / 1e9, "iterations": args.iterations,
        "workspace": str(workspace), "temporary": str(temporary), "records": records,
        "identity_method": "Exact byte SHA-256 and directory/file inventory; no JSON reserialization"}
    write_json(args.manifest, manifest)
    print(json.dumps({"manifest": str(args.manifest), "sha256": digest(args.manifest),
                      "completed_trees": len(records), "files": sum(len(r["expected"]["files"]) for r in records)}))


def verify(args):
    manifest_bytes = args.manifest.read_bytes()
    manifest = json.loads(manifest_bytes)
    differences = []
    stats = []
    sampled = []
    for index, record in enumerate(manifest["records"]):
        root = Path(record["root"])
        try:
            actual = snapshot(root)
        except (OSError, ValueError) as error:
            differences.append({"root": str(root), "lane": record["lane"], "error": type(error).__name__})
            continue
        expected = record["expected"]
        if actual != expected:
            differences.append({"root": str(root), "lane": record["lane"], "expected": expected, "actual": actual})
        if index % 16 < 4:  # Sample every lane, not only one surface.
            relative = sorted(expected["files"])[0]
            path = root / relative
            info = path.stat()
            stats.append({"path": str(path), "inode": info.st_ino, "device": info.st_dev,
                          "mtime_ns": info.st_mtime_ns, "ctime_ns": info.st_ctime_ns,
                          "bytes": info.st_size, "sha256": digest(path)})
            sampled.append(path)
    # A different implementation independently checks sampled raw hashes.
    command = subprocess.run(["sha256sum", "--", *map(str, sampled)], check=True,
                             capture_output=True, text=True, timeout=20)
    independent = []
    for path, line in zip(sampled, command.stdout.splitlines()):
        hashed = line.split(maxsplit=1)[0]
        independent.append({"path": str(path), "sha256": hashed, "matches_python": hashed == digest(path)})
    report = {"schema_version": "marinaframe.copy-probe-result.v1", "fixture_only": True,
        "checked_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "expectation_manifest": str(args.manifest),
        "expectation_manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
        "completed_trees": len(manifest["records"]),
        "files_checked": sum(len(r["expected"]["files"]) for r in manifest["records"]),
        "differences": differences, "sampled_filesystem_metadata": stats,
        "independent_sha256sum": independent,
        "passed": not differences and all(r["matches_python"] for r in independent),
        "limits": "Finite controlled fixture observation; no native workload, no root-cause inference, not a guarantee about future copies"}
    write_json(args.output, report)
    print(json.dumps({"output": str(args.output), "passed": report["passed"],
                      "files_checked": report["files_checked"], "differences": len(differences)}))
    return 0 if report["passed"] else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    init = sub.add_parser("initialize")
    init.add_argument("--workspace", type=Path, required=True)
    init.add_argument("--temporary", type=Path, required=True)
    init.add_argument("--manifest", type=Path, required=True)
    init.add_argument("--iterations", type=int, default=48)
    check = sub.add_parser("verify")
    check.add_argument("--manifest", type=Path, required=True)
    check.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "initialize":
        if not 1 <= args.iterations <= 100:
            parser.error("iterations must be between 1 and 100")
        initialize(args)
        return 0
    return verify(args)


if __name__ == "__main__":
    raise SystemExit(main())
