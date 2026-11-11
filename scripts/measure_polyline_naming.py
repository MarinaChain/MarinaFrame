"""Polyline station naming: score the frozen reader and the polyline product rule on nine development sheets.

Protocol and gates: docs/plans/2026-11-11-polyline-integration.md (committed before any run of the changed reader).
No model calls. Sheets: PARDON ME, BUE GIRL, C.A. Thayer, Balclutha, BUMBLE BEE (corrected sides), and the
four V-bottom sheets E. C. COLLIER, WHITE GULL, COLLEEN, CALEB JONES (development, formerly holdout; their
folders under work/holdout/ are the only holdout folders this script opens). Truth is read after both arms
have read the sheet, for scoring only.

With --baseline, the gates of the protocol are checked against an earlier result file of this script.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from measure_chine_reader_v2 import summarise  # noqa: E402
from select_hard_chine_reader import development_cases  # noqa: E402
from benchmarks.balclutha import crossing_value as cv  # noqa: E402
from benchmarks.deadrise_holdout import score as sc  # noqa: E402
from benchmarks.ec_collier import point_score as collier_points  # noqa: E402
from benchmarks.frozen_readers.v1 import body_plan_crossings as crossings  # noqa: E402
from benchmarks.frozen_readers.v1 import body_plan_reader as reader  # noqa: E402
from vessel_reconstruction import body_plan_polyline as polyline  # noqa: E402
from vessel_reconstruction import body_plan_reader as src_reader  # noqa: E402
from vessel_reconstruction import body_plan_sides  # noqa: E402

ARMS = ('frozen', 'polyline')
ROUND_BILGE = ('BUE GIRL', 'C.A. Thayer', 'Balclutha', 'BUMBLE BEE (corrected sides)')
# The four V-bottom development sheets: folder under the holdout root -> (calibration module, sheet file).
VBOTTOM_SHEETS = {
    'ec-collier': ('benchmarks.ec_collier.holdout_value', 'md1203-sheet-00002a-lines.tif'),
    'white-gull': ('benchmarks.white_gull.holdout_value', 'md1939-sheet-00001a-lines.tif'),
    'colleen': ('benchmarks.colleen.holdout_value', 'md1887-sheet-00001a-lines.tif'),
    'caleb-jones': ('benchmarks.caleb_jones.holdout_value', 'md1860-sheet-00001a-lines.tif'),
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as source:
        for block in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def table_sha256(table: dict) -> str:
    """Fingerprint of a waterline table: every key and the exact float value (repr), sorted."""
    text = '\n'.join(f'{station!r}|{label!r}|{value!r}' for (station, label), value in
                     sorted(table.items(), key=lambda item: (str(item[0][0]), str(item[0][1]))))
    return hashlib.sha256(text.encode()).hexdigest()


def read_arms(ink, layout, cal=None) -> tuple[dict, dict, dict]:
    """(tables, curves, polyline half notes) of the frozen reader and the polyline product rule, from one
    frozen reading. Curves are made only with a deadrise calibration module `cal` (point cells)."""
    frozen = cv.measure(ink, layout)
    identities = {name: reader.identities_by_rank(r.chains, r.layout.stations_outer_first)
                  for name, r in frozen.items()}
    # The polyline arm is the product entry point (`body_plan_sides`) on the frozen reading.
    product = body_plan_sides.read_sheet(ink, layout, frozen)
    halves = {name: result.half for name, result in product.items()}
    tables = {'frozen': cv.table_and_flags(frozen, identities, layout)[0],
              'polyline': {key: value for result in product.values() for key, value in result.table.items()}}
    curves = {}
    if cal is not None:
        curves = {'frozen': sc.frozen_curves(frozen, identities, layout, cal),
                  'polyline': sc.polyline_curves(halves, frozen, identities, layout, cal)}
    # The benchmark product rule (`deadrise_holdout.score`) on fresh polyline halves must give the same table.
    rule_halves = polyline.read_sheet(ink, layout)
    sc.engage(rule_halves, frozen, identities, layout, ink)
    notes = {name: {'read': half.read, 'named': [s.station for s in half.stations],
                    'engaged': [s.station for s in half.engaged], 'notes': half.notes,
                    'identity_source': {str(k): v for k, v in product[name].identity_source.items()}}
             for name, half in halves.items()}
    notes['entry_point_table_equals_rule'] = (
        tables['polyline'] == sc.polyline_table(rule_halves, frozen, identities, layout))
    notes['src_reader_unchanged_where_polyline_declines'] = src_reader_unchanged(ink, layout)
    return tables, curves, notes


def src_reader_unchanged(ink, layout) -> dict:
    """Per half, with the src crossing reader (the product's): when polyline neither reads the half nor engages a
    station, the product table and curves equal the crossing reader's rank-named table and chain paths."""
    result = {}
    for side in layout.sides:
        reading = src_reader.measure_side(ink, layout, side)
        identities = src_reader.identities_by_rank(reading.chains, side.stations_outer_first)
        table = src_reader.table_from_identities(reading, identities, layout.pixels_per_metre, layout.centre_column)
        product = body_plan_sides.read_side(ink, layout, reading)
        if product.polyline_used:
            result[side.name] = 'polyline used'
            continue
        same_curves = (set(product.curves) == set(identities.values()) and all(
            np.array_equal(product.curves[station], np.asarray(reading.chains[index].path, dtype=float).reshape(-1, 2))
            for index, station in identities.items()))
        result[side.name] = product.table == table and same_curves
    return result


def _kind_summary(result: dict) -> dict:
    given, wrong = result.get('cells_given', 0), result.get('wrong_cells', 0)
    return {'truth_cells': result.get('truth_cells'), 'cells_given': given, 'wrong_cells': wrong,
            'correct_cells': given - wrong, 'rms_m': result.get('rms_m'),
            'identity_errors': result.get('identity_errors'),
            'extra_cells': len(result.get('extra_cell_keys', []))}


def score_development_sheet(table: dict, truth: dict, scorer) -> dict:
    result = summarise(table, truth, scorer)
    result['truth_cells'] = len(truth)
    return {'waterline': _kind_summary(result)}


def score_vbottom_sheet(boat: str, table: dict, curves: dict, truth: dict, cal) -> dict:
    kinds = {'point': _kind_summary(sc.score_points(curves, truth, cal))}
    if truth['waterlines']:
        kinds['waterline'] = _kind_summary(sc.score_waterlines(table, truth, cal))
    return kinds


def sheet_totals(kinds: dict) -> dict:
    return {key: sum(k[key] for k in kinds.values()) for key in ('cells_given', 'correct_cells', 'wrong_cells')}


def run_cases(args) -> list[dict]:
    cases = []
    for name, sheet_path, truth_path, layout, load_truth, scorer in development_cases(
            args.sources, args.truth_root, args.legacy_truth_root):
        started = time.monotonic()
        ink = crossings.load_ink(sheet_path)
        tables, _, notes = read_arms(ink, layout)
        truth = load_truth(truth_path)  # read only now, after both arms have read the sheet
        cases.append(case_record(name, sha256_file(sheet_path), tables, notes,
                                 {arm: score_development_sheet(tables[arm], truth, scorer) for arm in ARMS},
                                 time.monotonic() - started))
        del ink
    for boat, (module, sheet_name) in VBOTTOM_SHEETS.items():
        cal = importlib.import_module(module)
        sheet_path = args.holdout_root / boat / sheet_name
        sheet_sha = sha256_file(sheet_path)
        if sheet_sha != cal.SHEET_SHA256:
            raise SystemExit(f'{boat}: sheet sha256 {sheet_sha} is not the calibrated sheet; stop')
        started = time.monotonic()
        ink = crossings.load_ink(sheet_path)
        layout = cal.sheet_layout()
        tables, curves, notes = read_arms(ink, layout, cal)
        truth_path = args.holdout_root / boat / 'truth.json'
        truth = ({'waterlines': {}, 'points': collier_points.load_truth(truth_path)} if boat == 'ec-collier'
                 else sc.load_truth(truth_path, cal))  # each loader checks the truth sha256
        cases.append(case_record(boat, sheet_sha, tables, notes,
                                 {arm: score_vbottom_sheet(boat, tables[arm], curves[arm], truth, cal)
                                  for arm in ARMS}, time.monotonic() - started))
        del ink
    return cases


def case_record(name, sheet_sha, tables, notes, scores, seconds) -> dict:
    record = {'sheet': name, 'sheet_sha256': sheet_sha, 'seconds': round(seconds, 1), 'polyline_halves': notes,
              'table_sha256': {arm: table_sha256(tables[arm]) for arm in ARMS},
              'polyline_table_identical_to_frozen': tables['polyline'] == tables['frozen'], 'arms': {}}
    for arm in ARMS:
        record['arms'][arm] = {'kinds': scores[arm], 'total': sheet_totals(scores[arm])}
    return record


def check_gates(cases: list[dict], baseline: list[dict]) -> dict:
    """Protocol gates: per-sheet correct cells not fewer, total wrong cells fall, round-bilge tables frozen."""
    before = {case['sheet']: case for case in baseline}
    per_sheet, wrong_before, wrong_after = {}, 0, 0
    for case in cases:
        old = before[case['sheet']]['arms']['polyline']['total']
        new = case['arms']['polyline']['total']
        wrong_before += old['wrong_cells']
        wrong_after += new['wrong_cells']
        entry = {'correct_before': old['correct_cells'], 'correct_after': new['correct_cells'],
                 'wrong_before': old['wrong_cells'], 'wrong_after': new['wrong_cells'],
                 'correct_not_fewer': new['correct_cells'] >= old['correct_cells']}
        if case['sheet'] in ROUND_BILGE:
            entry['table_identical_to_frozen'] = case['polyline_table_identical_to_frozen']
            entry['table_sha256_equals_frozen'] = case['table_sha256']['polyline'] == case['table_sha256']['frozen']
        per_sheet[case['sheet']] = entry
    passed = (all(e['correct_not_fewer'] for e in per_sheet.values()) and wrong_after < wrong_before
              and all(e.get('table_identical_to_frozen', True) and e.get('table_sha256_equals_frozen', True)
                      for e in per_sheet.values()))
    return {'per_sheet': per_sheet, 'total_wrong_before': wrong_before, 'total_wrong_after': wrong_after,
            'all_gates_pass': passed}


def check_equal(cases: list[dict], reference: list[dict]) -> dict:
    """Integration gate: the entry point gives the reference run's per-sheet totals, kinds and tables."""
    before = {case['sheet']: case for case in reference}
    per_sheet = {}
    for case in cases:
        old = before[case['sheet']]
        per_sheet[case['sheet']] = {
            'scores_equal': case['arms']['polyline'] == old['arms']['polyline'],
            'table_sha256_equal': case['table_sha256']['polyline'] == old['table_sha256']['polyline'],
            'entry_point_table_equals_rule': case['polyline_halves']['entry_point_table_equals_rule'],
            'src_reader_unchanged_where_polyline_declines':
                case['polyline_halves']['src_reader_unchanged_where_polyline_declines']}
    passed = all(e['scores_equal'] and e['table_sha256_equal'] and e['entry_point_table_equals_rule']
                 and all(v in (True, 'polyline used') for v in e['src_reader_unchanged_where_polyline_declines'].values())
                 for e in per_sheet.values())
    return {'per_sheet': per_sheet, 'all_equal': passed}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sources', required=True, type=Path)
    parser.add_argument('--truth-root', required=True, type=Path)
    parser.add_argument('--legacy-truth-root', required=True, type=Path)
    parser.add_argument('--holdout-root', required=True, type=Path, help='the work/holdout folder')
    parser.add_argument('--out', required=True, type=Path)
    parser.add_argument('--baseline', type=Path, help='an earlier result of this script: check the gates')
    parser.add_argument('--reference', type=Path, help='an earlier result of this script: check equal results')
    args = parser.parse_args()
    commit = subprocess.run(['git', 'rev-parse', 'HEAD'], capture_output=True, text=True).stdout.strip()
    report = {'engineering_approved': False, 'status': 'development cases only',
              'protocol': 'docs/plans/2026-11-11-polyline-integration.md', 'commit': commit,
              'polyline_sha256': sha256_file(Path(polyline.__file__)), 'cases': run_cases(args)}
    for case in report['cases']:
        for arm in ARMS:
            t = case['arms'][arm]['total']
            print(f"{case['sheet']:30s} {arm:9s} given {t['cells_given']:4d} correct {t['correct_cells']:4d} "
                  f"wrong {t['wrong_cells']:3d} {json.dumps(case['arms'][arm]['kinds'])}", flush=True)
        print(f"{case['sheet']:30s} polyline table identical to frozen: {case['polyline_table_identical_to_frozen']}",
              flush=True)
    if args.baseline:
        report['gates'] = check_gates(report['cases'], json.loads(args.baseline.read_text())['cases'])
        print('gates', json.dumps(report['gates'], indent=1), flush=True)
    if args.reference:
        report['equal_to_reference'] = check_equal(report['cases'], json.loads(args.reference.read_text())['cases'])
        print('equal to reference', json.dumps(report['equal_to_reference'], indent=1), flush=True)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, default=float) + '\n')


if __name__ == '__main__':
    main()
