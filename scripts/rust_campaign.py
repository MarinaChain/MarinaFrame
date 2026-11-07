#!/usr/bin/env python3
"""Run frozen Rust development/evaluation attempts; never score hidden truth.

The manifest contains only case IDs, source-spec paths, cohort labels and
provider-transfer authorization. A separate evaluator scores terminal outputs.
Credentials are inherited from OPENCODE_API_KEY, not accepted as CLI values.
No aggregate research usage cap is installed by this runner.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.pending')
    with temporary.open('x') as stream:
        stream.write(json.dumps(value, indent=2, allow_nan=False) + '\n')
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binary', type=Path, required=True)
    parser.add_argument('--worker-python', type=Path, required=True)
    parser.add_argument('--worker-source', type=Path)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--policy', choices=['deterministic', 'live'], required=True)
    parser.add_argument('--repeats', type=int, default=1)
    args = parser.parse_args()
    if not 1 <= args.repeats <= 100:
        parser.error('repeats must be an explicit experiment size between 1 and 100')
    binary = args.binary.resolve(strict=True)
    python = args.worker_python.absolute()
    manifest = json.loads(args.manifest.read_text())
    if set(manifest) != {'schema_version', 'cohort', 'cases'} or manifest['schema_version'] != 'marinaframe.campaign.v1':
        raise SystemExit('Invalid campaign manifest')
    if not isinstance(manifest['cases'], list) or not 1 <= len(manifest['cases']) <= 100:
        raise SystemExit('Invalid campaign case inventory')
    args.out.mkdir(parents=True, exist_ok=False)
    original_binary_hash = digest(binary)
    worker_files = {p.relative_to(args.worker_source).as_posix(): digest(p)
                    for p in sorted(args.worker_source.rglob('*.py'))} if args.worker_source else {}
    write(args.out / 'frozen-configuration.json', {
        'schema_version': 'marinaframe.campaign.run.v1', 'manifest_sha256': digest(args.manifest),
        'binary_sha256': original_binary_hash, 'worker_files': worker_files,
        'policy': args.policy, 'repeats': args.repeats, 'cohort': manifest['cohort'],
        'live_inference': args.policy == 'live', 'reference_scoring_performed': False,
        'aggregate_request_cap': None, 'aggregate_token_cap': None, 'aggregate_spend_cap': None,
        'engineering_approved': False,
    })
    records = []
    for case in manifest['cases']:
        if set(case) != {'id', 'source_spec', 'provider_transfer_authorized', 'authorization_basis'}:
            raise SystemExit('Invalid campaign case fields')
        if not isinstance(case['id'], str) or not case['id'].replace('-', '').replace('_', '').isalnum():
            raise SystemExit('Unsafe case ID')
        source = (args.manifest.parent / case['source_spec']).resolve(strict=True)
        for repeat in range(1, args.repeats + 1):
            if digest(binary) != original_binary_hash:
                raise SystemExit('Frozen controller binary changed')
            identity = f'{case["id"]}-trial-{repeat:02d}'
            task = args.out / identity
            command = [str(binary), 'run', '--task', str(task.absolute()), '--source', str(source),
                       '--worker-python', str(python), '--policy', args.policy]
            if args.worker_source:
                command += ['--worker-source', str(args.worker_source.absolute())]
            if args.policy == 'live':
                if case['provider_transfer_authorized'] is not True or not case['authorization_basis']:
                    raise SystemExit('This case is not authorized for provider transfer')
                command += ['--provider-transfer-basis', case['authorization_basis']]
            started = time.monotonic()
            with (args.out / (identity + '.stdout')).open('x') as out, (args.out / (identity + '.stderr')).open('x') as err:
                outcome = subprocess.run(command, stdout=out, stderr=err, check=False)
            seconds = time.monotonic() - started
            state_path = task / 'state.json'
            checkpoint = json.loads(state_path.read_text()) if state_path.exists() else {}
            state = checkpoint.get('state', {})
            verification = subprocess.run([str(binary), 'verify', '--task', str(task)], capture_output=True, text=True)
            try:
                verified = json.loads(verification.stdout or verification.stderr)
            except json.JSONDecodeError:
                verified = {'valid': False, 'error_code': 'verification_output_missing'}
            record = {'id': identity, 'case_id': case['id'], 'repeat': repeat, 'policy': args.policy,
                      'exit_code': outcome.returncode, 'wall_seconds': seconds, 'source_spec_sha256': digest(source),
                      'status': state.get('status'), 'termination_reason': state.get('termination_reason'),
                      'counters': state.get('counters', {}), 'verification': verified,
                      'generation_id': state.get('generation_id'), 'revision_id': state.get('revision_id'),
                      'candidate_exported': state.get('domain', {}).get('current_candidate', {}).get('valid') is True
                      if isinstance(state.get('domain', {}).get('current_candidate'), dict) else False,
                      'engineering_approved': False, 'reference_scoring_performed': False}
            records.append(record)
            write(args.out / 'attempts.json', records)
            print(json.dumps(record), flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
