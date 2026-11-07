"""Truth scores must not treat missing or hull-only references as complete truth."""
import importlib


def scorer():
    spec = importlib.util.find_spec('benchmarks.ship_cad.score')
    assert spec is not None, 'Component scorer is not implemented'
    return importlib.import_module('benchmarks.ship_cad.score')


def test_component_bbox_and_volume_error():
    c = {'built':True,'bbox_m':{'min':[0,0,0],'max':[2,1,1]},'volume_m3':2}
    t = {'bbox_m':{'min':[0,0,0],'max':[2,2,1]},'volume_m3':4}
    result = scorer().component_score(c,t)
    assert result['presence'] == 'built'
    assert result['bbox_max_error_m'] == 1
    assert result['volume_error_relative'] == -0.5


def test_upperworks_without_truth_are_unscorable():
    result = scorer().component_score({'built':False},None)
    assert result['presence'] == 'missing'
    assert result['bbox_max_error_m'] is None
    assert result['volume_error_relative'] is None
    assert result['truth_status'] == 'no_component_truth'
