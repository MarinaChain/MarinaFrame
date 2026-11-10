"""Offline accounting: duplicated summaries must not become extra requests."""
import csv
import json
import sys

from scripts import cost_per_ship as cost


def test_prices_use_cache_ttl_and_bound_collapsed_holdout_usage():
    call = dict(model='claude-sonnet-5-5', prompt_tokens=150, output_tokens=10,
                input_tokens=20, cache_read_tokens=100, cache_write_tokens=30,
                cache_write_5m_tokens=0, cache_write_1h_tokens=30, missing_usage=False)
    low, high = cost.api_cost_range(call)
    assert round(low, 6) == round((20 * 2 + 100 * .2 + 30 * 4 + 10 * 10) / 1e6, 6)
    assert low == high
    call.update(input_tokens=None, cache_read_tokens=None, cache_write_tokens=None,
                cache_write_5m_tokens=None, cache_write_1h_tokens=None)
    assert cost.api_cost_range(call) == ((150 * .2 + 100) / 1e6, (150 * 4 + 100) / 1e6)
    call['model'] = 'deepseek-v4.1-flash'
    assert cost.api_cost_range(call) == (None, None)
    call['model'] = 'crouton-alpha-free'
    assert cost.api_cost_range(call) == (0., 0.)
    call.update(model='claude-sonnet-5-5', missing_usage=True)
    assert cost.api_cost_range(call) == (None, None)


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))


def test_controller_uses_final_cli_usage_once_and_worker_resources(tmp_path):
    case = tmp_path / 'case'
    save(case / 'result.json', {'wall_seconds': 20})
    receipt = case / 'task/receipts/request-1.json'
    save(receipt, {'request_id': 'request-1', 'requested_model': 'claude-sonnet-5-5',
                   'state': 'completed', 'latency_seconds': 3,
                   'usage': {'prompt_tokens': 150, 'completion_tokens': 10}})
    result = {'type': 'result', 'usage': {'input_tokens': 20, 'output_tokens': 10,
              'cache_read_input_tokens': 100, 'cache_creation_input_tokens': 30,
              'cache_creation': {'ephemeral_1h_input_tokens': 30}}}
    receipt.with_suffix('.body').write_text(json.dumps({'type': 'assistant', 'usage': result['usage']})
                                            + '\n' + json.dumps(result))
    save(case / 'task/receipts/worker-1.json', {'operation': 'describe_vessel',
         'resources': {'wall_seconds': 12, 'worker_cpu_seconds': 2, 'children_cpu_seconds': 9}})
    run = cost.controller_run(case, 'round')
    assert run['wall_seconds'] == 20
    assert run['worker_seconds'] == 12
    assert run['worker_cpu_seconds'] == 11
    assert len(run['calls']) == 1
    call = run['calls'][0]
    assert call['prompt_tokens'] == 150
    assert call['input_tokens'] == 20
    assert call['cache_read_tokens'] == 100
    assert call['cache_write_1h_tokens'] == 30
    assert call['output_tokens'] == 10


def test_holdout_keeps_identical_lines_and_failed_unknown_usage(tmp_path):
    arm = tmp_path / 'sonnet'
    save(arm / 'summary.json', {'arm': 'sonnet', 'measurement': {'seconds': 2},
         'repeats': [{'seconds': 5, 'calls': 3, 'prompt_tokens': 200, 'completion_tokens': 20}]})
    receipt = arm / 'R1-1/receipts/claude.jsonl'
    receipt.parent.mkdir(parents=True)
    row = {'model': 'claude-sonnet-5-5', 'state': 'completed', 'seconds': 2,
           'usage': {'prompt_tokens': 100, 'completion_tokens': 10}}
    receipt.write_text('\n'.join(map(json.dumps, [row, row, {'model': 'claude-sonnet-5-5',
        'state': 'failed', 'seconds': 1, 'usage': {'prompt_tokens': 0, 'completion_tokens': 0}}])))
    runs = cost.holdout_runs(arm, 'hull')
    assert len(runs) == 1
    run = runs[0]
    assert run['wall_seconds'] == 5
    assert run['measurement_seconds'] == 2
    totals = cost.summarize_calls(run['calls'])
    assert totals['requests'] == 3
    assert totals['prompt_tokens'] == 200
    assert totals['missing_usage_requests'] == 1
    assert totals['models']['claude-sonnet-5-5']['cache_read_tokens'] is None


