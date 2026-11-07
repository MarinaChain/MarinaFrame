"""W11 live rerun with semantic, not call-count, no-progress supervision."""
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import signal
import subprocess
import time

from vessel_reconstruction.llm_setup import write_json

ROOT = Path(__file__).resolve().parents[2]


def one(case):
    out = ROOT / 'work/w14/w11' / case / 'llm'
    if (out / 'arm_record.json').exists() or (out / 'supervisor_stop.json').exists():
        return
    out.mkdir(parents=True, exist_ok=True)
    task = out / 'task'
    # Interrupted tasks remain evidence; never resume one with an unknown call.
    if (task / 'task.json').exists() or (task / 'events').exists():
        write_json(out / 'supervisor_stop.json', {'reason': 'semantic_no_progress_manual_stop',
            'detail': 'Repeated label reads and enumeration without assignment progress; original attempt retained.'})
        return
    command = [str(ROOT/'work/w14/marinaframe-normalized'), 'run', '--task', str(task),
               '--source', str(out.parent/'input/spec.json'), '--worker-python',
               '/Users/jonathanjie/Documents/workspace/MarinaFrame/.venv/bin/python',
               '--worker-source', str(ROOT/'work/w14/frozen-worker'), '--policy', 'live',
               '--on-ambiguity', 'draft', '--provider-transfer-basis', 'Authorized W14 development W11 live rerun']
    started = time.monotonic()
    best = None
    last_progress = started
    with (out/'controller_stdout.json').open('w') as stdout, (out/'controller_stderr.txt').open('w') as stderr:
        process = subprocess.Popen(command, stdout=stdout, stderr=stderr, start_new_session=True)
        stop = None
        while process.poll() is None:
            state = task/'domain/state.json'
            if state.exists():
                try:
                    data = json.loads(state.read_text())
                    signature = (tuple(sorted(data.get('selected', {}).items())),
                                 tuple(sorted((g.get('section_id',''),g.get('candidate_id','')) for g in data.get('guesses',[]))),
                                 (data.get('candidate') or {}).get('generation_id'))
                    if signature != best:
                        best = signature
                        last_progress = time.monotonic()
                except (ValueError, OSError):
                    pass  # Atomic writer may not yet have published the state.
            # 90 s permits the native provider timeout. 180 s permits two such
            # intervals without any assignment/build progress; views alone do
            # not reset this timer. This is not a total task or request cap.
            if time.monotonic()-last_progress > 180:
                stop = 'semantic_no_progress_180_seconds'
                os.killpg(process.pid, signal.SIGTERM)
                process.wait(timeout=20)
                break
            time.sleep(1)
    record = {'arm':'llm','exit':process.returncode,'wall_seconds':round(time.monotonic()-started,1),
              'supervisor_stop':stop,'engineering_approved':False}
    write_json(out/'arm_record.json',record)
    if stop:
        write_json(out/'supervisor_stop.json',record)
    print(case,record,flush=True)


def main():
    cases=json.loads((ROOT/'outputs/w14/w11_cases.json').read_text())
    with ThreadPoolExecutor(max_workers=3) as pool:
        list(pool.map(one,cases))


if __name__=='__main__':
    main()
