"""Round-13 checks without the drawing, the private truth, or model calls."""
import hashlib
import json
from pathlib import Path

import pytest

from benchmarks.bumble_bee import holdout_value as hv


FROZEN = {
    'benchmarks/frozen_readers/v1/body_plan_reader.py': '327c9f141876dc1945383ebe35023b6e7baaacc34306c5eecf26ffb16ba94e11',
    'benchmarks/frozen_readers/v1/body_plan_crossings.py': 'c6553371691121cd934b0991f273f9ff3a41963d46fd4238034f818aaf6fcf97',
    'benchmarks/frozen_readers/v1/body_plan_identity.py': 'ba738892696025364c3a58664bdf3fbf46e3c7d1a72df7eca31bcc441e9a0c34',
    'benchmarks/balclutha/crossing_value.py': 'f5ab03b178508c1cf9232417c38d2888cc1fb94b07d519e830c9fb5c9df82536',
}


def truth_document(rows=None, **changes):
    document = {'sheet_sha256': hv.SHEET_SHA256, 'stations': list(hv.PRINTED_STATIONS),
                'rows': rows or {w: [None] * 15 for w in hv.WATERLINES}}
    document.update(changes)
    return document


def write(tmp_path, document):
    path = tmp_path / 'truth.json'
    path.write_text(json.dumps(document))
    return path


def test_calibration_matches_the_protocol():
    layout = hv.sheet_layout()
    fore, aft = layout.sides
    assert (fore.name, fore.sign, fore.stations_outer_first) == ('fore', -1, (6, 5, 4, 3, 2, 1))
    assert (aft.name, aft.sign, aft.stations_outer_first) == ('aft', 1, tuple(range(7, 15)))
    assert set(fore.stations_outer_first) | set(aft.stations_outer_first) == set(hv.STATIONS)
    assert layout.centre_column == 3009.0 and layout.max_offset_px == 1900
    assert fore.grid_columns == (2609, 2209, 1809, 1409)
    assert aft.grid_columns == (3409, 3809, 4209, 4609)
    assert layout.waterline_rows == {'1-6-0': 8105, '2-3-0': 7805, '3-0-0': 7505, '3-9-0': 7205}
    assert layout.waterlines_low_to_high() == list(hv.WATERLINES)
    assert layout.pixels_per_metre == pytest.approx(1312.3359580)


def test_waterline_rows_follow_their_printed_height_labels():
    for label, row in hv.WATERLINE_ROWS.items():
        assert isinstance(row, int)
        feet = hv.printed_half_breadth(label) / 0.3048
        assert abs(hv.BASE_ROW - row - feet * hv.PIXELS_PER_FT) <= 0.5


@pytest.mark.parametrize('printed, inches', [('1-0-4+', 12.5 + 1 / 16), ('-1- 0-4', 12.5),
                                              ('0-11-7', 11.875), ('4-5-0', 53)])
def test_parser_uses_magnitude_and_plus_sixteenth(printed, inches):
    assert hv.printed_half_breadth(printed) == pytest.approx(inches * 0.0254)


@pytest.mark.parametrize('printed', ['"', 'ditto', '1-12-0', '1-0-8', '1-0', '1-0-4 1/2'])
def test_parser_rejects_unresolved_values(printed):
    with pytest.raises(ValueError):
        hv.printed_half_breadth(printed)


def test_truth_loader_skips_station_zero_and_blanks(tmp_path):
    document = truth_document()
    document['rows']['1-6-0'][0] = '0-0-0'  # stem column: kept as printed, never scored
    document['rows']['1-6-0'][1] = '0-7-4+'
    document['rows']['3-9-0'][14] = '-1-8-6'
    document['excluded'] = [{'station': 5, 'waterline': '2-3-0', 'printed': '"', 'reason': 'ditto'}]
    truth = hv.load_truth(write(tmp_path, document))
    assert set(truth) == {(1, '1-6-0'), (14, '3-9-0')}
    assert truth[(1, '1-6-0')] == pytest.approx((7.5 + 1 / 16) * 0.0254)
    assert truth[(14, '3-9-0')] == pytest.approx((12 + 8.75) * 0.0254)


@pytest.mark.parametrize('change', [
    lambda d: d.update(sheet_sha256='0' * 64),
    lambda d: d.update(stations=list(range(1, 15))),
    lambda d: d['rows'].pop('3-9-0'),
    lambda d: d['rows'].update({'4-6-0': [None] * 15}),
    lambda d: d['rows']['2-3-0'].pop(),
    lambda d: d['rows']['2-3-0'].__setitem__(3, '"'),
    lambda d: d.update(excluded=[{'station': 0, 'waterline': '2-3-0', 'reason': 'stem'}]),
    lambda d: d.update(excluded=[{'station': 3, 'waterline': '2-3-0', 'printed': '"'}]),
])
def test_truth_loader_stops_on_a_malformed_file(tmp_path, change):
    document = truth_document()
    change(document)
    with pytest.raises(ValueError):
        hv.load_truth(write(tmp_path, document))


def test_scorer_uses_stations_1_to_14_and_detects_swaps():
    truth = {(s, w): 0.2 + s * 0.08 + i * 0.01 for s in hv.STATIONS for i, w in enumerate(hv.WATERLINES)}
    exact = hv.score(truth, truth)
    assert (exact['truth_cells'], exact['cells_given'], exact['rms_m']) == (56, 56, 0.0)
    assert exact['identity_errors'] == []
    swapped = dict(truth)
    for w in hv.WATERLINES:
        swapped[(13, w)], swapped[(14, w)] = truth[(14, w)], truth[(13, w)]
    assert hv.score(swapped, truth)['identity_errors'] == [13, 14]
    partial = {key: value for key, value in truth.items() if key[0] <= 8}
    assert hv.score(partial, truth)['coverage'] == pytest.approx(32 / 56)


def test_run_refuses_a_different_sheet(tmp_path):
    sheet = tmp_path / 'other.tif'
    sheet.write_bytes(b'not the sheet')
    truth = write(tmp_path, truth_document())
    with pytest.raises(ValueError, match='SHA-256'):
        hv.run('code', sheet, truth, tmp_path / 'out')
    assert not (tmp_path / 'out').exists()


def test_reader_matches_the_frozen_checkpoint():
    root = Path(__file__).resolve().parents[1]
    for name, digest in FROZEN.items():
        assert hashlib.sha256((root / name).read_bytes()).hexdigest() == digest