def test_controller_includes_intake_calibration_without_treating_collapsed_input_as_uncached(tmp_path):
    case = tmp_path / 'bue_girl'
    save(case / 'result.json', {'wall_seconds': 100})
    receipt = case / 'intake/run-input/body-plan-answers/receipts/claude.jsonl'
    receipt.parent.mkdir(parents=True)
    receipt.write_text(json.dumps({'model': 'claude-sonnet-5-5', 'state': 'completed',
                                  'input_tokens': 100, 'output_tokens': 10, 'seconds': 4}) + '\n')

    run = cost.controller_run(case, 'autocal-live-6')

    assert run['wall_seconds'] == 100  # Intake is already inside the inclusive case time.
    assert len(run['calls']) == 1
    call = run['calls'][0]
    assert call['phase'] == 'intake_calibration'
    assert call['prompt_tokens'] == 100
    assert call['output_tokens'] == 10
    assert call['input_tokens'] is None
    assert call['seconds'] == 4
    assert cost.api_cost_range(call) == (0.00012, 0.0005)


def test_holdout_resume_counts_unique_request_ids_from_both_directories(tmp_path):
    arm = tmp_path / 'crouton'
    save(arm / 'summary.json', {'arm': 'crouton', 'measurement': None,
                              'repeats': [{'seconds': 10, 'calls': 2}]})
    row = {'request_id': 'saved', 'model': 'crouton-alpha-free', 'state': 'completed',
           'usage': {'prompt_tokens': 10, 'completion_tokens': 2}}
    save(arm / 'R1-1/receipts/saved.json', row)
    save(arm / 'R1-1-resumed/receipts/saved.json', row)
    save(arm / 'R1-1-resumed/receipts/new.json', dict(row, request_id='new'))
    run = cost.holdout_runs(arm, 'hull')[0]
    assert len(run['calls']) == 2
    assert run['measurement_seconds'] is None


def test_cli_writes_matching_ledgers_in_work_with_unknown_cost_flagged(tmp_path, monkeypatch):
    arm = tmp_path / 'holdouts/bue-girl/runs/sonnet'
    save(arm / 'summary.json', {'arm': 'sonnet', 'measurement': {'seconds': 1},
                              'repeats': [{'seconds': 2, 'calls': 1}]})
    receipt = arm / 'R1-1/receipts/claude.jsonl'
    receipt.parent.mkdir(parents=True)
    receipt.write_text(json.dumps({'model': 'claude-sonnet-5-5', 'state': 'failed',
                                  'usage': {'prompt_tokens': 0, 'completion_tokens': 0}}) + '\n')
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, 'argv', ['cost_per_ship.py', '--main-work', str(tmp_path / 'main'),
                                    '--holdout-root', str(tmp_path / 'holdouts')])

    cost.main()

    report = json.loads((tmp_path / 'work/cost_per_ship.json').read_text())
    with (tmp_path / 'work/cost_per_ship_runs.csv').open(newline='') as stream:
        rows = list(csv.DictReader(stream))
    assert len(report['runs']) == len(rows) == 1
    assert rows[0]['requests'] == '1'
    assert rows[0]['missing_usage_requests'] == '1'
    assert rows[0]['unpriced_requests'] == '1'
    assert rows[0]['api_cost_low_usd'] == rows[0]['api_cost_high_usd'] == ''
    assert not (tmp_path / 'outputs').exists()
