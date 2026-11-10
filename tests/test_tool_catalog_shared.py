import ast
import json
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile

from vessel_reconstruction.agent_tools import DomainTools
from vessel_reconstruction.investigation_tools import INVESTIGATION_ARGUMENTS
from vessel_reconstruction.rust_worker import OPERATIONS

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / 'src/vessel_reconstruction/tool_catalog.json'


def test_shared_catalog_matches_python_handlers_and_worker_operations():
    tools = json.loads(CATALOG.read_text())
    operations = {tool['operation'] for tool in tools if tool['route'] == 'worker'}
    assert len(operations) == sum(tool['route'] == 'worker' for tool in tools)
    for operation in operations - {'initialize', 'observe'}:
        assert callable(getattr(DomainTools, '_' + operation, None)), operation
    tree = ast.parse((ROOT / 'src/vessel_reconstruction/agent_tools.py').read_text())
    arguments = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == '_arguments')
    expected = next(node.value for node in arguments.body if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'expected' for t in node.targets))
    handlers = {key.value for key in expected.keys if isinstance(key, ast.Constant)} | set(INVESTIGATION_ARGUMENTS)
    assert operations == handlers | {'initialize', 'observe'}
    assert OPERATIONS == operations


def test_wheel_contains_shared_catalog(tmp_path):
    project = tmp_path / 'project'
    project.mkdir()
    for name in ('pyproject.toml', 'README.md', 'LICENSE'):
        shutil.copy(ROOT / name, project / name)
    shutil.copytree(ROOT / 'src', project / 'src', ignore=shutil.ignore_patterns('__pycache__', '*.egg-info'))
    wheel_dir = tmp_path / 'wheel'
    wheel_dir.mkdir()
    subprocess.run([sys.executable, '-m', 'pip', 'wheel', '--no-deps', '--no-build-isolation', '--no-index', '--wheel-dir', str(wheel_dir), str(project)], check=True, capture_output=True, text=True)
    with zipfile.ZipFile(next(wheel_dir.glob('*.whl'))) as wheel:
        assert json.loads(wheel.read('vessel_reconstruction/tool_catalog.json')) == json.loads(CATALOG.read_text())
