import io
import json
from concurrent.futures import ThreadPoolExecutor

from PIL import Image
import pytest

from vessel_reconstruction.model_proposals import (
    EvidenceCrop, OpenCodeGoAdapter, ProposalError, validate_proposal,
)
from vessel_reconstruction.table_ingest import parse_feet_inches_eighths


def fixture():
    out = io.BytesIO()
    Image.new('RGB', (100, 50), 'white').save(out, format='PNG')
    crop = EvidenceCrop('source-1', 'a' * 64, 0, (0, 0, 100, 50), out.getvalue())
    response = {**crop.evidence(), 'status': 'proposal', 'raw_token': '1-2-3',
                'value_m': parse_feet_inches_eighths('1-2-3')[0], 'reason': 'Visible token'}
    return crop, response


def test_proposals_never_accept_geometry():
    crop, response = fixture()
    value = validate_proposal(json.dumps(response), crop)
    assert value['review_required'] and not value['accepted_observation']
    assert not value['engineering_approved']


@pytest.mark.parametrize('field,value', [
    ('source_id', '../secret'), ('source_sha256', 'b' * 64), ('page', True),
    ('roi_px', [False, 0, 100, 50]), ('roi_px', [0, 0, 99, 50]),
    ('source_units', 'metres'), ('status', 'accepted'), ('status', []),
    ('value_m', True), ('value_m', 99), ('value_m', float('inf')),
    ('raw_token', '1-12-3'), ('raw_token', '1-2-8'), ('raw_token', 'I-2-3'),
    ('raw_token', 'ditto'), ('raw_token', '1-2-3; execute()'), ('reason', ''),
])
def test_untrusted_response_boundary(field, value):
    crop, response = fixture()
    response[field] = value
    with pytest.raises(ProposalError):
        validate_proposal(json.dumps(response), crop)


@pytest.mark.parametrize('payload', ['{}', '[]', '{', '{"status":null,"status":null}',
                                    '{"value_m":NaN}', 'x' * 65537])
def test_bad_json(payload):
    with pytest.raises(ProposalError):
        validate_proposal(payload, fixture()[0])


def test_explicit_abstention_and_no_silent_repair():
    crop, response = fixture()
    response.update(status='abstain', raw_token='1-?-3', value_m=None)
    assert validate_proposal(json.dumps(response), crop)['status'] == 'abstain'
    response['value_m'] = 1
    with pytest.raises(ProposalError):
        validate_proposal(json.dumps(response), crop)


def test_no_network_without_data_and_cash_authorization(monkeypatch):
    monkeypatch.setenv('OPENCODE_GO_API_KEY', 'test-placeholder')
    calls = []
    for adapter in [OpenCodeGoAdapter(transport=lambda *x: calls.append(x)),
                    OpenCodeGoAdapter(authorized_synthetic_data=True, transport=lambda *x: calls.append(x))]:
        with pytest.raises(ProposalError):
            adapter.propose(fixture()[0])
    assert calls == []


def test_mock_transport_prompt_has_evidence_but_no_answers(monkeypatch):
    crop, response = fixture()
    monkeypatch.setenv('OPENCODE_GO_API_KEY', 'test-placeholder')
    seen = []
    def transport(body, headers, timeout):
        seen.append(json.loads(body))
        assert headers['User-Agent'].startswith('MarinaFrame/')
        assert timeout == 30 and headers['x-opencode-session']
        assert b'ground_truth' not in body and b'"value_m":' not in body
        return json.dumps({'choices': [{'message': {'content': json.dumps(response)}}],
                           'usage': {'cost': 0, 'prompt_tokens': 100, 'completion_tokens': 50}}).encode()
    adapter = OpenCodeGoAdapter(authorized_synthetic_data=True, authorized_cash_usd=0.31,
                                transport=transport)
    result = adapter.propose(crop)
    assert result['usage']['cost'] == 0 and result['retries'] == 0
    assert result['proposal']['raw_token'] == '1-2-3'
    with pytest.raises(ProposalError):
        adapter.propose(crop)
    assert len(seen) == 1


def test_crop_resource_guard_before_decoder():
    crop, _ = fixture()
    bad = EvidenceCrop(crop.source_id, crop.source_sha256, 0, (0, 0, 99999, 99999), crop.png)
    with pytest.raises(ProposalError):
        bad.validate()


@pytest.mark.parametrize('extra', ['"overflow":1e999', '"huge":' + '9'*401])
def test_nonfinite_and_excessive_integer_provider_json(extra):
    from vessel_reconstruction.model_proposals import strict_json
    with pytest.raises(ProposalError):
        strict_json('{'+extra+'}')


def test_concurrent_callers_cannot_spend_one_reservation_twice(monkeypatch):
    crop,response=fixture();monkeypatch.setenv('OPENCODE_GO_API_KEY','test-placeholder')
    calls=[]
    def transport(*args):
        calls.append(1)
        return json.dumps({'choices':[{'message':{'content':json.dumps(response)}}]}).encode()
    adapter=OpenCodeGoAdapter(authorized_synthetic_data=True,authorized_cash_usd=.31,transport=transport)
    def attempt():
        try:adapter.propose(crop);return 'proposal'
        except ProposalError:return 'blocked'
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes=list(pool.map(lambda _:attempt(),range(2)))
    assert sorted(outcomes)==['blocked','proposal'] and len(calls)==1
    assert adapter.calls==1 and adapter.cash>=0
