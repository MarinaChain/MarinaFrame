"""Polyline engagement on hard-chine sheets: score the frozen reader and the polyline product rule on eleven
development sheets.

Protocol and gates: docs/plans/2026-11-12-polyline-engage.md (committed before any change to the reader).
No model calls. The nine sheets of `measure_polyline_naming.py` plus CAMA BEACH SKIFF No. 22 (hard chine) and the
14'-3" Davis Boat (round bilge). Both were holdouts, run once on 2026-11-11, and are now spent
(`benchmarks/spent_real_sheet_holdouts.json`): their numbers here are development numbers, not holdout numbers.
Truth is read after both arms have read a sheet, for scoring only.

With --baseline, the gates of the protocol are checked against an earlier result file of this script.
"""
from __future__ import annotations

import argparse
import importlib
import json
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import measure_polyline_naming as naming  # noqa: E402
from benchmarks.deadrise_holdout import score as sc  # noqa: E402
from benchmarks.frozen_readers.v1 import body_plan_crossings as crossings  # noqa: E402
from vessel_reconstruction import body_plan_polyline as polyline  # noqa: E402

ARMS = naming.ARMS
# The two spent published holdouts: folder under the holdout root -> (calibration module, sheet file).
SPENT_PUBLISHED_SHEETS = {
    'cama_beach_skiff_22': ('benchmarks.cama_beach_skiff_22.holdout_value',
                            'master-pnp-habshaer-wa-wa0800-wa0881-sheet-00001a.tif'),
    'davis_boat': ('benchmarks.davis_boat.holdout_value', 'master-pnp-habshaer-wa-wa0900-wa0928-sheet-00001a.tif'),
}
ROUND_BILGE = naming.ROUND_BILGE + ('davis_boat',)


def run_development_sheets(args, baseline: dict) -> list[dict]:
    """The five waterline development sheets, as `measure_polyline_naming.run_cases` scores them.

    A truth file that is missing (the legacy truth of two round-bilge sheets was deleted from a shared
    scratchpad on 2026-11-12) is not needed when both arms give the baseline's tables byte for byte: equal
    tables give equal scores, so the baseline's scores are carried over and the record says so. Otherwise the
    run stops.
    """
    cases = []
    for name, sheet_path, truth_path, layout, load_truth, scorer in naming.development_cases(
            args.sources, args.truth_root, args.legacy_truth_root):
        started = time.monotonic()
        ink = crossings.load_ink(sheet_path)
        tables, _, notes = naming.read_arms(ink, layout)
        del ink
        if truth_path.exists():
            truth = load_truth(truth_path)  # read only now, after both arms have read the sheet
            scores = {arm: naming.score_development_sheet(tables[arm], truth, scorer) for arm in ARMS}
        else:
            old = baseline.get(name)
            same = old is not None and all(naming.table_sha256(tables[arm]) == old['table_sha256'][arm] for arm in ARMS)
            if not same:
                raise SystemExit(f'{name}: truth {truth_path} is missing and the tables differ from the baseline; stop')
            scores = {arm: old['arms'][arm]['kinds'] for arm in ARMS}
            notes['scores_carried_from_baseline'] = f'truth file missing ({truth_path}); tables equal the baseline'
        cases.append(naming.case_record(name, naming.sha256_file(sheet_path), tables, notes, scores,
                                        time.monotonic() - started))
    return cases


def run_vbottom_sheets(args) -> list[dict]:
    """The four V-bottom development sheets, as `measure_polyline_naming.run_cases` scores them."""
    cases = []
    for boat, (module, sheet_name) in naming.VBOTTOM_SHEETS.items():
        cal = importlib.import_module(module)
        sheet_path = args.holdout_root / boat / sheet_name
        sheet_sha = naming.sha256_file(sheet_path)
        if sheet_sha != cal.SHEET_SHA256:
            raise SystemExit(f'{boat}: sheet sha256 {sheet_sha} is not the calibrated sheet; stop')
        started = time.monotonic()
        ink = crossings.load_ink(sheet_path)
        tables, curves, notes = naming.read_arms(ink, cal.sheet_layout(), cal)
        del ink
        truth_path = args.holdout_root / boat / 'truth.json'
        truth = ({'waterlines': {}, 'points': naming.collier_points.load_truth(truth_path)} if boat == 'ec-collier'
                 else sc.load_truth(truth_path, cal))  # each loader checks the truth sha256
        cases.append(naming.case_record(boat, sheet_sha, tables, notes,
                                        {arm: naming.score_vbottom_sheet(boat, tables[arm], curves[arm], truth, cal)
                                         for arm in ARMS}, time.monotonic() - started))
    return cases


