"""Round-12 checks without drawings, private truth, or model calls."""
import hashlib
import json
from pathlib import Path

import pytest

from benchmarks.bue_girl import holdout_value as hv


FROZEN = {
    'src/vessel_reconstruction/body_plan_reader.py': '327c9f141876dc1945383ebe35023b6e7baaacc34306c5eecf26ffb16ba94e11',
    'src/vessel_reconstruction/body_plan_crossings.py': 'c6553371691121cd934b0991f273f9ff3a41963d46fd4238034f818aaf6fcf97',
    'src/vessel_reconstruction/body_plan_identity.py': 'ba738892696025364c3a58664bdf3fbf46e3c7d1a72df7eca31bcc441e9a0c34',
    'benchmarks/balclutha/crossing_value.py': 'bafb3ac55a69046cbf3fafcdd02f63889a34a69b064917b8798315ad4c9a4ddf',
}


def test_calibration_uses_fore_left_and_whole_pixel_waterlines():
    layout = hv.sheet_layout()
    fore, aft = layout.sides
    assert (fore.sign, fore.stations_outer_first) == (-1, (6, 5, 4, 3, 2, 1))
    assert (aft.sign, aft.stations_outer_first) == (1, (7, 8, 9, 10, 11, 12))
    assert layout.centre_column == 3266.5 and layout.max_offset_px == 1650
    assert fore.grid_columns[-1] == 1693 and aft.grid_columns[-1] == 4638
    assert layout.waterlines_low_to_high() == list(hv.WATERLINES)
    for height, row in layout.waterline_rows.items():
        assert isinstance(row, int)
        feet = hv.printed_half_breadth(height) / 0.3048
        assert abs(hv.BASE_ROW - row - feet * hv.PIXELS_PER_FT) <= 2


@pytest.mark.parametrize('printed', ['1-0-4+', '-1- 0-4+', '  - 1 - 0 - 4 + '])
def test_parser_uses_magnitude_and_plus_sixteenth(printed):
    assert hv.printed_half_breadth(printed) == pytest.approx((1 + (0.5 + 1 / 16) / 12) * 0.3048)


@pytest.mark.parametrize('printed', ['ditto', '1-12-0', '1-0-8', '1-0-0/2-0-0', '--1-0-0'])
def test_parser_rejects_unresolved_values(printed):
    with pytest.raises(ValueError):
        hv.printed_half_breadth(printed)


def test_truth_loader_preserves_blanks_and_uses_height_keys(tmp_path):
    rows = {w: [None] * 12 for w in hv.WATERLINES}
    rows['2-6-0'][1] = '0-7-4+'
    rows['6-6-0'][0] = '-1-8-6'
    path = tmp_path / 'truth.json'
    path.write_text(json.dumps({'stations': list(hv.STATIONS), 'rows': rows}))
    truth = hv.load_truth(path)
    assert set(truth) == {(2, '2-6-0'), (1, '6-6-0')}
    assert truth[(2, '2-6-0')] == pytest.approx((7.5 + 1 / 16) / 12 * 0.3048)
    rows['2-6-0'].pop()
    path.write_text(json.dumps({'stations': list(hv.STATIONS), 'rows': rows}))
    with pytest.raises(ValueError):
        hv.load_truth(path)


def test_scorer_detects_neighbour_identity_errors():
    truth = {(s, w): 1 + s * 0.3 + i * 0.01 for s in (4, 5) for i, w in enumerate(hv.WATERLINES)}
    swapped = {(9 - s, w): v for (s, w), v in truth.items()}
    assert hv.score(truth, truth)['identity_errors'] == []
    assert hv.score(swapped, truth)['identity_errors'] == [4, 5]


def test_reader_matches_the_frozen_checkpoint():
    root = Path(__file__).resolve().parents[1]
    for name, digest in FROZEN.items():
        assert hashlib.sha256((root / name).read_bytes()).hexdigest() == digest
