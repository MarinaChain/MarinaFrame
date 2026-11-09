"""Huddell holdout scorer: H1 to H3 and the decision rule (docs/TANKS_V2.md section 4).

Written and committed before the truth file exists and before the run. It implements the
protocol as fixed; it reads only ``liberty_truth/truth.json`` (format: section 4.1 of the doc, units: amendment 4.2)
and the reader's tank records.
"""
from __future__ import annotations

import json
from pathlib import Path
import re
import statistics

from vessel_reconstruction import tank_plan_raster as raster

CUBIC_FOOT_M3 = 0.0283168  # m3 per cubic foot (protocol: m3 = cu ft x 0.0283168)
US_GALLON_CU_FT = 231 / 1728  # 1 US gal = 231 in3 exactly = 0.1336805556 ft3 (amendment 4.2)
UNIT_CU_FT = {'cu ft': 1.0, 'US gal': US_GALLON_CU_FT}  # printed unit -> cubic feet per unit

H1_TARGET = 0.60  # coverage share, at least
H2_TARGET = 0.20  # median abs relative volume error, at most
H3_TOTAL_TARGET = 0.15  # abs relative error of the grand total, at most
H2_BANDS = (0.10, 0.25)  # counts reported: matched tanks within 10 % and within 25 %

SIDES = ('P', 'S', 'C')
KINDS = ('double bottom', 'deep tank', 'peak', 'settling', 'other')
CONTENTS = ('fuel oil', 'fuel oil or ballast', 'ballast', 'fresh water', 'feed water', 'other')
CONTENT_GROUPS = {
    'fuel oil': ('fuel oil', 'fuel oil or ballast'),
    'ballast': ('ballast',),
    'fresh and feed water': ('fresh water', 'feed water'),
}
ROW_FIELDS = ('name', 'number', 'side', 'kind', 'content', 'printed_value', 'printed_unit')

# Label words that give a built tank its kind, in this order of precedence.
KIND_WORDS = (
    ('deep tank', re.compile(r'\bdeep\b')),
    ('peak', re.compile(r'\bpeak\b')),
    ('settling', re.compile(r'\bsettling\b')),
    ('double bottom', re.compile(r'\bd\.\s*b\b|\bdouble\s+bottom\b')),
)
# The reader's side suffix (``tank_plan_raster.tank_key``) against the truth side letter.
READER_SIDE = {'p': 'P', 'sb': 'S'}


# --------------------------------------------------------------------------- truth

def load_truth(path: Path) -> dict:
    """Read ``truth.json`` (doc section 4.1). Return the rows with a printed capacity, each with
    ``volume_m3`` converted from its printed unit, and the count of rows left out because they
    have no printed capacity. A malformed file raises ValueError."""
    data = json.loads(Path(path).read_text())
    if not isinstance(data, dict) or not isinstance(data.get('rows'), list):
        raise ValueError('truth.json must be an object with a "rows" list')
    rows, left_out = [], 0
    for index, row in enumerate(data['rows']):
        _check_row(index, row)
        if row['printed_value'] is None:
            left_out += 1
            continue
        cubic_feet = row['printed_value'] * UNIT_CU_FT[row['printed_unit']]
        rows.append({**{field: row[field] for field in ROW_FIELDS}, 'note': row.get('note'),
                     'volume_m3': cubic_feet * CUBIC_FOOT_M3})
    return {'source': data.get('source'), 'rows': rows, 'rows_without_capacity': left_out}


def _check_row(index: int, row: object) -> None:
    def fail(problem: str) -> None:
        raise ValueError(f'truth row {index}: {problem}')

    if not isinstance(row, dict):
        fail('not an object')
    missing = [field for field in ROW_FIELDS if field not in row]
    if missing:
        fail(f'missing {missing}')
    unknown = sorted(set(row) - set(ROW_FIELDS) - {'note'})
    if unknown:
        fail(f'unknown fields {unknown}')
    if not isinstance(row['name'], str) or not row['name'].strip():
        fail('name must be a non-empty string')
    number = row['number']
    if number is not None and (isinstance(number, bool) or not isinstance(number, int) or number < 1):
        fail('number must be a positive integer or null')
    if row['side'] not in SIDES:
        fail(f'side must be one of {SIDES}')
    if row['kind'] not in KINDS:
        fail(f'kind must be one of {KINDS}')
    if row['content'] not in CONTENTS:
        fail(f'content must be one of {CONTENTS}')
    value = row['printed_value']
    if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0):
        fail('printed_value must be a positive number or null')
    if value is not None and row['printed_unit'] not in UNIT_CU_FT:
        fail(f'printed_unit must be one of {tuple(UNIT_CU_FT)}')
    if 'note' in row and row['note'] is not None and not isinstance(row['note'], str):
        fail('note must be a string or null')


# --------------------------------------------------------------------------- built tanks

def built_identity(record: dict, plan_role: str | None) -> dict:
    """Tank number, side ('P', 'S' or None) and kind of one built tank, from its label as read
    and the role of its plan view."""
    key = raster.tank_key(record.get('label') or '')
    number, side = None, None
    if key:
        parts = key.split(' ')  # 'no 3' or 'no 3 p' / 'no 3 sb'
        number = int(parts[1])
        side = READER_SIDE[parts[2]] if len(parts) == 3 else None
    return {'number': number, 'side': side, 'kind': built_kind(record.get('label') or '', plan_role)}


