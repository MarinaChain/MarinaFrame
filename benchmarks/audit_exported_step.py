"""Post-evaluation diagnostic: compare actual exported STEP sections to labels.

The primary frozen gates compare extracted image curves and global CAD volume.
This additional diagnostic closes that distinction by cutting the exported CAD
at a predeclared nine equally spread interior reference stations. It neither
reruns inference nor changes existing scores/gates. Units are explicitly mm in
STEP and metres in labels. End caps and between-station geometry are not tested.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import time
import numpy as np
from .generate import sha256
from .evaluate import atomic_text, verify_manifest


def sample_step_sections(step_path: Path, reference_sections: list[dict], *, count=9, samples=129):
    from OCP.STEPControl import STEPControl_Reader
    from OCP.IFSelect import IFSelect_RetDone
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Section
    from OCP.gp import gp_Pln, gp_Pnt, gp_Dir
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopAbs import TopAbs_EDGE
    from OCP.BRepAdaptor import BRepAdaptor_Curve
    from OCP.TopoDS import TopoDS
    reader=STEPControl_Reader()
    if reader.ReadFile(str(step_path)) != IFSelect_RetDone:
        raise ValueError('Cannot read exported STEP')
    reader.TransferRoots(); shape=reader.OneShape()
    indices=np.unique(np.rint(np.linspace(1,len(reference_sections)-2,min(count,len(reference_sections)-2))).astype(int))
    if not len(indices): raise ValueError('No interior reference stations')
    records=[]
    for index in indices:
        ref=reference_sections[int(index)]
        section=BRepAlgoAPI_Section(shape,gp_Pln(gp_Pnt(ref['x_m']*1000,0,0),gp_Dir(1,0,0)),False)
        section.Build()
        if not section.IsDone():
            records.append({'id':ref['id'],'status':'cut_failed'}); continue
        edge=TopExp_Explorer(section.Shape(),TopAbs_EDGE)
        segments=[]
        while edge.More():
            curve=BRepAdaptor_Curve(TopoDS.Edge_s(edge.Current()))
            values=np.linspace(curve.FirstParameter(),curve.LastParameter(),513)
            points=np.asarray([[curve.Value(float(t)).Y()/1000,curve.Value(float(t)).Z()/1000] for t in values])
            segments.extend(zip(points[:-1],points[1:]))
            edge.Next()
        if not segments:
            records.append({'id':ref['id'],'status':'no_boundary'}); continue
        ends=np.asarray(segments); a,b=ends[:,0],ends[:,1]
        truth=np.asarray(ref['points_yz_m'],dtype=float)
        # Interior elevations avoid tangencies at the exact deck/keel edge.
        elevations=np.linspace(truth[0,1],truth[-1,1],samples+2)[1:-1]
        errors=[]; ambiguous=0; absent=0
        for z in elevations:
            crossing=((a[:,1]<=z)&(z<b[:,1]))|((b[:,1]<=z)&(z<a[:,1]))
            aa,bb=a[crossing],b[crossing]
            hits=aa[:,0]+(z-aa[:,1])*(bb[:,0]-aa[:,0])/(bb[:,1]-aa[:,1])
            hits=np.sort(hits[hits>=-1e-7])
            unique=[]
            for y in hits:
                if not unique or abs(y-unique[-1])>1e-6: unique.append(float(y))
            if len(unique)==0: absent+=1; continue
            if len(unique)>1: ambiguous+=1; continue
            errors.append(unique[0]-float(np.interp(z,truth[:,1],truth[:,0])))
        records.append({'id':ref['id'],'x_m':ref['x_m'],'status':'complete' if not ambiguous and not absent else 'incomplete',
            'compared_ordinates':len(errors),'ambiguous_ordinates':ambiguous,'absent_ordinates':absent,
            'mean_squared_error_m2':float(np.mean(np.square(errors))) if errors else None,
            'maximum_absolute_error_m':max(map(abs,errors)) if errors else None})
    return records


def audit(suite_dir:Path,evaluation_dir:Path,case_ids:list[str],out:Path):
    if out.exists(): raise FileExistsError('Diagnostic output exists; retain it and choose a fresh path')
    manifest=verify_manifest(suite_dir)
    report_path=evaluation_dir/'report.json'
    report=json.loads(report_path.read_text())
    cases={c['case_id']:c for c in manifest['cases']}
    scored={c['case_id']:c for c in report['records']}
    output={'diagnostic_only':True,'original_report_sha256':sha256(report_path),
      'preexisting_scores_unchanged':True,'selection':'Caller-declared cases; nine equally spread interior drawing stations in each case',
      'scope':'Actual STEP boundary vs numerical source half-sections;129 interior elevations per station; no endcaps or between-station accuracy claim',
      'step_units':'mm','reference_units':'m','cases':[]}
    for case_id in case_ids:
        if not scored[case_id]['score']['passed'] or scored[case_id]['score'].get('correct_abstention'):
            raise ValueError('Select only numerical reconstruction cases that exported CAD')
        truth=json.loads((suite_dir/cases[case_id]['ground_truth']).read_text())
        step_path=evaluation_dir/'runs'/case_id/'model.step'
        started=time.perf_counter()
        rr=sample_step_sections(step_path,truth['sections'])
        complete=all(r['status']=='complete' for r in rr)
        rms=float(np.sqrt(np.mean([r['mean_squared_error_m2'] for r in rr]))) if complete else None
        output['cases'].append({'case_id':case_id,'step_sha256':sha256(step_path),'complete':complete,
          'station_count':len(rr),'rms_section_error_m':rms,'rms_section_error_over_beam':rms/truth['beam_m'] if rms is not None else None,
          'maximum_absolute_error_m':max(r['maximum_absolute_error_m'] for r in rr) if complete else None,
          'wall_seconds':time.perf_counter()-started,'sections':rr})
    assert output['original_report_sha256']==sha256(report_path)
    atomic_text(out,json.dumps(output,indent=2)+'\n')
    return output

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('suite',type=Path);p.add_argument('evaluation',type=Path)
    p.add_argument('--case',action='append',required=True);p.add_argument('--out',type=Path,required=True)
    a=p.parse_args();r=audit(a.suite,a.evaluation,a.case,a.out)
    print(json.dumps([{k:v for k,v in c.items() if k!='sections'} for c in r['cases']],indent=2))
