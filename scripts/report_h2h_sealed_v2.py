"""Publish compact evidence from the completed, independently scored v2 run."""
from __future__ import annotations

import csv
import hashlib
import json
import statistics
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
MAIN = Path('/Users/jonathanjie/Documents/workspace/MarinaFrame')
ROOT = MAIN / 'work/h2h-sealed-v2'
sys.path.insert(0, str(ROOT / 'snapshot'))
from benchmarks.factory import report  # noqa: E402

DEVIATIONS = [
    'The first driver process stopped at 05:36 when its router session ended its turn (65 abstain cases done). '
    'The two abstain cases in progress (shipd-3-06455-separate-L1, -L2) are counted as failures '
    '(`interrupted_by_harness_stop`) and were not rerun. A detached resume driver ran only the cases that had not started.',
    'The original driver did not pass `--model-review true`, although the pre-registered LLM-first arm includes the W12 veto. '
    'The resume driver added it for the LLM arm only, before any LLM case ran.',
]


def timed(rows: list[dict]) -> list[float]:
    # Interrupted cases have no case time and no counters; they count as failures, not as zero-time runs.
    return [r['seconds'] for r in rows if r['seconds'] is not None]


def aggregate(rows: list[dict]) -> dict:
    return {
        'cases': len(rows), 'built': sum(r['built'] for r in rows),
        'correct': sum(r['correct'] for r in rows),
        'silent_wrong': sum(r['silent_wrong'] for r in rows),
        'labelled_wrong_draft': sum(r['labelled_wrong_draft'] for r in rows),
        'statuses': dict(sorted(Counter(r['controller_status'] for r in rows).items())),
        'failure_kinds': dict(sorted(Counter(r['failure_kind'] for r in rows if r['failure_kind']).items())),
        'guesses_total': sum(r['guesses'] for r in rows),
        'guesses_median': statistics.median(r['guesses'] for r in rows),
        'lines_total': sum(r['lines'] for r in rows),
        'lines_median': statistics.median(r['lines'] for r in rows),
        'requests': {k: sum(r.get(k, 0) for r in rows) for k in (
            'requests_intended', 'requests_completed', 'requests_failed', 'requests_unknown', 'requests_not_sent')},
        'prompt_tokens': sum(r.get('prompt_tokens', 0) for r in rows),
        'completion_tokens': sum(r.get('completion_tokens', 0) for r in rows),
        'list_cost_usd': sum(r['list_cost_usd'] for r in rows),
        'observed_cost_usd': sum(r.get('observed_cost_usd', 0.0) for r in rows),
        'list_cost_receipts': sum(r['list_cost_receipts'] for r in rows),
        'case_wall_sum_seconds': sum(timed(rows)),
        'case_wall_median_seconds': statistics.median(timed(rows)),
    }


def table_row(label: str, data: dict) -> str:
    status = data['statuses']
    failures = sum(data['failure_kinds'].values())
    return (f"| {label} | {data['cases']} | {data['built']} | {data['correct']} | {data['silent_wrong']} | "
            f"{data['labelled_wrong_draft']} | {status.get('awaiting_human_review', 0)} | "
            f"{status.get('draft_not_verified', 0)} | {status.get('abstained', 0)} | "
            f"{status.get('blocked', 0)} | {failures} | {data['guesses_median']:g} / {data['lines_median']:g} |")


