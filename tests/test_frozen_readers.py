"""The archived reader must keep its own dependencies and match the original reader."""
from dataclasses import asdict

from benchmarks.frozen_readers.v1 import body_plan_crossings as frozen_crossings
from benchmarks.frozen_readers.v1 import body_plan_reader as frozen_reader
from vessel_reconstruction import body_plan_crossings as product_crossings
from vessel_reconstruction import body_plan_reader as product_reader


def test_frozen_reader_uses_frozen_crossings():
    assert frozen_reader.bpc is frozen_crossings
    assert frozen_reader.bpc is not product_crossings


def test_frozen_reader_matches_product_on_synthetic_benchmark():
    from tests.test_body_plan_reader import synthetic_drawing, sheet_layout, side_layout

    ink = synthetic_drawing() < 128
    product = product_reader.measure_side(ink, sheet_layout(), side_layout())
    frozen = frozen_reader.measure_side(ink, sheet_layout(), side_layout())
    assert asdict(product) == asdict(frozen)
