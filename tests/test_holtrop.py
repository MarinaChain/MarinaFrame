"""Method-paper checks only; no ship validation or holdout data.

The worked example is Holtrop & Mennen (1982), International Shipbuilding
Progress 29(335), pp. 166-170, table on p. 170 (scan page 5).
The input table's -2.02% Lpp is not the method LCB: its result table supplies
-.75% LWL. Stern is +10. Adopted water nu=1.18831e-6 m2/s at the stated 15 C;
this viscosity is explicit, not printed as an input in the example table.
"""
from dataclasses import replace
import importlib.util
import math

import pytest


def test_holtrop_module_exists():
    assert importlib.util.find_spec("vessel_reconstruction.holtrop") is not None


def example_hull():
    from vessel_reconstruction.holtrop import HoltropHull
    return HoltropHull(
        lwl_m=205.0, beam_m=32.0, draft_m=10.0, volume_m3=37500.0,
        cm=0.98, cwp=0.75, lcb_percent_lwl_forward=-0.75,
        bulb_area_m2=20.0, bulb_center_height_m=4.0, transom_area_m2=16.0,
        appendage_area_m2=50.0, appendage_form_factor=1.5, stern_parameter=10.0,
    )


def resistance(hull=None, **kwargs):
    from vessel_reconstruction.holtrop import holtrop_resistance
    return holtrop_resistance(
        hull or example_hull(), speed_ms=kwargs.pop("speed_ms", 25 * 1852 / 3600),
        water_density_kg_m3=1025.0, kinematic_viscosity_m2_s=1.18831e-6, **kwargs)


def interaction(hull=None, propeller=None, **kwargs):
    from vessel_reconstruction.holtrop import HoltropPropeller, holtrop_interaction
    return holtrop_interaction(
        hull or example_hull(), propeller or HoltropPropeller(
            diameter_m=8.0, blade_area_ratio=0.7393, pitch_diameter_ratio=1.0, blade_count=4),
        speed_ms=25 * 1852 / 3600, water_density_kg_m3=1025.0,
        kinematic_viscosity_m2_s=1.18831e-6, **kwargs)


def test_1982_original_resistance_example():
    result = resistance()
    # Printed values have only 4-6 significant figures; not fitted constants.
    assert result.wetted_surface_m2 == pytest.approx(7381.45, abs=0.1)
    assert result.form_factor == pytest.approx(1.156, abs=0.0005)
    assert result.friction_coefficient == pytest.approx(0.001390, abs=0.0000005)
    assert result.correlation_coefficient == pytest.approx(0.000352, abs=0.0000005)
    assert result.friction_resistance_n / 1000 == pytest.approx(869.63, abs=0.1)
    assert result.appendage_resistance_n / 1000 == pytest.approx(8.83, abs=0.01)
    assert result.wave_resistance_n / 1000 == pytest.approx(557.11, rel=0.001)
    assert result.bulb_resistance_n / 1000 == pytest.approx(0.049, abs=0.001)
    assert result.transom_resistance_n == 0
    assert result.correlation_resistance_n / 1000 == pytest.approx(221.98, abs=1.5)
    # The printed RA=221.98 kN is not exactly reproducible from its CA formula
    # (220.57 kN at rho=1025). Do not tune CA or water properties to this table.
    assert result.total_resistance_n / 1000 == pytest.approx(1793.26, rel=0.001)
    assert result.effective_power_kw == pytest.approx(23063.0, rel=0.001)
    assert result.method == "holtrop_mennen_1982"
    assert result.engineering_approved is False
    assert result.validity_warnings


def test_1982_original_interaction_example():
    result = interaction()
    assert result.wake_fraction == pytest.approx(0.2584, abs=0.0005)
    assert result.thrust_deduction == pytest.approx(0.1747, abs=0.0001)
    assert result.relative_rotative_efficiency == pytest.approx(0.9931, abs=0.0001)
    assert result.hull_efficiency == pytest.approx((1 - 0.1747) / (1 - 0.2584), abs=0.001)
    assert result.engineering_approved is False


