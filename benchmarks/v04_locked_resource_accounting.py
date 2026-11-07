"""Resource-only summaries of locked final-live and assistant workflow records.

No source images/specs, request payloads, implementation solver code, independent
references or scores are opened. No provider/native process is launched.
"""
from __future__ import annotations

import argparse
import collections
import datetime
import hashlib
import json
from pathlib import Path

from v04_live_accounting import aggregate, images, integer, number

LIVE = Path('/tmp/marinaframe-v04-final-live/runs')
LIVE_LOCK = 'aa6c7fb5a6cb333b68ee9b1f2d1ba3a33f7ba063cc4aba0c1917fe73fa79070d'
ASSISTANT = Path('/tmp/marinaframe-v04-assistant-runs')
ASSISTANT_LOCK = '754113d9c1ab85081c286badbacb1c4ffcd816d129b31fb87bf6adccd69a9bb9'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class Locked:
    def __init__(self, root, expected):
        self.root = root
        self.lock_path = root / 'output-lock.json'
        if sha(self.lock_path) != expected:
            raise ValueError('Unexpected output-lock identity')
        self.lock = json.loads(self.lock_path.read_bytes())
        self.hashes = self.lock.get('file_sha256') or {r['path']: r['sha256'] for r in self.lock['files']}
        self.observed = {'output-lock.json': {'sha256': expected, 'bytes': self.lock_path.stat().st_size}}

    def read(self, path):
        path = Path(path)
        if not path.is_absolute():
            path = self.root / path
        relative = path.relative_to(self.root).as_posix()
        permitted = (path.name in {'attempt.json', 'state.json', 'verify.stdout', 'assistant-report.json'}
                     or path.parent.name in {'events', 'receipts'}
                     or (path.parent.name == 'operator' and path.name.endswith('_marinaframe.stdout.txt')))
        if not permitted or relative not in self.hashes:
            raise ValueError('Unadmitted resource-accounting path: ' + relative)
        raw = path.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        if digest != self.hashes[relative]:
            raise ValueError('Locked bytes changed: ' + relative)
        self.observed[relative] = {'sha256': digest, 'bytes': len(raw)}
        return json.loads(raw)

    def events(self, task):
        prefix = task.relative_to(self.root).as_posix() + '/events/'
        return [(self.root / p, self.read(p)) for p in sorted(self.hashes) if p.startswith(prefix) and p.endswith('.json')]

    def unchanged(self):
        return all(sha(self.root / p) == r['sha256'] for p, r in self.observed.items())


def numeric_sum(rows, field):
    values = [number(r.get(field)) for r in rows]
    present = [v for v in values if v is not None]
    return {'reported_sum': sum(present), 'coverage': len(present), 'records': len(rows)}


def worker_rows(locked, task, events):
    rows = []
    for path, event in events:
        if event['kind'] not in {'worker_result', 'worker_reconciled'}:
            continue
        payload = event['payload']
        artifact = payload['receipt']
        receipt_path = task / artifact['path']
        receipt = locked.read(receipt_path)
        if sha(receipt_path) != artifact['sha256']:
            raise ValueError('Worker receipt/event binding differs')
        if receipt['request_id'] != payload['response']['request_id']:
            raise ValueError('Worker identity differs')
        result = receipt.get('result') or {}
        candidate = result.get('candidate') or {}
        rows.append({'event_sequence': event['sequence'], 'event_path': str(path), 'event_sha256': sha(path),
                     'receipt_path': str(receipt_path), 'receipt_sha256': artifact['sha256'],
                     'request_id': receipt['request_id'], 'operation': receipt['operation'],
                     'execution_state': receipt['execution_state'], 'error_code': receipt.get('error_code'),
                     'reused': result.get('reused') is True,
                     'build_candidate_valid': candidate.get('valid') if receipt['operation'] == 'build_provisional' else None,
                     'supervision': payload.get('supervision'),
                     'worker_resources': receipt.get('resources'), 'inner_operation_resources': result.get('resources')})
    if len({r['request_id'] for r in rows}) != len(rows):
        raise ValueError('Duplicate adopted worker result; do not double count')
    return rows


