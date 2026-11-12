"""Synthetic development-runner boundaries and duplicate-method handling."""
import importlib.util
from pathlib import Path

import pytest


def runner():
    path = Path(__file__).parents[1]/'scripts/calibrate_performance.py'
    spec = importlib.util.spec_from_file_location('calibrate_performance', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_development_runner_exists():
    assert (Path(__file__).parents[1]/'scripts/calibrate_performance.py').exists()


def test_runner_allowlist_and_unique_conditions():
    from test_performance_compare import synthetic_case
    module = runner()
    case = synthetic_case()
    case.update(ship='KCS', method='holtrop_1984')
    assert len(module.prepare_points([case])) == 1
    with pytest.raises(ValueError, match='duplicate'):
        module.prepare_points([case, case])
    case['ship'] = 'unexposed'
    with pytest.raises(ValueError, match='development'):
        module.prepare_points([case])


def test_kvlcc2_evaluator_labels_group_as_one_ship():
    from test_performance_compare import synthetic_case
    case = synthetic_case()
    case.update(ship='KVLCC2 MOERI 1:58 bare hull, Fn 0.142 (source)', method='holtrop_1984')
    points = runner().prepare_points([case])
    assert points[0].ship == 'KVLCC2'


def test_runner_reports_all_folds_and_rows():
    from test_performance_compare import synthetic_case
    module = runner()
    cases = []
    for ship in ('KCS','JBC','KVLCC2'):
        case = synthetic_case()
        case.update(ship=ship, method='holtrop_1984')
        cases.append(case)
    result = module.calibrate(cases)
    assert set(result['leave_one_ship_out']) == {'KCS','JBC','KVLCC2'}
    assert len(result['rows']) == 3
    assert all(r['loo_ct_error_percent'] is not None for r in result['rows'])
    assert result['engineering_approved'] is False
