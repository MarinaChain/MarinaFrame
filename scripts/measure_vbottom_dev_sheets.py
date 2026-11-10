"""The V-bottom polyline reader on the five waterline dev sheets (no model calls).

Product rule measured here (`benchmarks.deadrise_holdout.score.polyline_table`): a half that the
polyline reader reads takes its waterline table (the traced polylines at the drawn waterline rows);
a declined half keeps the frozen reader's rank-identity table, with stations engaged one by one
(clear knuckle, named by the frozen reader) replaced by their polylines. On a round-bilge sheet
no station is engaged, so the table is the frozen table unchanged. PARDON ME (steep-sided hard chine) is a development case.

Same harness calibrations, truth files and scorers as scripts/measure_chine_reader_v2.py. Truth is
read after reading, for scoring only. Wrong cells = cells given with error above 0.15 m.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import measure_body_plan_chine as base  # noqa: E402
from measure_chine_reader_v2 import summarise  # noqa: E402
from benchmarks.balclutha import crossing_value as cv  # noqa: E402
from benchmarks.balclutha import model_value as balclutha  # noqa: E402
from benchmarks.bue_girl import holdout_value as bue  # noqa: E402
from benchmarks.bumble_bee import holdout_value as bumble  # noqa: E402
from benchmarks.deadrise_holdout import score as product  # noqa: E402
from benchmarks.pardon_me import holdout_value as pardon  # noqa: E402
from benchmarks.thayer import holdout_value as thayer  # noqa: E402
from vessel_reconstruction import body_plan_crossings as crossings  # noqa: E402
from vessel_reconstruction import body_plan_polyline as polyline  # noqa: E402
from vessel_reconstruction import body_plan_reader as reader  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sources', required=True, type=Path)
    parser.add_argument('--truth-root', required=True, type=Path)
    parser.add_argument('--legacy-truth-root', required=True, type=Path)
    parser.add_argument('--out', required=True, type=Path)
    parser.add_argument('--only', default='', help='run only sheets whose name contains this text')
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
        if args.only and args.only not in name:
            continue
        sheet_path = args.sources / relative
        missing = [str(p) for p in (sheet_path, truth_path) if not p.is_file()]
        if missing:
            report['cases'].append({'sheet': name, 'unavailable_inputs': missing})
            print(f'{name}: missing inputs {missing}', flush=True)
            continue
        started = time.monotonic()
        ink = crossings.load_ink(sheet_path)
        frozen = cv.measure(ink, layout)
        identities = {n: reader.identities_by_rank(r.chains, r.layout.stations_outer_first)
                      for n, r in frozen.items()}
        before_table, _ = cv.table_and_flags(frozen, identities, layout)
        halves = polyline.read_sheet(ink, layout)
        product.engage(halves, frozen, identities, layout, ink)
        after_table = product.polyline_table(halves, frozen, identities, layout)
        truth = load_truth(truth_path)  # read only now, after both readers have run
        before, after = summarise(before_table, truth, scorer), summarise(after_table, truth, scorer)
        case = {'sheet': name, 'frozen': before, 'polyline_or_frozen': after,
                'halves': {n: {'read': h.read, 'notes': h.notes, 'line_width_px': h.line_width_px,
                               'stations': [[s.station, s.chine[0], s.chine[1], s.turn_deg] for s in h.stations],
                               'engaged': [[s.station, s.chine[0], s.chine[1], s.turn_deg] for s in h.engaged],
                               'unnamed': [[s.chine[0], s.chine[1], s.turn_deg] for s in h.unnamed]}
                           for n, h in halves.items()},
                'table_unchanged': before_table == after_table,
                'seconds': round(time.monotonic() - started, 1)}
        report['cases'].append(case)
        print(f"{name}: halves read {[n for n, h in halves.items() if h.read]}; "
              f"{before['cells_given']}/{len(truth)} -> {after['cells_given']}/{len(truth)}, "
              f"RMS {before.get('rms_m', float('nan')):.6f} -> {after.get('rms_m', float('nan')):.6f}, "
              f"max {before.get('max_abs_m', float('nan')):.4f} -> {after.get('max_abs_m', float('nan')):.4f}, "
              f"wrong {before['wrong_cells']} -> {after['wrong_cells']}, identity {before['identity_errors']} -> "
              f"{after['identity_errors']}, unchanged {case['table_unchanged']}", flush=True)
        for n, h in halves.items():
            print('   ', n, 'read' if h.read else 'declined', 'engaged', [s.station for s in h.engaged], h.notes,
                  flush=True)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, default=float) + '\n')


if __name__ == '__main__':
    main()
