"""Resolution behaviour on generated drawings, without real sheets or truth data."""
from dataclasses import asdict
from hashlib import sha256
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from benchmarks.frozen_readers.v1 import body_plan_reader as frozen
from tests.test_body_plan_reader import synthetic_drawing, sheet_layout, side_layout
from tests.test_sheet_calibration import synthetic_sheet, FakeReading
from vessel_reconstruction import body_plan_crossings as crossings
from vessel_reconstruction import body_plan_intake as intake
from vessel_reconstruction import body_plan_reader as reader


def test_reference_matches_frozen_reader():
    ink = synthetic_drawing() < 128
    assert crossings.sheet_resolution_factor(ink) == 1.0
    assert asdict(reader.measure_side(ink, sheet_layout(), side_layout())) == asdict(
        frozen.measure_side(ink, sheet_layout(), side_layout()))


def test_calibration_fixture_matches_frozen_reader():
    from vessel_reconstruction import sheet_calibration

    ink = synthetic_sheet()
    cal = sheet_calibration.calibrate(ink, FakeReading(), dpi=100.0)
    layout = cal.layout()
    for side in layout.sides:
        assert asdict(reader.measure_side(ink, layout, side)) == asdict(
            frozen.measure_side(ink, layout, side))


def test_frozen_reader_hashes():
    root = Path(__file__).resolve().parents[1] / 'benchmarks/frozen_readers/v1'
    expected = {
        'body_plan_reader.py': '327c9f141876dc1945383ebe35023b6e7baaacc34306c5eecf26ffb16ba94e11',
        'body_plan_crossings.py': 'c6553371691121cd934b0991f273f9ff3a41963d46fd4238034f818aaf6fcf97',
        'body_plan_identity.py': 'ba738892696025364c3a58664bdf3fbf46e3c7d1a72df7eca31bcc441e9a0c34',
    }
    for name, digest in expected.items():
        assert sha256((root / name).read_bytes()).hexdigest() == digest


@pytest.mark.parametrize('factor', [0.5, 0.2])
def test_small_sheet_has_resolution_warning(factor):
    image = Image.fromarray((~synthetic_sheet() * 255).astype('uint8'))
    image = image.resize((int(image.width * factor), int(image.height * factor)), Image.Resampling.NEAREST)
    ink = np.asarray(image) < 128
    record, cal = intake.read_body_plan(ink, ScaledReading(factor), dpi=100 * factor)
    assert cal.flagged('low_resolution')
    assert 0 < record['calibration']['resolution_factor'] < 0.75
    _, report = intake.reader_anchors([], [], record)
    assert any('resolution' in warning.lower() for warning in report['warnings'])


class ScaledReading(FakeReading):
    def __init__(self, factor):
        super().__init__()
        self.factor = factor

    def locate(self, ink):
        result = super().locate(ink)
        result['body_plan_box_px'] = [round(x * self.factor) for x in result['body_plan_box_px']]
        return result

    def label_lines(self, ink, box, horizontals, verticals):
        from tests.test_sheet_calibration import BASE, CENTRE, PX_FT
        centre = min(verticals, key=lambda line: abs(line.position - CENTRE * self.factor)) if verticals else None
        heights = [(line, (BASE * self.factor - line.position) / (PX_FT * self.factor))
                   for line in horizontals if abs(line.position - BASE * self.factor) > 3 * self.factor]
        return {'horizontal_ft': heights, 'base_lines': [], 'vertical_ft': [], 'centreline': centre,
                'stations_left': [4, 5, 6], 'stations_right': [1, 2, 3]}