def summarize_workers(rows):
    supervision = [r['supervision'] or {} for r in rows]
    worker = [r['worker_resources'] or {} for r in rows]
    inner = [r['inner_operation_resources'] or {} for r in rows]
    result = {
        'worker_results': len(rows), 'operation_counts': dict(collections.Counter(r['operation'] for r in rows)),
        'execution_states': dict(collections.Counter(r['execution_state'] for r in rows)),
        'controller_admission_queue_wait_seconds': numeric_sum(supervision, 'queue_wait_seconds'),
        'controller_supervision_execution_wall_seconds': numeric_sum(supervision, 'wall_seconds'),
        'bridge_reported_wall_seconds': numeric_sum(worker, 'wall_seconds'),
        'bridge_self_cpu_seconds': numeric_sum(worker, 'worker_cpu_seconds'),
        'bridge_waited_children_cpu_seconds': numeric_sum(worker, 'children_cpu_seconds'),
        'inner_operation_reported_wall_seconds': numeric_sum(inner, 'wall_seconds'),
        'maximum_reported_bridge_process_rss_kib': max((r.get('worker_peak_rss_kib', 0) for r in worker), default=0),
        'maximum_reported_descendant_process_rss_kib': max((r.get('children_peak_rss_kib', 0) for r in worker), default=0),
        'build_worker_attempts': sum(r['operation'] == 'build_provisional' for r in rows),
        'valid_new_build_results': sum(r['operation'] == 'build_provisional' and r['build_candidate_valid'] is True and not r['reused'] for r in rows),
        'reused_results': sum(r['reused'] for r in rows),
        'interpretation': 'Queue is domain-worker admission, including initialize/inspection as well as CAD/render/audit. Supervision wall excludes that separately reported queue. Bridge and inner wall/CPU observations are nested and must not be added. RUSAGE_CHILDREN is waited-descendant accounting. Individual-process RSS maxima are never summed into concurrent service memory.',
    }
    result['by_operation'] = {}
    for operation in sorted({r['operation'] for r in rows}):
        group = [r for r in rows if r['operation'] == operation]
        result['by_operation'][operation] = {
            'count': len(group),
            'queue_wait_seconds': numeric_sum([r['supervision'] or {} for r in group], 'queue_wait_seconds'),
            'supervision_wall_seconds': numeric_sum([r['supervision'] or {} for r in group], 'wall_seconds'),
            'inner_reported_wall_seconds': numeric_sum([r['inner_operation_resources'] or {} for r in group], 'wall_seconds')}
    return result


