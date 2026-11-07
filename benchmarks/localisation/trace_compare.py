"""Score the existing deterministic draft's best source-supported stroke.

This is not an approved trace. Keep strict-tracer abstention and draft-choice
errors separate. No truth enters candidate generation or ranking.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor
import json
from pathlib import Path

import numpy as np

from benchmarks.llm_setup_review.sample import SETUP_SAMPLE_HULLS
from vessel_reconstruction.agent_tools import inspect_source_worker
from vessel_reconstruction.draft import candidate_score
from vessel_reconstruction.llm_setup import write_json


def one(job):
    case, root, out = job
    directory = root / 'inputs' / case
    params = json.loads((root / 'params' / (case + '.json')).read_text())
    if params['split'] != 'development':
        raise ValueError('Development only')
    spec = json.loads((directory / 'spec.json').read_text())
    evidence = inspect_source_worker(directory / 'spec.json', ['s03', 's07'], out / case)
    rows = []
    for entry in evidence['sections']:
        candidates = [c for c in entry['candidates'] if c.get('selectable')]
        best = max(candidates, key=candidate_score) if candidates else None
        section = next(s for s in spec['sections'] if s['id'] == entry['section_id'])
        calibration = section['calibration']
        curve = None
        if best:
            points = np.asarray(best['source_points_px'])
            curve = np.column_stack([(points[:,0]-calibration['centerline_px'])/calibration['pixels_per_metre'],
                                     (calibration['baseline_px']-points[:,1])/calibration['pixels_per_metre']])
        rows.append({'case_id':case,'station':entry['section_id'],'candidate_id':best['candidate_id'] if best else None,
                     'score':candidate_score(best) if best else None,
                     'points_yz_m':curve.tolist() if curve is not None else None,
                     'status':'unverified_deterministic_draft' if best else 'no_candidate'})
    write_json(out/(case+'.json'),rows)
    return rows


def safe_one(job):
    try:
        return one(job)
    except Exception as error:
        case, _, out = job
        rows = [{'case_id': case, 'station': sid, 'points_yz_m': None,
                 'status': 'inspection_failed', 'error': str(error)} for sid in ['s03', 's07']]
        write_json(out / (case + '.json'), rows)
        return rows


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args()
    args.out.mkdir(parents=True,exist_ok=False)
    jobs=[(f'{h}-L{l}',args.root,args.out) for h in SETUP_SAMPLE_HULLS for l in range(4)]
    with ProcessPoolExecutor(max_workers=2) as pool:
        rows=[r for group in pool.map(safe_one,jobs) for r in group]
    write_json(args.out/'results.json',rows)


if __name__=='__main__':
    main()
