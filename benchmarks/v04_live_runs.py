"""Reference-blind live execution from a sealed input and transfer-rights index.

Reads no reference geometry, expected-outcome labels or other arms' results.
The key is inherited, never accepted in an argument or written into evidence.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time


def sha(path):
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
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--runtime', type=Path, required=True)
    p.add_argument('--worker-python', type=Path, required=True)
    p.add_argument('--index', type=Path, required=True)
    p.add_argument('--authorization', type=Path, required=True)
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--jobs', type=int, default=2, choices=[1, 2])
    a = p.parse_args()
    if not os.environ.get('OPENCODE_API_KEY'):
        raise SystemExit('Configured provider credential required; no request sent')
    runtime = a.runtime.resolve(strict=True)
    frozen = json.loads((runtime/'freeze.json').read_text())
    for name, expected in frozen['files'].items():
        if sha(runtime/name) != expected:
            raise SystemExit('Frozen runtime changed')
    index = json.loads(a.index.read_text())
    rights = json.loads(a.authorization.read_text())
    if rights['implementation_index_sha256'] != sha(a.index):
        raise SystemExit('Transfer mapping is not bound to this input index')
    cases = index['cases']; authorized = {c['case_id']:c for c in rights['cases']}
    if len(authorized) != len(cases) or {c['case_id'] for c in cases} != set(authorized):
        raise SystemExit('Transfer mapping case inventory differs')
    source_root = Path(index['input_root']).resolve(strict=True)
    for case in cases:
        r = authorized[case['case_id']]
        if (case['input'],case['drawing']) != (r['input'],r['drawing']):
            raise SystemExit('Input mapping changed')
        for name, digest_key, bytes_key in [('input','spec_sha256','spec_bytes'),('drawing','source_sha256','source_bytes')]:
            f = (source_root/case[name]).resolve(strict=True)
            if not f.is_relative_to(source_root) or sha(f) != r[digest_key] or f.stat().st_size != r[bytes_key]:
                raise SystemExit('Sealed authorized input changed')
    a.out.mkdir(parents=True,exist_ok=False)
    write(a.out/'execution-protocol.json',{'schema_version':'marinaframe.live-evaluation-execution.v1',
        'started_utc':datetime.now(timezone.utc).isoformat(),'runtime_freeze_sha256':sha(runtime/'freeze.json'),
        'source_commit':frozen['source_commit'],'binary_sha256':sha(runtime/'marinaframe'),
        'input_index_sha256':sha(a.index),'authorization_sha256':sha(a.authorization),
        'input_tree_sha256':index['input_tree_sha256'],'cases':[c['case_id'] for c in cases],
        'script_sha256':sha(__file__),'concurrent_tasks':a.jobs,'native_concurrency':1,
        'aggregate_request_cap':None,'aggregate_token_cap':None,'aggregate_spend_cap':None,
        'whole_task_timeout':None,'per_request_and_worker_limits':'Captured runtime defaults',
        'capture_before_transfer':True,'reference_scoring_performed':False,'engineering_approved':False})
    binary = str(runtime/'marinaframe'); python = str(a.worker_python.absolute())
    env = dict(os.environ); env.pop('PYTHONPATH',None)

    def execute(case):
        identity = case['case_id']; r = authorized[identity]
        out = a.out/identity; out.mkdir(); task = out/'task'; commands=[]
        started = time.monotonic()

        def command(stage, argv):
            begin = time.monotonic()
            with (out/(stage+'.stdout')).open('x') as stdout,(out/(stage+'.stderr')).open('x') as stderr:
                result = subprocess.run(argv,env=env,stdout=stdout,stderr=stderr,check=False)
            commands.append({'stage':stage,'command':argv,'exit_code':result.returncode,'wall_seconds':time.monotonic()-begin})
            write(out/'commands.json',commands)
            return result.returncode

        write(out/'attempt-intent.json',{'case_id':identity,'started_utc':datetime.now(timezone.utc).isoformat(),
            'source_sha256':r['source_sha256'],'spec_sha256':r['spec_sha256'],'reference_scoring_performed':False})
        command('capture',[binary,'run','--task',str(task.absolute()),'--source',str(source_root/case['input']),
            '--worker-python',python,'--worker-source',str(runtime/'src'),'--policy','live','--steps','0',
            '--provider-transfer-basis',r['provider_transfer_basis']])
        checkpoint=json.loads((task/'state.json').read_text());state=checkpoint['state']
        if state['status']=='paused':
            domain=json.loads((task/'domain/state.json').read_text())
            submitted=json.loads((task/'domain/input/submitted_spec.json').read_text())
            if set(domain['sources'])!={'source'} or domain['sources']['source']['sha256']!=r['source_sha256']:
                raise RuntimeError('Captured source is outside the authorized transfer inventory')
            if submitted!=json.loads((source_root/case['input']).read_text()):
                raise RuntimeError('Captured substantive specification changed')
            if sha(task/'domain/input'/domain['sources']['source']['file'])!=r['source_sha256']:
                raise RuntimeError('Captured source bytes changed')
            write(out/'captured-transfer-binding.json',{'case_id':identity,'source_manifest_sha256':state['source_manifest_sha256'],
                'source_sha256':r['source_sha256'],'submitted_spec_structure_matches':True,
                'authorization_sha256':sha(a.authorization),'bound_before_first_provider_request':True})
            command('live',[binary,'resume','--task',str(task.absolute())])
        command('verify',[binary,'verify','--task',str(task.absolute())])
        state=json.loads((task/'state.json').read_text())['state']
        try:verified=json.loads((out/'verify.stdout').read_text() or (out/'verify.stderr').read_text())
        except json.JSONDecodeError:verified={'valid':False,'error_code':'verification_output_missing'}
        record={'case_id':identity,'status':state['status'],'termination_reason':state['termination_reason'],
            'counters':state['counters'],'wall_seconds':time.monotonic()-started,'commands':commands,
            'generation_id':state['generation_id'],'revision_id':state['revision_id'],'verification':verified,
            'pending':state['pending'],'source_manifest_sha256':state['source_manifest_sha256'],
            'engineering_approved':False,'reference_scoring_performed':False}
        write(out/'attempt.json',record)
        return record

    outcomes=[]
    with ThreadPoolExecutor(max_workers=a.jobs) as pool:
        futures={pool.submit(execute,case):case['case_id'] for case in cases}
        for future in as_completed(futures):
            identity=futures[future]
            try:record=future.result()
            except Exception as exc:
                record={'case_id':identity,'runner_error_type':type(exc).__name__,
                    'status':'runner_failed','evidence_preserved':True,'reference_scoring_performed':False}
            outcomes.append(record);write(a.out/'attempts.json',outcomes)
            print(json.dumps({k:record.get(k) for k in ['case_id','status','counters','wall_seconds','runner_error_type']}),flush=True)
    files={f.relative_to(a.out).as_posix():sha(f) for f in sorted(a.out.rglob('*')) if f.is_file()}
    write(a.out/'output-lock.json',{'schema_version':'marinaframe.live-output-lock.v1',
        'locked_utc':datetime.now(timezone.utc).isoformat(),'attempts':len(outcomes),'file_sha256':files,
        'all_attempts_retained':True,'reference_scoring_performed':False})
    return 1 if any(r['status']=='runner_failed' for r in outcomes) else 0


if __name__=='__main__':
    raise SystemExit(main())
