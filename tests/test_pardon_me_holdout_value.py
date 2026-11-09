"""Round-14 checks without drawings, private truth, or model calls."""
import hashlib
import json
from pathlib import Path

import pytest

from benchmarks.pardon_me import holdout_value as hv


FROZEN = {
    'src/vessel_reconstruction/body_plan_reader.py': '327c9f141876dc1945383ebe35023b6e7baaacc34306c5eecf26ffb16ba94e11',
    'src/vessel_reconstruction/body_plan_crossings.py': 'c6553371691121cd934b0991f273f9ff3a41963d46fd4238034f818aaf6fcf97',
    'src/vessel_reconstruction/body_plan_identity.py': 'ba738892696025364c3a58664bdf3fbf46e3c7d1a72df7eca31bcc441e9a0c34',
    'benchmarks/balclutha/crossing_value.py': 'bafb3ac55a69046cbf3fafcdd02f63889a34a69b064917b8798315ad4c9a4ddf',
}


def write_truth(path: Path, rows: dict) -> Path:
    path.write_text(json.dumps({'stations': list(hv.STATIONS), 'rows': rows}))
    return path


def test_calibration_uses_aft_left_and_fore_right():
    layout = hv.sheet_layout()
    aft, fore = layout.sides
    assert (aft.name, aft.sign, aft.stations_outer_first) == ('aft', -1, (6, 7, 8, 9, 10, 11))
    assert (fore.name, fore.sign, fore.stations_outer_first) == ('fore', 1, (5, 4, 3, 2, 1))
    assert sorted(aft.stations_outer_first + fore.stations_outer_first) == list(hv.STATIONS)
    assert layout.centre_column == 3270.0 and layout.max_offset_px == 1550
    for side in layout.sides:
        offsets = [side.sign * (column - hv.CENTRE_COLUMN) for column in side.grid_columns]
        assert offsets == pytest.approx([300, 600, 900, 1200], abs=1.5)


def test_waterline_rows_follow_baseline_and_scale():
    layout = hv.sheet_layout()
    assert layout.waterlines_low_to_high() == list(reversed(hv.WATERLINES))
    assert [hv.waterline_height_ft(w) for w in hv.WATERLINES] == [3, 2, 1, 0, -1, -2]
    for label, row in layout.waterline_rows.items():
        assert isinstance(row, int)
        assert hv.BASE_ROW - row == hv.waterline_height_ft(label) * hv.PIXELS_PER_FT


@pytest.mark.parametrize('printed', ['4-8-6+', '-4- 8-6+', '  - 4 - 8 - 6 + '])
def test_parser_uses_magnitude_and_plus_sixteenth(printed):
    assert hv.printed_half_breadth(printed) == pytest.approx((4 + (8.75 + 1 / 16) / 12) * 0.3048)


@pytest.mark.parametrize('printed', ['ditto', '1-12-0', '1-0-8', '1-0-0/2-0-0', '--1-0-0', ''])
def test_parser_rejects_unresolved_values(printed):
    with pytest.raises(ValueError):
        hv.printed_half_breadth(printed)


def test_truth_loader_keeps_blanks_out_and_uses_printed_labels(tmp_path):
    rows = {w: [None] * 11 for w in hv.WATERLINES}
    rows['3-0-0'][0] = '2-0-6+'
    rows['-1-0-0'][10] = '0-3-0'
    truth = hv.load_truth(write_truth(tmp_path / 'truth.json', rows))
    assert set(truth) == {(1, '3-0-0'), (11, '-1-0-0')}
    assert truth[(11, '-1-0-0')] == pytest.approx(3 / 12 * 0.3048)


def test_truth_loader_rejects_wrong_shape(tmp_path):
    rows = {w: [None] * 11 for w in hv.WATERLINES}
    short = dict(rows, **{'0-0-0': [None] * 10})
    with pytest.raises(ValueError):
        hv.load_truth(write_truth(tmp_path / 'short.json', short))
    missing = {w: v for w, v in rows.items() if w != '-2-0-0'}
    with pytest.raises(ValueError):
        hv.load_truth(write_truth(tmp_path / 'missing.json', missing))
    (tmp_path / 'stations.json').write_text(json.dumps({'stations': list(range(1, 13)), 'rows': rows}))
    with pytest.raises(ValueError):
        hv.load_truth(tmp_path / 'stations.json')


def test_scorer_detects_neighbour_identity_errors():
    truth = {(s, w): 1 + s * 0.3 + i * 0.01 for s in (4, 5) for i, w in enumerate(hv.WATERLINES)}
    swapped = {(9 - s, w): v for (s, w), v in truth.items()}
    assert hv.score(truth, truth)['identity_errors'] == []
    assert hv.score(swapped, truth)['identity_errors'] == [4, 5]


def test_code_arm_runs_once_and_never_approves(tmp_path, monkeypatch):
    rows = {w: [None] * 11 for w in hv.WATERLINES}
    rows['1-0-0'][4] = '5-0-0'
    truth_path = write_truth(tmp_path / 'truth.json', rows)
    monkeypatch.setattr(hv.bpc, 'load_ink', lambda path: 'pixels')
    monkeypatch.setattr(hv.round8, 'measure', lambda pixels, layout: {})
    monkeypatch.setattr(hv.round8, 'measurement_summary', lambda readings: {})
    calls = []

    def run_code(readings, layout, truth, scorer):
        calls.append(layout)
        return scorer({(5, '1-0-0'): 5 * 0.3048}, truth)

    monkeypatch.setattr(hv.round8, 'run_code', run_code)
    summary = hv.run('code', Path('sheet.tif'), truth_path, tmp_path / 'code')
    assert len(calls) == 1 and calls[0] == hv.sheet_layout()
    assert summary['truth_cells'] == 1 and summary['passes_rule'] is True
    assert summary['engineering_approved'] is False
    assert json.loads((tmp_path / 'code' / 'summary.json').read_text())['arm'] == 'code'
    with pytest.raises(FileExistsError):
        hv.run('code', Path('sheet.tif'), truth_path, tmp_path / 'code')


def test_reader_matches_the_frozen_checkpoint():
    root = Path(__file__).resolve().parents[1]
    for name, digest in FROZEN.items():
        assert hashlib.sha256((root / name).read_bytes()).hexdigest() == digest
