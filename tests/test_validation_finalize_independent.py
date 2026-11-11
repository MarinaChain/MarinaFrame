"""Author-separated regression expectations from actual finalization findings.

Native execution is doubled by the explicitly controlled existing fixture.
These tests exercise actual DomainTools locks, public selections, typed report
verification and Harness event commits; they do not measure hull accuracy.
"""
import json
import threading

import pytest

from vessel_reconstruction.agent_harness import Harness, ScriptedPolicy, TaskStore
from vessel_reconstruction import validation_contract as vc
from validation_fixture import ControlledValidationDomain

FINISH={'tool':'finish','arguments':{'outcome':'candidate_ready_for_review','summary':'Independent guarded finish test.'},'reason':'Exercise finalization transaction.'}


def prepared(store):
    domain=ControlledValidationDomain(store.path,maximum=.0005)
    sid=domain.spec['sections'][0]['id']
    domain.state['catalog'][sid]={'section_id':sid,'grid_evidence':{},'candidates':[
        {'candidate_id':'independent-race-choice','selectable':True,'hypothesis':'Controlled alternate',
         'contour_selection':{'anchors_px':[[100,30],[100,210]],'half_width_px':3}}]}
    domain._save()
    assert domain.execute('validate_candidate',{})['ok'] is True
    other=ControlledValidationDomain(store.path,maximum=.0005)
    return domain,other,sid


@pytest.mark.parametrize('interleaving',['predicate','termination_commit'])
def test_selection_cannot_commit_inside_finalization_transaction(tmp_path,monkeypatch,interleaving):
    with TaskStore(tmp_path/'task',create=True) as store:
        domain,other,sid=prepared(store)
        result=[]
        def attempt_selection():
            result.append(other.execute('select_contours',{'selections':[{'section_id':sid,'candidate_id':'independent-race-choice'}]}))
        if interleaving=='predicate':
            original=vc.ready_for_review
            def predicate(*args,**kwargs):
                attempt_selection()
                return original(*args,**kwargs)
            monkeypatch.setattr(vc,'ready_for_review',predicate)
        else:
            original=store.append
            def append(kind,payload,state):
                if kind=='terminated' and state.get('status')=='awaiting_human_review':attempt_selection()
                return original(kind,payload,state)
            monkeypatch.setattr(store,'append',append)
        state=Harness(store,domain,ScriptedPolicy([FINISH])).run()
        assert len(result)==1, 'The intended finalization interleaving was not exercised'
        assert result[0]['ok'] is False, 'A second domain selection committed while finalization was in progress'
        persisted=json.loads(domain.state_path.read_text())
        assert persisted['revision']==0 and persisted['selected']=={}
        assert state['status']=='awaiting_human_review' and state['engineering_approved'] is False


def test_cancel_after_predicate_pass_prevents_review_ready_commit(tmp_path,monkeypatch):
    with TaskStore(tmp_path/'task',create=True) as store:
        domain,_,_=prepared(store);event=threading.Event();called=[]
        original=vc.ready_for_review
        def predicate(*args,**kwargs):
            result=original(*args,**kwargs);called.append(result);event.set();return result
        monkeypatch.setattr(vc,'ready_for_review',predicate)
        state=Harness(store,domain,ScriptedPolicy([FINISH]),cancel_event=event).run()
        assert called==[True], 'Cancellation must be injected after a complete passing predicate'
        assert event.is_set() and state['status']=='cancelled'
        assert state['engineering_approved'] is False


@pytest.mark.parametrize('bad_revision',[False,True,0.0,-1,10**12,None])
def test_malformed_persisted_revision_is_rejected_without_recovery_promotion(tmp_path,bad_revision):
    domain=ControlledValidationDomain(tmp_path/'task',maximum=.0005)
    assert domain.execute('validate_candidate',{})['ok'] is True
    state=json.loads(domain.state_path.read_text());state['revision']=bad_revision
    domain.state_path.write_text(json.dumps(state))
    # A live object must reject cleanly instead of formatting invalid state again
    # in its error-observation path. A newly opened object must refuse admission.
    result=domain.execute('validate_candidate',{})
    assert result['ok'] is False
    with pytest.raises((ValueError,TypeError)):
        ControlledValidationDomain(domain.task_dir,maximum=.0005)


def test_elapsed_deadline_after_predicate_prevents_review_ready_commit(tmp_path,monkeypatch):
    from vessel_reconstruction import agent_harness
    with TaskStore(tmp_path/'task',create=True) as store:
        domain,_,_=prepared(store);called=[]
        original=vc.ready_for_review;clock=agent_harness.time.monotonic
        def predicate(*args,**kwargs):
            result=original(*args,**kwargs);called.append(result)
            monkeypatch.setattr(agent_harness.time,'monotonic',lambda:clock()+3600)
            return result
        monkeypatch.setattr(vc,'ready_for_review',predicate)
        state=Harness(store,domain,ScriptedPolicy([FINISH])).run()
        assert called==[True]
        assert state['status']=='budget_exhausted' and state['engineering_approved'] is False
