"""Explicit command boundary for the persistent CAD harness."""
from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path
import signal
import threading

from .agent_harness import DeterministicPolicy, Harness, HarnessError, HarnessLimits, ScriptedPolicy, TaskStore, verify_task
from .agent_tools import DomainTools
from .schema import load_bounded_json


def _policy(args, cancel, state=None):
    if args.policy == 'deterministic':
        return DeterministicPolicy()
    if args.policy == 'scripted':
        if not args.script:
            raise HarnessError('Scripted mock mode requires --script')
        decisions=load_bounded_json(args.script,max_bytes=128_000,max_nodes=20_000)
        if not isinstance(decisions,list) or not 1<=len(decisions)<=64:
            raise HarnessError('Scripted mock input must contain1..64 decisions')
        return ScriptedPolicy(decisions)
    from .agent_provider import OpenCodeGoAgentProvider
    state=state or {}
    used=state.get('live_calls_reserved',0)
    cap=state.get('live_request_cap')
    remaining=args.max_live_requests if cap is None else min(args.max_live_requests,cap-used)
    if remaining<1:raise HarnessError('Task-wide live request allowance is exhausted')
    return OpenCodeGoAgentProvider(authorized_external_data=bool(args.authorize_data_sha256),
        max_requests=min(remaining,8),max_output_tokens=1024,
        max_total_output_tokens=min(remaining,8)*1024,cancel=cancel,
        admission_mode=args.admission_mode,
        prior_generation_reservations=state.get('live_external_prior',0)+used)


