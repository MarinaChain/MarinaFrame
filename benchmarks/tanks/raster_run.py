"""Run the raster tank-plan reader on one case and score it (docs/TANKS_V2.md section 3).

Usage (outputs are drawing derivatives: keep them in the git-ignored ``work/``)::

    PYTHONPATH=src:. python -m benchmarks.tanks.raster_run --case gunnerus_tank_plan --dpi 300 \\
        --sources ../../../work/sources --hull ../../../work/whole-vessel/final/whole-vessel-draft.glb \\
        --truth work/tanks-raster/truth/d1_tank_plan_rev1.json --out work/tanks-raster/runs/d1-300

Huddell holdout (section 4): ``--scorer holdout --truth <liberty_truth/truth.json>`` scores with
``benchmarks.tanks.holdout_score`` (H1 to H3, decision rule) and writes ``holdout_score.json``.

The model (Claude Sonnet 5.5, Claude Code CLI on the subscription) reads text only; its answers
are cached per question image in ``--cache`` so a code change replays without new calls.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import statistics
import time

from benchmarks.tanks import holdout_score
from benchmarks.tanks.raster_cases import load_case
from vessel_reconstruction import tank_plan_raster as raster
from vessel_reconstruction import tanks

R1_TARGET = 0.80
R2_TARGET_M = 0.5
R3_TARGET = 0.15
R4_GROUP_TARGET = 0.15
R4_TOTAL_TARGET = 0.10
LIQUID_GROUPS = ('water ballast', 'fresh water', 'fuel oil', 'misc')


# --------------------------------------------------------------------------- truth

def truth_d1(path: Path) -> dict:
    return json.loads(path.read_text())


def truth_d2(sources: Path) -> dict:
    """The v1 truth: the printed table of the vector Tank Arrangement (same drawing as D2)."""
    from benchmarks.gunnerus import whole_vessel_internals as vector

    dxf = sources / 'gunnerus' / vector.TANK_PLAN
    texts = vector._texts(dxf, (0, 0, 80000, 60000))
    rows = [{'number': row.number, 'name': row.name, 'frames': list(row.frames), 'volume_m3': row.volume_m3,
             'group': row.group} for row in vector.read_tank_table(texts)]
    totals = {group: value['volume_m3'] for group, value in vector.read_table_totals(texts).items()}
    return {'source': 'Tank Arrangement Rev0.dxf printed table (as docs/TANKS_V1.md)', 'rows': rows,
            'group_totals_m3': totals}


# --------------------------------------------------------------------------- scoring

def _number_side(key: str | None) -> tuple[str, str] | None:
    match = re.fullmatch(r'no (\d+) ?(p|sb)?', key or '')
    return (match.group(1), match.group(2) or '') if match else None


def match_rows(truth_rows: list[dict], built: list[dict]) -> dict[int, int]:
    """Truth row index -> built tank index. A tank number matches when the numbers agree and the
    sides agree or one side is not printed (a unique match); a row without a number matches a
    tank without a number whose label shares a name word."""
    matched: dict[int, int] = {}
    used: set[int] = set()
    for i, row in enumerate(truth_rows):
        wanted = _number_side(raster.tank_key(row['number'] or ''))
        if not wanted:
            continue
        exact = [j for j, t in enumerate(built) if j not in used and _number_side(t['key']) == wanted]
        loose = [j for j, t in enumerate(built) if j not in used and _number_side(t['key'])
                 and _number_side(t['key'])[0] == wanted[0]
                 and ('' in (_number_side(t['key'])[1], wanted[1]))]
        choice = exact[:1] or (loose if len(loose) == 1 else [])
        if choice:
            matched[i] = choice[0]
            used.add(choice[0])
    for i, row in enumerate(truth_rows):
        if i in matched or _number_side(raster.tank_key(row['number'] or '')):
            continue
        name_words = raster.words(row['name']) | raster.words(row['number'] or '')
        for j, tank in enumerate(built):
            if j in used or tank['key']:
                continue
            if name_words & raster.words(tank['label']):
                matched[i] = j
                used.add(j)
                break
    return matched


def score(truth: dict, records: list[dict]) -> dict:
    from benchmarks.gunnerus.whole_vessel_internals import frame_x_m

    built = [r for r in records if r['built']]
    rows = truth['rows']
    matched = match_rows(rows, built)
    with_volume = [i for i, row in enumerate(rows) if row['volume_m3']]
    g1, g2 = {}, {}
    for i, j in matched.items():
        row, tank = rows[i], built[j]
        aft, fwd = (frame_x_m(f) for f in row['frames'])
        if aft is not None and fwd is not None:
            g1[row['number'] or row['name']] = [round(tank['x_m'][0] - aft, 3), round(tank['x_m'][1] - fwd, 3)]
        if row['volume_m3']:
            g2[row['number'] or row['name']] = {'built_m3': round(tank['volume_m3'], 3), 'table_m3': row['volume_m3'],
                                                'rel_error': round(tank['volume_m3'] / row['volume_m3'] - 1, 4),
                                                'label': tank['label']}
    ends = [abs(e) for pair in g1.values() for e in pair]
    errors = [abs(v['rel_error']) for v in g2.values()]
    coverage = sum(1 for i in with_volume if i in matched) / len(with_volume)
    # T2: the capacity plan's own groups (the reader's content) against the printed totals.
    groups = {}
    for group in LIQUID_GROUPS:
        printed = truth['group_totals_m3'].get(group)
        ours = sum(t['volume_m3'] for t in built if t['content'] == group)
        by_truth_group = sum(built[j]['volume_m3'] for i, j in matched.items() if rows[i]['group'] == group)
        groups[group] = {'printed_m3': printed, 'built_m3': round(ours, 3),
                         'rel_error': round(ours / printed - 1, 4) if printed else None,
                         'built_by_truth_group_m3': round(by_truth_group, 3)}
    printed_total = sum(v['printed_m3'] or 0 for v in groups.values())
    built_total = sum(v['built_m3'] for v in groups.values())
    numbered = [i for i, row in enumerate(rows) if _number_side(raster.tank_key(row['number'] or ''))]
    return {
        'R1_coverage': {'value': round(coverage, 3), 'matched': len([i for i in with_volume if i in matched]),
                        'rows_with_volume': len(with_volume), 'built_tanks': len(built), 'target': R1_TARGET},
        'R2_ends_median_abs_m': {'value': round(statistics.median(ends), 3) if ends else None, 'n_tanks': len(g1),
                                 'per_tank': g1, 'target': R2_TARGET_M},
        'R3_volume_median_abs_rel': {'value': round(statistics.median(errors), 4) if errors else None,
                                     'n_tanks': len(g2), 'within_10pct': sum(e <= 0.10 for e in errors),
                                     'within_3pct': sum(e <= 0.03 for e in errors), 'per_tank': g2,
                                     'target': R3_TARGET},
        'R4_groups': {'per_group': groups, 'grand_total_rel_error': round(built_total / printed_total - 1, 4),
                      'group_target': R4_GROUP_TARGET, 'total_target': R4_TOTAL_TARGET},
        'R7_numbers_read': {'value': round(sum(1 for i in numbered if i in matched) / len(numbered), 3)
                            if numbered else None, 'rows_with_number': len(numbered)},
        'unmatched_rows': [rows[i]['number'] or rows[i]['name'] for i in range(len(rows)) if i not in matched],
        'unmatched_tanks': [t['label'] for j, t in enumerate(built) if j not in matched.values()],
    }


# --------------------------------------------------------------------------- run

def plan_view_roles(specs: list) -> dict[str, str]:
    """Plan view name (as ``read_sheets`` names it in the tank records) -> plan role."""
    roles = {}
    for number, sheet in enumerate(specs):
        prefix = f'sheet{number + 1}_' if len(specs) > 1 else ''
        roles.update({prefix + view.name: view.role for view in sheet.views if view.kind == 'plan'})
    return roles


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--case', required=True)
    parser.add_argument('--sources', type=Path, required=True)
    parser.add_argument('--dpi', type=int, default=300)
    parser.add_argument('--scan', action='store_true', help='the simulated bilevel scan variant')
    parser.add_argument('--hull', type=Path, help='whole-vessel GLB with a "hull" node (clip)')
    parser.add_argument('--truth', help='truth JSON, or "d2" for the v1 vector table')
    parser.add_argument('--scorer', choices=('dev', 'holdout'), default='dev',
                        help='dev: R1 to R7 (section 3); holdout: H1 to H3 (section 4, Huddell truth.json)')
    parser.add_argument('--cache', type=Path, default=Path('work/tanks-raster/cache'))
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--task', type=Path, help='Task whose build the tank display belongs to')
    parser.add_argument('--revision', help='Revision of the task build')
    args = parser.parse_args()
    if (args.task is None) != (args.revision is None):
        parser.error('--task and --revision must be supplied together')
    from vessel_reconstruction.display_provenance import bind_display_output, check_display_record
    binding = bind_display_output(args.out / 'tanks.glb', args.task, args.revision)
    if binding is not None and args.hull:
        _, reason = check_display_record(args.hull, binding)
        if reason is not None:
            raise ValueError(f'Cannot bind the tank display: {reason}.')

    started = time.time()
    args.out.mkdir(parents=True, exist_ok=True)
    sheets = load_case(args.sources, args.case, args.dpi, args.scan)
    view_roles = plan_view_roles([sheet for _, _, sheet in sheets])
    slicer = None
    if args.hull:
        from benchmarks.gunnerus.whole_vessel_internals import hull_triangles_from_glb
        slicer = tanks.HullSlicer(hull_triangles_from_glb(args.hull))
    ask = raster.claude_asker(args.cache)
    results, reading = raster.read_sheets(sheets, ask, slicer)
    del sheets
    reading.update(case=args.case, scan_variant=args.scan, seconds=round(time.time() - started, 1))
    model = raster.tank_model(results)
    if binding != bind_display_output(args.out / 'tanks.glb', args.task, args.revision):
        raise ValueError('The selected build changed while making the tank model.')
    tanks.save_tanks(model, args.out / 'tanks.npz')
    tanks.write_tanks_display(model, args.out / 'tanks.glb', task=args.task, revision=args.revision)
    from vessel_reconstruction.exports.tank_tables import write_tank_tables
    stamp = [f'Draft tank model from a raster tank plan ({args.case}). Not approved for construction.',
             'Units metres; x forward from frame 0, y to port, z up from the baseline.']
    write_tank_tables(model, args.out / 'tank_tables', f'{args.case}_DRAFT', stamp)
    if args.scorer == 'holdout':
        if not args.truth:
            parser.error('--scorer holdout needs --truth (liberty_truth/truth.json)')
        result = holdout_score.score(holdout_score.load_truth(Path(args.truth)), reading['tanks'], view_roles)
        (args.out / 'holdout_score.json').write_text(json.dumps(result, indent=1) + '\n')
        (args.out / 'reading.json').write_text(json.dumps(reading, indent=1, default=str) + '\n')
        print(json.dumps({'H1': result['H1_coverage']['value'], 'H2': result['H2_volume_median_abs_rel']['value'],
                          'H3_total': result['H3_totals']['grand_total_rel_error'],
                          'decision': result['decision'], 'tanks_built': result['H1_coverage']['built_tanks'],
                          'seconds': reading['seconds']}, indent=1))
        return
    if args.truth:
        truth = truth_d2(args.sources) if args.truth == 'd2' else truth_d1(Path(args.truth))
        reading['metrics'] = score(truth, reading['tanks'])
    (args.out / 'reading.json').write_text(json.dumps(reading, indent=1, default=str) + '\n')
    summary = {key: (value.get('value') if isinstance(value, dict) and 'value' in value else value)
               for key, value in reading.get('metrics', {}).items() if key != 'R4_groups'}
    if 'metrics' in reading:
        summary['R4'] = {g: v['rel_error'] for g, v in reading['metrics']['R4_groups']['per_group'].items()}
        summary['R4_total'] = reading['metrics']['R4_groups']['grand_total_rel_error']
    summary['tanks_built'] = sum(t['built'] for t in reading['tanks'])
    summary['seconds'] = reading['seconds']
    print(json.dumps(summary, indent=1))


if __name__ == '__main__':
    main()
