"""Read-only provider accounting from original task journals, never request payloads.

No provider/native actions. Final-live inputs/references are not opened: its
existing strict verification output is checked against the terminal output lock.
"""
from __future__ import annotations
import argparse, collections, datetime, hashlib, json, math, os, subprocess
from pathlib import Path

REPO = Path('/workspace/scratch/3b76408c5d11/marinaframe-rust')
OLD = Path('/workspace/scratch/3b76408c5d11/marinaframe-agentic/artifacts/agentic')
BINARY = Path('/tmp/marinaframe-v04-runtime-8916e68/marinaframe')
FINAL = Path('/tmp/marinaframe-v04-final-live/runs')
FINAL_LOCK_SHA = 'aa6c7fb5a6cb333b68ee9b1f2d1ba3a33f7ba063cc4aba0c1917fe73fa79070d'
INVENTORY = {}
LOCK_FILES = {}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load(path):
    path = Path(path)
    raw = path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if str(path) in INVENTORY and INVENTORY[str(path)]['sha256'] != digest:
        raise ValueError('Accounting input changed during observation: ' + str(path))
    if path.is_relative_to(FINAL) and LOCK_FILES and path.name != 'output-lock.json':
        relative = path.relative_to(FINAL).as_posix()
        if LOCK_FILES.get(relative) != digest:
            raise ValueError('Runtime record does not match final output lock: ' + relative)
    INVENTORY[str(path)] = {'sha256': digest, 'bytes': len(raw)}
    return json.loads(raw)


def dump(path, value):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + '\n')


def number(value):
    return value if type(value) in (int, float) and math.isfinite(value) and value >= 0 else None


def integer(value):
    return value if type(value) is int and value >= 0 else None


def discover(extensions):
    skip = {'src', 'input', 'inputs', 'prior-input', 'domain', 'rust-control', 'scripts', 'runtime', '__pycache__', 'target', '.git', 'receipts', 'requests', 'worker-logs'}
    tasks = []
    for n in range(1, 9):
        root = Path('/tmp') / f'marinaframe-v04-dev{n}'
        for here, dirs, files in os.walk(root):
            dirs[:] = [d for d in dirs if d not in skip and not (n == 8 and not extensions and d in {'trial-03', 'trial-04', 'trial-05', 'trial-06'})]
            if 'events' in dirs:
                path = Path(here); relative = path.relative_to(root).as_posix()
                cohort = f'dev{n}' if n != 8 else ('dev8-initial' if relative.split('/')[0] in {'trial-01', 'trial-02'} else 'dev8-extension')
                tasks.append((cohort, relative, path)); dirs.remove('events')
    return sorted(tasks, key=lambda x: (int(x[0].split('-')[0][3:]), 'extension' in x[0], x[1]))


def strict_verify(task, final=False):
    if final:
        path = task.parent / 'verify.stdout'
        value = load(path)
        return {'mode': 'existing final strict output bound by terminal output-lock', 'source': str(path), 'source_sha256': INVENTORY[str(path)]['sha256'], 'result': value}
    command = [str(BINARY), 'verify', '--task', str(task)]
    env = {k: os.environ[k] for k in ('PATH', 'HOME', 'LANG', 'LC_ALL', 'LC_CTYPE', 'TZ') if k in os.environ}
    result = subprocess.run(command, cwd='/tmp', env=env, capture_output=True, text=True, timeout=90)
    value, channel = {'valid': False, 'output_not_json': True}, None
    for name, output in [('stdout', result.stdout), ('stderr', result.stderr)]:
        try:
            candidate = json.loads(output)
            if isinstance(candidate, dict): value, channel = candidate, name; break
        except json.JSONDecodeError:
            pass
    return {'mode': 'current frozen strict verifier; read-only', 'command': command, 'exit_code': result.returncode,
            'json_output_channel': channel, 'stdout_sha256': hashlib.sha256(result.stdout.encode()).hexdigest(),
            'stderr_sha256': hashlib.sha256(result.stderr.encode()).hexdigest(), 'binary_sha256': sha(BINARY), 'result': value}


def images(receipt):
    keys = ('artifact_id', 'sha256', 'bytes', 'evidence_kind', 'view', 'generation_id', 'revision_id', 'step_sha256', 'pixels_attached')
    return [{k: item.get(k) for k in keys} for item in receipt.get('images', []) if type(item) is dict]


