"""Real loopback HTTP boundaries; credentials below are per-test random sessions."""
import base64
import hashlib
import http.client
import io
import json
from pathlib import Path
import socket
import threading
import time
from unittest.mock import patch

import pytest
from PIL import Image

from vessel_reconstruction.isolation import WorkerLimits
from vessel_reconstruction.pipeline import reconstruct
from vessel_reconstruction.server import WorkbenchServer, _run_id, write_snapshot


def png():
    buffer=io.BytesIO();Image.new('RGB',(20,20),'white').save(buffer, format='PNG');return buffer.getvalue()


class Client:
    def __init__(self, server):
        self.server=server; self.cookie=''; self.csrf=''
    def request(self, path, payload=None, *, method=None, headers=None, auth=True, csrf=True, raw=None):
        headers=dict(headers or {})
        if auth and self.cookie: headers['Cookie']=self.cookie
        if csrf and self.csrf: headers['X-MarinaFrame-CSRF']=self.csrf
        if payload is not None:
            raw=json.dumps(payload).encode(); headers.setdefault('Content-Type','application/json')
        if method is None: method='POST' if payload is not None else 'GET'
        connection=http.client.HTTPConnection('127.0.0.1',self.server.server_address[1],timeout=5)
        connection.request(method,path,body=raw,headers=headers)
        response=connection.getresponse(); body=response.read(); result=(response.status,dict(response.getheaders()),body);connection.close();return result
    def login(self):
        status,headers,body=self.request('/api/session',{'token':self.server.bootstrap_token},auth=False)
        assert status==200
        self.cookie=headers['Set-Cookie'].split(';',1)[0];self.csrf=json.loads(body)['csrf']
        assert 'HttpOnly' in headers['Set-Cookie'] and 'SameSite=Strict' in headers['Set-Cookie']


@pytest.fixture
def service(tmp_path):
    artifacts=tmp_path/'artifacts';source=tmp_path/'drawing.png';source.write_bytes(png())
    spec={'schema_version':'1.0','vessel_id':'server-test','units':'unknown','source':{'file':'drawing.png'},'symmetry':'port_starboard','symmetry_evidence':'Explicit test assumption','end_closure':'flat_at_terminal_stations','sections':[]}
    path=tmp_path/'spec.json';path.write_text(json.dumps(spec))
    run=artifacts/'published';result=reconstruct(path,run,export_cad=False)
    assert result['status']=='blocked'
    server=WorkbenchServer(('127.0.0.1',0),artifacts,Path(__file__).resolve().parents[1]/'src/vessel_reconstruction/web',queue_options={'start_worker':False,'min_free_bytes':0,'limits':WorkerLimits(output_bytes=1024**2)})
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    client=Client(server);client.login()
    try: yield server,client,run
    finally: server.shutdown();server.server_close();thread.join(2)


def test_read_and_write_require_session(service):
    server,client,run=service
    for path in ['/api/runs','/api/health','/api/jobs/'+'a'*32,f'/api/run/{_run_id("published")}/source.png']:
        assert client.request(path,auth=False)[0]==401
    assert client.request('/api/uploads',{},auth=False)[0]==401
    assert client.request('/')[0]==200
    assert client.request('/api/session')[0]==200
    assert client.request('/api/uploads',{},csrf=False)[0]==403


@pytest.mark.parametrize('host,origin',[('attacker.example','http://attacker.example'),('localhost','http://localhost'),('127.0.0.1:1','http://127.0.0.1:1')])
def test_matching_hostile_host_origin_never_pass(service,host,origin):
    server,client,run=service
    headers={'Host':host,'Origin':origin}
    assert client.request('/api/runs',headers=headers)[0]==403
    assert client.request('/api/reconstruct',{'spec':{},'image_base64':'AA=='},headers=headers)[0]==403


def test_cross_origin_null_origin_and_duplicate_host_rejected(service):
    server,client,run=service
    for origin in ['https://unrelated.example','null','http://localhost:1']:
        assert client.request('/api/runs',headers={'Origin':origin})[0]==403
    conn=http.client.HTTPConnection('127.0.0.1',server.server_address[1],timeout=3)
    conn.putrequest('GET','/api/runs',skip_host=True)
    conn.putheader('Host',f'127.0.0.1:{server.server_address[1]}');conn.putheader('Host','attacker.example');conn.endheaders()
    assert conn.getresponse().status==403;conn.close()


