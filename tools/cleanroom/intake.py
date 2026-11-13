#!/usr/bin/env python3
"""Offline neutral C/C++ source intake. Private inputs are never executed."""
import argparse
import importlib.util
import json
from pathlib import Path
import re
import shutil
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("identity_check", ROOT / "scripts/check_identity.py")
identity = importlib.util.module_from_spec(spec)
spec.loader.exec_module(identity)
IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z_0-9]*\Z")
# Strings and character literals must be consumed before comment delimiters.
TOKENS = re.compile(r'"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'|/\*.*?\*/|//[^\n]*|[A-Za-z_][A-Za-z_0-9]*', re.DOTALL)
SUFFIXES = {".c", ".h", ".cc", ".cpp", ".hpp"}


def transform(text, mapping, rules):
    # This small lexer does not claim full preprocessing or raw-literal support.
    # Reject ambiguous syntax rather than rename inside a literal or comment.
    if re.search(r"\\\r?\n", text) or 'R"' in text:
        raise ValueError("line splices and raw literals require manual neutralization")
    def replace(match):
        token = match.group()
        if token.startswith(("//", "/*")):
            contaminated = identity.identity_hits(token, rules) or any(name in token for name in mapping)
            contaminated = contaminated or any(pattern.search(token) for pattern in identity.FINGERPRINTS.values())
            if contaminated:
                return "".join("\n" if char == "\n" else " " for char in token)
            return token
        if token.startswith(('"', "'")):
            return token
        return mapping.get(token, token)
    result = TOKENS.sub(replace, text)
    # Include paths are filenames, not program string values. Keep references
    # aligned with the renamed source tree without rewriting other literals.
    def rename_include(match):
        path = re.sub(r"[A-Za-z_][A-Za-z_0-9]*", lambda token: mapping.get(token.group(), token.group()), match.group(2))
        return match.group(1) + path + match.group(3)
    return re.sub(r'(^[ \t]*#[ \t]*include[ \t]*["<])([^"<>\n]+)([">])',
                  rename_include, result, flags=re.MULTILINE)


def _overlap(left, right):
    return left == right or left in right.parents or right in left.parents


def convert(source, mapping_file, output):
    source, mapping_file, output = Path(source), Path(mapping_file), Path(output)
    if source.is_symlink() or mapping_file.is_symlink() or output.is_symlink():
        raise ValueError("links are not supported")
    source, mapping_file, output = source.resolve(), mapping_file.resolve(), output.absolute()
    if not source.is_dir() or output.exists() or _overlap(source, output.resolve()):
        raise ValueError("invalid input or output location")
    if ROOT == mapping_file or ROOT in mapping_file.parents or source in mapping_file.parents:
        raise ValueError("mapping must be private and outside the source tree")
    if any(parent.is_symlink() for parent in output.parents):
        raise ValueError("output parent links are not supported")
    mapping = json.loads(mapping_file.read_text(encoding="utf-8"))
    if not isinstance(mapping, dict) or not mapping:
        raise ValueError("mapping must be a nonempty JSON object")
    if not all(isinstance(key, str) and isinstance(value, str) and IDENTIFIER.fullmatch(key) and IDENTIFIER.fullmatch(value)
               for key, value in mapping.items()):
        raise ValueError("mapping entries must be C identifiers")
    if len(set(mapping.values())) != len(mapping) or set(mapping) & set(mapping.values()):
        raise ValueError("mapping targets must be distinct and not source names")
    rules = identity.load_rules()
    if not rules:
        raise ValueError("intake requires an identity list")
    # Include all private original symbols even if the caller's list omits them.
    rules += [(True, name) for name in mapping]
    files = sorted(source.rglob("*"))
    if any(path.is_symlink() for path in files):
        raise ValueError("source links are not supported")
    files = [path for path in files if path.is_file()]
    if not files or any(path.suffix.lower() not in SUFFIXES for path in files):
        raise ValueError("only C/C++ source and headers are supported")
    output.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".neutral-intake-", dir=output.parent))
    try:
        destinations = set()
        for path in files:
            parts = [re.sub(r"[A-Za-z_][A-Za-z_0-9]*", lambda m: mapping.get(m.group(), m.group()), part)
                     for part in path.relative_to(source).parts]
            relative = Path(*parts)
            # Case-fold for portable filesystems, even on a case-sensitive host.
            key = relative.as_posix().casefold()
            if key in destinations:
                raise ValueError("output path collision")
            destinations.add(key)
            destination = staging / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(transform(identity.decode_source(path.read_bytes()), mapping, rules), encoding="utf-8")
        paths = sorted(path for path in staging.rglob("*") if path.is_file())
        # Intake checks fingerprints in every output source, regardless of path.
        findings = []
        for path in paths:
            findings.extend(identity.scan_paths(staging, [path], rules, [], native_tree=True))
            text = path.read_text(encoding="utf-8")
            if any(pattern.search(text) for pattern in identity.FINGERPRINTS.values()):
                findings.append((0, 0, "native-fingerprint"))
        if findings:
            raise ValueError("output failed identity checks")
        if output.exists():
            raise ValueError("output already exists")
        staging.rename(output)
    finally:
        if staging.exists():
            shutil.rmtree(staging)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("mapping", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    try:
        convert(args.source, args.mapping, args.output)
    except (OSError, ValueError):
        print("intake failed: private details redacted", file=sys.stderr)
        return 1
    print("intake completed: output passed identity checks")
    return 0


if __name__ == "__main__":
    sys.exit(main())
