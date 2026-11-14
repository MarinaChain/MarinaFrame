"""Typed engineering diagnostics must preserve strict offset rejection."""
from dataclasses import replace

import numpy as np
import pytest

from vessel_reconstruction import resistance_thin_ship as thin


def hull():
    return thin.HullOffsets(np.array([0., 1., 2.]), np.array([-1., 0.]),
                            np.array([[0., 0.], [.1, .2], [0., 0.]]),
                            1., 2., ("synthetic",))


@pytest.mark.parametrize("value", [-1e-4, -1e-16])
def test_negative_breadth_has_typed_location_and_no_clipping(value):
    original = hull()
    original.half_breadths_m[1, 0] = value
    with pytest.raises(ValueError) as caught:
        thin.wave_resistance(original, speed_m_s=2)
    error = caught.value
    assert type(error).__name__ == "HullOffsetsError"
    assert error.code == "negative_half_breadth"
    assert "[1, 0]" in str(error)
    assert "m" in str(error)
    assert "regenerate" in str(error).lower()
    assert original.half_breadths_m[1, 0] == value


@pytest.mark.parametrize("change,code", [
    ({"half_breadths_m": np.zeros((2, 2))}, "breadth_shape"),
    ({"half_breadths_m": np.array([[0., 0.], [np.nan, .2], [0., 0.]])}, "nonfinite_half_breadth"),
    ({"x_m": np.array([0., 1., 1.])}, "invalid_x_grid"),
    ({"z_m": np.array([-1., -1.])}, "invalid_z_grid"),
    ({"z_m": np.array([-.5, 0.])}, "draft_span"),
    ({"half_breadths_m": np.array([[0., .1], [.1, .2], [0., 0.]])}, "open_ends"),
])
def test_distinct_geometric_rejection_codes(change, code):
    with pytest.raises(ValueError) as caught:
        thin.wave_resistance(replace(hull(), **change), speed_m_s=2)
    assert type(caught.value).__name__ == "HullOffsetsError"
    assert caught.value.code == code