def test_bootstrap_one_use_and_expired_sessions(service):
    server,client,run=service
    assert client.request('/api/session',{'token':server.bootstrap_token},auth=False)[0]==403
    with server.session_lock:
        for record in server.sessions.values(): record['expires']=0
    assert client.request('/api/runs')[0]==401


def test_remote_bind_refused_without_creating_queue(tmp_path):
    with pytest.raises(ValueError,match='Remote binding'):
        WorkbenchServer(('0.0.0.0',0),tmp_path/'artifacts',tmp_path)
    assert not (tmp_path/'artifacts').exists()


def test_inventory_original_bytes_and_streaming_response(service):
    server,client,run=service
    status,headers,body=client.request('/api/runs');assert status==200
    record=json.loads(body)['runs'][0]
    assert record['name']=='server-test' and record['integrity']=='local_manifest'
    original_read_bytes = Path.read_bytes
    def only_asset_stream(path):
        if path == run/'source.png': raise AssertionError('download must stream')
        return original_read_bytes(path)
    with patch.object(Path,'read_bytes',only_asset_stream):
        status,headers,body=client.request(f'/api/run/{_run_id("published")}/source.png')
    assert status==200 and body==png()
    assert headers['X-Content-Type-Options']=='nosniff'


def test_traversal_symlink_and_cross_run_asset_not_served(service,tmp_path):
    server,client,run=service
    (tmp_path/'private.json').write_text('private')
    (run/'outside.json').symlink_to(tmp_path/'private.json')
    for path in [f'/api/run/{_run_id("published")}/../../private.json',f'/api/run/{_run_id("../")}/private.json',f'/api/run/{_run_id("published")}/outside.json',f'/api/run/{_run_id("published")}/../other/source.png']:
        assert client.request(path)[0] in (400,404,409)
    assert client.request(f'/api/run/{_run_id(".workbench")}/jobs.sqlite3')[0]==400


def test_tampered_and_legacy_runs_have_no_downloads(service):
    server,client,run=service
    (run/'source.png').write_bytes(b'tampered')
    assert client.request(f'/api/run/{_run_id("published")}/source.png')[0]==409
    legacy=server.artifacts/'legacy';legacy.mkdir();(legacy/'result.json').write_text(json.dumps({'vessel_id':'legacy','status':'review_required','exports':{'step':'model.step'}}));(legacy/'model.step').write_text('old')
    assert client.request(f'/api/run/{_run_id("legacy")}/model.step')[0]==409
    with pytest.raises(ValueError,match='manifest'):
        write_snapshot(legacy,server.artifacts/'legacy.html')


def test_reference_local_path_needs_matching_uploaded_bytes(service):
    server,client,run=service
    payload={'spec':{'source':{},'station_reference':{'file':'/etc/passwd'}},'image_base64':base64.b64encode(png()).decode()}
    status,_,body=client.request('/api/reconstruct',payload)
    assert status==400 and 'uploaded station-reference' in json.loads(body)['error']
    assert not list(server.queue.inputs.iterdir())


def test_stream_upload_integrity_path_rewrite_and_idempotency(service):
    server,client,run=service
    raw=png();digest=hashlib.sha256(raw).hexdigest()
    spec={'vessel_id':'upload','source':{'file':'../../private.txt'},'station_reference':{'file':'/etc/passwd'},'sections':[]}
    payload={'spec':spec,'sources':{role:{'bytes':len(raw),'sha256':digest} for role in ('primary','reference')}}
    status,_,body=client.request('/api/uploads',payload,headers={'Idempotency-Key':'streamed-submission-1'});assert status==201
    job=json.loads(body)
    status,_,again=client.request('/api/uploads',payload,headers={'Idempotency-Key':'streamed-submission-1'});assert status==200 and json.loads(again)['id']==job['id']
    assert client.request(f'/api/jobs/{job["id"]}/submit',{})[0]==409
    with patch('PIL.Image.open',side_effect=AssertionError('HTTP process must not parse uploaded images')):
        for role in ('primary','reference'):
            assert client.request(f'/api/jobs/{job["id"]}/sources/{role}',method='PUT',headers={'Content-Type':'application/octet-stream'},raw=raw)[0]==200
    status,_,body=client.request(f'/api/jobs/{job["id"]}/submit',{});assert status==202 and json.loads(body)['state']=='queued'
    stored=json.loads((server.queue.inputs/job['id']/'spec.json').read_text())
    assert stored['source']['file']=='drawing.png' and stored['station_reference']['file']=='station_reference.png'
    assert stored['source']['upload_original_sha256']==digest
    assert (server.queue.inputs/job['id']/'drawing.png').read_bytes()==raw
    assert (server.queue.inputs/job['id']/'station_reference.png').read_bytes()==raw
    assert not (server.queue.runs/job['id']).exists()
    assert client.request(f'/api/jobs/{job["id"]}/cancel',{})[0]==202


