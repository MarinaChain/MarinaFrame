"""Version 2 diagnostic: exact linear STEP section intersections with tolerance.

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

COMPARATOR_VERSION = "step_linear_sections_v2"
ENDPOINT_TOLERANCE_M = 1e-9
DEDUPLICATION_TOLERANCE_M = 1e-9


def ordinate_intersection(segments, z, *, endpoint_tolerance_m=ENDPOINT_TOLERANCE_M,
                          deduplication_tolerance_m=DEDUPLICATION_TOLERANCE_M):
    """Intersect straight CAD segments; never drop an unresolved ordinate.

    Independently exported edge endpoints may differ at floating-point scale.
    Use a closed interval with a fixed 1 nm endpoint tolerance, and record any
    tolerance assistance. Distinct positive boundaries and horizontal overlaps
    remain ambiguous. A larger real gap remains absent.
    """
    candidates = []
    adjustments = []
    horizontal = []
    nearest = []
    for first, second in segments:
        ya, za = map(float, first); yb, zb = map(float, second)
        low, high = min(za, zb), max(za, zb)
        if max(ya, yb) >= -endpoint_tolerance_m:
            nearest.append(min(abs(z - low), abs(z - high)))
        if z < low - endpoint_tolerance_m or z > high + endpoint_tolerance_m:
            continue
        if abs(zb - za) <= endpoint_tolerance_m:
            if max(ya, yb) >= -endpoint_tolerance_m:
                yl, yh = max(0.0, min(ya, yb)), max(0.0, max(ya, yb))
                if yh - yl > deduplication_tolerance_m:
                    horizontal.append([yl, yh])
                else:
                    candidates.append((yl + yh) / 2)
            continue
        bounded_z = min(high, max(low, z))
        y = ya + (bounded_z - za) * (yb - ya) / (zb - za)
        if y >= -endpoint_tolerance_m:
            candidates.append(max(0.0, y))
            if bounded_z != z:
                adjustments.append(abs(bounded_z - z))
    clusters = []
    for y in sorted(candidates):
        if not clusters or y - clusters[-1][0] > deduplication_tolerance_m:
            clusters.append([y])
        else:
            clusters[-1].append(y)
    unique = [float(np.mean(cluster)) for cluster in clusters]
    status = "ambiguous" if horizontal or len(unique) > 1 else "complete" if unique else "absent"
    return {"status": status, "y_m": unique[0] if status == "complete" else None,
            "boundary_candidates_y_m": unique, "horizontal_intervals_y_m": horizontal,
            "endpoint_tolerance_applied": bool(adjustments),
            "maximum_endpoint_adjustment_m": max(adjustments, default=0.0),
            "nearest_positive_endpoint_distance_m": min(nearest, default=None)}


def sample_step_sections(step_path: Path, reference_sections: list[dict], *, count=9, samples=129):
    from OCP.STEPControl import STEPControl_Reader
    from OCP.IFSelect import IFSelect_RetDone
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Section
    from OCP.gp import gp_Pln, gp_Pnt, gp_Dir
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopAbs import TopAbs_EDGE
    from OCP.BRepAdaptor import BRepAdaptor_Curve
    from OCP.TopoDS import TopoDS
    from OCP.GeomAbs import GeomAbs_Line
    reader=STEPControl_Reader()
    if reader.ReadFile(str(step_path)) != IFSelect_RetDone:
        raise ValueError('Cannot read exported STEP')
    reader.TransferRoots(); shape=reader.OneShape()
    indices=np.unique(np.rint(np.linspace(1,len(reference_sections)-2,min(count,len(reference_sections)-2))).astype(int))
    if not len(indices): raise ValueError('No interior reference stations')
    records=[]
    for index in indices:
        ref=reference_sections[int(index)]
        truth=np.asarray(ref['points_yz_m'],dtype=float)
        elevations=np.linspace(truth[0,1],truth[-1,1],samples+2)[1:-1]
        base={'id':ref['id'],'x_m':ref['x_m'],'requested_ordinates':len(elevations)}
        section=BRepAlgoAPI_Section(shape,gp_Pln(gp_Pnt(ref['x_m']*1000,0,0),gp_Dir(1,0,0)),False)
        section.Build()
        if not section.IsDone():
            records.append({**base,'status':'cut_failed','compared_ordinates':0,
                'absent_ordinates':0,'ambiguous_ordinates':0,'unevaluated_ordinates':len(elevations),
                'unresolved_ordinate_details':[{'z_m':float(z),'reason':'cut_failed'} for z in elevations]}); continue
        edge=TopExp_Explorer(section.Shape(),TopAbs_EDGE)
        segments=[]; unsupported=[]; curve_types={}
        while edge.More():
            curve=BRepAdaptor_Curve(TopoDS.Edge_s(edge.Current()))
            kind=str(curve.GetType());curve_types[kind]=curve_types.get(kind,0)+1
            if curve.GetType()!=GeomAbs_Line:
                unsupported.append(kind)
            else:
                first=curve.Value(curve.FirstParameter());last=curve.Value(curve.LastParameter())
                segments.append(([first.Y()/1000,first.Z()/1000],[last.Y()/1000,last.Z()/1000]))
            edge.Next()
        if unsupported:
            records.append({**base,'status':'unsupported_curved_boundary','curve_types':curve_types,
                'compared_ordinates':0,'absent_ordinates':0,'ambiguous_ordinates':0,'unevaluated_ordinates':len(elevations),
                'unresolved_ordinate_details':[{'z_m':float(z),'reason':'unsupported_curved_boundary'} for z in elevations]});continue
        if not segments:
            records.append({**base,'status':'no_boundary','compared_ordinates':0,'absent_ordinates':len(elevations),
                'ambiguous_ordinates':0,'unevaluated_ordinates':0,
                'unresolved_ordinate_details':[{'z_m':float(z),'reason':'no_boundary'} for z in elevations]}); continue
        # Interior elevations avoid tangencies at the exact deck/keel edge.
        errors=[]; ambiguous=0; absent=0; unresolved=[]; assisted=[]
        for z in elevations:
            hit=ordinate_intersection(segments,float(z))
            if hit['endpoint_tolerance_applied']:
                assisted.append({'z_m':float(z),'maximum_endpoint_adjustment_m':hit['maximum_endpoint_adjustment_m']})
            if hit['status']!='complete':
                absent+=int(hit['status']=='absent');ambiguous+=int(hit['status']=='ambiguous')
                unresolved.append({'z_m':float(z),**hit});continue
            errors.append(hit['y_m']-float(np.interp(z,truth[:,1],truth[:,0])))
        records.append({**base,'status':'complete' if not ambiguous and not absent else 'incomplete',
            'compared_ordinates':len(errors),'ambiguous_ordinates':ambiguous,'absent_ordinates':absent,
            'unevaluated_ordinates':0,'curve_types':curve_types,
            'endpoint_tolerance_assisted_ordinates':len(assisted),'endpoint_tolerance_details':assisted,
            'unresolved_ordinate_details':unresolved,
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
    output={'diagnostic_only':True,'comparator_version':COMPARATOR_VERSION,
      'comparator_source_file':str(Path(__file__).relative_to(Path(__file__).resolve().parents[1])),
      'comparator_source_sha256':sha256(Path(__file__)),
      'endpoint_tolerance_m':ENDPOINT_TOLERANCE_M,'deduplication_tolerance_m':DEDUPLICATION_TOLERANCE_M,
      'boundary_method':'Exact intersections of straight STEP cut edges; nonlinearity, missing ordinates and multiple boundaries remain explicit failures.',
      'endpoint_policy':'Closed endpoint intervals with fixed1nm tolerance; every assisted ordinate and its adjustment is recorded. No inference geometry is changed.',
      'original_report_sha256':sha256(report_path),
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
          'requested_ordinates':sum(r['requested_ordinates'] for r in rr),
          'compared_ordinates':sum(r['compared_ordinates'] for r in rr),
          'absent_ordinates':sum(r['absent_ordinates'] for r in rr),
          'ambiguous_ordinates':sum(r['ambiguous_ordinates'] for r in rr),
          'unevaluated_ordinates':sum(r['unevaluated_ordinates'] for r in rr),
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
