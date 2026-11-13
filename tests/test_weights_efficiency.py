"""Synthetic arithmetic tests; not public-ship validation evidence."""
import json
from dataclasses import replace

import pytest

from vessel_reconstruction.weights_efficiency import (
    DesignIndexInput, OperationalInput, design_index, operational_cii,
)


def design_inputs():
    return DesignIndexInput(
        deadweight_t=50000, mcr_kw=10000, reference_speed_kn=15,
        main_sfoc_g_kwh=170, auxiliary_sfoc_g_kwh=200,
        main_fuel="HFO", auxiliary_fuel="MDO", sources=("synthetic-example",),
    )


def test_eedi_hand_calculation_and_record():
    result = design_index(design_inputs())
    # PME=7500; PAE=.025*10000+250=500. No correction factors.
    assert result.quantities["attained_index"].value == pytest.approx(
        (7500 * 170 * 3.114 + 500 * 200 * 3.206) / (50000 * 15), rel=1e-9
    )
    fragment = result.to_record_fragment()
    assert fragment["engineering_approved"] is False
    assert fragment["quantities"]["reference_speed_ms"]["value"] == pytest.approx(15 * 1852 / 3600)
    for value in fragment["quantities"].values():
        assert set(value) == {"value", "unit", "uncertainty", "method", "method_version", "sources", "status"}
        assert value["status"] == "review_required"
        assert value["uncertainty"]["reason"]
    json.dumps(fragment, allow_nan=False)


def test_limited_eexi_uses_83_percent_and_original_auxiliary_basis():
    result = design_index(replace(design_inputs(), index="EEXI", limited_mcr_kw=6000))
    assert result.quantities["main_power_kw"].value == 4980
    assert result.quantities["auxiliary_power_kw"].value == 500
    capped = design_index(replace(design_inputs(), index="EEXI", limited_mcr_kw=9500))
    assert capped.quantities["main_power_kw"].value == 7500


@pytest.mark.parametrize("change", [
    {"deadweight_t": 0}, {"reference_speed_kn": float("nan")},
    {"main_fuel": "LNG"}, {"index": "other"},
    {"limited_mcr_kw": 5000}, {"index": "EEXI", "limited_mcr_kw": 11000},
    {"sources": ()},
])
def test_reject_unsupported_design_inputs(change):
    with pytest.raises(ValueError):
        design_index(replace(design_inputs(), **change))


def test_cii_unadjusted_annual_mass_and_current_reduction():
    data = OperationalInput(50000, 60000, (("HFO", 1000), ("MDO", 50)), 2030, ("synthetic",))
    result = operational_cii(data)
    assert result.quantities["attained_cii"].value == pytest.approx((3114 + 160.3) * 1e6 / (50000 * 60000))
    assert result.quantities["required_cii"].value == pytest.approx(5247 * 50000 ** -.610 * .785)
    assert "MEPC.400(83)" in result.quantities["required_cii"].sources
    assert "unadjusted" in result.scope


@pytest.mark.parametrize("change", [{"year": 2031}, {"distance_nm": 0}, {"fuel_t": ()}, {"fuel_t": (("HFO", -1),)}])
def test_reject_invalid_cii(change):
    data = OperationalInput(50000, 60000, (("HFO", 1000),), 2026, ("synthetic",))
    with pytest.raises(ValueError):
        operational_cii(replace(data, **change))
