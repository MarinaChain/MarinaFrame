"""CI path routing must reduce work without dropping shared-code checks."""
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
ALL = {"python", "rust", "ui", "wheel"}


@pytest.mark.parametrize(
    ("paths", "expected"),
    [
        (["docs/guide.txt", "README.md", "tasks/lessons.md", "work/pm-briefs/a.txt"], set()),
        (["app/ui/styles.css"], {"ui"}),
        (["app/ui/js/deleted file.js", "app/ui-tests/shell.test.mjs"], {"ui"}),
        (["src/vessel_reconstruction/runtime.py"], {"python", "rust", "wheel"}),
        (["tests/test_runtime.py"], {"python", "rust", "wheel"}),
        (["crates/control/src/lib.rs", "app/core/src/lib.rs"], {"rust", "wheel"}),
        (["app/src-tauri/src/main.rs"], {"rust", "wheel"}),
        (["docs/guide.md", "app/ui/index.html"], {"ui"}),
        ([".github/workflows/ci.yml"], ALL),
        (["docs/dependency-scope-exclusions.json"], ALL),
        (["app/package-lock.json"], ALL),
        (["app/package.json"], ALL),
        (["crates/control/Cargo.toml"], ALL),
        (["Cargo.lock"], ALL),
        (["pyproject.toml"], ALL),
        (["requirements-lock.txt"], ALL),
        (["requirements-linux-py312.lock"], ALL),
        (["Makefile"], ALL),
        (["scripts/ci_changes.sh"], ALL),
        (["new-unknown-folder/file.txt"], ALL),
        ([], set()),
    ],
)
def test_ci_path_suites(paths, expected):
    result = subprocess.run(
        ["bash", str(ROOT / "scripts/ci_changes.sh")],
        input="".join(path + "\0" for path in paths),
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    flags = dict(line.split("=", 1) for line in result.stdout.splitlines())
    assert set(flags) == ALL
    assert {suite for suite, enabled in flags.items() if enabled == "true"} == expected
    assert set(flags.values()) <= {"true", "false"}
