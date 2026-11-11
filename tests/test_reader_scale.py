"""Resolution behaviour on generated drawings, without real sheets or truth data (code-review item 8)."""
from dataclasses import asdict, replace
from hashlib import sha256
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from benchmarks.frozen_readers.v1 import body_plan_reader as frozen
from tests.test_body_plan_reader import (STATIONS_OUTER_FIRST, WATERLINE_ROWS, sheet_layout, side_layout,
                                         station_offset, synthetic_drawing)
from tests.test_sheet_calibration import synthetic_sheet, FakeReading
from vessel_reconstruction import body_plan_crossings as crossings
from vessel_reconstruction import body_plan_intake as intake
from vessel_reconstruction import body_plan_reader as reader


def reduced(ink: np.ndarray, scale: float) -> np.ndarray:
    """The ink of the same drawing scanned at `scale` times the pixel density (area average)."""
    paper = Image.fromarray(np.where(ink, 0, 255).astype(np.uint8))
    size = (round(ink.shape[1] * scale), round(ink.shape[0] * scale))
    return np.asarray(paper.resize(size, Image.Resampling.BOX)) < 128


def reduced_layout(scale: float):
    """The synthetic drawing's layout on the reduced pixel grid (pixel centres map as (x + 0.5) * scale - 0.5)."""
    def point(value):
        return (value + 0.5) * scale - 0.5

    layout = sheet_layout()
    side = replace(side_layout(), grid_columns=tuple(point(c) for c in side_layout().grid_columns))
    rows = {label: int(round(point(row))) for label, row in layout.waterline_rows.items()}
    return reader.SheetLayout(point(layout.centre_column), layout.pixels_per_metre * scale, rows,
                              int(round(layout.max_offset_px * scale)), (side,))


def table_errors(module, ink, layout) -> list[float]:
    """Absolute half-breadth errors (m) of the rank-numbered table against the drawn curves."""
    reading = module.measure_side(ink, layout, layout.sides[0])
    identities = module.identities_by_rank(reading.chains, STATIONS_OUTER_FIRST)
    table = module.table_from_identities(reading, identities, layout.pixels_per_metre, layout.centre_column)
    return [abs(table[(station, w)] - station_offset(rank, row) / 100.0)
            for station, rank in zip(STATIONS_OUTER_FIRST, (4, 3, 2, 1, 0))
            for w, row in WATERLINE_ROWS.items() if (station, w) in table]


def test_threshold_scale_keeps_the_checked_band_and_scales_outside_it():
    assert crossings.threshold_scale(None) == 1.0
    for stroke in (4.0, 4.7, 5.0, 6.6, 7.5):
        assert crossings.threshold_scale(stroke) == 1.0
    assert crossings.threshold_scale(2.0) == pytest.approx(0.5)
    assert crossings.threshold_scale(15.0) == pytest.approx(2.0)
    assert crossings.resolution_factor(2.5) == pytest.approx(0.5)


def test_stroke_width_needs_enough_crossings():
    few = [crossings.Crossing(0.0, 0.0, 0.0, 5.0, 5, 5, 0.0)] * (crossings.MIN_STROKE_CROSSINGS - 1)
    assert crossings.stroke_width_px(few) is None
    assert crossings.stroke_width_px(few + few) == 5.0


def test_reference_matches_frozen_reader():
    ink = synthetic_drawing() < 128
    product = reader.measure_side(ink, sheet_layout(), side_layout())
    assert crossings.threshold_scale(reader.side_stroke_width(product)) == 1.0
    assert repr(asdict(product)) == repr(asdict(frozen.measure_side(ink, sheet_layout(), side_layout())))


def test_calibration_fixture_matches_frozen_reader():
    from vessel_reconstruction import sheet_calibration

    ink = synthetic_sheet()
    cal = sheet_calibration.calibrate(ink, FakeReading(), dpi=100.0)
    assert cal.threshold_scale() == 1.0 and not cal.flagged('low_resolution')
    layout = cal.layout()
    for side in layout.sides:
        assert asdict(reader.measure_side(ink, layout, side)) == asdict(
            frozen.measure_side(ink, layout, side))


@pytest.mark.parametrize('scale', [0.5, 0.35])
def test_a_reduced_scan_is_read_with_scaled_thresholds(scale):
    ink = reduced(synthetic_drawing() < 128, scale)
    layout = reduced_layout(scale)
    pixel_m = 1 / layout.pixels_per_metre
    scaled = table_errors(reader, ink, layout)
    assert len(scaled) == len(STATIONS_OUTER_FIRST) * len(WATERLINE_ROWS)
    # Within 1.5 reduced pixels where curves are apart; 3 where two curves are drawn together.
    assert max(scaled) <= 3 * pixel_m
    assert np.median(scaled) <= 1.5 * pixel_m
    # The frozen thresholds class the thin curves as grid lines and lose most cells.
    assert len(table_errors(frozen, ink, layout)) <= 2


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
    measured = record['calibration']['resolution_factor']
    # At 0.2 no drawn line is left to measure: the resolution is unknown, and still flagged.
    assert measured is None if factor == 0.2 else 0 < measured < 0.75
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
