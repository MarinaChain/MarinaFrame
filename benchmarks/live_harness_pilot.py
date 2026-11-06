"""Small explicitly authorized, included-allowance-only live harness experiment.

No evaluator labels enter the task. This experiment reports its actual result;
calling it is not a guarantee of model success. Credentials are process memory
or OPENCODE_API_KEY and never serialized. No automatic provider retries.
"""
from __future__ import annotations
import argparse
from dataclasses import asdict
import json
from pathlib import Path
import threading
import time

from vessel_reconstruction.agent_harness import FINISH, Harness, HarnessLimits, TaskStore, _artifact_bytes, verify_task
from vessel_reconstruction.agent_tools import DomainTools
from vessel_reconstruction.agent_provider import OpenCodeGoAgentProvider, export_replay_transcript, verify_replay_transcript
from vessel_reconstruction.provenance import write_json


def run_pilot(spec, out, *, api_key=None, credential_source='configured_environment',prior_generation_reservations=0):
    out=Path(out);cancel=threading.Event();started=time.monotonic()
    provider=OpenCodeGoAgentProvider(api_key=api_key,credential_source=credential_source,
        authorized_external_data=True,admission_mode='fresh_observed_included_allowance',
        max_requests=6,max_output_tokens=1024,max_total_output_tokens=6144,cancel=cancel,
        max_session_seconds=240,prior_generation_reservations=prior_generation_reservations)
    with TaskStore(out,create=True) as store:
        domain=DomainTools(store.path,Path(spec),cancel_event=cancel)
        limits=HarnessLimits(max_actions=6,max_policy_calls=6,max_builds=1,
            wall_seconds=240,observation_bytes=21_000,max_images_per_call=2,max_image_bytes=131072)
        state=Harness(store,domain,provider,limits=limits,cancel_event=cancel,
            authorize_data_sha256=domain.describe()['source_manifest_sha256']).run()
        events=list(store.events)
        artifacts={}
        def visit(v):
            if isinstance(v,dict):
                if {'id','path','sha256','mime_type'}<=set(v):artifacts[v['id']]=v
                for x in v.values():visit(x)
            elif isinstance(v,list):
                for x in v:visit(x)
        for e in events:visit(e['payload'])
        transcript=export_replay_transcript(events,domain.catalog()+[FINISH],
            image_loader=lambda meta:_artifact_bytes(store.path,artifacts[meta['artifact_id']],131072))
        write_json(out/'replay-transcript.json',transcript)
        replay=verify_replay_transcript(transcript)
        receipts=[e['payload']['receipt'] for e in events if e['kind']=='decision']
        known_costs=[r['observed_cost_usd'] for r in receipts if r.get('observed_cost_usd') is not None]
        summary={'experiment':'six_call_live_harness_pilot','policy':'live','model':'deepseek-v4.1-flash',
            'status':state['status'],'termination_reason':state.get('termination_reason'),
            'source_manifest_sha256':state['source_manifest_sha256'],'limits':asdict(limits),
            'generation_requests':provider.calls,'decisions':len(receipts),
            'actions':[e['payload']['decision']['tool'] for e in events if e['kind']=='decision'],
            'operator_actions':state['operator_actions'],
            'observed_cost_usd':sum(known_costs) if len(known_costs)==len(receipts) else None,
            'cost_observations':len(known_costs),'prior_generation_reservations':prior_generation_reservations,
            'billing_sources':sorted({r.get('usage',{}).get('billing_source','unknown') for r in receipts}),
            'prompt_tokens':sum(r.get('usage',{}).get('prompt_tokens',0) for r in receipts),
            'completion_tokens':sum(r.get('usage',{}).get('completion_tokens',0) for r in receipts),
            'image_decisions':sum(r.get('input_mode')=='vision' for r in receipts),
            'elapsed_seconds':time.monotonic()-started,'replay':replay,
            'engineering_approved':False,'generalization_claim':False,
            'admission_limitation':'Fresh observed included allowance; not a hard provider zero-dollar cap. Concurrent account consumption cannot be reserved.'}
        write_json(out/'provider-preflight-receipts.json',provider.preflight_receipts)
    summary['task_verification']=verify_task(out)
    write_json(out/'experiment-summary.json',summary)
    return summary


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('spec',type=Path);p.add_argument('--out',type=Path,required=True)
    p.add_argument('--authorize-included-pilot',action='store_true',required=True)
    a=p.parse_args();print(json.dumps(run_pilot(a.spec,a.out),indent=2))