def test_named_lwl_coefficients_and_explicit_surface():
    hull = example_hull()
    assert hull.cb_lwl == pytest.approx(37500 / (205 * 32 * 10))
    assert hull.cp_lwl == pytest.approx(hull.cb_lwl / 0.98)
    result = resistance(replace(hull, wetted_surface_m2=7000))
    assert result.wetted_surface_m2 == 7000
    assert result.friction_resistance_n == pytest.approx(
        0.5 * 1025.0 * (25 * 1852 / 3600) ** 2 * 7000 * result.friction_coefficient)


def test_component_sum_and_model_scale_switch():
    result = resistance()
    model = resistance(include_correlation_allowance=False)
    assert result.total_resistance_n == pytest.approx(sum((
        result.viscous_resistance_n, result.appendage_resistance_n,
        result.wave_resistance_n, result.bulb_resistance_n,
        result.transom_resistance_n, result.correlation_resistance_n,
        result.tunnel_resistance_n)))
    assert model.correlation_resistance_n == 0
    assert model.correlation_coefficient == 0
    assert result.total_resistance_n - model.total_resistance_n == pytest.approx(
        result.correlation_resistance_n)
    assert any("air" in warning.lower() for warning in model.validity_warnings)


def test_optional_terms_zero_and_zero_speed_limit():
    hull = replace(example_hull(), bulb_area_m2=0, transom_area_m2=0,
                   appendage_area_m2=0)
    result = resistance(hull)
    assert result.bulb_resistance_n == 0
    assert result.transom_resistance_n == 0
    assert result.appendage_resistance_n == 0
    assert result.tunnel_resistance_n == 0
    stopped = resistance(speed_ms=0)
    assert stopped.total_resistance_n == 0
    assert stopped.effective_power_kw == 0
    assert stopped.friction_coefficient == 0


@pytest.mark.parametrize("changes", [
    {"lwl_m": 0}, {"beam_m": -1}, {"draft_m": float("nan")},
    {"volume_m3": float("inf")}, {"cm": 0}, {"cwp": 1},
    {"volume_m3": 205 * 32 * 10}, {"bulb_area_m2": -1},
    {"wetted_surface_m2": 0}, {"lcb_percent_lwl_forward": -100},
    {"appendage_form_factor": -1}, {"forward_draft_m": -1},
])
def test_invalid_hull_input_rejected(changes):
    with pytest.raises(ValueError):
        resistance(replace(example_hull(), **changes))


def test_invalid_environment_and_unknown_method():
    from vessel_reconstruction.holtrop import holtrop_resistance
    for changes in ({"speed_ms": -1}, {"speed_ms": float("nan")},
                    {"water_density_kg_m3": 0}, {"kinematic_viscosity_m2_s": 0},
                    {"method": "holtrop"}, {"speed_ms": 1e-10}):
        args = dict(speed_ms=10, water_density_kg_m3=1025,
                    kinematic_viscosity_m2_s=1e-6)
        args.update(changes)
        with pytest.raises(ValueError):
            holtrop_resistance(example_hull(), **args)


def test_no_complex_bulb_or_propeller_geometry():
    from vessel_reconstruction.holtrop import HoltropPropeller
    with pytest.raises(ValueError, match="bulb"):
        resistance(replace(example_hull(), bulb_center_height_m=11))
    with pytest.raises(ValueError):
        interaction(propeller=HoltropPropeller(
            diameter_m=11, blade_area_ratio=0.55, pitch_diameter_ratio=1))


def test_tunnel_is_separate_and_explicit():
    hull = replace(example_hull(), tunnel_diameter_m=1.0, tunnel_coefficient=0.01)
    result = resistance(hull)
    assert result.tunnel_resistance_n == pytest.approx(
        1025.0 * (25 * 1852 / 3600) ** 2 * 1 ** 2 * 0.01)


