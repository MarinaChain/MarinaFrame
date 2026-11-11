"""Controller boundary, interruption, evidence and review invariants."""
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import threading
import time

import pytest

from vessel_reconstruction.agent_harness import (DeterministicPolicy, Harness, HarnessError,
    HarnessLimits, ScriptedPolicy, TaskStore, _artifact_bytes, verify_task)


def decision(tool, arguments=None):
    return {'tool':tool,'arguments':arguments or {},'reason':'Test policy proposal.'}


def stop():
    return decision('finish',{'outcome':'abstain','summary':'Evidence is insufficient.'})


class Domain:
    def __init__(self):self.calls=[];self.valid=False
    def catalog(self):
        return [{'name':n,'description':'A bounded test tool','parameters':{'type':'object'}}
                for n in ('inspect_source','select_contours','build_provisional','render_candidate','validate_candidate')]
    def describe(self):
        return {'source_manifest_sha256':'a'*64,'section_count':1,'catalog_ready':False,'sections':[{'id':'s1'}]}
    def execute(self,name,args):
        self.calls.append((name,args))
        if args and name!='select_contours':return {'ok':False,'error_code':'unexpected_arguments'}
        if name=='validate_candidate':return {'ok':self.valid,'engineering_approved':False}
        return {'ok':True,'status':'observed','engineering_approved':False}


def run(tmp_path, choices, *, limits=None, domain=None, cancel=None):
    domain=domain or Domain()
    with TaskStore(tmp_path/'task',create=True) as store:
        result=Harness(store,domain,ScriptedPolicy(choices),limits=limits,cancel_event=cancel).run()
        events=list(store.events)
    return result,events,domain


def test_unknown_operation_rejected_then_policy_can_revise(tmp_path):
    state,events,domain=run(tmp_path,[decision('exec',{'code':'import os'}),decision('inspect_source'),stop()])
    assert state['rejections']==1 and state['status']=='blocked'
    assert domain.calls==[('inspect_source',{})]
    assert 'decision_rejected' in [e['kind'] for e in events]
    assert verify_task(tmp_path/'task')['valid']


def test_forbidden_arguments_do_not_create_export_or_approval(tmp_path):
    state,events,domain=run(tmp_path,[decision('build_provisional',{'output_dir':'/tmp/escape'}),stop()])
    assert state['builds']==1 and state['rejections']==1 and not state['engineering_approved']
    assert events[-1]['state_after']['human_semantic_review_required']


def test_final_model_approval_cannot_override_failed_geometry(tmp_path):
    state,events,domain=run(tmp_path,[decision('finish',{'outcome':'candidate_ready_for_review','summary':'Approved'})])
    assert state['status']=='blocked'
    assert domain.calls==[('validate_candidate',{})]
    assert not state['engineering_approved']


def test_even_valid_geometry_never_grants_engineering_approval(tmp_path):
    domain=Domain();domain.valid=True
    state,_,_=run(tmp_path,[decision('finish',{'outcome':'candidate_ready_for_review','summary':'Review'})],domain=domain)
    assert state['status']=='awaiting_human_review' and not state['engineering_approved']


def test_repeated_tool_has_no_progress_stop(tmp_path):
    state,_,domain=run(tmp_path,[decision('inspect_source')]*4)
    assert state['status']=='no_progress' and len(domain.calls)==2


def test_global_build_budget_blocks_even_different_proposals(tmp_path):
    state,_,domain=run(tmp_path,[decision('build_provisional'),decision('inspect_source'),decision('build_provisional')],
                       limits=replace(HarnessLimits(),max_builds=1))
    assert state['status']=='budget_exhausted'
    assert sum(n=='build_provisional' for n,_ in domain.calls)==1


def test_policy_calls_reserved_before_failure_and_not_reset_on_resume(tmp_path):
    domain=Domain();limits=replace(HarnessLimits(),max_policy_calls=1)
    state,events,_=run(tmp_path,[],limits=limits,domain=domain)
    assert state['status']=='provider_failed' and state['policy_calls']==1
    with TaskStore(tmp_path/'task') as store:
        resumed=Harness(store,domain,ScriptedPolicy([stop()]),limits=limits).run()
    assert resumed['status']=='budget_exhausted' and resumed['policy_calls']==1


