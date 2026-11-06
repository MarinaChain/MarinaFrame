"""Create and hash a fixed suite; never silently overwrite frozen inputs."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import shutil
from .generate import generate_section_sheet, procedural_sections, sha256

ROOT=Path(__file__).resolve().parents[1]
CONTRACT=Path(__file__).with_name('holdout_contract.json')


def make_suite(output_dir: str|Path, *, suite: str='holdout', include_external: bool=True, contract_path: str|Path|None=None) -> dict:
    out=Path(output_dir)
    if (out/'suite_manifest.json').exists():
        raise FileExistsError('A frozen manifest already exists; choose a new destination, never silently rewrite evaluation inputs')
    out.mkdir(parents=True,exist_ok=True)
    with (out/'generation.lock').open('x') as lock:
        lock.write('This destination is reserved. Use a new directory after any failed/incomplete generation.\n')
    contract_file=Path(contract_path) if contract_path is not None else CONTRACT
    contract=json.loads(contract_file.read_text())
    cases=[]
    def add(case_id, sections, volume, provenance, style, category, seed, **kwargs):
        receipt=generate_section_sheet(sections,out/'inference'/case_id,vessel_id=case_id,
            seed=seed,style=style,reference_volume_m3=volume,provenance=provenance,
            label_dir=out/'private_labels'/case_id,**kwargs)
        cases.append({'case_id':case_id,'category':category,'expected_outcome':'reconstruct',
            'spec':str(Path(receipt['spec']).relative_to(out)),
            'ground_truth':str(Path(receipt['ground_truth']).relative_to(out)),
            'image_sha256':receipt['image_sha256'],'spec_sha256':receipt['spec_sha256']})
        return cases[-1]
    families=contract['heldout_families'] if suite=='holdout' else {contract['development_family']:contract['development_seeds']}
    for family,seeds in families.items():
        for seed in seeds:
            sections,volume,provenance=procedural_sections(seed,family)
            for style in (contract['render_styles'] if suite=='holdout' else ['clean','degraded']):
                case_id=f'{family}-{seed}-{style}'
                add(case_id,sections,volume,provenance,style,'degraded' if style=='degraded' else 'clean',seed)
    if suite=='holdout':
        sections,volume,provenance=procedural_sections(contract.get('negative_geometry_seed',104729),'holdout_multichine')
        for kind in contract['negatives']:
            cid=f'negative-{kind}'
            c=add(cid,sections,volume,provenance,'clean','negative',contract.get('negative_render_seed',8675309),
                  missing_curve_index=12 if kind=='missing_curve' else None)
            spec_path=out/c['spec'];spec=json.loads(spec_path.read_text())
            if kind=='missing_scale': spec['sections'][12].pop('calibration')
            elif kind=='negative_scale': spec['sections'][12]['calibration']['pixels_per_metre']=-10
            elif kind=='insufficient_sections': spec['sections']=spec['sections'][:1]
            spec_path.write_text(json.dumps(spec,indent=2)+'\n')
            c['expected_outcome']='blocked';c['negative_kind']=kind;c['spec_sha256']=sha256(spec_path)
            truth_path=out/c['ground_truth'];truth=json.loads(truth_path.read_text())
            truth.update(expected_outcome='blocked',negative_kind=kind,spec_sha256=c['spec_sha256'])
            truth_path.write_text(json.dumps(truth,indent=2)+'\n')
    if include_external:
        reference_path=ROOT/'data/external/dtmb5415/reference_sections.json'
        if not reference_path.exists(): raise FileNotFoundError('Run python -m benchmarks.external_hull before including external reference')
        reference=json.loads(reference_path.read_text())
        for style in ['clean','degraded']:
            add(f'external-dtmb5415-{style}',reference['sections'],reference['reference_volume_m3'],
                reference['provenance'],style,'external',contract.get('external_render_seed',382194),
                source_url=reference['provenance']['source_url'],source_license='MIT')
    if suite=='holdout':
        historical=ROOT/'data/external/balclutha/body_plan_sheet_7.tif'
        if historical.exists():
            cid='historical-balclutha-unannotated';folder=out/'inference'/cid;folder.mkdir(parents=True,exist_ok=True)
            shutil.copy2(historical,folder/'drawing.tif')
            source=json.loads(historical.with_name('source_manifest.json').read_text())
            spec={'schema_version':'1.0','vessel_id':cid,'source':{'file':'drawing.tif','url':source['landing_page'],'license':source['license']},'units':'m','symmetry':'port_starboard','symmetry_evidence':'Not established automatically from this historical sheet.','end_closure':'flat_at_terminal_stations','sections':[],'components':[]}
            (folder/'spec.json').write_text(json.dumps(spec,indent=2)+'\n')
            labels=out/'private_labels'/cid;labels.mkdir(parents=True,exist_ok=True)
            (labels/'ground_truth.json').write_text(json.dumps({'expected_outcome':'blocked','source_provenance':source,'evaluation_note':'Raw independently authored historical drawing with overlapping curves and a table; unannotated drawing is outside the supported single-contour calibrated-panel contract. No numeric accuracy claimed.'},indent=2)+'\n')
            cases.append({'case_id':cid,'category':'historical_challenge','expected_outcome':'blocked','spec':str((folder/'spec.json').relative_to(out)),'ground_truth':str((labels/'ground_truth.json').relative_to(out)),'image_sha256':sha256(folder/'drawing.tif'),'spec_sha256':sha256(folder/'spec.json')})
    for c in cases:
        c['ground_truth_sha256']=sha256(out/c['ground_truth'])
    manifest={'schema_version':'1.0','suite':contract.get('suite_name',suite),'contract_sha256':sha256(contract_file),'contract':contract,'cases':cases,'case_count':len(cases),'label_visibility':'private_labels is evaluation-only; inference copies receive no label files'}
    (out/'suite_manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    (out/'suite_manifest.sha256').write_text(sha256(out/'suite_manifest.json')+'  suite_manifest.json\n')
    return manifest


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--out',type=Path,required=True);p.add_argument('--suite',choices=['development','holdout'],default='holdout');p.add_argument('--without-external',action='store_true');p.add_argument('--contract',type=Path);a=p.parse_args()
    m=make_suite(a.out,suite=a.suite,include_external=not a.without_external,contract_path=a.contract)
    print(json.dumps({'out':str(a.out),'cases':len(m['cases']),'manifest_sha256':sha256(a.out/'suite_manifest.json')},indent=2))
if __name__=='__main__':main()
