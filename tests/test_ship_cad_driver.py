"""Synthetic provider-driver transforms and stop policy."""
import importlib
import pytest


def driver():
    spec = importlib.util.find_spec('benchmarks.ship_cad.run')
    assert spec is not None, 'Ship CAD driver is not implemented'
    return importlib.import_module('benchmarks.ship_cad.run')


def test_normalized_region_maps_actual_attachment_to_dxf():
    d = driver()
    assert d.region_bounds([100, 200, 600, 800], [10, 20, 110, 220]) == pytest.approx([20, 60, 70, 180])


def test_no_progress_requires_new_success_not_new_failed_regions():
    d = driver()
    a = {'outline': {'status': 'failed', 'reason': 'no closed outline'}}
    b = {'outline2': {'status': 'failed', 'reason': 'no closed outline'}}
    assert d.progress_key(a) == d.progress_key(b)
    assert d.progress_key({'a': {'status': 'measured', 'value': [1, 2]}}) != d.progress_key(a)