def aggregate(requests):
    outcomes = collections.Counter(r['outcome'] for r in requests)
    costs = [r['observed_cost_usd'] for r in requests if r['observed_cost_usd'] is not None]
    return {
        'request_records': len(requests), 'intended': sum(r['durable_intent'] for r in requests),
        'completed': outcomes['completed'], 'failed': outcomes['failed'],
        'unknown': outcomes['transmission_or_completion_unknown'], 'not_sent': outcomes['not_sent'],
        'reported_prompt_tokens': sum(r['prompt_tokens'] or 0 for r in requests),
        'reported_completion_tokens': sum(r['completion_tokens'] or 0 for r in requests),
        'prompt_token_coverage': sum(r['prompt_tokens'] is not None for r in requests),
        'completion_token_coverage': sum(r['completion_tokens'] is not None for r in requests),
        'cost_receipt_coverage': len(costs), 'cost_unreported_requests': len(requests) - len(costs),
        'reported_cost_sum_usd': sum(costs), 'explicit_zero_cost_receipts': sum(c == 0 for c in costs),
        'requests_with_attached_images': sum(any(i['pixels_attached'] is True for i in r['images']) for r in requests),
        'attached_image_receipt_entries': sum(i['pixels_attached'] is True for r in requests for i in r['images']),
        'completed_requests_with_attached_images': sum(r['outcome'] == 'completed' and any(i['pixels_attached'] is True for i in r['images']) for r in requests),
    }


