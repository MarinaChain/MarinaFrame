"""Scratch before/after source fingerprint runner. No evaluator truth in inference."""
import argparse
import copy
import hashlib
import json
import shutil
import sys
import tempfile
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument('--source', type=Path, required=True)
parser.add_argument('--out', type=Path, required=True)
parser.add_argument('--suite', choices=['procedural', 'factory'], required=True)
args = parser.parse_args()
sys.path.insert(0, str(args.source.resolve()))
sys.path.insert(1, str(Path.cwd()))
from vessel_reconstruction.agent_tools import inspect_source_worker
from vessel_reconstruction.ingest import extract_sections


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def fingerprint(path):
    spec = json.loads(path.read_text())
    baseline = extract_sections(spec, path.parent) if args.suite == 'procedural' else {'sections': [], 'gaps': []}
    selected = copy.deepcopy(spec)
    records = {}
    temporary_parent = Path(tempfile.mkdtemp(prefix='replay-' + args.out.stem + '-', dir='work'))
    temporary = temporary_parent / 'inspection'
    try:
        obs = inspect_source_worker(path, [s['id'] for s in spec['sections']], temporary)
        for entry in obs['sections']:
            candidates = [c for c in entry['candidates'] if c['selectable']]
            cid = entry['grid_evidence'].get('unique_non_grid_candidate_id')
            if cid is None and len(candidates) == 1:
                cid = candidates[0]['candidate_id']
            candidate = next((c for c in candidates if c['candidate_id'] == cid), None)
            records[entry['section_id']] = {'candidates': [c['candidate_id'] for c in candidates],
                'chosen': cid, 'policy_admissible': candidate is not None and candidate.get('non_grid_competing_components') == 0,
                'baseline_gaps': [g['kind'] for g in entry['baseline_gaps']],
                'rejections': [r['reason'] for r in entry.get('rejected_trace_hypotheses', [])]}
            if candidate:
                section = next(s for s in selected['sections'] if s['id'] == entry['section_id'])
                section['contour_selection'] = candidate['contour_selection']
    except Exception as exc:
        return {'error': type(exc).__name__ + ': ' + str(exc), 'all_selected': False}
    finally:
        if temporary_parent.exists():
            shutil.rmtree(temporary_parent)
    if args.suite == 'factory':
        selected['sections'] = [s for s in selected['sections'] if records[s['id']]['chosen']]
    measured = extract_sections(selected, path.parent) if selected['sections'] else {'sections': [], 'gaps': []}
    for section in spec['sections']:
        sid = section['id']
        result = next((s for s in measured['sections'] if s['id'] == sid), None)
        records[sid]['points_sha256'] = digest(result['points_yz_m']) if result and records[sid]['chosen'] else None
        records[sid]['gaps'] = [g['kind'] for g in measured['gaps'] if g['section_id'] == sid]
    return {'sections': records, 'all_selected': all(r['chosen'] for r in records.values()),
            'baseline_geometry': digest([{k: s[k] for k in ('id', 'points_yz_m')} for s in baseline['sections']]),
            'baseline_gaps': [(g['section_id'], g['kind']) for g in baseline['gaps']]}


cases = {}
if args.suite == 'procedural':
    from benchmarks.generate import procedural_sections, generate_section_sheet
    from examples.make_agent_example import make_example
    contract = json.loads(Path('benchmarks/confirmation_contract_v2.json').read_text())
    planned = [(family, seed, style) for family, seeds in contract['heldout_families'].items()
               for seed in seeds for style in ('drafting', 'degraded')]
    planned += [('development_wigley', seed, style) for seed in (17,23,41)
                for style in ('clean','degraded') if not (seed == 23 and style == 'degraded')]
    for family, seed, style in planned:
        cid = f'{family}-{seed}-{style}'
        folder = Path('work/procedural') / cid
        if not (folder / 'spec.json').exists():
            sections, volume, provenance = procedural_sections(seed, family)
            generate_section_sheet(sections, folder, vessel_id=cid, seed=seed, style=style,
                reference_volume_m3=volume, provenance=provenance,
                label_dir=Path('work/procedural-labels') / cid)
        cases[cid] = folder / 'spec.json'
    for ambiguous in (False, True):
        cid = 'agent-ambiguous' if ambiguous else 'agent'
        folder = Path('work/procedural') / cid
        if not (folder / 'spec.json').exists():
            make_example(folder, ambiguous=ambiguous)
        cases[cid] = folder / 'spec.json'
else:
    from benchmarks.llm_setup_review.sample import regenerate, frozen_cases
    from benchmarks.factory import hulls as H
    H.ROOT = Path.cwd()
    from benchmarks.factory.truth import build_truth
    frozen = frozen_cases()
    root = Path('work/factory')
    ids = [cid for cid, row in frozen.items() if row['split'] == 'development']
    grouped = {}
    for cid in ids:
        grouped.setdefault(frozen[cid]['hull_id'], []).append(cid)
    mismatches = []
    for hull, case_ids in sorted(grouped.items()):
        if any(not (root/'inputs'/cid/'spec.json').exists() for cid in case_ids):
            regenerate(case_ids, root)
        for cid in case_ids:
            for field, file in [('drawing_sha256',root/'inputs'/cid/'drawing.png'),
                                ('spec_sha256',root/'inputs'/cid/'spec.json'),
                                ('params_sha256',root/'params'/f'{cid}.json')]:
                if hashlib.sha256(file.read_bytes()).hexdigest() != frozen[cid][field]:
                    mismatches.append([cid,field])
            cases[cid] = root/'inputs'/cid/'spec.json'
        if hull in ('shipd-1-01410','shipd-2-01040','shipd-2-05051','wigley'):
            truth = root/'sealed'/'truth'/f'{hull}.npz'
            truth.parent.mkdir(parents=True,exist_ok=True)
            if not truth.exists():
                build_truth(H.load_cached(root/'hulls',hull), truth)
        print('generated', hull, flush=True)
    Path('outputs/sysser45/factory-hash-check.json').write_text(json.dumps(mismatches,indent=2))
    assert not mismatches, mismatches

from concurrent.futures import ProcessPoolExecutor, as_completed
import multiprocessing
results = json.loads(args.out.read_text()) if args.out.exists() else {}
pending = {cid: path for cid, path in cases.items() if cid not in results}
with ProcessPoolExecutor(max_workers=2, mp_context=multiprocessing.get_context('fork')) as pool:
    futures = {pool.submit(fingerprint, path): cid for cid, path in pending.items()}
    for future in as_completed(futures):
        cid = futures[future]
        results[cid] = future.result()
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(results, indent=2))
        print(cid, results[cid].get('all_selected'), results[cid].get('error',''), flush=True)
print('cases',len(results),'all_selected',sum(bool(r.get('all_selected')) for r in results.values()), flush=True)