def test_resume_cannot_increase_limits(tmp_path):
    run(tmp_path,[stop()])
    with TaskStore(tmp_path/'task') as store:
        with pytest.raises(HarnessError,match='preserve'):
            Harness(store,Domain(),ScriptedPolicy([stop()]),limits=replace(HarnessLimits(),max_actions=19)).run()


def test_pre_cancel_does_not_call_policy(tmp_path):
    cancel=threading.Event();cancel.set()
    state,_,domain=run(tmp_path,[decision('inspect_source')],cancel=cancel)
    assert state['status']=='cancelled' and not domain.calls and state['policy_calls']==0


def test_global_deadline_cancels_cooperating_policy(tmp_path):
    cancel=threading.Event()
    class Slow:
        kind='mock';supports_images=False
        def decide(self,*args):
            assert cancel.wait(2)
            raise RuntimeError('cancelled')
    with TaskStore(tmp_path/'task',create=True) as store:
        state=Harness(store,Domain(),Slow(),cancel_event=cancel,limits=replace(HarnessLimits(),wall_seconds=.05)).run()
    assert state['status']=='budget_exhausted' and state['elapsed_seconds']<1


def test_live_transfer_needs_exact_captured_manifest_authorization(tmp_path):
    class Live:
        kind='live';supports_images=True
        def decide(self,*args):raise AssertionError('must not send')
    with TaskStore(tmp_path/'task',create=True) as store:
        state=Harness(store,Domain(),Live(),authorize_data_sha256='b'*64).run()
    assert state['status']=='blocked' and state['policy_calls']==0


def test_lock_prevents_two_controllers(tmp_path):
    with TaskStore(tmp_path/'task',create=True):
        with pytest.raises(HarnessError,match='Another'):
            TaskStore(tmp_path/'task')


def test_event_and_cache_tampering_are_detected(tmp_path):
    run(tmp_path,[stop()]);task=tmp_path/'task'
    state=json.loads((task/'state.json').read_text());state['state']['engineering_approved']=True
    (task/'state.json').write_text(json.dumps(state))
    assert not verify_task(task)['valid']
    event=task/'events/000001.json';value=json.loads(event.read_text());value['payload']['domain']={}
    event.write_text(json.dumps(value))
    assert not verify_task(task)['valid']


def test_event_gap_and_symlink_are_detected(tmp_path):
    run(tmp_path,[stop()]);task=tmp_path/'task'
    p=task/'events/000001.json';p.rename(task/'events/000099.json')
    assert not verify_task(task)['valid']


def test_uncheckpointed_domain_mutation_fails_closed(tmp_path):
    domain=Domain();domain.state_path=tmp_path/'domain.json';domain.state_path.write_text('{}')
    run(tmp_path,[stop()],domain=domain)
    domain.state_path.write_text('{"changed":true}')
    with TaskStore(tmp_path/'task') as store:
        with pytest.raises(HarnessError,match='checkpoint'):
            Harness(store,domain,ScriptedPolicy([stop()])).run()


def test_interrupted_request_is_recorded_and_reservation_retained(tmp_path):
    with TaskStore(tmp_path/'task',create=True) as store:
        harness=Harness(store,Domain(),ScriptedPolicy([stop()]));harness._start()
        store.append('policy_requested',{'observation':{}},store.state|{'policy_calls':1,'status':'running'})
    with TaskStore(tmp_path/'task') as store:
        state=Harness(store,Domain(),ScriptedPolicy([stop()])).run()
        assert any(e['kind']=='interrupted_operation' for e in store.events)
    assert state['policy_calls']==2


def test_operator_action_is_distinct_and_cannot_finish_or_bypass_budgets(tmp_path):
    with TaskStore(tmp_path/'task',create=True) as store:
        h=Harness(store,Domain(),DeterministicPolicy(),limits=replace(HarnessLimits(),max_actions=1))
        state=h.step(decision('inspect_source'),actor='assistant_operator',note='Test inspection')
        assert state['operator_actions']==1 and state['policy_calls']==0
        assert store.events[1]['payload']['identity_verified'] is False
        with pytest.raises(HarnessError):h.step(stop(),actor='human_operator',note='Approve')
        with pytest.raises(HarnessError,match='budgets'):h.step(decision('inspect_source'),actor='human_operator',note='Again')


