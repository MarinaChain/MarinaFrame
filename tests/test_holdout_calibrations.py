"""Synthetic checks of the CAMA BEACH SKIFF No. 22 and Davis Boat calibrations (no sheet, no truth)."""
from __future__ import annotations

import pytest

from benchmarks.cama_beach_skiff_22 import holdout_value as cama
from benchmarks.davis_boat import holdout_value as davis
from benchmarks.deadrise_holdout import score as sc


@pytest.mark.parametrize('cal', [cama, davis])
def test_rows_run_low_to_high_and_heights_match_labels(cal):
    layout = cal.sheet_layout()
    assert sorted(side.name for side in layout.sides) == ['aft', 'fore']
    assert layout.waterlines_low_to_high() == list(cal.WATERLINES)
    for label in cal.WATERLINES:
        height = cal.height_ft(cal.WATERLINE_ROWS[label], cal.CENTRE_COLUMN)
        assert height == pytest.approx(sc.printed_feet(label), abs=1 / 96)  # within an eighth of an inch
        assert height == pytest.approx(cal.WATERLINE_HEIGHTS_FT[label])
    assert len(cal.TRUTH_SHA256) == 64 and len(cal.SHEET_SHA256) == 64
    assert cal.PIXELS_PER_FT == 600.0


@pytest.mark.parametrize('cal', [cama, davis])
def test_every_scored_station_is_named_once(cal):
    named = sum((side.stations_outer_first for side in cal.sheet_layout().sides), ())
    assert len(named) == len(set(named))
    assert set(cal.STATIONS) <= set(named)


def test_cama_sides_and_rows():
    aft, fore = cama.sheet_layout().sides
    assert (aft.name, aft.sign, aft.stations_outer_first) == ('aft', -1, (8, 9, 10))
    assert (fore.name, fore.sign, fore.stations_outer_first) == ('fore', 1, (7, 6, 5, 4, 3, 2, 1))
    assert cama.STATIONS == tuple(range(1, 10))  # station 10 has no printed offsets
    # The drawn waterlines W0 to W3 are measuring rows on their drawn image rows.
    assert {label: cama.WATERLINE_ROWS[label] for label in ('0-0-0', '0-3-0', '0-6-0', '0-9-0')} == {
        '0-0-0': 3235, '0-3-0': 3085, '0-6-0': 2935, '0-9-0': 2785}
    assert cama.WATERLINE_ROWS['-0-3-4'] == 3410 and cama.WATERLINE_ROWS['1-5-0'] == 2385
    for name in ('WL 0-9-0', 'WL 0-6-0', 'WL 0-3-0', 'WL 0-0-0'):  # printed row names (protocol)
        label = sc.match_waterline(sc.printed_feet(name[2:]), cama)
        assert label == name[3:]


def test_davis_sides_rows_and_half_stations():
    aft, fore = davis.sheet_layout().sides
    assert (aft.name, aft.sign) == ('aft', -1) and (fore.name, fore.sign) == ('fore', 1)
    assert aft.stations_outer_first[:3] == (5, 6, 7) and fore.stations_outer_first[:4] == (4, 3, 2, 1)
    placeholders = {davis.HALF_STATION_7_5, davis.HALF_STATION_0_5}
    assert placeholders.isdisjoint(davis.STATIONS) and all(p > 100 for p in placeholders)
    assert davis.STATIONS == tuple(range(1, 8))
    assert davis.WATERLINES == ('0-3-0', '0-6-0', '0-9-0', '1-0-0', '1-3-0', '1-6-0', '1-9-0', '2-0-0')
    for inches in range(3, 25, 3):  # printed "WATERLINE n", renamed "WL <ft-in-eighths>"
        assert sc.match_waterline(inches / 12, davis) is not None
    assert all(abs(abs(c - davis.CENTRE_COLUMN) % (davis.PIXELS_PER_FT / 2)) < 1e-9
               for c in davis.FORE_GRID_COLUMNS + davis.AFT_GRID_COLUMNS)
