"""Aggregate an offline synthetic GA measurement; never makes model calls.

Run with PYTHONPATH=src:. python scripts/summarize_ga_synthetic_run.py RUN_ROOT.
Per-case scores and exam answers stay under RUN_ROOT. Reader/scorer rules are unchanged.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
from statistics import median
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from score_ga_exam import load_predictions, score as exam_score
from benchmarks.ga_synthetic.score import FACES, score


def write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, indent=2, allow_nan=False) + '\n')


def summarize(root: Path) -> dict:
    totals = defaultdict(lambda: {'truth': 0, 'found': 0, 'invented': 0, 'unmeasured': 0,
                                 'predicted': 0, 'faces': defaultdict(list), 'guessed_matches': 0})
    answers, cases, errors = {}, {}, {}
    for truth_path in sorted((root / 'truth').glob('*.json')):
        truth = json.loads(truth_path.read_text())
        case = truth['case_id']
        counts = Counter(s['kind'] for s in truth['spaces'])
        answers[case] = {**truth['dimensions'], 'cargo_holds': counts['cargo_hold'],
                         'cargo_hatches': counts['cargo_hatch'], 'cargo_cranes': counts['cargo_crane']}
        arrangement_path = root / 'run' / case / 'ga_arrangement_input.json'
        for kind, count in counts.items():
            totals[kind]['truth'] += count
        if not arrangement_path.exists():
            errors[case] = 'missing arrangement input; all truth spaces retained as missing'
            continue
        arrangement = json.loads(arrangement_path.read_text())
        try:
            result = score(truth, arrangement)
        except ValueError as error:
            errors[case] = str(error)
            # Preserve the raw failure. Translate only the incompatible provenance name
            # on a separate input copy; boxes and matching rules do not change.
            translated = json.loads(json.dumps(arrangement))
            changes = []
            for space in translated['spaces']:
                statuses = (space.get('extent') or {}).get('status') or {}
                for axis, status in statuses.items():
                    if status == 'printed':
                        statuses[axis] = 'read'
                        changes.append({'id': space['id'], 'axis': axis})
            if not changes:
                continue
            try:
                result = score(truth, translated)
            except ValueError as translated_error:
                errors[case] += f'; compatibility copy: {translated_error}'
                continue
            write_json(root / 'run' / case / 'scorer-compatible-input.json', translated)
            write_json(root / 'run' / case / 'status-translation.json', {'printed_to_read': changes})
        write_json(root / 'run' / case / 'synthetic-score.json', result)
        cases[case] = {k: result[k] for k in ('found_fraction', 'missing', 'invented', 'unmeasured')}
        reading_kinds = {s['id']: s['kind'] for s in arrangement['spaces']}
        for kind, entry in result['by_kind'].items():
            totals[kind]['found'] += entry['found_count']
            totals[kind]['invented'] += len(entry['invented'])
        for space in arrangement['spaces']:
            totals[space['kind']]['predicted'] += 1
        for space_id in result['unmeasured']:
            totals[reading_kinds[space_id]]['unmeasured'] += 1
        for match in result['matches']:
            total = totals[match['kind']]
            total['guessed_matches'] += bool(match['guessed_axes'])
            for face, error in match['face_error_m'].items():
                total['faces'][face].append(abs(error))
    by_kind = {}
    for kind, total in sorted(totals.items()):
        by_kind[kind] = {k: v for k, v in total.items() if k != 'faces'}
        by_kind[kind]['found_share'] = total['found'] / total['truth'] if total['truth'] else None
        by_kind[kind]['invented_share_of_predictions'] = (
            total['invented'] / total['predicted'] if total['predicted'] else None)
        by_kind[kind]['absolute_face_error_m'] = {
            face: {'n': len(total['faces'][face]),
                   'median': median(total['faces'][face]) if total['faces'][face] else None,
                   'worst': max(total['faces'][face]) if total['faces'][face] else None}
            for face in FACES}
    receipts = [json.loads(p.read_text()) for p in sorted((root / 'run').glob('**/receipts/*.json'))]
    readings = [json.loads(p.read_text()) for p in (root / 'run').glob('*/ga_reading.json')]
    usage = {'receipt_attempts': len(receipts),
             'reading_reported_requests': sum(d['usage']['requests'] for d in readings),
             'receipts_without_observed_cost': sum(r.get('observed_cost_usd') is None for r in receipts),
             'states': dict(Counter(r['state'] for r in receipts)),
             'models': dict(Counter(r.get('requested_model') for r in receipts)),
             'observed_cost_usd': sum(r.get('observed_cost_usd') or 0 for r in receipts),
             'list_cost_usd': sum((r.get('usage') or {}).get('list_cost') or 0 for r in receipts),
             'prompt_tokens': sum((r.get('usage') or {}).get('prompt_tokens') or 0 for r in receipts),
             'completion_tokens': sum((r.get('usage') or {}).get('completion_tokens') or 0 for r in receipts)}
    assert len(receipts) <= 80, 'Campaign request cap exceeded'
    write_json(root / 'exam-answers.json', answers)
    exam = exam_score(load_predictions(root / 'run'), answers)
    write_json(root / 'exam-score.json', exam)
    result = {'by_kind': by_kind, 'cases': cases, 'errors': errors, 'usage': usage,
              'exam_fields': exam['fields'], 'exam_groups': exam['groups'], 'engineering_approved': False}
    write_json(root / 'aggregate.json', result)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('root', type=Path)
    print(json.dumps(summarize(parser.parse_args().root), indent=2))
