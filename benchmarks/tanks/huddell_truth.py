"""Convert the frozen EC2-S-C1 capacity tables into the Huddell holdout truth file (protocol 4.1-4.3).

Rules (fixed before the run): one row per physical tank. Tanks printed in both WATER BALLAST (cu ft) and
FUEL OIL (US gal) are dual-use: the cu ft value is used, content "fuel oil or ballast", gallons in the note.
The second printed "No.5P" in WATER BALLAST is No.5S (protocol 4.2). Unnumbered rows keep number null.
"""
import json
import sys

source, out = sys.argv[1], sys.argv[2]
tables = {t['title']: t['rows'] for t in json.load(open(source))['tables']}


def number(row):
    return int(row['number']) if row.get('number') else None


def side(row):
    return row.get('side') or 'C'


ballast = tables['WATER BALLAST']
seen_5p = False
for row in ballast:  # protocol 4.2: the second printed No.5P is No.5S
    if row['name'] == 'WATER BALLAST' and row['number'] == '5' and row['side'] == 'P':
        if seen_5p:
            row['side'], row['note'] = 'S', 'printed 5P; second 5P in P/S order is 5S (protocol 4.2)'
        seen_5p = True

fuel_gallons = {}
for row in tables['FUEL OIL']:
    if row['name'] == 'FUEL OIL TANK':
        fuel_gallons[('double bottom', number(row), side(row))] = row['cells'][0]
    elif row['name'].startswith('CARGO OIL OR FUEL OIL'):
        fuel_gallons[('deep tank', number(row), side(row))] = row['cells'][0]

rows = []
for row in ballast:
    name, value = row['name'], float(row['cells'][0])
    if name == 'WATER BALLAST':
        kind = 'double bottom'
    elif name == 'DEEP TANKS':
        kind = 'deep tank'
    else:
        kind = 'peak'
    key = (kind, number(row), side(row))
    content = 'fuel oil or ballast' if key in fuel_gallons else ('fresh water' if 'CULINARY' in name else 'ballast')
    note = row.get('note')
    if key in fuel_gallons:
        note = '; '.join(filter(None, [note, f'also printed in FUEL OIL as {fuel_gallons.pop(key)} US gal']))
    rows.append({'name': f"{name} {row.get('number') or ''}{row.get('side') or ''}".strip(), 'number': number(row),
                 'side': side(row), 'kind': kind, 'content': content, 'printed_value': value,
                 'printed_unit': 'cu ft', 'note': note})

assert not fuel_gallons, f'fuel rows without a ballast twin: {fuel_gallons}'
for row in tables['FRESH WATER']:
    feed = row['name'] == 'RESERVE FEED'
    rows.append({'name': f"{row['name']} {row.get('number') or ''}{row.get('side') or ''}".strip(),
                 'number': number(row), 'side': side(row), 'kind': 'double bottom' if feed else 'other',
                 'content': 'feed water' if feed else 'fresh water', 'printed_value': float(row['cells'][0]),
                 'printed_unit': 'US gal', 'note': None})
for row in tables['FUEL OIL']:
    if 'SETTLING' in row['name']:
        rows.append({'name': f"{row['name']} {row.get('side') or ''}".strip(), 'number': number(row),
                     'side': side(row), 'kind': 'settling', 'content': 'fuel oil',
                     'printed_value': float(row['cells'][0]), 'printed_unit': 'US gal', 'note': None})

json.dump({'source': 'EC2-S-C1 capacity plan, SS John W. Brown (mce312cp1942); frozen/table_as_printed.json',
           'rows': rows}, open(out, 'w'), indent=1)
print(len(rows), 'rows;', sum(r['number'] is None for r in rows), 'unnumbered')
