"""Accounting and fixed denominators for the measurement-only report."""
import importlib.util
import json
from pathlib import Path

from benchmarks.ga_synthetic.generate import arrangements


def test_missing_arrangement_keeps_truth_and_exam_denominators(tmp_path):
    path = Path(__file__).parents[1] / 'scripts' / 'summarize_ga_synthetic_run.py'
    spec = importlib.util.spec_from_file_location('synthetic_summary', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    (tmp_path / 'truth').mkdir()
    (tmp_path / 'run').mkdir()
    truth = arrangements()[0]
    (tmp_path / 'truth' / 'case.json').write_text(json.dumps(truth))
    result = module.summarize(tmp_path)
    assert sum(k['truth'] for k in result['by_kind'].values()) == len(truth['spaces'])
    assert sum(k['found'] for k in result['by_kind'].values()) == 0
    assert result['exam_groups']['particulars']['abstained'] == 4
    assert result['exam_groups']['counts']['abstained'] == 3
    assert result['usage']['receipt_attempts'] == 0
    assert truth['case_id'] in result['errors']


def test_printed_status_translation_preserves_box_values(tmp_path):
    path = Path(__file__).parents[1] / 'scripts' / 'summarize_ga_synthetic_run.py'
    spec = importlib.util.spec_from_file_location('synthetic_summary', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    (tmp_path / 'truth').mkdir()
    truth = arrangements()[0]
    (tmp_path / 'truth' / 'case.json').write_text(json.dumps(truth))
    case_dir = tmp_path / 'run' / truth['case_id']
    case_dir.mkdir(parents=True)
    source = {'kind': 'unknown', 'reason': 'synthetic fixture'}
    reading = {'schema': 'marinaframe.ga_reading.v1', 'case_id': truth['case_id'],
               'engineering_approved': False, 'test_fixture': True,
               'particulars': {k: {'value': v, 'status': 'read', 'source_record': source}
                               for k, v in truth['dimensions'].items()},
               'spaces': [{'id': s['id'], 'kind': s['kind'], 'label': s['label'],
                           'status': 'read', 'side': 'centre', 'source_record': source,
                           'extent': {**{f'{a}_m': v for a, v in s['box_m'].items()},
                                      'status': {'x': 'printed', 'y': 'read', 'z': 'read'}}}
                          for s in truth['spaces']]}
    input_path = case_dir / 'ga_arrangement_input.json'
    input_path.write_text(json.dumps(reading))
    result = module.summarize(tmp_path)
    assert truth['case_id'] in result['errors']
    assert sum(k['found'] for k in result['by_kind'].values()) == len(truth['spaces'])
    assert json.loads(input_path.read_text()) == reading
    assert (case_dir / 'status-translation.json').exists()
