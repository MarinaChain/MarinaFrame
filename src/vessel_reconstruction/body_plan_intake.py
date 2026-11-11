"""The scanned body-plan reader in the app's hull path (docs/AUTO_CALIBRATION.md, step 3).

At intake (`intake.write_spec`), when the setting MARINAFRAME_BODY_PLAN_READER=1 is on, the
spec page is calibrated automatically (`sheet_calibration`, label questions through the Claude
CLI) and each half is read by `body_plan_sides.read_side`: the crossing reader with code-only
station identity (nesting order), and the hard-chine polyline reader where it engages (a half
read as a whole, or single stations with a clear chine knuckle). The result goes into
`intake.json` as `body_plan_reading`: the calibration with its source labels and flags, per
station the code-measured waterline cells, the drawn curve in metres and where its name came
from (`identity_source`), and per half what the hard-chine reader did (`hard_chine`).

In the worker, the first hull (`first_hull_tools.build_first_hull`) uses these station curves
as anchors for the stations it read, labelled as code-traced from the body plan, when the
calibration has no open flag. Stations the reader did not read keep the model path (traced
candidates, form fit). A flagged calibration is not used; the person sees why. In both cases
the worker writes the calibration overlay and a summary into the task (`domain/body-plan-check.*`)
for the review UI, where a person confirms it as one item.

This module only calls the readers; it does not change their output.
"""
from __future__ import annotations

import copy
import json
import os
import re
from pathlib import Path

import numpy as np

from vessel_reconstruction import body_plan_reader as bpr
from vessel_reconstruction import body_plan_sides
from vessel_reconstruction import calibration_reading as cr
from vessel_reconstruction import sheet_calibration as sc

SETTING = 'MARINAFRAME_BODY_PLAN_READER'
SCHEMA = 'marinaframe/body-plan-reading/v1'
CHECK_JSON = 'body-plan-check.json'
CHECK_PNG = 'body-plan-check.png'
ANSWERS_FOLDER = 'body-plan-answers'
# Points kept per drawn station curve (the builder accepts 5 to 1025).
CURVE_POINTS = 120
MIN_CURVE_POINTS = 5
# The model's own calibration of the body view may differ from the automatic one by this share
# of the scale before the first hull says so.
SCALE_WARNING_SHARE = 0.02


def enabled(environment=None) -> bool:
    return (environment if environment is not None else os.environ).get(SETTING, '').strip() == '1'


# ---------------------------------------------------------------- intake

def _curve_m(path, cal: sc.Calibration) -> list[list[float]]:
    """A drawn station curve, image points (row, column), as [half-breadth m, height m] points, low to
    high, one per height."""
    per_metre = cal.pixels_per_ft / sc.FEET_M
    by_height = {}
    for row, column in path:
        z = round((cal.baseline_row - float(row)) / per_metre, 4)
        y = abs(float(column) - cal.centre_column) / per_metre
        by_height.setdefault(z, []).append(y)
    points = [[float(np.median(ys)), z] for z, ys in sorted(by_height.items())]
    if len(points) > CURVE_POINTS:
        keep = np.linspace(0, len(points) - 1, CURVE_POINTS).round().astype(int)
        points = [points[i] for i in keep]
    return [[round(y, 4), round(z, 4)] for y, z in points]


def waterline_spacing_m(cal: sc.Calibration) -> float:
    heights = sorted(w['height_ft'] for w in cal.waterlines)
    gaps = np.diff(heights)
    return float(np.median(gaps)) * sc.FEET_M if len(gaps) else sc.FEET_M


def read_body_plan(ink: np.ndarray, reading, dpi: float | None) -> tuple[dict, sc.Calibration]:
    """Calibrate and read one sheet; returns (record, calibration)."""
    cal = sc.calibrate(ink, reading, dpi=dpi)
    return read_with_calibration(ink, cal), cal