def test_1984_updates_are_named_and_not_1982_aliases():
    old = resistance()
    new = resistance(method="holtrop_1984")
    assert new.method == "holtrop_1984"
    # 1984 p. 272: c14=1+.011*Cstern, revised form factor.
    hull = example_hull()
    cp = hull.cp_lwl
    run = hull.lwl_m * (1 - cp + 0.06 * cp * hull.lcb_percent_lwl_forward / (4 * cp - 1))
    expected = 0.93 + (0.487118 * (1 + 0.011 * hull.stern_parameter)
                      * (32 / 205) ** 1.06806 * (10 / 205) ** 0.46106
                      * (205 / run) ** 0.121563
                      * (205 ** 3 / 37500) ** 0.36486 * (1 - cp) ** -0.604247)
    assert new.form_factor == pytest.approx(expected)
    assert new.form_factor != old.form_factor
    assert new.wave_resistance_n != old.wave_resistance_n
    newer_interaction = interaction(method="holtrop_1984")
    # Revised t equation, not its 1982 counterpart.
    expected_t = (0.25014 * (32 / 205) ** 0.28956 * (math.sqrt(32 * 10) / 8) ** 0.2624
                  / (1 - cp + 0.0225 * hull.lcb_percent_lwl_forward) ** 0.01762
                  + 0.0015 * hull.stern_parameter)
    assert newer_interaction.thrust_deduction == pytest.approx(expected_t)


def test_1984_wave_interpolation_and_speed_warning():
    hull = example_hull()
    fn_to_speed = math.sqrt(9.81 * hull.lwl_m)
    low = resistance(speed_ms=0.4 * fn_to_speed, method="holtrop_1984")
    high = resistance(speed_ms=0.55 * fn_to_speed, method="holtrop_1984")
    middle = resistance(speed_ms=0.475 * fn_to_speed, method="holtrop_1984")
    assert middle.wave_resistance_n == pytest.approx(
        (low.wave_resistance_n + high.wave_resistance_n) / 2)
    outside = resistance(speed_ms=0.85 * fn_to_speed, method="holtrop_1984")
    assert any("high-speed" in warning for warning in outside.validity_warnings)
    assert math.isfinite(outside.total_resistance_n)


def test_twin_screw_interaction_uses_explicit_pitch_and_diameter():
    from vessel_reconstruction.holtrop import HoltropPropeller
    hull = example_hull()
    prop = HoltropPropeller(diameter_m=5, blade_area_ratio=0.55,
                           pitch_diameter_ratio=0.9, propeller_count=2)
    result = interaction(propeller=prop)
    cv = resistance().form_factor * resistance().friction_coefficient + resistance().correlation_coefficient
    assert result.wake_fraction == pytest.approx(
        0.3095 * hull.cb_lwl + 10 * cv * hull.cb_lwl - 0.23 * 5 / math.sqrt(32 * 10))
    assert result.thrust_deduction == pytest.approx(
        0.325 * hull.cb_lwl - 0.1885 * 5 / math.sqrt(32 * 10))
    assert result.relative_rotative_efficiency == pytest.approx(
        0.9737 + 0.111 * (hull.cp_lwl - 0.0225 * hull.lcb_percent_lwl_forward) - 0.06325 * 0.9)


@pytest.mark.parametrize("method", ["holtrop_mennen_1982", "holtrop_1984"])
def test_open_stern_uses_1982_equations_retained_in_1984(method):
    hull = replace(example_hull(), single_screw_stern="open_stern")
    result = interaction(hull, method=method)
    r = resistance(hull, method=method)
    cv = r.form_factor * r.friction_coefficient + r.correlation_coefficient
    assert result.wake_fraction == pytest.approx(0.3 * hull.cb_lwl + 10 * cv * hull.cb_lwl - 0.1)
    assert result.thrust_deduction == 0.10
    assert result.relative_rotative_efficiency == 0.98


def test_range_warnings_separate_from_caveats():
    result = resistance()
    assert result.validity_warnings
    assert result.range_warnings == ()
    high = resistance(replace(example_hull(), tunnel_diameter_m=1, tunnel_coefficient=.02))
    assert any("Tunnel" in warning for warning in high.range_warnings)


