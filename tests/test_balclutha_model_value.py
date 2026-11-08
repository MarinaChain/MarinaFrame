"""Synthetic tests for the Balclutha sheet 7 model-value scorer (no drawing, no model call)."""
import json

import pytest
from benchmarks.balclutha import model_value as mv


def test_feet_inches_eighths_to_metres():
    assert mv.feet_inches_eighths('19-1-0') == pytest.approx((19 + 1 / 12) * 0.3048)
    assert mv.feet_inches_eighths('0-6-4') == pytest.approx((6.5 / 12) * 0.3048)
    assert mv.feet_inches_eighths(None) is None


def reply(stations):
    return '```json\n' + json.dumps({'source': 'ai_inferred', 'waterlines_ft': list(mv.WATERLINES_FT),
                                     'stations': stations}) + '\n```'


def test_parse_reading_and_reject_bad_values():
    reading = mv.parse_reading(reply({'3': [0.5, 1.0, None, 2.0, 2.5, 3.0, 3.5, 4.0]}))
    assert reading[(3, 4)] == 0.5 and (3, 12) not in reading and len(reading) == 7
    with pytest.raises(ValueError):
        mv.parse_reading(reply({'3': [0.5]}))
    with pytest.raises(ValueError):
        mv.parse_reading(reply({'3': [99, 1, 1, 1, 1, 1, 1, 1]}))


def test_score_counts_cells_errors_and_station_identity():
    truth = {(s, w): s + w / 100 for s in (4, 5, 6) for w in mv.WATERLINES_FT}
    reading = {(5, w): truth[(5, w)] + 0.1 for w in mv.WATERLINES_FT}
    # Station 6 read with the values of station 5: an identity error.
    reading.update({(6, w): truth[(5, w)] for w in mv.WATERLINES_FT})
    result = mv.score(reading, truth)
    assert result['cells_given'] == 16 and result['coverage'] == pytest.approx(16 / 24)
    assert result['identity_errors'] == [6]
    assert result['within_0_15'] == pytest.approx(0.5)
