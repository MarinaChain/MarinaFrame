"""Evaluate a frozen image suite without handing labels to reconstruction.

The inference subprocess receives an isolated copy of spec + source image only.
Labels are read in this evaluator AFTER the subprocess has finished. This is a
transparent data-flow boundary, not an OS security sandbox. All cases, including
failures and abstentions, are retained; gates come from the frozen manifest.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import importlib.metadata
import io
import csv
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time

import numpy as np
from PIL import Image
from .generate import sha256, section_volume

ROOT = Path(__file__).resolve().parents[1]


def atomic_text(path: Path, text: str) -> None:
    """Publish a complete UTF-8 artifact and verify the bytes before proceeding.

    Full checkpoint snapshots avoid depending on incremental append visibility.
    This affects evidence persistence only; it never changes a score.
    """
    payload = text.encode('utf-8')
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix=path.name+'.pending-', delete=False) as stream:
        temporary = Path(stream.name)
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)
    if path.read_bytes() != payload:
        raise OSError(f'Artifact readback mismatch: {path}')


def verify_manifest(suite_dir: str | Path) -> dict:
    """Reject changed inputs rather than scoring against stale frozen hashes."""
    suite_dir = Path(suite_dir)
    manifest_path = suite_dir / 'suite_manifest.json'
    expected = (suite_dir / 'suite_manifest.sha256').read_text().split()[0]
    if sha256(manifest_path) != expected:
        raise ValueError('Frozen suite manifest hash mismatch')
    manifest = json.loads(manifest_path.read_text())
    # The embedded contract is the authority for old suites. A current contract
    # may evolve for a NEW suite, without retroactively changing old gates.
    for case in manifest['cases']:
        spec_path = suite_dir / case['spec']
        if sha256(spec_path) != case['spec_sha256']:
            raise ValueError(f"Frozen spec hash mismatch: {case['case_id']}")
        spec = json.loads(spec_path.read_text())
        source = (spec_path.parent / spec['source']['file']).resolve()
        if sha256(source) != case['image_sha256']:
            raise ValueError(f"Frozen drawing hash mismatch: {case['case_id']}")
        if sha256(suite_dir / case['ground_truth']) != case['ground_truth_sha256']:
            raise ValueError(f"Frozen ground truth hash mismatch: {case['case_id']}")
    return manifest


def section_error_metrics(predicted_sections: list[dict], truth: dict) -> dict:
    """Compare y(z) on each known station, with equal weighting per station.

    Predictions must cover each full reference vertical interval; missing
    sections/elevations are a scored failure, not silently omitted points.
    """
    known = truth.get('sections', [])
    if not known:
        return {'available': False, 'reason': 'No numerical reference for this challenge'}
    by_id = {s['id']: s for s in predicted_sections}
    square_errors, max_errors = [], []
    missing, position_mismatches = [], []
    duplicate_ids = {sid for sid in by_id if sum(s['id'] == sid for s in predicted_sections) > 1}
    for original in known:
        estimate = by_id.get(original['id'])
        if estimate is None or original['id'] in duplicate_ids:
            missing.append(original['id'])
            continue
        estimated_x = estimate.get('x_m')
        if estimated_x is None or not np.isfinite(estimated_x) or abs(estimated_x-original['x_m']) > 1e-7:
            position_mismatches.append(original['id'])
            missing.append(original['id'])
            continue
        gp = np.asarray(original['points_yz_m'], dtype=float)
        pp = np.asarray(estimate.get('points_yz_m', []), dtype=float)
        if pp.ndim != 2 or pp.shape[1] != 2 or len(pp) < 2 or not np.isfinite(pp).all():
            missing.append(original['id']); continue
        pp = pp[np.argsort(pp[:, 1])]
        if np.any(np.diff(pp[:, 1]) <= 0) or pp[0, 1] > gp[0, 1]+1e-6 or pp[-1, 1] < gp[-1, 1]-1e-6:
            missing.append(original['id']); continue
        # 257 shared normalized elevations avoid weighting generator sampling.
        z = np.linspace(gp[0,1], gp[-1,1], 257)
        error = np.interp(z, pp[:,1], pp[:,0]) - np.interp(z, gp[:,1], gp[:,0])
        square_errors.append(float(np.mean(error**2)))
        max_errors.append(float(np.max(np.abs(error))))
    rms = float(np.sqrt(np.mean(square_errors))) if square_errors else None
    beam = float(truth['beam_m'])
    return {'available': True, 'complete': not missing, 'missing_section_ids': missing,
            'position_mismatch_section_ids': position_mismatches,
            'duplicate_prediction_ids': sorted(duplicate_ids),
            'compared_sections': len(square_errors), 'reference_sections': len(known),
            'rms_section_error_m': rms,
            'rms_section_error_over_beam': rms/beam if rms is not None else None,
            'maximum_section_error_m': max(max_errors) if max_errors else None,
            'comparison': 'Equal station weighting; interpolated half breadth at 257 elevations; RMS normalized by full beam'}


def score_result(result: dict, truth: dict, *, expected_outcome: str, gate: dict) -> dict:
    actual = result.get('status', 'missing_result')
    if expected_outcome == 'blocked':
        passed = actual == 'blocked' and not result.get('exports') and not result.get('parts')
        return {'passed': passed, 'correct_abstention': passed, 'expected_outcome': expected_outcome,
                'actual_outcome': actual, 'reason': 'Required information or evidence absent; model must not be published'}
    metric = section_error_metrics(result.get('sections', []), truth)
    observed_volume = result.get('metrics', {}).get('volume_m3')
    target = truth.get('reference_volume_m3')
    volume_error = abs(observed_volume-target)/target if observed_volume is not None and target else None
    cad = bool(result.get('metrics', {}).get('cad_valid')) and result.get('metrics', {}).get('solid_count') == 1
    passed = (actual == 'review_required' and cad and metric.get('complete', False)
              and volume_error is not None and volume_error <= gate['maximum_relative_volume_error']
              and metric.get('rms_section_error_over_beam') is not None
              and metric['rms_section_error_over_beam'] <= gate['maximum_rms_section_error_over_beam'])
    return {'passed': bool(passed), 'expected_outcome': expected_outcome, 'actual_outcome': actual,
            'cad_valid_single_solid': cad, 'reference_volume_m3': target,
            'observed_volume_m3': observed_volume, 'relative_volume_error': volume_error,
            **metric}


def threshold_baseline(spec: dict, base_dir: Path) -> dict:
    """Simple reproducible baseline: rightmost pixel <120 in each sampled row.

    Same declared calibration/ROIs and vertical extent as the main method, but
    no curve continuity, component selection, stroke confidence or CAD fitting.
    It deliberately provides a meaningful image-processing baseline, not an
    oracle reading the target contour or source CAD.
    """
    started = time.perf_counter()
    if not spec.get('sections'):
        return {'method':'rightmost_dark_pixel_per_row_threshold_120', 'status':'blocked',
                'sections':[], 'volume_m3':None, 'errors':[{'error':'No declared sections'}],
                'timing_seconds':time.perf_counter()-started}
    image = np.asarray(Image.open(base_dir/spec['source']['file']).convert('L'))
    sections, errors = [], []
    for s in spec.get('sections', []):
        try:
            c = s['calibration']; ppm = float(c['pixels_per_metre'])
            if ppm <= 0: raise ValueError('nonpositive scale')
            cx, baseline = float(c['centerline_px']), float(c['baseline_px'])
            x0,y0,x1,y1 = map(int,s['roi_px'])
            heights = np.linspace(float(s['z_min_m']),float(s['z_max_m']),65)
            ys = []
            for z in heights:
                row = int(round(baseline-z*ppm))
                if not (y0 <= row < y1): raise ValueError('vertical interval outside ROI')
                dark = np.flatnonzero(image[row, max(x0,int(np.ceil(cx))):x1] < 120)
                if not len(dark): raise ValueError('row has no dark curve pixel')
                pixel = max(x0,int(np.ceil(cx))) + dark[-1]
                ys.append(max(0., (pixel-cx)/ppm))
            sections.append({'id':s['id'],'x_m':s['x_m'],'points_yz_m':np.column_stack((ys,heights)).tolist()})
        except (KeyError,ValueError,IndexError,TypeError) as exc:
            errors.append({'id':s.get('id'),'error':str(exc)})
    valid = len(sections) >= 3 and not errors
    return {'method':'rightmost_dark_pixel_per_row_threshold_120',
            'status':'section_estimate' if valid else 'blocked', 'sections':sections,
            'volume_m3':section_volume(sections) if valid else None,
            'errors':errors,'timing_seconds':time.perf_counter()-started,
            'note':'Section-only baseline; no CAD-validity claim. Uses the same operator calibration.'}


def _run_inference(spec_path: Path, output_path: Path, *, export_cad: bool, timeout_seconds: float, code_root: Path | None = None) -> dict:
    """No labels are copied or passed on the inference command line."""
    spec = json.loads(spec_path.read_text())
    original_source = (spec_path.parent/spec['source']['file']).resolve()
    with tempfile.TemporaryDirectory(prefix='vessel_pixels_only_') as temp:
        isolated = Path(temp)
        # Preserve exact spec bytes and local basename to preserve input hashes.
        local_source = Path(spec['source']['file'])
        if local_source.is_absolute() or '..' in local_source.parts:
            raise ValueError('Benchmark sources must be relative paths inside the case')
        (isolated/local_source).parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(original_source, isolated/local_source)
        shutil.copy2(spec_path, isolated/'spec.json')
        env = os.environ.copy()
        env['PYTHONPATH'] = str(code_root if code_root is not None else ROOT/'src')
        env['OPENBLAS_NUM_THREADS'] = '1'
        env['OMP_NUM_THREADS'] = '1'
        command = [sys.executable,'-m','vessel_reconstruction','reconstruct',str(isolated/'spec.json'),'--out',str(output_path)]
        if not export_cad: command.append('--no-cad')
        started = time.perf_counter()
        try:
            completed = subprocess.run(command,cwd=isolated,env=env,capture_output=True,text=True,timeout=timeout_seconds)
            receipt = {'return_code':completed.returncode,'wall_seconds':time.perf_counter()-started,
                       'input_files':[str(p.relative_to(isolated)) for p in isolated.rglob('*') if p.is_file()],
                       'input_spec_sha256':sha256(isolated/'spec.json'),'input_image_sha256':sha256(isolated/local_source)}
            output_path.mkdir(parents=True,exist_ok=True)
            (output_path/'inference_stdout.txt').write_text(completed.stdout)
            (output_path/'inference_stderr.txt').write_text(completed.stderr)
            if (output_path/'result.json').exists():
                receipt['result'] = json.loads((output_path/'result.json').read_text())
            else:
                receipt['result'] = {'status':'missing_result','metrics':{},'sections':[],
                    'gaps':[{'code':'subprocess_failed','message':completed.stderr[-2000:]}]}
            return receipt
        except subprocess.TimeoutExpired as exc:
            return {'return_code':None,'wall_seconds':time.perf_counter()-started,'timeout':True,
                    'input_files':[str(p.relative_to(isolated)) for p in isolated.rglob('*') if p.is_file()],
                    'result':{'status':'timeout','metrics':{},'sections':[],
                        'gaps':[{'code':'timeout','message':f'Exceeded {timeout_seconds}s'}]}}


def _snapshot_inference_code(output_dir: Path) -> tuple[Path, dict]:
    """Freeze one code tree so later workspace edits cannot mix model versions."""
    code_root = output_dir/'inference_code'
    source = ROOT/'src'/'vessel_reconstruction'
    target = code_root/'vessel_reconstruction'
    shutil.copytree(source,target,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    hashes = {str(p.relative_to(code_root)):sha256(p) for p in sorted(target.rglob('*.py'))}
    versions={}
    for name in ['cadquery','numpy','scipy','Pillow','opencv-python-headless']:
        try: versions[name]=importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError: versions[name]='unavailable'
    evaluator_hashes = {str(p.relative_to(ROOT)):sha256(p) for p in [Path(__file__).resolve(),ROOT/'benchmarks/generate.py']}
    for relative in evaluator_hashes:
        destination = output_dir/'evaluation_code'/relative
        destination.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(ROOT/relative,destination)
    evidence={'python':sys.version,'files':hashes,'evaluation_files':evaluator_hashes,'package_versions':versions,
              'source':str(source),'purpose':'Frozen before any heldout inference in this evaluation run'}
    atomic_text(output_dir/'inference_code_manifest.json',json.dumps(evidence,indent=2)+'\n')
    return code_root,evidence


def _number_summary(values):
    finite = [float(v) for v in values if v is not None and np.isfinite(v)]
    return {'n':len(finite),'mean':float(np.mean(finite)) if finite else None,
            'median':float(np.median(finite)) if finite else None,
            'maximum':max(finite) if finite else None}


def evaluate(suite_dir: str|Path, output_dir: str|Path, *, export_cad=True, timeout_seconds=90., case_ids=None, jobs=2) -> dict:
    suite_dir, output_dir = Path(suite_dir).resolve(), Path(output_dir).resolve()
    if (output_dir/'report.json').exists() or (output_dir/'cases.jsonl').exists():
        raise FileExistsError('A report already exists; use a new output directory to retain attempted results')
    manifest = verify_manifest(suite_dir)
    output_dir.mkdir(parents=True,exist_ok=True)
    selected = [c for c in manifest['cases'] if case_ids is None or c['case_id'] in case_ids]
    if not selected: raise ValueError('No cases selected')
    started = time.perf_counter()
    if not 1 <= jobs <= 4: raise ValueError('jobs must be between 1 and 4')
    code_root,code_manifest=_snapshot_inference_code(output_dir)
    records=[]
    pool=ThreadPoolExecutor(max_workers=jobs)
    futures=[pool.submit(_run_inference,suite_dir/case['spec'],output_dir/'runs'/case['case_id'],
             export_cad=export_cad,timeout_seconds=timeout_seconds,code_root=code_root) for case in selected]
    for index, case in enumerate(selected):
        spec_path = suite_dir/case['spec']; run_dir = output_dir/'runs'/case['case_id']
        try:
            receipt = futures[index].result()
        except Exception as exc:
            receipt={'return_code':None,'wall_seconds':0.,'result':{'status':'evaluation_execution_error','metrics':{},'sections':[],
                'gaps':[{'code':'execution_error','message':f'{type(exc).__name__}: {exc}'}]}}
        # Ground truth is first decoded after this case's inference has ended.
        truth=json.loads((suite_dir/case['ground_truth']).read_text())
        result=receipt.pop('result')
        gate=manifest['contract']['gates'].get(case['category'],{})
        score=score_result(result,truth,expected_outcome=case['expected_outcome'],gate=gate)
        spec=json.loads(spec_path.read_text())
        try:
            baseline=threshold_baseline(spec,spec_path.parent)
            baseline_metric=section_error_metrics(baseline['sections'],truth)
            if truth.get('reference_volume_m3') and baseline['volume_m3'] is not None:
                baseline_metric['relative_volume_error']=abs(baseline['volume_m3']-truth['reference_volume_m3'])/truth['reference_volume_m3']
            baseline={k:v for k,v in baseline.items() if k!='sections'} | {'accuracy':baseline_metric}
        except Exception as exc:
            baseline={'status':'error','error':f'{type(exc).__name__}: {exc}'}
        record={'case_id':case['case_id'],'category':case['category'],'score':score,'inference':receipt,
            'result_path':str((run_dir/'result.json').relative_to(output_dir)),
            'gaps':result.get('gaps',[]),'metrics':result.get('metrics',{}),'baseline':baseline,
            'image_sha256':case['image_sha256'],'spec_sha256':case['spec_sha256'],
            'ground_truth_sha256':case['ground_truth_sha256']}
        records.append(record)
        atomic_text(output_dir/'cases.jsonl',''.join(json.dumps(r)+'\n' for r in records))
        print(f"[{index+1}/{len(selected)}] {case['case_id']}: {score['actual_outcome']} passed={score['passed']} vol_err={score.get('relative_volume_error')}",flush=True)
    pool.shutdown(wait=True)
    groups={}
    for category in sorted({r['category'] for r in records}):
        rr=[r for r in records if r['category']==category]
        fraction=sum(r['score']['passed'] for r in rr)/len(rr)
        gate=manifest['contract']['gates'].get(category,{})
        if category in {'clean','degraded'}:
            met=fraction>=gate['minimum_pass_fraction']
        elif category=='negative': met=fraction>=gate['minimum_correct_block_fraction']
        elif category=='external': met=sum(r['score']['passed'] for r in rr)>=gate['minimum_valid_cad_cases']
        else: met=None
        groups[category]={'attempted':len(rr),'passed':sum(r['score']['passed'] for r in rr),'pass_fraction':fraction,
            'gate':gate,'gate_met':met,'relative_volume_error':_number_summary([r['score'].get('relative_volume_error') for r in rr]),
            'rms_section_error_over_beam':_number_summary([r['score'].get('rms_section_error_over_beam') for r in rr]),
            'wall_seconds':_number_summary([r['inference']['wall_seconds'] for r in rr]),
            'baseline_relative_volume_error':_number_summary([r['baseline'].get('accuracy',{}).get('relative_volume_error') for r in rr]),
            'baseline_rms_section_error_over_beam':_number_summary([r['baseline'].get('accuracy',{}).get('rms_section_error_over_beam') for r in rr])}
    report={'schema_version':'1.0','suite':manifest['suite'],'suite_manifest_sha256':sha256(suite_dir/'suite_manifest.json'),
        'frozen_contract_sha256':manifest['contract_sha256'],'total_cases_in_frozen_suite':len(manifest['cases']),
        'attempted_cases':len(records),'partial_run':len(records)!=len(manifest['cases']),
        'all_predeclared_numeric_gates_met':len(records)==len(manifest['cases']) and all(g['gate_met'] for g in groups.values() if g['gate_met'] is not None),
        'groups':groups,'records':records,'export_cad':export_cad,'total_wall_seconds':time.perf_counter()-started,
        'inference_jobs':jobs,'inference_code_manifest':code_manifest,
        'inference_code_manifest_sha256':sha256(output_dir/'inference_code_manifest.json'),
        'assistance':manifest['contract']['assistance'],
        'limitations':['Synthetic drawings include independently defined geometry but not the distribution of arbitrary shipyard scans.',
            'External DTMB tests use newly rasterized cross sections of published CAD; they are not a previously authored paper drawing.',
            'DTMB source is cropped to a single-contour supported hull region; detached bulb, actual tips and appendages are excluded.',
            'The raw historical sheet is an abstention challenge; passing that case is not successful historical reconstruction.',
            'Inference is a separate subprocess with only image/spec inputs; this is an audited data flow, not an OS access-control sandbox.',
            'Viewports, station positions, scale/origins, vertical extents, symmetry and closure are operator supplied.',
            'CAD validity and drawing accuracy are not engineering approval or evidence of as-built condition.']}
    atomic_text(output_dir/'report.json',json.dumps(report,indent=2)+'\n')
    write_report_markdown(report,output_dir/'report.md')
    csv_buffer=io.StringIO(newline='')
    writer=csv.DictWriter(csv_buffer,fieldnames=['case_id','category','status','passed','volume_error','rms_over_beam','wall_seconds','gap_codes'])
    writer.writeheader()
    for r in records: writer.writerow({'case_id':r['case_id'],'category':r['category'],'status':r['score']['actual_outcome'],
        'passed':r['score']['passed'],'volume_error':r['score'].get('relative_volume_error'),'rms_over_beam':r['score'].get('rms_section_error_over_beam'),
        'wall_seconds':r['inference']['wall_seconds'],'gap_codes':','.join(g.get('kind',g.get('code','')) for g in r['gaps'])})
    atomic_text(output_dir/'cases.csv',csv_buffer.getvalue())
    return report


def write_report_markdown(report:dict,path:Path):
    def pct(v): return '—' if v is None else f'{v:.2%}'
    lines=['# Frozen benchmark results','',f"Attempted **{report['attempted_cases']} / {report['total_cases_in_frozen_suite']}** cases. All applicable predeclared gates met: **{report['all_predeclared_numeric_gates_met']}**.",'',
        f"Frozen input manifest SHA256: `{report['suite_manifest_sha256']}`",'',
        '| Category | Attempts | Passes | Pass fraction | Mean volume error | Worst volume error | Mean section RMS / beam | Gate met |',
        '|---|---:|---:|---:|---:|---:|---:|---|']
    for name,g in report['groups'].items():
        lines.append(f"| {name} | {g['attempted']} | {g['passed']} | {pct(g['pass_fraction'])} | {pct(g['relative_volume_error']['mean'])} | {pct(g['relative_volume_error']['maximum'])} | {pct(g['rms_section_error_over_beam']['mean'])} | {g['gate_met']} |")
    lines+=['','## Data boundary and assistance','',
        'The subprocess receives only a copy of the source image and the declared specification. The evaluator reads numerical labels after reconstruction. No ground-truth points, source CAD, shape parameters or target volumes enter reconstruction. This is an input/data-flow separation, not a security sandbox.','',
        'Operator-supplied assistance: '+', '.join(report['assistance'])+'.','',
        '## Baseline','',
        'The baseline chooses the rightmost pixel darker than 120 on each of 65 rows per section using the same viewport/calibration. It has no continuity reasoning or CAD validity guarantee. All baseline abstentions/errors are retained in report.json.','',
        '| Category | Baseline numerical cases | Mean volume error | Mean section RMS / beam |',
        '|---|---:|---:|---:|']
    for name,g in report['groups'].items(): lines.append(f"| {name} | {g['baseline_relative_volume_error']['n']} | {pct(g['baseline_relative_volume_error']['mean'])} | {pct(g['baseline_rms_section_error_over_beam']['mean'])} |")
    lines+=['','## All case outcomes','',
        '| Case | Status | Pass | Volume error | Section RMS / beam | Gaps |','|---|---|---|---:|---:|---|']
    for r in report['records']:
        codes=', '.join(sorted({g.get('kind',g.get('code','')) for g in r['gaps']}))
        lines.append(f"| {r['case_id']} | {r['score']['actual_outcome']} | {r['score']['passed']} | {pct(r['score'].get('relative_volume_error'))} | {pct(r['score'].get('rms_section_error_over_beam'))} | {codes} |")
    lines+=['','## Limits','']+['- '+s for s in report['limitations']]
    atomic_text(path,'\n'.join(lines)+'\n')


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('suite',type=Path);p.add_argument('--out',type=Path,required=True)
    p.add_argument('--no-cad',action='store_true');p.add_argument('--timeout',type=float,default=90);p.add_argument('--case',action='append')
    p.add_argument('--jobs',type=int,default=2,help='Independent isolated inference processes, maximum4')
    a=p.parse_args();r=evaluate(a.suite,a.out,export_cad=not a.no_cad,timeout_seconds=a.timeout,case_ids=a.case,jobs=a.jobs)
    print(json.dumps({'report':str(a.out/'report.json'),'groups':r['groups'],'all_gates_met':r['all_predeclared_numeric_gates_met']},indent=2))

if __name__=='__main__':main()
