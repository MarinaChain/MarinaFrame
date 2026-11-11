"""Evaluation-only component scoring. Never import this module in inference.

The available Gunnerus STEP is hull-only. No superstructure truth is inferred
from the drawing or from the candidate, and missing scores remain null.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from vessel_reconstruction.ship_cad_worker import read_worker_json


def component_score(component, truth):
    result = {'presence':'built' if component.get('built') else 'missing',
              'truth_status':'available' if truth else 'no_component_truth',
              'bbox_max_error_m':None, 'volume_error_relative':None}
    if truth and component.get('built'):
        result['bbox_max_error_m'] = max(abs(component['bbox_m'][side][i]-truth['bbox_m'][side][i])
                                         for side in ('min','max') for i in range(3))
        result['volume_error_relative'] = (component['volume_m3']-truth['volume_m3'])/truth['volume_m3']
    return result


def run(args):
    latest = json.loads((args.run/'latest.json').read_text())
    task = Path(latest['task'])
    # The sandboxed worker writes only below task/work (ship_cad_worker.run).
    report = read_worker_json(task/'work', Path('output/provenance.json'))
    if report is None:
        program = json.loads(Path(latest['program']).read_text())
        report = {'components':[{**c,'built':False,'reason':'Isolated worker did not complete'}
                                 for c in program['components']],
                  'cross_view':{'status':'blocked','missing':['profile','plan','body']}}
    truth = json.loads((args.truth/'truth_load.json').read_text())
    hull_truth = {'bbox_m':{side:[v/1000 for v in truth['bbox_mm'][side]] for side in ('min','max')},
                  'volume_m3':truth['volume_mm3']/1e9}
    components = {c['id']:{'operation':c['op'], 'reason':c['reason'],
                          **component_score(c, hull_truth if c['op']=='hull' else None)}
                  for c in report['components']}
    result = {'truth_scope':'hull_only_not_complete_vessel', 'components':components,
              'engineering_approved':False, 'cross_view':report['cross_view']}
    hull = next((c for c in report['components'] if c['op']=='hull'), None)
    if hull and hull.get('built'):
        from benchmarks.gunnerus.score import score
        read = json.loads((args.run/'hull-read.json').read_text())
        stations = [{'id':s['id'],'x_m':s['x_m'],'status':'read'} for s in read['sections']]
        stations += [{**s,'status':'abstained'} for s in read['abstentions']]
        metric = json.loads(args.metric.read_text())
        # Existing scorer writes diagnostic plots. Use its metrics without
        # creating new plotting code or publishing drawing derivatives.
        hull_score = score(args.truth,task/f'output/{hull["id"]}.step',stations,metric,args.run/'hull-score')
        result['hull_metrics'] = {k:hull_score[k] for k in
            ('summary','hydrostatics_at_design_draft','between_station_half_breadth_main')}
    (args.run/'component-scores.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run',type=Path,required=True)
    parser.add_argument('--truth',type=Path,required=True)
    parser.add_argument('--metric',type=Path,default=Path('benchmarks/gunnerus/config/metric_gunnerus.json'))
    run(parser.parse_args())


if __name__ == '__main__':
    main()
