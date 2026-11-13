"""Design-loop plumbing contracts; synthetic inputs are not accuracy evidence."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from vessel_reconstruction.design_record import DesignRecord, restore_result


def empty_record():
    data = json.loads(Path('tests/fixtures/design_record/kvlcc2.json').read_text())
    data['main_dimensions'] = {}
    return DesignRecord.from_dict(data)


def test_fragment_adapter_preserves_bands_missing_and_vector_metadata():
    from vessel_reconstruction.design_loop.evidence import fragment_evidence
    fragment = {'q': dict(value=10., unit='m', uncertainty={'kind': 'absolute_band',
        'lower': 8., 'upper': 13., 'basis': 'training envelope'}, method='fit',
        method_version='1', sources=['synthetic'], status='review_required'),
        'missing': dict(value=None, unit='m', uncertainty={'reason': 'not supplied'},
        method='input', method_version='1', sources=['synthetic'], status='review_required')}
    evidence = fragment_evidence(fragment)
    q = evidence['value']['q']['value']
    assert q['uncertainty'] == dict(kind='absolute', lower=2., upper=3., basis='training envelope')
    assert q['method'] == 'fit'
    assert evidence['value']['missing']['value']['value']['kind'] == 'missing'
    vector = deepcopy(fragment['q'])
    vector['value'] = [10., 12.]
    vector['uncertainty'] = {'reason': 'unknown'}
    result = fragment_evidence(vector)
    assert [item['value']['method'] for item in result['value']] == ['fit', 'fit']


def test_graph_caches_owned_patches_and_invalidates_by_input_content(tmp_path):
    from vessel_reconstruction.design_loop.graph import Step, run_graph
    from vessel_reconstruction.design_record import quantity
    base = empty_record()
    calls = []
    def calculate(record):
        calls.append('a')
        data = record.to_dict()
        data['main_dimensions']['length'] = quantity(100., 'm', method='test', method_version='1', sources=['synthetic'])
        return DesignRecord.from_dict(data)
    step = Step('dimension', '1', (('requirements',),), (('main_dimensions',),), calculate)
    first, receipt = run_graph(base, [step], tmp_path)
    assert receipt.executed == ('dimension',)
    second, receipt = run_graph(base, [step], tmp_path)
    assert receipt.cached == ('dimension',)
    assert first.to_json() == second.to_json()
    assert calls == ['a']
    changed = base.to_dict()
    changed['name'] = 'unrelated change survives cached patch'
    result, receipt = run_graph(DesignRecord.from_dict(changed), [step], tmp_path)
    assert result.to_dict()['name'] == changed['name']
    assert receipt.executed == ()
    changed['requirements']['cargo_types'] = ['product oil']
    _, receipt = run_graph(DesignRecord.from_dict(changed), [step], tmp_path)
    assert receipt.executed == ('dimension',)
    step_v2 = Step('dimension', '2', step.reads, step.writes, calculate)
    _, receipt = run_graph(base, [step_v2], tmp_path)
    assert receipt.executed == ('dimension',)


def test_graph_rejects_corrupt_cache_and_unowned_writes(tmp_path):
    from vessel_reconstruction.design_loop.graph import Step, run_graph
    base = empty_record()
    def bad(record):
        data = record.to_dict()
        data['name'] = 'not owned'
        return DesignRecord.from_dict(data)
    step = Step('test', '1', (('requirements',),), (('main_dimensions',),), bad)
    with pytest.raises(ValueError, match='unowned'):
        run_graph(base, [step], tmp_path)
    good = Step('test', '1', step.reads, step.writes, lambda record: record)
    run_graph(base, [good], tmp_path)
    entry = next(tmp_path.glob('*.json'))
    entry.write_text('{"broken":true}')
    with pytest.raises(ValueError, match='cache'):
        run_graph(base, [good], tmp_path)


def synthetic_config():
    import numpy as np
    from vessel_reconstruction.hull_variation import HullSections, section_properties
    x = np.array([0., 10., 30., 70., 90., 100.])
    fullness = np.array([.15, .7, 1., 1., .7, .15])
    parent = HullSections(x, np.array([0., 4., 10., 15.]),
        10 * fullness[:, None] * np.array([.8, 1., 1., 1.])[None, :], 100, 20, 10, (30, 70))
    cb, _ = section_properties(parent)
    return dict(design_id='synthetic-loop', name='Synthetic integration', sources=['synthetic plumbing only'],
        requirements=dict(dwt_t=10000., service_speed_kn=10., cargo_types=['product oil']),
        fleet=[dict(ship_id=f'synthetic-{i}', design_id=f'synthetic-{i}', dwt_t=dwt,
            lpp_m=100., beam_m=20., draft_m=10., depth_m=15., cb=cb,
            sources=['synthetic plumbing fleet']) for i, dwt in enumerate([5000., 8000., 12000., 20000.])],
        parent={key: value.tolist() if hasattr(value, 'tolist') else value for key, value in vars(parent).items()},
        parent_sources=['synthetic non-box hull'],
        arrangement=dict(cargo_rows=2, cargo_columns=2, engine_room_length_m=15., forepeak_length_m=8.,
            slop_length_m=5., slop_columns=2, fuel_reserve_length_m=3.),
        weights=dict(narrow_house_lh_m2=200., wide_house_lh_m2=100., steel_coefficient=.03,
            outfit_t_m2=.3, machinery_rest_coefficient=.72, main_engine_mass_t=250., mcr_kw=10000.,
            component_cg_m=[[50., 0., 7.], [55., 0., 12.], [15., 0., 5.]],
            component_relative_bands=[.2, .25, .3], band_basis='synthetic sensitivity'),
        power=dict(water_density_kg_m3=1025., kinematic_viscosity_m2_s=1.19e-6,
            thrust_deduction=.2, wake_fraction=.3, open_water_efficiency=.65,
            relative_rotative_efficiency=1., shaft_efficiency=.98),
        engine=dict(rpm=80., sea_margin=.15, minimum_engine_margin=.05, maximum_engine_margin=.95,
            layouts=[dict(name='synthetic engine', vertices=[[60., 500.], [100., 500.], [100., 10000.], [60., 10000.]],
                sfoc_by_load=[[.05, 185.], [.5, 175.], [.75, 170.], [1., 180.]],
                sources=['synthetic tuning table'], sfoc_rating_kw=10000., sfoc_rating_rpm=80.)]),
        efficiency=dict(reference_speed_kn=9., auxiliary_sfoc_g_kwh=190., main_fuel='HFO', auxiliary_fuel='MDO',
            distance_nm=40000., fuel_t=[['HFO', 3000.]], year=2026,
            sources=['synthetic reference-power speed; not service speed or statutory evidence']))


@pytest.mark.cad
def test_pipeline_real_modules_cache_and_speed_dependency(tmp_path):
    from vessel_reconstruction.design_loop import create_record, run_pipeline
    config = synthetic_config()
    record, receipt = run_pipeline(create_record(config), tmp_path)
    assert receipt.executed == ('concept', 'hull', 'arrangement', 'weights', 'power', 'engine', 'efficiency')
    assert record.to_dict()['status'] == 'draft'
    assert record.to_dict()['engineering_approved'] is False
    assert record.to_dict()['tanks']
    assert record.to_dict()['weights']
    assert 'eedi' in record.to_dict()['results']['fuel']
    again, receipt = run_pipeline(create_record(config), tmp_path)
    assert receipt.executed == ()
    assert record.to_json() == again.to_json()
    config['requirements']['service_speed_kn'] = 10.5
    changed, receipt = run_pipeline(create_record(config), tmp_path)
    assert receipt.executed == ('concept', 'power', 'engine', 'efficiency')
    assert changed.to_dict()['main_dimensions'] == record.to_dict()['main_dimensions']
    config['efficiency']['distance_nm'] = 42000.
    _, receipt = run_pipeline(create_record(config), tmp_path)
    assert receipt.executed == ('efficiency',)
    edited = changed.to_dict()
    edited['requirements']['quantities']['dwt']['value'] = 11000.
    _, receipt = run_pipeline(DesignRecord.from_dict(edited), tmp_path)
    assert 'concept' in receipt.executed and 'arrangement' in receipt.executed
    assert 'hull' not in receipt.executed


def test_cli_runs_config_then_record_without_recomputing(tmp_path):
    import os
    import subprocess
    import sys
    config = tmp_path / 'config.json'
    config.write_text(json.dumps(synthetic_config()))
    output, receipt = tmp_path / 'record.json', tmp_path / 'receipt.json'
    command = [sys.executable, 'scripts/design_loop.py', '--cache', str(tmp_path / 'cache'),
        '--out', str(output), '--receipt', str(receipt)]
    env = {**os.environ, 'PYTHONPATH': str(Path('src').resolve())}
    subprocess.run(command + ['--config', str(config)], env=env, check=True, capture_output=True)
    assert len(json.loads(receipt.read_text())['executed']) == 7
    subprocess.run(command + ['--record', str(output)], env=env, check=True, capture_output=True)
    assert json.loads(receipt.read_text())['executed'] == []


def test_input_table_columns_and_parent_metadata_keep_units():
    from vessel_reconstruction.design_loop.evidence import fragment_evidence
    evidence = fragment_evidence({'vertices': [[80., 10000.]], 'sfoc_by_load': [[.75, 170.]],
        'fuel_t': [['HFO', 3000.]], 'x_m': [1., 2.]})['value']
    assert [q['value']['unit'] for q in evidence['vertices']['value'][0]['value']] == ['rpm', 'kW']
    assert [q['value']['unit'] for q in evidence['sfoc_by_load']['value'][0]['value']] == ['1', 'g/kWh']
    assert evidence['fuel_t']['value'][0]['value'][1]['value']['unit'] == 't'
    assert evidence['x_m']['value'][0]['value']['unit'] == 'm'


def test_pipeline_api_and_required_sources():
    from vessel_reconstruction.design_loop import create_record
    with pytest.raises(ValueError, match='sources'):
        create_record({**synthetic_config(), 'sources': []})


def test_graph_rejects_unordered_dependencies_and_colliding_owners(tmp_path):
    from vessel_reconstruction.design_loop.graph import Step, run_graph
    a = Step('a', '1', (('requirements',),), (('main_dimensions',),), lambda r: r)
    b = Step('b', '1', (('main_dimensions',),), (('weights',),), lambda r: r, depends_on=('a',))
    with pytest.raises(ValueError, match='dependency'):
        run_graph(empty_record(), [b, a], tmp_path)
    with pytest.raises(ValueError, match='overlap'):
        run_graph(empty_record(), [a, Step('duplicate', '1', a.reads, a.writes, lambda r: r)], tmp_path)