def main() -> None:
    destination = REPO / 'outputs/h2h-sealed-v2'
    assert not destination.exists(), 'Do not replace published evidence'
    freeze = json.loads((ROOT / 'freeze.json').read_text())
    for relative, expected in freeze['files_sha256'].items():
        assert hashlib.sha256((ROOT / 'snapshot' / relative).read_bytes()).hexdigest() == expected
    campaign = json.loads((ROOT / 'campaign.json').read_text())
    assert campaign.get('finished')
    summary = {'split': 'hull-disjoint (v2)', 'caveat': 'Clusters can share broad families with the frozen splits; this is not family-disjoint.',
               'freeze': {k: v for k, v in freeze.items() if k != 'files_sha256'},
               'campaign': campaign, 'protocol_deviations': DEVIATIONS, 'arms': {}}
    all_rows = {}
    for arm in ('abstain', 'draft', 'llm'):
        assert (ROOT / f'{arm}-scored.json').exists()
        rows = report.load_rows(ROOT, [arm])
        assert len(rows) == len({r['case_id'] for r in rows}) == 288
        compact = []
        for row in rows:
            score = row.pop('score')
            if row['built']:
                assert score is not None
            row['score_status'] = score.get('status') if score else 'no_model'
            # Unknown scorer outcomes are not silently called wrong geometry.
            gate_failed = bool(score and score.get('status') == 'scored' and not row['correct'])
            row['silent_wrong'] = row['controller_status'] == 'awaiting_human_review' and row['built'] and gate_failed
            row['labelled_wrong_draft'] = row['controller_status'] == 'draft_not_verified' and row['built'] and gate_failed
            counters = row.pop('counters')
            row.update(counters)
            compact.append(row)
        all_rows[arm] = compact
        data = aggregate(compact)
        data['arm_wall_seconds'] = json.loads((ROOT / f'{arm}-finished.json').read_text())['wall_seconds_this_session']
        data['score_statuses'] = dict(Counter(r['score_status'] for r in compact))
        data['by_layout'] = {layout: aggregate([r for r in compact if r['layout'] == layout]) for layout in ('separate', 'overlay')}
        data['by_level'] = {str(level): aggregate([r for r in compact if r['level'] == level]) for level in range(4)}
        data['by_layout_level'] = {f'{layout}/L{level}': aggregate([r for r in compact if r['layout'] == layout and r['level'] == level])
                                   for layout in ('separate', 'overlay') for level in range(4)}
        summary['arms'][arm] = data
    arms = summary['arms']
    if not arms['llm']['silent_wrong'] and arms['llm']['correct'] >= arms['draft']['correct']:
        tied = arms['llm']['correct'] == arms['draft']['correct']
        if tied and not arms['draft']['silent_wrong'] and arms['draft']['labelled_wrong_draft'] < arms['llm']['labelled_wrong_draft']:
            decision = 'draft' if arms['draft']['correct'] > arms['abstain']['correct'] else 'abstain'
        else:
            decision = 'llm'
    elif not arms['draft']['silent_wrong'] and arms['draft']['correct'] > arms['abstain']['correct']:
        decision = 'draft'
    else:
        decision = 'abstain'
    summary['decision'] = decision
    destination.mkdir(parents=True)
    for arm, rows in all_rows.items():
        (destination / f'{arm}.jsonl').write_text(''.join(json.dumps(r, sort_keys=True) + '\n' for r in rows))
    (destination / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    header = ('| Arm / group | Cases | Built | Correct | Silent wrong | Wrong draft | Review-ready | Draft status | Abstained | Blocked | Failed* | Guesses / lines median |\n'
              '|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|')
    text = ['## Head-to-head, hull-disjoint (v2)', '',
            '**Silent wrong builds are reported first:** ' + ', '.join(f'{a}: {arms[a]["silent_wrong"]}' for a in arms) + '.', '',
            '**Decision from the pre-registered rule: ' + {'llm': 'LLM-first becomes the default', 'draft': 'deterministic draft becomes the default; LLM-first remains an explicit option', 'abstain': 'abstain stays the default'}[decision] + '.** No app setting was changed by this evaluation.', '',
            'Protocol: [pre-registration](plans/2026-11-08-h2h-sealed-v2.md). Each arm ran once on all 288 drawings, with two jobs at most. '
            'Frozen inference code is `7c2d4f6`, captured from `d9d8609` (only the protocol document differs). '
            'DeepSeek uses `deepseek-v4.1-flash`, draft ambiguity mode, the frozen W11 tools and CLI operational defaults, '
            'with W12/W14 code present. The W12 `--model-review` veto was enabled for the LLM arm by the resume driver, before any LLM case ran (see deviations). '
            'No retries replaced results and no inference settings changed after the first case.', '',
            '**Broad-family caveat:** ' + summary['caveat'] + ' These are 36 Ship-D hulls, both layouts, four levels; no named real-ship family is included.', '',
            '**Restoration note (not a protocol deviation):** ' + freeze['restoration'] + ' Before the first case, this run independently checked all 900 unique drawing/spec/parameter/truth files against the frozen manifests (288 cases, 36 truth tables). '
            'Hash checking is separate from inference. Inference received only each drawing/spec input folder; it never opened sealed truth. '
            'Each arm was scored only after completion, using the existing independent factory scorer and unchanged 2% RMS half-beam / 5% in-range volume gate. '
            'Scoring used the same per-user native admission lock as inference.', '',
            f"Snapshot tree SHA-256: `{freeze['snapshot_tree_sha256']}`. Controller SHA-256: `{freeze['controller_sha256']}`. "
            f"Git archive SHA-256: `{freeze['git_archive_sha256']}`. Manifest SHA-256: `{freeze['split_manifest_sha256']}`.", '',
            header]
    text += [table_row(arm, arms[arm]) for arm in arms]
    text += ['', '*Failed includes blocked and other non-built/non-abstained outcomes; it overlaps the blocked column. '
             'Built counts valid CAD candidates even if the final status is not review-ready. Lines are sections with a selected or guessed source-backed candidate, not correct models. '
             'Guesses count open final-state guesses. A missing model is `no_model`, not zero error.', '', '### By layout and level', '', header]
    for arm in arms:
        for group, data in arms[arm]['by_layout_level'].items():
            text.append(table_row(f'{arm} / {group}', data))
    text += ['', '### Marginal layout and level counts', '', header]
    for arm in arms:
        for group, data in arms[arm]['by_layout'].items(): text.append(table_row(f'{arm} / {group}', data))
        for group, data in arms[arm]['by_level'].items(): text.append(table_row(f'{arm} / L{group}', data))
    text += ['', '### Model usage, wall time and failures', '',
             'Arm wall is for the driver session that finished the arm; abstain also ran 65 cases before the interruption.', '',
            '| Arm | Requests intended / completed / failed / unknown / not sent | Prompt tokens | Completion tokens | List cost USD | Observed cost USD | Arm wall s | Case wall median s |',
             '|---|---:|---:|---:|---:|---:|---:|---:|']
    for arm, data in arms.items():
        requests = ' / '.join(str(v) for v in data['requests'].values())
        text.append(f"| {arm} | {requests} | {data['prompt_tokens']:,} | {data['completion_tokens']:,} | {data['list_cost_usd']:.8f} | {data['observed_cost_usd']:.8f} | {data['arm_wall_seconds']:.1f} | {data['case_wall_median_seconds']:.1f} |")
    text += ['', 'List cost is provider-reported nominal usage, not an invoice. Observed cost is the receipt cost field; subscription cost is unknown. '
             'Case wall includes native queue waits and provider time. Summed case wall is not elapsed arm wall.', '']
    for arm, data in arms.items():
        text.append(f"- **{arm} failures:** `{json.dumps(data['failure_kinds'], sort_keys=True)}`. Score statuses: `{json.dumps(data['score_statuses'], sort_keys=True)}`.")
    text += ['', '**Protocol deviations:**', ''] + [f'- {d}' for d in DEVIATIONS] + ['', 'The dataset restoration preserved the frozen input bytes. '
             'The split is now spent for model selection; later tuning requires a new holdout.', '',
             'Compact per-case rows and all marginal counts, usage, timing and provenance: [`outputs/h2h-sealed-v2/`](../outputs/h2h-sealed-v2/). '
             'Full finished task folders remain local under the main checkout’s ignored `work/h2h-sealed-v2/`. Drawings, truth, overlays and credentials are not committed.', '']
    (ROOT / 'report-section.md').write_text('\n'.join(text))
    print(json.dumps({'decision': decision, 'arms': {a: {k: d[k] for k in ('cases', 'built', 'correct', 'silent_wrong', 'labelled_wrong_draft')} for a, d in arms.items()}}, indent=2))


if __name__ == '__main__':
    main()