def live_resources():
    locked = Locked(LIVE, LIVE_LOCK)
    cases, all_requests, all_workers, times = [], [], [], []
    attempts = sorted(p for p in locked.hashes if len(Path(p).parts) == 2 and Path(p).name == 'attempt.json')
    if len(attempts) != 15:
        raise ValueError('Expected exactly fifteen original locked attempts')
    for attempt_path in attempts:
        attempt = locked.read(attempt_path)
        task = LIVE / Path(attempt_path).parent / 'task'
        checkpoint = locked.read(task / 'state.json')
        state = checkpoint['state']
        events = locked.events(task)
        times += [e['time_ms'] for _, e in events]
        verify = locked.read(task.parent / 'verify.stdout')
        if not verify.get('valid') or verify['head_sha256'] != checkpoint['head_sha256']:
            raise ValueError('Retained verifier does not bind the terminal task')
        intents, requests, worker = {}, [], worker_rows(locked, task, events)
        for path, event in events:
            payload = event['payload']
            if event['kind'] == 'provider_intent':
                intents[payload['request_id']] = event
            if event['kind'] not in {'provider_result', 'provider_reconciled'}:
                continue
            artifact = payload['receipt_file']
            receipt_path = task / artifact['path']
            receipt = locked.read(receipt_path)
            if sha(receipt_path) != artifact['sha256']:
                raise ValueError('Provider receipt/event binding differs')
            identity = receipt['request_id']
            usage = receipt.get('usage') or {}
            intent = intents.get(identity)
            requests.append({'task_id': state['task_id'], 'request_id': identity,
                             'durable_intent': intent is not None, 'outcome': receipt['state'],
                             'receipt_path': str(receipt_path), 'receipt_sha256': artifact['sha256'],
                             'event_sequence': event['sequence'], 'event_sha256': sha(path),
                             'attempt': receipt.get('attempt'), 'retry_of': receipt.get('retry_of'),
                             'http_status': receipt.get('http_status'), 'error_code': receipt.get('error_code'),
                             'prompt_tokens': integer(usage.get('prompt_tokens')), 'completion_tokens': integer(usage.get('completion_tokens')),
                             'observed_cost_usd': number(receipt.get('observed_cost_usd')),
                             'reported_list_cost_usd': number(usage.get('list_cost')), 'billing_source': usage.get('billing_source'),
                             'latency_seconds': number(receipt.get('latency_seconds')),
                             'images': images(receipt), 'supervision': payload.get('supervision')})
        if len({r['request_id'] for r in requests}) != len(requests):
            raise ValueError('Duplicate adopted provider outcome; inspect instead of double counting')
        represented = {r['request_id'] for r in requests}
        receipt_prefix = task.relative_to(LIVE).as_posix() + '/receipts/request-'
        locked_provider_ids = {Path(p).stem for p in locked.hashes if p.startswith(receipt_prefix) and p.endswith('.json')}
        if locked_provider_ids != represented:
            raise ValueError('Unadopted or missing provider receipt requires separate reconciliation accounting')
        for identity, event in intents.items():
            if identity not in represented:
                explicit = next((e for _, e in events if e['kind'] == 'provider_not_sent' and e['payload'].get('request_id') == identity), None)
                requests.append({'task_id': state['task_id'], 'request_id': identity, 'durable_intent': True,
                                 'outcome': 'not_sent' if explicit else 'transmission_or_completion_unknown',
                                 'prompt_tokens': None, 'completion_tokens': None, 'observed_cost_usd': None,
                                 'reported_list_cost_usd': None, 'images': [], 'attempt': event['payload'].get('attempt'),
                                 'retry_of': event['payload'].get('retry_of'), 'latency_seconds': None})
        totals = aggregate(requests)
        counter_map = {'intended': 'requests_intended', 'completed': 'requests_completed', 'failed': 'requests_failed',
                       'unknown': 'requests_unknown', 'not_sent': 'requests_not_sent', 'reported_prompt_tokens': 'prompt_tokens',
                       'reported_completion_tokens': 'completion_tokens', 'reported_cost_sum_usd': 'observed_cost_usd'}
        differences = {k: [totals[k], state['counters'].get(v)] for k,v in counter_map.items() if totals[k] != state['counters'].get(v)}
        if differences:
            raise ValueError('Provider counter mismatch: ' + json.dumps(differences))
        attached = [(r['request_id'], i) for r in requests if r['outcome'] == 'completed'
                    for i in r['images'] if i.get('pixels_attached') is True
                    and i.get('evidence_kind') in {'step_reimport_render', 'step_section_cut_comparison'}]
        validation = (state.get('domain') or {}).get('validation') or {}
        binding = (validation.get('contract') or {}).get('binding') or {}
        current = [(rid, i) for rid, i in attached if binding.get('step_sha256') and i.get('step_sha256') == binding['step_sha256']
                   and i.get('generation_id') == state['generation_id'] and i.get('revision_id') == state['revision_id']]
        rejected = [{'sequence': e['sequence'], 'reason': e['payload'].get('reason')} for _,e in events if e['kind'] == 'finalization_rejected']
        no_progress = [{'sequence': e['sequence'], 'reason': e['payload'].get('reason')} for _,e in events
                       if e['kind'] == 'task_terminated' and any(x in str(e['payload'].get('reason','')).lower() for x in ('no_progress', 'no progress', 'repeated_action'))]
        row = {'case_id': attempt['case_id'], 'task_id': state['task_id'], 'workflow_status': state['status'],
               'terminal_head_sha256': checkpoint['head_sha256'], 'generation_id': state['generation_id'], 'revision_id': state['revision_id'],
               'strict_history_valid': verify['valid'], 'verification_source': str(task.parent/'verify.stdout'),
               'provider': totals, 'requests': requests, 'recorded_counters': state['counters'], 'counter_differences': differences,
               'provider_retry_attempts': sum((r.get('attempt') or 1) > 1 or r.get('retry_of') is not None for r in requests),
               'provider_reported_list_cost_usd': numeric_sum(requests, 'reported_list_cost_usd'),
               'provider_receipt_latency_seconds': numeric_sum(requests, 'latency_seconds'),
               'workers': worker, 'worker_summary': summarize_workers(worker),
               'attempt_wall_seconds': attempt['wall_seconds'],
               'command_stage_times': [{'stage': c['stage'], 'wall_seconds': c['wall_seconds'], 'exit_code': c['exit_code']} for c in attempt['commands']],
               'event_kind_counts': dict(collections.Counter(e['kind'] for _,e in events)),
               'finalization_rejections': rejected, 'no_progress_terminations': no_progress,
               'action_fingerprint_count': len(state['action_fingerprints']),
               'maximum_action_fingerprint_occurrences': max(state['action_fingerprints'].values(), default=0),
               'attached_completed_STEP_image_entries': len(attached),
               'attached_completed_STEP_image_entries_by_kind': dict(collections.Counter(i['evidence_kind'] for _,i in attached)),
               'attached_completed_STEP_views': dict(collections.Counter(i['view'] for _,i in attached)),
               'requests_with_completed_STEP_pixels': sorted({rid for rid,_ in attached}),
               'unique_completed_STEP_image_hashes': sorted({i['sha256'] for _,i in attached}),
               'terminal_validation_STEP_binding_present': bool(binding.get('step_sha256')),
               'final_audit_bound_STEP_views': sorted({i['view'] for _,i in current}),
               'engineering_approved': False}
        cases.append(row); all_requests += requests; all_workers += worker
    if not locked.unchanged():
        raise ValueError('A locked source changed during read-only accounting')
    return {'schema_version': 'marinaframe.final-live-resources.v1', 'output_lock_sha256': LIVE_LOCK,
            'source_root': str(LIVE), 'cases': cases, 'case_count': len(cases),
            'workflow_status_counts': dict(collections.Counter(r['workflow_status'] for r in cases)),
            'provider_totals': aggregate(all_requests), 'worker_totals': summarize_workers(all_workers),
            'provider_reported_list_cost_usd': numeric_sum(all_requests, 'reported_list_cost_usd'),
            'account_invoice_cost_usd': None,
            'controller_parent_cpu_seconds': None, 'controller_parent_peak_rss_kib': None,
            'simultaneous_service_peak_rss_kib': None,
            'provider_receipt_latency_seconds': numeric_sum(all_requests, 'latency_seconds'),
            'sum_attempt_wall_seconds': sum(r['attempt_wall_seconds'] for r in cases),
            'first_to_last_journal_event_span_seconds': (max(times)-min(times))/1000,
            'provider_retry_attempts': sum(r['provider_retry_attempts'] for r in cases),
            'finalization_rejection_count': sum(len(r['finalization_rejections']) for r in cases),
            'no_progress_termination_count': sum(len(r['no_progress_terminations']) for r in cases),
            'maximum_action_fingerprint_occurrences': max(r['maximum_action_fingerprint_occurrences'] for r in cases),
            'attached_completed_STEP_image_entries': sum(r['attached_completed_STEP_image_entries'] for r in cases),
            'attached_completed_STEP_image_entries_by_kind': dict(collections.Counter(i['evidence_kind'] for r in all_requests for i in r['images']
                if r['outcome'] == 'completed' and i.get('pixels_attached') is True
                and i.get('evidence_kind') in {'step_reimport_render', 'step_section_cut_comparison'})),
            'all_attached_image_entries_by_kind': dict(collections.Counter(i['evidence_kind'] for r in all_requests for i in r['images'] if i.get('pixels_attached') is True)),
            'completed_requests_with_STEP_pixels': sum(len(r['requests_with_completed_STEP_pixels']) for r in cases),
            'strictly_verified_histories': sum(r['strict_history_valid'] for r in cases),
            'all_read_inputs_unchanged': True, 'observed_locked_inputs': locked.observed,
            'limitations': ['Resource/status accounting only; no accuracy score or reference was read.',
                           'Reported observed cost 0 is a receipt field, not proof of zero invoice cost; missing fields remain unknown.',
                           'Provider list_cost is a separate reported nominal price field, not an additional charge to add to observed cost.',
                           'Tasks overlap. Summed case, provider and worker walls are work totals, not campaign elapsed; journal span excludes launch/setup and trailing verify overhead.',
                           'Queue includes all serialized domain-worker operations and is not isolated CAD compute time.',
                           'The final audit-bound view list requires terminal validation; an empty list is not proof that no STEP pixels were attached.',
                           'Memory maxima belong to individual processes and waited descendants, not simultaneous process-tree/service memory.'],
            'new_provider_or_native_calls': 0, 'reference_or_score_reads': 0, 'source_image_spec_or_request_payload_reads': 0}