def trial(cohort, name, task):
    checkpoint = load(task / 'state.json'); state = checkpoint['state']
    events = [(p, load(p)) for p in sorted((task / 'events').glob('*.json'))]
    intents, outcomes, receipts, observed_outcomes = {}, {}, {}, {}
    first_provider = min((e['sequence'] for _, e in events if e['kind'] == 'provider_intent'), default=10**12)
    decisions, interventions, builds, changes, completed_images = [], [], [], [], []
    last_decision = {}; last_built = None
    revision_ids = set(); generation_ids = set()
    for path, event in events:
        kind, payload, sequence = event['kind'], event['payload'], event['sequence']
        after = event.get('state_after', {})
        if after.get('revision_id'): revision_ids.add(after['revision_id'])
        if after.get('generation_id'): generation_ids.add(after['generation_id'])
        if kind == 'provider_intent':
            intents[payload['request_id']] = {'event': str(path), 'sequence': sequence, 'images': payload.get('images', []), 'attempt': payload.get('attempt'), 'retry_of': payload.get('retry_of')}
        if kind in {'provider_result', 'provider_reconciled'}:
            receipt = payload['receipt']; identity = receipt['request_id']
            artifact = payload.get('receipt_file')
            receipt_path = task / artifact['path'] if artifact else task / 'receipts' / (identity + '.json')
            if not receipt_path.resolve().is_relative_to(task.resolve()): raise ValueError('Foreign receipt path')
            raw_receipt = load(receipt_path)
            if artifact and sha(receipt_path) != artifact['sha256']: raise ValueError('Changed bound receipt')
            receipts[identity] = (raw_receipt, receipt_path, sequence, True, raw_receipt == receipt)
            outcomes[identity] = raw_receipt['state']; observed_outcomes.setdefault(identity, []).append(raw_receipt['state'])
            if raw_receipt['state'] == 'completed':
                completed_images.extend((sequence, identity, i) for i in images(raw_receipt))
        if kind in {'provider_not_sent', 'provider_outcome_unknown'}:
            identity = payload['request_id']; value = 'not_sent' if kind == 'provider_not_sent' else 'transmission_or_completion_unknown'
            outcomes[identity] = value; observed_outcomes.setdefault(identity, []).append(value)
        if kind == 'operator_intervention':
            interventions.append({'sequence': sequence, 'actor': payload.get('actor'), 'tool': payload['decision']['tool'], 'before_first_provider_intent': sequence < first_provider})
        if kind == 'decision':
            last_decision = {'sequence': sequence, 'actor': payload.get('actor'), 'tool': payload['decision']['tool'], 'arguments': payload['decision']['arguments']}
            decisions.append(last_decision)
        if kind in {'worker_result', 'worker_reconciled'}:
            operation = payload['operation']; result = payload['response'].get('result') or {}
            if operation == 'build_provisional':
                candidate = result.get('candidate') or {}
                step = next((a['sha256'] for a in result.get('artifacts', []) if a.get('kind') == 'provisional_step'), None)
                item = {'sequence': sequence, 'actor': last_decision.get('actor'), 'reused': result.get('reused') is True,
                        'valid': candidate.get('valid'), 'path': candidate.get('path'), 'generation_id': candidate.get('generation_id'),
                        'revision_id': candidate.get('revision_id'), 'step_sha256': step, 'status': result.get('status')}
                builds.append(item)
                if candidate.get('valid') is True: last_built = item
            if operation == 'select_contours' and result.get('changed') is True:
                prior = dict(last_built) if last_built else None
                prior_images = [(seq, identity, i) for seq, identity, i in completed_images
                                if prior and i.get('pixels_attached') is True and i.get('step_sha256') == prior.get('step_sha256')
                                and i.get('generation_id') == prior.get('generation_id') and i.get('revision_id') == prior.get('revision_id')]
                changes.append({'sequence': sequence, 'actor': last_decision.get('actor'), 'prior_candidate': prior,
                                'prior_step_views_on_completed_receipts': sorted({i['view'] for _, _, i in prior_images if i.get('view')}),
                                'prior_image_request_ids': sorted({identity for _, identity, _ in prior_images}),
                                'new_generation_id': payload['response'].get('domain', {}).get('generation_id'),
                                'new_revision_id': payload['response'].get('domain', {}).get('revision_id')})
    # Include an actual late/orphan provider receipt, even if the controller never adopted it.
    for path in sorted((task / 'receipts').glob('request-*.json')):
        if path.stem not in receipts:
            receipt = load(path)
            if receipt.get('request_id') != path.stem: raise ValueError('Receipt identity mismatch')
            receipts[path.stem] = (receipt, path, None, False, None)
            outcomes[path.stem] = receipt['state']
    requests = []
    for identity in sorted(set(intents) | set(outcomes) | set(receipts)):
        receipt, path, sequence, adopted, matches = receipts.get(identity, ({}, None, None, False, None))
        usage = receipt.get('usage') or {}; intent = intents.get(identity, {})
        outcome = outcomes.get(identity, 'transmission_or_completion_unknown')
        requests.append({'cohort': cohort, 'trial': name, 'task_id': state['task_id'], 'request_id': identity,
                         'durable_intent': identity in intents, 'intent_event': intent.get('event'), 'intent_sequence': intent.get('sequence'),
                         'outcome': outcome, 'outcome_history': observed_outcomes.get(identity, []), 'receipt_adopted': adopted,
                         'receipt_event_sequence': sequence, 'receipt_path': str(path) if path else None, 'receipt_sha256': sha(path) if path else None,
                         'receipt_content_matches_event': matches, 'requested_model': receipt.get('requested_model'),
                         'returned_model': receipt.get('returned_model'), 'evidence_mode': receipt.get('evidence_mode'),
                         'http_status': receipt.get('http_status'), 'error_code': receipt.get('error_code'),
                         'attempt': receipt.get('attempt', intent.get('attempt')), 'retry_of': receipt.get('retry_of', intent.get('retry_of')),
                         'prompt_tokens': integer(usage.get('prompt_tokens')), 'completion_tokens': integer(usage.get('completion_tokens')),
                         'observed_cost_usd': number(receipt.get('observed_cost_usd')), 'billing_source': usage.get('billing_source'),
                         'reported_list_cost_usd': number(usage.get('list_cost')), 'decision_tool': (receipt.get('decision') or {}).get('tool'),
                         'images': images(receipt), 'latency_seconds': number(receipt.get('latency_seconds'))})
    totals = aggregate(requests); counters = state.get('counters', {})
    mapping = {'intended': 'requests_intended', 'completed': 'requests_completed', 'failed': 'requests_failed', 'unknown': 'requests_unknown',
               'not_sent': 'requests_not_sent', 'reported_prompt_tokens': 'prompt_tokens', 'reported_completion_tokens': 'completion_tokens',
               'reported_cost_sum_usd': 'observed_cost_usd'}
    counter_differences = {key: {'ledger': totals[key], 'controller': counters.get(field)} for key, field in mapping.items() if totals[key] != counters.get(field)}
    verification = strict_verify(task, cohort == 'final-live')
    valid = verification['result'].get('valid') is True
    domain = state.get('domain', {}); binding = ((domain.get('validation') or {}).get('contract') or {}).get('binding') or {}
    live_finish = max((d['sequence'] for d in decisions if d['actor'] == 'live_model' and d['tool'] == 'finish' and d['arguments'].get('outcome') == 'candidate_ready_for_review'), default=0)
    final_images = [(seq, identity, i) for seq, identity, i in completed_images if i.get('pixels_attached') is True
                    and i.get('generation_id') == state.get('generation_id') and i.get('revision_id') == state.get('revision_id')
                    and binding.get('step_sha256') and i.get('step_sha256') == binding['step_sha256']]
    final_views = sorted({i['view'] for _, _, i in final_images if i.get('view')})
    corrective = [c for c in changes if c['actor'] == 'live_model' and c['prior_candidate']]
    prior_two_views = any({'body', 'oblique'} <= set(c['prior_step_views_on_completed_receipts']) for c in corrective)
    live_rebuilds = [b for b in builds if b['actor'] == 'live_model' and b['valid'] is True and not b['reused']
                    and b['generation_id'] == state.get('generation_id') and b['revision_id'] == state.get('revision_id')
                    and b['step_sha256'] == binding.get('step_sha256')
                    and any(c['sequence'] < b['sequence'] and c['new_generation_id'] == b['generation_id'] for c in corrective)]
    views_before_finish = {i['view'] for seq, _, i in final_images if seq < live_finish and i.get('view')}
    visual_sequence = bool(corrective) and prior_two_views and bool(live_rebuilds) and {'body', 'oblique'} <= views_before_finish and state['status'] == 'awaiting_human_review' and valid
    if not requests: demonstration = 'No provider attempt; deterministic or admission control.'
    elif state['status'] == 'awaiting_human_review' and not valid: demonstration = 'Historical ready label rejected by current strict verification; no current-ready credit.'
    elif visual_sequence: demonstration = 'Bound prior/current STEP images, model selection change and verified provisional candidate; semantic accuracy not inferred.'
    elif corrective: demonstration = 'Model changed a selection after a candidate existed; complete prior/current two-view qualification not met.'
    elif state['status'] == 'awaiting_human_review' and valid: demonstration = 'Verified provisional construction/current STEP inspection; no post-build model revision demonstrated.'
    else: demonstration = 'Retained refusal or failure; included in the attempt denominator.'
    row = {'cohort': cohort, 'trial': name, 'original_task': str(task), 'task_id': state['task_id'],
           'policy': state.get('config', {}).get('policy'), 'historical_status': state['status'], 'termination_reason': state.get('termination_reason'),
           'head_sha256': checkpoint.get('head_sha256'), 'event_count': len(events), 'requests': totals,
           'stored_counters': counters, 'counter_differences': counter_differences, 'verification': verification, 'strict_valid': valid,
           'current_review_ready': state['status'] == 'awaiting_human_review' and valid,
           'final_generation_id': state.get('generation_id'), 'final_revision_id': state.get('revision_id'),
           'observed_revision_ids': sorted(revision_ids), 'observed_generation_ids': sorted(generation_ids),
           'controller_build_reservations': counters.get('builds'), 'build_observations': builds,
           'confirmed_new_build_attempts': len({b['path'] for b in builds if b['path'] and not b['reused']}),
           'operator_interventions': interventions, 'assistant_setup_actions': sum(i['actor'] == 'assistant_operator' and i['before_first_provider_intent'] for i in interventions),
           'assistant_later_actions': sum(i['actor'] == 'assistant_operator' and not i['before_first_provider_intent'] for i in interventions),
           'decision_counts_by_actor': dict(collections.Counter(d['actor'] for d in decisions)),
           'live_build_decisions': sum(d['actor'] == 'live_model' and d['tool'] == 'build_provisional' for d in decisions),
           'selection_changes': changes, 'model_changes_after_candidate': len(corrective),
           'final_current_STEP_views_on_completed_receipts': final_views, 'final_image_request_ids': sorted({identity for _, identity, _ in final_images}),
           'model_rebuild_after_selection_event_sequences': [b['sequence'] for b in live_rebuilds], 'live_ready_finish_sequence': live_finish or None,
           'current_STEP_views_before_live_ready_finish': sorted(views_before_finish),
           'qualified_prior_and_current_visual_revision_sequence': visual_sequence, 'demonstrates': demonstration, 'engineering_approved': False}
    return row, requests


