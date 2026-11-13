"""Synthetic layout tests, not engine-maker performance claims."""
from dataclasses import replace

import pytest

from vessel_reconstruction.weights_efficiency.engine import EngineLayout, EngineRequest, select_engine


def layout():
    # Convex log(power)-log(speed) rectangle, synthetic only.
    return EngineLayout("synthetic", ((60, 5000), (100, 5000), (100, 10000), (60, 10000)),
                        ((.5, 180), (.75, 170), (1., 175)), ("synthetic-table",),
                        sfoc_rating_kw=6000*1.15/.9, sfoc_rating_rpm=80)


def test_layout_margins_and_sfoc_interpolation():
    request = EngineRequest(6000, 80, .15, .10, ("synthetic-power",))
    result = select_engine(request, (layout(),))
    assert len(result) == 1
    quantities = result[0].quantities
    assert quantities["smcr_kw"].value == pytest.approx(6000 * 1.15 / .9)
    assert quantities["operating_sfoc"].value == pytest.approx(173)
    assert quantities["sea_power_kw"].value == pytest.approx(6900)
    assert result[0].to_record_fragment()["engineering_approved"] is False


def test_out_of_layout_and_out_of_sfoc_range_are_not_extrapolated():
    assert select_engine(EngineRequest(12000, 80, .15, .1, ("s",)), (layout(),)) == ()
    assert select_engine(EngineRequest(6000, 120, .15, .1, ("s",)), (layout(),)) == ()
    narrow = replace(layout(), sfoc_by_load=((.5, 180), (.75, 170)))
    assert select_engine(EngineRequest(6000, 80, .15, .1, ("s",)), (narrow,)) == ()


def test_sfoc_requires_matching_smcr_tuning():
    assert select_engine(EngineRequest(5000, 80, .15, .1, ("s",)), (layout(),)) == ()


def test_reject_invalid_margin_and_nonconvex_layout():
    with pytest.raises(ValueError):
        select_engine(EngineRequest(6000, 80, .15, 1, ("s",)), (layout(),))
    bad = replace(layout(), vertices=((60, 5000), (100, 10000), (100, 5000), (60, 10000)))
    with pytest.raises(ValueError):
        select_engine(EngineRequest(6000, 80, .15, .1, ("s",)), (bad,))