def assistant_resources():
    locked = Locked(ASSISTANT, ASSISTANT_LOCK)
    report = locked.read('assistant-report.json')
    if sha(ASSISTANT/'assistant-report.json') != locked.lock['report_sha256']:
        raise ValueError('Assistant report binding differs')
    cases, all_workers = [], []
    for original in report['cases']:
        task = Path(original['task_dir'])
        checkpoint = locked.read(task/'state.json'); state = checkpoint['state']
        if checkpoint['head_sha256'] != original['head_sha256'] or state['counters'] != original['final_status']['counters']:
            raise ValueError('Assistant report differs from locked terminal state')
        verify = locked.read(original['verify_stdout'])
        if not verify.get('valid') or verify['head_sha256'] != checkpoint['head_sha256']:
            raise ValueError('Assistant retained verification does not bind the state')
        events = locked.events(task); workers = worker_rows(locked, task, events)
        interventions = [{'event_sequence': e['sequence'], 'actor': e['payload'].get('actor'),
                          'tool': e['payload']['decision']['tool']} for _,e in events if e['kind'] == 'operator_intervention']
        if len(interventions) != original['intervention_count']:
            raise ValueError('Assistant intervention count differs')
        cases.append({'case_id': original['case_id'], 'task_id': state['task_id'], 'workflow_status': state['status'],
                      'head_sha256': checkpoint['head_sha256'], 'strict_history_valid': verify['valid'],
                      'recorded_counters': state['counters'], 'interventions': interventions,
                      'intervention_count': len(interventions), 'intervention_type_counts': dict(collections.Counter(i['tool'] for i in interventions)),
                      'rendered_views': original['rendered_views'], 'workers': workers, 'worker_summary': summarize_workers(workers),
                      'native_cli_elapsed_seconds_reported': original['native_cli_elapsed_seconds'],
                      'native_cli_child_cpu_seconds_reported': original['native_cli_child_cpu_seconds'],
                      'task_disk_bytes_at_summary': original['task_disk_bytes_at_summary'],
                      'failed_or_rejected_cli_commands': original['failed_or_rejected_cli_commands'],
                      'worker_failures': original['worker_failures'], 'live_provider_used': False,
                      'human_review_performed': False, 'naval_architect_review_performed': False, 'engineering_approved': False})
        all_workers += workers
    if not locked.unchanged():
        raise ValueError('A locked assistant source changed')
    return {'schema_version': 'marinaframe.assistant-resource-accounting.v1', 'output_lock_sha256': ASSISTANT_LOCK,
            'assistant_report_sha256': locked.lock['report_sha256'], 'role': report['role'], 'cases': cases,
            'primary_attempts': report['primary_attempts'], 'extra_primary_attempts': report['extra_primary_attempts'],
            'interventions_total': sum(r['intervention_count'] for r in cases),
            'workflow_status_counts': dict(collections.Counter(r['workflow_status'] for r in cases)),
            'worker_totals': summarize_workers(all_workers), 'elapsed_accounting_reported': report['elapsed_accounting'],
            'visual_observation_entries_reported': len(report['visual_observations']),
            'failed_or_rejected_logged_commands': len(report['failed_or_rejected_logged_commands']),
            'task_provider_requests_total': sum(r['recorded_counters']['requests_intended'] for r in cases),
            'task_provider_prompt_tokens_total': sum(r['recorded_counters']['prompt_tokens'] for r in cases),
            'task_provider_completion_tokens_total': sum(r['recorded_counters']['completion_tokens'] for r in cases),
            'assistant_conversation_tokens': None, 'assistant_conversation_cost_usd': None,
            'all_read_inputs_unchanged': True, 'observed_locked_inputs': locked.observed,
            'limitations': ['Assistant operator arm, not a human or naval architect review.',
                           'Zero task-provider calls does not establish zero token/cost for the assistant conversation; those are not metered in this evidence.',
                           'Session wall minus measured subprocess wait is a collaboration-effort proxy; image viewing, connector/orchestration/context/bootstrap time remain included.',
                           'The historical verifier outputs were read under the output lock; this collector did not reopen mutable CLI lockfiles or rerun commands.',
                           'No semantic correctness or independent geometry score is inferred from workflow status or rendered views.'],
            'new_provider_or_native_calls': 0, 'reference_or_score_reads': 0, 'source_image_spec_or_request_payload_reads': 0}


