"""Aggregate W14 evidence without dropping failures or missing measurements."""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path

import numpy as np

from vessel_reconstruction.llm_setup import digest, write_json


def stats(values):
    values = [v for v in values if v is not None]
    return {'n': len(values), 'median': float(np.median(values)) if values else None,
            'p90': float(np.percentile(values, 90)) if values else None}


def receipts(root):
    unique = {}
    for path in root.rglob('receipts/*.json'):
        try:
            record = json.loads(path.read_text())
        except (ValueError, OSError):
            continue
        if record.get('protocol') != 'marinaframe.provider.v1':
            continue
        request_id = record['request_id']
        if request_id in unique:
            if unique[request_id]['receipt_sha256'] != digest(path):
                raise ValueError('Conflicting provider receipt: ' + request_id)
            continue
        unique[request_id] = {'receipt_path': str(path), 'receipt_sha256': digest(path), **record}
    return list(unique.values())


def usage(rows):
    return {'calls': len(rows), 'states': dict(Counter(r['state'] for r in rows)),
            'prompt_tokens': sum(r.get('usage', {}).get('prompt_tokens', 0) for r in rows),
            'completion_tokens': sum(r.get('usage', {}).get('completion_tokens', 0) for r in rows),
            'observed_cost_usd': sum(r.get('observed_cost_usd') or 0 for r in rows),
            'list_cost_usd': sum(r.get('usage', {}).get('list_cost', 0) or 0 for r in rows),
            'images': sum(len(r.get('images', [])) for r in rows),
            'missing_usage': sum(not r.get('usage') for r in rows)}


def calibration(root):
    rows = [json.loads(p.read_text()) for p in root.glob('*/score.json')]
    table = []
    for size in sorted({tuple(r['size']) for r in rows}):
        for mode in sorted({r['mode'] for r in rows}):
            group = [r for r in rows if tuple(r['size']) == size and r['mode'] == mode]
            errors = [v for r in group for v in r['errors_px']]
            fitted = [r['fit']['rms_px'] for r in group if r['fit']]
            table.append({'size': size, 'mode': mode, 'requests': len(group), 'planned_marks': len(group)*6,
                          'error_px': stats(errors), 'fraction_long_side': stats([v/max(size) for v in errors]),
                          'in_sample_fit_rms_px': stats(fitted), 'fits': [r['fit'] for r in group]})
    return table


def drawing_table(rows):
    table = []
    for layout in ['separate', 'overlay']:
        for level in range(4):
            for mode in ['sheet', 'crop']:
                group = [r for r in rows if r['layout'] == layout and r['level'] == level and r['mode'] == mode]
                # Combined-request scale answers are contaminated by supplied
                # calibration. Independent scale.py results are scored separately.
                # Frozen sample: seven separate and three overlay hulls, two
                # stations and two heights each. Driver failures remain missing.
                planned = (7 if layout == 'separate' else 3) * 4
                table.append({'layout': layout, 'level': level, 'mode': mode, 'planned': planned,
                              'retained_rows': len(group),
                              'truth_present': sum(r['truth_half_breadth_m'] is not None for r in group),
                              'position_px': stats([r['position_error_px'] for r in group]),
                              'half_breadth_m': stats([r['half_breadth_error_m'] for r in group]),
                              'tracer_m': stats([r['tracer_error_m'] for r in group]),
                              'draft_m': stats([r.get('draft_error_m') for r in group]),
                              'combined_scale_excluded': True})
    return table


def setup_table(root, factory):
    case_results = json.loads((root/'results.json').read_text())
    corners, centres, bases, scales = [], [], [], []
    exact_counts = layout_correct = retained = 0
    for row in case_results:
        if row.get('error'):
            continue
        layout_correct += (row.get('layout_proposed') == ('separate_panels' if row['layout_truth']=='separate' else 'overlaid_body_plan'))
        proposal = root / row['case_id'] / 'proposal.json'
        if not proposal.exists():
            continue
        retained += 1
        if row['layout_truth'] != 'separate':
            continue
        truth = json.loads((factory/'inputs'/row['case_id']/'spec.json').read_text())
        overview = json.loads(proposal.read_text())['overview']
        exact_counts += len(overview.get('panels', [])) == len(truth['sections'])
        for panel, target in zip(overview.get('panels', []), truth['sections']):
            corners.extend(abs(a-b) for a,b in zip(panel['box_px'], target['roi_px']))
        for value in row['values']:
            centres.append(value['centreline_x_px']['absolute_error_px'])
            bases.append(value['baseline_y_px']['absolute_error_px'])
            scales.append(value['pixels_per_metre']['relative_error'])
    return {'cases':len(case_results),'driver_errors':sum(bool(r.get('error')) for r in case_results),
            'retained':retained,'layout_correct':layout_correct,'exact_separate_panel_counts':exact_counts,
            'panel_corner_px':stats(corners),'centreline_px':stats(centres),'baseline_px':stats(bases),'scale_relative':stats(scales)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,default=Path('work/w14'))
    parser.add_argument('--out',type=Path,default=Path('outputs/w14'))
    args=parser.parse_args()
    args.out.mkdir(parents=True,exist_ok=True)
    records=receipts(args.root)
    # Read the provider's actual usage shape before assigning list-cost totals.
    groups={}
    for name in ['calibration','calibration-v3','calibration-extra','diagnostic','ruler-probe','setup-normalized','setup-rejected-reruns','drawing-localisation','scale-independent','w11']:
        group=[r for r in records if str(args.root/name)+'/' in r['receipt_path']]
        groups[name]=usage(group)
    # Inventory keeps full typed receipts; request manifests bind image transforms.
    write_json(args.out/'receipt_inventory.json',records)
    write_json(args.out/'usage.json',{'groups':groups,'total':usage(records)})
    for name in ['calibration-v3','calibration-extra']:
        if (args.root/name).exists():write_json(args.out/(name+'-summary.json'),calibration(args.root/name))
    if (args.root/'drawing-localisation/results.json').exists():
        rows=json.loads((args.root/'drawing-localisation/results.json').read_text())
        draft_path = args.root / 'draft-trace-final/results.json'
        if draft_path.exists():
            from benchmarks.localisation.drawings import crossing
            drafts = {(r['case_id'], r['station']): r for r in json.loads(draft_path.read_text())}
            for row in rows:
                draft = drafts.get((row['case_id'], row['station']), {})
                points = draft.get('points_yz_m')
                value = crossing([np.asarray(points)], row['height_m']) if points else None
                target = row['truth_half_breadth_m']
                row['draft_half_breadth_m'] = value
                row['draft_error_m'] = abs(value-target) if value is not None and target is not None else None
                row['draft_status'] = draft.get('status')
        write_json(args.out/'localisation-results.json',rows)
        write_json(args.out/'localisation-summary.json',drawing_table(rows))
    if (args.root/'setup-normalized/results.json').exists():
        write_json(args.out/'setup-summary.json',setup_table(args.root/'setup-normalized',args.root/'factory'))


if __name__=='__main__':
    main()
