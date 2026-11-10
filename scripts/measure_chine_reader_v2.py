"""Compare the frozen reader and reader v2 on the five dev sheets (no model calls).

Same harness calibration, truth and scorers as scripts/measure_body_plan_chine.py. Truth is read
after reading, for scoring only. PARDON ME is a development case. Wrong cells = cells given
whose error exceeds 0.15 m (the harness's own within_0_15 band).
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import measure_body_plan_chine as base  # noqa: E402
from benchmarks.balclutha import crossing_value as cv  # noqa: E402
from benchmarks.balclutha import model_value as balclutha  # noqa: E402
from benchmarks.bue_girl import holdout_value as bue  # noqa: E402
from benchmarks.bumble_bee import holdout_value as bumble  # noqa: E402
from benchmarks.pardon_me import holdout_value as pardon  # noqa: E402
from benchmarks.thayer import holdout_value as thayer  # noqa: E402
from benchmarks.frozen_readers.v1 import body_plan_crossings as crossings  # noqa: E402
from benchmarks.frozen_readers.v1 import body_plan_reader as reader  # noqa: E402
from vessel_reconstruction import body_plan_reader_v2 as v2  # noqa: E402

WRONG_BAND_M = 0.15


def summarise(table, truth, scorer):
    result = scorer(table, truth)
    common = [k for k in truth if k in table]
    result['wrong_cells'] = sum(abs(table[k] - truth[k]) > WRONG_BAND_M for k in common)
    result['missing_cells'] = len(truth.keys() - table.keys())
    result['missing_cell_keys'] = [[s, w] for s, w in truth if (s, w) not in table]
    result['extra_cell_keys'] = [[s, w] for s, w in table if (s, w) not in truth]
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sources', required=True, type=Path)
    parser.add_argument('--truth-root', required=True, type=Path)
    parser.add_argument('--legacy-truth-root', required=True, type=Path)
    parser.add_argument('--out', required=True, type=Path)
    args = parser.parse_args()
    cases = [
        ('PARDON ME (development)', 'haer/master-pnp-habshaer-ny-ny2300-ny2390-sheet-00004a.tif',
         args.truth_root / 'pardon-me/truth_s4.json', pardon.sheet_layout(), pardon.load_truth, pardon.score),
        ('BUE GIRL', 'haer/master-pnp-habshaer-or-or0500-or0590-sheet-00002a.tif',
         args.truth_root / 'bue-girl/truth_s2.json', bue.sheet_layout(), bue.load_truth, bue.score),
        ('C.A. Thayer', 'haer/ca_thayer/loc_ca1506_sheet_04.tif',
         args.legacy_truth_root / 'thayer/truth_s4.json', thayer.sheet_layout(), thayer.load_truth, thayer.score),
        ('Balclutha', 'balclutha_ca54_s7.tif',
         args.legacy_truth_root / 'balclutha/truth_s7.json', cv.sheet_layout(), balclutha.load_truth, cv.score),
        ('BUMBLE BEE (corrected sides)', 'haer/master-pnp-habshaer-or-or0500-or0589-sheet-00002a.tif',
         args.truth_root / 'bumble-bee/truth_s2.json', base.corrected_bumble_layout(), bumble.load_truth,
         bumble.score),
    ]
    report = {'engineering_approved': False, 'pardon_me_is_development_case': True, 'cases': []}
    for name, relative, truth_path, layout, load_truth, scorer in cases:
        sheet_path = args.sources / relative
        missing = [str(p) for p in (sheet_path, truth_path) if not p.is_file()]
        if missing:
            report['cases'].append({'sheet': name, 'unavailable_inputs': missing})
            continue
        started = time.monotonic()
        truth = load_truth(truth_path)
        ink = crossings.load_ink(sheet_path)
        frozen = cv.measure(ink, layout)
        identities = {n: reader.identities_by_rank(r.chains, r.layout.stations_outer_first)
                      for n, r in frozen.items()}
        before_table, _ = cv.table_and_flags(frozen, identities, layout)
        sides = v2.read_sheet(ink, layout, frozen)
        after_table, flags = v2.sheet_table(sides, layout)
        before, after = summarise(before_table, truth, scorer), summarise(after_table, truth, scorer)
        case = {'sheet': name, 'frozen': before, 'v2': after,
                'sides_using_chine': [n for n, s in sides.items() if s.uses_chine],
                'abstained': {n: s.abstained for n, s in sides.items()},
                'chine_points': {n: [[p.station, p.row, p.column] for p in s.chine_points] for n, s in sides.items()},
                'rms_no_regression': after.get('rms_m', 0) <= before.get('rms_m', 0) + 1e-12,
                'coverage_no_regression': after['cells_given'] >= before['cells_given'],
                'seconds': round(time.monotonic() - started, 1)}
        report['cases'].append(case)
        print(f"{name}: {before['cells_given']}/{len(truth)} -> {after['cells_given']}/{len(truth)}, "
              f"RMS {before['rms_m']:.6f} -> {after['rms_m']:.6f}, max {before['max_abs_m']:.4f} -> "
              f"{after['max_abs_m']:.4f}, wrong {before['wrong_cells']} -> {after['wrong_cells']}, "
              f"identity {before['identity_errors']} -> {after['identity_errors']}, chine sides "
              f"{case['sides_using_chine']}", flush=True)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2) + '\n')


if __name__ == '__main__':
    main()
