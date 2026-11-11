"""Explain round 13 with frozen measurements and saved labels; never call an arm or model.

Usage::

    PYTHONPATH=src:. .venv/bin/python -m benchmarks.bumble_bee.diagnose \
        --sheet <sheet.tif> --truth <truth_s2.json> --runs <runs folder>

Only stdout is written. Truth fits and nearby ink are diagnostic evidence, not new identities
or corrected scores. All tables retain the original calibration and assignment functions.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from benchmarks.balclutha import crossing_value as round8
from benchmarks.bumble_bee import holdout_value as hv
from vessel_reconstruction import body_plan_crossings as bpc
from vessel_reconstruction import body_plan_identity as bpi
from vessel_reconstruction import body_plan_reader as bpr

# Diagnostic windows only, not reader thresholds or proof that two strokes are one station.
NEAR_PX = 60
CLOSE_PX = 35


def chain_metres(reading, chain, layout):
    return {waterline: reading.stations[waterline][index].offset_px(
        layout.centre_column, reading.layout.sign) / layout.pixels_per_metre
        for waterline, index in chain.nodes.items()}


def best_fits(values, truth):
    """Independent fits across ALL stations, with at least two shared nonblank rows.

    Fits need not be unique or order-preserving and can use different row counts. They are
    not a reassignment, a visual identification, or an alternative benchmark result.
    """
    fits = []
    for station in hv.STATIONS:
        errors = [value - truth[(station, waterline)] for waterline, value in values.items()
                  if (station, waterline) in truth]
        if len(errors) >= 2:
            fits.append((float(np.sqrt(np.mean(np.square(errors)))), station, len(errors)))
    return sorted(fits)


def saved_assignments(runs, readings, code_ids):
    """Reconstruct final assignments from saved labels, without question generation or calls."""
    assignments = {'code': code_ids}
    labels_by_repeat = {}
    for arm in hv.ARMS:
        if arm == 'code':
            continue
        summary = json.loads((runs / arm / 'summary.json').read_text())
        for repeat in range(1, len(summary['repeats']) + 1):
            folder = runs / arm / f'R1-{repeat}'
            raw = json.loads((folder / 'labels.json').read_text())
            labels = {side: {int(index): label for index, label in found.items()}
                      for side, found in raw.items()}
            name = f'{arm}/{folder.name}'
            labels_by_repeat[name] = labels
            assignments[name] = {side: bpi.identities_from_labels(reading, labels[side])[0]
                                 for side, reading in readings.items()}
    return assignments, labels_by_repeat


def waterline_report(ink, layout):
    print('\n== Waterline traces ==')
    for side in layout.sides:
        span = sorted((int(layout.centre_column + side.sign * 10),
                       int(layout.centre_column + side.sign * layout.max_offset_px)))
        for waterline in layout.waterlines_low_to_high():
            nominal = layout.waterline_rows[waterline]
            trace = bpc.locate_waterline(ink, nominal, tuple(span))
            traced = trace.row_at(sum(span) / 2)
            fallback = trace.gradient == 0 and trace.intercept == nominal
            print(f'{side.name} {waterline}: nominal={nominal}, traced={traced:.2f}, '
                  f'half_thickness={trace.half_thickness:.2f}, '
                  f'{"nominal fallback" if fallback else "drawn line located"}')


def chain_report(readings, layout, truth, assignments, labels):
    print('\n== Chains: frozen code identity, raw labels, final assignments, truth fits ==')
    print('Fits use all stations; top three shown as station:RMS_mm:shared_rows. '
          'Close fits are ambiguous, not confirmed identities.')
    for side, reading in readings.items():
        for index, chain in enumerate(reading.chains):
            values = chain_metres(reading, chain, layout)
            fits = best_fits(values, truth)
            print(f'{side} chain {index}: code={assignments["code"][side].get(index)}, '
                  f'span={bpr.rows_spanned(chain):.0f}px, inferred_links={chain.inferred_links}')
            print('  values_m: ' + ', '.join(f'{w}={v:.6f}' for w, v in values.items()))
            print('  fits: ' + ', '.join(f'{s}:{rms * 1000:.1f}:{n}' for rms, s, n in fits[:3]))
            for name, raw in labels.items():
                print(f'  {name}: label={raw[side].get(index)}, '
                      f'assigned={assignments[name][side].get(index)}')


def crossing_report(readings, layout):
    print('\n== Crossings and chain sharing ==')
    print(f'close means a distinct station crossing within {CLOSE_PX}px, not proof of a merge.')
    for side, reading in readings.items():
        for waterline in layout.waterlines_low_to_high():
            for crossing in reading.crossings[waterline]:
                offset = crossing.offset_px(layout.centre_column, reading.layout.sign)
                close = [other for other in reading.stations[waterline]
                         if other is not crossing and abs(other.x_px - crossing.x_px) < CLOSE_PX]
                owners = [index for index, chain in enumerate(reading.chains)
                          if waterline in chain.nodes and
                          reading.stations[waterline][chain.nodes[waterline]] is crossing]
                print(f'{side} {waterline}: offset={offset:.1f}px '
                      f'({offset / layout.pixels_per_metre:.6f}m), kind={crossing.kind}, '
                      f'slope={crossing.slope:+.2f}, width={crossing.width_px:.1f}, '
                      f'close={len(close)}, chains={owners}, notes={crossing.notes}')


def missing_evidence(reading, layout, identities, station, waterline, truth_m):
    """Separate the exact assignment gap from ink near a truth-derived offset.

    The assigned half can itself be wrong. A nearby crossing does not establish which physical
    station produced it; proximity therefore stays evidence, never an asserted missing cause.
    """
    owners = [index for index, label in identities.items() if label == station]
    if not owners:
        gap = 'identity: no chain assigned'
    else:
        gap = f'assigned chain {owners[0]} has no node on this waterline'
    expected = truth_m * layout.pixels_per_metre
    if expected > layout.max_offset_px:
        return f'{gap}; truth offset {expected:.1f}px beyond max offset {layout.max_offset_px}px'
    nearby = sorted((crossing for crossing in reading.crossings[waterline]
                     if abs(crossing.offset_px(layout.centre_column, reading.layout.sign)
                            - expected) <= NEAR_PX), key=lambda crossing: abs(
                                crossing.offset_px(layout.centre_column, reading.layout.sign) - expected))
    evidence = []
    for crossing in nearby:
        offset = crossing.offset_px(layout.centre_column, reading.layout.sign)
        status = ('rejected shallow' if crossing.kind == bpc.KIND_SHALLOW else
                  'double candidate (not rejected)' if crossing.kind == bpc.KIND_DOUBLE else
                  crossing.kind)
        evidence.append(f'{offset:.1f}px {status} slope={crossing.slope:+.2f} '
                        f'notes={crossing.notes}')
    ink = ' | '.join(evidence) or f'no crossing within {NEAR_PX}px'
    return f'{gap}; on calibrated {reading.layout.name} half near truth {expected:.1f}px: {ink}'


def cell_report(readings, layout, truth, assignments, tables):
    side_of = {station: side.name for side in layout.sides for station in side.stations_outer_first}
    print('\n== Per-cell record (all arms; error = given minus truth) ==')
    print('arm\twaterline\tstation\ttruth_present\tcell_given\terror_mm\tevidence')
    for name, table in tables.items():
        for waterline in layout.waterlines_low_to_high():
            for station in hv.STATIONS:
                cell = (station, waterline)
                present, given = cell in truth, cell in table
                error, evidence = '-', '-'
                if present and given:
                    error = f'{(table[cell] - truth[cell]) * 1000:+.2f}'
                elif present:
                    side = side_of[station]
                    evidence = missing_evidence(readings[side], layout, assignments[name][side],
                                                station, waterline, truth[cell])
                elif given:
                    evidence = f'extra cell: {table[cell]:.6f}m; truth blank'
                print(f'{name}\t{waterline}\t{station}\t{present}\t{given}\t{error}\t{evidence}')
        print(f'{name} missing: ' + ', '.join(f'{s}/{w}' for s, w in truth if (s, w) not in table))
        print(f'{name} extra: ' + ', '.join(f'{s}/{w}={v:.6f}m' for (s, w), v in table.items()
                                         if (s, w) not in truth))
        largest = sorted(((abs(table[cell] - value), cell, table[cell] - value)
                          for cell, value in truth.items() if cell in table), reverse=True)[:5]
        print(f'{name} largest errors: ' + ', '.join(f'{s}/{w}={error * 1000:+.2f}mm'
              for _, (s, w), error in largest))


def check_saved_metrics(runs, tables, truth):
    """Check deterministic reconstruction against saved scores; do not write scores or decide."""
    for name, table in tables.items():
        arm, _, repeat = name.partition('/')
        summary = json.loads((runs / arm / 'summary.json').read_text())
        index = int(repeat.split('-')[-1]) - 1 if repeat else 0
        saved = summary['repeats'][index]
        for metric, value in hv.score(table, truth).items():
            if saved[metric] != value:
                raise ValueError(f'{name}: deterministic metric mismatch: {metric}')
    print('Reconstructed metrics match every saved repeat; no arm or model was called.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sheet', type=Path, required=True)
    parser.add_argument('--truth', type=Path, required=True)
    parser.add_argument('--runs', type=Path, required=True)
    args = parser.parse_args()
    hv.check_sheet(args.sheet)
    truth = hv.load_truth(args.truth)
    ink, layout = bpc.load_ink(args.sheet), hv.sheet_layout()
    readings = round8.measure(ink, layout)
    code_ids = {side: bpr.identities_by_rank(reading.chains, reading.layout.stations_outer_first)
                for side, reading in readings.items()}
    assignments, labels = saved_assignments(args.runs, readings, code_ids)
    tables = {name: round8.table_and_flags(readings, ids, layout)[0]
              for name, ids in assignments.items()}
    print(f'Diagnosis only: truth_cells={len(truth)}; engineering_approved=false')
    check_saved_metrics(args.runs, tables, truth)
    waterline_report(ink, layout)
    chain_report(readings, layout, truth, assignments, labels)
    crossing_report(readings, layout)
    cell_report(readings, layout, truth, assignments, tables)


if __name__ == '__main__':
    main()
