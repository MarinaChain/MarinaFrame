"""Runner summaries and phase boundary do not spend model requests."""
import importlib.util
from pathlib import Path

import pytest


def runner():
    path = Path(__file__).resolve().parents[1] / 'scripts/measure_polyline_position_names.py'
    spec = importlib.util.spec_from_file_location('position_runner_test', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_zero_coverage_has_zero_wrong_cells_not_a_crash():
    summary = runner().compact({'cells_given': 0}, 30)
    assert summary['given'] == summary['correct'] == summary['wrong'] == 0
    assert summary['missing'] == 30
    assert summary['rms_m'] is None


def test_score_refuses_without_all_nine_predictions(tmp_path):
    from types import SimpleNamespace
    import json
    (tmp_path / 'prediction_manifest.json').write_text(json.dumps({'all_nine_predicted': False}))
    with pytest.raises(RuntimeError, match='all-nine'):
        runner().score(SimpleNamespace(out=tmp_path))
