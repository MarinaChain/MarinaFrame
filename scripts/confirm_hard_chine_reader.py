"""Confirmatory run of the hard-chine reader selection on four V-bottom sheets (no model calls).

Protocol: docs/plans/2026-11-11-reader-selection.md section 12 (committed before this script ran).
The four sheets (E. C. COLLIER, WHITE GULL, COLLEEN, CALEB JONES) are development, formerly holdout.
Arms as in scripts/select_hard_chine_reader.py: frozen v1, chine joining, reader v2 and the polyline
reader with the product rule, all from one frozen reading. Truth is read after every arm has read
the sheet, for scoring only.
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

sys.path.insert(0, str(Path(__file__).resolve().parent))
from select_hard_chine_reader import ARMS, ink_summary, section_ink_distances  # noqa: E402
from benchmarks.balclutha import crossing_value as cv  # noqa: E402
from benchmarks.deadrise_holdout import score as sc  # noqa: E402
from benchmarks.ec_collier import point_score as collier_points  # noqa: E402
from benchmarks.frozen_readers.v1 import body_plan_crossings as crossings  # noqa: E402
from benchmarks.frozen_readers.v1 import body_plan_reader as reader  # noqa: E402
from vessel_reconstruction import body_plan_chine as chine  # noqa: E402
from vessel_reconstruction import body_plan_polyline as polyline  # noqa: E402
from vessel_reconstruction import body_plan_reader_v2 as v2  # noqa: E402

# boat folder under the holdout root -> (calibration module, sheet file name)
SHEETS = {
    'ec-collier': ('benchmarks.ec_collier.holdout_value', 'md1203-sheet-00002a-lines.tif'),
    'white-gull': ('benchmarks.white_gull.holdout_value', 'md1939-sheet-00001a-lines.tif'),
    'colleen': ('benchmarks.colleen.holdout_value', 'md1887-sheet-00001a-lines.tif'),
    'caleb-jones': ('benchmarks.caleb_jones.holdout_value', 'md1860-sheet-00001a-lines.tif'),
}
KINDS = ('waterline', 'point')


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as source:
        for block in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def load_truth(boat: str, path: Path, cal) -> dict:
    """{'waterlines': {...}, 'points': {...}} in the deadrise scorer's shape; each loader checks the sha256."""
    if boat == 'ec-collier':
        return {'waterlines': {}, 'points': collier_points.load_truth(path)}
    return sc.load_truth(path, cal)


def read_all_arms(ink, layout, cal) -> tuple[dict, dict]:
    """(waterline table, station curves) of each arm, from one frozen reading."""
    frozen = cv.measure(ink, layout)
    identities = {name: reader.identities_by_rank(r.chains, r.layout.stations_outer_first)
                  for name, r in frozen.items()}
    joined = {name: chine.join_chine(ink, layout, r) for name, r in frozen.items()}
    joined_identities = {name: reader.identities_by_rank(r.chains, r.layout.stations_outer_first)
                         for name, r in joined.items()}
    sides = v2.read_sheet(ink, layout, frozen)
    halves = polyline.read_sheet(ink, layout)
    sc.engage(halves, frozen, identities, layout, ink)
    tables = {'frozen': cv.table_and_flags(frozen, identities, layout)[0],
              'joining': cv.table_and_flags(joined, joined_identities, layout)[0],
              'reader_v2': v2.sheet_table(sides, layout)[0],
              'polyline': sc.polyline_table(halves, frozen, identities, layout)}
    curves = {'frozen': sc.frozen_curves(frozen, identities, layout, cal),
              'joining': sc.frozen_curves(joined, joined_identities, layout, cal),
              'reader_v2': sc.v2_curves(sides, layout, cal),
              'polyline': sc.polyline_curves(halves, frozen, identities, layout, cal)}
    return tables, curves