def findings(live, assistant):
    p, w, effort = live['provider_totals'], live['worker_totals'], assistant['elapsed_accounting_reported']
    lines = ['# Locked final-arm resource accounting', '',
             'This is resource/workflow accounting only. No reference geometry, accuracy score, source image/specification, provider request payload or solver implementation was read. The original terminal output locks bind every admitted input; no task or lockfile was mutated and no provider/native job was launched.', '',
             '## Fifteen final-live attempts', '',
             f"All {live['case_count']} original attempts are retained: 8 review-ready, 3 abstained and 4 blocked; all 15 existing strict verifier records bind their locked terminal heads. Status is not independent accuracy.", '',
             f"There are **{p['intended']} intended / {p['completed']} completed / {p['failed']} failed / {p['unknown']} unknown / {p['not_sent']} not-sent requests**, reporting **{p['reported_prompt_tokens']:,} prompt and {p['reported_completion_tokens']:,} completion tokens**. All 74 receipts explicitly report observed cost 0, with no missing reported price/token fields. The separate nominal `list_cost` sum is ${live['provider_reported_list_cost_usd']['reported_sum']:.8f}; it is not an additional charge or an invoice. Actual account billing is not established by these records.", '',
             f"The worker records contain {w['worker_results']} completed operations: 15 initialization, 19 source inspections, 9 contour selections, 8 builds, 16 renders and 19 validations. All eight builds returned valid candidates. Eleven operation results explicitly report reuse. There are zero provider retries, zero recorded no-progress terminations and no action fingerprint count above one. Three attempted finalizations were rejected until current STEP body/oblique pixels were transmitted.", '',
             f"Summed admission wait is **{w['controller_admission_queue_wait_seconds']['reported_sum']:.3f} s**, separately from **{w['controller_supervision_execution_wall_seconds']['reported_sum']:.3f} s** of supervised worker execution. Admission includes initialization/source inspection/selection as well as CAD, rendering and audit. These are totals across overlapping tasks, not elapsed campaign duration. Summed case wall is {live['sum_attempt_wall_seconds']:.3f} s; the first-to-last journal-event span is {live['first_to_last_journal_event_span_seconds']:.3f} s and excludes unlogged launch/setup and trailing verification overhead. Provider receipt latency sums to {live['provider_receipt_latency_seconds']['reported_sum']:.3f} s, with the same overlap caveat.", '',
             '| Case | Workflow status | Completed requests | Prompt / completion tokens | Attempt wall s | Admission wait s | Worker execution s | Attached STEP render / cut entries |',
             '|---|---|---:|---:|---:|---:|---:|---:|']
    for row in live['cases']:
        t, r, kinds = row['provider'], row['worker_summary'], row['attached_completed_STEP_image_entries_by_kind']
        lines.append(f"| {row['case_id']} | {row['workflow_status']} | {t['completed']} | {t['reported_prompt_tokens']:,} / {t['reported_completion_tokens']:,} | {row['attempt_wall_seconds']:.3f} | {r['controller_admission_queue_wait_seconds']['reported_sum']:.3f} | {r['controller_supervision_execution_wall_seconds']['reported_sum']:.3f} | {kinds.get('step_reimport_render',0)} / {kinds.get('step_section_cut_comparison',0)} |")
    lines += ['',
              f"There are {p['attached_image_receipt_entries']} image attachment entries on {p['requests_with_attached_images']} completed requests. They comprise 63 source pages, 129 source-candidate overlays, 21 STEP render entries (13 body and 8 oblique) and 39 STEP section-cut comparisons. STEP-derived pixels appear in {live['completed_requests_with_STEP_pixels']} completed requests. Repeated attachments are entries, not unique drawings or independent observations. The JSON retains image hashes, view labels and STEP/generation/revision bindings. Attached pixels do not prove comprehension or semantic correctness.", '',
              f"Largest reported bridge process maximum is {w['maximum_reported_bridge_process_rss_kib']:,} KiB and largest descendant-process maximum is {w['maximum_reported_descendant_process_rss_kib']:,} KiB. They are separate process maxima and are not summed into a service peak. Bridge self CPU totals {w['bridge_self_cpu_seconds']['reported_sum']:.3f} s and waited-child CPU {w['bridge_waited_children_cpu_seconds']['reported_sum']:.3f} s; nested inner-worker records are retained but not added again.", '',
              '## Reference-blind assistant operator effort', '',
              'The locked assistant report covers two attempts, no extra primary attempts, one review-ready outcome and one abstention. It records six typed assistant interventions: five in the constructed case and one finish/abstain action in the ambiguous case. These were assistant actions, not human or naval-architect review. Five actual-view entries are reported by that operator; this collector did not reopen the images.', '',
              f"Reported session wall was **{effort['session_wall_seconds_including_tool_wait_to_summary']:.3f} s** including tool waits. Measured subprocess wait was {effort['measured_subprocess_wait_seconds_all_logged_commands']:.3f} s, including {effort['native_controller_cli_wait_seconds']:.3f} s of native-controller CLI time. The remaining {effort['session_wall_seconds_minus_measured_subprocess_wait']:.3f} s is a collaboration-effort proxy containing image-viewer, connector, orchestration, context and unseparated bootstrap time; it is not measured model inference or human labor. The {effort['controller_admission_queue_wait_seconds']:.9f} s admission wait is already inside CLI elapsed and must not be subtracted twice.", '',
              'The task journals record zero live-provider requests and zero task-provider tokens. Assistant conversation token use and cost are **unmetered/unknown**, not zero. The operator reported no failed/rejected commands; all ten worker results completed, with one actual build, two STEP renders and one reused validation result. No professional engineering approval occurred.', '',
              '## Provenance and reproduction', '',
              f"Live output lock: `{LIVE_LOCK}`. Assistant output lock: `{ASSISTANT_LOCK}`. The JSON summaries retain the observed input inventory, exact per-request/per-worker provenance, original counters, coverage and limitations. {len(live['observed_locked_inputs'])} live and {len(assistant['observed_locked_inputs'])} assistant lock-bound inputs were rehashed unchanged after collection.", '',
              'Run `python benchmarks/v04_locked_resource_accounting.py --out /tmp/NEW_RESOURCE_ACCOUNTING` against the retained original locked roots. The collector creates only its new output directory. Workflow/resource comparisons do not establish model superiority or geometric accuracy.', '']
    return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    if not args.out.is_absolute() or not args.out.is_relative_to('/tmp'):
        raise ValueError('Use a new absolute /tmp output directory')
    args.out.mkdir(parents=True, exist_ok=False)
    live, assistant = live_resources(), assistant_resources()
    identity = {'collected_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
                'collector_sha256': sha(Path(__file__)),
                'accounting_helpers_sha256': sha(Path(__file__).with_name('v04_live_accounting.py'))}
    for name, value in [('v04_live_resources.json', live), ('v04_assistant_resources.json', assistant)]:
        value.update(identity)
        (args.out/name).write_text(json.dumps(value, indent=2, allow_nan=False)+'\n')
    (args.out/'v04_resource_findings.md').write_text(findings(live, assistant))
    print(json.dumps({'live_cases': live['case_count'], 'live_provider': live['provider_totals'],
                      'live_workers': live['worker_totals'], 'live_status': live['workflow_status_counts'],
                      'assistant_cases': assistant['primary_attempts'], 'assistant_interventions': assistant['interventions_total'],
                      'all_read_inputs_unchanged': True}))


if __name__ == '__main__':
    main()
