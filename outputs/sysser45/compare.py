import json
from pathlib import Path
for suite in ('procedural','factory'):
    folder=Path('outputs/sysser45')
    before=json.loads((folder/f'{suite}-before.json').read_text())
    after=json.loads((folder/f'{suite}-after.json').read_text())
    result={'before_cases':len(before),'after_cases':len(after),'lost':[],'gained':[],'changed_geometry':[], 'catalog_changed':[], 'case_lost':[], 'case_gained':[], 'errors_before':[], 'errors_after':[]}
    for cid,b in before.items():
        if 'error' in b:result['errors_before'].append([cid,b['error']])
        if cid not in after:continue
        a=after[cid]
        if 'error' in a:result['errors_after'].append([cid,a['error']])
        if b.get('all_selected') and not a.get('all_selected'):result['case_lost'].append(cid)
        if not b.get('all_selected') and a.get('all_selected'):result['case_gained'].append(cid)
        for sid,old in b.get('sections',{}).items():
            new=a.get('sections',{}).get(sid)
            if not new:continue
            if old['chosen'] and not new['chosen']:result['lost'].append([cid,sid])
            if not old['chosen'] and new['chosen']:result['gained'].append([cid,sid])
            if old['chosen'] and new['chosen'] and old['points_sha256']!=new['points_sha256']:result['changed_geometry'].append([cid,sid])
            if old['candidates']!=new['candidates']:result['catalog_changed'].append([cid,sid])
    (folder/f'{suite}-comparison.json').write_text(json.dumps(result,indent=2))
    print(suite,{k:len(v) if isinstance(v,list) else v for k,v in result.items()})
