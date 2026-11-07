"""Controlled current-Python/current-Rust harness comparison; no providers or evaluator labels.

All active tasks live in /tmp. The Python benchmark policy explicitly mirrors the
Rust deterministic tool order and failure behavior, including body + oblique.
The retained DomainTools/native implementation is never modified.
"""
from __future__ import annotations
import argparse,copy,datetime,fcntl,hashlib,json,os,platform,resource,shutil,signal,subprocess,sys,threading,time
from pathlib import Path

SCHEMA='marinaframe.control-parity.v1'
REPO=Path('/workspace/scratch/3b76408c5d11/marinaframe-rust')
PYTHON='/tmp/marinaframe-v04-release-env/bin/python'
RUNTIME=Path('/tmp/marinaframe-v04-runtime-8916e68')
LOCK=Path('/tmp/marinaframe-native-admission-0.lock')

def read(p):return json.loads(Path(p).read_text())
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def write(p,value):
 p=Path(p);p.parent.mkdir(parents=True,exist_ok=True);tmp=p.with_name(p.name+'.writing')
 with tmp.open('w') as f:json.dump(value,f,indent=2,allow_nan=False);f.write('\n');f.flush();os.fsync(f.fileno())
 os.replace(tmp,p)
def runtime_env(runtime):
 env={k:os.environ[k] for k in ('PATH','HOME','LANG','LC_ALL','LC_CTYPE','TZ') if k in os.environ}
 env.update(PYTHONPATH=str(Path(runtime)/'src'),PYTHONNOUSERSITE='1',PYTHONDONTWRITEBYTECODE='1')
 return env

def admission():
 fd=os.open(LOCK,os.O_RDWR|os.O_CREAT|getattr(os,'O_NOFOLLOW',0),0o600);start=time.monotonic();fcntl.flock(fd,fcntl.LOCK_EX)
 return fd,time.monotonic()-start

def release(fd):fcntl.flock(fd,fcntl.LOCK_UN);os.close(fd)