def run_spent_published(args) -> list[dict]:
    cases = []
    for boat, (module, sheet_name) in SPENT_PUBLISHED_SHEETS.items():
        cal = importlib.import_module(module)
        sheet_path = args.holdout_root / boat / sheet_name
        sheet_sha = naming.sha256_file(sheet_path)
        if sheet_sha != cal.SHEET_SHA256:
            raise SystemExit(f'{boat}: sheet sha256 {sheet_sha} is not the calibrated sheet; stop')
        started = time.monotonic()
        ink = crossings.load_ink(sheet_path)
        tables, curves, notes = naming.read_arms(ink, cal.sheet_layout(), cal)
        truth = sc.load_truth(args.holdout_root / boat / 'truth.json', cal)  # checks the truth sha256
        cases.append(naming.case_record(boat, sheet_sha, tables, notes,
                                        {arm: naming.score_vbottom_sheet(boat, tables[arm], curves[arm], truth, cal)
                                         for arm in ARMS}, time.monotonic() - started))
        del ink
    return cases


def check_gates(cases: list[dict], baseline: list[dict]) -> dict:
    """Protocol gates: per-sheet correct cells not fewer, total wrong cells not more, round-bilge tables
    unchanged (equal to the baseline table and to the frozen table)."""
    before = {case['sheet']: case for case in baseline}
    per_sheet, wrong_before, wrong_after = {}, 0, 0
    for case in cases:
        old_case = before[case['sheet']]
        old, new = old_case['arms']['polyline']['total'], case['arms']['polyline']['total']
        wrong_before += old['wrong_cells']
        wrong_after += new['wrong_cells']
        entry = {'correct_before': old['correct_cells'], 'correct_after': new['correct_cells'],
                 'wrong_before': old['wrong_cells'], 'wrong_after': new['wrong_cells'],
                 'given_before': old['cells_given'], 'given_after': new['cells_given'],
                 'correct_not_fewer': new['correct_cells'] >= old['correct_cells']}
        if case['sheet'] in ROUND_BILGE:
            entry['table_unchanged'] = (case['table_sha256']['polyline'] == old_case['table_sha256']['polyline']
                                        and case['polyline_table_identical_to_frozen'])
        per_sheet[case['sheet']] = entry
    passed = (all(e['correct_not_fewer'] and e.get('table_unchanged', True) for e in per_sheet.values())
              and wrong_after <= wrong_before)
    return {'per_sheet': per_sheet, 'total_wrong_before': wrong_before, 'total_wrong_after': wrong_after,
            'all_gates_pass': passed}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sources', required=True, type=Path)
    parser.add_argument('--truth-root', required=True, type=Path)
    parser.add_argument('--legacy-truth-root', required=True, type=Path)
    parser.add_argument('--holdout-root', required=True, type=Path, help='the work/holdout folder')
    parser.add_argument('--out', required=True, type=Path)
    parser.add_argument('--baseline', type=Path, help='an earlier result of this script: check the gates')
    args = parser.parse_args()
    commit = subprocess.run(['git', 'rev-parse', 'HEAD'], capture_output=True, text=True).stdout.strip()
    baseline = json.loads(args.baseline.read_text())['cases'] if args.baseline else []
    cases = (run_development_sheets(args, {case['sheet']: case for case in baseline})
             + run_vbottom_sheets(args) + run_spent_published(args))
    report = {'engineering_approved': False, 'status': 'development cases only (Cama Beach and Davis Boat are spent)',
              'protocol': 'docs/plans/2026-11-12-polyline-engage.md', 'commit': commit,
              'polyline_sha256': naming.sha256_file(Path(polyline.__file__)), 'cases': cases}
    for case in cases:
        for arm in ARMS:
            t = case['arms'][arm]['total']
            print(f"{case['sheet']:30s} {arm:9s} given {t['cells_given']:4d} correct {t['correct_cells']:4d} "
                  f"wrong {t['wrong_cells']:3d} {json.dumps(case['arms'][arm]['kinds'])}", flush=True)
        print(f"{case['sheet']:30s} polyline halves {json.dumps({k: v for k, v in case['polyline_halves'].items() if isinstance(v, dict) and 'read' in v})}",
              flush=True)
    if args.baseline:
        report['gates'] = check_gates(cases, baseline)
        print('gates', json.dumps(report['gates'], indent=1), flush=True)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, default=float) + '\n')


if __name__ == '__main__':
    main()
