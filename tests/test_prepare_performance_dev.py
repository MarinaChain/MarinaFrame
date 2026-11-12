"""Public data preparation rejects missing CAD inputs without scanning ships."""
from pathlib import Path
import importlib.util
import pytest


def test_iges_preparation_rejects_missing_explicit_input(tmp_path):
    path=Path(__file__).resolve().parents[1]/"scripts"/"prepare_performance_dev.py"
    spec=importlib.util.spec_from_file_location("prepare_performance_dev",path)
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with pytest.raises(ValueError,match="cannot read IGES"):
        module.read_iges_mesh(tmp_path/"missing.igs")
