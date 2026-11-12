"""Check holdout metadata without importing harnesses or reading any truth."""
from __future__ import annotations

import ast
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
HOLDOUT_MODULES = sorted((ROOT / 'benchmarks').glob('*/holdout_value.py'))
VALID_STATUSES = {'blind', 'spent', 'development'}


@pytest.mark.parametrize('module_path', HOLDOUT_MODULES, ids=lambda path: path.parent.name)
def test_holdout_module_declares_valid_status(module_path: Path) -> None:
    tree = ast.parse(module_path.read_text())
    declarations = [
        node for node in tree.body
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == 'STATUS' for target in node.targets)
    ]
    assert len(declarations) == 1, f'{module_path}: declare STATUS once'
    assert ast.literal_eval(declarations[0].value) in VALID_STATUSES


def test_registry_matches_all_holdout_modules() -> None:
    registry = ROOT / 'docs/holdouts/REGISTRY.md'
    assert registry.is_file(), 'missing holdout registry'
    rows = []
    for line in registry.read_text().splitlines():
        if line.startswith('| ') and 'benchmarks/' in line and 'holdout_value.py' in line:
            cells = [cell.strip().strip('`') for cell in line.strip('|').split('|')]
            # Table columns: sheet, kind, module, protocol, blind run, result, status, evidence.
            assert len(cells) == 8, line
            rows.append((cells[2], cells[6]))
    assert len(rows) == len(dict(rows)), 'duplicate holdout module in registry'
    assert {path for path, _ in rows} == {
        path.relative_to(ROOT).as_posix() for path in HOLDOUT_MODULES
    }
    for relative_path, status in rows:
        tree = ast.parse((ROOT / relative_path).read_text())
        declared = [
            ast.literal_eval(node.value) for node in tree.body
            if isinstance(node, ast.Assign)
            and any(isinstance(target, ast.Name) and target.id == 'STATUS' for target in node.targets)
        ]
        assert declared == [status], relative_path
        assert status in VALID_STATUSES
