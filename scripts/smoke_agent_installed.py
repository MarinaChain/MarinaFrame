"""Exercise the installed agent wheel outside source imports, without a provider."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import time


def main():
    p=argparse.ArgumentParser();p.add_argument('--repo',type=Path,required=True);p.add_argument('--out',type=Path,required=True)
    a=p.parse_args();repo=a.repo.resolve();out=a.out.resolve();out.mkdir(parents=True,exist_ok=False)
    commands=[]
    def run(name,args):
        started=time.monotonic();r=subprocess.run([str(x) for x in args],cwd='/tmp',capture_output=True,text=True,timeout=240)
        (out/(name+'.txt')).write_text(r.stdout+r.stderr)
        commands.append({'name':name,'command':list(map(str,args)),'exit_code':r.returncode,'elapsed_seconds':time.monotonic()-started})
        (out/'commands.json').write_text(json.dumps(commands,indent=2)+'\n')
        if r.returncode:raise RuntimeError(name+' failed; see retained log')
        return r.stdout
    cli=[sys.executable,'-I','-m','vessel_reconstruction','agent']
    run('installed-module',[sys.executable,'-I','-c',
        'import vessel_reconstruction as v; from vessel_reconstruction import agent_cli,agent_harness,agent_provider,agent_review,agent_tools; '
        'assert v.__version__=="0.3.0"; assert "site-packages" in v.__file__; print(v.__version__,v.__file__)'])
    run('generate-source',[sys.executable,'-I',repo/'examples/make_agent_example.py','--out',out/'input'])
    state=json.loads(run('agent-run',cli+['run',out/'input/spec.json','--out',out/'task','--policy','deterministic']))
    assert state['status']=='awaiting_human_review' and state['builds']==1 and state['operator_actions']==0
    assert state['engineering_approved'] is False and state['human_semantic_review_required'] is True
    verification=json.loads(run('agent-verify',cli+['verify',out/'task']))
    assert verification['valid'] and verification['artifacts_checked']>=10
    run('agent-review',cli+['review',out/'task','--out',out/'review.html'])
    run('agent-status',cli+['status',out/'task'])
    transcript=repo/'artifacts/agentic/live/three-station/replay-transcript.json'
    if transcript.exists():
        replay=json.loads(run('exact-live-decision-replay',cli+['replay',transcript]))
        assert replay['verified'] and replay['generation_requests']==0 and replay['cad_operations_executed']==0
    result={'checks':len(commands),'all_passed':True,'provider_calls':0,'source':'installed wheel with isolated Python imports',
        'status':state['status'],'verification':verification}
    (out/'summary.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))


if __name__=='__main__':main()
