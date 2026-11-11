"""Round-bilge holdout (14'-3" Double Ended Davis Boat): one run of the code readers with the committed
calibration, scored by the waterline harness scorer and decided by rule 3.5.9 (docs/holdouts/davis-boat.md,
section 4). No model calls.

Arms (code only, deterministic, so one run each):
- `product`: `body_plan_sides.read_side` on the crossing reader's reading of each half, as
  `body_plan_intake` calls it. This arm decides PASS / FAIL.
- `frozen`: frozen reader v1, rank identities (comparison, reported).
- `polyline_rule`: the benchmark product rule (`deadrise_holdout.score.polyline_table`), shown equal to
  `product` on nine development sheets (comparison, reported).

Scored cells: the nonblank printed waterline half-breadths at stations 1 to 7, through
`deadrise_holdout.score.score_waterlines`, which calls `balclutha.model_value.score`. Rule 3.5.9: an arm
passes if it gives at least 60 % of the scored cells and its (median) RMS is at most 0.15 m
(`balclutha.router_value.decide` with one repeat). Point cells (sheer, rabbet) are reported for the
`frozen` and `polyline_rule` arms only, not gated. Every reader runs before the truth file is read.

The calibration module is the only per-boat input; it is used unchanged.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import time
from pathlib import Path

from benchmarks.balclutha import crossing_value as cv
from benchmarks.balclutha import router_value as rule
from benchmarks.deadrise_holdout import score as sc
from benchmarks.frozen_readers.v1 import body_plan_crossings as frozen_crossings
from benchmarks.frozen_readers.v1 import body_plan_reader as frozen_reader
from vessel_reconstruction import body_plan_crossings as product_crossings
from vessel_reconstruction import body_plan_polyline as polyline
from vessel_reconstruction import body_plan_reader as product_reader
from vessel_reconstruction import body_plan_sides

# 'davis-boat' is the holdout. 'colleen' is a spent holdout (now a development case), listed only so that this
# script can be checked end to end before the one Davis run.
BOATS = {'davis-boat': 'benchmarks.davis_boat.holdout_value',
         'colleen': 'benchmarks.colleen.holdout_value'}
ARMS = ('product', 'frozen', 'polyline_rule')
DECIDING_ARM = 'product'
ONE_RUN = 1  # code arms are deterministic: rule 3.5.9 is applied to their one run


def read_product(ink, layout) -> dict:
    """{half: body_plan_sides.SideResult}, the product reading of each half."""
    return {side.name: body_plan_sides.read_side(ink, layout, product_reader.measure_side(ink, layout, side))
            for side in layout.sides}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--boat', choices=sorted(BOATS), required=True)
    parser.add_argument('--sheet', type=Path, required=True)
    parser.add_argument('--truth', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    cal = importlib.import_module(BOATS[args.boat])
    sheet_sha = hashlib.sha256(args.sheet.read_bytes()).hexdigest()
    if sheet_sha != cal.SHEET_SHA256:
        raise SystemExit(f'sheet sha256 {sheet_sha} is not the protocol sheet; stop')
    layout = cal.sheet_layout()

    seconds = {}
    started = time.monotonic()
    product_ink = product_crossings.load_ink(args.sheet)
    product = read_product(product_ink, layout)
    seconds['product'] = round(time.monotonic() - started, 1)

    started = time.monotonic()
    frozen_ink = frozen_crossings.load_ink(args.sheet)
    frozen = cv.measure(frozen_ink, layout)
    identities = {name: frozen_reader.identities_by_rank(r.chains, r.layout.stations_outer_first)
                  for name, r in frozen.items()}
    halves = polyline.read_sheet(frozen_ink, layout)
    sc.engage(halves, frozen, identities, layout, frozen_ink)
    seconds['frozen_and_polyline_rule'] = round(time.monotonic() - started, 1)

    tables = {'product': {key: value for result in product.values() for key, value in result.table.items()},
              'frozen': cv.table_and_flags(frozen, identities, layout)[0],
              'polyline_rule': sc.polyline_table(halves, frozen, identities, layout)}
    curves = {'frozen': sc.frozen_curves(frozen, identities, layout, cal),
              'polyline_rule': sc.polyline_curves(halves, frozen, identities, layout, cal)}

    truth = sc.load_truth(args.truth, cal)  # read only now, after every reader has run
    waterline = {arm: sc.score_waterlines(tables[arm], truth, cal) for arm in ARMS}
    points = {arm: sc.score_points(curves[arm], truth, cal) for arm in curves}
    decisions = {}
    for arm in ARMS:
        median_rms, passes = rule.decide([waterline[arm]], repeats=ONE_RUN)
        decisions[arm] = {'coverage': waterline[arm].get('coverage'), 'median_rms_m': median_rms,
                          'passes_rule_3_5_9': passes}

    report = {
        'holdout': f'{args.boat}; one run, no tuning', 'protocol': cal.PROTOCOL, 'engineering_approved': False,
        'sheet_sha256': sheet_sha, 'truth_sha256': cal.TRUTH_SHA256, 'deciding_arm': DECIDING_ARM,
        'truth_cells': {'waterline': sum(v is not None for v in truth['waterlines'].values()),
                        'point': sum(v['height'] is not None and v['half_breadth'] is not None
                                     for v in truth['points'].values())},
        'truth_unmatched_waterlines': truth['unmatched_waterlines'],
        'seconds': seconds, 'measurement': cv.measurement_summary(frozen),
        'decisions': decisions, 'waterline': waterline, 'point': points,
        'product_identity_source': {name: {str(s): src for s, src in r.identity_source.items()}
                                    for name, r in product.items()},
        'product_polyline_used': {name: r.polyline_used for name, r in product.items()},
        'frozen_identities': {n: {str(k): v for k, v in i.items()} for n, i in identities.items()},
        'tables': {arm: {f'{s}/{w}': v for (s, w), v in sorted(table.items())} for arm, table in tables.items()},
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, default=float) + '\n')

    keys = ('truth_cells', 'cells_given', 'coverage', 'rms_m', 'max_abs_m', 'within_0_05', 'within_0_15',
            'wrong_cells', 'identity_errors', 'extra_cells', 'missing_cell_keys', 'extra_cell_keys')
    for arm in ARMS:
        print(arm, 'waterline', json.dumps({k: waterline[arm].get(k) for k in keys}, default=float))
        print(arm, 'decision', json.dumps(decisions[arm], default=float))
    for arm, result in points.items():
        print(arm, 'point (reported, not gated)', json.dumps({k: result.get(k) for k in keys}, default=float))
    print('product polyline used', report['product_polyline_used'])
    print('unmatched waterlines', truth['unmatched_waterlines'])


if __name__ == '__main__':
    main()
