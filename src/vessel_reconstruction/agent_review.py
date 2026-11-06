"""Self-contained review UI over verified task evidence; no automatic approval."""
from __future__ import annotations

import base64
import html
import json
from pathlib import Path

from .agent_harness import HarnessError, TaskStore, _artifact_bytes, verify_task
from .schema import load_bounded_json


def write_review(task, output):
    task=Path(task).absolute();output=Path(output).absolute()
    verification=verify_task(task)
    if not verification['valid']:raise HarnessError('Review export requires intact task evidence')
    with TaskStore(task) as store:
        if store.head!=verification['head_sha256']:raise HarnessError('Task changed during review export')
        state=store.state.copy();events=list(store.events)
        domain=load_bounded_json(task/'domain/state.json',max_bytes=16_000_000,max_nodes=600_000)
        artifacts={}
        def collect(value):
            if isinstance(value,dict):
                if value.get('mime_type')=='image/png' and {'path','sha256','id'}<=set(value):
                    artifacts[value['id']]=value
                for x in value.values():collect(x)
            elif isinstance(value,list):
                for x in value:collect(x)
        for event in events:collect(event['payload'])
        figures=[];total_bytes=0
        total_figures=sum(not a.get('model_eligible') for a in artifacts.values())
        for a in artifacts.values():
            if a.get('model_eligible'):continue
            raw=_artifact_bytes(task,a,8*1024**2);total_bytes+=len(raw)
            if len(figures)>=80 or total_bytes>24*1024**2:break
            title=' · '.join(str(a[k]) for k in ('kind','section_id','view') if k in a)
            figures.append('<figure><img loading="lazy" src="data:image/png;base64,'+base64.b64encode(raw).decode()+
                '" alt="'+html.escape(title,quote=True)+'"><figcaption>'+html.escape(title)+'<small>SHA256 '+a['sha256']+'</small></figcaption></figure>')
        sections=[]
        for sid,entry in domain['catalog'].items():
            options=[]
            for candidate in entry['candidates']:
                cid=candidate['candidate_id'];chosen=domain['selected'].get(sid)==cid
                options.append('<label class="choice"><input type="radio" name="'+html.escape(sid,quote=True)+
                    '" value="'+html.escape(cid,quote=True)+'" '+('checked ' if chosen else '')+
                    ('' if candidate['selectable'] else 'disabled ')+'> <span><b>'+html.escape(candidate.get('hypothesis',cid))+
                    '</b><small>'+html.escape(cid)+'</small></span></label>')
            sections.append('<fieldset data-section="'+html.escape(sid,quote=True)+'"><legend>'+html.escape(sid)+
                '</legend><p>Excluded strokes remain in the source evidence. Selecting a contour creates a provisional revision.</p>'+''.join(options)+'</fieldset>')
        trajectory=[]
        for event in events:
            payload=event['payload'];kind=event['kind']
            decision=payload.get('decision')
            line=decision.get('tool')+' — '+decision.get('reason','') if decision else payload.get('reason',payload.get('tool',kind))
            receipt=payload.get('receipt') or {}
            if receipt.get('returned_model'):line+=' · '+receipt['returned_model']+' · '+receipt.get('input_mode','')
            trajectory.append('<li><span>'+str(event['sequence'])+' · '+html.escape(kind)+'</span><p>'+html.escape(str(line))+'</p></li>')
        metrics={'status':state['status'],'policy':state['policy'],'model_or_policy_calls':state['policy_calls'],
            'operator_actions':state['operator_actions'],'builds':state['builds'],'engineering_approved':False,
            'source_manifest_sha256':state['source_manifest_sha256'],'event_head_sha256':store.head,
            'validation':domain.get('validation')}
    body='''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>MarinaFrame · Task review</title><style>
:root{font-family:system-ui,sans-serif;color:#142c3c;background:#edf3f5;line-height:1.5}*{box-sizing:border-box}body{margin:0}header{padding:38px max(24px,calc((100vw - 1220px)/2));background:#102c3d;color:white}header small{color:#90d6cf;letter-spacing:.13em}h1{font-size:36px;line-height:1.15;margin:10px 0}header p{max-width:850px}main{max-width:1270px;margin:0 auto;padding:24px}nav{display:flex;gap:24px;padding:16px 0;flex-wrap:wrap}a{color:#006b76}header a{color:#b7ebe5}.status{background:#fff0cc;border:1px solid #a67413;padding:16px;border-radius:8px;margin:16px 0}section{margin:28px 0}h2{font-size:24px}small{display:block;overflow-wrap:anywhere}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(330px,1fr));gap:18px}figure,fieldset,.panel{margin:0;background:white;border:1px solid #cfdee5;border-radius:8px;padding:16px;min-width:0}figure img{max-width:100%;height:auto;display:block;background:#fff}figcaption{padding-top:10px;font-size:14px}figcaption small{font-size:11px;color:#4b6676}.choice{display:flex;align-items:flex-start;gap:8px;padding:10px 0;border-bottom:1px solid #e2eaee}.choice input{margin-top:7px}.choice span{min-width:0;overflow-wrap:anywhere}legend{font-weight:700}button{background:#086e78;border:0;border-radius:6px;color:white;padding:12px 18px;font:inherit;cursor:pointer}button:focus-visible,a:focus-visible,input:focus-visible{outline:3px solid #f6a13a;outline-offset:3px}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#102c3d;color:#e0f4f5;padding:20px;border-radius:8px;font-size:13px}ol{padding-left:26px}li{padding:9px 0}li span{font-size:12px;text-transform:uppercase;letter-spacing:.05em;color:#496477}li p{margin:3px 0}.instructions{max-width:900px}#selection-status{min-height:24px;font-weight:600}@media(max-width:540px){.grid{grid-template-columns:1fr}main{padding:16px}header{padding:26px 16px}h1{font-size:29px}}
</style></head><body><header><small>MARINAFRAME / EVIDENCE WORKBENCH</small><h1>Source pixels to a reviewable hull</h1><p>Inspect the drawing, preserved contour alternatives, exported STEP views, and the decisions that connect them.</p><nav><a href="#evidence">Visual evidence</a><a href="#selection">Contour selection</a><a href="#trajectory">Decision history</a><a href="#measurements">Measurements</a></nav></header><main><div class="status"><b>Human semantic review required.</b> No engineering approval has been granted. Local hashes establish file consistency; they do not certify a vessel or authenticate a reviewer.</div>
'''
    figure_notice=f'Displaying {len(figures)} of {total_figures} recorded evidence images.'
    if len(figures)<total_figures:
        figure_notice+=' This export is incomplete because of its size bound; inspect the complete task artifacts before selecting contours for omitted sections.'
    body+='<section id="evidence"><h2>Visual evidence</h2><p>'+figure_notice+'</p><p>CAD views are rendered from the reimported exported STEP. Source overlays retain competing strokes.</p><div class="grid">'+''.join(figures)+'</div></section>'
    body+='<section id="selection"><h2>Inspect and revise contours</h2><p class="instructions">Choose a source-supported alternative for each station. Download the decision, apply it with the local command below, then resume the task to rebuild and validate. This offline file does not execute tools or approve the geometry.</p><div class="grid">'+''.join(sections)+'</div><p><button id="download-selection" type="button">Download selection decision</button></p><p id="selection-status" role="status" aria-live="polite"></p><pre>vessel-reconstruct agent step TASK --decision selection-decision.json --actor human_operator --note "Describe the source evidence for this revision"\nvessel-reconstruct agent resume TASK --policy deterministic\nvessel-reconstruct agent review TASK --out revised-review.html</pre></section>'
    body+='<section id="trajectory"><h2>Decision history</h2><ol>'+''.join(trajectory)+'</ol></section>'
    body+='<section id="measurements"><h2>Measurements and evidence binding</h2><pre>'+html.escape(json.dumps(metrics,indent=2))+'</pre></section></main>'
    body+='''<script>document.getElementById('download-selection').addEventListener('click',()=>{const selections=[...document.querySelectorAll('fieldset[data-section]')].flatMap(f=>{const chosen=f.querySelector('input:checked');return chosen?[{section_id:f.dataset.section,candidate_id:chosen.value}]:[]});const status=document.getElementById('selection-status');if(!selections.length){status.textContent='Select at least one inspected contour.';return;}const decision={tool:'select_contours',arguments:{selections},reason:'Explicit operator selections from source evidence; semantic review remains required.'};const blob=new Blob([JSON.stringify(decision,null,2)+'\\n'],{type:'application/json'});const url=URL.createObjectURL(blob);const a=document.createElement('a');a.href=url;a.download='selection-decision.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),500);status.textContent='Selection decision downloaded. Apply it locally to record the operator intervention and regenerate the candidate.';});</script></body></html>'''
    output.parent.mkdir(parents=True,exist_ok=True);output.write_text(body,encoding='utf-8')
    return output
