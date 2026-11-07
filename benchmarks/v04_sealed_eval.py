"""Post-hoc, reference-isolated v0.4 evaluation utilities.

This module imports no MarinaFrame inference implementation. The generation script
and numeric reference remain in the independent evaluator's sealed_reference tree.
No score command is allowed without a frozen-runtime and finalized-attempt receipt.
"""
from __future__ import annotations
import argparse,hashlib,json,math,time
from datetime import datetime,timezone
from pathlib import Path

SCHEMA='marinaframe-independent-v04-evaluation-1'

def read(path): return json.loads(Path(path).read_text())
def write(path,obj):
 p=Path(path);p.parent.mkdir(parents=True,exist_ok=True)
 p.write_text(json.dumps(obj,indent=2,sort_keys=True,allow_nan=False)+'\n')
def digest(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def utc(): return datetime.now(timezone.utc).isoformat()

def verify_inputs(root,seal):
 rows=read(seal)['files']; discrepancies=[]
 for row in rows:
  p=Path(root)/row['path']
  if not p.is_file() or digest(p)!=row['sha256'] or p.stat().st_size!=row['bytes']:
   discrepancies.append(row['path'])
 actual={str(p.relative_to(root)) for p in Path(root).rglob('*') if p.is_file()}
 expected={r['path'] for r in rows}
 discrepancies += sorted(actual-expected)
 if discrepancies: raise ValueError('Input seal mismatch: '+', '.join(discrepancies))
 computed=hashlib.sha256('\n'.join(f'{r["path"]}\t{r["sha256"]}' for r in rows).encode()).hexdigest()
 if computed!=read(seal)['input_tree_sha256']: raise ValueError('Invalid input-tree seal receipt')
 return {'verified':True,'files':len(rows),'input_tree_sha256':computed}

def verify_references(root,seal):
 m=read(Path(root)/'reference_manifest.json')
 if digest(Path(root)/'reference_manifest.json')!=read(seal)['reference_manifest_sha256']:
  raise ValueError('Reference manifest changed')
 for row in m['files']:
  if digest(Path(root)/row['path'])!=row['sha256']: raise ValueError('Reference changed')
 return m

def require_frozen_finalized(freeze_path,attempt_path):
 f=read(freeze_path); a=read(attempt_path)
 if f.get('frozen') is not True or not f.get('frozen_utc') or not f.get('arms'):
  raise ValueError('A runtime freeze with arm identities is required')
 if a.get('finalized') is not True or not a.get('finalized_utc'):
  raise ValueError('Inference must finish and be finalized before reference scoring')
 if a.get('arm') not in f['arms']: raise ValueError('Attempt arm absent from freeze')
 if not a.get('case_id') or not a.get('attempt_id'): raise ValueError('Missing attempt identity')
 for row in a.get('output_files',[]):
  if digest(row['path'])!=row['sha256']: raise ValueError('Finalized output changed')
 return f,a

def pixel_baseline(spec_path,out,freeze_path):
 """Independent row median of dark (<128) runs; no CAD or family prior."""
 from PIL import Image
 import numpy as np
 f=read(freeze_path)
 if f.get('frozen') is not True: raise ValueError('Wait for freeze before baseline execution')
 spec=read(spec_path); base=Path(spec_path).parent
 start=time.monotonic(); rec={'schema_version':SCHEMA,'kind':'simple_pixel_baseline_no_CAD','case_id':spec.get('vessel_id'),'created_utc':utc(),'threshold':128,'sections':[],'diagnostics':[]}
 for s in spec.get('sections',[]):
  cal=s.get('calibration',{}); ppm=cal.get('pixels_per_metre')
  if not all(isinstance(cal.get(k),(float,int)) for k in ['pixels_per_metre','centerline_px','baseline_px']) or ppm<=0 or 'z_min_m' not in s or 'z_max_m' not in s:
   rec['diagnostics'].append({'section_id':s.get('id'),'kind':'missing_calibration'}); continue
  arr=np.asarray(Image.open(base/spec['source']['file']).convert('L'))
  left,top,right,bottom=s['roi_px']; left=max(0,int(math.ceil(left)));right=min(arr.shape[1],int(math.floor(right)))
  wanted=list(range(int(round(cal['baseline_px']-s['z_max_m']*ppm)),int(round(cal['baseline_px']-s['z_min_m']*ppm))+1))
  vals=[];ambiguous=0;missing=0
  for row in wanted:
   if row<0 or row>=arr.shape[0]: missing+=1;continue
   xs=np.flatnonzero(arr[row,left:right]<128)+left
   runs=np.split(xs,np.flatnonzero(np.diff(xs)>1)+1) if xs.size else []
   runs=[v for v in runs if v.size and v.size<=20]
   if len(runs)!=1:
    ambiguous += len(runs)>1;missing += not runs;continue
   vals.append({'z_m':(cal['baseline_px']-row)/ppm,'y_m':(float(np.median(runs[0]))-cal['centerline_px'])/ppm})
  rec['sections'].append({'id':s['id'],'x_m':s['x_m'],'rows_required':len(wanted),'rows_resolved':len(vals),'ambiguous_rows':int(ambiguous),'missing_rows':int(missing),'points':vals})
 rec['wall_seconds']=time.monotonic()-start
 rec['CAD_exported']=False;write(out,rec);return rec

def cut_step(step_path,spec_path,out,freeze_path,attempt_path):
 """Independent raw-STEP section measurement using actual OCCT plane intersections.

Each cut edge is sampled at 0.01 mm requested geometric deflection. Horizontal
closures are included; terminal stations are not displaced into the interior.
"""
 require_frozen_finalized(freeze_path,attempt_path)
 import cadquery as cq
 import numpy as np
 from OCP.BRepAlgoAPI import BRepAlgoAPI_Section
 from OCP.gp import gp_Dir,gp_Pln,gp_Pnt
 start=time.monotonic();spec=read(spec_path)
 imported=cq.importers.importStep(str(step_path));shapes=imported.vals()
 solids=[s for q in shapes for s in q.Solids()]
 shape=cq.Compound.makeCompound(shapes)
 rec={'schema_version':SCHEMA,'created_utc':utc(),'case_id':spec['vessel_id'],'step_sha256':digest(step_path),'step_units':'mm','shape_valid':bool(shape.isValid()),'solid_count':len(solids),'volume_m3':float(shape.Volume()/1e9),'cut_deflection_requested_mm':.01,'required_samples_per_station':4097,'sections':[],'cadquery_version':cq.__version__}
 for sec in spec.get('sections',[]):
  plane=gp_Pln(gp_Pnt(float(sec['x_m'])*1000,0,0),gp_Dir(1,0,0))
  op=BRepAlgoAPI_Section(shape.wrapped,plane,False);op.Build()
  zgrid=np.linspace(float(sec['z_min_m']),float(sec['z_max_m']),4097)
  values=np.full(zgrid.shape,-np.inf,dtype=float); zmm=zgrid*1000
  edges=cq.Shape.cast(op.Shape()).Edges() if op.IsDone() else []
  count=0
  for edge in edges:
   pts,params=edge.sample(.01);count+=len(pts)
   for p,q in zip(pts[:-1],pts[1:]):
    z0,z1=float(p.z),float(q.z);y0,y1=float(p.y),float(q.y)
    if abs(z1-z0)<1e-9:
     sel=np.abs(zmm-z0)<=1e-5
     if max(y0,y1)>=-1e-5: values[sel]=np.maximum(values[sel],max(y0,y1)/1000)
    else:
     sel=(zmm>=min(z0,z1)-1e-5)&(zmm<=max(z0,z1)+1e-5)
     ys=y0+(zmm[sel]-z0)*(y1-y0)/(z1-z0)
     ys=np.where(ys>=-1e-5,ys/1000,-np.inf)
     values[sel]=np.maximum(values[sel],ys)
  rec['sections'].append({'id':sec['id'],'x_m':sec['x_m'],'cut_done':bool(op.IsDone()),'edges':len(edges),'sampled_edge_vertices':count,'z_m':zgrid.tolist(),'y_m':[float(v) if math.isfinite(v) else None for v in values],'unresolved':int(np.sum(~np.isfinite(values)))})
 rec['wall_seconds']=time.monotonic()-start
 write(out,rec);return {k:v for k,v in rec.items() if k!='sections'}

def score(step_measurements,reference_dir,seal_path,freeze_path,attempt_path,out):
 import numpy as np
 _,attempt=require_frozen_finalized(freeze_path,attempt_path)
 verify_references(reference_dir,seal_path)
 ref=read(Path(reference_dir)/'cases'/f'{attempt["case_id"]}.json')
 m=read(step_measurements)
 if ref['expected']!='candidate': raise ValueError('Numeric source/volume scoring is only valid for supported procedural cases')
 if m['case_id']!=ref['case_id']: raise ValueError('Measurement/reference case mismatch')
 secmap={s['id']:s for s in m['sections']};rms=[];maxima=[];unresolved=0;required=0;worst=None
 for r in ref['sections']:
  s=secmap.get(r['id']);required+=4097
  if s is None: unresolved+=4097;continue
  z=np.asarray(s['z_m']); vals=np.array([np.nan if v is None else v for v in s['y_m']]);target=np.interp(z,r['z_m'],r['y_m']);errs=np.abs(vals-target)
  good=np.isfinite(errs);unresolved+=int(np.sum(~good))
  if good.any():
   rms.extend((errs[good]*ref['pixels_per_metre'])**2);idx=int(np.nanargmax(errs));loc={'section_id':s['id'],'z_m':float(z[idx]),'actual_y_m':float(vals[idx]),'reference_y_m':float(target[idx]),'error_m':float(errs[idx]),'error_px':float(errs[idx]*ref['pixels_per_metre'])};maxima.append(loc['error_px'])
   if worst is None or loc['error_px']>worst['error_px']:worst=loc
 errvol=abs(m['volume_m3']-ref['reference_volume_m3'])/ref['reference_volume_m3'];errrms=float(math.sqrt(np.mean(rms))) if rms else None;errmax=max(maxima) if maxima else None
 independent_pass=bool(m['shape_valid'] and m['solid_count']==1 and not unresolved and required==4097*len(ref['sections']) and errvol<=.03 and errrms is not None and errrms<=2 and errmax is not None and errmax<=4)
 result={'schema_version':SCHEMA,'created_utc':utc(),'attempt_id':attempt['attempt_id'],'case_id':attempt['case_id'],'arm':attempt['arm'],'reference_kind':'independently_authored_procedural','reference_volume_m3':ref['reference_volume_m3'],'reimported_volume_m3':m['volume_m3'],'volume_relative_error':errvol,'section_rms_px_resolved_only':errrms,'section_max_px_resolved_only':errmax,'required_ordinates':required,'unresolved_ordinates':unresolved,'worst':worst,'independent_geometry_pass':independent_pass,'selected_trace_to_STEP_limit_mm':1.1,'selected_trace_to_STEP_pass':attempt.get('selected_trace_to_STEP_pass'),'selected_trace_to_STEP_max_error_mm':attempt.get('selected_trace_to_STEP_max_error_mm'),'full_pass':independent_pass and attempt.get('selected_trace_to_STEP_pass') is True,'measurement_sha256':digest(step_measurements),'attempt_sha256':digest(attempt_path),'freeze_sha256':digest(freeze_path)}
 write(out,result);return result

def main():
 p=argparse.ArgumentParser();sub=p.add_subparsers(dest='command',required=True)
 q=sub.add_parser('verify');q.add_argument('--input-root',required=True);q.add_argument('--seal',required=True)
 q=sub.add_parser('pixel-baseline');q.add_argument('--spec',required=True);q.add_argument('--out',required=True);q.add_argument('--freeze',required=True)
 q=sub.add_parser('cut-step');q.add_argument('--step',required=True);q.add_argument('--spec',required=True);q.add_argument('--out',required=True);q.add_argument('--freeze',required=True);q.add_argument('--attempt',required=True)
 q=sub.add_parser('score');q.add_argument('--measurements',required=True);q.add_argument('--reference-dir',required=True);q.add_argument('--seal',required=True);q.add_argument('--freeze',required=True);q.add_argument('--attempt',required=True);q.add_argument('--out',required=True)
 a=p.parse_args()
 if a.command=='verify':result=verify_inputs(Path(a.input_root),a.seal)
 elif a.command=='pixel-baseline':result=pixel_baseline(a.spec,a.out,a.freeze)
 elif a.command=='cut-step':result=cut_step(a.step,a.spec,a.out,a.freeze,a.attempt)
 else:result=score(a.measurements,a.reference_dir,a.seal,a.freeze,a.attempt,a.out)
 print(json.dumps(result,indent=2,sort_keys=True,allow_nan=False))
if __name__=='__main__':main()