def historical():
    probe_path = OLD / 'provider/live_capability_smoke.json'; probes = load(probe_path)
    rows = []
    sources = [(f'capability-probe-{i+1}', probe_path, x['receipt']) for i, x in enumerate(probes['results'])]
    for path in sorted((OLD / 'live/three-station/events').glob('*.json')):
        event = load(path)
        if event['kind'] == 'decision': sources.append((f'task-decision-event-{event["sequence"]}', path, event['payload']['receipt']))
    for name, path, receipt in sources:
        usage = receipt.get('usage') or {}
        rows.append({'cohort': 'historical-v0.3-separate', 'trial': name, 'task_id': None, 'request_id': receipt.get('request_id'),
                     'durable_intent': True, 'outcome': 'completed', 'source': str(path), 'source_sha256': sha(path),
                     'prompt_tokens': integer(usage.get('prompt_tokens')), 'completion_tokens': integer(usage.get('completion_tokens')),
                     'observed_cost_usd': number(receipt.get('observed_cost_usd')), 'images': images(receipt),
                     'evidence_mode': receipt.get('evidence_mode'), 'returned_model': receipt.get('returned_model')})
    unknown_path = OLD / 'live/interrupted-followup/events/000002.json'; unknown = load(unknown_path)
    stop_path = OLD / 'live/interrupted-followup/events/000003.json'; stop = load(stop_path)
    assert unknown['kind'] == 'policy_requested' and stop['kind'] == 'interrupted_by_approval_review'
    load(OLD / 'provider/followup-approval-rejection.json')
    rows.append({'cohort': 'historical-v0.3-separate', 'trial': 'interrupted-followup-reservation', 'task_id': None, 'request_id': None,
                 'durable_intent': True, 'outcome': 'transmission_or_completion_unknown', 'source': str(unknown_path), 'source_sha256': sha(unknown_path),
                 'stop_source': str(stop_path), 'stop_sha256': sha(stop_path), 'prompt_tokens': None, 'completion_tokens': None,
                 'observed_cost_usd': None, 'images': [], 'note': 'Reserved policy call with no provider completion/billing receipt. Transmission is unconfirmed; never zero or not-sent.'})
    assert len(rows) == 7 and sum(r['outcome'] == 'completed' for r in rows) == 6
    return {'scope': 'Published v0.3 history, separate from all v0.4 denominators; no retry/reconciliation attempted.', 'requests': rows, 'totals': aggregate(rows)}