def prepare(out):
 out=Path(out);assert out.is_relative_to('/tmp');out.mkdir(parents=True,exist_ok=False)
 sources={
  'straight3':Path('/tmp/marinaframe-v04-dev4/inputs/retention/spec.json'),
  'known47_25':Path('/workspace/scratch/3b76408c5d11/vessel-reconstruction/data/generated/confirmation_v2/inference/holdout_roundflare-271097-drafting/spec.json'),
  'degraded25':Path('/workspace/scratch/3b76408c5d11/vessel-reconstruction/data/generated/confirmation_v2/inference/holdout_roundflare-271013-degraded/spec.json')}
 cases=[]
 for name,source in sources.items():
  dest=out/'inputs'/name;dest.mkdir(parents=True);spec=read(source)
  for role in ('source','station_reference'):
   if spec.get(role):
    asset=source.parent/spec[role]['file'];assert asset.is_file() and asset.resolve().is_relative_to(source.parent.resolve())
    target=dest/asset.name;shutil.copy2(asset,target);spec[role]['file']=target.name
  write(dest/'spec.json',spec)
  cases.append({'name':name,'spec':str(dest/'spec.json'),'source_spec':str(source),'source_spec_sha256':sha(source),'classification':'procedural development input; not a sealed evaluation case'})
 mixed=out/'inputs/mixed_height3';shutil.copytree(out/'inputs/straight3',mixed);spec=read(mixed/'spec.json');spec['vessel_id']='control-parity-mixed-height3'
 for section,(low,high) in zip(spec['sections'],[(.2,2.5),(0.,3.),(.4,2.8)]):section.update(z_min_m=low,z_max_m=high)
 write(mixed/'spec.json',spec);cases.append({'name':'mixed_height3','spec':str(mixed/'spec.json'),'classification':'procedural variant of straight3 with deliberately supplied unequal vertical extents; no reference geometry'})
 partial=out/'inputs/genuine_partial';partial.mkdir()
 original=REPO/'artifacts/v04/data/balclutha_frame108_preview.png';shutil.copy2(original,partial/'drawing.png')
 spec={'schema_version':'1.0','vessel_id':'balclutha-single-section-incomplete-request','units':'m','source':{'file':'drawing.png','sha256':sha(original),'url':'https://www.loc.gov/resource/hhh.ca1493.sheet/?sp=48','license':'NPS HAER public-domain basis retained in project registry'},'sections':[],'symmetry':False,'symmetry_evidence':'Not inferred from this single structural section.','end_closure':'unspecified'}
 write(partial/'spec.json',spec);cases.append({'name':'genuine_partial','spec':str(partial/'spec.json'),'source_asset':str(original),'classification':'authentic partial vessel evidence: one archival structural section; no calibrated station set supplied; expected admission refusal, no CAD timing'})
 manifest={'schema_version':SCHEMA,'created_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'cases':cases,'files':{str(p.relative_to(out/'inputs')):{'sha256':sha(p),'bytes':p.stat().st_size} for p in sorted((out/'inputs').rglob('*')) if p.is_file()},'no_evaluator_reference_or_index_read':True,'provider_calls':0}
 write(out/'cohort.json',manifest)
 protocol={'schema_version':SCHEMA,'repetitions':2,'ordering':'alternate arm order by case and repetition','cold_definition':'first fresh-process/task trial; OS and filesystem caches are not flushed; second trial is another fresh process/task','python_policy':'benchmark_rust_aligned_v1: source grammar, explicit failure abstention, body then oblique, validation then final cached validation','comparison_gate':'operation arguments and selected candidate geometry must match; otherwise report mismatch and exclude speed ratio','native_engine':'same frozen Python source + same installed dependencies; native WorkerLimits unchanged','python_controller_limits':{'max_actions':64,'max_policy_calls':64,'wall_seconds':1800,'observation_bytes':96000},'differences':'Rust adds a fresh bridge process and supervised boundary per operation, supplemental section observation derivatives, and an outer210s/180CPU/5GiB profile around unchanged native180s/120CPU/4GiB build limits. Python admission is benchmark-added around whole task, Rust admission is built in per operation. No provider/image-delivery workload.','memory':'per-process self peaks and sampled controller VmHWM; never add peaks across overlapping processes. OS wait4 CPU is whole-command accounting and must not be added to overlapping worker CPU receipts.','queue_probe':'one-second deliberate admission hold with initialization-only workload; no CAD; separate from main timings','cache_probe':'valid straight3 task copies, explicit cached validate; preserve original candidate and audit artifacts; no stale promotion','cases':[c['name'] for c in cases]}
 write(out/'protocol.json',protocol);print(json.dumps({'prepared':str(out),'cases':len(cases)}))

def python_arm(args):
 from vessel_reconstruction.agent_harness import Harness,TaskStore,HarnessLimits,digest
 from vessel_reconstruction.agent_tools import DomainTools
 stages=[]
 class TimedDomain(DomainTools):
  def execute(self,tool,arguments):
   started=time.monotonic();s0=resource.getrusage(resource.RUSAGE_SELF);c0=resource.getrusage(resource.RUSAGE_CHILDREN)
   result=super().execute(tool,arguments)
   s1=resource.getrusage(resource.RUSAGE_SELF);c1=resource.getrusage(resource.RUSAGE_CHILDREN)
   stages.append({'operation':tool,'arguments':arguments,'wall_seconds':time.monotonic()-started,'controller_cpu_seconds':s1.ru_utime+s1.ru_stime-s0.ru_utime-s0.ru_stime,'children_cpu_seconds':c1.ru_utime+c1.ru_stime-c0.ru_utime-c0.ru_stime,'controller_self_peak_rss_kib':s1.ru_maxrss,'ok':result.get('ok'),'status':result.get('status'),'cached':result.get('reused',False),'resources':result.get('resources',{})})
   return result
 class AlignedPolicy:
  kind='deterministic';supports_images=False
  def decide(self,observation,tools,images):
   d=observation['domain'];last=observation.get('last_tool_observation') or {}
   def response(tool,arguments):return {'decision':{'tool':tool,'arguments':arguments,'reason':'Named benchmark source-grammar policy aligned to Rust tool order; no model inference.'},'receipt':{'provider':'benchmark_rust_aligned_v1','live_inference':False,'observation_sha256':digest(observation)}}
   def abstain(reason):return response('finish',{'outcome':'abstain','summary':reason})
   if d.get('input_errors'):return abstain('Invalid source specification or calibration; inspect the recorded input errors.')
   if last.get('ok') is False:return abstain('Previous operation failed; preserve its evidence and require review.')
   selected={s['id'] for s in d['sections'] if s.get('selected_candidate_id')};selections=[]
   for section in last.get('sections',d.get('inspected_sections',[])):
    sid=section['section_id']
    if sid in selected:continue
    candidates=[c for c in section.get('candidates',[]) if c.get('selectable') is True]
    chosen=section.get('grid_evidence',{}).get('unique_non_grid_candidate_id') or (candidates[0]['candidate_id'] if len(candidates)==1 else None)
    if not chosen:return abstain('Multiple or no supported source interpretations; explicit review required.')
    selections.append({'section_id':sid,'candidate_id':chosen})
   if selections:return response('select_contours',{'selections':selections})
   if not d.get('catalog_ready'):return response('inspect_source',{})
   if len(selected)<len(d['sections']):return response('inspect_source',{'section_ids':[s['id'] for s in d['sections'] if s['id'] not in selected][:12]})
   if not d.get('current_candidate'):return response('build_provisional',{})
   if d['current_candidate'].get('valid') is not True:return abstain('Current native build failed.')
   for view in ('body','oblique'):
    if view not in d.get('rendered_views',[]):return response('render_candidate',{'view':view})
   if not d.get('validation'):return response('validate_candidate',{})
   return response('finish',{'outcome':'candidate_ready_for_review' if d['validation'].get('geometry_checks_passed') is True else 'abstain','summary':'Aligned deterministic sequence finished; semantic review remains required.'})
 fd,queued=admission();started=time.monotonic();creating=not args.cached
 try:
  with TaskStore(args.task,create=creating) as store:
   init=time.monotonic();domain=TimedDomain(store.path,args.spec if creating else store.path/'domain/input/spec.json');init_wall=time.monotonic()-init
   limits=HarnessLimits(max_actions=64,max_policy_calls=64,wall_seconds=1800,observation_bytes=96000,max_images_per_call=3)
   if not creating:limits=HarnessLimits(**store.events[0]['payload']['limits'])
   harness=Harness(store,domain,AlignedPolicy(),limits=limits)
   if args.initialize_only:harness._start();state=store.state
   elif args.cached:state=harness.step({'tool':'validate_candidate','arguments':{},'reason':'Explicit current-candidate cache parity probe.'},actor='assistant_operator',note='Benchmark cached validation on an intact task copy; no semantic approval.')
   else:state=harness.run()
   usage=resource.getrusage(resource.RUSAGE_SELF)
   result={'queue_wait_seconds':queued,'active_wall_seconds':time.monotonic()-started,'initialization_wall_seconds':init_wall,'controller_self_peak_rss_kib':usage.ru_maxrss,'controller_self_cpu_seconds':usage.ru_utime+usage.ru_stime,'state':{k:v for k,v in state.items() if k!='last_observation'},'stages':stages,'engineering_approved':False}
 finally:release(fd)
 write(args.metrics,result);print(json.dumps({'status':state['status'],'engineering_approved':False}))

def controller_proc(command,marker):
 expected=os.fsencode(marker)
 for path in Path('/proc').glob('[0-9]*/cmdline'):
  try:
   argv=path.read_bytes().split(b'\0')
   if expected in argv and os.fsencode(command[0])==argv[0] and (b'python-arm' in argv if command[0].endswith('python') else True):return path.parent
  except OSError:pass
 return None

def measure(command,out,env,marker,timeout=1800):
 out=Path(out);out.parent.mkdir(parents=True,exist_ok=True);started=time.monotonic();peak=None;proc_dir=None
 with out.with_suffix('.stdout').open('w') as stdout,out.with_suffix('.stderr').open('w') as stderr:
  p=subprocess.Popen(list(map(str,command)),cwd='/tmp',env=env,stdin=subprocess.DEVNULL,stdout=stdout,stderr=stderr,start_new_session=True)
  while True:
   pid,status,usage=os.wait4(p.pid,os.WNOHANG)
   if pid:break
   if proc_dir is None:proc_dir=controller_proc(command,marker)
   if proc_dir:
    try:
     for line in (proc_dir/'status').read_text().splitlines():
      if line.startswith('VmHWM:'):peak=max(peak or 0,int(line.split()[1]))
    except OSError:pass
   if time.monotonic()-started>timeout:
    os.killpg(p.pid,signal.SIGTERM);time.sleep(.5)
    try:os.killpg(p.pid,signal.SIGKILL)
    except ProcessLookupError:pass
    pid,status,usage=os.wait4(p.pid,0);break
   time.sleep(.02)
  p.returncode=os.waitstatus_to_exitcode(status)
 result={'command':list(map(str,command)),'exit_code':p.returncode,'wall_seconds':time.monotonic()-started,'whole_command_cpu_seconds_wait4':usage.ru_utime+usage.ru_stime,'os_wait4_reported_maxrss_kib':usage.ru_maxrss,'controller_sampled_self_peak_rss_kib':peak,'sampling_interval_seconds':.02,'memory_note':'VmHWM is controller process only when observed; wait4 maxrss and worker maxima are separate, never summed.'}
 write(out.with_suffix('.json'),result);return result

def summarize(task,arm,metrics):
 task=Path(task);events=[read(p) for p in sorted((task/'events').glob('*.json'))];domain=read(task/'domain/state.json');state=read(task/'state.json')['state']
 decisions=[];stages=[];bridges=[]
 for event in events:
  payload=event['payload']
  if event['kind']=='decision':
   d=copy.deepcopy(payload['decision']);d.pop('reason',None)
   if d['tool']=='finish':d['arguments'].pop('summary',None)
   decisions.append(d)
  if event['kind'] in ('worker_result','worker_reconciled'):
   response=payload['response'];observation=response.get('result') or {};stages.append({'operation':payload['operation'],'supervision':payload.get('supervision'),'ok':observation.get('ok'),'status':observation.get('status'),'cached':observation.get('reused',False),'resources':observation.get('resources',{})});bridges.append(response.get('resources',{}))
 if arm=='python':stages=read(metrics)['stages']
 profiles=[]
 for dirname in ('inspections','renders','validation'):
  for path in sorted((task/'domain'/dirname).glob('*/observation.json')):
   doc=read(path)
   if 'resources' in doc:profiles.append({'stage':dirname,'path':str(path.relative_to(task)),**doc['resources']})
 current=next((b for b in reversed(domain['builds']) if b['revision_id']=='r'+str(domain['revision']).zfill(4)),None)
 geometry=None
 if current and current.get('valid'):
  run=task/current['path'];v=domain.get('validation') or {}
  geometry={'cad_sections_sha256':sha(run/'cad_sections.json'),'mesh_sha256':sha(run/'mesh.json'),'step_sha256':sha(run/'model.step'),'metrics':current['metrics'],'actual_step_audit':v.get('geometry_audit'),'sampled_sections':v.get('sampled_sections'),'geometry_checks_passed':v.get('geometry_checks_passed'),'validation_contract':v.get('contract')}
 return {'status':state['status'],'input_errors':domain.get('input_errors'),'decisions':decisions,'decision_count':len(decisions),'native_build_count':len(domain['builds']),'stages':stages,'bridge_profiles':bridges,'native_observation_profiles':profiles,'geometry':geometry,'selection':domain['selected'],'engineering_approved':False}

def verify(task,arm,runtime,out):
 command=[str(runtime/'marinaframe'),'verify','--task',str(task)] if arm=='rust' else [PYTHON,'-c','import json,sys;from vessel_reconstruction.agent_harness import verify_task;print(json.dumps(verify_task(sys.argv[1])))',str(task)]
 p=subprocess.run(command,cwd='/tmp',env=runtime_env(runtime),capture_output=True,text=True,timeout=90)
 value=json.loads(p.stdout) if p.stdout else {'stderr':p.stderr};write(out,{'command':command,'exit_code':p.returncode,'result':value});return value

def run_study(out,runtime,repetitions=2):
 out=Path(out);runtime=Path(runtime);assert out.is_relative_to('/tmp')
 manifest=read(out/'cohort.json');script=out/'benchmark.py'
 if not script.exists():shutil.copy2(Path(__file__),script)
 cpu_model=next((line.split(':',1)[1].strip() for line in Path('/proc/cpuinfo').read_text().splitlines() if line.startswith('model name')),None)
 write(out/'runtime.json',{'binary_sha256':sha(runtime/'marinaframe'),'python':PYTHON,'python_version':sys.version,'platform':platform.platform(),'cpu_model':cpu_model,'visible_cpu_count':os.cpu_count(),'cpu_affinity_count':len(os.sched_getaffinity(0)),'cpu_max':Path('/sys/fs/cgroup/cpu.max').read_text().strip() if Path('/sys/fs/cgroup/cpu.max').exists() else None,'worker_files':{p.name:sha(p) for p in sorted((runtime/'src/vessel_reconstruction').glob('*.py'))},'benchmark_sha256':sha(script),'protocol_sha256':sha(out/'protocol.json'),'provider_calls':0})
 rows=[]
 for case_index,case in enumerate(manifest['cases']):
  for repetition in range(repetitions):
   for arm in (('python','rust') if (case_index+repetition)%2==0 else ('rust','python')):
    directory=out/'runs'/case['name']/str(repetition+1)/arm;directory.mkdir(parents=True,exist_ok=False);task=directory/'task';metrics=directory/'python-metrics.json'
    command=[PYTHON,str(script),'python-arm','--spec',case['spec'],'--task',str(task),'--metrics',str(metrics)] if arm=='python' else [str(runtime/'marinaframe'),'run','--task',str(task),'--source',case['spec'],'--worker-python',PYTHON,'--worker-source',str(runtime/'src'),'--policy','deterministic']
    print(json.dumps({'starting':case['name'],'repetition':repetition+1,'arm':arm}),flush=True)
    timing=measure(command,directory/'command',runtime_env(runtime),task)
    try:
     result=summarize(task,arm,metrics);result['verification']=verify(task,arm,runtime,directory/'verification.json')
    except Exception as exc:result={'collection_error':type(exc).__name__+':'+str(exc),'status':'collection_failed'}
    row={'case':case['name'],'repetition':repetition+1,'arm':arm,'timing':timing,'result':result,'task':str(task)};write(directory/'summary.json',row);rows.append(row);write(out/'results.json',rows)
    print(json.dumps({'completed':case['name'],'repetition':repetition+1,'arm':arm,'wall_seconds':timing['wall_seconds'],'status':result['status'],'builds':result.get('native_build_count')}),flush=True)
 return rows

def tree_identity(root):
 root=Path(root)
 return {str(p.relative_to(root)):sha(p) for p in sorted(root.rglob('*')) if p.is_file()}

def probes(out,runtime):
 out=Path(out);runtime=Path(runtime);assert out.is_relative_to('/tmp')
 rows=read(out/'results.json');script=out/'benchmark.py';results=[]
 write(out/'probe-runtime.json',{'probe_driver_sha256':sha(Path(__file__)),'python_arm_snapshot_sha256':sha(script),'binary_sha256':sha(runtime/'marinaframe'),'collection_changes':'Before probe execution, independent review added separate original-before/copy-before integrity checks and explicit queue-contention eligibility. Main timing snapshot is unchanged.'})
 # Intact copied tasks preserve both the original audit and finalization evidence.
 for arm in ('python','rust'):
  original=next((r for r in rows if r['case']=='straight3' and r['arm']==arm and r['result'].get('status')=='awaiting_human_review' and r['result'].get('verification',{}).get('valid') is True),None)
  if original is None:
   results.append({'probe':'cache','arm':arm,'status':'unavailable','reason':'No successful verified straight3 task.'});continue
  directory=out/'probes/cache'/arm;directory.mkdir(parents=True,exist_ok=False);task=directory/'task'
  original_before=tree_identity(original['task']);write(directory/'original-before.json',original_before);shutil.copytree(original['task'],task)
  before=tree_identity(task);write(directory/'before.json',before)
  if before!=original_before:raise ValueError('Cache task copy differs from its original-before inventory.')
  before_verify=verify(task,arm,runtime,directory/'verification-before.json')
  if before_verify.get('valid') is not True:raise ValueError('Copied cache task failed verification before measurement.')
  metrics=directory/'python-metrics.json'
  if arm=='python':command=[PYTHON,str(script),'python-arm','--task',str(task),'--metrics',str(metrics),'--cached']
  else:
   checkpoint=read(task/'state.json');state=checkpoint['state'];intervention=directory/'intervention.json'
   write(intervention,{'schema_version':'marinaframe.intervention.v1','task_id':state['task_id'],'expected_head_sha256':checkpoint['head_sha256'],'expected_generation_id':state['generation_id'],'expected_revision_id':state['revision_id'],'decision':{'tool':'validate_candidate','arguments':{},'reason':'Explicit current-candidate cache parity probe.'}})
   command=[str(runtime/'marinaframe'),'step','--task',str(task),'--intervention',str(intervention),'--actor','assistant_operator','--note','Benchmark cache parity on intact copied evidence; no semantic approval.']
  timing=measure(command,directory/'command',runtime_env(runtime),task);summary=summarize(task,arm,metrics);after=tree_identity(task);write(directory/'after.json',after)
  changed={p for p in before if after.get(p)!=before[p]};added={p for p in after if p not in before};audit_changed=sorted(p for p in changed|added if p.startswith('domain/validation/'));build_changed=sorted(p for p in changed|added if p.startswith('domain/builds/'))
  last=summary['stages'][-1] if summary['stages'] else {}
  audit_jobs=lambda identities:{p.split('/')[2] for p in identities if p.startswith('domain/validation/') and len(p.split('/'))>3}
  build_jobs=lambda identities:{p.split('/')[2] for p in identities if p.startswith('domain/builds/') and len(p.split('/'))>3}
  original_after=tree_identity(original['task']);write(directory/'original-after.json',original_after)
  result={'probe':'cache','arm':arm,'timing':timing,'cache_hit':last.get('cached') is True,'last_stage':last,'audit_artifact_changes':audit_changed,'native_build_artifact_changes':build_changed,'new_native_audit_jobs':len(audit_jobs(after)-audit_jobs(before)),'new_native_build_jobs':len(build_jobs(after)-build_jobs(before)),'verification':verify(task,arm,runtime,directory/'verification-after.json'),'copy_before_equals_original_before':before==original_before,'original_task_unchanged':original_after==original_before,'summary':summary}
  write(directory/'summary.json',result);results.append(result);print(json.dumps({'probe':'cache','arm':arm,'cache_hit':result['cache_hit'],'wall_seconds':timing['wall_seconds'],'native_changes':len(audit_changed)+len(build_changed)}),flush=True)
 # A bounded deliberate lock hold measures admission separately; no native job.
 source=next(c['spec'] for c in read(out/'cohort.json')['cases'] if c['name']=='straight3')
 for arm in ('python','rust'):
  directory=out/'probes/queue'/arm;directory.mkdir(parents=True,exist_ok=False);task=directory/'task';metrics=directory/'python-metrics.json'
  command=[PYTHON,str(script),'python-arm','--spec',source,'--task',str(task),'--metrics',str(metrics),'--initialize-only'] if arm=='python' else [str(runtime/'marinaframe'),'run','--task',str(task),'--source',source,'--worker-python',PYTHON,'--worker-source',str(runtime/'src'),'--policy','deterministic','--steps','0']
  fd,prior_queue=admission();released={};held=time.monotonic()
  def unlock():
   released['hold_seconds']=time.monotonic()-held;release(fd)
  timer=threading.Timer(1.,unlock);timer.start()
  try:timing=measure(command,directory/'command',runtime_env(runtime),task)
  finally:timer.join()
  summary=summarize(task,arm,metrics);wait=read(metrics)['queue_wait_seconds'] if arm=='python' else sum(s.get('supervision',{}).get('queue_wait_seconds',0.) for s in summary['stages'])
  result={'probe':'queue','arm':arm,'timing':timing,'deliberate_lock_hold_seconds':released['hold_seconds'],'benchmark_acquisition_wait_before_test_seconds':prior_queue,'reported_queue_wait_seconds':wait,'contention_observed':wait>=.05,'interpretation':'Measured admission delay; not a controller throughput comparison. Import/startup precedes admission, so a wait below50ms is inconclusive for contention.','native_build_count':summary['native_build_count'],'verification':verify(task,arm,runtime,directory/'verification.json'),'summary':summary}
  write(directory/'summary.json',result);results.append(result);print(json.dumps({'probe':'queue','arm':arm,'wait_seconds':wait,'wall_seconds':timing['wall_seconds'],'builds':summary['native_build_count']}),flush=True)
 write(out/'probe-results.json',results);return results

def main():
 p=argparse.ArgumentParser();sub=p.add_subparsers(dest='command',required=True)
 a=sub.add_parser('prepare');a.add_argument('--out',required=True,type=Path)
 a=sub.add_parser('run');a.add_argument('--out',required=True,type=Path);a.add_argument('--runtime',type=Path,default=RUNTIME);a.add_argument('--repetitions',type=int,default=2)
 a=sub.add_parser('probes');a.add_argument('--out',required=True,type=Path);a.add_argument('--runtime',type=Path,default=RUNTIME)
 a=sub.add_parser('python-arm');a.add_argument('--spec',type=Path);a.add_argument('--task',type=Path,required=True);a.add_argument('--metrics',type=Path,required=True);a.add_argument('--initialize-only',action='store_true');a.add_argument('--cached',action='store_true')
 a=p.parse_args()
 if a.command=='prepare':prepare(a.out)
 elif a.command=='python-arm':python_arm(a)
 elif a.command=='probes':probes(a.out,a.runtime)
 else:run_study(a.out,a.runtime,a.repetitions)
if __name__=='__main__':main()
