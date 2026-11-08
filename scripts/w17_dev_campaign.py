"""Reproduce the W17 development-only investigator comparison.

Raw inputs, tasks and receipts belong in the main checkout's work/w17 directory.
The sample is fixed from manifest metadata, never from inference outcomes.
"""
from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
MAIN = Path('/Users/jonathanjie/Documents/workspace/MarinaFrame')
OUT = MAIN / 'work/w17'


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + '\n')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def prepare():
    import numpy as np
    from benchmarks.factory import generate as generator, hulls
    from benchmarks.llm_setup_review import sample

    rows = [json.loads(line) for line in (ROOT / 'benchmarks/factory/manifests/cases.jsonl').read_text().splitlines()]
    development = [r for r in rows if r['split'] == 'development']
    selected = []
    for layout in ('overlay', 'separate'):
        ids = sorted({r['hull_id'] for r in development if r['layout'] == layout})[:3]
        selected.extend(r for r in development if r['layout'] == layout and r['hull_id'] in ids)
    selected.sort(key=lambda r: r['case_id'])
    assert len(selected) == 24
    assert Counter((r['layout'], r['level']) for r in selected) == {
        (layout, level): 3 for layout in ('overlay', 'separate') for level in range(4)}
    sample_path = OUT / 'sample.json'
    if sample_path.exists():
        assert json.loads(sample_path.read_text()) == selected
    else:
        write(sample_path, selected)
    hulls.sources_root = lambda: MAIN / 'work/sources'
    np.seterr(all='ignore')
    factory = OUT / 'factory'
    checks = sample.regenerate([r['case_id'] for r in selected], factory)
    assert all(r['drawing_sha256_matches_frozen'] for r in checks)
    for hull_id in sorted({r['hull_id'] for r in selected}):
        entry = generator._entry(hulls.load_cached(factory / 'hulls', hull_id), 'development', factory)
        assert entry['truth_sha256'] == sample.hull_record(hull_id)['truth_sha256']
    for row in selected:
        case = row['case_id']
        assert sha(factory / 'inputs' / case / 'spec.json') == row['spec_sha256']
        assert sha(factory / 'params' / f'{case}.json') == row['params_sha256']
    write(OUT / 'regeneration.json', checks)
    print('Prepared and hash-verified 24 development cases.', flush=True)


def sample_rows(round_only=False):
    rows = json.loads((OUT / 'sample.json').read_text())
    return [r for r in rows if r['hull_id'] == 'dtmb5415'] if round_only else rows


def run(arm, thinking, round_only=False):
    rows = sample_rows(round_only)
    runtime = OUT / f'{arm}-runtime'
    source = OUT / f'{arm}-source/src'
    binary = runtime / 'marinaframe'
    if arm == 'thinking':
        binary = OUT / 'after-runtime/marinaframe'
        source = OUT / 'after-source/src'
    assert binary.is_file() and source.is_dir()
    write(OUT / f'{arm}-identity.json', {'binary_sha256': sha(binary), 'worker_source': str(source),
                                      'jobs': 2, 'sample_sha256': sha(OUT / 'sample.json')})

    def one(row):
        case = row['case_id']
        directory = OUT / 'runs' / arm / case
        directory.mkdir(parents=True, exist_ok=False)
        command = [str(binary), 'run', '--task', str(directory / 'task'), '--source',
                   str(OUT / 'factory/inputs' / case / 'spec.json'), '--worker-python',
                   str(MAIN / '.venv/bin/python'), '--worker-source', str(source), '--policy', 'live',
                   '--on-ambiguity', 'draft', '--model-review', 'true', '--provider-transfer-basis',
                   'Founder authorized acquired drawings to DeepSeek for development/evaluation (2026-11-07); W17 development comparison.']
        if thinking:
            command.extend(['--investigation-thinking', 'enabled'])
        write(directory / 'command.json', command)
        start = time.time()
        with (directory / 'stdout.log').open('w') as stdout, (directory / 'stderr.log').open('w') as stderr:
            result = subprocess.run(command, stdout=stdout, stderr=stderr, check=False)
        write(directory / 'attempt.json', {'returncode': result.returncode, 'wall_seconds': time.time() - start})
        print(f'{arm} {case}: exit {result.returncode}', flush=True)

    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(one, rows))
    print(f'{arm}: all {len(rows)} attempts finished', flush=True)


