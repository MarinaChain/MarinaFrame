import importlib.util
import json
from pathlib import Path
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("intake", ROOT / "tools/cleanroom/intake.py")
intake = importlib.util.module_from_spec(spec)
spec.loader.exec_module(intake)


def fixture(tmp_path):
    source = tmp_path / "input"
    source.mkdir()
    mapping = tmp_path / "mapping.json"
    mapping.write_text(json.dumps({"Zorbax": "mf_sample"}))
    return source, mapping, tmp_path / "output"


def test_clean_source_compiles(tmp_path, monkeypatch):
    source, mapping, output = fixture(tmp_path)
    monkeypatch.setenv("MF_IDENTITY_DENYLIST", "Zorbax")
    (source / "Zorbax.c").write_text('/* Zorbax private comment */\nint Zorbax(void) { return 7; }\n')
    (source / "Zorbax.h").write_text("int Zorbax(void);\n")
    original = (source / "Zorbax.c").read_text()
    (source / "Zorbax.c").write_text('#include "Zorbax.h"\n' + original)
    before = mapping.read_bytes()
    intake.convert(source, mapping, output)
    result = (output / "mf_sample.c").read_text()
    assert "Zorbax" not in result
    assert "int mf_sample(void)" in result
    subprocess.run(["cc", "-fsyntax-only", str(output / "mf_sample.c")], check=True)
    assert mapping.read_bytes() == before
    assert (source / "Zorbax.c").exists()


def test_residual_string_fails_without_output(tmp_path, monkeypatch):
    source, mapping, output = fixture(tmp_path)
    monkeypatch.setenv("MF_IDENTITY_DENYLIST", "Zorbax")
    (source / "sample.c").write_text('const char *s = "Zorbax";')
    with pytest.raises(ValueError):
        intake.convert(source, mapping, output)
    assert not output.exists()


def test_collision_and_output_replacement(tmp_path, monkeypatch):
    source, mapping, output = fixture(tmp_path)
    monkeypatch.setenv("MF_IDENTITY_DENYLIST", "Zorbax")
    (source / "Zorbax.c").write_text("int Zorbax;")
    (source / "mf_sample.c").write_text("int other;")
    with pytest.raises(ValueError):
        intake.convert(source, mapping, output)
    output.mkdir()
    with pytest.raises(ValueError):
        intake.convert(source, mapping, output)


def test_missing_denylist_and_overlap_fail(tmp_path, monkeypatch):
    source, mapping, output = fixture(tmp_path)
    monkeypatch.delenv("MF_IDENTITY_DENYLIST", raising=False)
    monkeypatch.delenv("MF_IDENTITY_DENYLIST_FILE", raising=False)
    with pytest.raises(ValueError):
        intake.convert(source, mapping, output)
    monkeypatch.setenv("MF_IDENTITY_DENYLIST", "Zorbax")
    with pytest.raises(ValueError):
        intake.convert(source, mapping, source / "nested")


def test_tokens_and_comments():
    rules = intake.identity.parse_rules("Zorbax")
    text = 'int Zorbax; int Zorbax_extra; char *s="// safe"; // Zorbax\n'
    result = intake.transform(text, {"Zorbax": "mf_sample"}, rules)
    assert "int mf_sample; int Zorbax_extra;" in result
    assert '"// safe"' in result
    assert result.endswith("\n")


def test_unsupported_literal_syntax_fails():
    for text in ['const char *s = R"(text)";', 'int x; \\\nint y;']:
        with pytest.raises(ValueError):
            intake.transform(text, {"Zorbax": "mf_sample"}, [])


@pytest.mark.parametrize("raw", [b"int sample;\x00", b"\xff\xfe"])
def test_binary_source_rejected(tmp_path, monkeypatch, raw):
    source, mapping, output = fixture(tmp_path)
    monkeypatch.setenv("MF_IDENTITY_DENYLIST", "Zorbax")
    (source / "sample.c").write_bytes(raw)
    with pytest.raises(ValueError):
        intake.convert(source, mapping, output)
    assert not output.exists()


def test_link_rejected(tmp_path, monkeypatch):
    source, mapping, output = fixture(tmp_path)
    monkeypatch.setenv("MF_IDENTITY_DENYLIST", "Zorbax")
    (source / "link.c").symlink_to(mapping)
    with pytest.raises(ValueError):
        intake.convert(source, mapping, output)
