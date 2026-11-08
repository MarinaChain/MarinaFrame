"""One-shot frozen v2 inference. Never opens evaluator truth or scores cases."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

MAIN = Path('/Users/jonathanjie/Documents/workspace/MarinaFrame')
OUTPUT = MAIN / 'work/h2h-sealed-v2'
SNAPSHOT = OUTPUT / 'snapshot'
ACTIVE = Path('/tmp/marinaframe-h2h-sealed-v2')
PYTHON = MAIN / '.venv/bin/python'
INPUTS = MAIN / 'work/factory-sealed-v2/inputs'
BASIS = 'User authorized the pre-registered sealed v2 DeepSeek head-to-head, 2026-11-08; evaluation only.'


def write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, indent=2) + '\n')


def run_case(arm: str, case: dict) -> dict:
    case_id = case['case_id']
    active = ACTIVE / arm / case_id
    active.mkdir(parents=True, exist_ok=False)
    task = active / 'task'
    command = [str(SNAPSHOT / 'marinaframe'), 'run', '--task', str(task),
               '--source', str(INPUTS / case_id / 'spec.json'),
               '--worker-python', str(PYTHON), '--worker-source', str(SNAPSHOT / 'src'),
               '--policy', 'live' if arm == 'llm' else 'deterministic',
               '--on-ambiguity', 'abstain' if arm == 'abstain' else 'draft']
    if arm == 'llm':
        command += ['--provider-transfer-basis', BASIS]
    write_json(active / 'command.json', {'command': command})
    started = time.perf_counter()
    with (active / 'stdout.json').open('w') as stdout, (active / 'stderr.txt').open('w') as stderr:
        completed = subprocess.run(command, stdout=stdout, stderr=stderr, cwd=SNAPSHOT)
    wall = time.perf_counter() - started
    try:
        status = json.loads((active / 'stdout.json').read_text())
    except ValueError:
        status = {}
    state_file = task / 'domain/state.json'
    state = json.loads(state_file.read_text()) if state_file.exists() else {}
    guesses = state.get('guesses') or []
    lines = set((state.get('selected') or {}).keys())
    lines.update(g['section_id'] for g in guesses if g.get('chosen_candidate_id'))
    candidate = status.get('current_candidate') or {}
    candidate_dir = task / candidate['path'] if candidate.get('path') else None
    model = next((candidate_dir / name for name in ('model.step', 'model-draft.step')
                  if (candidate_dir / name).exists()), None) if candidate_dir else None
    built = bool(candidate.get('valid') and model)
    if built:
        shutil.copy2(model, active / 'model.step')
    counters = status.get('counters') or {}
    list_cost = 0.0
    cost_receipts = 0
    for receipt_path in (task / 'receipts').glob('*.json'):
        receipt = json.loads(receipt_path.read_text())
        usage = receipt.get('usage') or {}
        value = usage.get('list_cost')
        if isinstance(value, (float, int)):
            list_cost += value
            cost_receipts += 1
    row = {k: case[k] for k in ('case_id', 'layout', 'level', 'hull_id', 'family', 'split')}
    row.update(arm=arm, controller_status=status.get('status', 'cli_error'),
               termination_reason=status.get('termination_reason'), exit_code=completed.returncode,
               built=built, outcome='built' if built else ('abstained' if status.get('status') == 'abstained' else 'failed'),
               failure_kind=None if built or status.get('status') == 'abstained' else status.get('termination_reason', 'cli_error'),
               guesses=len(guesses), lines=len(lines), counters=counters, list_cost_usd=list_cost,
               list_cost_receipts=cost_receipts, seconds=wall)
    write_json(active / 'result.json', row)
    destination = OUTPUT / 'runs' / arm / case_id
    destination.parent.mkdir(parents=True, exist_ok=True)
    assert not destination.exists()
    shutil.move(str(active), destination)
    print(json.dumps({'arm': arm, 'case': case_id, 'status': row['controller_status'], 'built': built, 'seconds': round(wall, 1)}), flush=True)
    return row


def main() -> None:
    assert not ACTIVE.exists(), 'Existing active campaign: do not restart or replace results'
    assert not (OUTPUT / 'campaign.json').exists(), 'Campaign already attempted'
    assert not (OUTPUT / 'runs').exists(), 'Results already exist'
    cases = [json.loads(line) for line in (SNAPSHOT / 'benchmarks/factory/manifests/sealed-v2/cases.jsonl').read_text().splitlines()]
    assert len(cases) == 288
    freeze = json.loads((OUTPUT / 'freeze.json').read_text())
    for relative, expected in freeze['files_sha256'].items():
        assert hashlib.sha256((SNAPSHOT / relative).read_bytes()).hexdigest() == expected, relative
    for case in cases:
        for kind, name in [('drawing', 'drawing.png'), ('spec', 'spec.json')]:
            assert hashlib.sha256((INPUTS / case['case_id'] / name).read_bytes()).hexdigest() == case[kind + '_sha256']
    campaign = {'started': time.strftime('%Y-%m-%dT%H:%M:%S%z'), 'jobs': 2,
                'driver_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                'arms': ['abstain', 'draft', 'llm'], 'cases_per_arm': 288,
                'controller_limits': 'Frozen OperationalLimits::default(); W11 CLI without overrides',
                'case_timeout': None, 'retry': False, 'model_review': False,
                'native_lock': f'/tmp/marinaframe-native-admission-{os.geteuid()}.lock'}
    write_json(OUTPUT / 'campaign.json', campaign)
    for arm in campaign['arms']:
        started = time.perf_counter()
        # Complete the first real case before admitting the rest. A whole-arm
        # startup failure must stop the campaign, not become 288 duplicate errors.
        first = run_case(arm, cases[0])
        if first['controller_status'] == 'cli_error' or not (OUTPUT / 'runs' / arm / cases[0]['case_id'] / 'task/domain/state.json').exists():
            raise RuntimeError(f'{arm}: harness startup failure; preserve result and stop')
        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(lambda case: run_case(arm, case), cases[1:]))
        write_json(OUTPUT / f'{arm}-finished.json', {'cases': len(cases), 'wall_seconds': time.perf_counter() - started,
                                                   'finished': time.strftime('%Y-%m-%dT%H:%M:%S%z')})
    campaign['finished'] = time.strftime('%Y-%m-%dT%H:%M:%S%z')
    write_json(OUTPUT / 'campaign.json', campaign)


if __name__ == '__main__':
    main()