def dev8_comparison(rows):
    selected = [next(r for r in rows if r['cohort'] == cohort and r['trial'] == name)
                for cohort, name in [('dev8-initial', 'trial-02/task'), ('dev8-extension', 'trial-05/task')]]
    evidence = []
    for row in selected:
        task = Path(row['original_task']); state = load(task / 'state.json')['state']; candidate = state['domain']['current_candidate']
        cad_path = task / candidate['path'] / 'cad_sections.json'; cad = load(cad_path)
        selection_path = task / 'domain/revisions' / state['revision_id'] / 'selection.json'; selection = load(selection_path)
        ids = {s['id']: s.get('selected_candidate_id') for s in state['domain']['sections']}
        evidence.append({'trial': row['trial'], 'cad_sections_path': str(cad_path), 'cad_sections_sha256': sha(cad_path),
                         'selection_path': str(selection_path), 'selection_sha256': sha(selection_path), 'selected_candidate_ids': ids,
                         'qualified_visual_sequence': row['qualified_prior_and_current_visual_revision_sequence'], 'strict_valid': row['strict_valid'],
                         'selection_document': selection, 'cad_section_count': len(cad.get('sections', [])) if isinstance(cad, dict) else len(cad)})
    return {'trials': evidence, 'cad_section_bytes_equal': evidence[0]['cad_sections_sha256'] == evidence[1]['cad_sections_sha256'],
            'selection_document_bytes_equal': evidence[0]['selection_sha256'] == evidence[1]['selection_sha256'],
            'selected_candidate_ids_equal': evidence[0]['selected_candidate_ids'] == evidence[1]['selected_candidate_ids'],
            'native_calls': 0, 'source_pixels_or_reference_truth_read': False}


