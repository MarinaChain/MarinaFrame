"""Independent equation checks; no ship truth or fitted reference values."""
import math

import numpy as np
import pytest

from vessel_reconstruction import performance


@pytest.mark.parametrize("reynolds, expected", [(1e6, 0.0046875), (1e7, 0.003),
                                                 (1e8, 0.0020833333333333333)])
def test_ittc1957_equation(reynolds, expected):
    result = performance.ittc1957_friction(reynolds)
    assert result.value == pytest.approx(expected)
    assert "ITTC-1957" in result.method
    assert result.engineering_approved is False


@pytest.mark.parametrize("reynolds", [0, -1, 100, math.nan, math.inf])
def test_friction_rejects_invalid_or_singular_reynolds(reynolds):
    with pytest.raises(ValueError):
        performance.ittc1957_friction(reynolds)


def test_friction_marks_laminar_range():
    result = performance.ittc1957_friction(1e4)
    assert result.validity_warnings


def test_delivered_and_brake_power_are_distinct():
    result = performance.propulsion_power(
        effective_power_kw=5000, thrust_deduction=0.15, wake_fraction=0.20,
        open_water_efficiency=0.55, relative_rotative_efficiency=1.0,
        shaft_efficiency=0.98)
    eta_h = 0.85 / 0.80
    assert result.hull_efficiency == pytest.approx(eta_h)
    assert result.delivered_power_kw == pytest.approx(5000 / (eta_h * 0.55))
    assert result.brake_power_kw == pytest.approx(result.delivered_power_kw / 0.98)
    assert result.engineering_approved is False
    assert result.validity_warnings  # caller-supplied efficiencies, no regression claim


def test_fuel_uses_brake_power_and_explicit_sfoc():
    result = performance.fuel_per_day(brake_power_kw=1000, sfoc_g_per_kwh=180)
    assert result.value == pytest.approx(4.32)
    assert result.unit == "t/day"
    assert result.inputs == {"brake_power_kw": 1000, "sfoc_g_per_kwh": 180}


@pytest.mark.parametrize("field, value", [
    ("effective_power_kw", -1), ("effective_power_kw", math.nan),
    ("thrust_deduction", 1), ("thrust_deduction", -0.1),
    ("wake_fraction", 1), ("wake_fraction", -0.1),
    ("open_water_efficiency", 0), ("open_water_efficiency", 1.1),
    ("relative_rotative_efficiency", 0), ("shaft_efficiency", 1.1),
])
def test_power_rejects_nonphysical_inputs(field, value):
    inputs = dict(effective_power_kw=1000, thrust_deduction=0.15, wake_fraction=0.2,
                  open_water_efficiency=0.55, relative_rotative_efficiency=1.0,
                  shaft_efficiency=0.98)
    inputs[field] = value
    with pytest.raises(ValueError):
        performance.propulsion_power(**inputs)


@pytest.mark.parametrize("power, sfoc", [(-1, 180), (math.inf, 180), (1000, 0),
                                        (1000, math.nan)])
def test_fuel_rejects_invalid_inputs(power, sfoc):
    with pytest.raises(ValueError):
        performance.fuel_per_day(brake_power_kw=power, sfoc_g_per_kwh=sfoc)


def test_comparison_uses_measured_area_for_power_not_estimated_area():
    result = performance.compare_resistance(
        estimated_resistance_n=110, estimated_wetted_surface_m2=11,
        measured_ct=0.02, measured_reference_surface_m2=10,
        speed_ms=1, water_density_kg_m3=1000, scale="model",
        source="synthetic example, row 1")
    # Measured R=100 N, estimated CT=0.02: CT error=0%, power error=10%.
    assert result.ct_error_percent == pytest.approx(0)
    assert result.effective_power_error_percent == pytest.approx(10)
    assert result.measured_effective_power_kw == pytest.approx(0.1)
    assert result.source == "synthetic example, row 1"
    assert result.engineering_approved is False
    assert result.validity_warnings


@pytest.mark.parametrize("overrides", [{"measured_ct": 0}, {"speed_ms": 0},
    {"water_density_kg_m3": math.nan}, {"source": ""}, {"scale": "unknown"},
    {"estimated_resistance_n": -1}, {"measured_reference_surface_m2": 0}])
def test_comparison_rejects_invalid_reference_basis(overrides):
    inputs = dict(estimated_resistance_n=110, estimated_wetted_surface_m2=11,
                  measured_ct=0.02, measured_reference_surface_m2=10,
                  speed_ms=1, water_density_kg_m3=1000, scale="model", source="synthetic row 1")
    inputs.update(overrides)
    with pytest.raises(ValueError):
        performance.compare_resistance(**inputs)


def _box_mesh():
    vertices = np.array([(0, -10, 0), (100, -10, 0), (100, 10, 0), (0, 10, 0),
                         (0, -10, 10), (100, -10, 10), (100, 10, 10), (0, 10, 10)])
    faces = [(0, 2, 1), (0, 3, 2), (4, 5, 6), (4, 6, 7), (0, 1, 5), (0, 5, 4),
             (1, 2, 6), (1, 6, 5), (2, 3, 7), (2, 7, 6), (3, 0, 4), (3, 4, 7)]
    return vertices[np.array(faces)]


def test_mesh_particulars_reuse_hydrostatics_without_renaming_lwl_as_lpp():
    result = performance.hull_particulars_from_mesh(
        _box_mesh(), draft_m=6, lpp_m=110, aft_perpendicular_x_m=-5,
        forward_x_sign=1, scale="model")
    assert result.waterline_length_m == pytest.approx(100)
    assert result.lpp_m == 110
    assert result.volume_m3 == pytest.approx(12000)
    assert result.wetted_surface_m2 == pytest.approx(3440)
    assert result.cb_lpp == pytest.approx(12000 / (110 * 20 * 6))
    assert result.cm == pytest.approx(1)
    assert result.cp_lpp == pytest.approx(result.cb_lpp)
    assert result.cwp_lpp == pytest.approx(100 / 110)
    assert result.lcb_percent_lpp_forward_of_midships == pytest.approx(0)
    assert result.transom_area_m2 is None
    assert result.scale == "model"
    assert result.validity_warnings
    assert result.engineering_approved is False


def test_mesh_draft_is_above_keel_not_global_waterline_z():
    mesh = _box_mesh().astype(float)
    mesh[:, :, 2] += 5
    result = performance.hull_particulars_from_mesh(
        mesh, draft_m=11, lpp_m=100, aft_perpendicular_x_m=0,
        forward_x_sign=1, scale="model")
    assert result.draft_m == pytest.approx(6)
    assert result.cb_lpp == pytest.approx(1)
    assert result.cm == pytest.approx(1)


def test_lcb_convention_is_explicit_for_reversed_mesh_axis():
    result = performance.hull_particulars_from_mesh(
        _box_mesh(), draft_m=6, lpp_m=100, aft_perpendicular_x_m=110,
        forward_x_sign=-1, scale="ship")
    assert result.lcb_percent_lpp_forward_of_midships == pytest.approx(10)


@pytest.mark.parametrize("overrides", [{"forward_x_sign": 0}, {"lpp_m": 0},
                                         {"scale": "unknown"}, {"draft_m": -1},
                                         {"aft_perpendicular_x_m": math.nan}])
def test_mesh_particulars_require_stated_physical_basis(overrides):
    inputs = dict(draft_m=6, lpp_m=100, aft_perpendicular_x_m=0,
                  forward_x_sign=1, scale="model")
    inputs.update(overrides)
    with pytest.raises(ValueError):
        performance.hull_particulars_from_mesh(_box_mesh(), **inputs)
