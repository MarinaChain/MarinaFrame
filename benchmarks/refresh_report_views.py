"""Refresh readable gap labels after a report, without changing numeric results.

The running initial evaluator used gap['code']; core gap objects use 'kind'.
All original gap objects were retained in JSON. This utility preserves the
first readable report views and records a display-only correction receipt.
"""
from __future__ import annotations
import argparse
import csv
import hashlib
import json
from pathlib import Path
import shutil
from .evaluate import write_report_markdown


def refresh_report_views(report_path: str|Path):
    report_path=Path(report_path)
    root=report_path.parent
    receipt_path=root/'reporting_correction.json'
    if receipt_path.exists():
        raise FileExistsError('Report views already refreshed')
    before_hash=hashlib.sha256(report_path.read_bytes()).hexdigest()
    report=json.loads(report_path.read_text())
    originals={}
    for name in ['report.md','cases.csv']:
        source=root/name
        if source.exists():
            copy=root/(source.stem+'.before_gap_label_correction'+source.suffix)
            shutil.copy2(source,copy)
            originals[name]={'preserved_as':copy.name,'sha256':hashlib.sha256(source.read_bytes()).hexdigest()}
    write_report_markdown(report,root/'report.md')
    with (root/'cases.csv').open('w',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=['case_id','category','status','passed','volume_error','rms_over_beam','wall_seconds','gap_codes'])
        writer.writeheader()
        for r in report['records']:
            writer.writerow({'case_id':r['case_id'],'category':r['category'],'status':r['score']['actual_outcome'],
                'passed':r['score']['passed'],'volume_error':r['score'].get('relative_volume_error'),
                'rms_over_beam':r['score'].get('rms_section_error_over_beam'),'wall_seconds':r['inference']['wall_seconds'],
                'gap_codes':','.join(sorted({g.get('kind',g.get('code','')) for g in r['gaps']}))})
    assert before_hash==hashlib.sha256(report_path.read_bytes()).hexdigest()
    receipt={'reason':'Readable gap labels corrected from code-only to kind with code fallback; all original JSON gap objects were already preserved.',
        'numeric_report_unchanged_sha256':before_hash,'preserved_views':originals,
        'updated_views':{n:hashlib.sha256((root/n).read_bytes()).hexdigest() for n in ['report.md','cases.csv']},
        'evaluation_source_snapshot_preserved':'evaluation_code/benchmarks/evaluate.py',
        'display_renderer_sha256':hashlib.sha256((Path(__file__).parent/'evaluate.py').read_bytes()).hexdigest()}
    receipt_path.write_text(json.dumps(receipt,indent=2)+'\n')
    return receipt

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('report',type=Path)
    args=parser.parse_args()
    print(json.dumps(refresh_report_views(args.report),indent=2))
