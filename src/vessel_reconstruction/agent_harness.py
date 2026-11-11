"""Bounded, evidence-led orchestration over the trusted reconstruction tool layer.

The policy proposes one operation. This controller owns budgets, transitions,
durable history, artifact checks and termination; policy text is never executed.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
import base64
import fcntl
import hashlib
import json
import os
import stat
import threading
import time
import uuid

from .provenance import canonical_json, write_json
from .schema import loads_bounded_json, load_bounded_json


class HarnessError(ValueError):
    pass


def digest(value):
    return hashlib.sha256(canonical_json(value)).hexdigest()


@dataclass(frozen=True)
class HarnessLimits:
    max_actions: int = 18
    max_policy_calls: int = 12
    max_builds: int = 3
    max_repeated_action: int = 2
    max_rejections: int = 3
    wall_seconds: float = 600.0
    observation_bytes: int = 48_000
    max_images_per_call: int = 2
    max_image_bytes: int = 262_144

    def __post_init__(self):
        for key in ('max_actions','max_policy_calls','max_builds','max_repeated_action','max_rejections'):
            v=getattr(self,key)
            if type(v) is not int or not 1 <= v <= 64:
                raise HarnessError(f'Invalid controller limit: {key}')
        if type(self.wall_seconds) not in (int,float) or not 0 < self.wall_seconds <= 1800:
            raise HarnessError('Wall budget must be finite and at most1800 seconds')
        if type(self.observation_bytes) is not int or not 2048 <= self.observation_bytes <= 128_000:
            raise HarnessError('Invalid observation byte budget')
        if type(self.max_images_per_call) is not int or not 0 <= self.max_images_per_call <= 3:
            raise HarnessError('Invalid image count budget')
        if type(self.max_image_bytes) is not int or not 1024 <= self.max_image_bytes <= 1_048_576:
            raise HarnessError('Invalid image byte budget')


FINISH = {'name':'finish','description':'Stop with a candidate requiring review or explicit abstention. This never approves engineering use.',
          'parameters':{'type':'object','properties':{'outcome':{'enum':['candidate_ready_for_review','abstain']},
          'summary':{'type':'string','maxLength':512}},'required':['outcome','summary'],'additionalProperties':False}}


def validate_decision(value, allowed):
    if type(value) is not dict or set(value) != {'tool','arguments','reason'}:
        raise HarnessError('Decision must contain exactly tool, arguments and reason')
    if type(value['tool']) is not str or value['tool'] not in allowed:
        raise HarnessError('Operation is not in the domain allowlist')
    if type(value['arguments']) is not dict or type(value['reason']) is not str or len(value['reason'])>512:
        raise HarnessError('Invalid action argument or rationale type/size')
    # Bounded JSON rejects duplicate keys, NaN, deep structures and huge numbers.
    loads_bounded_json(canonical_json(value),max_bytes=48_000,max_nodes=5000)
    if value['tool']=='finish':
        args=value['arguments']
        if set(args)!={'outcome','summary'} or args['outcome'] not in ('candidate_ready_for_review','abstain') or type(args['summary']) is not str or len(args['summary'])>512:
            raise HarnessError('Invalid finish arguments')
    return value


class TaskStore:
    """Append-only hash-chained events; mutable state is only a derived cache.

    The flock inode is permanent. Its existence never means work is active. A
    process must hold the OS lock. Local hashes are not external signatures.
    """
    def __init__(self, path, *, create=False):
        self.path=Path(path).absolute()
        if create:
            self.path.mkdir(parents=True,exist_ok=False,mode=0o700)
            (self.path/'events').mkdir()
        if self.path.is_symlink() or not self.path.is_dir(): raise HarnessError('Invalid task directory')
        self.fd=os.open(self.path/'controller.lock',os.O_RDWR|os.O_CREAT|getattr(os,'O_NOFOLLOW',0),0o600)
        try: fcntl.flock(self.fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:
            os.close(self.fd);raise HarnessError('Another controller owns this task')
        self.events=[];self.head=None;self.state={}
        try:
            if not stat.S_ISREG(os.fstat(self.fd).st_mode):
                raise HarnessError('Controller lock is not an ordinary file')
            self.reload()
        except Exception:
            self.close()
            raise

    def reload(self):
        events=[];head=None
        directory=self.path/'events'
        if directory.is_symlink() or not directory.is_dir(): raise HarnessError('Invalid event directory')
        inventory=sorted(directory.iterdir())
        if len(inventory)>1000: raise HarnessError('Event inventory exceeds task bounds')
        for i,p in enumerate(inventory,1):
            if p.name != f'{i:06d}.json' or p.is_symlink() or not p.is_file(): raise HarnessError('Event inventory is not contiguous or ordinary')
            event=load_bounded_json(p,max_bytes=2_000_000,max_nodes=100_000)
            checksum=event.pop('event_sha256',None)
            if event.get('sequence')!=i or event.get('previous_sha256')!=head or digest(event)!=checksum:
                raise HarnessError('Task event chain failed verification')
            if type(event.get('state_after')) is not dict: raise HarnessError('Missing state snapshot')
            event['event_sha256']=checksum;events.append(event);head=checksum
        self.events=events;self.head=head;self.state=events[-1]['state_after'].copy() if events else {}

    def append(self,kind,payload,state):
        event={'sequence':len(self.events)+1,'previous_sha256':self.head,'kind':kind,
               'time_utc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),'time_unix':time.time(),
               'payload':payload,'state_after':state.copy()}
        loads_bounded_json(canonical_json(event),max_bytes=2_000_000,max_nodes=100_000)
        event['event_sha256']=digest(event)
        target=self.path/'events'/f'{event["sequence"]:06d}.json'
        if target.exists(): raise HarnessError('An event cannot be overwritten')
        write_json(target,event)
        self.events.append(event);self.head=event['event_sha256'];self.state=state.copy()
        write_json(self.path/'state.json',{'event_sha256':self.head,'state':self.state})
        return event

    def close(self):
        if self.fd is not None:
            fcntl.flock(self.fd,fcntl.LOCK_UN);os.close(self.fd);self.fd=None

    def __enter__(self): return self
    def __exit__(self,*args): self.close()


def domain_checkpoint(domain):
    """Bind mutable domain state to each controller event, when it is on disk."""
    path=getattr(domain,'state_path',None)
    if path is None: return None
    path=Path(path)
    if path.is_symlink() or not path.is_file() or path.stat().st_size>16_000_000:
        raise HarnessError('Invalid persistent domain checkpoint')
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _safe_model_observation(value):
    """Opaque identities and measurements may reach a model; local paths may not."""
    if isinstance(value,dict):
        return {k:_safe_model_observation(v) for k,v in value.items()
                if k not in {'path','absolute_path','spec_path','source_path','output_dir','ground_truth','target_geometry','reference_volume'}}
    if isinstance(value,list): return [_safe_model_observation(v) for v in value]
    return value


def bounded_observation(observation, maximum):
    """Paginate oversized evidence without turning omitted rivals into uniqueness.

    The complete tool result stays in the event store. Candidate alternatives for
    any presented section are kept together; a size failure asks for a smaller
    inspection instead of silently selecting or dropping competing contours.
    """
    value=_safe_model_observation(observation)
    domain=value['domain'];last=value.get('last_tool_observation') or {}
    if last.get('sections'):
        domain.pop('inspected_sections',None)  # duplicate, not independent evidence
    if isinstance(last.get('artifacts'),list):
        original=last['artifacts']
        last['artifacts']=[a for a in original if a.get('model_eligible')]
        last['non_display_artifacts_in_event_store']=len(original)-len(last['artifacts'])
    current=domain.get('current_candidate');previous=domain.get('last_valid_candidate')
    if current and previous and current.get('id')==previous.get('id'):
        domain['last_valid_candidate']={'id':previous['id'],'same_as_current':True}
    if len(canonical_json(value))<=maximum:return value
    sections=domain.get('sections',[])
    ordered=sorted(sections,key=lambda s:bool(s.get('selected_candidate_id')))
    compact={k:domain.get(k) for k in ('source_manifest_sha256','generation_id','revision_id',
             'section_count','selected_count','catalog_ready','human_semantic_review_required','engineering_approved')}
    compact['sections']=ordered[:12]
    compact['section_summaries_omitted']=max(0,len(sections)-12)
    compact['inspected_sections']=[]
    compact['current_candidate']=None if not current else {k:current.get(k) for k in ('id','status','valid','generation_id','revision_id')}
    compact['validation']=None
    compact['rendered_views']=domain.get('rendered_views',[])
    value['domain']=compact
    value['last_tool_observation']={'ok':False,'status':'observation_budget',
        'error_code':'observation_too_large','complete_evidence_retained_in_event_store':True,
        'message':'Combined evidence exceeds the policy context budget. No contour alternatives are shown in this observation. Reinspect one section_id at a time, or abstain; never infer uniqueness from omitted evidence.'}
    if len(canonical_json(value))>maximum:
        raise HarnessError('Minimum task observation exceeds the configured budget')
    return value


def _artifact_bytes(task,descriptor,maximum):
    rel=descriptor.get('path')
    if type(rel) is not str or Path(rel).is_absolute() or '..' in Path(rel).parts:
        raise HarnessError('Artifact path must stay inside the task')
    path=task/rel
    if any(p.is_symlink() for p in [path,*path.parents] if p!=task.parent):
        raise HarnessError('Symlinked observation artifact refused')
    if not path.is_file() or path.stat().st_size>maximum: raise HarnessError('Observation artifact absent or too large')
    data=path.read_bytes()
    if hashlib.sha256(data).hexdigest()!=descriptor.get('sha256'): raise HarnessError('Observation artifact hash mismatch')
    return data


class Harness:
    def __init__(self,store,domain,policy,*,limits=None,cancel_event=None,authorize_data_sha256=None):
        self.store,self.domain,self.policy=store,domain,policy
        self.cancel=cancel_event or threading.Event()
        self.limits=limits or HarnessLimits()
        self.authorize_data_sha256=authorize_data_sha256
        self.schemas=domain.catalog()+[FINISH]
        self.allowed={x['name'] for x in self.schemas}

    def _start(self):
        description=self.domain.describe()
        if not self.store.events:
            self.store.append('task_created',{'domain':description,'limits':asdict(self.limits)},
                 {'schema_version':'1.0','task_id':uuid.uuid4().hex,'status':'ready','policy':getattr(self.policy,'kind','unknown'),
                  'actions':0,'policy_calls':0,'builds':0,'rejections':0,'elapsed_seconds':0.,'engineering_approved':False,
                  'human_semantic_review_required':True,'last_observation':None,'last_action_hash':None,'repeated_action':0,
                  'operator_actions':0,'domain_state_sha256':domain_checkpoint(self.domain),
                  'source_manifest_sha256':description.get('source_manifest_sha256'),
                  'live_request_cap':min(getattr(self.policy,'max_requests',self.limits.max_policy_calls),self.limits.max_policy_calls)
                      if getattr(self.policy,'kind',None)=='live' else None,
                  'live_calls_reserved':0,
                  'live_external_prior':getattr(self.policy,'prior_generation_reservations',0)
                      if getattr(self.policy,'kind',None)=='live' else 0})
        else:
            if self.store.state['status'] not in {'ready','running','paused','interrupted','provider_failed','budget_exhausted','blocked','awaiting_human_review','cancelled'}:
                raise HarnessError('Task state does not permit continuation')
            if self.store.events[0]['payload']['limits']!=asdict(self.limits):
                raise HarnessError('Resume must preserve the original task limits')
            if self.store.state.get('domain_state_sha256')!=domain_checkpoint(self.domain):
                raise HarnessError('Domain changed without a completed controller checkpoint; preserve this task and start a new task from reviewed inputs')
            if self.store.state.get('source_manifest_sha256')!=description.get('source_manifest_sha256'):
                raise HarnessError('Task source manifest changed')
            if self.store.events[-1]['kind'] in {'policy_requested','tool_started','build_reserved','decision'}:
                interrupted_elapsed=min(self.limits.wall_seconds,max(0.,time.time()-self.store.events[-1].get('time_unix',time.time())))
                self.store.append('interrupted_operation',{'prior_event':self.store.events[-1]['kind'],
                    'note':'Prior operation outcome is unknown. Its reserved calls and builds remain charged.'},
                    self.store.state|{'status':'interrupted','elapsed_seconds':self.store.state['elapsed_seconds']+interrupted_elapsed})
            kind=getattr(self.policy,'kind','unknown')
            if self.store.state['policy']!=kind:
                self.store.append('policy_changed',{'from':self.store.state['policy'],'to':kind},
                                  self.store.state|{'policy':kind})
        if getattr(self.policy,'kind',None)=='live':
            s=self.store.state.copy()
            if 'live_calls_reserved' not in s:
                s['live_calls_reserved']=sum(e['kind']=='policy_requested' and e['state_after'].get('policy')=='live'
                                            for e in self.store.events)
                s['live_external_prior']=0
                if s['live_calls_reserved']:
                    s['live_request_cap']=s['live_calls_reserved']
                    s['legacy_live_allowance_unknown']=True
            if s.get('live_request_cap') is None:
                s['live_request_cap']=min(getattr(self.policy,'max_requests',self.limits.max_policy_calls),self.limits.max_policy_calls)
                s['live_external_prior']=getattr(self.policy,'prior_generation_reservations',0)
            if s!=self.store.state:self.store.append('live_budget_initialized',{},s)
            required_prior=s['live_external_prior']+s['live_calls_reserved']
            if getattr(self.policy,'prior_generation_reservations',required_prior)<required_prior:
                raise HarnessError('Live resume must preserve previous generation reservations')
        return description

    def _terminate(self,status,reason,started,initial_elapsed):
        state=self.store.state|{'status':status,'termination_reason':reason,
                               'elapsed_seconds':initial_elapsed+time.monotonic()-started,
                               'engineering_approved':False,'human_semantic_review_required':True}
        state['domain_state_sha256']=domain_checkpoint(self.domain)
        self.store.append('terminated',{'reason':reason},state)
        return state

    def run(self):
        description=self._start()
        remaining=max(0.001,self.limits.wall_seconds-self.store.state.get('elapsed_seconds',0.))
        self._deadline_triggered=False
        def deadline():
            self._deadline_triggered=True
            self.cancel.set()
        timer=threading.Timer(remaining,deadline)
        timer.daemon=True;timer.start()
        try:
            return self._run(description)
        finally:
            timer.cancel()

    def _run(self,description):
        started=time.monotonic();elapsed=self.store.state['elapsed_seconds']
        if getattr(self.policy,'kind',None)=='live':
            required=description.get('source_manifest_sha256')
            if not required or self.authorize_data_sha256!=required:
                return self._terminate('blocked','Exact source-manifest authorization is required before live transfer',started,elapsed)
        while True:
            s=self.store.state.copy()
            s['elapsed_seconds']=elapsed+time.monotonic()-started
            if self.cancel.is_set():
                status='budget_exhausted' if self._deadline_triggered else 'cancelled'
                return self._terminate(status,'Task deadline reached' if self._deadline_triggered else 'Operator cancelled the task',started,elapsed)
            if elapsed+time.monotonic()-started>=self.limits.wall_seconds:
                return self._terminate('budget_exhausted','Task wall budget exhausted',started,elapsed)
            if s['actions']>=self.limits.max_actions or s['policy_calls']>=self.limits.max_policy_calls:
                return self._terminate('budget_exhausted','Action or policy-call budget exhausted',started,elapsed)
            if s['rejections']>=self.limits.max_rejections:
                return self._terminate('blocked','Task rejection budget is exhausted',started,elapsed)
            if getattr(self.policy,'kind',None)=='live' and s['live_calls_reserved']>=s['live_request_cap']:
                return self._terminate('budget_exhausted','Task-wide live request allowance exhausted',started,elapsed)
            observation={'task':{k:v for k,v in s.items() if k!='last_observation'},'domain':self.domain.describe(),
                         'last_tool_observation':s['last_observation'],
                         'rules':['Use only declared source evidence; no evaluator targets are available.',
                                  'Every candidate needs human semantic review. Never approve engineering use.']}
            try:model_observation=bounded_observation(observation,self.limits.observation_bytes)
            except HarnessError as exc:
                return self._terminate('blocked',str(exc),started,elapsed)
            images=[]
            if getattr(self.policy,'supports_images',False):
                descriptors=(s['last_observation'] or {}).get('artifacts',[])
                try:
                    for a in descriptors:
                        if a.get('mime_type')=='image/png' and a.get('model_eligible',False) and len(images)<self.limits.max_images_per_call:
                            data=_artifact_bytes(self.store.path,a,self.limits.max_image_bytes)
                            images.append({'artifact_id':a.get('id'),'sha256':a['sha256'],'mime_type':'image/png',
                                           'data_base64':base64.b64encode(data).decode()})
                except (OSError,HarnessError) as exc:
                    return self._terminate('blocked',str(exc),started,elapsed)
            s['policy_calls']+=1;s['status']='running'
            if getattr(self.policy,'kind',None)=='live':s['live_calls_reserved']+=1
            self.store.append('policy_requested',{'observation':model_observation,'observation_sha256':digest(model_observation),
                            'images':[{k:v for k,v in a.items() if k!='data_base64'} for a in images]},s)
            try:
                response=self.policy.decide(model_observation,self.schemas,images)
            except Exception as exc:
                receipt=getattr(exc,'receipt',None)
                code=getattr(exc,'code',None)
                self.store.append('policy_failed',{'error_type':type(exc).__name__,
                    'error_code':code if isinstance(code,str) and len(code)<=80 else None,'receipt':receipt},self.store.state)
                if self.cancel.is_set():
                    return self._terminate('budget_exhausted' if self._deadline_triggered else 'cancelled',
                                           'Policy stopped after cancellation or deadline',started,elapsed)
                return self._terminate('provider_failed',f'Policy failed ({type(exc).__name__}); no further calls made',started,elapsed)
            try:
                decision=validate_decision(response['decision'],self.allowed)
            except (KeyError,TypeError,ValueError) as exc:
                s=self.store.state.copy();s['actions']+=1;s['rejections']+=1
                s['last_observation']={'ok':False,'status':'rejected','error_code':'invalid_decision',
                    'message':'Choose one allowlisted operation with its declared JSON arguments. Code and paths are not operations.'}
                self.store.append('decision_rejected',{'error_type':type(exc).__name__,
                    'observation':s['last_observation']},s)
                if s['rejections']>=self.limits.max_rejections:
                    return self._terminate('blocked','Repeated malformed policy decisions',started,elapsed)
                continue
            action_hash=digest({'tool':decision['tool'],'arguments':decision['arguments']})
            s=self.store.state.copy();s['actions']+=1
            s['repeated_action']=s['repeated_action']+1 if s['last_action_hash']==action_hash else 1;s['last_action_hash']=action_hash
            self.store.append('decision',{'decision':decision,'receipt':response.get('receipt',{})},s)
            if self.cancel.is_set() or elapsed+time.monotonic()-started>=self.limits.wall_seconds:
                timed_out=self._deadline_triggered or elapsed+time.monotonic()-started>=self.limits.wall_seconds
                return self._terminate('budget_exhausted' if timed_out else 'cancelled',
                                       'Decision recorded; execution stopped after deadline or cancellation',started,elapsed)
            if s['repeated_action']>self.limits.max_repeated_action:
                return self._terminate('no_progress','Repeated identical operation',started,elapsed)
            if decision['tool']=='finish':
                outcome=decision['arguments']['outcome']
                if outcome=='candidate_ready_for_review':
                    check=self.domain.execute('validate_candidate',{})
                    self.store.append('final_validation',check,self.store.state|{'domain_state_sha256':domain_checkpoint(self.domain)})
                    if self.cancel.is_set() or elapsed+time.monotonic()-started>=self.limits.wall_seconds:
                        timed_out=self._deadline_triggered or elapsed+time.monotonic()-started>=self.limits.wall_seconds
                        return self._terminate('budget_exhausted' if timed_out else 'cancelled',
                                               'Final validation stopped after deadline or cancellation',started,elapsed)
                    if not check.get('ok'):
                        return self._terminate('blocked','Final deterministic validation refused the candidate',started,elapsed)
                    return self._terminate('awaiting_human_review',decision['arguments']['summary'],started,elapsed)
                return self._terminate('blocked',decision['arguments']['summary'],started,elapsed)
            if decision['tool']=='build_provisional':
                if s['builds']>=self.limits.max_builds:
                    return self._terminate('budget_exhausted','Native build budget exhausted',started,elapsed)
                s['builds']+=1
                self.store.append('build_reserved',{'build_number':s['builds']},s)
            self.store.append('tool_started',{'tool':decision['tool'],'arguments':decision['arguments']},self.store.state)
            try:
                result=self.domain.execute(decision['tool'],decision['arguments'])
                loads_bounded_json(canonical_json(result),max_bytes=1_500_000,max_nodes=80_000)
            except Exception as exc:
                result={'ok':False,'status':'tool_error','error_type':type(exc).__name__,
                        'message':'Operation rejected or failed; inspect constraints and choose another permitted action.',
                        'engineering_approved':False}
            s=self.store.state.copy();s['last_observation']=result
            s['domain_state_sha256']=domain_checkpoint(self.domain)
            s['elapsed_seconds']=elapsed+time.monotonic()-started
            if not result.get('ok',False): s['rejections']+=1
            self.store.append('tool_observed',{'tool':decision['tool'],'arguments':decision['arguments'],'observation':result},s)
            if s['rejections']>=self.limits.max_rejections:
                return self._terminate('blocked','Repeated rejected or unsuccessful operations',started,elapsed)

    def step(self, decision, *, actor, note):
        """An explicit operator action, recorded separately from model inference."""
        if actor not in {'human_operator','assistant_operator'} or not isinstance(note,str) or not 1<=len(note)<=512:
            raise HarnessError('An operator role and bounded explanation are required')
        self._start()
        decision=validate_decision(decision,self.allowed-{'finish'})
        s=self.store.state.copy()
        if self.cancel.is_set():raise HarnessError('Operator action cancelled')
        if s['elapsed_seconds']>=self.limits.wall_seconds or s['rejections']>=self.limits.max_rejections:
            raise HarnessError('Operator action cannot bypass elapsed-time or rejection budgets')
        if s['actions']>=self.limits.max_actions or (decision['tool']=='build_provisional' and s['builds']>=self.limits.max_builds):
            raise HarnessError('Operator actions cannot bypass task budgets')
        s['actions']+=1;s['operator_actions']+=1;s['status']='running'
        if decision['tool']=='build_provisional': s['builds']+=1
        self.store.append('operator_action',{'actor':actor,'identity_verified':False,'note':note,'decision':decision},s)
        self.store.append('tool_started',{'tool':decision['tool'],'arguments':decision['arguments']},s)
        started=time.monotonic()
        timer=threading.Timer(self.limits.wall_seconds-s['elapsed_seconds'],self.cancel.set)
        timer.daemon=True;timer.start()
        try:result=self.domain.execute(decision['tool'],decision['arguments'])
        finally:timer.cancel()
        status='paused'
        if s['elapsed_seconds']+time.monotonic()-started>=self.limits.wall_seconds:status='budget_exhausted'
        elif self.cancel.is_set():status='cancelled'
        s=s|{'last_observation':result,'status':status,'domain_state_sha256':domain_checkpoint(self.domain),
             'elapsed_seconds':s['elapsed_seconds']+time.monotonic()-started,'engineering_approved':False}
        if not result.get('ok'):s['rejections']+=1
        self.store.append('operator_observed',{'actor':actor,'observation':result},s)
        return s


class ScriptedPolicy:
    kind='mock'
    supports_images=False
    def __init__(self,decisions): self.decisions=iter(decisions)
    def decide(self,observation,tools,images):
        return {'decision':next(self.decisions),'receipt':{'provider':'scripted_mock','live_inference':False,
                'observation_sha256':digest(observation),'quality_claim_permitted':False}}


class DeterministicPolicy:
    """Source-grammar comparison arm. This is not model inference."""
    kind='deterministic'
    supports_images=False
    def decide(self,observation,tools,images):
        d=observation['domain'];last=observation.get('last_tool_observation') or {}
        selected={s['id'] for s in d.get('sections',[]) if s.get('selected_candidate_id')}
        sections=[s for s in last.get('sections',d.get('inspected_sections',[]))
                  if s.get('section_id',s.get('id')) not in selected]
        if last.get('error_code')=='observation_too_large':
            remaining=[s['id'] for s in d.get('sections',[]) if s['id'] not in selected]
            tool,args=('inspect_source',{'section_ids':remaining[:1]}) if remaining else (
                'finish',{'outcome':'abstain','summary':'Validation evidence exceeds the bounded policy context; explicit review is required.'})
        elif sections:
            selections=[]
            for s in sections:
                chosen=s.get('grid_evidence',{}).get('unique_non_grid_candidate_id')
                candidates=[c for c in s.get('candidates',[]) if c.get('selectable')]
                if not chosen and len(candidates)==1: chosen=candidates[0]['candidate_id']
                if not chosen:
                    tool,args='finish',{'outcome':'abstain','summary':'Source grammar did not identify a unique supported contour; operator selection is required.'}
                    break
                selections.append({'section_id':s.get('section_id',s.get('id')),'candidate_id':chosen})
            else:
                tool,args='select_contours',{'selections':selections}
        elif not d.get('catalog_ready'):
            tool,args='inspect_source',{}
        elif d.get('selected_count',0)<d.get('section_count',0):
            tool,args='inspect_source',{'section_ids':[s['id'] for s in d['sections'] if s['id'] not in selected][:12]}
        elif not d.get('current_candidate'):
            tool,args='build_provisional',{}
        elif not d.get('rendered_views'):
            tool,args='render_candidate',{'view':'oblique'}
        elif not d.get('validation'):
            tool,args='validate_candidate',{}
        else:
            tool,args='finish',{'outcome':'candidate_ready_for_review' if d['validation'].get('geometry_checks_passed',d['validation'].get('ok')) else 'abstain',
                                'summary':'Deterministic source-grammar tool sequence finished; semantic review remains required.'}
        return {'decision':{'tool':tool,'arguments':args,'reason':'Fixed source-grammar comparison policy.'},
                'receipt':{'provider':'deterministic_policy','live_inference':False,'observation_sha256':digest(observation)}}


def verify_task(path):
    try:
        with TaskStore(path) as store:
            cached=load_bounded_json(store.path/'state.json',max_bytes=2_000_000,max_nodes=100_000)
            valid=cached=={'event_sha256':store.head,'state':store.state}
            problems=[];checked=set()
            def visit(value):
                if isinstance(value,dict):
                    if {'path','sha256','mime_type'}<=set(value):
                        identity=(value['path'],value['sha256'])
                        if identity not in checked:
                            checked.add(identity)
                            try:_artifact_bytes(store.path,value,128*1024**2)
                            except (OSError,ValueError):problems.append('Artifact mismatch: '+str(value.get('id','unknown')))
                    for v in value.values():visit(v)
                elif isinstance(value,list):
                    for v in value:visit(v)
            for event in store.events:visit(event['payload'])
            state_path=store.path/'domain/state.json'
            if store.state.get('domain_state_sha256') is not None and not state_path.is_file():
                problems.append('Required domain checkpoint is missing')
            if state_path.exists():
                from .agent_tools import DomainTools
                domain=DomainTools(store.path,store.path/'domain/input/spec.json')
                if domain_checkpoint(domain)!=store.state.get('domain_state_sha256'):problems.append('Domain checkpoint mismatch')
                from .run_record import verify_run
                for candidate in domain.state['builds']:
                    if candidate.get('valid') and not verify_run(store.path/candidate['path']).get('valid'):
                        problems.append('Candidate immutable run failed verification')
            return {'valid':valid and not problems,'problems':problems,'artifacts_checked':len(checked),
                    'events':len(store.events),'head_sha256':store.head,
                    'status':store.state.get('status'),'engineering_approved':False,
                    'assurance':'Local event, source, observed artifact and candidate-run integrity; no external authenticity or engineering approval.'}
    except (OSError,ValueError,KeyError,TypeError) as exc:
        return {'valid':False,'error_type':type(exc).__name__,'engineering_approved':False}