def test_1984_high_speed_equation_from_p272():
    h = example_hull()
    fn = 0.6
    r = resistance(speed_ms=fn * math.sqrt(9.81 * h.lwl_m), method="holtrop_1984")
    l, b, t, volume = h.lwl_m, h.beam_m, h.draft_m, h.volume_m3
    c3 = 0.56 * 20 ** 1.5 / (b * t * (0.31 * math.sqrt(20) + 10 - 4))
    c2 = math.exp(-1.89 * math.sqrt(c3))
    c5 = 1 - 0.8 * 16 / (b * t * h.cm)
    c17 = 6919.3 * h.cm ** -1.3346 * (volume / l ** 3) ** 2.00977 * (l / b - 2) ** 1.40692
    m3 = -7.2035 * (b / l) ** 0.326869 * (t / b) ** 0.605375
    m4 = -1.69385 * 0.4 * math.exp(-0.034 * fn ** -3.29)
    lam = 1.446 * h.cp_lwl - 0.03 * l / b
    expected = c17 * c2 * c5 * volume * 1025 * 9.81 * math.exp(
        m3 * fn ** -0.9 + m4 * math.cos(lam * fn ** -2))
    assert r.wave_resistance_n == pytest.approx(expected)


def test_numeric_domains_and_explicit_propeller_counts():
    from vessel_reconstruction.holtrop import HoltropPropeller
    for prop in (HoltropPropeller(8, .7, 1, propeller_count=3),
                 HoltropPropeller(8, 0, 1), HoltropPropeller(8, .7, -1)):
        with pytest.raises(ValueError):
            interaction(propeller=prop)
    with pytest.raises(ValueError):
        resistance(replace(example_hull(), tunnel_diameter_m=1))
    with pytest.raises(ValueError):
        resistance(replace(example_hull(), volume_m3=0.96 * .98 * 205 * 32 * 10),
                   method="holtrop_mennen_1982")
    # Fractional L/B power in high-speed branch must not become complex.
    with pytest.raises(ValueError):
        resistance(replace(example_hull(), beam_m=110), speed_ms=30,
                   method="holtrop_1984")
    with pytest.raises(ValueError):
        resistance(replace(example_hull(), bulb_center_height_m=6.2), method="holtrop_1984")


def test_1982_correlation_equation_uses_c2_bulb_factor():
    # 1982 p.168 explicitly includes c2 in the final CA addend.
    h = replace(example_hull(), forward_draft_m=5, bulb_area_m2=1, bulb_center_height_m=1)
    r = resistance(h)
    c3 = .56 / (32 * 10 * (.31 + 5 - 1))
    c2 = math.exp(-1.89 * math.sqrt(c3))
    expected = (.006 * (205 + 100) ** -.16 - .00205
                + .003 * math.sqrt(205 / 7.5) * h.cb_lwl ** 4 * c2 * (.04 - 5 / 205))
    assert r.correlation_coefficient == pytest.approx(expected)


def test_1982_paper_input_lcb_basis_is_not_silently_reinterpreted():
    # Input table says 2.02% aft of half Lpp; result table separately supplies
    # -.75% LWL. Endpoint offsets are not supplied; use printed LWL value.
    original = resistance()
    wrong_basis = resistance(replace(example_hull(), lcb_percent_lwl_forward=-2.02))
    assert original.total_resistance_n != wrong_basis.total_resistance_n
    assert example_hull().lcb_percent_lwl_forward == -.75


def test_1982_low_draft_and_1984_broad_hull_wake_branches():
    h = replace(example_hull(), draft_m=3, aft_draft_m=3, forward_draft_m=3,
                volume_m3=11000, bulb_area_m2=0, transom_area_m2=0)
    result = resistance(h)
    cp = h.cp_lwl
    run = h.lwl_m * (1 - cp + .06 * cp * h.lcb_percent_lwl_forward / (4 * cp - 1))
    expected_form = 1.03 * (.93 + .479948 * (32 / run) ** .92497
                           * (.95 - cp) ** -.521448
                           * (1 - cp + .0225 * -.75) ** .6906)
    assert result.form_factor == pytest.approx(expected_form)
    from vessel_reconstruction.holtrop import HoltropPropeller
    prop = HoltropPropeller(1, .7, 1)
    result = interaction(h, prop, method="holtrop_1984")
    assert math.isfinite(result.wake_fraction)


def test_stop_interaction_rejected():
    from vessel_reconstruction.holtrop import HoltropPropeller, holtrop_interaction
    with pytest.raises(ValueError):
        holtrop_interaction(example_hull(), HoltropPropeller(8, .7, 1), speed_ms=0,
                            water_density_kg_m3=1025, kinematic_viscosity_m2_s=1e-6)
