import importlib.util
from pathlib import Path
import pytest


def test_baseline_comparison_keeps_published_length_basis():
    spec = importlib.util.spec_from_file_location('hull_runner', Path(__file__).parents[1] / 'scripts/check_hull_variation.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    rows = module.compare_particulars(dict(length_m=300, breadth_m=58, draft_m=20,
                                           volume_m3=300000, wetted_surface_m2=26000))
    assert rows['length_m']['published'] == 320
    assert rows['length_m']['difference'] == -20
    assert rows['cb']['sampled'] == pytest.approx(300000 / (320 * 58 * 20.8))
