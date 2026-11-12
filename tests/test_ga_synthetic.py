"""Synthetic boxes, sheet isolation and offline measurements (no reader calls)."""
import hashlib
import json
import math

import pytest
from PIL import Image


def test_seeded_six_commercial_arrangements():
    from benchmarks.ga_synthetic.generate import arrangements

    cases = arrangements(17)
    assert cases == arrangements(17)
    assert cases != arrangements(18)
    assert [c['ship_type'] for c in cases] == ['bulk_carrier', 'tanker', 'general_cargo'] * 2
    assert len({c['case_id'] for c in cases}) == 6
    for case in cases:
        assert case['engineering_approved'] is False
        assert len(case['frame_table']) > 100
        kinds = {s['kind'] for s in case['spaces']}
        assert {'ballast_tank', 'engine_room', 'accommodation_deck'} <= kinds
        assert ({'cargo_tank'} if case['ship_type'] == 'tanker' else
                {'cargo_hold', 'cargo_hatch', 'cargo_crane'}) <= kinds
        assert any('DB' in s['label'] for s in case['spaces'])
        assert any('WING' in s['label'] for s in case['spaces'])
        assert any('PEAK' in s['label'] for s in case['spaces'])
        for space in case['spaces']:
            for axis in 'xyz':
                low, high = space['box_m'][axis]
                assert math.isfinite(low) and low < high


def test_generated_files_are_separate_and_repeatable(tmp_path):
    from benchmarks.ga_synthetic.generate import write_suite

    first, second = tmp_path / 'first', tmp_path / 'second'
    write_suite(first, seed=17, count=1)
    write_suite(second, seed=17, count=1)
    assert sorted(p.name for p in first.iterdir()) == ['SHA256SUMS', 'images', 'truth']
    image = next((first / 'images').iterdir())
    assert image.suffix == '.png'
    with Image.open(image) as sheet:
        assert sheet.size == (3960, 2800)
        assert sheet.getextrema()[0][0] < 50
        for top, bottom in [(300, 900), (1100, 1700), (1900, 2500)]:
            assert sheet.crop((200, top, 3700, bottom)).getextrema()[0][0] < 50
    truth = json.loads(next((first / 'truth').iterdir()).read_text())
    assert truth['schema'] == 'marinaframe.ga_synthetic_truth.v1'
    assert truth['spaces'] and truth['frame_table']
    for path in first.rglob('*'):
        if path.is_file():
            assert path.read_bytes() == (second / path.relative_to(first)).read_bytes()
    for line in (first / 'SHA256SUMS').read_text().splitlines():
        digest, name = line.split('  ')
        assert hashlib.sha256((first / name).read_bytes()).hexdigest() == digest
    with pytest.raises(FileExistsError):
        write_suite(first, seed=17, count=1)


def test_projection_labels_separate_coincident_hold_and_db():
    from benchmarks.ga_synthetic.generate import arrangements
    from benchmarks.ga_synthetic.render import projected_spaces

    case = arrangements()[0]
    labels = projected_spaces(case, 'tank_top', 'y')
    hold = next(s for s in labels if s['label'] == 'NO.1 HOLD')
    db = next(s for s in labels if s['label'] == 'NO.1 DB W.B.')
    assert hold['label_offset_px'] != db['label_offset_px']
    upper = projected_spaces(case, 'upper_deck', 'y')
    assert any(s['label'] == 'DECKS 1-3 (SAME BREADTH)' for s in upper)
