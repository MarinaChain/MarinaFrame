"""Where one section, part, tank or steel group came from (docs/SOURCE_RECORD.md).

Every item of a run carries one small ``source_record`` so the app can show the drawing it was
read from. There are three kinds:

``read``
    The item was read from drawing ink: ``regions`` lists each sheet region it was read from.
``guessed``
    The item is a labelled guess: ``method`` says what rule or model gave it, ``inputs`` lists
    the sheet regions and other parts the guess used.
``unknown``
    The producer cannot say where the item came from: ``reason`` says why.

A region names its sheet file, page, view and, when the reader knows it, the box in sheet
pixels (``box_px`` = [left, top, right, bottom] in a frame of ``page_px`` = [width, height]).
A reader that knows the sheet but not the pixels writes ``box_px: null``; it never invents a box.
"""
from __future__ import annotations

import math
from collections.abc import Iterable

SCHEMA = 'source-record/v1'
KINDS = ('read', 'guessed', 'unknown')
VIEWS = ('profile', 'plan', 'section', 'body plan', 'table')
# Measurement view names of the ship-cad language and the readers -> record view names.
VIEW_NAMES = {'profile': 'profile', 'plan': 'plan', 'body': 'body plan', 'body_plan': 'body plan',
              'body plan': 'body plan', 'section': 'section', 'table': 'table'}
# Keep each record small: the app reads one per part, and a run can have hundreds of parts.
MAX_REGIONS = 8
MAX_INPUTS = 12
MAX_TEXT = 240
# Labels of a value that was not read from ink (ship_cad.resolve_program).
GUESS_LABELS = ('guessed', 'ai_inferred')


def _short(text: str) -> str:
    text = ' '.join(str(text).split())
    return text if len(text) <= MAX_TEXT else text[:MAX_TEXT - 1] + '…'


def view_name(view: str | None) -> str | None:
    """The record view of a reader view name ('plan_1deck' -> 'plan'), or None when unknown."""
    if not view:
        return None
    key = str(view).lower()
    if key in VIEW_NAMES:
        return VIEW_NAMES[key]
    for prefix, name in VIEW_NAMES.items():
        if key.startswith(prefix + '_') or key.endswith('_' + prefix):
            return name
    return None


def region(sheet: str, *, view: str | None, page: int = 0, box_px: Iterable[float] | None = None,
           page_px: Iterable[int] | None = None) -> dict:
    """One sheet region. ``box_px`` and ``page_px`` go together; without them the box is null."""
    record = {'sheet': str(sheet), 'page': int(page), 'view': view_name(view), 'box_px': None}
    if box_px is not None and page_px is not None:
        left, top, right, bottom = (float(v) for v in box_px)
        width, height = (int(v) for v in page_px)
        # Clip to the page: a box partly off the sheet still shows where the ink is.
        left, right = max(0.0, min(left, right)), min(float(width), max(left, right))
        top, bottom = max(0.0, min(top, bottom)), min(float(height), max(top, bottom))
        if right > left and bottom > top:
            record['box_px'] = [round(left, 1), round(top, 1), round(right, 1), round(bottom, 1)]
            record['page_px'] = [width, height]
    return record


def part_input(part_id: str) -> dict:
    """Another part a guess used (for example the deck a bulwark stands on)."""
    return {'part': str(part_id)}


def _unique(items: Iterable[dict], limit: int) -> list[dict]:
    seen, kept = set(), []
    for item in items:
        key = tuple(sorted((k, str(v)) for k, v in item.items()))
        if key not in seen:
            seen.add(key)
            kept.append(item)
    return kept[:limit]


def read(regions: Iterable[dict]) -> dict:
    regions = _unique(regions, MAX_REGIONS)
    if not regions:
        raise ValueError('a read record needs at least one region')
    return {'kind': 'read', 'regions': regions}


def guessed(method: str, inputs: Iterable[dict] = ()) -> dict:
    return {'kind': 'guessed', 'method': _short(method), 'inputs': _unique(inputs, MAX_INPUTS)}


def unknown(reason: str) -> dict:
    return {'kind': 'unknown', 'reason': _short(reason)}


def _check_region(item: dict) -> None:
    if not isinstance(item.get('sheet'), str) or not item['sheet']:
        raise ValueError('a region needs a sheet file name')
    if not isinstance(item.get('page'), int) or item['page'] < 0:
        raise ValueError('a region page is a whole number from 0')
    if item.get('view') is not None and item['view'] not in VIEWS:
        raise ValueError(f'unknown region view {item["view"]!r}')
    box = item.get('box_px')
    if box is None:
        return
    page = item.get('page_px')
    if (not isinstance(box, list) or len(box) != 4 or not all(isinstance(v, (int, float)) and math.isfinite(v)
                                                              for v in box)):
        raise ValueError('box_px is [left, top, right, bottom]')
    if not isinstance(page, list) or len(page) != 2 or not all(isinstance(v, int) and v > 0 for v in page):
        raise ValueError('a region with a box needs page_px [width, height]')
    if not (0 <= box[0] < box[2] <= page[0] and 0 <= box[1] < box[3] <= page[1]):
        raise ValueError('box_px must lie on the page')


