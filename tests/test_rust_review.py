"""Rust review boundary tests; CLI execution is explicit and injectable."""
from copy import deepcopy
import hashlib
import http.client
import json
from pathlib import Path
import re
import threading
import time

import pytest
from PIL import Image

from vessel_reconstruction import rust_review as rr


@pytest.fixture
def task(tmp_path):
    task=tmp_path/'task';(task/'events').mkdir(parents=True);(task/'domain').mkdir()
    image=task/'source.png';Image.new('RGB',(10,12),'white').save(image)
    sha=rr.digest_file(image)
    artifact={'path':'source.png','sha256':sha,'bytes':image.stat().st_size,'id':'artifact-'+sha[:24],
              'kind':'source_page','mime_type':'image/png'}
    domain={'catalog':{'s0':{'x_m':0,'candidates':[{'candidate_id':'c0','hypothesis':'<script>untrusted()</script>','selectable':True}]}},'selected':{},'validation':None}
    (task/'domain/state.json').write_text(json.dumps(domain));domain_hash=rr.digest_file(task/'domain/state.json')
    state={'task_id':'task-fixture','status':'paused','generation_id':'generation-'+'1'*24,'revision_id':'r0000',
           'source_manifest_sha256':'2'*64,'domain_checkpoint_sha256':domain_hash,'config':{'policy':'deterministic','model':'fixture'},
           'domain':{'current_candidate':None},'counters':{'builds':0,'operator_actions':0,'requests_intended':0,
               'requests_completed':0,'requests_unknown':0,'requests_failed':0,'prompt_tokens':0,'completion_tokens':0,'requests_without_cost':0}}
    (task/'state.json').write_text(json.dumps({'head_sha256':'3'*64,'state':state}))
    (task/'events/000001.json').write_text(json.dumps({'sequence':1,'kind':'worker_result','state_after':state,
         'payload':{'response':{'result':{'artifacts':[artifact]}}}}))
    verify={'valid':True,'head_sha256':'3'*64,'events':1,'pending_domain_requires_reconciliation':False}
    def runner(controller,args,**kwargs):return deepcopy(verify)
    return task,runner,verify


def test_snapshot_rechecks_rust_head_and_embeds_exact_image(task):
    root,runner,_=task;calls=[]
    def tracked(*args,**kwargs):calls.append(args[1][0]);return runner(*args,**kwargs)
    view=rr.snapshot(root,Path('/configured/controller'),runner=tracked)
    assert calls==['verify','verify'] and view['images_embedded']==1
    assert view['figures'][0]['freshness']=='captured_source'
    assert view['binding']['expected_head_sha256']=='3'*64
    html=rr.render_html(view)
    assert '<script>untrusted()' not in html and '&lt;script&gt;untrusted()' in html
    assert 'engineering_approved' not in view['binding']


def test_changed_source_image_is_not_displayed(task):
    root,runner,_=task;(root/'source.png').write_bytes(b'changed')
    with pytest.raises(rr.ReviewError,match='artifact_'):rr.snapshot(root,Path('/configured/controller'),runner=runner)


def test_changed_checkpoint_or_head_is_not_exported(task):
    root,runner,verify=task;calls=0
    def race(*args,**kwargs):
        nonlocal calls
        calls+=1;out=runner(*args,**kwargs)
        if calls==2:out['head_sha256']='4'*64
        return out
    with pytest.raises(rr.ReviewError,match='task_changed'):rr.snapshot(root,Path('/configured/controller'),runner=race)
    (root/'domain/state.json').write_text('{}')
    with pytest.raises(rr.ReviewError,match='checkpoint_changed'):rr.snapshot(root,Path('/configured/controller'),runner=runner)


def test_artifact_traversal_and_symlinks_are_rejected(task):
    root,runner,_=task;p=root/'events/000001.json';event=json.loads(p.read_text())
    event['payload']['response']['result']['artifacts'][0]['path']='../source.png';p.write_text(json.dumps(event))
    with pytest.raises(ValueError):rr.snapshot(root,Path('/configured/controller'),runner=runner)


