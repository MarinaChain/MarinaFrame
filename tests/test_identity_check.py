import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("identity_check", ROOT / "scripts/check_identity.py")
identity = importlib.util.module_from_spec(spec)
spec.loader.exec_module(identity)


def test_normalized_and_sensitive_rules():
    rules = identity.parse_rules("# private\nZorbax Works\ncs:Qiv\n")
    assert identity.identity_hits("ZORBAX---works", rules)
    assert identity.identity_hits(" Qiv()", rules)
    assert not identity.identity_hits("qiv Qivmore", rules)
    assert identity.identity_hits("Zorbax\nWorks", rules)


def test_native_fingerprints_and_allowlist(tmp_path):
    path = tmp_path / "kernels/src/sample.c"
    path.parent.mkdir(parents=True)
    value = "0x" + "a" * 9
    path.write_text(value)
    assert identity.scan_paths(tmp_path, [path], [], [])
    allowed = [{"path": "kernels/src/sample.c", "kind": "address", "value": value}]
    assert not identity.scan_paths(tmp_path, [path], [], allowed)
    path.write_text("b" * 64)
    assert identity.scan_paths(tmp_path, [path], [], [])


def test_paths_binary_and_redacted_cli(tmp_path, capsys, monkeypatch):
    path = tmp_path / "Zorbax.bin"
    path.write_bytes(b"\x00Zorbax\xff")
    rules = identity.parse_rules("Zorbax")
    hits = identity.scan_paths(tmp_path, [path], rules, [])
    assert len(hits) >= 2
    identity.report(hits)
    assert "zorbax" not in capsys.readouterr().out.lower()


def test_missing_list_warns(monkeypatch, capsys):
    monkeypatch.delenv("MF_IDENTITY_DENYLIST", raising=False)
    monkeypatch.delenv("MF_IDENTITY_DENYLIST_FILE", raising=False)
    assert identity.load_rules() == []
    assert "warning" in capsys.readouterr().err.lower()


def test_seeded_cli_failure(tmp_path):
    (tmp_path / "sample.c").write_text("int Zorbax;")
    env = dict(os.environ, MF_IDENTITY_DENYLIST="Zorbax")
    env.pop("MF_IDENTITY_DENYLIST_FILE", None)
    result = subprocess.run([sys.executable, "-I", str(ROOT / "scripts/check_identity.py"),
                             "--root", str(tmp_path), "--tree"],
                            env=env, capture_output=True, text=True)
    assert result.returncode == 1
    assert "Zorbax" not in result.stdout + result.stderr


def test_pm_binary_policy(tmp_path):
    rules = identity.parse_rules("Qiv\ncs:Zorbax\nVeltrona\n")
    assert len(rules) - len(identity.binary_rules(rules)) == 2
    path = tmp_path / "sample.bin"
    path.write_bytes(b"\xff Qiv Zorbax \x00")
    assert not identity.scan_paths(tmp_path, [path], rules, [])
    path.write_bytes(b"\xff VELTRONA \x00")
    assert identity.scan_paths(tmp_path, [path], rules, [])
    path.write_bytes(b"\xff" + "Veltrona".encode("utf-16-le"))
    assert identity.scan_paths(tmp_path, [path], rules, [])
    path.write_text(" Qiv Zorbax ")
    assert identity.scan_paths(tmp_path, [path], rules, [])
    renamed = tmp_path / "Qiv.bin"
    renamed.write_bytes(b"\xff\x00")
    assert identity.scan_paths(tmp_path, [renamed], rules, [])


def test_native_binary_refused_without_list(tmp_path):
    path = tmp_path / "kernels/sample.dat"
    path.parent.mkdir()
    path.write_bytes(b"\x00\xff")
    assert (1, 0, "binary-native") in identity.scan_paths(tmp_path, [path], [], [])
    outside = tmp_path / "sample.c"
    outside.write_bytes(b"\x00\xff")
    assert identity.scan_paths(tmp_path, [outside], [], [], native_tree=True)


def test_cli_binary_skipped_count(tmp_path):
    env = dict(os.environ, MF_IDENTITY_DENYLIST="Qiv\ncs:Zorbax\nVeltrona")
    env.pop("MF_IDENTITY_DENYLIST_FILE", None)
    result = subprocess.run([sys.executable, "-I", str(ROOT / "scripts/check_identity.py"),
                             "--root", str(tmp_path), "--tree"],
                            env=env, capture_output=True, text=True)
    assert result.returncode == 0
    assert "binary-skipped entry count: 2" in result.stdout
    assert "Zorbax" not in result.stdout + result.stderr


def test_links_fail_closed(tmp_path):
    source = tmp_path / "source.c"
    source.write_text("clean")
    link = tmp_path / "link.c"
    link.symlink_to(source)
    assert identity.scan_paths(tmp_path, [link], [], [])
