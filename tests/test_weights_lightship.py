"""Explicit-coefficient weight tests; coefficients and CGs are synthetic."""
from dataclasses import replace
import pytest
from vessel_reconstruction.weights_efficiency.weights import WeightInput, estimate_weights


def inputs():
    return WeightInput(length_m=150, beam_m=25, depth_m=14, draft_m=9,
                       cb_at_80_depth=.8, narrow_house_lh_m2=200, wide_house_lh_m2=100,
                       steel_coefficient=.03, outfit_t_m2=.3, machinery_rest_coefficient=.72,
                       main_engine_mass_t=250,
                       mcr_kw=10000, displacement_t=40000,
                       component_cg_m=((75, 0, 7), (80, 0, 12), (20, 0, 5)),
                       component_relative_bands=(.2, .25, .3),
                       band_basis="Synthetic sensitivity assumptions, not confidence intervals",
                       sources=("synthetic",))


def test_weights_and_mass_weighted_cg_with_conservative_bands():
    result = estimate_weights(inputs())
    q = result.quantities
    en = 150*(25+9) + .8*150*(14-9) + .85*200 + .75*100
    steel = .03 * en**1.36 * (1+.5*(.8-.7))
    outfit = .3 * 150*25
    machinery = 250 + .72 * 10000**.70
    lightship = steel+outfit+machinery
    band = steel*.2+outfit*.25+machinery*.3
    assert q["steel_t"].value == pytest.approx(steel, rel=1e-9)
    assert q["lightship_t"].value == pytest.approx(lightship, rel=1e-9)
    assert q["deadweight_t"].value == pytest.approx(40000-lightship, rel=1e-9)
    assert q["lightship_x_m"].value == pytest.approx((steel*75+outfit*80+machinery*20)/lightship, rel=1e-9)
    assert q["lightship_t"].uncertainty["absolute_band"] == pytest.approx(band, rel=1e-9)
    assert q["deadweight_t"].uncertainty["reason"]  # displacement band not supplied
    assert q["lightship_x_m"].uncertainty["reason"]  # CG accuracy not supplied


@pytest.mark.parametrize("change", [{"draft_m": 15}, {"component_relative_bands": (.2,)},
                                     {"displacement_t": 1}, {"cb_at_80_depth": 1.1},
                                     {"band_basis": ""}, {"steel_coefficient": float("nan")}])
def test_reject_invalid_weight_input(change):
    with pytest.raises(ValueError):
        estimate_weights(replace(inputs(), **change))