def test_step_render_freshness_uses_both_revision_and_generation(task):
    root,runner,_=task;p=root/'events/000001.json';event=json.loads(p.read_text())
    result=event['payload']['response']['result'];result['artifacts'][0]['kind']='step_reimport_render'
    result['rendered_generation_id']=event['state_after']['generation_id'];result['rendered_revision_id']='r0009'
    p.write_text(json.dumps(event));view=rr.snapshot(root,Path('/configured/controller'),runner=runner)
    assert view['figures'][0]['freshness']=='preserved_older_candidate'
    assert 'Preserved older candidate' in rr.render_html(view)


@pytest.fixture
def server(task):
    root,runner,_=task;calls=[]
    def controller(binary,args,**kwargs):
        if args[0]=='verify':return runner(binary,args,**kwargs)
        calls.append(list(map(str,args)));return {'status':'paused','engineering_approved':False}
    server=rr.ReviewServer(('127.0.0.1',0),root,Path('/configured/controller'),allow_actions=True,
                           actor='assistant_operator',runner=controller)
    server.read_view();thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    yield server,calls
    server.shutdown();server.server_close();thread.join(3)


def request(server,method,path,body=None,headers=None):
    conn=http.client.HTTPConnection('127.0.0.1',server.server_address[1],timeout=5)
    supplied={'Origin':server.origin}
    if body is not None:supplied['Content-Type']='application/json'
    supplied.update(headers or {})
    raw=None if body is None else (body if isinstance(body,str) else json.dumps(body))
    conn.request(method,path,body=raw,headers=supplied);response=conn.getresponse()
    value=response.read();result=(response.status,dict(response.getheaders()),value)
    conn.close();return result


def login(server):
    status,headers,_=request(server,'POST','/api/session',{'token':server.bootstrap})
    assert status==200
    cookie=headers['Set-Cookie'].split(';')[0]
    status,_,html=request(server,'GET','/',headers={'Cookie':cookie})
    assert status==200
    config=json.loads(re.search(rb'<script id="review-config" type="application/json">(.*?)</script>',html).group(1))
    return cookie,config


@pytest.mark.parametrize('headers',[{'Host':'evil.example'},{'Origin':'https://evil.example'},{'Origin':'null'}])
def test_host_and_origin_reject_before_session_or_action(server,headers):
    s,calls=server;status,_,_=request(s,'POST','/api/session',{'token':s.bootstrap},headers)
    assert status==403 and not calls


def test_one_time_bootstrap_cookie_and_csrf_are_required(server):
    s,calls=server;cookie,config=login(s)
    assert request(s,'POST','/api/session',{'token':s.bootstrap})[0]==403
    assert request(s,'GET','/api/job')[0]==401
    assert request(s,'POST','/api/action',{'operation':'cancel','note':''},{'Cookie':cookie})[0]==403
    assert not calls
    status,_,_=request(s,'POST','/api/action',{'operation':'cancel','note':''},
                      {'Cookie':cookie,'X-CSRF-Token':config['csrf']})
    assert status==200 and calls[-1][0]=='cancel'


def test_stale_foreign_and_path_operations_never_reach_cli(server):
    s,calls=server;cookie,config=login(s);headers={'Cookie':cookie,'X-CSRF-Token':config['csrf']}
    intervention=config['binding']|{'decision':{'tool':'build_provisional','arguments':{},'reason':'Fixture'}}
    intervention['expected_head_sha256']='f'*64
    body={'operation':'intervene','note':'Explicit fixture action','intervention':intervention}
    assert request(s,'POST','/api/action',body,headers)[0]==409 and not calls
    body['intervention']=config['binding']|{'decision':{'tool':'execute_shell','arguments':{'path':'/etc/passwd'},'reason':'Fixture'}}
    assert request(s,'POST','/api/action',body,headers)[0]==409 and not calls
    assert request(s,'GET','/../../etc/passwd',headers={'Cookie':cookie})[0]==404


