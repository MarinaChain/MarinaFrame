import hashlib
import json

import pytest

from benchmarks.proposal_experiment import freeze,evaluate,_read_confined
from vessel_reconstruction.model_proposals import ProposalError


@pytest.mark.parametrize('filename',['../outside.png','/tmp/outside.png','nested/crop.png'])
def test_dataset_escape_rejected_before_read(tmp_path,filename):
    with pytest.raises(ValueError):
        _read_confined(tmp_path,filename)


def test_symlink_rejected(tmp_path):
    (tmp_path/'target').write_bytes(b'not a source')
    (tmp_path/'crop.png').symlink_to(tmp_path/'target')
    with pytest.raises(OSError):
        _read_confined(tmp_path,'crop.png')


def test_live_requires_exact_dataset_authorization(tmp_path):
    dataset=tmp_path/'data';freeze(dataset)
    with pytest.raises(ValueError,match='exact dataset'):
        evaluate(dataset,tmp_path/'report.json',provider='live',cash=100)


def test_opaque_ids_and_path_preflight_before_any_transport(tmp_path,monkeypatch):
    dataset=tmp_path/'data';freeze(dataset)
    manifest=json.loads((dataset/'manifest.json').read_text())
    assert all(e['id'].startswith('crop-') and e['description'] not in e['id'] for e in manifest['cases'])
    manifest['cases'][-1]['file']='../outside.png'
    (dataset/'manifest.json').write_text(json.dumps(manifest))
    digest=hashlib.sha256((dataset/'manifest.json').read_bytes()).hexdigest()
    called=[]
    monkeypatch.setattr('benchmarks.proposal_experiment.OpenCodeGoAdapter.propose',lambda *a:called.append(1))
    with pytest.raises(ValueError,match='filename'):
        evaluate(dataset,tmp_path/'report.json',provider='live',cash=100,authorized_dataset_sha256=digest)
    assert not called


def test_provider_failure_retains_all_denominators_and_stops_calls(tmp_path,monkeypatch):
    dataset=tmp_path/'data';freeze(dataset)
    digest=hashlib.sha256((dataset/'manifest.json').read_bytes()).hexdigest()
    calls=[]
    def fail(*args):
        calls.append(1);raise ProposalError('Controlled mock transport failure')
    monkeypatch.setattr('benchmarks.proposal_experiment.OpenCodeGoAdapter.propose',fail)
    monkeypatch.setattr('benchmarks.proposal_experiment._read_cell',lambda *args:{'status':'ambiguous'})
    output=tmp_path/'report.json'
    totals=evaluate(dataset,output,provider='live',cash=100,authorized_dataset_sha256=digest)
    report=json.loads(output.read_text())
    assert len(calls)==1 and len(report['cases'])==13
    assert report['provider_failures_or_unattempted']==13
    assert report['live_transport_attempts']==0 and report['validated_live_responses']==0
    assert report['generalization_claim_permitted'] is False
    assert totals['model_proposal']['emitted']==0
    assert output.with_suffix('.attempts.json').is_file()