def score_arm(table: dict, curves: dict, truth: dict, cal) -> dict:
    scores = {'point': sc.score_points(curves, truth, cal)}
    if truth['waterlines']:
        scores['waterline'] = sc.score_waterlines(table, truth, cal)
    for result in scores.values():
        result['correct_cells'] = result.get('cells_given', 0) - result.get('wrong_cells', 0)
    return scores


def totals(cases: list[dict]) -> dict:
    """Protocol section 12: correct and wrong cells summed over sheets and both kinds of cell."""
    summed = {}
    for arm in ARMS:
        results = [case['arms'][arm]['score'][kind] for case in cases for kind in KINDS
                   if kind in case['arms'][arm]['score']]
        summed[arm] = {key: sum(r.get(key, 0) for r in results)
                       for key in ('truth_cells', 'cells_given', 'wrong_cells', 'correct_cells')}
    others = [arm for arm in ARMS if arm != 'reader_v2']  # ARMS order is frozen, joining, ..., polyline
    next_best = min(others, key=lambda arm: (-summed[arm]['correct_cells'], summed[arm]['wrong_cells'],
                                             others.index(arm)))
    integrate = (summed['reader_v2']['correct_cells'] >= summed[next_best]['correct_cells']
                 and summed['reader_v2']['wrong_cells'] <= summed[next_best]['wrong_cells'])
    return {'by_arm': summed, 'next_best_arm': next_best, 'integrate_reader_v2': integrate}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--holdout-root', required=True, type=Path, help='the work/holdout folder')
    parser.add_argument('--out', required=True, type=Path)
    args = parser.parse_args()
    commit = subprocess.run(['git', 'rev-parse', 'HEAD'], capture_output=True, text=True).stdout.strip()
    report = {'engineering_approved': False, 'status': 'development, formerly holdout',
              'protocol': 'docs/plans/2026-11-11-reader-selection.md section 12', 'commit': commit, 'cases': []}
    for boat, (module, sheet_name) in SHEETS.items():
        cal = importlib.import_module(module)
        sheet_path, truth_path = args.holdout_root / boat / sheet_name, args.holdout_root / boat / 'truth.json'
        sheet_sha = sha256(sheet_path)
        if sheet_sha != cal.SHEET_SHA256:
            raise SystemExit(f'{boat}: sheet sha256 {sheet_sha} is not the calibrated sheet; stop')
        started = time.monotonic()
        layout = cal.sheet_layout()
        ink = crossings.load_ink(sheet_path)
        tables, curves = read_all_arms(ink, layout, cal)
        truth = load_truth(boat, truth_path, cal)  # read only now, after every arm has read the sheet
        case = {'sheet': boat, 'sheet_sha256': sheet_sha, 'arms': {}}
        for arm in ARMS:
            case['arms'][arm] = {'score': score_arm(tables[arm], curves[arm], truth, cal),
                                 'ink': ink_summary(section_ink_distances(tables[arm], ink, layout)),
                                 'table_identical_to_frozen': tables[arm] == tables['frozen'],
                                 'curves_identical_to_frozen': curves[arm] == curves['frozen']}
        case['seconds'] = round(time.monotonic() - started, 1)
        report['cases'].append(case)
        for arm in ARMS:
            for kind, s in case['arms'][arm]['score'].items():
                print(f"{boat:12s} {arm:10s} {kind:9s} cells {s.get('cells_given', 0)}/{s.get('truth_cells', 0)} "
                      f"correct {s['correct_cells']} wrong {s.get('wrong_cells', 0)} RMS {s.get('rms_m')} "
                      f"identity {s.get('identity_errors')} extra {len(s.get('extra_cell_keys', []))}", flush=True)
            print(f"{boat:12s} {arm:10s} ink {case['arms'][arm]['ink']['median_rms_mm']} mm, off-ink "
                  f"{case['arms'][arm]['ink']['off_ink_sections']}, same as frozen "
                  f"{case['arms'][arm]['curves_identical_to_frozen']}", flush=True)
        del ink
    report['totals'] = totals(report['cases'])
    print('totals', json.dumps(report['totals']), flush=True)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, default=float) + '\n')


if __name__ == '__main__':
    main()
