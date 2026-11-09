"""The body-plan reader in the hull path: intake record, worker anchors, review item. No sheets or model calls."""
import json

import numpy as np
import pytest

from tests.test_sheet_calibration import FakeReading, synthetic_sheet
from vessel_reconstruction import body_plan_intake as bpi
from vessel_reconstruction import intake
from vessel_reconstruction.form_fit import Anchor, fit_vessel
from vessel_reconstruction.vessel_model import build_spec


def test_setting_is_off_by_default():
    assert bpi.enabled({}) is False
    assert bpi.enabled({bpi.SETTING: '1'}) is True
    assert bpi.enabled({bpi.SETTING: 'yes'}) is False


def test_intake_skips_the_reader_without_the_setting(tmp_path, monkeypatch):
    monkeypatch.delenv(bpi.SETTING, raising=False)
    assert intake._body_plan_reading(tmp_path / 'sheet.png', tmp_path) is None


def test_intake_records_a_failure_instead_of_raising(tmp_path, monkeypatch):
    monkeypatch.setenv(bpi.SETTING, '1')
    record = intake._body_plan_reading(tmp_path / 'missing.png', tmp_path, ask=lambda p, i: '{}')
    assert record['usable_for_build'] is False and 'failed' in record['reason']


def test_reading_of_a_synthetic_body_plan():
    record, cal = bpi.read_body_plan(synthetic_sheet(), FakeReading(), dpi=100.0)
    assert record['usable_for_build'] is True and record['engineering_approved'] is False
    assert sorted(s['station'] for s in record['stations']) == [1, 2, 3, 4, 5, 6]
    station = next(s for s in record['stations'] if s['station'] == 1)
    assert station['side'] == 'fore' and len(station['curve_y_z_m']) >= bpi.MIN_CURVE_POINTS
    heights = [z for _, z in station['curve_y_z_m']]
    assert heights == sorted(heights)
    # outermost fore station (3) is fuller than the innermost (1) at the 3 ft waterline
    def at_3ft(number):
        cells = next(s for s in record['stations'] if s['station'] == number)['cells_z_y_m']
        return min(cells, key=lambda cell: abs(cell[0] - 3 * 0.3048))[1]
    assert at_3ft(3) > at_3ft(1)
    json.dumps(record)


def test_flagged_calibration_is_not_used_for_the_build():
    record, _ = bpi.read_body_plan(synthetic_sheet(), FakeReading(shape_fore='left'), dpi=100.0)
    assert record['usable_for_build'] is False and 'flags' in record['reason']
    anchors, report = bpi.reader_anchors([{'id': 'S1', 'x_m': 1.0}], [], record)
    assert anchors == [] and report['used'] is False


@pytest.mark.parametrize('section_id, number', [('S12', 12), ('st-3', 3), ('7', 7), ('sta_07', 7), ('aft', None),
                                                ('s1-2', None)])
def test_station_number(section_id, number):
    assert bpi.station_number(section_id) == number


def _sections(count=6):
    cal = {'centerline_px': 1000.0, 'baseline_px': 1400.0, 'pixels_per_metre': 100 / 0.3048}
    return [{'id': f'S{i}', 'x_m': float(i), 'roi_px': [0, 0, 10, 10], 'calibration': dict(cal),
             'z_min_m': 0.0, 'z_max_m': 2.0} for i in range(1, count + 1)]


def test_reader_anchors_replace_matching_stations_and_keep_others():
    record, _ = bpi.read_body_plan(synthetic_sheet(), FakeReading(), dpi=100.0)
    sections = _sections(6) + [{'id': 'S9', 'x_m': 9.0, 'calibration': {}}]
    other = Anchor('S9', 9.0, [[0.1, 0.0], [0.5, 1.0]], {'id': 'S9'})
    anchors, report = bpi.reader_anchors(sections, [other], record)
    assert report['used'] and report['stations'] == [f'S{i}' for i in range(1, 7)]
    assert [a.id for a in anchors] == [f'S{i}' for i in range(1, 7)] + ['S9']
    assert all(a.source == 'read' for a in anchors[:6]) and anchors[6].source == 'traced'
    assert 'contour_selection' not in anchors[0].selection_section


def test_read_rows_build_as_traced_authored_curves():
    record, _ = bpi.read_body_plan(synthetic_sheet(), FakeReading(), dpi=100.0)
    sections = _sections(6)
    anchors, _ = bpi.reader_anchors(sections, [], record)
    table = fit_vessel(sections, anchors, None)
    assert {row.source for row in table.stations} <= {'read', 'fitted'}
    assert any(row.source == 'read' for row in table.stations)
    spec = build_spec(table, {'sections': sections}, sections)
    read = [s for s in spec['sections'] if s['authored']['basis'].startswith(bpi_basis())]
    assert read and all(s['authored']['source_label'] == 'traced' for s in read)
    assert all('contour_selection' not in s for s in read)


def bpi_basis():
    from vessel_reconstruction.vessel_model import READ_BASIS
    return READ_BASIS


def test_write_check_writes_overlay_and_summary(tmp_path):
    ink = synthetic_sheet()
    record, _ = bpi.read_body_plan(ink, FakeReading(), dpi=100.0)
    image = np.where(ink, 0, 255).astype(np.uint8)
    bpi.write_check(tmp_path, image, record, {'used': True, 'stations': ['S1'], 'reason': ''})
    summary = json.loads((tmp_path / bpi.CHECK_JSON).read_text())
    assert summary['used'] is True and summary['engineering_approved'] is False and summary['flags'] == []
    assert (tmp_path / bpi.CHECK_PNG).read_bytes().startswith(b'\x89PNG')
    bpi.write_check(tmp_path / 'none', image, None, {'used': False})
    assert not (tmp_path / 'none').exists()