def test_typed_intervention_calls_fixed_rust_command_and_actor(server):
    s,calls=server;cookie,config=login(s);headers={'Cookie':cookie,'X-CSRF-Token':config['csrf']}
    body={'operation':'intervene','note':'Explicit fixture action','intervention':config['binding']|{
        'decision':{'tool':'build_provisional','arguments':{},'reason':'Fixture'}}}
    status,_,raw=request(s,'POST','/api/action',body,headers);assert status==202
    for _ in range(100):
        if s.job['status']!='running':break
        time.sleep(.01)
    assert s.job['status']=='completed' and calls[-1][0]=='step'
    assert calls[-1][-4:]==['--actor','assistant_operator','--note','Explicit fixture action']
    assert '--intervention' in calls[-1] and s.job['result']['engineering_approved'] is False


def test_second_concurrent_action_is_rejected_but_cancel_remains_available(server):
    s,calls=server;cookie,config=login(s);headers={'Cookie':cookie,'X-CSRF-Token':config['csrf']}
    s.job_lock.acquire()
    try:
        body={'operation':'resume','note':'Fixture','steps':1,'clear_cancel':False,'binding':config['binding']}
        assert request(s,'POST','/api/action',body,headers)[0]==409
        assert request(s,'POST','/api/action',{'operation':'cancel','note':''},headers)[0]==200
    finally:s.job_lock.release()


def test_read_only_and_live_task_mutations_are_refused(server):
    s,calls=server;cookie,config=login(s);headers={'Cookie':cookie,'X-CSRF-Token':config['csrf']}
    s.allow_actions=False
    assert request(s,'POST','/api/action',{'operation':'cancel','note':''},headers)[0]==409
    s.allow_actions=True;s.action_policy='live'
    assert request(s,'POST','/api/action',{'operation':'cancel','note':''},headers)[0]==409
    assert not calls


def test_duplicate_json_and_oversized_requests_are_refused(server):
    s,_=server
    assert request(s,'POST','/api/session','{"token":"a","token":"b"}')[0]==400
    assert request(s,'POST','/api/session',{'token':'x'*70000})[0]==400


def test_embedded_configuration_preserves_literal_text_without_script_injection(task):
    root,runner,_=task;view=rr.snapshot(root,Path('/configured/controller'),runner=runner)
    view['binding']['task_id']='</script><script>not_executable()</script>'
    markup=rr.render_html(view)
    config=json.loads(re.search(r'<script id="review-config" type="application/json">(.*?)</script>',markup).group(1))
    assert config['binding']['task_id']==view['binding']['task_id']
    assert '<script>not_executable()' not in markup


def test_non_ascii_credentials_fail_closed_without_connection_abort(server):
    s,calls=server
    assert request(s,'POST','/api/session',{'token':'invalid-é'})[0]==403
    assert request(s,'POST','/api/session',{'token':'\ud800'})[0]==403
    cookie,config=login(s)
    assert request(s,'POST','/api/action',{'operation':'cancel','note':''},
                   {'Cookie':cookie,'X-CSRF-Token':'invalid-é'})[0]==403
    assert not calls


def test_resume_passes_atomic_binding_to_rust_and_preserves_race_refusal(server):
    s,calls=server;cookie,config=login(s);headers={'Cookie':cookie,'X-CSRF-Token':config['csrf']}
    original_runner=s.runner
    def changed_before_process_lock(binary,args,**kwargs):
        if args[0]=='verify':return original_runner(binary,args,**kwargs)
        calls.append(list(map(str,args)))
        raise rr.ReviewError('stale_or_foreign_intervention')
    s.runner=changed_before_process_lock
    body={'operation':'resume','note':'Resume after inspecting current source evidence.',
          'steps':4,'clear_cancel':False,'binding':config['binding']}
    assert request(s,'POST','/api/action',body,headers)[0]==202
    for _ in range(100):
        if s.job['status']!='running':break
        time.sleep(.01)
    assert s.job['status']=='failed' and s.job['error_code']=='stale_or_foreign_intervention'
    args=calls[-1];assert args[0]=='resume'
    for key,flag in [('expected_head_sha256','--expected-head-sha256'),
                     ('expected_generation_id','--expected-generation-id'),
                     ('expected_revision_id','--expected-revision-id'),('task_id','--expected-task-id')]:
        assert args[args.index(flag)+1]==config['binding'][key]
