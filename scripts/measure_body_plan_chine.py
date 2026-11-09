"""Compare the frozen reader and chine post-processing without model calls.

Use existing harness calibrations and scorers. Truth stays outside the repository;
results contain scores, predicted cells, missing cell keys and input fingerprints.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict, replace
import hashlib
import json
from pathlib import Path
import time

from benchmarks.balclutha import crossing_value as cv
from benchmarks.balclutha import model_value as balclutha
from benchmarks.bue_girl import holdout_value as bue
from benchmarks.bumble_bee import holdout_value as bumble
from benchmarks.pardon_me import holdout_value as pardon
from benchmarks.thayer import holdout_value as thayer
from vessel_reconstruction import body_plan_chine as chine
from vessel_reconstruction import body_plan_crossings as crossings
from vessel_reconstruction import body_plan_reader as reader


def fingerprint(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as source:
        for block in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def corrected_bumble_layout():
    """docs/AUTO_CALIBRATION.md section 4: not merely a swap of the old halves."""
    layout = bumble.sheet_layout()
    sides = (reader.SideLayout('aft', -1, tuple(range(9, 15)), bumble.grid_columns(-1)),
             reader.SideLayout('fore', 1, tuple(range(8, 0, -1)), bumble.grid_columns(1)))
    return replace(layout, sides=sides)


def score_readings(readings, layout, truth, scorer):
    identities = {name: reader.identities_by_rank(r.chains, r.layout.stations_outer_first)
                  for name, r in readings.items()}
    table, flags = cv.table_and_flags(readings, identities, layout)
    result = scorer(table, truth)
    result.update(missing_cells=len(truth.keys() - table.keys()), fairness_flags=len(flags), calls=0,
                  missing_cell_keys=[[s, w] for s, w in truth if (s, w) not in table],
                  extra_cell_keys=[[s, w] for s, w in table if (s, w) not in truth],
                  predicted_cells=[{'station': s, 'waterline': w, 'half_breadth_m': value}
                                   for (s, w), value in table.items()],
                  identities=identities, measurement=cv.measurement_summary(readings))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sources', required=True, type=Path, help='Existing work/sources directory')
    parser.add_argument('--truth-root', required=True, type=Path, help='Parent of pardon-me, bue-girl, bumble-bee')
    parser.add_argument('--legacy-truth-root', required=True, type=Path, help='wv-agent parent of thayer, balclutha')
    parser.add_argument('--out', required=True, type=Path)
    args = parser.parse_args()
    cases = [
        ('PARDON ME', 'haer/master-pnp-habshaer-ny-ny2300-ny2390-sheet-00004a.tif',
         args.truth_root / 'pardon-me/truth_s4.json', pardon.sheet_layout(), pardon.load_truth, pardon.score),
        ('BUE GIRL', 'haer/master-pnp-habshaer-or-or0500-or0590-sheet-00002a.tif',
         args.truth_root / 'bue-girl/truth_s2.json', bue.sheet_layout(), bue.load_truth, bue.score),
        ('C.A. Thayer', 'haer/ca_thayer/loc_ca1506_sheet_04.tif',
         args.legacy_truth_root / 'thayer/truth_s4.json', thayer.sheet_layout(), thayer.load_truth, thayer.score),
        ('Balclutha', 'balclutha_ca54_s7.tif',
         args.legacy_truth_root / 'balclutha/truth_s7.json', cv.sheet_layout(), balclutha.load_truth, cv.score),
        ('BUMBLE BEE (corrected sides)', 'haer/master-pnp-habshaer-or-or0500-or0589-sheet-00002a.tif',
         args.truth_root / 'bumble-bee/truth_s2.json', corrected_bumble_layout(), bumble.load_truth, bumble.score),
    ]
    report = {'implementation_commit': '4232502', 'engineering_approved': False,
              'method': 'One frozen measurement per sheet; join_chine post-processes the same reading; unchanged rank identities and harness scorers.',
              'cases': []}
    for name, relative_sheet, truth_path, layout, load_truth, scorer in cases:
        sheet_path = args.sources / relative_sheet
        missing = [str(path) for path in (sheet_path, truth_path) if not path.is_file()]
        if missing:
            report['cases'].append({'sheet': name, 'unavailable_inputs': missing})
            print(f'{name}: unavailable {missing}', flush=True)
            continue
        started = time.monotonic()
        truth = load_truth(truth_path)
        ink = crossings.load_ink(sheet_path)
        frozen = cv.measure(ink, layout)
        before = score_readings(frozen, layout, truth, scorer)
        joined = {side: chine.join_chine(ink, layout, reading) for side, reading in frozen.items()}
        after = score_readings(joined, layout, truth, scorer)
        changed_sides = [side for side in frozen if joined[side] is not frozen[side]]
        case = {'sheet': name, 'sheet_path': str(sheet_path), 'sheet_sha256': fingerprint(sheet_path),
                'truth_path': str(truth_path), 'truth_sha256': fingerprint(truth_path),
                'calibration': asdict(layout), 'frozen': before, 'chine': after,
                'changed_sides': changed_sides,
                'rms_no_regression': after['rms_m'] <= before['rms_m'],
                'coverage_no_regression': after['cells_given'] >= before['cells_given'],
                'seconds': round(time.monotonic() - started, 3)}
        report['cases'].append(case)
        print(f"{name}: {before['cells_given']}/{len(truth)} -> {after['cells_given']}/{len(truth)}, "
              f"RMS {before['rms_m']:.10f} -> {after['rms_m']:.10f}, changed sides {changed_sides}", flush=True)
        del ink, frozen, joined
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2) + '\n')


if __name__ == '__main__':
    main()
