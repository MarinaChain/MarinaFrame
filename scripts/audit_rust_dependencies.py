"""Audit exact public package versions and capture installed Cargo licenses.

Network requests contain only ecosystem/package/version metadata. All advisory
classes, including informational and unmaintained reports, are retained. This
does not scan native bundled libraries, the OS, compiler or application source.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tomllib
import urllib.parse
import urllib.request
import uuid


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n")


def fetch(url, payload=None, maximum=16 * 1024**2):
    request = urllib.request.Request(url,
        data=None if payload is None else json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "User-Agent": "MarinaFrame-public-package-audit/0.4"},
        method="GET" if payload is None else "POST")
    with urllib.request.urlopen(request, timeout=30) as response:
        raw = response.read(maximum + 1)
    if len(raw) > maximum:
        raise ValueError("Advisory response exceeds audit bounds")
    return json.loads(raw)


def audit_osv(packages, ecosystem, directory):
    queries = [{"package": {"name": p["name"], "ecosystem": ecosystem}, "version": p["version"]} for p in packages]
    write(directory / "query.json", {"queries": queries})
    report = {"database": "OSV", "endpoint": "https://api.osv.dev/v1/querybatch", "ecosystem": ecosystem,
        "checked": len(queries), "time_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "scope": "Exact public package names/versions; all returned advisory classes; no exclusions",
        "project_source_or_credentials_transmitted": False, "findings": [], "errors": []}
    try:
        response = fetch(report["endpoint"], {"queries": queries})
        write(directory / "response.json", response)
        results = response["results"]
        if len(results) != len(packages):
            raise ValueError("Incomplete OSV batch response")
        for package, result in zip(packages, results):
            if result.get("next_page_token"):
                raise ValueError("OSV pagination requires explicit follow-up; audit is incomplete")
            for item in result.get("vulns", []):
                identifier = item["id"]
                detail = fetch("https://api.osv.dev/v1/vulns/" + urllib.parse.quote(identifier, safe=""))
                write(directory / "advisories" / (identifier + ".json"), detail)
                affected = [a for a in detail.get("affected", []) if a.get("package", {}).get("name", "").lower().replace("_", "-") == package["name"].lower().replace("_", "-")]
                classifications = sorted({a.get("database_specific", {}).get("informational", "vulnerability") for a in affected})
                report["findings"].append({"package": package["name"], "version": package["version"], "id": identifier,
                    "summary": detail.get("summary"), "classifications": classifications,
                    "withdrawn": detail.get("withdrawn"), "affected": affected,
                    "references": detail.get("references", []), "advisory_file": "advisories/" + identifier + ".json"})
        report["status"] = "completed"
    except (OSError, ValueError, KeyError, TypeError) as error:
        report.update(status="incomplete")
        report["errors"].append(type(error).__name__ + ": " + str(error)[:300])
    write(directory / "audit.json", report)
    return report


def cargo_command(cargo, root, *arguments):
    result = subprocess.run([cargo, *arguments], cwd=root, text=True, capture_output=True, timeout=120)
    if result.returncode:
        raise ValueError("Cargo metadata command failed: " + result.stderr[:1000])
    return result.stdout


def license_inventory(metadata, locked, production, directory):
    rows, combined = [], ["# Third-party Cargo license and notice inventory\n",
        "These are installed upstream files, preserved verbatim below. Declared license expressions are metadata, not legal clearance.\n"]
    for package in sorted(metadata["packages"], key=lambda p: (p["name"], p["version"])):
        if not package.get("source", "") or not package["source"].startswith("registry+"):
            continue
        name, version = package["name"], package["version"]
        source = Path(package["manifest_path"]).parent
        row = {"name": name, "version": version, "purl": f"pkg:cargo/{name}@{version}",
            "license_expression": package.get("license"), "license_file_declared": package.get("license_file"),
            "repository": package.get("repository"), "links_native_library": package.get("links"),
            "linux_normal_or_build_dependency": (name, version) in production, "files": [], "problems": []}
        archive = source.parent.parent.parent / "cache" / source.parent.name / f"{name}-{version}.crate"
        expected = locked[(name, version)]["checksum"]
        row["lock_checksum"] = expected
        row["downloaded_crate_archive_verified"] = archive.is_file() and sha(archive) == expected
        if not row["downloaded_crate_archive_verified"]:
            row["problems"].append("Downloaded crate archive is absent or does not match lock checksum")
        files = []
        for path in source.rglob("*"):
            lower = path.name.lower()
            if path.is_file() and (lower.startswith(("license", "licence", "copying", "notice", "copyright", "authors")) or lower.endswith((".license", ".license.txt"))):
                files.append(path)
        if package.get("license_file"):
            explicit = source / package["license_file"]
            if explicit.is_file() and explicit not in files:
                files.append(explicit)
        for path in sorted(files):
            if path.is_symlink() or not path.resolve().is_relative_to(source.resolve()) or path.stat().st_size > 4 * 1024**2:
                row["problems"].append("License/notice path was unsafe or exceeded bounds: " + path.name)
                continue
            relative = path.relative_to(source)
            destination = directory / "licenses" / f"{name}-{version}" / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, destination)
            row["files"].append({"source_relative_path": relative.as_posix(), "output": destination.relative_to(directory).as_posix(), "sha256": sha(destination), "bytes": destination.stat().st_size})
            combined.extend([f"\n## {name} {version} — {relative.as_posix()}\n", destination.read_text(errors="replace") + "\n"])
        if not row["files"]:
            row["problems"].append("No conventional license/notice files found in installed crate; declared SPDX metadata retained")
        rows.append(row)
    (directory / "THIRD_PARTY_CARGO_NOTICES.txt").write_text("".join(combined))
    write(directory / "cargo-license-inventory.json", rows)
    return rows


def make_sbom(metadata, locked, inventory, production, directory, target):
    notices = {(p["name"], p["version"]): p for p in inventory}
    packages = {(p["name"], p["version"]): p for p in metadata["packages"]}
    components = []
    for key, package in sorted(locked.items()):
        name, version = key
        manifest = packages.get(key)
        row = {"type": "library", "name": name, "version": version, "bom-ref": f"pkg:cargo/{name}@{version}",
            "purl": f"pkg:cargo/{name}@{version}", "hashes": [{"alg": "SHA-256", "content": package["checksum"]}],
            "scope": "required" if key in production else "optional", "properties": [
                {"name": "marinaframe:license_manifest_available", "value": str(manifest is not None).lower()},
                {"name": "marinaframe:linux_normal_or_build_dependency", "value": str(key in production).lower()}]}
        if manifest and manifest.get("license"):
            expression = manifest["license"].replace("MIT/Apache-2.0", "MIT OR Apache-2.0")
            row["licenses"] = [{"expression": expression}]
        if key in notices:
            row["properties"].append({"name": "marinaframe:license_file_count", "value": str(len(notices[key]["files"]))})
        components.append(row)
    ids = {p["id"]: f"pkg:cargo/{p['name']}@{p['version']}" for p in metadata["packages"]}
    graph = [{"ref": ids[n["id"]], "dependsOn": sorted({ids[d["pkg"]] for d in n["deps"] if d["pkg"] in ids})} for n in metadata["resolve"]["nodes"]]
    root_id = metadata["resolve"].get("root")
    if root_id is None:
        members = metadata.get("workspace_default_members", metadata["workspace_members"])
        if len(members) != 1:
            raise ValueError("SBOM application identity requires one explicit workspace default member")
        root_id = members[0]
    main = next(p for p in metadata["packages"] if p["id"] == root_id)
    sbom = {"bomFormat": "CycloneDX", "specVersion": "1.6", "serialNumber": "urn:uuid:" + str(uuid.uuid4()), "version": 1,
        "metadata": {"timestamp": dt.datetime.now(dt.timezone.utc).isoformat(), "component": {
            "type": "application", "name": main["name"], "version": main["version"], "bom-ref": ids[main["id"]],
            "licenses": [{"license": {"name": "All rights reserved; existing workspace LICENSE"}}]},
            "properties": [{"name": "marinaframe:target", "value": target}, {"name": "marinaframe:scope", "value": "Entire Cargo.lock component list; target-filtered dependency graph, including tests/build tools; bundled native and OS components not comprehensively enumerated"}]},
        "components": components, "dependencies": graph}
    write(directory / "cargo-sbom.cdx.json", sbom)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--cargo", default="cargo")
    parser.add_argument("--target", default="x86_64-unknown-linux-gnu")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--optional-python-lock", type=Path)
    args = parser.parse_args()
    root, out = args.root.resolve(), args.out.resolve()
    out.mkdir(parents=True, exist_ok=False)
    lock = root / "Cargo.lock"; before = sha(lock)
    data = tomllib.loads(lock.read_text())
    locked = {(p["name"], p["version"]): p for p in data["package"] if p.get("source", "").startswith("registry+")}
    metadata_raw = cargo_command(args.cargo, root, "metadata", "--locked", "--offline", "--format-version", "1", "--filter-platform", args.target)
    (out / "cargo-metadata.json").write_text(metadata_raw)
    metadata = json.loads(metadata_raw)
    tree = cargo_command(args.cargo, root, "tree", "--locked", "--offline", "--target", args.target, "--edges", "normal,build", "--prefix", "none", "--format", "{p}")
    (out / "cargo-normal-build-tree.txt").write_text(tree)
    production = {tuple(match.groups()) for line in tree.splitlines() if (match := re.match(r"^(\S+) v([^ ]+)", line))}
    inventory = license_inventory(metadata, locked, production, out)
    make_sbom(metadata, locked, inventory, production, out, args.target)
    osv = audit_osv([{"name": k[0], "version": k[1]} for k in sorted(locked)], "crates.io", out / "rust-osv")
    optional = None
    if args.optional_python_lock:
        package_lines = [line.split()[0].split("==") for line in args.optional_python_lock.read_text().splitlines() if line.strip() and not line.startswith("#")]
        optional = audit_osv([{"name": n, "version": v} for n, v in package_lines], "PyPI", out / "optional-python-osv")
    summary = {"time_utc": dt.datetime.now(dt.timezone.utc).isoformat(), "target": args.target,
        "cargo_lock_sha256": before, "cargo_lock_unchanged_during_audit": sha(lock) == before,
        "locked_external_packages": len(locked), "target_metadata_packages": len(metadata["packages"]),
        "linux_normal_or_build_external_packages": len(production & set(locked)),
        "license_inventories": len(inventory), "license_file_count": sum(len(x["files"]) for x in inventory),
        "license_inventory_problems": [{"name": x["name"], "version": x["version"], "problems": x["problems"]} for x in inventory if x["problems"]],
        "all_installed_crate_archives_match_lock": all(x["downloaded_crate_archive_verified"] for x in inventory),
        "off_target_or_uninstalled_license_metadata": [{"name": n, "version": v} for n, v in sorted(set(locked) - {(x["name"], x["version"]) for x in inventory})],
        "rust_osv_status": osv["status"], "rust_findings": osv["findings"],
        "optional_python_status": None if optional is None else optional["status"],
        "optional_python_findings": None if optional is None else optional["findings"],
        "limitations": ["No native bundled-library, OS, compiler/toolchain or proprietary-license clearance", "No exclusions applied to Rust or optional Python findings", "No project source or credentials transmitted", "Target-filtered installed manifests do not establish off-target redistribution rights"]}
    write(out / "summary.json", summary)
    print(json.dumps(summary, indent=2))
    if not summary["cargo_lock_unchanged_during_audit"] or osv["status"] != "completed" or (optional and optional["status"] != "completed"):
        return 2
    return 1 if osv["findings"] or (optional and optional["findings"]) else 0


if __name__ == "__main__":
    raise SystemExit(main())