def validate(record: dict) -> dict:
    """Return ``record`` when it is a valid source record; raise ValueError otherwise."""
    if not isinstance(record, dict) or record.get('kind') not in KINDS:
        raise ValueError('a source record has kind read, guessed or unknown')
    if record['kind'] == 'read':
        regions = record.get('regions')
        if not isinstance(regions, list) or not 0 < len(regions) <= MAX_REGIONS:
            raise ValueError('a read record has 1 to 8 regions')
        for item in regions:
            _check_region(item)
    elif record['kind'] == 'guessed':
        if not isinstance(record.get('method'), str) or not record['method'].strip():
            raise ValueError('a guessed record says its rule or method')
        inputs = record.get('inputs')
        if not isinstance(inputs, list) or len(inputs) > MAX_INPUTS:
            raise ValueError('a guessed record has at most 12 inputs')
        for item in inputs:
            if 'part' in item:
                if not isinstance(item['part'], str) or not item['part'] or len(item) != 1:
                    raise ValueError('a part input is {"part": id}')
            else:
                _check_region(item)
    elif not isinstance(record.get('reason'), str) or not record['reason'].strip():
        raise ValueError('an unknown record says why')
    return record


# ---------------------------------------------------------------- ship-cad components

def _measurement_region(record: dict) -> dict | None:
    """The sheet region of a traced measurement, when its reader named the sheet."""
    given = record.get('sheet_region')
    if isinstance(given, dict) and given.get('sheet'):
        return region(given['sheet'], view=given.get('view') or record.get('view'), page=given.get('page', 0),
                      box_px=given.get('box_px'), page_px=given.get('page_px'))
    return None


def component_record(evidence: dict, *, part_refs: Iterable[str] = (), unspecified: bool = False) -> dict:
    """The source record of one ship-cad component from its argument evidence.

    ``evidence`` maps an argument or measurement reference to the record that gave its value
    (ship_cad.resolve_program): a traced measurement, or a ``{source, basis}`` fill.
    ``part_refs`` are other components the part is built on (an opening's target).
    """
    regions, guesses, unplaced = [], [], []
    for reference, record in evidence.items():
        if not isinstance(record, dict):
            continue
        if record.get('source') in GUESS_LABELS:
            guesses.append(f'{reference}: {record.get("basis") or record["source"]}')
            continue
        if record.get('status') == 'measured':
            place = _measurement_region(record)
            if place is None:
                unplaced.append(reference)
            else:
                regions.append(place)
    inputs = regions + [part_input(ref) for ref in part_refs]
    if unspecified:
        return unknown('The part program did not name a recognised source; it was built from its values.')
    if guesses:
        return guessed('; '.join(guesses), inputs)
    if regions:
        return read(regions)
    if unplaced:
        return unknown(f'Measured ({", ".join(unplaced)}) but the reader did not record the sheet.')
    if part_refs:
        return guessed('Built from other parts', inputs)
    return unknown('No measurement or guess records this part.')


# ---------------------------------------------------------------- hull sections

def section_region(source_file: str, roi_px, *, page: int, page_px, view: str = 'body plan') -> dict:
    """The body-plan region of one section: its region of interest on the rendered page."""
    return region(source_file, view=view, page=page, box_px=roi_px, page_px=page_px)


def traced_section(source_file: str, roi_px, *, page: int, page_px) -> dict:
    return read([section_region(source_file, roi_px, page=page, page_px=page_px)])


def authored_section(source_file: str, roi_px, *, page: int, page_px, label: str, basis: str) -> dict:
    """A model-authored section: a guess that used the model's view of the section region."""
    return guessed(f'Model-authored section ({label}): {basis}',
                   [section_region(source_file, roi_px, page=page, page_px=page_px)])


def _neighbours(sections: list[dict], index: int) -> list[str]:
    """Ids of the nearest sections aft and forward of ``sections[index]`` that are not themselves
    interpolated (the sections an interpolated section is made from)."""
    x = sections[index].get('x_m')
    if not isinstance(x, (int, float)):
        return []
    others = [s for s in sections if s.get('source_label') != 'interpolated' and isinstance(s.get('x_m'), (int, float))]
    aft = max((s for s in others if s['x_m'] < x), key=lambda s: s['x_m'], default=None)
    fwd = min((s for s in others if s['x_m'] > x), key=lambda s: s['x_m'], default=None)
    return [str(s['id']) for s in (aft, fwd) if s is not None]


def finish_sections(sections: list[dict], *, faired: bool = False) -> None:
    """Make each built section's record say what the build did to it (in place).

    A traced section that a draft repaired or that hull fairing replaced is a guess that used its
    region; an interpolated section is a guess from its neighbours; a section whose reader wrote
    no record (the table reader) is unknown.
    """
    for index, section in enumerate(sections):
        record = section.get('source_record')
        label = section.get('source_label', 'traced')
        regions = record.get('regions', []) if isinstance(record, dict) and record.get('kind') == 'read' else []
        if label == 'interpolated':
            section['source_record'] = guessed('Interpolated between the neighbouring sections',
                                               [part_input(i) for i in _neighbours(sections, index)])
        elif record is None:
            section['source_record'] = unknown('The reader of this section does not record its sheet region yet.')
        elif regions and label not in ('traced', 'read'):
            section['source_record'] = guessed(f'Draft {label} section from its drawn curve', regions)
        elif regions and faired:
            section['source_record'] = guessed('Taken from one fair surface fitted to all stations', regions)


# ---------------------------------------------------------------- record files

# Records of the tanks of a capacity plan, beside it: tank_tables/<stem>_source_records.json
# (the app reads it with <stem>_capacity_plan.csv, app/core/src/run_tables.rs).
TANK_RECORDS_SUFFIX = '_source_records.json'


def write_records(path, records: dict) -> None:
    """Write ``{id: record}`` as a record file, after checking each record."""
    import json
    from pathlib import Path

    for record in records.values():
        validate(record)
    Path(path).write_text(json.dumps({'schema': SCHEMA, 'records': records}, indent=1) + '\n')
