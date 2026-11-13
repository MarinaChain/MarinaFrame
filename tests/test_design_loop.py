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


def test_graph_rejects_unordered_dependencies_and_colliding_owners(tmp_path):
    from vessel_reconstruction.design_loop.graph import Step, run_graph
    a = Step('a', '1', (('requirements',),), (('main_dimensions',),), lambda r: r)
    b = Step('b', '1', (('main_dimensions',),), (('weights',),), lambda r: r, depends_on=('a',))
    with pytest.raises(ValueError, match='dependency'):
        run_graph(empty_record(), [b, a], tmp_path)
    with pytest.raises(ValueError, match='overlap'):
        run_graph(empty_record(), [a, Step('duplicate', '1', a.reads, a.writes, lambda r: r)], tmp_path)