def test_artifact_hash_path_and_symlink_boundary(tmp_path):
    raw=b'pixels';p=tmp_path/'image.png';p.write_bytes(raw)
    a={'path':'image.png','sha256':hashlib.sha256(raw).hexdigest()}
    assert _artifact_bytes(tmp_path,a,10)==raw
    for path in ('../outside','/etc/passwd'):
        with pytest.raises(HarnessError):_artifact_bytes(tmp_path,a|{'path':path},10)
    p.unlink();p.symlink_to(tmp_path/'absent')
    with pytest.raises(HarnessError):_artifact_bytes(tmp_path,a,10)


def test_deterministic_policy_abstains_on_competitors_and_selects_only_unique_source_id():
    policy=DeterministicPolicy();domain={'sections':[{'id':'s1'}],'section_count':1,'selected_count':0}
    section={'section_id':'s1','candidates':[{'candidate_id':'a','selectable':True},{'candidate_id':'b','selectable':True}],
             'grid_evidence':{'unique_non_grid_candidate_id':None}}
    obs={'domain':domain,'last_tool_observation':{'sections':[section]}}
    assert policy.decide(obs,[],[])['decision']['arguments']['outcome']=='abstain'
    section['grid_evidence']['unique_non_grid_candidate_id']='a'
    result=policy.decide(obs,[],[])['decision']
    assert result['arguments']['selections']==[{'section_id':'s1','candidate_id':'a'}]


@pytest.mark.parametrize('kwargs',[{'max_actions':True},{'wall_seconds':float('nan')},{'wall_seconds':float('inf')},
    {'max_images_per_call':4},{'observation_bytes':1}])
def test_invalid_limits(kwargs):
    with pytest.raises(HarnessError):HarnessLimits(**kwargs)


def test_observation_pagination_never_silently_removes_alternatives():
    from vessel_reconstruction.agent_harness import bounded_observation
    rivals=[{'candidate_id':str(i),'selectable':True,'support':'x'*1000} for i in range(80)]
    observation={'task':{'status':'running'},'domain':{'sections':[{'id':'s1'}],
        'section_count':1,'selected_count':0,'catalog_ready':True,'inspected_sections':rivals},
        'last_tool_observation':{'sections':[{'section_id':'s1','candidates':rivals}]}}
    bounded=bounded_observation(observation,6000)
    assert bounded['last_tool_observation']['error_code']=='observation_too_large'
    assert bounded['domain']['inspected_sections']==[]
    assert len(observation['last_tool_observation']['sections'][0]['candidates'])==80
    result=DeterministicPolicy().decide(bounded,[],[])['decision']
    assert result=={'tool':'inspect_source','arguments':{'section_ids':['s1']},'reason':'Fixed source-grammar comparison policy.'}


def test_bounded_observation_keeps_all_alternatives_when_they_fit():
    from vessel_reconstruction.agent_harness import bounded_observation
    section={'section_id':'s','candidates':[{'candidate_id':'a'},{'candidate_id':'b'}]}
    obs={'task':{},'domain':{'inspected_sections':[section]},'last_tool_observation':{'sections':[section]}}
    result=bounded_observation(obs,6000)
    assert result['last_tool_observation']['sections']==[section]
    assert 'inspected_sections' not in result['domain']


def test_missing_required_domain_checkpoint_cannot_verify(tmp_path):
    from test_agent_tools import drawing
    from vessel_reconstruction.agent_tools import DomainTools
    spec,_=drawing(tmp_path/'input')
    with TaskStore(tmp_path/'task',create=True) as store:
        domain=DomainTools(store.path,spec)
        Harness(store,domain,ScriptedPolicy([stop()])).run()
    assert verify_task(tmp_path/'task')['valid']
    domain.state_path.unlink()
    result=verify_task(tmp_path/'task')
    assert not result['valid'] and 'Required domain checkpoint is missing' in result['problems']


@pytest.mark.parametrize('exhaustion',['elapsed','rejections','cancelled'])
def test_operator_step_cannot_bypass_other_controller_gates(tmp_path,exhaustion):
    cancel=threading.Event();domain=Domain();limits=replace(HarnessLimits(),wall_seconds=1.)
    with TaskStore(tmp_path/'task',create=True) as store:
        harness=Harness(store,domain,DeterministicPolicy(),limits=limits,cancel_event=cancel)
        harness._start()
        if exhaustion=='elapsed':store.append('test_checkpoint',{},store.state|{'elapsed_seconds':2.})
        elif exhaustion=='rejections':store.append('test_checkpoint',{},store.state|{'rejections':3})
        else:cancel.set()
        with pytest.raises(HarnessError):harness.step(decision('inspect_source'),actor='assistant_operator',note='Test boundary')
    assert not domain.calls