def render_report(summary):
    total = summary['v04_requests']
    lines = ['# Live provider accounting for MarinaFrame 0.4', '',
             'This ledger counts original task journals and provider receipts. Copied task directories are excluded. Runtime completion, strict task integrity, pixel-bearing request receipts and semantic reconstruction correctness are separate claims.', '',
             f"**{len(summary['trials'])} original v0.4 trials contain {total['intended']} intended requests: {total['completed']} completed, {total['failed']} failed, {total['unknown']} unknown and {total['not_sent']} explicitly not sent.** Reported usage totals {total['reported_prompt_tokens']:,} prompt and {total['reported_completion_tokens']:,} completion tokens. Cost coverage is {total['cost_receipt_coverage']}/{total['request_records']} receipts, with reported sum ${total['reported_cost_sum_usd']:.6f}. The separate v0.3 unresolved reservation remains unknown.", '',
             '## Cohort denominators', '',
             '| Cohort | Trials | Intended / completed / failed / unknown / not sent | Prompt / completion tokens reported | Cost receipts / requests | Reported cost sum | Strictly valid / currently review-ready |',
             '|---|---:|---|---:|---:|---:|---:|']
    for cohort, group in summary['cohorts'].items():
        t = group['requests']; lines.append(f"| {cohort} | {group['trials']} | {t['intended']} / {t['completed']} / {t['failed']} / {t['unknown']} / {t['not_sent']} | {t['reported_prompt_tokens']:,} / {t['reported_completion_tokens']:,} | {t['cost_receipt_coverage']} / {t['request_records']} | ${t['reported_cost_sum_usd']:.6f} | {group['strict_valid']} / {group['current_review_ready']} |")
    lines += ['', 'Reported zero cost means that a receipt explicitly returned zero. It is not proof of a zero-cost account, a total invoice, or absent charges when receipts are missing. Token totals similarly sum only reported fields. Every missing field remains visible in JSON coverage counts.', '',
              'The initial dev8 two-trial cohort is retained separately from its predeclared four-trial extension. The extension never changes the original denominator. Final-live accounting was admitted only after its terminal output lock; no sealed source image/spec or independent evaluator reference was opened by this aggregator.', '',
              '## Per-trial accounting', '',
              '| Trial | Historical terminal status | I / C / F / U / N | Tokens P / C | Cost coverage | Builds reserved / confirmed | Revision | Assistant setup | Final strict result |',
              '|---|---|---|---:|---:|---:|---|---:|---|']
    for r in summary['trials']:
        t = r['requests']; verdict = 'valid' if r['strict_valid'] else str(r['verification']['result'].get('error_code', 'rejected'))
        lines.append(f"| {r['cohort']} {r['trial']} | {r['historical_status']} | {t['intended']}/{t['completed']}/{t['failed']}/{t['unknown']}/{t['not_sent']} | {t['reported_prompt_tokens']:,}/{t['reported_completion_tokens']:,} | {t['cost_receipt_coverage']}/{t['request_records']} | {r['controller_build_reservations']}/{r['confirmed_new_build_attempts']} | {r['final_revision_id']} | {r['assistant_setup_actions']} | {verdict} |")
    lines += ['', '## What each trial demonstrates', '',
              'The final audit-bound view list matches completed image receipts to the STEP identity in the terminal validation contract. An empty list means that this particular classification has no matches; it does not prove that no STEP pixels were attached. In particular, an abstention without a final validation contract can still follow a request containing valid prior-candidate renders.', '']
    lines += [f"- **{r['cohort']} {r['trial']}:** {r['demonstrates']} Final audit-bound STEP views recorded on completed receipts: {', '.join(r['final_current_STEP_views_on_completed_receipts']) or 'none classified'}." for r in summary['trials']]
    h = summary['historical_v03']['totals']
    lines += ['', '## Separate published v0.3 history', '',
              f"The original records contain **six completed calls** (two capability probes and four task decisions), with **{h['reported_prompt_tokens']:,} prompt and {h['reported_completion_tokens']:,} completion tokens** reported. All six report observed cost $0. A seventh follow-up policy call was reserved and interrupted with **no provider completion or billing receipt**. Its transmission, tokens and cost remain unknown. It is never counted as zero or not-sent and is excluded from all v0.4 totals.", '',
              '## Accounting rules and limits', '',
              '- A completed provider receipt includes a valid returned decision. Failed decisions, including schema/summary violations, remain charged to the intended denominator and retain any reported usage/cost.',
              '- Explicit not-sent means the journal records that state; absence of a receipt is classified unknown. A task rejected before a provider intent contributes a trial but no request.',
              '- Every request is identified by original task ID and request ID. Duplicate copied identities are excluded from aggregate request totals and listed separately.',
              '- Old dev2/dev4 ready labels that fail the current strict numeric/audit reader remain rejected. Their provider usage remains part of historical accounting; their ready labels receive no current verified-success credit.',
              '- Completed pixel-bearing request receipts prove attached, bound image payload metadata, not that the model understood a drawing or that the selected interpretation is correct.',
              '- Assistant seed selection/build/render actions are counted separately. A model correction is not credited as a complete visual revision sequence unless prior and current STEP body/oblique receipts, changed selection, new build and final strict verification are present.',
              '- Development strict verification uses the unchanged final frozen binary. Final-live uses existing strict verification outputs bound by the terminal output lock, avoiding any independent reference/source inspection.',
              '- The aggregator opens no provider request payload, credential text, sealed source pixels/specifications or independent evaluator reference. It performs no native job, provider call, retry or evidence rewrite.', '']
    if summary.get('dev8_repair_comparison'):
        c = summary['dev8_repair_comparison']; lines += ['## Repeated dev8 interpretation', '',
            f"Trial02 and trial05 selected the same candidate IDs: **{c['selected_candidate_ids_equal']}**. Their CAD section bytes match: **{c['cad_section_bytes_equal']}**. Full selection-document bytes match: **{c['selection_document_bytes_equal']}**. Both sequence qualifications are retained in the JSON alongside exact event/request IDs. This comparison reads existing candidate/selection artifacts only; it does not rerun CAD or establish independent contour truth.", '']
    lines += ['## Evidence and reproducibility', '',
              'The accounting directory contains `accounting.json`, `provider-attempts.jsonl`, `provider-attempts.md`, `source-inventory.json`, the separate historical ledger, strict-verification results embedded per trial, and the immutable initial and final snapshots. The original runtime paths and SHA-256 identities permit auditing every counted receipt.', '',
              'Reproduce with `python benchmarks/v04_live_accounting.py --out /tmp/NEW_ACCOUNTING` for the original cohort; add `--include-dev8-extension` for the four separately declared additional trials. The final-live output lock is mandatory and checked by hash. All candidates retain `engineering_approved=false`.']
    return '\n'.join(lines) + '\n'


