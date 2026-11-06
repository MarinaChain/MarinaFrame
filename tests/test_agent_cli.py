import json
from pathlib import Path
from vessel_reconstruction.cli import main


def test_agent_cli_routes_and_reports_unknown_task_without_traceback(tmp_path,capsys):
    assert main(['agent','verify',str(tmp_path/'missing')])==2
    assert json.loads(capsys.readouterr().out)['valid'] is False


def test_agent_cli_deterministic_block_and_resume_preserve_inputs(tmp_path,capsys):
    from test_agent_tools import drawing
    spec,_=drawing(tmp_path/'input',faint_competitor=True)
    task=tmp_path/'task'
    assert main(['agent','run',str(spec),'--out',str(task)])==2
    state=json.loads(capsys.readouterr().out)
    assert state['status']=='blocked' and state['builds']==0
    assert main(['agent','verify',str(task)])==0
    assert json.loads(capsys.readouterr().out)['valid']
    out=tmp_path/'review.html'
    assert main(['agent','review',str(task),'--out',str(out)])==0
    capsys.readouterr()
    text=out.read_text()
    assert 'Download selection decision' in text and 'Human semantic review required' in text
    assert 'min-width:0;overflow-wrap:anywhere' in text
    assert 'https://' not in text and 'http://' not in text
    choice={'tool':'exec','arguments':{'code':'write files'},'reason':'attack'}
    choice_path=tmp_path/'attack.json';choice_path.write_text(json.dumps(choice))
    assert main(['agent','step',str(task),'--decision',str(choice_path),'--actor','assistant_operator','--note','adversarial'])==2
    assert json.loads(capsys.readouterr().out)['status']=='blocked'
    assert main(['agent','verify',str(task)])==0
    assert json.loads(capsys.readouterr().out)['valid']


def test_cli_resume_provider_reserves_only_remaining_live_allowance(monkeypatch):
    from argparse import Namespace
    import threading
    from vessel_reconstruction.agent_cli import _policy
    import vessel_reconstruction.agent_provider as provider
    recorded={}
    def fake_provider(**kwargs):recorded.update(kwargs);return kwargs
    monkeypatch.setattr(provider,'OpenCodeGoAgentProvider',fake_provider)
    args=Namespace(policy='live',authorize_data_sha256='a'*64,max_live_requests=8,admission_mode='account_zero_budget')
    state={'live_request_cap':6,'live_calls_reserved':4,'live_external_prior':2}
    _policy(args,threading.Event(),state)
    assert recorded['max_requests']==2 and recorded['prior_generation_reservations']==6