def test_hash_mismatch_length_limits_and_duplicate_json_reject(service):
    server,client,run=service
    payload={'spec':{'source':{}},'sources':{'primary':{'bytes':len(png()),'sha256':'0'*64}}}
    status,_,body=client.request('/api/uploads',payload);job=json.loads(body)
    assert client.request(f'/api/jobs/{job["id"]}/sources/primary',method='PUT',headers={'Content-Type':'application/octet-stream'},raw=png())[0]==400
    assert not list((server.queue.inputs/job['id']).glob('*.part'))
    payload['sources']['primary']['bytes']=21*1024**2
    assert client.request('/api/uploads',payload)[0]==413
    for body in [b'{"spec":{},"spec":{},"sources":{}}',b'{"spec":{"x":NaN}}',b'{"spec":{"x":1e400}}',b'{']:
        assert client.request('/api/uploads',method='POST',headers={'Content-Type':'application/json'},raw=body)[0]==400


def test_offline_snapshot_is_self_contained_without_live_session(service,tmp_path):
    server,client,run=service
    output=write_snapshot(run,tmp_path/'snapshot.html')
    html=output.read_text()
    assert 'window.__VESSEL_SNAPSHOT__=' in html and 'data:image/png;base64,' in html
    assert '<script src="/app.js"' not in html and 'href="/style.css"' not in html
    assert server.bootstrap_token not in html and client.csrf not in html
    assert 'if(SNAPSHOT){await refreshRuns();return;}' in html


def test_request_total_deadline_closes_slow_body(tmp_path):
    server=WorkbenchServer(('127.0.0.1',0),tmp_path/'artifacts',tmp_path,request_seconds=.25,queue_options={'start_worker':False,'min_free_bytes':0})
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    try:
        connection=socket.create_connection(('127.0.0.1',server.server_address[1]),timeout=2)
        request=f'POST /api/session HTTP/1.1\r\nHost: 127.0.0.1:{server.server_address[1]}\r\nContent-Type: application/json\r\nContent-Length: 100\r\n\r\n{{'.encode()
        started=time.monotonic();connection.sendall(request)
        assert connection.recv(4096)==b''
        assert time.monotonic()-started<1.5
        connection.close()
    finally:server.shutdown();server.server_close();thread.join(2)


def test_malformed_legacy_inventory_is_isolated(service):
    server,client,run=service
    for index,raw in enumerate(['{"vessel_id":NaN,"status":"review_required"}','{"vessel_id":{},"status":"review_required"}','{"vessel_id":"wrong","status":[]}']):
        bad=server.artifacts/f'bad-{index}';bad.mkdir();(bad/'result.json').write_text(raw)
    status,_,body=client.request('/api/runs')
    assert status==200
    assert [run['name'] for run in json.loads(body)['runs']]==['server-test']


def test_review_state_is_derived_separately_from_immutable_record(service,tmp_path):
    from vessel_reconstruction.review import record_review
    server,client,run=service
    before=(run/'result.json').read_bytes()
    result=json.loads(before)
    record_review(run,decision='needs_information',reviewer='Local test reviewer',notes='Need readable contours.',expected_run_id=result['run_id'])
    assert (run/'result.json').read_bytes()==before
    assert client.request(f'/api/review/{_run_id("published")}',auth=False)[0]==401
    status,_,body=client.request(f'/api/review/{_run_id("published")}')
    assert status==200 and json.loads(body)['state']=='needs_information'
    html=write_snapshot(run,tmp_path/'review-snapshot.html').read_text()
    assert '"review_state":{"state":"needs_information"' in html
    assert 'replay_spec.json' in html