def read_with_calibration(ink: np.ndarray, cal: sc.Calibration) -> dict:
    """Run the same frozen reader with an existing calibration, including person corrections."""
    record = {'schema': SCHEMA, 'calibration': calibration_record(cal), 'stations': [],
              'engineering_approved': False, 'identity': 'code: nesting order (outermost chain first)'}
    if not cal.usable:
        record['usable_for_build'] = False
        record['reason'] = 'calibration incomplete'
        return record
    layout = cal.layout()
    heights = {w['label']: w['height_ft'] * sc.FEET_M for w in cal.waterlines}
    for side in layout.sides:
        result = body_plan_sides.read_side(ink, layout, bpr.measure_side(ink, layout, side))
        for station in sorted(result.curves):
            cells = sorted([[round(heights[w], 4), round(value, 4)] for (s, w), value in result.table.items()
                            if s == station and w in heights])
            curve = _curve_m(result.curves[station], cal)
            source = result.identity_source[station]
            if cells and source == body_plan_sides.IDENTITY_RANK:
                # The followed ink beyond the waterlines can run onto rails, deck lines or a
                # neighbour; keep one waterline spacing past the measured cells (the first hull
                # continues the curve to the keel and deck from the profile). A traced polyline
                # ends at its own sheer and rabbet, so it is kept whole.
                margin = waterline_spacing_m(cal)
                low, high = cells[0][0] - margin, cells[-1][0] + margin
                curve = [p for p in curve if low <= p[1] <= high]
            record['stations'].append({'station': station, 'side': side.name, 'cells_z_y_m': cells,
                                       'curve_y_z_m': curve, 'identity_source': source})
        record.setdefault('fairness_flags', []).extend(dict(flag, side=side.name) for flag in result.fairness_flags)
        record.setdefault('hard_chine', {})[side.name] = {
            'read_as_whole': result.half.read, 'engaged_stations': [s.station for s in result.half.engaged],
            'notes': list(result.half.notes)}
    record['stations'].sort(key=lambda s: s['station'])
    record['usable_for_build'] = not cal.flags and bool(record['stations'])
    if cal.flags:
        record['reason'] = 'calibration has open flags; a person must confirm it first'
    return record


def calibration_record(cal: sc.Calibration) -> dict:
    """The calibration without the raw model answers (kept in the answers folder)."""
    data = cal.to_json()
    measures = data.pop('measures', {})
    data['scale_measures'] = {name: {k: v for k, v in m.items() if k in ('px_per_ft', 'source')}
                              for name, m in (measures.get('scale') or {}).items()}
    data['side_checks'] = measures.get('side_checks')
    return data


def calibration_from_record(data: dict, scale: float = 1.0) -> sc.Calibration:
    """The calibration of a record, its pixel values multiplied by `scale` (the worker's page may be
    a reduced copy of the sheet the intake read)."""
    def scaled(value):
        return None if value is None else value * scale

    sides = [dict(side, grid_columns=[c * scale for c in side.get('grid_columns', [])])
             for side in data.get('sides') or []]
    waterlines = [dict(w, row=w['row'] * scale) for w in data.get('waterlines') or []]
    cal = sc.Calibration(box=[int(round(v * scale)) for v in data.get('box') or []],
                         centre_column=scaled(data.get('centre_column')), baseline_row=scaled(data.get('baseline_row')),
                         pixels_per_ft=scaled(data.get('pixels_per_ft')), max_offset_px=scaled(data.get('max_offset_px')),
                         waterlines=waterlines, sides=sides, grid_rows=[r * scale for r in data.get('grid_rows') or []],
                         sources=dict(data.get('sources') or {}), notes=list(data.get('notes') or []),
                         resolution_factor=data.get('resolution_factor'))
    cal.flags = [sc.Flag(f['field'], f['message']) for f in data.get('flags') or []]
    return cal


def read_at_intake(sheet: Path, out_dir: Path, ask=None) -> dict:
    """Intake step: read the spec page's body plan; writes the overlay PNG and the answers cache."""
    from PIL import Image

    from vessel_reconstruction import body_plan_crossings as bpc
    with Image.open(sheet) as image:
        dpi = image.info.get('dpi')
    dpi = float(dpi[0]) if dpi and dpi[0] else None
    ink = bpc.load_ink(sheet)
    reading = cr.ClaudeReading(ask or cr.claude_ask(receipts=out_dir / ANSWERS_FOLDER / 'receipts'),
                               cache=out_dir / ANSWERS_FOLDER, sheet_id=sheet.name)
    record, cal = read_body_plan(ink, reading, dpi)
    if cal.box:
        (out_dir / CHECK_PNG).write_bytes(cr.overlay_png(ink, cal))
        record['overlay'] = CHECK_PNG
    record['model_calls'] = reading.calls
    return record