def test_operator_native_deadline_propagates_cancellation(tmp_path):
    cancel=threading.Event()
    class WaitingDomain(Domain):
        def execute(self,*args):
            assert cancel.wait(1)
            return {'ok':False,'status':'cancelled'}
    with TaskStore(tmp_path/'task',create=True) as store:
        state=Harness(store,WaitingDomain(),DeterministicPolicy(),cancel_event=cancel,
            limits=replace(HarnessLimits(),wall_seconds=.05)).step(decision('inspect_source'),
                actor='assistant_operator',note='Exercise deadline')
    assert state['status']=='budget_exhausted' and state['elapsed_seconds']<1


def test_live_allowance_does_not_reset_on_resume(tmp_path):
    class Live:
        kind='live';supports_images=False
        def __init__(self,cap,prior):self.max_requests=cap;self.prior_generation_reservations=prior;self.calls=0
        def decide(self,*args):
            self.calls+=1
            return {'decision':stop(),'receipt':{'evidence_mode':'mock_transport'}}
    first=Live(1,0)
    with TaskStore(tmp_path/'task',create=True) as store:
        state=Harness(store,Domain(),first,authorize_data_sha256='a'*64).run()
    assert state['live_request_cap']==1 and state['live_calls_reserved']==1
    wrong_prior=Live(6,0)
    with TaskStore(tmp_path/'task') as store:
        with pytest.raises(HarnessError,match='reservations'):
            Harness(store,Domain(),wrong_prior,authorize_data_sha256='a'*64).run()
    resumed=Live(6,1)
    with TaskStore(tmp_path/'task') as store:
        state=Harness(store,Domain(),resumed,authorize_data_sha256='a'*64).run()
    assert state['status']=='budget_exhausted' and state['live_request_cap']==1 and resumed.calls==0


def test_resumed_timer_is_computed_after_charging_interruption(tmp_path,monkeypatch):
    import vessel_reconstruction.agent_harness as module
    delays=[]
    class Timer:
        def __init__(self,delay,callback):delays.append(delay)
        def start(self):pass
        def cancel(self):pass
    limits=replace(HarnessLimits(),wall_seconds=.15)
    with TaskStore(tmp_path/'task',create=True) as store:
        harness=Harness(store,Domain(),ScriptedPolicy([stop()]),limits=limits)
        harness._start()
        pending=store.append('policy_requested',{},store.state|{'policy_calls':1,'status':'running'})
        monkeypatch.setattr(module.time,'time',lambda:pending['time_unix']+.10)
        monkeypatch.setattr(module.threading,'Timer',Timer)
        harness.run()
    assert len(delays)==1 and .04<delays[0]<.06


def test_legacy_live_task_with_unknown_original_allowance_cannot_dispatch(tmp_path):
    class Live:
        kind='live';supports_images=False;max_requests=8;prior_generation_reservations=1;calls=0
        def decide(self,*args):raise AssertionError('Unknown legacy authorization cannot permit a new request')
    with TaskStore(tmp_path/'task',create=True) as store:
        h=Harness(store,Domain(),ScriptedPolicy([stop()]));h._start()
        legacy={k:v for k,v in store.state.items() if k not in {'live_request_cap','live_calls_reserved','live_external_prior'}}
        legacy.update(policy='live',policy_calls=1,status='provider_failed')
        store.append('policy_requested',{},legacy)
        state=Harness(store,Domain(),Live(),authorize_data_sha256='a'*64).run()
    assert state['status']=='budget_exhausted'
    assert state['legacy_live_allowance_unknown'] and state['live_request_cap']==state['live_calls_reserved']==1


def test_late_validation_does_not_turn_deadline_into_success(tmp_path):
    class LateDomain(Domain):
        def execute(self,name,args):
            time.sleep(.06)
            return {'ok':True}
    state,_,_=run(tmp_path,[decision('finish',{'outcome':'candidate_ready_for_review','summary':'Review'})],
        domain=LateDomain(),limits=replace(HarnessLimits(),wall_seconds=.03))
    assert state['status']=='budget_exhausted' and not state['engineering_approved']
