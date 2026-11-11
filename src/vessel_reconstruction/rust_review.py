"""Verified Rust task review and an optional authenticated loopback operator UI.

Rust remains the authority for state, interventions and native work. This module
never imports or invokes the Python Harness. The configured task and controller
are trusted launch arguments; HTTP clients cannot supply paths or commands.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import html
import json
import os
from pathlib import Path
import secrets
import signal
import subprocess
import sys
import tempfile
import threading
import time

from .provenance import digest_file, safe_relative_file
from .schema import load_bounded_json, loads_bounded_json

MAX_HTTP = 65536
MAX_IMAGES = 72
MAX_IMAGE_BYTES = 8 * 1024**2
MAX_TOTAL_IMAGES = 32 * 1024**2
COOKIE = 'marinaframe_rust_review'
UI_TOOLS = {'inspect_source', 'select_contours', 'build_provisional', 'render_candidate', 'validate_candidate'}


class ReviewError(ValueError):
    pass


def encode(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(',', ':'))


def escaped(value):
    return html.escape(str(value), quote=True)


def token_matches(candidate, expected):
    """Credentials are opaque ASCII; malformed Unicode is a controlled refusal."""
    if type(candidate) is not str or not candidate.isascii():
        return False
    return hmac.compare_digest(candidate, expected)


def _run_cli(controller, arguments, *, timeout=300):
    """Run one fixed Rust command without a shell; kill its process group on timeout."""
    controller = Path(controller).absolute()
    if not controller.is_file() or controller.is_symlink():
        raise ReviewError('controller_missing_or_symlink')
    # Output is spooled to bounded-on-read temporary files; the trusted Rust CLI
    # prints one summary. Native worker output has its own Rust supervision caps.
    with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
        process = subprocess.Popen([str(controller), *map(str, arguments)], stdin=subprocess.DEVNULL,
                                   stdout=stdout, stderr=stderr, start_new_session=True)
        try:
            process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL); process.wait(timeout=5)
            raise ReviewError('controller_timeout_preserve_pending_task')
        stdout.seek(0); stderr.seek(0)
        raw = stdout.read(262145) if process.returncode == 0 else stderr.read(65537)
        if len(raw) > (262144 if process.returncode == 0 else 65536):
            raise ReviewError('controller_response_limit')
        try:
            result = loads_bounded_json(raw, max_bytes=262144, max_nodes=30000)
        except (ValueError, TypeError):
            raise ReviewError('controller_response_invalid')
        if type(result) is not dict:
            raise ReviewError('controller_response_invalid')
        if process.returncode != 0:
            code = result.get('error_code', 'controller_refused')
            raise ReviewError(code if type(code) is str and len(code) <= 180 else 'controller_refused')
        return result


def snapshot(task, controller, *, runner=_run_cli):
    """Read a head-bound, Rust-verified display snapshot with exact artifact bytes."""
    task = Path(task).absolute()
    if not task.is_dir() or task.is_symlink():
        raise ReviewError('invalid_task_root')
    before = runner(controller, ['verify', '--task', task])
    if before.get('valid') is not True or before.get('pending_domain_requires_reconciliation') is True:
        raise ReviewError('task_requires_verification_or_reconciliation')
    wrapper = load_bounded_json(safe_relative_file(task, 'state.json'), max_bytes=2*1024**2, max_nodes=180000)
    state = wrapper.get('state')
    if type(state) is not dict or wrapper.get('head_sha256') != before.get('head_sha256'):
        raise ReviewError('task_changed_during_review')
    domain_file = safe_relative_file(task, 'domain/state.json')
    if digest_file(domain_file) != state.get('domain_checkpoint_sha256'):
        raise ReviewError('domain_checkpoint_changed')
    domain = load_bounded_json(domain_file, max_bytes=24*1024**2, max_nodes=600000)
    event_paths = sorted((task/'events').glob('*.json'))
    if len(event_paths) != before.get('events') or len(event_paths) > 1000:
        raise ReviewError('event_inventory_changed')
    events, images, total_event_bytes = [], {}, 0
    for path in event_paths:
        safe_relative_file(task, path.relative_to(task).as_posix())
        total_event_bytes += path.stat().st_size
        if total_event_bytes > 96*1024**2:
            raise ReviewError('review_event_budget')
        event = load_bounded_json(path, max_bytes=2*1024**2, max_nodes=180000)
        events.append(event)
        payload = event.get('payload', {})
        observation = payload.get('response', {}).get('result', {}) if type(payload.get('response')) is dict else {}
        rendered_generation = observation.get('rendered_generation_id', event['state_after'].get('generation_id'))
        rendered_revision = observation.get('rendered_revision_id', event['state_after'].get('revision_id'))
        def collect(value):
            if type(value) is dict:
                if value.get('mime_type') == 'image/png' and {'path','sha256','id','bytes','kind'} <= set(value):
                    if value.get('model_eligible') is not True and value.get('kind') != 'model_observation':
                        key = (value['path'], value['sha256'])
                        if len(images) < 512 or key in images:
                            candidate = 'step_' in value['kind']
                            fresh = (rendered_generation == state.get('generation_id') and rendered_revision == state.get('revision_id'))
                            images[key] = {**value, 'sequence':event['sequence'],
                                'generation_id':rendered_generation if candidate else None,
                                'revision_id':rendered_revision if candidate else None,
                                'freshness':('current_candidate' if fresh else 'preserved_older_candidate') if candidate else 'captured_source'}
                for child in value.values(): collect(child)
            elif type(value) is list:
                for child in value: collect(child)
        collect(payload)
    figures, total = [], 0
    ordered = sorted(images.values(), key=lambda image:(image['freshness']=='preserved_older_candidate', -image['sequence']))
    for image in ordered:
        file = safe_relative_file(task, image['path'])
        size = file.stat().st_size
        if type(image['bytes']) is not int or image['bytes'] != size or size > MAX_IMAGE_BYTES:
            raise ReviewError('artifact_byte_contract')
        if digest_file(file) != image['sha256'] or image['id'] != 'artifact-'+image['sha256'][:24]:
            raise ReviewError('artifact_hash_changed')
        if len(figures) >= MAX_IMAGES or total+size > MAX_TOTAL_IMAGES:
            continue
        raw = file.read_bytes()
        if not raw.startswith(b'\x89PNG\r\n\x1a\n') or hashlib.sha256(raw).hexdigest() != image['sha256']:
            raise ReviewError('image_bytes_changed_or_not_png')
        total += size
        figures.append({**image, 'src':'data:image/png;base64,'+base64.b64encode(raw).decode()})
    after = runner(controller, ['verify', '--task', task])
    if after.get('valid') is not True or after.get('head_sha256') != before['head_sha256']:
        raise ReviewError('task_changed_during_review')
    # Recheck checkpoint after image reading, even if a different domain caller
    # changed it without committing a new Rust event.
    if digest_file(domain_file) != state['domain_checkpoint_sha256']:
        raise ReviewError('domain_checkpoint_changed')
    sections = []
    for sid, entry in domain.get('catalog', {}).items():
        sections.append({'id':sid, 'selected':domain.get('selected', {}).get(sid),
            'x_m':entry.get('x_m'), 'candidates':[
                {'id':c['candidate_id'], 'hypothesis':c.get('hypothesis','source alternative'),
                 'selectable':c.get('selectable') is True} for c in entry.get('candidates', [])]})
    history = []
    for event in events:
        payload = event.get('payload', {})
        decision = payload.get('decision', {})
        history.append({'sequence':event['sequence'],'kind':event['kind'],
            'actor':payload.get('actor'), 'tool':decision.get('tool',payload.get('operation')),
            'reason':decision.get('reason',payload.get('reason','')),
            'status':event['state_after'].get('status')})
    candidate = state.get('domain', {}).get('current_candidate')
    validation = domain.get('validation')
    current_validation = validation if (type(validation) is dict and validation.get('generation_id') == state.get('generation_id') and validation.get('revision_id') == state.get('revision_id')) else None
    return {'schema_version':'marinaframe.rust-review.v1','task_id':state['task_id'],
        'status':state['status'],'termination_reason':state.get('termination_reason'),
        'policy':state['config']['policy'],'model':state['config'].get('model'),
        'binding':{'schema_version':'marinaframe.intervention.v1','task_id':state['task_id'],
                   'expected_head_sha256':before['head_sha256'],'expected_generation_id':state['generation_id'],
                   'expected_revision_id':state['revision_id']},
        'generation_id':state['generation_id'],'revision_id':state['revision_id'],
        'source_manifest_sha256':state['source_manifest_sha256'],'counters':state['counters'],
        'candidate':candidate,'last_valid_candidate':domain.get('last_valid_candidate'),
        'validation':current_validation,'sections':sections,'history':history,'figures':figures,
        'image_inventory':len(images),'images_embedded':len(figures),'embedded_image_bytes':total,
        'cancel_requested':(task/'cancel.request').exists(),'verification':after,
        'engineering_approved':False,'professional_identity_authenticated':False}


STYLE = '''
:root{font:15px/1.55 system-ui,sans-serif;color:#173443;background:#edf2f4}*{box-sizing:border-box}body{margin:0}header{background:#102d3b;color:white;padding:28px max(22px,calc((100vw - 1240px)/2))}header small{color:#8cd8cc;letter-spacing:.13em}h1{font-size:33px;line-height:1.2;margin:8px 0}header p{max-width:850px;color:#d7e6ea;margin:8px 0}nav{display:flex;gap:22px;flex-wrap:wrap;margin-top:15px}a{color:#087184}header a{color:#aee6da}main{max-width:1280px;margin:auto;padding:22px}.notice{padding:14px 18px;border:1px solid #d4ad4e;background:#fff4d8;border-radius:7px}.metrics{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin:18px 0}.metric,.card,fieldset,figure{background:white;border:1px solid #cbdce3;border-radius:8px;padding:16px;min-width:0}.metric b{font-size:22px;display:block}.metric span{color:#4b6774;font-size:13px}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:16px}.hero{display:grid;grid-template-columns:1fr 1fr;gap:16px}figure{margin:0}figure img{width:100%;height:300px;object-fit:contain;background:#fff;cursor:zoom-in}dialog{max-width:95vw;max-height:95vh;border:1px solid #aac2ce;border-radius:8px;padding:16px}dialog::backdrop{background:#102d3bcc}.zoom-scroll{max-width:90vw;max-height:78vh;overflow:auto}.zoom-scroll img{max-width:none;max-height:none;width:auto;height:auto}.hero img{height:350px}figcaption{font-size:13px;margin-top:8px}figcaption small{display:block;color:#536e7a;font-size:10px;overflow-wrap:anywhere}section{margin:28px 0}h2{font-size:23px;line-height:1.2;margin:0 0 14px}h3{font-size:17px;margin:3px 0 12px}.badge{display:inline-block;border-radius:20px;padding:2px 9px;background:#e2f2ed;font-size:12px;font-weight:650;color:#155349}.old{background:#fff0d8;color:#81520d}.choice{display:flex;gap:9px;align-items:flex-start;border-top:1px solid #e2eaed;padding:12px 0}.choice input{margin-top:5px}.choice span{overflow-wrap:anywhere}.choice small{display:block;font-size:11px;color:#56717b}legend{font-weight:700}button,select,input[type=text]{font:inherit;border-radius:6px;border:1px solid #b5cdd6;padding:10px 14px}button{background:#0b6f7a;color:white;border-color:#0b6f7a;cursor:pointer}button.secondary{background:white;color:#174856}button.danger{background:#8d3b32;border-color:#8d3b32}button:disabled{opacity:.45;cursor:not-allowed}button:focus-visible,a:focus-visible,input:focus-visible,summary:focus-visible,select:focus-visible{outline:3px solid #eb9b2d;outline-offset:3px}.actions{display:flex;gap:10px;flex-wrap:wrap;margin:14px 0;align-items:center}#action-status{padding:12px;background:#e8f2f3;min-height:48px;border-radius:6px;white-space:pre-wrap}label.note{display:block;margin:12px 0}label.note input{width:100%;max-width:850px;background:white}.table{overflow:auto}table{border-collapse:collapse;width:100%;background:white;font-size:13px}td,th{text-align:left;border:1px solid #d3e1e6;padding:9px;vertical-align:top}small,code{overflow-wrap:anywhere}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#143543;color:#e7f3f4;padding:16px;border-radius:7px;font-size:12px}details{margin:12px 0}summary{cursor:pointer;font-weight:650}.facts{display:flex;gap:18px;flex-wrap:wrap;color:#b9d7df;font-size:13px}.subtle{color:#54707d}.older{display:none}body.show-older .older{display:block}@media(max-width:760px){header{padding:24px 16px}h1{font-size:27px}main{padding:16px}.hero{grid-template-columns:1fr}.metrics{grid-template-columns:1fr 1fr}.grid{grid-template-columns:1fr}.hero img{height:280px}.actions button{flex-grow:1}}
/* The main comparison retains its explicitly labelled older candidate while a
   new selection is awaiting a render; the optional history stays collapsed. */
.hero .older{display:block}
'''

SCRIPT = r'''
const config=JSON.parse(document.getElementById('review-config').textContent);
const status=document.getElementById('action-status');
const zoom=document.getElementById('image-zoom');
for(const image of document.querySelectorAll('figure img')){const open=()=>{document.getElementById('zoom-image').src=image.src;document.getElementById('zoom-image').alt=image.alt;zoom.showModal();};image.addEventListener('click',open);image.addEventListener('keydown',event=>{if(event.key==='Enter'||event.key===' '){event.preventDefault();open();}});}
document.getElementById('close-zoom').addEventListener('click',()=>zoom.close());
let busy=false;
function chosen(){return [...document.querySelectorAll('fieldset[data-section]')].flatMap(f=>{const c=f.querySelector('input:checked');return c?[{section_id:f.dataset.section,candidate_id:c.value}]:[]})}
function intervention(tool,args){return {...config.binding,decision:{tool,arguments:args,reason:'Explicit operator action from reviewed source evidence; semantic review remains required.'}}}
function setBusy(value){busy=value;document.querySelectorAll('[data-mutation]').forEach(b=>b.disabled=value||!config.actions);}
async function send(operation,extra={}){
 if(!config.actions){status.textContent='This is a read-only review. Download an intervention for the configured Rust CLI.';return;}
 if(busy&&operation!=='cancel')return;
 const note=document.getElementById('operator-note').value.trim();
 if(operation!=='cancel'&&!note){status.textContent='Describe the source evidence or reason for this operator action.';return;}
 try{
  const r=await fetch('/api/action',{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':config.csrf},body:JSON.stringify({operation,note,...extra})});
  const data=await r.json();if(!r.ok)throw Error(data.error_code||'action_refused');
  if(operation==='cancel'){status.textContent='Cancellation requested. Existing work and receipts remain preserved.';return;}
  setBusy(true);status.textContent='Rust controller is running this operator action. You can request cancellation.';
  async function poll(){try{const response=await fetch('/api/job',{cache:'no-store'});const job=await response.json();if(job.id!==data.job_id)throw Error('job_identity_changed');if(job.status==='running'){setTimeout(poll,800);return;}setBusy(false);if(job.status==='failed'){status.textContent='Rust refused or stopped the action: '+job.error_code+'. Refresh the review before another edit.';return;}status.textContent='Action recorded. Loading current evidence…';location.reload();}catch(error){setBusy(false);status.textContent=error.message;}}
  poll();
 }catch(error){setBusy(false);status.textContent='Action was not started: '+error.message;}
}
document.getElementById('download').addEventListener('click',()=>{const selections=chosen();if(!selections.length){status.textContent='Select at least one inspected contour.';return;}const blob=new Blob([JSON.stringify(intervention('select_contours',{selections}),null,2)+'\n'],{type:'application/json'});const a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download='marinaframe-intervention.json';a.click();setTimeout(()=>URL.revokeObjectURL(a.href),500);status.textContent='Downloaded a decision bound to this task, revision, generation and event head. Rust will reject it after the task changes.';});
document.getElementById('apply').addEventListener('click',()=>send('intervene',{intervention:intervention('select_contours',{selections:chosen()})}));
for(const [id,tool] of [['build','build_provisional'],['validate','validate_candidate'],['inspect','inspect_source']])document.getElementById(id).addEventListener('click',()=>send('intervene',{intervention:intervention(tool,{})}));
document.getElementById('render').addEventListener('click',()=>send('intervene',{intervention:intervention('render_candidate',{view:document.getElementById('view').value})}));
document.getElementById('resume').addEventListener('click',()=>send('resume',{steps:8,clear_cancel:document.getElementById('clear-cancel').checked,binding:config.binding}));
document.getElementById('cancel').addEventListener('click',()=>send('cancel'));
document.getElementById('show-older').addEventListener('change',e=>document.body.classList.toggle('show-older',e.target.checked));
document.getElementById('refresh').addEventListener('click',()=>location.reload());
setBusy(false);
'''


def render_html(view, *, actions=False, csrf='', actor='human_operator'):
    actions = bool(actions and view['policy'] == 'deterministic')
    nonce = secrets.token_urlsafe(24)
    def figure(a):
        title=' · '.join(str(a[k]).replace('_',' ') for k in ('kind','section_id','view') if a.get(k))
        older=a['freshness']=='preserved_older_candidate'
        label='Preserved older candidate' if older else ('Current candidate' if a['freshness']=='current_candidate' else 'Captured source')
        return '<figure class="'+('older' if older else '')+'"><img tabindex="0" role="button" aria-label="Open source or STEP evidence at full resolution" alt="'+escaped(title)+'" src="'+a['src']+'"><figcaption><span class="badge '+('old' if older else '')+'">'+label+'</span> '+escaped(title)+'<small>'+escaped(a.get('revision_id') or '')+' · SHA-256 '+a['sha256']+'</small></figcaption></figure>'
    source=next((a for a in view['figures'] if a['kind']=='source_page'),None)
    cad=next((a for a in view['figures'] if a['kind']=='step_reimport_render' and a.get('view')=='oblique' and a['freshness']=='current_candidate'),None)
    if cad is None:cad=next((a for a in view['figures'] if a['kind']=='step_reimport_render'),None)
    hero=(figure(source) if source else '<div class="card"><h3>Source inspection pending</h3><p>Use Inspect next stations to collect source evidence.</p></div>')+(figure(cad) if cad else '<div class="card"><h3>STEP view pending</h3><p>Build and render a provisional candidate to inspect its actual exported geometry.</p></div>')
    sections=[]
    for section in view['sections']:
        choices=[]
        for c in section['candidates']:
            choices.append('<label class="choice"><input type="radio" name="station-'+escaped(section['id'])+'" value="'+escaped(c['id'])+'" '+('checked ' if c['id']==section['selected'] else '')+('' if c['selectable'] else 'disabled ')+
                '><span><b>'+escaped(c['hypothesis'].replace('_',' '))+'</b><small>'+escaped(c['id'])+'</small></span></label>')
        sections.append('<fieldset data-section="'+escaped(section['id'])+'"><legend>'+escaped(section['id'])+' · x='+escaped(section['x_m'])+' m</legend>'+''.join(choices)+'</fieldset>')
    contract=(view.get('validation') or {}).get('contract') or {}
    checks=contract.get('checks',{})
    validation_text='Not checked for this revision' if not contract else ' / '.join(k.replace('_',' ')+': '+str(v) for k,v in checks.items())
    counters=view['counters'];candidate=view.get('candidate') or {};metrics=candidate.get('metrics') or {}
    measurements=' · '.join(key.replace('_m','').capitalize()+': '+format(float(metrics[key]),'.3f')+' m' for key in ('length_m','beam_m','depth_m') if type(metrics.get(key)) in (int,float))
    history=''.join('<tr><td>'+str(e['sequence'])+'</td><td>'+escaped(e['kind'])+'</td><td>'+escaped(e.get('actor') or e.get('tool') or '')+'</td><td>'+escaped(e.get('reason') or e.get('status') or '')+'</td></tr>' for e in reversed(view['history']))
    config={'binding':view['binding'],'actions':actions,'csrf':csrf,'actor':actor}
    config_json=encode(config).replace('<',chr(92)+'u003c').replace('>',chr(92)+'u003e').replace('&',chr(92)+'u0026')
    all_images=''.join(figure(a) for a in view['figures'] if a is not source and a is not cad)
    mode='Local operator controls · '+actor if actions else 'Read-only evidence snapshot · intervention download available'
    cost='No provider requests' if counters['requests_intended']==0 else (str(counters['requests_completed'])+' completed / '+str(counters['requests_unknown'])+' unknown / '+str(counters['requests_failed'])+' failed')
    body='<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="Content-Security-Policy" content="default-src \'none\'; img-src data:; style-src \'unsafe-inline\'; script-src \'nonce-'+nonce+'\'; connect-src \'self\'; base-uri \'none\'; form-action \'none\'"><title>MarinaFrame · Rust task review</title><style>'+STYLE+'</style></head><body><header><small>MARINAFRAME / RUST TASK REVIEW</small><h1>Inspect a provisional vessel</h1><p>Compare source pixels, preserved contour choices and views of the exported STEP. Each revision keeps its evidence and remaining review obligations.</p><div class="facts"><span>'+escaped(view['task_id'])+'</span><span>'+escaped(view['revision_id'])+'</span><span>'+escaped(mode)+'</span></div><nav><a href="#evidence">Evidence</a><a href="#selection">Revise contours</a><a href="#checks">Checks</a><a href="#history">History</a></nav></header><main>'
    body+='<div class="notice"><b>Engineering approval: not granted.</b> Source interpretation still requires human review. File consistency and geometric checks do not establish real-vessel accuracy.</div><div class="metrics"><div class="metric"><span>Task status</span><b id="task-status">'+escaped(view['status'].replace('_',' '))+'</b></div><div class="metric"><span>Current revision</span><b>'+escaped(view['revision_id'])+'</b></div><div class="metric"><span>Builds / operator actions</span><b>'+str(counters['builds'])+' / '+str(counters['operator_actions'])+'</b></div><div class="metric"><span>Policy</span><b>'+escaped(view['policy'])+'</b></div></div>'
    if view.get('termination_reason'):body+='<p class="subtle">'+escaped(view['termination_reason'])+'</p>'
    if view['cancel_requested']:body+='<p class="notice"><b>Cancellation requested.</b> Clear the request explicitly when resuming.</p>'
    body+='<section id="evidence"><h2>Drawing and exported geometry</h2><p>'+escaped(measurements)+'</p><div class="hero">'+hero+'</div><details><summary>Source overlays, section checks and additional views ('+str(view['images_embedded'])+' images)</summary><p><label><input id="show-older" type="checkbox"> Show preserved older candidate images</label></p><p class="subtle">Displaying '+str(view['images_embedded'])+' of '+str(view['image_inventory'])+' recorded images. '+('The display is bounded; consult remaining task evidence before editing omitted stations.' if view['images_embedded']<view['image_inventory'] else 'All recorded display images are included.')+'</p><div class="grid">'+all_images+'</div></details></section>'
    body+='<section id="selection"><h2>Review and revise source contours</h2><p>Select an inspected alternative. Apply records an operator intervention; rebuild, render and validate create new candidate evidence. Older valid candidates remain available for comparison.</p><div class="grid">'+(''.join(sections) or '<p>No inspected contour alternatives yet.</p>')+'</div><label class="note">Reason for this operator action<input id="operator-note" type="text" maxlength="512" placeholder="Describe the source evidence or correction"></label><div class="actions"><button id="apply" data-mutation>Apply selections</button><button id="download" class="secondary">Download intervention</button><button id="inspect" class="secondary" data-mutation>Inspect next stations</button></div><div class="actions"><button id="build" data-mutation>Rebuild candidate</button><select id="view" aria-label="STEP view"><option>oblique</option><option>body</option><option>plan</option><option>profile</option></select><button id="render" data-mutation>Render STEP view</button><button id="validate" data-mutation>Validate candidate</button></div><div class="actions"><button id="resume" data-mutation>Resume deterministic workflow</button><label><input id="clear-cancel" type="checkbox"> Clear cancellation when resuming</label><button id="cancel" class="danger" '+('' if actions else 'disabled')+'>Cancel task</button><button id="refresh" class="secondary">Refresh evidence</button></div><p id="action-status" role="status" aria-live="polite">'+('Actions run through the Rust controller. Operator identity is a declared role, not authenticated professional approval.' if actions else 'This view cannot run mutations. Use the downloaded intervention with the Rust CLI. Live provider tasks are read-only in this UI.')+'</p></section>'
    body+='<section id="checks"><h2>Validation and source identity</h2><div class="card"><h3>'+escaped(validation_text)+'</h3><p>'+escaped(cost)+'</p><p>Prompt tokens: '+str(counters['prompt_tokens'])+' · Completion tokens: '+str(counters['completion_tokens'])+' · Receipts without known cost: '+str(counters['requests_without_cost'])+'</p><p>Current generation: <code>'+escaped(view['generation_id'])+'</code></p><p>Source manifest: <code>'+view['source_manifest_sha256']+'</code></p><p>Event head: <code>'+view['binding']['expected_head_sha256']+'</code></p><details><summary>Complete current validation contract</summary><pre>'+escaped(json.dumps(contract,indent=2))+'</pre></details></div></section><section id="history"><h2>Recorded decisions and operations</h2><div class="table"><table><thead><tr><th>Event</th><th>Kind</th><th>Actor / operation</th><th>Observation</th></tr></thead><tbody>'+history+'</tbody></table></div></section></main><dialog id="image-zoom"><button id="close-zoom">Close full-resolution view</button><p>Scroll to inspect the original displayed pixels.</p><div class="zoom-scroll"><img id="zoom-image" alt=""></div></dialog><script id="review-config" type="application/json">'+config_json+'</script><script nonce="'+nonce+'">'+SCRIPT+'</script></body></html>'
    return body


def write_review(task, controller, output):
    view=snapshot(task,controller)
    output=Path(output);output.parent.mkdir(parents=True,exist_ok=True)
    with output.open('x',encoding='utf-8') as handle:handle.write(render_html(view))
    return {'file':str(output),'sha256':digest_file(output),'task_id':view['task_id'],
            'head_sha256':view['binding']['expected_head_sha256'],'images':view['images_embedded'],
            'engineering_approved':False}


class ReviewServer(ThreadingHTTPServer):
    daemon_threads=True
    allow_reuse_address=True
    def __init__(self,address,task,controller,*,allow_actions=False,actor='human_operator',runner=_run_cli):
        if address[0] != '127.0.0.1':raise ReviewError('loopback_binding_required')
        if actor not in {'human_operator','assistant_operator'}:raise ReviewError('invalid_actor')
        self.task=Path(task).absolute();self.controller=Path(controller).absolute();self.runner=runner
        self.allow_actions=allow_actions;self.actor=actor;self.action_policy=None;self.sessions={};self.session_lock=threading.Lock()
        self.bootstrap=secrets.token_urlsafe(32);self.bootstrap_expires=time.monotonic()+600;self.bootstrap_used=False
        self.job_lock=threading.Lock();self.job={'id':None,'status':'idle'};self.job_state_lock=threading.Lock()
        self.connections=threading.BoundedSemaphore(12)
        super().__init__(address,ReviewHandler)
        self.authority=f'127.0.0.1:{self.server_address[1]}';self.origin='http://'+self.authority
        self.login_url=self.origin+'/#session='+self.bootstrap
    def get_request(self):
        connection,address=super().get_request();connection.settimeout(20);return connection,address
    def process_request(self,request,client_address):
        if not self.connections.acquire(blocking=False):self.shutdown_request(request);return
        try:super().process_request(request,client_address)
        except BaseException:self.connections.release();raise
    def process_request_thread(self,request,client_address):
        try:super().process_request_thread(request,client_address)
        finally:self.connections.release()
    def read_view(self):
        view=snapshot(self.task,self.controller,runner=self.runner)
        if self.action_policy is None:self.action_policy=view['policy']
        return view
    def action(self,body):
        if not self.allow_actions:raise ReviewError('read_only_session')
        if self.action_policy is None:self.read_view()
        if self.action_policy!='deterministic':raise ReviewError('live_task_mutations_require_explicit_cli')
        if type(body) is not dict or type(body.get('note')) is not str or len(body['note'])>512:raise ReviewError('invalid_action_note')
        operation=body.get('operation')
        if operation=='cancel':
            if set(body)!={'operation','note'}:raise ReviewError('unknown_action_fields')
            return self.runner(self.controller,['cancel','--task',self.task],timeout=10)
        if not body['note'].strip():raise ReviewError('operator_note_required')
        if not self.job_lock.acquire(blocking=False):raise ReviewError('operator_action_already_running')
        try:
            view=self.read_view()
            if view['policy']!='deterministic':raise ReviewError('live_task_mutations_require_explicit_cli')
            if operation=='intervene':
                if set(body)!={'operation','note','intervention'}:raise ReviewError('unknown_action_fields')
                intervention=body['intervention']
                if type(intervention) is not dict or set(intervention)!=set(view['binding'])|{'decision'}:raise ReviewError('invalid_intervention_fields')
                if any(intervention[k]!=v for k,v in view['binding'].items()):raise ReviewError('stale_or_foreign_intervention')
                decision=intervention['decision']
                if type(decision) is not dict or set(decision)!={'tool','arguments','reason'} or decision['tool'] not in UI_TOOLS:raise ReviewError('unsupported_ui_operation')
                # The Rust controller independently validates the complete typed
                # decision and captured candidate IDs. No shell/path API exists.
                args=None
            elif operation=='resume':
                if set(body)!={'operation','note','binding','steps','clear_cancel'}:raise ReviewError('unknown_action_fields')
                if body['binding']!=view['binding']:raise ReviewError('stale_or_foreign_intervention')
                if type(body['steps']) is not int or not 1<=body['steps']<=8 or type(body['clear_cancel']) is not bool:raise ReviewError('invalid_resume_options')
                args=['resume','--task',self.task,'--steps',body['steps'],'--clear-cancel',str(body['clear_cancel']).lower()]
                # Rust checks all four fields under its task lock. The display
                # check alone cannot protect against an external CLI change
                # between this snapshot and the background process acquiring it.
                for key,flag in [('expected_head_sha256','--expected-head-sha256'),
                                 ('expected_generation_id','--expected-generation-id'),
                                 ('expected_revision_id','--expected-revision-id'),
                                 ('task_id','--expected-task-id')]:
                    args.extend([flag,body['binding'][key]])
            else:raise ReviewError('unknown_ui_operation')
            job_id=secrets.token_hex(12)
            with self.job_state_lock:self.job={'id':job_id,'status':'running','operation':operation}
            def work():
                try:
                    if operation=='intervene':
                        with tempfile.TemporaryDirectory(prefix='marinaframe-intervention-') as temporary:
                            path=Path(temporary)/'intervention.json';path.write_text(encode(intervention))
                            result=self.runner(self.controller,['step','--task',self.task,'--intervention',path,'--actor',self.actor,'--note',body['note']],timeout=300)
                    else:result=self.runner(self.controller,args,timeout=900)
                    with self.job_state_lock:self.job={'id':job_id,'status':'completed','result':result}
                except (ReviewError,OSError,ValueError,TypeError) as error:
                    with self.job_state_lock:self.job={'id':job_id,'status':'failed','error_code':str(error)[:180]}
                finally:self.job_lock.release()
            threading.Thread(target=work,daemon=True,name='rust-review-operator').start()
            return {'job_id':job_id,'status':'running'}
        except BaseException:self.job_lock.release();raise


BOOTSTRAP='''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>MarinaFrame local review</title><body style="font:18px system-ui;padding:40px"><h1>Open your local review session</h1><p id="message">Use the one-time local session link printed by the review server.</p><script>const token=new URLSearchParams(location.hash.slice(1)).get('session');history.replaceState(null,'','/');if(token)fetch('/api/session',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({token})}).then(async response=>{if(response.ok)location.reload();else document.getElementById('message').textContent='Session link expired or already used. Restart the local review server to open a new session.';});</script></body></html>'''


class ReviewHandler(BaseHTTPRequestHandler):
    server:ReviewServer
    server_version='MarinaFrameRustReview/1'
    def log_message(self,*args):pass
    def _send(self,status,body,content_type='application/json',cookie=None):
        raw=body.encode() if type(body) is str else encode(body).encode()
        self.send_response(status);self.send_header('Content-Type',content_type);self.send_header('Content-Length',str(len(raw)))
        self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('Referrer-Policy','no-referrer');self.send_header('X-Frame-Options','DENY')
        self.send_header('Cross-Origin-Resource-Policy','same-origin')
        if cookie:self.send_header('Set-Cookie',cookie)
        self.end_headers();self.wfile.write(raw)
    def _host(self):
        return self.headers.get_all('Host',[])==[self.server.authority] and self.headers.get_all('Origin',[]) in ([],[self.server.origin])
    def _session(self):
        try:
            cookie=SimpleCookie();cookie.load(self.headers.get('Cookie',''));token=cookie[COOKIE].value
        except (KeyError,ValueError):return None
        with self.server.session_lock:
            session=self.server.sessions.get(token)
            if not session or session['expires']<time.monotonic():return None
            return session
    def do_GET(self):
        if not self._host():self._send(403,{'error_code':'untrusted_host_or_origin'});return
        session=self._session()
        if self.path=='/' and session is None:self._send(200,BOOTSTRAP,'text/html; charset=utf-8');return
        if session is None:self._send(401,{'error_code':'session_required'});return
        try:
            if self.path=='/':
                self._send(200,render_html(self.server.read_view(),actions=self.server.allow_actions,csrf=session['csrf'],actor=self.server.actor),'text/html; charset=utf-8')
            elif self.path=='/api/job':
                with self.server.job_state_lock:self._send(200,self.server.job)
            else:self._send(404,{'error_code':'not_found'})
        except (ReviewError,OSError,ValueError,TypeError,KeyError) as error:self._send(409,{'error_code':str(error)[:180]})
    def do_POST(self):
        if not self._host() or self.headers.get_all('Origin',[])!=[self.server.origin]:self._send(403,{'error_code':'untrusted_host_or_origin'});return
        if self.headers.get('Transfer-Encoding') or len(self.headers.get_all('Content-Length',[]))!=1 or self.headers.get('Content-Type','').split(';')[0]!='application/json':self._send(400,{'error_code':'request_framing'});return
        try:
            length=int(self.headers['Content-Length'])
            if not 1<=length<=MAX_HTTP:raise ReviewError('request_size')
            raw=self.rfile.read(length)
            if len(raw)!=length:raise ReviewError('incomplete_request_body')
            body=loads_bounded_json(raw,max_bytes=MAX_HTTP,max_nodes=5000,max_depth=16)
            if type(body) is not dict:raise ReviewError('request_object')
        except (OSError,ValueError,TypeError):self._send(400,{'error_code':'invalid_request_json'});return
        if self.path=='/api/session':
            if set(body)!={'token'} or type(body['token']) is not str:self._send(400,{'error_code':'invalid_bootstrap'});return
            with self.server.session_lock:
                if self.server.bootstrap_used or self.server.bootstrap_expires<time.monotonic() or not token_matches(body['token'],self.server.bootstrap):self._send(403,{'error_code':'bootstrap_expired_or_used'});return
                self.server.bootstrap_used=True;token=secrets.token_urlsafe(32);session={'csrf':secrets.token_urlsafe(32),'expires':time.monotonic()+3600};self.server.sessions[token]=session
            self._send(200,{'session':'established'},cookie=COOKIE+'='+token+'; HttpOnly; SameSite=Strict; Path=/');return
        session=self._session()
        if session is None:self._send(401,{'error_code':'session_required'});return
        csrf=self.headers.get_all('X-CSRF-Token',[])
        if len(csrf)!=1 or not token_matches(csrf[0],session['csrf']):self._send(403,{'error_code':'csrf_required'});return
        if self.path!='/api/action':self._send(404,{'error_code':'not_found'});return
        try:
            result=self.server.action(body)
            self._send(200 if body.get('operation')=='cancel' else 202,result)
        except (ReviewError,OSError,ValueError,TypeError,KeyError) as error:self._send(409,{'error_code':str(error)[:180]})


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest='command',required=True)
    for name in ('export','serve'):
        child=sub.add_parser(name);child.add_argument('--task',type=Path,required=True);child.add_argument('--controller',type=Path,required=True)
        if name=='export':child.add_argument('--out',type=Path,required=True)
        else:
            child.add_argument('--port',type=int,default=8767);child.add_argument('--allow-actions',action='store_true')
            child.add_argument('--actor',choices=['human_operator','assistant_operator'],default='human_operator')
            child.add_argument('--session-file',type=Path)
    args=parser.parse_args()
    if args.command=='export':print(encode(write_review(args.task,args.controller,args.out)));return
    server=ReviewServer(('127.0.0.1',args.port),args.task,args.controller,allow_actions=args.allow_actions,actor=args.actor)
    # Startup verification is read-only and occurs before accepting HTTP requests.
    view=server.read_view()
    startup={'url':server.login_url,'task_id':view['task_id'],'allow_actions':args.allow_actions and view['policy']=='deterministic','actor':args.actor}
    if args.session_file:
        fd=os.open(args.session_file,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(fd,'w') as handle:handle.write(encode(startup)+'\n')
        print(encode({'session_file':str(args.session_file),'task_id':view['task_id'],'listening':server.origin}),flush=True)
    else:print(encode(startup),flush=True)
    try:server.serve_forever(poll_interval=.2)
    except KeyboardInterrupt:pass
    finally:server.server_close()

if __name__=='__main__':
    try:main()
    except (ReviewError,OSError,ValueError,TypeError,KeyError) as error:
        print(encode({'ok':False,'error_code':str(error)[:180],'engineering_approved':False}),file=sys.stderr)
        raise SystemExit(2)
