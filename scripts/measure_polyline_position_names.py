"""One fixed nine-sheet comparison, all predictions before any truth load.

Protocol: docs/plans/2026-11-12-polyline-naming.md, label amendment 52cecb4.
Run predict then score. Never overwrite an existing campaign directory.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import pickle
import subprocess
import sys

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from select_hard_chine_reader import development_cases
from measure_polyline_naming import VBOTTOM_SHEETS
from measure_chine_reader_v2 import summarise
from benchmarks.balclutha import crossing_value as cv
from benchmarks.deadrise_holdout import score as sc
from benchmarks.ec_collier import point_score as collier_points
from benchmarks.frozen_readers.v1 import body_plan_crossings as crossings
from benchmarks.frozen_readers.v1 import body_plan_reader as frozen
from benchmarks.hard_chine import reader_v2
from vessel_reconstruction import body_plan_polyline as polyline
from vessel_reconstruction import station_number_images as labels

ARMS = ('position_labels', 'polyline_v11', 'current', 'reader_v2')


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, data):
    Path(path).write_text(json.dumps(data, indent=2, default=lambda value: value.item()
                                   if isinstance(value, np.generic) else str(value), allow_nan=False) + '\n')


def historical_module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def cases(root):
    for name, sheet, truth, layout, loader, scorer in development_cases(root / 'sources', root / 'dev-truth', root / 'dev-truth'):
        yield name, sheet, truth, layout, loader, scorer, None
    for boat, (module, sheet_name) in VBOTTOM_SHEETS.items():
        cal = __import__(module, fromlist=['sheet_layout'])
        yield boat, root / 'dev-truth' / boat / sheet_name, root / 'dev-truth' / boat / 'truth.json', cal.sheet_layout(), None, None, cal


def read_labels(binary, sheet, layout, out):
    rows = list(layout.waterline_rows.values())
    span = max(rows) - min(rows)
    body_box = (layout.centre_column - layout.max_offset_px, min(rows) - span,
                layout.centre_column + layout.max_offset_px, max(rows) + span)
    manifest = labels.prepare(sheet, out / 'request', body_box)
    result = subprocess.run([str(binary), 'vision-request', '--request', str(out / 'request'),
                             '--out', str(out / 'provider'),
                             '--provider-transfer-basis', 'User approved development body-plan station-label extraction'],
                            capture_output=True, text=True)
    (out / 'controller.stdout').write_text(result.stdout)
    (out / 'controller.stderr').write_text(result.stderr)
    path = out / 'provider/vision_reading.json'
    reading = json.loads(path.read_text()) if path.exists() else {'reply': None, 'receipts': []}
    if not path.exists():
        reading['receipts'] = [json.loads(path.read_text()) for path in sorted((out / 'provider/receipts').glob('*.json'))]
    receipts = reading.get('receipts', [])
    if len(receipts) > 2:
        raise RuntimeError('request budget exceeded; stop campaign')
    reply = (reading.get('reply') or {}).get('station_numbers') or {}
    items = reply.get('items', [])
    mapped = labels.deduplicate([labels.map_item(item, manifest) for item in items])
    write(out / 'mapped_labels.json', {'items': mapped, 'reply_refused': not bool(reply),
                                      'rejected': reply.get('rejected', []), 'receipts': receipts})
    return mapped, receipts


def predict(args):
    if not args.resume:
        args.out.mkdir(parents=True, exist_ok=False)
    elif not args.out.is_dir():
        raise RuntimeError('cannot resume absent campaign')
    # Freeze historical source from git before running; never modify the frozen baseline.
    historic = args.out / 'polyline_v11.py'
    if not args.resume:
        historic.write_bytes(subprocess.check_output(['git', 'show', 'd026adb:src/vessel_reconstruction/body_plan_polyline.py']))
    old = historical_module(historic, 'campaign_polyline_v11')
    source_paths = sorted(Path('src/vessel_reconstruction').glob('*.py')) + [Path(__file__)]
    source_hashes = {str(path): digest(path) for path in source_paths}
    freeze = {'source_sha256': source_hashes, 'binary_sha256': digest(args.binary),
              'historic_sha256': digest(historic)}
    freeze_path = args.out / 'source_freeze.json'
    if args.resume:
        if json.loads(freeze_path.read_text()) != freeze:
            raise RuntimeError('campaign source or binary changed; refuse resume')
    else:
        write(freeze_path, freeze)
    predictions, total_requests = [], 0
    for index, (name, sheet, truth_path, layout, loader, scorer, cal) in enumerate(cases(args.work_root)):
        if index >= args.limit:
            break
        print(f'{name}: predictions (truth unopened)', flush=True)
        case_out = args.out / f'case{index}'
        saved = case_out / 'predictions.pickle'
        if saved.exists():
            # Only our own campaign output is loaded; never unpickle provider data.
            with saved.open('rb') as stream:
                record = pickle.load(stream)
            predictions.append(record)
            total_requests += len(record['receipts'])
            continue
        case_out.mkdir()
        if cal and digest(sheet) != cal.SHEET_SHA256:
            raise RuntimeError(f'{name}: calibrated image hash mismatch')
        items, receipts = read_labels(args.binary, sheet, layout, case_out)
        total_requests += len(receipts)
        if total_requests > 18:
            raise RuntimeError('campaign request budget exceeded')
        ink = crossings.load_ink(sheet)
        readings = cv.measure(ink, layout)
        identities = {key: frozen.identities_by_rank(reading.chains, reading.layout.stations_outer_first)
                      for key, reading in readings.items()}
        halves = polyline.read_sheet(ink, layout)
        sc.engage(halves, readings, identities, layout, ink)
        old_halves = old.read_sheet(ink, layout)
        existing = sc.frozen_half_tables(readings, identities, layout)
        for side in layout.sides:
            old.engage_stations(old_halves[side.name], side, existing[side.name], layout, ink)
        # Existing scoring helpers call the current module for table assembly;
        # use the historical half_table for v1.1 to preserve its product rule.
        tables = {'current': sc.polyline_table(halves, readings, identities, layout),
                  'polyline_v11': {key: value for side in layout.sides for key, value in
                                   old.half_table(old_halves[side.name], existing[side.name], layout).items()}}
        labelled, notes = {}, {}
        for side in layout.sides:
            labelled[side.name], notes[side.name] = labels.name_half(halves[side.name], side, items, layout)
        tables['position_labels'] = sc.polyline_table(labelled, readings, identities, layout)
        v2 = reader_v2.read_sheet(ink, layout, readings)
        tables['reader_v2'] = reader_v2.sheet_table(v2, layout)[0]
        curves = {}
        if cal:
            curves = {'current': sc.polyline_curves(halves, readings, identities, layout, cal),
                      'polyline_v11': sc.polyline_curves(old_halves, readings, identities, layout, cal),
                      'position_labels': sc.polyline_curves(labelled, readings, identities, layout, cal),
                      'reader_v2': sc.v2_curves(v2, layout, cal)}
        record = {'sheet': name, 'sheet_sha256': digest(sheet), 'truth_path': str(truth_path),
                  'tables': tables, 'curves': curves, 'notes': notes, 'receipts': receipts,
                  'position_named': sorted({station.station for half in labelled.values() for station in half.stations})}
        predictions.append(record)
        with (case_out / 'predictions.pickle').open('wb') as stream:
            pickle.dump(record, stream)
        del ink
    # Local pickle is produced by this runner, never downloaded or model-supplied.
    with (args.out / 'predictions.pickle').open('wb') as stream:
        pickle.dump(predictions, stream)
    write(args.out / 'prediction_manifest.json', {'commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip(),
          'binary_sha256': digest(args.binary), 'historic_sha256': digest(historic),
          'predictions_sha256': digest(args.out / 'predictions.pickle'), 'requests': total_requests,
          'truth_loaded': False, 'all_nine_predicted': len(predictions) == 9, 'engineering_approved': False})


def compact(result, truth_count):
    given, wrong = result.get('cells_given', 0), result.get('wrong_cells', 0)
    return {'truth_cells': truth_count, 'given': given, 'correct': given - wrong, 'wrong': wrong,
            'rms_m': result.get('rms_m'), 'max_m': result.get('max_abs_m', result.get('max_error_m')),
            'identity_errors': result.get('identity_errors', []),
            'missing': result.get('missing_cells', truth_count - given),
            'extra': result.get('extra_cell_keys', [])}


def score(args):
    if (args.out / 'result.json').exists():
        raise RuntimeError('already scored; do not repeat')
    manifest = json.loads((args.out / 'prediction_manifest.json').read_text())
    if not manifest['all_nine_predicted'] or digest(args.out / 'predictions.pickle') != manifest['predictions_sha256']:
        raise RuntimeError('all-nine prediction freeze missing')
    with (args.out / 'predictions.pickle').open('rb') as stream:
        predictions = pickle.load(stream)
    results = []
    for prediction, case in zip(predictions, cases(args.work_root)):
        name, _, truth_path, layout, loader, scorer, cal = case
        if name != prediction['sheet']:
            raise RuntimeError('case order changed')
        truth = (loader(truth_path) if cal is None else
                 {'waterlines': {}, 'points': collier_points.load_truth(truth_path)} if name == 'ec-collier'
                 else sc.load_truth(truth_path, cal))
        arms = {}
        for arm in ARMS:
            table = prediction['tables'][arm]
            if cal is None:
                kinds = {'waterline': compact(summarise(table, truth, scorer), len(truth))}
            else:
                point_score = sc.score_points(prediction['curves'][arm], truth, cal)
                kinds = {'point': compact(point_score, point_score['truth_cells'])}
                if truth['waterlines']:
                    wl = sc.score_waterlines(table, truth, cal)
                    kinds['waterline'] = compact(wl, sum(value is not None for value in truth['waterlines'].values()))
            arms[arm] = kinds
        result = {'sheet': name, 'arms': arms, 'unnamed_sections': sum(n['unnamed_sections'] for n in prediction['notes'].values()),
                  'position_named': prediction['position_named'], 'notes': prediction['notes'],
                  'truth_sha256': digest(truth_path), 'receipts': prediction['receipts']}
        results.append(result)
        print(name, json.dumps(arms), flush=True)
    totals = {}
    for arm in ARMS:
        kinds = [kind for case in results for kind in case['arms'][arm].values()]
        given = sum(kind['given'] for kind in kinds)
        totals[arm] = {key: sum(kind[key] for kind in kinds) for key in ('given', 'correct', 'wrong')}
        totals[arm]['rms_m'] = math.sqrt(sum(kind['given'] * (kind['rms_m'] or 0.) ** 2 for kind in kinds) / given) if given else None
    identity_failures = {case['sheet']: sorted({station for kind in case['arms']['position_labels'].values()
                        for station in kind['identity_errors'] if station in case['position_named']}) for case in results}
    accepted = (totals['position_labels']['correct'] >= totals['polyline_v11']['correct']
                and totals['position_labels']['wrong'] <= totals['current']['wrong']
                and not any(identity_failures.values()))
    receipts = [receipt for prediction in predictions for receipt in prediction['receipts']]
    observed = [receipt.get('observed_cost_usd') for receipt in receipts]
    estimates = [(receipt.get('usage') or {}).get('list_cost') for receipt in receipts]
    usage = {'requests': len(receipts),
             'prompt_tokens': sum((receipt.get('usage') or {}).get('prompt_tokens', 0) for receipt in receipts),
             'completion_tokens': sum((receipt.get('usage') or {}).get('completion_tokens', 0) for receipt in receipts),
             'observed_cost_usd': sum(observed) if all(value is not None for value in observed) else None,
             'requests_without_observed_cost': sum(value is None for value in observed),
             'list_cost_usd': sum(estimates) if all(value is not None for value in estimates) else None}
    report = {'engineering_approved': False, 'cases': results, 'totals': totals, 'usage': usage,
              'naming_identity_errors': identity_failures, 'accepted': accepted, 'prediction_manifest': manifest}
    write(args.out / 'result.json', report)
    print(json.dumps({'totals': totals, 'accepted': accepted, 'naming_identity_errors': identity_failures}), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase', choices=['predict', 'score'])
    parser.add_argument('--work-root', required=True, type=Path)
    parser.add_argument('--out', required=True, type=Path)
    parser.add_argument('--binary', type=Path)
    parser.add_argument('--limit', type=int, default=9, help='prediction checkpoint only; scoring requires nine')
    parser.add_argument('--resume', action='store_true', help='reuse completed predictions without new requests')
    args = parser.parse_args()
    (predict if args.phase == 'predict' else score)(args)


if __name__ == '__main__':
    main()
