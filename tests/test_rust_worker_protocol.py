"""Cross-boundary parser regressions; no provider or native CAD calls."""
import json
import pytest

from vessel_reconstruction.rust_worker import parse_request, PROTOCOL


def valid():
    return {'protocol':PROTOCOL,'request_id':'worker-123','operation':'inspect_source',
            'arguments':{},'expected_domain_sha256':'a'*64,'expected_worker_sha256':'b'*64}


def test_strict_worker_request_has_exact_identity_and_optional_hashes():
    value=valid()
    assert parse_request(json.dumps(value))==value
    value.update(operation='initialize',expected_domain_sha256=None,expected_worker_sha256=None)
    assert parse_request(json.dumps(value))==value


@pytest.mark.parametrize('field,value',[
    ('protocol','marinaframe.worker.unknown'),('request_id','../../outside'),
    ('request_id',True),('operation','run_shell'),('arguments',[]),
    ('expected_domain_sha256',False),('expected_worker_sha256','g'*64),
    ('expected_worker_sha256','a'*63),('unrecognized',123),
])
def test_worker_rejects_malformed_or_unrecognized_fields(field,value):
    request=valid();request[field]=value
    with pytest.raises((ValueError,TypeError)):
        parse_request(json.dumps(request))


@pytest.mark.parametrize('field',list(valid()))
def test_worker_rejects_missing_required_fields(field):
    request=valid();del request[field]
    with pytest.raises(ValueError):parse_request(json.dumps(request))


@pytest.mark.parametrize('raw',[
    '{"protocol":"a","protocol":"b"}',
    '{"arguments":{"x":1,"x":2}}',
    '{"arguments":{"x":NaN}}',
    '{"arguments":{"x":1e9999}}',
])
def test_worker_rejects_duplicate_or_nonfinite_json(raw):
    with pytest.raises(ValueError):parse_request(raw)