def main(argv=None):
    parser=argparse.ArgumentParser(prog='vessel-reconstruct agent',description='Evidence-led CAD task harness. Every result requires semantic review.')
    sub=parser.add_subparsers(dest='command',required=True)
    for name in ('run','resume'):
        p=sub.add_parser(name)
        if name=='run':
            p.add_argument('spec',type=Path);p.add_argument('--out',required=True,type=Path)
            p.add_argument('--max-actions',type=int,default=18)
            p.add_argument('--max-policy-calls',type=int,default=12)
            p.add_argument('--max-builds',type=int,default=3)
            p.add_argument('--wall-seconds',type=float,default=600.)
        else:p.add_argument('task',type=Path)
        p.add_argument('--policy',choices=['deterministic','scripted','live'],default='deterministic')
        p.add_argument('--script',type=Path)
        p.add_argument('--authorize-data-sha256',help='Exact captured source-manifest hash authorized for external processing')
        p.add_argument('--max-live-requests',type=int,choices=range(1,9),default=6)
        p.add_argument('--admission-mode',choices=['account_zero_budget','fresh_observed_included_allowance'],default='account_zero_budget')
    p=sub.add_parser('step',help='Apply a separately recorded operator selection or operation')
    p.add_argument('task',type=Path);p.add_argument('--decision',required=True,type=Path)
    p.add_argument('--actor',required=True,choices=['human_operator','assistant_operator'])
    p.add_argument('--note',required=True)
    for name in ('verify','status'):
        p=sub.add_parser(name);p.add_argument('task',type=Path)
    p=sub.add_parser('review',help='Export an offline source/CAD/trajectory review interface')
    p.add_argument('task',type=Path);p.add_argument('--out',required=True,type=Path)
    p=sub.add_parser('transcript',help='Export exact recorded model inputs and decisions for offline replay')
    p.add_argument('task',type=Path);p.add_argument('--out',required=True,type=Path)
    p=sub.add_parser('replay',help='Verify exact recorded decisions; makes zero provider calls and executes no CAD')
    p.add_argument('transcript',type=Path)
    args=parser.parse_args(argv)
    try:
        if args.command=='verify':
            result=verify_task(args.task);print(json.dumps(result,indent=2));return 0 if result['valid'] else 2
        if args.command=='status':
            with TaskStore(args.task) as store:
                result={k:v for k,v in store.state.items() if k!='last_observation'}
            print(json.dumps(result,indent=2));return 0
        if args.command=='review':
            from .agent_review import write_review
            print(str(write_review(args.task,args.out)));return 0
        if args.command=='replay':
            from .agent_provider import verify_replay_transcript
            result=verify_replay_transcript(load_bounded_json(args.transcript,max_bytes=8_000_000,max_nodes=300_000))
            print(json.dumps(result,indent=2));return 0 if result['verified'] else 2
        if args.command=='transcript':
            from .agent_provider import export_replay_transcript
            from .agent_harness import FINISH, _artifact_bytes
            from .provenance import write_json
            if not verify_task(args.task)['valid']:raise HarnessError('Transcript export requires intact task evidence')
            with TaskStore(args.task) as store:
                domain=DomainTools(store.path,store.path/'domain/input/spec.json')
                artifacts={}
                def visit(v):
                    if isinstance(v,dict):
                        if {'id','path','sha256','mime_type'}<=set(v):artifacts[v['id']]=v
                        for x in v.values():visit(x)
                    elif isinstance(v,list):
                        for x in v:visit(x)
                for event in store.events:visit(event['payload'])
                transcript=export_replay_transcript(store.events,domain.catalog()+[FINISH],
                    image_loader=lambda a:_artifact_bytes(store.path,artifacts[a['artifact_id']],262144))
            args.out.parent.mkdir(parents=True,exist_ok=True);write_json(args.out,transcript)
            print(str(args.out.absolute()));return 0
        cancel=threading.Event()
        old={}
        if threading.current_thread() is threading.main_thread():
            for sig in (signal.SIGINT,signal.SIGTERM):
                old[sig]=signal.signal(sig,lambda *_:cancel.set())
        try:
            creating=args.command=='run';task=args.out if creating else args.task
            with TaskStore(task,create=creating) as store:
                domain=DomainTools(store.path,args.spec if creating else store.path/'domain/input/spec.json',cancel_event=cancel)
                if creating:
                    limits=HarnessLimits(max_actions=args.max_actions,max_policy_calls=args.max_policy_calls,
                        max_builds=args.max_builds,wall_seconds=args.wall_seconds,
                        observation_bytes=21_000 if args.policy=='live' else 48_000,
                        max_image_bytes=131_072 if args.policy=='live' else 262_144)
                else:limits=HarnessLimits(**store.events[0]['payload']['limits'])
                if not creating and 'live_calls_reserved' not in store.state:
                    inferred=sum(e['kind']=='policy_requested' and e['state_after'].get('policy')=='live' for e in store.events)
                    store.append('live_budget_migrated',{'conservative_prior_reserved_calls':inferred},
                        store.state|{'live_calls_reserved':inferred,'live_external_prior':0,
                                    'live_request_cap':inferred if inferred else None,
                                    'legacy_live_allowance_unknown':bool(inferred)})
                policy=DeterministicPolicy() if args.command=='step' else _policy(args,cancel,store.state)
                harness=Harness(store,domain,policy,limits=limits,cancel_event=cancel,
                                authorize_data_sha256=getattr(args,'authorize_data_sha256',None))
                if args.command=='step':
                    state=harness.step(load_bounded_json(args.decision,max_bytes=48_000),actor=args.actor,note=args.note)
                else:state=harness.run()
                result={k:v for k,v in state.items() if k!='last_observation'}
            print(json.dumps(result,indent=2))
            return 0 if result['status'] in {'awaiting_human_review','paused'} else 2
        finally:
            for sig,previous in old.items():signal.signal(sig,previous)
    except (ValueError,OSError,KeyError,TypeError) as exc:
        # Do not print provider payloads or secrets; structured details are in receipts.
        print(json.dumps({'status':'blocked','error_type':type(exc).__name__,
                          'message':str(exc) if isinstance(exc,HarnessError) else 'Task admission or persistent evidence check failed.',
                          'engineering_approved':False},indent=2))
        return 2
