"""Resume the one-shot v2 campaign after the driver process was stopped from outside.

Rules (docs/plans/2026-11-08-h2h-sealed-v2.md):
- Finished case results are kept. They are never rerun.
- A case that was in progress when the driver stopped is a counted failure
  (`interrupted_by_harness_stop`). It is never retried.
- Only cases that never started are run, with the same frozen snapshot, inputs and
  controller settings as the original driver (run_h2h_sealed_v2.run_case).
- One correction before the LLM arm starts: the pre-registered LLM-first arm includes
  the W12 veto review. The original driver did not pass `--model-review true`, so it
  is added here for the LLM arm only. No LLM case had run when this was added.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import run_h2h_sealed_v2 as base  # noqa: E402

INTERRUPTED = 'interrupted_by_harness_stop'
# base.subprocess is this same module object, so keep the original function.
_ORIGINAL_RUN = subprocess.run


def run_with_review(command: list[str], *args, **kwargs):
    if '--policy' in command and command[command.index('--policy') + 1] == 'live':
        command = [*command, '--model-review', 'true']
    return _ORIGINAL_RUN(command, *args, **kwargs)


def record_interrupted(arm: str, active: Path, cases: dict) -> dict:
    case = cases[active.name]
    row = {k: case[k] for k in ('case_id', 'layout', 'level', 'hull_id', 'family', 'split')}
    row.update(arm=arm, controller_status=INTERRUPTED, termination_reason=INTERRUPTED,
               exit_code=None, built=False, outcome='failed', failure_kind=INTERRUPTED,
               guesses=0, lines=0, counters={}, list_cost_usd=0.0, list_cost_receipts=0, seconds=None)
    base.write_json(active / 'result.json', row)
    destination = base.OUTPUT / 'runs' / arm / active.name
    assert not destination.exists()
    shutil.move(str(active), destination)
    return row


def main() -> None:
    campaign_path = base.OUTPUT / 'campaign.json'
    campaign = json.loads(campaign_path.read_text())
    assert 'finished' not in campaign, 'Campaign already finished'
    cases = [json.loads(line) for line in
             (base.SNAPSHOT / 'benchmarks/factory/manifests/sealed-v2/cases.jsonl').read_text().splitlines()]
    by_id = {case['case_id']: case for case in cases}
    freeze = json.loads((base.OUTPUT / 'freeze.json').read_text())
    for relative, expected in freeze['files_sha256'].items():
        assert hashlib.sha256((base.SNAPSHOT / relative).read_bytes()).hexdigest() == expected, relative
    for case in cases:
        for kind, name in [('drawing', 'drawing.png'), ('spec', 'spec.json')]:
            digest = hashlib.sha256((base.INPUTS / case['case_id'] / name).read_bytes()).hexdigest()
            assert digest == case[kind + '_sha256'], case['case_id']

    interrupted = []
    if base.ACTIVE.exists():
        for arm_dir in sorted(base.ACTIVE.iterdir()):
            for active in sorted(arm_dir.iterdir()):
                interrupted.append(record_interrupted(arm_dir.name, active, by_id)['case_id'])
        shutil.rmtree(base.ACTIVE)
    campaign.setdefault('resumes', []).append({
        'resumed': time.strftime('%Y-%m-%dT%H:%M:%S%z'),
        'reason': 'Driver process stopped when its router session ended; not a case result.',
        'interrupted_cases_counted_as_failed': interrupted,
        'resume_driver_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'llm_model_review': True,
        'model_review_note': 'Pre-registered LLM-first arm includes W12 veto review; added before any LLM case ran.'})
    campaign['model_review'] = 'llm arm only (see resumes)'
    base.write_json(campaign_path, campaign)

    subprocess.run = run_with_review
    for arm in campaign['arms']:
        if (base.OUTPUT / f'{arm}-finished.json').exists():
            continue
        done = {p.name for p in (base.OUTPUT / 'runs' / arm).iterdir()} if (base.OUTPUT / 'runs' / arm).exists() else set()
        remaining = [case for case in cases if case['case_id'] not in done]
        started = time.perf_counter()
        if not done:
            first = base.run_case(arm, remaining[0])
            if first['controller_status'] == 'cli_error' or not (
                    base.OUTPUT / 'runs' / arm / remaining[0]['case_id'] / 'task/domain/state.json').exists():
                raise RuntimeError(f'{arm}: harness startup failure; preserve result and stop')
            remaining = remaining[1:]
        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(lambda case: base.run_case(arm, case), remaining))
        count = len(list((base.OUTPUT / 'runs' / arm).iterdir()))
        assert count == len(cases), f'{arm}: {count} results'
        base.write_json(base.OUTPUT / f'{arm}-finished.json',
                        {'cases': count, 'wall_seconds_this_session': time.perf_counter() - started,
                         'finished': time.strftime('%Y-%m-%dT%H:%M:%S%z')})
    campaign = json.loads(campaign_path.read_text())
    campaign['finished'] = time.strftime('%Y-%m-%dT%H:%M:%S%z')
    base.write_json(campaign_path, campaign)


if __name__ == '__main__':
    main()