# ---------------------------------------------------------------- worker

def station_number(section_id: str) -> int | None:
    """The station number in a section id such as 'S12', 'st-3', '7' or 'sta_07'."""
    found = re.findall(r'\d+', str(section_id))
    return int(found[-1]) if len(found) == 1 else None


def reader_anchors(sections: list[dict], anchors: list, record: dict | None) -> tuple[list, dict]:
    """Anchors from the body-plan reading for the stations it read; others are kept.

    Returns (anchors, report). Without a usable reading, the anchors are returned unchanged.
    """
    from .form_fit import Anchor
    if not record:
        return anchors, {'used': False, 'reason': 'no body-plan reading (setting off or no body plan)'}
    if not record.get('usable_for_build'):
        warnings = [flag['message'] for flag in record.get('calibration', {}).get('flags', [])
                    if flag.get('field') == 'low_resolution']
        return anchors, {'used': False, 'reason': record.get('reason', 'calibration not usable'),
                         'warnings': warnings}
    curves = {s['station']: s for s in record.get('stations', [])}
    # px per metre on the worker's page (a reduced copy of the read sheet, when it was too large)
    per_metre = record['calibration']['pixels_per_ft'] / sc.FEET_M * record.get('spec_page_scale', 1.0)
    replaced, warnings = [], []
    kept = {a.id: a for a in anchors}
    for section in sections:
        number = station_number(section['id'])
        station = curves.get(number)
        if station is None or len(station['curve_y_z_m']) < MIN_CURVE_POINTS:
            continue
        model_scale = (section.get('calibration') or {}).get('pixels_per_metre')
        if model_scale and abs(model_scale - per_metre) / per_metre > SCALE_WARNING_SHARE:
            warnings.append(f'{section["id"]}: model scale {model_scale:.1f} px/m, body-plan calibration '
                            f'{per_metre:.1f} px/m')
        selection = copy.deepcopy(section)
        selection.pop('contour_selection', None)
        points = [list(p) for p in station['curve_y_z_m']]
        kept[section['id']] = Anchor(section['id'], float(section['x_m']), points, selection,
                                     z_max_m=section.get('z_max_m'), pixels_per_metre=per_metre, source='read',
                                     notes=[f'body-plan reader: station {number}, {station["side"]} half'])
        replaced.append(section['id'])
    ordered = [kept[s['id']] for s in sections if s['id'] in kept]
    report = {'used': bool(replaced), 'stations': replaced, 'warnings': warnings,
              'reason': '' if replaced else 'no section id matched a station the reader read'}
    return ordered, report


def write_check(task_root: Path, image: np.ndarray, record: dict | None, report: dict) -> None:
    """The review item: overlay PNG and summary JSON in the task's domain folder."""
    if not record or not record.get('calibration', {}).get('box'):
        return
    cal = calibration_from_record(record['calibration'], record.get('spec_page_scale', 1.0))
    gray = image.mean(axis=2) if image.ndim == 3 else image
    (task_root / CHECK_PNG).write_bytes(cr.overlay_png(gray < 128, cal))
    summary = {'schema': SCHEMA, 'overlay': CHECK_PNG, 'used': report.get('used', False),
               'stations_used': report.get('stations', []), 'reason': report.get('reason', ''),
               'warnings': report.get('warnings', []),
               'flags': [f'{f.field}: {f.message}' for f in cal.flags], 'notes': cal.notes,
               'pixels_per_ft': cal.pixels_per_ft, 'sources': cal.sources,
               'sides': [{k: s[k] for k in ('name', 'sign', 'stations_outer_first')} for s in cal.sides],
               'engineering_approved': False, 'person_check': 'confirm the centreline, baseline, waterlines '
                                                             'and which half is FORE'}
    (task_root / CHECK_JSON).write_text(json.dumps(summary, indent=2) + '\n')
