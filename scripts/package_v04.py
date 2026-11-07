"""Build a manifest-verified 0.4 source/evidence release with explicit data rights.

The old generic packager is not suitable for this release's restricted dataset.
This tool reads tracked source and completed evidence, preserves originals, uses
the exact public-data allowlist, and can apply an independently reviewed export
plan to release copies only. It never reads credential inputs or uploads files.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path, PurePosixPath
import stat
import subprocess
import zipfile


BASE = "5b0b48e3dd9bcef25427d27ce800118935f58d1a"
APPLICATION_FREEZE = "8916e68f4c175bdab291d7c0bf2978862be8915d"
PACKAGE_ROOT = "MarinaFrame-0.4"


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def safe_relative(name: str) -> str:
    path = PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts or not path.parts or "\\" in name:
        raise ValueError("Unsafe release-relative path")
    return path.as_posix()


def snapshot(path: Path) -> dict:
    if path.is_symlink() or not path.is_file():
        raise ValueError("Release input is not an ordinary file")
    raw = path.read_bytes()
    return {"sha256": digest(raw), "bytes": len(raw),
            "mode": stat.S_IMODE(path.stat().st_mode)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--supplement", type=Path, required=True,
                        help="Reviewed release-only files, including git bundle and patch")
    parser.add_argument("--evidence-inventory", type=Path, required=True,
                        help="Reviewed completed-evidence snapshot; historical failures remain included")
    parser.add_argument("--evidence-inventory-sha256", required=True)
    parser.add_argument("--export-plan", type=Path,
                        help="JSON exclusions and replacements, each bound to original SHA-256")
    args = parser.parse_args()
    repo = args.repo.resolve(strict=True)
    out = args.out.absolute()
    if out.exists():
        raise SystemExit("Refusing to overwrite an existing release")
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()
    if subprocess.check_output(["git", "diff", "--name-only", "HEAD"], cwd=repo):
        raise SystemExit("Commit tracked source/documentation changes before release")
    if subprocess.check_output(["git", "ls-files", "--others", "--exclude-standard"], cwd=repo):
        raise SystemExit("Untracked source is outside the release inventory; resolve it explicitly")
    subprocess.run(["git", "merge-base", "--is-ancestor", BASE, "HEAD"], cwd=repo, check=True)
    subprocess.run(["git", "diff", "--exit-code", APPLICATION_FREEZE, "HEAD", "--",
                    "src", "rust-control/src", "Cargo.toml", "Cargo.lock",
                    "rust-control/Cargo.toml", "rust-toolchain.toml", "pyproject.toml",
                    "requirements-linux-py312.lock", "requirements-data-linux-py312.lock"],
                   cwd=repo, check=True, stdout=subprocess.DEVNULL)
    tracked = subprocess.check_output(["git", "ls-files", "-z"], cwd=repo).decode().split("\0")
    inventory: dict[str, Path] = {}
    tracked_names = list(filter(None, tracked))
    tracked_snapshots = {}
    for name in tracked_names:
        relative = safe_relative(name)
        if relative.startswith("artifacts/"):
            raise SystemExit("Evidence must be admitted by the explicit evidence rules")
        inventory[relative] = repo / relative
        current = snapshot(inventory[relative])
        committed = subprocess.check_output(["git", "cat-file", "blob", f"{head}:{relative}"], cwd=repo)
        if current["sha256"] != digest(committed) or current["bytes"] != len(committed):
            raise SystemExit("Tracked source differs from the named delivery commit")
        tracked_snapshots[relative] = current

    data_root = repo / "artifacts/v04/data"
    allow_path = data_root / "release-allowlist.json"
    allow_snapshot = snapshot(allow_path)
    allow = json.loads(allow_path.read_text())
    if snapshot(allow_path) != allow_snapshot:
        raise SystemExit("Data allowlist changed during admission")
    permitted = {safe_relative(row["file"]): row for row in allow["files"]}
    if len(permitted) != len(allow["files"]):
        raise SystemExit("Duplicate data release allowlist entry")
    for name, row in permitted.items():
        if name == "restricted" or name.startswith("restricted/"):
            raise SystemExit("Restricted data entered the public allowlist")
        path = data_root / name
        raw = path.read_bytes()
        if digest(raw) != row["sha256"] or len(raw) != row["bytes"]:
            raise SystemExit("Data release allowlist identity mismatch")

    excluded_data = []
    evidence = repo / "artifacts/v04"
    evidence_inventory_raw = args.evidence_inventory.read_bytes()
    if digest(evidence_inventory_raw) != args.evidence_inventory_sha256:
        raise SystemExit("Completed-evidence inventory identity differs")
    evidence_inventory = json.loads(evidence_inventory_raw)
    if (evidence_inventory.get("schema_version") != "marinaframe.completed-evidence-admission.v1"
            or evidence_inventory.get("delivery_commit") != head
            or evidence_inventory.get("application_freeze") != APPLICATION_FREEZE):
        raise SystemExit("Completed-evidence snapshot has a different delivery/runtime identity")
    evidence_rows = evidence_inventory.get("files", [])
    expected_evidence = {safe_relative(row["path"]): row for row in evidence_rows}
    if not evidence_rows or len(expected_evidence) != len(evidence_rows):
        raise SystemExit("Empty or duplicate completed-evidence inventory")
    admitted_evidence = {}
    for path in sorted(evidence.rglob("*")):
        if path.is_symlink():
            raise SystemExit("Symlink in release evidence")
        if not path.is_file():
            continue
        name = path.relative_to(repo).as_posix()
        if path.is_relative_to(data_root):
            data_name = path.relative_to(data_root).as_posix()
            if data_name != "release-allowlist.json" and data_name not in permitted:
                excluded_data.append(data_name)
                continue
        inventory[name] = path
        admitted_evidence[name] = path
    if set(admitted_evidence) != set(expected_evidence):
        raise SystemExit("Completed-evidence file set differs from the reviewed snapshot")
    for name, path in admitted_evidence.items():
        if snapshot(path) != {k: expected_evidence[name][k] for k in ("sha256", "bytes", "mode")}:
            raise SystemExit("Completed-evidence identity differs from the reviewed snapshot")

    supplement = args.supplement.resolve(strict=True)
    for path in sorted(supplement.rglob("*")):
        if path.is_symlink():
            raise SystemExit("Symlink in release supplement")
        if path.is_file():
            name = safe_relative(path.relative_to(supplement).as_posix())
            if name in inventory:
                raise SystemExit("Supplement would overwrite source/evidence")
            inventory[name] = path

    plan = json.loads(args.export_plan.read_text()) if args.export_plan else {}
    exclusions = {safe_relative(row["path"]): row for row in plan.get("exclude", [])}
    replacements = {safe_relative(row["path"]): row for row in plan.get("replace", [])}
    if set(exclusions) & set(replacements):
        raise SystemExit("Conflicting export-plan action")
    for name, row in {**exclusions, **replacements}.items():
        if name not in inventory or digest(inventory[name].read_bytes()) != row["original_sha256"]:
            raise SystemExit("Export-plan original identity mismatch")
    replacement_snapshots = {}
    for name, row in replacements.items():
        replacement = Path(row["replacement_file"]).resolve(strict=True)
        identity = snapshot(replacement)
        if identity["sha256"] != row["replacement_sha256"]:
            raise SystemExit("Export-plan replacement identity mismatch")
        replacement_snapshots[name] = identity
        inventory[name] = replacement
    for name in exclusions:
        del inventory[name]

    # Re-enforce the data boundary after supplements and transformations. A
    # matching prefix is not authorization to append or replace a data item.
    data_prefix = "artifacts/v04/data/"
    expected_data = {data_prefix + name: row for name, row in permitted.items()}
    expected_data[data_prefix + "release-allowlist.json"] = allow_snapshot
    admitted_data = {name: path for name, path in inventory.items() if name.startswith(data_prefix)}
    if set(admitted_data) != set(expected_data):
        raise SystemExit("Final data inventory differs from the exact release allowlist")
    for name, path in admitted_data.items():
        current = snapshot(path)
        expected = expected_data[name]
        if current["sha256"] != expected["sha256"] or current["bytes"] != expected["bytes"]:
            raise SystemExit("Final data identity differs from the exact release allowlist")
    admitted = {name: snapshot(path) for name, path in inventory.items()}
    for name, expected in replacement_snapshots.items():
        if admitted[name] != expected or admitted[name]["sha256"] != replacements[name]["replacement_sha256"]:
            raise SystemExit("Reviewed replacement changed after export-plan admission")
    for name, expected in tracked_snapshots.items():
        if name in exclusions or name in replacements:
            continue  # The original and reviewed transformation are separately bound above.
        if admitted[name] != expected:
            raise SystemExit("Tracked source changed after delivery-commit comparison")
    for name, expected in expected_data.items():
        if admitted[name]["sha256"] != expected["sha256"] or admitted[name]["bytes"] != expected["bytes"]:
            raise SystemExit("Data changed between final allowlist check and snapshot")
    for name, expected in expected_evidence.items():
        if name in exclusions or name in replacements:
            continue
        if admitted[name] != {k: expected[k] for k in ("sha256", "bytes", "mode")}:
            raise SystemExit("Evidence changed after reviewed-snapshot admission")
    if "docs/V04_REPORT.md" not in inventory or "git/MarinaFrame-0.4.git.bundle" not in inventory:
        raise SystemExit("Required report/history is missing")
    bundle = inventory["git/MarinaFrame-0.4.git.bundle"]
    bundle_heads = subprocess.check_output(["git", "bundle", "list-heads", str(bundle)], text=True)
    if not any(line.split()[0] == head for line in bundle_heads.splitlines()):
        raise SystemExit("Git bundle does not contain the named delivery HEAD")
    subprocess.run(["git", "bundle", "verify", str(bundle)], cwd=repo, check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    report = inventory["docs/V04_REPORT.md"].read_text()
    if any(text in report for text in ("report draft", "still being reconciled", "being locked and scored", "This draft paragraph", "The release version will")):
        raise SystemExit("Final report still has unfinished-result language")

    out.parent.mkdir(parents=True, exist_ok=True)
    temporary = out.with_suffix(out.suffix + ".pending")
    if temporary.exists():
        raise SystemExit("Incomplete release already exists; preserve it before a new attempt")
    manifest_rows = []
    with zipfile.ZipFile(temporary, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for name, path in sorted(inventory.items()):
            if path.is_symlink() or not path.is_file():
                raise SystemExit("Release file changed kind")
            raw = path.read_bytes()
            current = {"sha256": digest(raw), "bytes": len(raw),
                       "mode": stat.S_IMODE(path.stat().st_mode)}
            if current != admitted[name]:
                raise SystemExit("Release input changed after admission; preserving incomplete archive")
            row = {"path": name, "bytes": len(raw), "sha256": digest(raw)}
            if name in replacements:
                row["release_copy_transformation"] = replacements[name]["reason"]
                row["original_sha256"] = replacements[name]["original_sha256"]
            manifest_rows.append(row)
            info = zipfile.ZipInfo(f"{PACKAGE_ROOT}/{name}", date_time=(2026, 11, 7, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = (current["mode"] | stat.S_IFREG) << 16
            archive.writestr(info, raw, compresslevel=6)
        manifest = {
            "schema_version": "marinaframe.release-manifest.v1",
            "base_commit": BASE,
            "application_freeze": APPLICATION_FREEZE,
            "delivery_commit": head,
            "files": manifest_rows,
            "file_count": len(manifest_rows),
            "source_bytes": sum(row["bytes"] for row in manifest_rows),
            "public_data_allowlist_sha256": allow_snapshot["sha256"],
            "completed_evidence_inventory_sha256": args.evidence_inventory_sha256,
            "omitted_data_paths": excluded_data,
            "export_plan": {"exclude": list(exclusions.values()),
                            "replace": [{k: v for k, v in r.items() if k != "replacement_file"}
                                        for r in replacements.values()]},
            "engineering_approved": False,
            "remote_publication_performed": False,
            "scope": "Tracked source/history plus completed evidence. Restricted data is omitted; failures are retained.",
        }
        archive.writestr(f"{PACKAGE_ROOT}/RELEASE_MANIFEST.json",
                         json.dumps(manifest, indent=2, allow_nan=False) + "\n")
    with zipfile.ZipFile(temporary) as archive:
        expected = {f"{PACKAGE_ROOT}/{row['path']}": row for row in manifest_rows}
        if set(archive.namelist()) != set(expected) | {f"{PACKAGE_ROOT}/RELEASE_MANIFEST.json"}:
            raise SystemExit("Archive inventory differs")
        for name, row in expected.items():
            raw = archive.read(name)
            if len(raw) != row["bytes"] or digest(raw) != row["sha256"]:
                raise SystemExit("Archive member verification failed")
    temporary.replace(out)
    receipt = {"schema_version": "marinaframe.release-receipt.v1",
               "path": str(out), "bytes": out.stat().st_size,
               "sha256": digest(out.read_bytes()), "delivery_commit": head,
               "application_freeze": APPLICATION_FREEZE,
               "file_count": len(manifest_rows), "source_bytes": manifest["source_bytes"],
               "every_member_hash_and_inventory_verified": True,
               "created_utc": datetime.now(timezone.utc).isoformat()}
    out.with_suffix(".json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps(receipt, indent=2), flush=True)


if __name__ == "__main__":
    main()