def score(arm, round_only=False):
    from benchmarks.factory import truth, report

    rows = sample_rows(round_only)
    results = []
    for row in rows:
        directory = OUT / 'runs' / arm / row['case_id']
        stdout = directory / 'stdout.log'
        if not (directory / 'attempt.json').exists():
            raise RuntimeError(f"Attempt not finished: {row['case_id']}")
        try:
            status = json.loads(stdout.read_text().splitlines()[-1])
        except (ValueError, IndexError):
            status = {'status': 'driver_error', 'current_candidate': None}
        candidate = status.get('current_candidate')
        if not candidate or not candidate.get('valid'):
            candidate = status.get('last_valid_candidate')
        models = []
        if candidate and candidate.get('path'):
            run_dir = directory / 'task' / candidate['path']
            models = [p for p in (run_dir / 'model.step', run_dir / 'model-draft.step') if p.is_file()]
        correct = False
        scored = None
        if models:
            spec = json.loads((OUT / 'factory/inputs' / row['case_id'] / 'spec.json').read_text())
            stations = [{'id': s['id'], 'x_m': s['x_m']} for s in spec['sections']]
            try:
                scored = truth.score_model(OUT / 'factory/sealed/truth' / f"{row['hull_id']}.npz", models[0], stations)
                main = scored.get('summary', {}).get('half_breadth_main')
                volume = scored.get('hydrostatics_at_design_draft', {}).get('volume_error_relative_within_range')
                correct = bool(scored.get('status') == 'scored' and main and
                    main['rms_of_station_rms_m'] / scored['truth']['max_half_breadth_m'] <= report.RMS_GATE_FRACTION and
                    volume is not None and abs(volume) <= report.VOLUME_GATE)
            except Exception as error:
                scored = {'status': 'scoring_error', 'exception_type': type(error).__name__}
            write(directory / 'score.json', scored)
        receipts = []
        seen = set()
        for path in sorted((directory / 'task/receipts').glob('request-*.json')):
            receipt = json.loads(path.read_text())
            if receipt.get('protocol') == 'marinaframe.provider.v1' and receipt['request_id'] not in seen:
                receipts.append(receipt)
                seen.add(receipt['request_id'])
        cost = [r.get('usage', {}).get('list_cost') for r in receipts]
        results.append({'case_id': row['case_id'], 'layout': row['layout'], 'level': row['level'],
            'status': status['status'], 'built': bool(models), 'correct': correct,
            'silent_wrong_build': bool(models) and not correct and status['status'] == 'awaiting_human_review',
            'labelled_wrong_draft': bool(models) and not correct and status['status'] != 'awaiting_human_review',
            'score_status': scored.get('status') if scored else None,
            'requests': len(receipts), 'request_states': dict(Counter(r['state'] for r in receipts)),
            'list_cost_usd': sum(c for c in cost if c is not None),
            'requests_missing_list_cost': sum(c is None for c in cost),
            'prompt_tokens': sum(r.get('usage', {}).get('prompt_tokens', 0) for r in receipts),
            'completion_tokens': sum(r.get('usage', {}).get('completion_tokens', 0) for r in receipts)})
    counts = Counter(r['status'] for r in results)
    summary = {'arm': arm, 'planned_cases': len(rows), 'status_counts': dict(counts),
        'no_progress_rate': counts['no_progress'] / len(rows),
        **{key: sum(r[key] for r in results) for key in ('built', 'correct', 'silent_wrong_build',
            'labelled_wrong_draft', 'requests', 'list_cost_usd', 'requests_missing_list_cost', 'prompt_tokens', 'completion_tokens')},
        'sample_sha256': sha(OUT / 'sample.json'),
        'gate': {'rms_fraction': report.RMS_GATE_FRACTION, 'volume_relative': report.VOLUME_GATE}}
    write(ROOT / 'outputs/w17' / f'{arm}.json', {'summary': summary, 'cases': results})
    print(json.dumps(summary, indent=2), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['prepare', 'run', 'score'])
    parser.add_argument('--arm', default='baseline')
    parser.add_argument('--round', action='store_true', help='Run only DTMB L0-L3.')
    args = parser.parse_args()
    if args.action == 'prepare':
        prepare()
    elif args.action == 'score':
        score(args.arm, args.round)
    else:
        run(args.arm, args.arm == 'thinking', args.round)


if __name__ == '__main__':
    main()