def built_kind(label: str, plan_role: str | None) -> str:
    """The kind from the label words; without such a word the plan role ('double_bottom' gives
    'double bottom'; any other role gives 'other')."""
    lower = label.lower()
    for kind, pattern in KIND_WORDS:
        if pattern.search(lower):
            return kind
    return 'double bottom' if plan_role == 'double_bottom' else 'other'


# --------------------------------------------------------------------------- matching

def sides_agree(tank_side: str | None, row: dict, rows: list[dict]) -> bool:
    """Sides agree when equal. A tank without a side matches a centre-line row, or a row that is
    the single row of its tank number and kind."""
    if tank_side is not None:
        return tank_side == row['side']
    if row['side'] == 'C':
        return True
    same = [r for r in rows if r['number'] == row['number'] and r['kind'] == row['kind']]
    return len(same) == 1


def matches(tank: dict, row: dict, rows: list[dict]) -> bool:
    return (row['number'] is not None and tank['number'] == row['number']
            and sides_agree(tank['side'], row, rows) and tank['kind'] == row['kind'])


def match_rows(rows: list[dict], tanks: list[dict]) -> dict[int, int]:
    """Truth row index -> built tank index. Rows are taken in file order; each row takes the
    first unused built tank (reader order) that matches it. Each row and each tank is used once."""
    matched: dict[int, int] = {}
    used: set[int] = set()
    for i, row in enumerate(rows):
        for j, tank in enumerate(tanks):
            if j not in used and matches(tank, row, rows):
                matched[i] = j
                used.add(j)
                break
    return matched


# --------------------------------------------------------------------------- metrics

def _rel_error(built: float, truth: float) -> float | None:
    return built / truth - 1 if truth else None


def score(truth: dict, records: list[dict], view_roles: dict[str, str]) -> dict:
    """H1 to H3 and the decision. ``view_roles`` maps a plan view name (as in the records) to its
    role ('double_bottom' or 'above')."""
    rows = truth['rows']
    built = [r for r in records if r['built']]
    tanks = [built_identity(r, view_roles.get(r.get('view'))) for r in built]
    matched = match_rows(rows, tanks)

    table = []
    for i, row in enumerate(rows):
        j = matched.get(i)
        built_m3 = built[j]['volume_m3'] if j is not None else 0.0
        error = _rel_error(built_m3, row['volume_m3']) if j is not None else None
        table.append({'name': row['name'], 'number': row['number'], 'side': row['side'], 'kind': row['kind'],
                      'content': row['content'], 'note': row['note'],
                      'printed_value': row['printed_value'], 'printed_unit': row['printed_unit'],
                      'truth_m3': round(row['volume_m3'], 3),
                      'matched': j is not None,
                      'built_label': built[j]['label'] if j is not None else None,
                      'built_view': built[j].get('view') if j is not None else None,
                      'built_m3': round(built_m3, 3),
                      'rel_error': None if error is None else round(error, 4)})

    coverage = len(matched) / len(rows) if rows else 0.0
    h1 = {'value': round(coverage, 4), 'matched_rows': len(matched), 'truth_rows': len(rows),
          'built_tanks': len(built), 'target_min': H1_TARGET, 'met': coverage >= H1_TARGET}

    errors = [abs(_rel_error(built[j]['volume_m3'], rows[i]['volume_m3'])) for i, j in matched.items()]
    median = statistics.median(errors) if errors else None
    h2 = {'value': None if median is None else round(median, 4), 'n_matched': len(errors),
          'within_10pct': sum(e <= H2_BANDS[0] for e in errors),
          'within_25pct': sum(e <= H2_BANDS[1] for e in errors),
          'target_max': H2_TARGET, 'met': median is not None and median <= H2_TARGET}

    # Totals use unrounded volumes; an unmatched row counts 0 m3.
    built_of_row = [built[matched[i]]['volume_m3'] if i in matched else 0.0 for i in range(len(rows))]
    groups = {}
    for group, contents in CONTENT_GROUPS.items():
        members = [i for i, row in enumerate(rows) if row['content'] in contents]
        truth_m3 = sum(rows[i]['volume_m3'] for i in members)
        built_m3 = sum(built_of_row[i] for i in members)
        error = _rel_error(built_m3, truth_m3)
        groups[group] = {'truth_m3': round(truth_m3, 3), 'built_m3': round(built_m3, 3), 'rows': len(members),
                         'rel_error': None if error is None else round(error, 4)}
    truth_total = sum(row['volume_m3'] for row in rows)
    built_total = sum(built_of_row)
    total_error = _rel_error(built_total, truth_total)
    h3 = {'per_group': groups, 'grand_total_truth_m3': round(truth_total, 3),
          'grand_total_built_m3': round(built_total, 3),
          'grand_total_rel_error': None if total_error is None else round(total_error, 4),
          'target_max': H3_TOTAL_TARGET,
          'met': total_error is not None and abs(total_error) <= H3_TOTAL_TARGET}

    missed = [name for name, metric in (('H1', h1), ('H2', h2), ('H3', h3)) if not metric['met']]
    return {
        'protocol': 'docs/TANKS_V2.md section 4 (Huddell holdout)',
        'truth_source': truth.get('source'), 'rows_without_capacity': truth.get('rows_without_capacity', 0),
        'H1_coverage': h1, 'H2_volume_median_abs_rel': h2, 'H3_totals': h3,
        'decision': {'passed': not missed, 'missed': missed},
        'rows': table,
        'unmatched_tanks': [built[j]['label'] for j in range(len(built)) if j not in matched.values()],
        'engineering_approved': False,
    }
