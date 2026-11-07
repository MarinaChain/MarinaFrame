"""Acquisition boundaries with fake transport; never contact external hosts."""
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import urllib.error
import urllib.request

from PIL import Image
import pytest

spec=importlib.util.spec_from_file_location('data_acquire',Path(__file__).parents[1]/'scripts/data_acquire.py')
acq=importlib.util.module_from_spec(spec);spec.loader.exec_module(acq)


def manifest(tmp_path,url='https://source.example/public.png',**fields):
    item={'item_id':'fixture','download_url':url,'source_url':'https://source.example/page',
          'local_filename':'fixture.png','rights':{'local_processing':'owner_authorized'}}
    item.update(fields)
    path=tmp_path/'manifest.json';path.write_text(json.dumps({'schema_version':'marinaframe-acquisition-1',
                           'allowed_hosts':['source.example'],'items':[item]}))
    return path


@pytest.mark.parametrize('url',['http://source.example/public.png','https://other.example/public.png',
                                'https://user:password@source.example/public.png','https://source.example:444/a',
                                'https://source.example/a?api_key=secret','https://source.example/a#fragment'])
def test_unsafe_or_undeclared_requests_fail_before_transport(tmp_path,monkeypatch,url):
    monkeypatch.setattr(acq.urllib.request,'build_opener',lambda *a:pytest.fail('No transport for rejected manifest'))
    with pytest.raises(ValueError):acq.acquire(manifest(tmp_path,url),tmp_path/'out')
    assert not (tmp_path/'out').exists()


def test_denial_is_recorded_without_retry_or_mirror(tmp_path,monkeypatch):
    requests=[]
    class Opener:
        def open(self,request,timeout):
            requests.append(request.full_url)
            raise urllib.error.HTTPError(request.full_url,403,'Denied',{},None)
    monkeypatch.setattr(acq.urllib.request,'build_opener',lambda *a:Opener())
    result=acq.acquire(manifest(tmp_path),tmp_path/'out')
    assert len(requests)==1 and result['downloaded_items']==0
    receipt=result['receipts'][0]
    assert receipt['http_status']==403 and receipt['no_alternate_route_attempted']
    assert json.loads((tmp_path/'out/receipts.json').read_text())['receipts'][0]['status']=='http_denied_or_failed'


def transport(monkeypatch,payload):
    class Response(io.BytesIO):
        status=200;url='https://source.example/public.png'
        headers={'Content-Type':'image/png','Content-Length':str(len(payload))}
    class Opener:
        def open(self,request,timeout):return Response(payload)
    monkeypatch.setattr(acq.urllib.request,'build_opener',lambda *a:Opener())


def png():
    output=io.BytesIO();Image.new('L',(12,8),255).save(output,format='PNG');return output.getvalue()


def test_download_persists_unchanged_bytes_and_checked_header(tmp_path,monkeypatch):
    payload=png();transport(monkeypatch,payload)
    result=acq.acquire(manifest(tmp_path),tmp_path/'out')
    r=result['receipts'][0]
    assert r['status']=='downloaded' and r['sha256']==hashlib.sha256(payload).hexdigest()
    assert (r['width_px'],r['height_px'])==(12,8) and r['pixel_decode_performed'] is False
    assert (tmp_path/'out/originals/fixture.png').read_bytes()==payload


def test_expected_hash_mismatch_preserves_failure_and_never_admits_original(tmp_path,monkeypatch):
    payload=png();transport(monkeypatch,payload)
    result=acq.acquire(manifest(tmp_path,expected_sha256='0'*64),tmp_path/'out')
    r=result['receipts'][0]
    assert r['status']=='failed' and r['reason']=='Expected source hash mismatch'
    assert r['partial_sha256']==hashlib.sha256(payload).hexdigest()
    assert not (tmp_path/'out/originals/fixture.png').exists()


def test_content_length_budget_rejects_before_file_write(tmp_path,monkeypatch):
    transport(monkeypatch,png())
    result=acq.acquire(manifest(tmp_path),tmp_path/'out',max_file_bytes=1)
    assert result['downloaded_items']==0 and result['bytes_downloaded']==0
    assert not list((tmp_path/'out/originals').iterdir())


def test_redirect_cannot_cross_declared_host_boundary():
    handler=acq.DeclaredHostRedirect(['source.example'])
    request=urllib.request.Request('https://source.example/public.png')
    with pytest.raises(ValueError,match='outside'):
        handler.redirect_request(request,None,302,'redirect',{},'https://other.example/private.png')