def main():
    global LOCK_FILES
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument('--out', type=Path, required=True); parser.add_argument('--include-dev8-extension', action='store_true'); args = parser.parse_args()
    assert args.out.is_relative_to('/tmp'); args.out.mkdir(parents=True, exist_ok=False)
    tasks = discover(args.include_dev8_extension)
    lock = load(FINAL / 'output-lock.json'); assert sha(FINAL / 'output-lock.json') == FINAL_LOCK_SHA
    LOCK_FILES = lock['file_sha256']; protocol = load(FINAL / 'execution-protocol.json')
    final_tasks = sorted(p / 'task' for p in FINAL.iterdir() if p.is_dir() and (p / 'task/state.json').is_file())
    assert len(final_tasks) == lock['attempts'] == 15
    tasks += [('final-live', task.parent.name, task) for task in final_tasks]
    initial_protocol = load(Path('/tmp/marinaframe-v04-dev8/protocol.json')); extension_protocol = load(Path('/tmp/marinaframe-v04-dev8/extension-protocol.json'))
    rows, requests, duplicates, seen = [], [], [], {}
    for cohort, name, path in tasks:
        row, calls = trial(cohort, name, path); rows.append(row)
        for call in calls:
            key = call['task_id'], call['request_id']
            if key in seen:
                duplicates.append({'identity': list(key), 'first': seen[key], 'duplicate_trial': f'{cohort}/{name}'})
            else:
                seen[key] = f'{cohort}/{name}'; requests.append(call)
        print(json.dumps({'accounted': f'{cohort}/{name}', 'intended': row['requests']['intended'], 'strict_valid': row['strict_valid']}), flush=True)
    history = historical(); groups = {}
    for cohort in dict.fromkeys(r['cohort'] for r in rows):
        group = [r for r in rows if r['cohort'] == cohort]; calls = [r for r in requests if r['cohort'] == cohort]
        groups[cohort] = {'trials': len(group), 'requests': aggregate(calls), 'strict_valid': sum(r['strict_valid'] for r in group),
                          'current_review_ready': sum(r['current_review_ready'] for r in group), 'assistant_setup_actions': sum(r['assistant_setup_actions'] for r in group),
                          'qualified_visual_revision_sequences': sum(r['qualified_prior_and_current_visual_revision_sequence'] for r in group)}
    summary = {'schema_version': 'marinaframe.live-accounting.v1', 'observed_at_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
               'script_sha256': sha(Path(__file__)), 'strict_verifier_binary_sha256': sha(BINARY), 'original_task_roots_only': True,
               'dev8_extension_included': args.include_dev8_extension, 'dev8_initial_protocol_sha256': sha(Path('/tmp/marinaframe-v04-dev8/protocol.json')),
               'dev8_extension_protocol_sha256': sha(Path('/tmp/marinaframe-v04-dev8/extension-protocol.json')),
               'dev8_declared_denominators': {'initial': initial_protocol['repeats'], 'extension': extension_protocol['additional_trials'], 'total': extension_protocol['total_attempt_denominator']},
               'final_live_output_lock_sha256': FINAL_LOCK_SHA, 'final_live_source_commit': protocol['source_commit'], 'final_live_binary_sha256': protocol['binary_sha256'],
               'trials': rows, 'cohorts': groups, 'v04_requests': aggregate(requests), 'duplicate_request_records_excluded': duplicates,
               'counter_difference_trials': [r['original_task'] for r in rows if r['counter_differences']],
               'historical_v03': history, 'direct_source_or_reference_reads': False, 'provider_request_payload_reads': False,
               'credential_reads': False, 'native_calls': 0, 'provider_calls': 0, 'engineering_approved': False}
    if args.include_dev8_extension: summary['dev8_repair_comparison'] = dev8_comparison(rows)
    changed = [path for path, item in INVENTORY.items() if sha(path) != item['sha256']]
    if changed: raise ValueError('Original accounting evidence changed during observation')
    dump(args.out / 'accounting.json', summary); dump(args.out / 'source-inventory.json', {'files': INVENTORY, 'changed_during_observation': changed})
    dump(args.out / 'historical-v03-separate.json', history)
    (args.out / 'provider-attempts.jsonl').write_text(''.join(json.dumps(row, allow_nan=False) + '\n' for row in requests))
    (args.out / 'REPORT.md').write_text(render_report(summary))
    table = ['# Retained provider attempts', '', '| Original trial | Request ID | Outcome | Prompt / completion tokens | Reported cost | Attached images | Error |', '|---|---|---|---:|---:|---:|---|']
    for r in requests:
        cost = 'unreported' if r['observed_cost_usd'] is None else '$' + str(r['observed_cost_usd'])
        table.append(f"| {r['cohort']} {r['trial']} | {r['request_id']} | {r['outcome']} | {r['prompt_tokens']} / {r['completion_tokens']} | {cost} | {sum(i['pixels_attached'] is True for i in r['images'])} | {r['error_code'] or ''} |")
    (args.out / 'provider-attempts.md').write_text('\n'.join(table) + '\n')
    print(json.dumps({'trials': len(rows), 'requests': summary['v04_requests'], 'counter_difference_trials': summary['counter_difference_trials'], 'duplicates': len(duplicates)}))


if __name__ == '__main__':
    main()
