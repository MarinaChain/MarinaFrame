#!/usr/bin/env python3
"""Explicitly seed a prior source interpretation, then hand control to live policy.

This is an assisted development experiment, not an unassisted reconstruction.
The initial choice is a retained row-centroid interpretation or an explicitly
labelled controlled grid-line mistake. No reference shape, numerical accuracy
score or correct-answer candidate ID is read here or sent to the model.
The Rust event log records every setup operation as assistant_operator.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import time


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--binary', type=Path, required=True)
    p.add_argument('--worker-python', type=Path, required=True)
    p.add_argument('--worker-source', type=Path, required=True)
    p.add_argument('--source', type=Path, required=True)
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--initial-rule', choices=['row-centroid', 'controlled-grid'], default='row-centroid')
    p.add_argument('--pre-render-prior', action='store_true',
                   help='Record two additional operator render actions so the first live request can inspect the existing STEP.')
    a = p.parse_args()
    a.out.mkdir(parents=True, exist_ok=False)
    task = a.out / 'task'
    command_log = []

    def run(name, arguments):
        start = time.monotonic()
        with (a.out / f'{name}.stdout').open('x') as stdout, (a.out / f'{name}.stderr').open('x') as stderr:
            r = subprocess.run([str(a.binary.absolute()), *arguments], stdout=stdout, stderr=stderr)
        command_log.append({'stage': name, 'exit_code': r.returncode, 'wall_seconds': time.monotonic()-start})
        (a.out / 'commands.json').write_text(json.dumps(command_log, indent=2)+'\n')
        if r.returncode:
            raise SystemExit(f'{name} failed; evidence retained')

    run('initialize', ['run', '--task', str(task.absolute()), '--source', str(a.source.absolute()),
        '--worker-python', str(a.worker_python.absolute()), '--worker-source', str(a.worker_source.absolute()),
        '--policy', 'live', '--steps', '0', '--provider-transfer-basis',
        'User-authorized MarinaFrame campaign; original project-generated CC0 development drawing; no restricted source material.'])

    def step(name, tool, arguments):
        checkpoint = json.loads((task/'state.json').read_text())
        state = checkpoint['state']
        value = {'schema_version':'marinaframe.intervention.v1', 'task_id':state['task_id'],
            'expected_head_sha256':checkpoint['head_sha256'], 'expected_generation_id':state['generation_id'],
            'expected_revision_id':state['revision_id'], 'decision':{'tool':tool, 'arguments':arguments,
                'reason':'Explicit prior source interpretation for an assisted development experiment; semantic identity is unresolved.'}}
        path=a.out/f'{name}-intervention.json';path.write_text(json.dumps(value,indent=2)+'\n')
        run(name,['step','--task',str(task.absolute()),'--intervention',str(path.absolute()),
            '--actor','assistant_operator','--note','Deterministic prior-candidate seed; all subsequent reconstruction decisions are delegated to the live model.'])

    step('inspect','inspect_source',{})
    domain=json.loads((task/'domain/state.json').read_text())
    selections=[]
    for sid,entry in domain['catalog'].items():
        ids={c['candidate_id'] for c in entry['candidates'] if c['selectable']}
        if a.initial_rule == 'controlled-grid':
            vertical = [c for c in entry['candidates'] if c['selectable']
                        and c.get('grid_supported_hypothesis') is False
                        and c.get('source_support', {}).get('maximum_step_px_per_row') == 0
                        and c.get('non_grid_competing_components', 0) > 0]
            vertical.sort(key=lambda c: c['contour_selection']['anchors_px'][0][0])
            if not vertical:
                raise SystemExit('No measured vertical grid alternative available for this controlled fault')
            chosen = vertical[len(vertical)//2]['candidate_id']
            selections.append({'section_id':sid,'candidate_id':chosen})
            continue
        prior=[c['endpoint_evidence']['centroid_alternative_id'] for c in entry['candidates']
               if c.get('endpoint_evidence',{}).get('centroid_alternative_id') in ids]
        if len(set(prior))==1:
            chosen=prior[0]
        else:
            chosen=entry.get('grid_evidence',{}).get('unique_non_grid_candidate_id')
            if chosen is None and len(ids)==1:chosen=next(iter(ids))
        if not chosen:
            raise SystemExit('No unique prior interpretation available; no arbitrary fallback')
        selections.append({'section_id':sid,'candidate_id':chosen})
    if len(selections)!=len(json.loads(a.source.read_text())['sections']):
        raise SystemExit('This small assisted experiment requires all sections in one bounded inspection')
    step('prior-selection','select_contours',{'selections':selections})
    step('prior-build','build_provisional',{})
    if a.pre_render_prior:
        step('prior-body','render_candidate',{'view':'body'})
        step('prior-oblique','render_candidate',{'view':'oblique'})
    (a.out/'initial-domain.json').write_text((task/'domain/state.json').read_text())
    run('live-continuation',['resume','--task',str(task.absolute())])
    run('verify',['verify','--task',str(task.absolute())])
    final=json.loads((task/'state.json').read_text())['state']
    summary={'status':final['status'],'counters':final['counters'],'revision_id':final['revision_id'],
        'assisted_initial_candidate':True,'initial_setup_operator_actions':5 if a.pre_render_prior else 3,
        'prior_step_views_prepared':a.pre_render_prior,'reference_truth_used_in_inference':False,
        'initial_rule':a.initial_rule,'controlled_fault':a.initial_rule == 'controlled-grid',
        'engineering_approved':False}
    (a.out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n');print(json.dumps(summary))


if __name__=='__main__':
    main()
