"""Exercise Make's cache selection without compiling or changing a real cache."""

import os
from pathlib import Path
import shutil
import subprocess

import pytest


MAKEFILE = Path(__file__).resolve().parents[1] / "Makefile"


def git(root, *args):
    return subprocess.run(["git", "-C", str(root), *args], check=True,
                          capture_output=True, text=True).stdout.strip()


@pytest.fixture
def checkouts(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    git(root, "init", "-q")
    shutil.copyfile(MAKEFILE, root / "Makefile")
    git(root, "add", "Makefile")
    git(root, "-c", "user.name=Test", "-c", "user.email=test@example.invalid",
        "commit", "-qm", "initial")
    linked = tmp_path / "linked"
    git(root, "worktree", "add", "-qb", "lane-test", str(linked))
    return root, linked


def make_output(root, *args, environment=None):
    env = {key: value for key, value in os.environ.items()
           if key not in {"CI", "CARGO_TARGET_DIR", "MAKEFLAGS", "MFLAGS", "MAKELEVEL"}
           and not key.startswith("GIT_")}
    env.update(environment or {})
    # The extra makefile exposes the exported value; no Rust commands execute.
    result = subprocess.run(
        ["make", "--no-print-directory", "-f", "Makefile", "-f", "-", *args],
        input=".PHONY: cache-value\ncache-value:\n\t@printf '%s\\n' \"$$CARGO_TARGET_DIR\"\n",
        cwd=root, env=env, check=True, capture_output=True, text=True)
    return result.stdout.strip()


def test_main_and_linked_checkout_share_target(checkouts):
    root, linked = checkouts
    expected = root / '.claude/worktrees/shared-target-sol'
    assert Path(make_output(root, 'cache-value')) == expected
    assert Path(make_output(linked, 'cache-value')) == expected


@pytest.mark.parametrize("ci", ["true", "1"])
def test_ci_keeps_local_target(checkouts, ci):
    root, _ = checkouts
    assert make_output(root, "cache-value", environment={"CI": ci}) == "target"


@pytest.mark.parametrize("ci", ["", "true"])
def test_explicit_target_overrides_default(checkouts, ci):
    root, linked = checkouts
    env = {"CI": ci, "CARGO_TARGET_DIR": "custom-target"}
    assert make_output(linked, "cache-value", environment=env) == "custom-target"
    assert make_output(root, "cache-value", "CARGO_TARGET_DIR=command-target",
                       environment=env) == "command-target"


@pytest.mark.parametrize("target", ["relative-cache", "/absolute/cache"])
def test_smoke_uses_selected_target(checkouts, target):
    _, linked = checkouts
    output = make_output(linked, "-n", "smoke", f"CARGO_TARGET_DIR={target}")
    binary = ((linked / target).resolve() / 'release/marinaframe').as_posix()
    assert f'"{binary}" run ' in output
    assert f'"{binary}" verify ' in output
    assert "\n target/release/marinaframe" not in output


def test_source_archive_keeps_local_target(tmp_path):
    shutil.copyfile(MAKEFILE, tmp_path / "Makefile")
    assert make_output(tmp_path, "cache-value") == "target"
