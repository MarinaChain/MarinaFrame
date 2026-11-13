#!/usr/bin/env python3
"""Scan identities without exposing private rules or matching source in logs."""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys


def normalize(text):
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def parse_rules(text):
    rules = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        sensitive = line.startswith("cs:")
        token = line[3:] if sensitive else normalize(line)
        if not token:
            raise ValueError("empty identity rule")
        rules.append((sensitive, token))
    return rules


def load_rules():
    text = os.environ.get("MF_IDENTITY_DENYLIST", "")
    filename = os.environ.get("MF_IDENTITY_DENYLIST_FILE")
    if filename:
        text += "\n" + Path(filename).read_text(encoding="utf-8")
    rules = parse_rules(text)
    if not rules:
        print("warning: no identity list configured; identity rules skipped", file=sys.stderr)
    return rules


def identity_hits(text, rules):
    normalized = normalize(text)
    return [index for index, (sensitive, token) in enumerate(rules)
            if (re.search(r"(?<!\w)" + re.escape(token) + r"(?!\w)", text)
                if sensitive else token in normalized)]


FINGERPRINTS = {
    "address": re.compile(r"\b0x[0-9a-fA-F]{7,}\b"),
    "hash": re.compile(r"(?<![0-9a-fA-F])[0-9a-fA-F]{64}(?![0-9a-fA-F])"),
}
NATIVE_SUFFIXES = {".c", ".h", ".cc", ".cpp", ".hpp", ".rs", ".f", ".f90"}


def binary_rules(rules):
    return [(sensitive, token) for sensitive, token in rules
            if not sensitive and len(normalize(token)) >= 6]


def decode_source(raw):
    """UTF-8 text excludes NUL-bearing binary records."""
    text = raw.decode("utf-8")
    if "\x00" in text:
        raise UnicodeError("binary content")
    return text


def scan_paths(root, paths, rules, allowlist, *, native_tree=False):
    """Return (file ordinal, line, category), never private values or paths."""
    findings = []
    for ordinal, path in enumerate(paths, 1):
        relative = path.relative_to(root).as_posix()
        if identity_hits(relative, rules):
            findings.append((ordinal, 0, "identity-path"))
        if path.is_symlink() or any(parent.is_symlink() for parent in path.parents if parent != root.parent):
            findings.append((ordinal, 0, "link"))
            continue
        try:
            raw = path.read_bytes()
        except OSError:
            findings.append((ordinal, 0, "unreadable"))
            continue
        try:
            texts = [decode_source(raw)]
            active_rules = rules
        except UnicodeError:
            if native_tree or relative.startswith("kernels/"):
                findings.append((ordinal, 0, "binary-native"))
            # Latin-1 preserves each raw byte, including separators, for the
            # existing ASCII normalization rules. Also check text layers already
            # extracted by this scanner; no archive or PDF parser is invoked.
            texts = [raw.decode("latin-1")]
            for encoding, pattern in (("utf-16-le", rb"(?:[\x20-\x7e]\x00){4,}"),
                                      ("utf-16-be", rb"(?:\x00[\x20-\x7e]){4,}")):
                texts.extend(item.decode(encoding) for item in re.findall(pattern, raw))
            active_rules = binary_rules(rules)
        for text in texts:
            whole_hits = set(identity_hits(text, active_rules))
            line_hits = set()
            for line_number, line in enumerate(text.splitlines(), 1):
                line_hits.update(identity_hits(line, active_rules))
                if identity_hits(line, active_rules):
                    findings.append((ordinal, line_number, "identity-content"))
                if relative.startswith("kernels/") and path.suffix.lower() in NATIVE_SUFFIXES:
                    for kind, pattern in FINGERPRINTS.items():
                        for match in pattern.finditer(line):
                            entry = {"path": relative, "kind": kind, "value": match.group()}
                            if entry not in allowlist:
                                findings.append((ordinal, line_number, kind))
            if whole_hits - line_hits:
                findings.append((ordinal, 0, "identity-multiline"))
    return findings


def report(findings):
    for ordinal, line, category in findings:
        print(f"file #{ordinal}, line {line}: {category}")
    print(f"identity scan: {len(findings)} finding(s)")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--tree", action="store_true", help="scan every file instead of tracked files")
    args = parser.parse_args()
    root = args.root.resolve()
    try:
        rules = load_rules()
        print(f"binary-skipped entry count: {len(rules) - len(binary_rules(rules))}")
        allowlist = json.loads((Path(__file__).with_name("identity_allowlist.json")).read_text())
        if args.tree:
            paths = sorted(path for path in root.rglob("*") if not path.is_dir() or path.is_symlink())
        else:
            listing = subprocess.check_output(["git", "-C", str(root), "ls-files", "-z"])
            paths = [root / os.fsdecode(name) for name in listing.split(b"\0") if name]
        findings = scan_paths(root, paths, rules, allowlist)
        report(findings)
        return bool(findings)
    except (OSError, ValueError, subprocess.SubprocessError):
        print("identity scan: configuration or input error (details redacted)", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
