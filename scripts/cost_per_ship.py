#!/usr/bin/env python3
"""Account for stored run records only. Never imports a model client or reads images.

Run from any checkout with --main-work pointing at the main checkout's work folder.
CLI result usage is cumulative within one invocation: read only its final result, not
assistant messages, modelUsage, or usage.iterations again. Holdout summaries duplicate
per-call receipts; they supply timing and scores only.

Writes derived JSON and CSV ledgers under work/ by default; do not commit them.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
import json
from pathlib import Path

MAIN_WORK = Path('/Users/jonathanjie/Documents/workspace/MarinaFrame/work')
HOLDOUT_ROOT = Path('/private/tmp/claude-501')
# USD per million tokens, recorded 2026-11-10. API-equivalent, not subscription bills.
# Claude: bundled-skills/2.1.317/c2410b3d888fef8507425f875f1de23e/
# claude-api/shared/models.md (Sonnet 5.5: 2/10/.20; Opus 5.5: 4/20/.20),
# shared/prompt-caching.md (5m write 1.25x, 1h write 2x).
# DeepSeek: no exact rate table found locally. The approximate blended historical
# rate in docs/plans/2026-11-08-whole-vessel-design.md is NOT a tariff.
PRICE_DATE = '2026-11-10'
PRICES = {
    'claude-sonnet-5-5': dict(input=2., output=10., read=.2, write_5m=2.5, write_1h=4.),
    'claude-opus-5-5': dict(input=4., output=20., read=.2, write_5m=5., write_1h=8.),
    'deepseek-v4.1-flash': None,  # price not found; report tokens only
    'crouton-alpha-free': dict(input=0., output=0., read=0., write_5m=0., write_1h=0.),
}


def api_cost_range(call):
    price = PRICES.get(call['model'])
    if price is None or call['missing_usage']:
        return None, None
    output_cost = call['output_tokens'] * price['output']
    if call['input_tokens'] is None:
        # Holdout harness collapsed uncached + cache writes + cache reads.
        # These are algebraic bounds, not claims about actual cache use.
        return ((call['prompt_tokens'] * price['read'] + output_cost) / 1e6,
                (call['prompt_tokens'] * price['write_1h'] + output_cost) / 1e6)
    base = (call['input_tokens'] * price['input']
            + call['cache_read_tokens'] * price['read'] + output_cost)
    write_5m = call['cache_write_5m_tokens'] or 0
    write_1h = call['cache_write_1h_tokens'] or 0
    unknown_ttl = max(0, call['cache_write_tokens'] - write_5m - write_1h)
    base += write_5m * price['write_5m'] + write_1h * price['write_1h']
    return ((base + unknown_ttl * price['write_5m']) / 1e6,
            (base + unknown_ttl * price['write_1h']) / 1e6)


TOKEN_FIELDS = ('prompt_tokens', 'output_tokens', 'input_tokens', 'cache_read_tokens',
                'cache_write_tokens', 'cache_write_5m_tokens', 'cache_write_1h_tokens')


def read_json(path):
    return json.loads(path.read_text())


def normalize_call(receipt, source, phase, raw=None):
    usage = receipt.get('usage') or {}
    model = (receipt.get('returned_model') or receipt.get('answered_by')
             or receipt.get('requested_model') or receipt.get('model') or 'unknown')
    output = usage.get('completion_tokens')
    prompt = usage.get('prompt_tokens')
    # Failed holdout CLI invocations wrote prompt=0 even when no result existed.
    missing = (prompt is None or output is None
               or (receipt.get('state') == 'failed' and prompt == 0 and output == 0))
    call = dict(source=str(source), model=model, phase=phase,
                state=receipt.get('state', 'unknown'), prompt_tokens=prompt,
                output_tokens=output, missing_usage=missing,
                seconds=receipt.get('latency_seconds', receipt.get('seconds')),
                receipt_list_cost_usd=usage.get('list_cost'),
                observed_cost_usd=receipt.get('observed_cost_usd', usage.get('cost')))
    call.update({key: None for key in TOKEN_FIELDS if key not in call})
    if raw is not None:
        u = raw.get('usage') or {}
        if 'input_tokens' in u and 'output_tokens' in u:
            creation = u.get('cache_creation') or {}
            writes = u.get('cache_creation_input_tokens', 0)
            call.update(input_tokens=u['input_tokens'], output_tokens=u['output_tokens'],
                        cache_read_tokens=u.get('cache_read_input_tokens', 0),
                        cache_write_tokens=writes,
                        cache_write_5m_tokens=creation.get('ephemeral_5m_input_tokens'),
                        cache_write_1h_tokens=creation.get('ephemeral_1h_input_tokens'),
                        missing_usage=False)
            call['prompt_tokens'] = call['input_tokens'] + call['cache_read_tokens'] + writes
    return call


def final_cli_result(path):
    if not path.exists():
        return None
    result = None
    for line in path.read_text().splitlines():
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if value.get('type') == 'result':
            result = value
    return result


def summarize_calls(calls):
    models = {}
    for model in sorted({call['model'] for call in calls}):
        rows = [call for call in calls if call['model'] == model]
        total = {'requests': len(rows), 'states': dict(Counter(c['state'] for c in rows)),
                 'missing_usage_requests': sum(c['missing_usage'] for c in rows)}
        for field in TOKEN_FIELDS:
            values = [c[field] for c in rows if c[field] is not None]
            total[field] = sum(values) if values else None
        costs = [api_cost_range(c) for c in rows]
        total['unpriced_requests'] = sum(low is None for low, high in costs)
        total['known_api_cost_low_usd'] = sum(low for low, high in costs if low is not None)
        total['known_api_cost_high_usd'] = sum(high for low, high in costs if high is not None)
        total['model_seconds'] = sum(c['seconds'] or 0 for c in rows)
        total['receipt_list_cost_usd'] = sum(c['receipt_list_cost_usd'] or 0 for c in rows)
        models[model] = total
    return {'requests': len(calls), 'prompt_tokens': sum(c['prompt_tokens'] or 0 for c in calls),
            'output_tokens': sum(c['output_tokens'] or 0 for c in calls),
            'missing_usage_requests': sum(c['missing_usage'] for c in calls), 'models': models}


def controller_run(case, campaign):
    task = case / 'task'
    result_path = case / 'result.json'
    result = read_json(result_path) if result_path.exists() else {}
    phase_by_request = {}
    for path in sorted((task / 'events').glob('*.json')):
        event = read_json(path)
        if event.get('kind') == 'provider_intent':
            phase_by_request[event['payload']['request_id']] = (
                event.get('state_after', {}).get('domain', {}).get('description_phase') or 'investigation')
    calls, seen = [], set()
    for path in sorted((task / 'receipts').glob('request-*.json')):
        receipt = read_json(path)
        request_id = receipt.get('request_id', str(path))
        if request_id in seen:
            continue
        seen.add(request_id)
        calls.append(normalize_call(receipt, path, phase_by_request.get(request_id, 'unknown'),
                                    final_cli_result(path.with_suffix('.body'))))
    # Intake uses a separate log. Its "input_tokens" already includes cache reads
    # and writes, so preserve it as collapsed prompt usage, not uncached input.
    intake_log = case / 'intake/run-input/body-plan-answers/receipts/claude.jsonl'
    if intake_log.exists():
        for number, line in enumerate(intake_log.read_text().splitlines(), 1):
            if line.strip():
                receipt = json.loads(line)
                receipt = dict(receipt, usage={
                    'prompt_tokens': receipt.get('input_tokens'),
                    'completion_tokens': receipt.get('output_tokens')})
                calls.append(normalize_call(receipt, f'{intake_log}:{number}', 'intake_calibration'))
    workers = defaultdict(lambda: {'operations': 0, 'wall_seconds': 0., 'cpu_seconds': 0.})
    for path in sorted((task / 'receipts').glob('worker-*.json')):
        receipt = read_json(path)
        resources = receipt.get('resources') or {}
        row = workers[receipt.get('operation', 'unknown')]
        row['operations'] += 1
        row['wall_seconds'] += resources.get('wall_seconds', 0)
        row['cpu_seconds'] += sum(resources.get(k, 0) for k in ('worker_cpu_seconds', 'children_cpu_seconds'))
    return dict(kind='controller', campaign=campaign, case=case.name, arm='live',
                source=str(case), wall_seconds=result.get('wall_seconds'),
                status=result.get('controller_status'), termination_reason=result.get('termination_reason'),
                worker_seconds=sum(r['wall_seconds'] for r in workers.values()),
                worker_cpu_seconds=sum(r['cpu_seconds'] for r in workers.values()),
                worker_operations=dict(workers), calls=calls)


def holdout_runs(arm_dir, case):
    summary = read_json(arm_dir / 'summary.json')
    runs = []
    for index, score in enumerate(summary.get('repeats', []), 1):
        repeat = arm_dir / f'R1-{index}'
        calls, seen = [], set()
        receipt_dirs = [repeat / 'receipts']
        receipt_dirs.extend(p / 'receipts' for p in sorted(arm_dir.glob(f'R1-{index}-*')) if p.is_dir())
        for receipt_dir in receipt_dirs:
            for path in sorted(receipt_dir.glob('*.json')):
                receipt = read_json(path)
                identity = receipt.get('request_id', str(path.resolve()))
                if identity not in seen:
                    seen.add(identity)
                    calls.append(normalize_call(receipt, path, 'label_questions'))
            for path in sorted(receipt_dir.glob('*.jsonl')):
                for number, line in enumerate(path.read_text().splitlines(), 1):
                    if line.strip():
                        calls.append(normalize_call(json.loads(line), f'{path}:{number}', 'label_questions'))
        runs.append(dict(kind='holdout', campaign=arm_dir.name, case=case,
                         arm=summary.get('arm', arm_dir.name), repeat=index, source=str(repeat),
                         wall_seconds=score.get('seconds'),
                         measurement_seconds=(summary.get('measurement') or {}).get('seconds'),
                         resume_note=score.get('resume_note'),
                         summary_requests=score.get('calls'), summary_prompt_tokens=score.get('prompt_tokens'),
                         summary_output_tokens=score.get('completion_tokens'),
                         rms_m=score.get('rms_m'), coverage=score.get('coverage'),
                         passes_rule=summary.get('passes_rule'), calls=calls))
    return runs


def collect(main_work, holdout_root, tank_roots=()):
    runs = []
    for pattern in ('round-3view-*-sonnet-*', 'autocal-live-*'):
        for campaign in sorted(main_work.glob(pattern)):
            for case in sorted(campaign.iterdir()):
                if (case / 'task').is_dir():
                    runs.append(controller_run(case, campaign.name))
    for case in ('bue-girl', 'bumble-bee', 'pardon-me'):
        for summary in sorted((holdout_root / case / 'runs').glob('*/summary.json')):
            runs.extend(holdout_runs(summary.parent, case))
    # Tank caches are shared across replays. Count each actual receipt path once, not
    # once per reading. Reading wall times cannot be assigned to that shared cache.
    tank_paths = sorted({p.resolve() for root in tank_roots for p in root.rglob('claude.jsonl')})
    for path in tank_paths:
        calls = [normalize_call(json.loads(line), f'{path}:{n}', 'tank_label_questions')
                 for n, line in enumerate(path.read_text().splitlines(), 1) if line.strip()]
        runs.append(dict(kind='tank_cache', campaign='tank', case=path.parent.parent.name,
                         arm='sonnet', source=str(path), wall_seconds=None, calls=calls))
    for run in runs:
        run['totals'] = summarize_calls(run['calls'])
        run['phases'] = {phase: summarize_calls([c for c in run['calls'] if c['phase'] == phase])
                         for phase in sorted({c['phase'] for c in run['calls']})}
    return {'schema_version': 1, 'price_date': PRICE_DATE, 'prices_usd_per_million': PRICES,
            'main_work': str(main_work), 'holdout_root': str(holdout_root),
            'tank_roots': [str(p) for p in tank_roots], 'tank_receipt_files': len(tank_paths),
            'runs': runs}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--main-work', type=Path, default=MAIN_WORK)
    parser.add_argument('--holdout-root', type=Path, default=HOLDOUT_ROOT)
    parser.add_argument('--tank-root', type=Path, action='append', default=[])
    parser.add_argument('--out', type=Path, default=Path('work/cost_per_ship.json'),
                        help='JSON ledger (default: work/cost_per_ship.json); also writes <stem>_runs.csv')
    args = parser.parse_args()
    tank_roots = args.tank_root or [args.main_work / 'tanks-raster']
    report = collect(args.main_work, args.holdout_root, tank_roots)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2) + '\n')
    csv_path = args.out.with_name(f'{args.out.stem}_runs.csv')
    fields = ('case', 'campaign', 'arm', 'repeat', 'kind', 'wall_seconds', 'worker_seconds',
              'worker_cpu_seconds', 'requests', 'prompt_tokens', 'output_tokens',
              'missing_usage_requests', 'api_cost_low_usd', 'api_cost_high_usd',
              'unpriced_requests', 'source')
    with csv_path.open('w', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for run in report['runs']:
            totals = run['totals']
            models = totals['models'].values()
            unpriced = sum(model['unpriced_requests'] for model in models)
            row = {field: run.get(field) for field in fields}
            row.update({field: totals[field] for field in
                        ('requests', 'prompt_tokens', 'output_tokens', 'missing_usage_requests')})
            # A partial known subtotal is not the total price of an unpriced run.
            row.update(unpriced_requests=unpriced,
                       api_cost_low_usd=None if unpriced else sum(
                           model['known_api_cost_low_usd'] for model in models),
                       api_cost_high_usd=None if unpriced else sum(
                           model['known_api_cost_high_usd'] for model in models))
            writer.writerow(row)
    print(f"{len(report['runs'])} runs; {sum(r['totals']['requests'] for r in report['runs'])} receipts; "
          f"{report['tank_receipt_files']} tank receipt files; saved {args.out} and {csv_path}")


if __name__ == '__main__':
    main()
