"""Read-only round-14 diagnosis; no arm runs, model calls, or saved-run writes.

Reconstruct deterministic measurements and apply the saved labels, then require the
scored fields to match every original summary. Print all 66 cells per distinct table
and the crossing/chain evidence. This is not a new scored holdout run.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

from benchmarks.pardon_me import holdout_value as hv
from vessel_reconstruction import body_plan_identity as bpi


def crossing_record(crossing, side, layout) -> dict:
    return {'offset_px': crossing.offset_px(layout.centre_column, side.sign),
            'kind': crossing.kind, 'slope': crossing.slope, 'notes': crossing.notes}


def cell_evidence(station, waterline, truth, table, readings, identities, layout) -> dict:
    key = station, waterline
    expected, measured = truth.get(key), table.get(key)
    reading = next(r for r in readings.values() if station in r.layout.stations_outer_first)
    side = reading.layout
    sources = []
    for index, assigned in identities[side.name].items():
        chain = reading.chains[index]
        if assigned == station and waterline in chain.nodes:
            sources.append(index)
    result = {'station': station, 'waterline': waterline, 'truth_present': key in truth,
              'cell_given': key in table, 'truth_m': expected, 'given_m': measured,
              'error_m': measured - expected if expected is not None and measured is not None else None,
              'source_chains': sources}
    if expected is None:
        result['diagnosis'] = 'extra cell' if measured is not None else 'blank truth; no cell'
        return result
    if measured is not None:
        result['diagnosis'] = 'given; inspect error and source chain'
        return result
    offset = expected * layout.pixels_per_metre
    result['truth_offset_px'] = offset
    if offset > layout.max_offset_px:
        result['diagnosis'] = 'beyond max offset'
        return result
    found = reading.crossings[waterline]
    if not found:
        result['diagnosis'] = 'no crossing recorded on this half/waterline'
        return result
    nearest = min(found, key=lambda c: abs(c.offset_px(layout.centre_column, side.sign) - offset))
    evidence = crossing_record(nearest, side, layout)
    evidence['gap_to_truth_px'] = evidence['offset_px'] - offset
    evidence['chains'] = [
        {'chain': i, 'assigned_station': identities[side.name].get(i),
         'nodes': chain.nodes}
        for i, chain in enumerate(reading.chains)
        if waterline in chain.nodes and reading.stations[waterline][chain.nodes[waterline]] is nearest]
    result['nearest_crossing'] = evidence
    # Proximity is diagnosis only, not an identity assignment or a scoring tolerance.
    near = abs(evidence['gap_to_truth_px']) <= hv.bpc.LINK_TOLERANCE_PX
    if near and nearest.kind == hv.bpc.KIND_SHALLOW:
        result['diagnosis'] = 'rejected shallow'
    elif near and nearest.kind not in hv.bpc.STATION_KINDS:
        result['diagnosis'] = 'rejected ' + nearest.kind
    elif near:
        result['diagnosis'] = 'crossing exists; identity/chain selection omitted this cell'
    else:
        result['diagnosis'] = 'no crossing within link tolerance of truth offset'
    if nearest.kind == hv.bpc.KIND_DOUBLE:
        result['diagnosis'] += '; nearest is double (possible merge, not proved station identity)'
    return result


def diagnose(sheet: Path, truth_path: Path, runs: Path) -> dict:
    layout = hv.sheet_layout()
    truth = hv.load_truth(truth_path)
    readings = hv.round8.measure(hv.bpc.load_ink(sheet), layout)
    measurement = hv.round8.measurement_summary(readings)
    groups = []
    for arm in hv.ARMS:
        summary = json.loads((runs / arm / 'summary.json').read_text())
        if measurement != summary['measurement']['sides']:
            raise ValueError(f'{arm}: reconstructed measurement differs from saved summary')
        for repeat, saved in enumerate(summary['repeats'], 1):
            if arm == 'code':
                identities = {name: hv.bpr.identities_by_rank(r.chains, r.layout.stations_outer_first)
                              for name, r in readings.items()}
            else:
                labels = json.loads((runs / arm / f'R1-{repeat}' / 'labels.json').read_text())
                identities = {name: bpi.identities_from_labels(
                    r, {int(k): v for k, v in labels[name].items()})[0] for name, r in readings.items()}
            table, flags = hv.round8.table_and_flags(readings, identities, layout)
            score = hv.score(table, truth)
            score['fairness_flags'] = len(flags)
            for field, value in score.items():
                original = saved[field]
                matches = math.isclose(value, original, rel_tol=1e-12, abs_tol=1e-12) if isinstance(
                    value, float) else value == original
                if not matches:
                    raise ValueError(f'{arm}/{repeat}: reconstructed {field} differs from saved score')
            case = f'{arm}/{repeat}'
            group = next((g for g in groups if g['identities'] == identities), None)
            if group is not None:
                group['saved_cases'].append(case)
                continue
            groups.append({'saved_cases': [case], 'identities': identities, 'score': score,
                           'cells': [cell_evidence(s, w, truth, table, readings, identities, layout)
                                     for w in hv.WATERLINES for s in hv.STATIONS]})
    return {'purpose': 'diagnosis only; no arm rerun', 'engineering_approved': False,
            'proximity_note': 'Nearest crossing is evidence, not a recovered station. Near means within '
                              'the frozen 8 px link tolerance; this does not change scoring.',
            'measurement': measurement, 'tables': groups,
            'crossings': {name: {w: [crossing_record(c, r.layout, layout) for c in r.crossings[w]]
                                 for w in hv.WATERLINES} for name, r in readings.items()},
            'chains': {name: [{'chain': i, 'nodes': c.nodes, 'inferred_links': c.inferred_links}
                              for i, c in enumerate(r.chains)] for name, r in readings.items()}}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sheet', type=Path, required=True)
    parser.add_argument('--truth', type=Path, required=True)
    parser.add_argument('--runs', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(diagnose(args.sheet, args.truth, args.runs), indent=2) + '\n', end='')


if __name__ == '__main__':
    main()
