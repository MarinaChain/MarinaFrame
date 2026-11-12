"""Public method checks only: no vessel measurements or held-out data.

Numerical references: MacKenzie & Forrester accepted manuscript (2007),
DOI 10.1016/j.oceaneng.2007.07.004, equations 12–13 and tables 1–2;
Helma (2019), SMP'19 MA2-4, section 3.2. The latter is chart-rounded,
not a high precision experiment or an independent validation of the series.
"""
import math

import pytest

from vessel_reconstruction import propeller


def evaluate(j=0.6, **changes):
    inputs = dict(advance_coefficient=j, pitch_diameter_ratio=1.0,
                  expanded_area_ratio=0.7, blade_count=4)
    inputs.update(changes)
    return propeller.wageningen_b_series(**inputs)


def test_exact_table_sizes_and_spot_checks():
    assert len(propeller.KT_TERMS) == 39
    assert len(propeller.KQ_TERMS) == 47
    # Rows are (coefficient, J exponent, P/D exponent, EAR exponent, Z exponent).
    assert propeller.KT_TERMS[0] == (0.008804960, 0, 0, 0, 0)
    assert (0.000056523, 3, 6, 1, 2) in propeller.KT_TERMS
    assert (-0.001465640, 0, 3, 2, 2) in propeller.KT_TERMS
    assert (-0.000465900, 0, 6, 2, 2) in propeller.KQ_TERMS
    assert (0.000086924, 3, 3, 2, 2) in propeller.KQ_TERMS


@pytest.mark.parametrize('j', [0.0, 0.3, 0.6, 1.0])
def test_published_three_blade_half_pitch_expanded_equations(j):
    # Manuscript equations 12–13: Z=3 (table 3, propeller A), EAR=.54,
    # nominal P/D=6/12=.5. Printed metric dimensions are rounded.
    # Coefficients printed to only 4–7 decimal places; not exact regression values.
    point = evaluate(j, pitch_diameter_ratio=0.5, expanded_area_ratio=0.54, blade_count=3)
    expected_kt = 0.1900 - 0.2517*j - 0.1904*j*j + 0.07085*j**3
    expected_kq = 0.01684 - 0.01777*j - 0.01291*j*j + 0.005945*j**3
    assert point.kt == pytest.approx(expected_kt, abs=6e-5)
    assert point.kq == pytest.approx(expected_kq, abs=9e-6)


def test_helma_2019_independent_chart_rounded_worked_example():
    # B5-90, J≈.69, P/D≈1.07: KQ≈.041, eta≈.62, sqrt(KT)/J≈.7.
    point = evaluate(0.69, pitch_diameter_ratio=1.07, expanded_area_ratio=0.9, blade_count=5)
    assert point.kq == pytest.approx(0.041, abs=0.001)
    assert point.open_water_efficiency == pytest.approx(0.62, abs=0.015)
    assert math.sqrt(point.kt) / 0.69 == pytest.approx(0.7, abs=0.015)


def expanded_reference(j, p, a, z):
    # Separate grouped equation transcribed from tables 1–2, not the production
    # term evaluator. This detects exponent/order errors but shares the publication.
    kt0 = (0.00880496 + .166351*p + .158114*p**2 + .415437*p**2*a
           + .0144043*z + .0143481*p*z - .0125894*a*z - .133698*p**3
           + .00638407*p**6 - .0507214*a**2 - .00841728*p**3*z
           - .0317791*p**3*a*z - .00410798*p**2*a**2*z - .000606848*z**2
           + .000690904*a*z**2 + .00421749*p**3*a*z**2 - .00146564*p**3*a**2*z**2)
    kt1 = (-.204554 - .481497*p*a + .0606826*p*z + .0109689*a*z
           + .010465*p**6*a**2 + .0168424*p**3*z + .018604*a**2*z
           - .0049819*z**2 - .00163652*p**2*z**2 - .000328787*p**6*z**2)
    kt2 = (-.147581*a - .0530054*z - .00132718*p**6 + .0854559*a**2
           - .00648272*p**6*a**2 + .0025983*z**2 + .000116502*p**6*z**2)
    kt3 = .168496*a - .0504475*a**2 - .00102296*p**3*z - .000560528*z**2 + .000056523*p**6*a*z**2
    kq0 = (.00379369 + .00344778*p**2 - .0408811*p*a + .188561*p**2*a
           + .00513696*p*z - .0269403*p**2*a*z + .0161886*p**3*a + .015896*a**2
           - .0502782*p*a**2 - .0397722*p**3*a**2 - .00350024*p**6*a**2
           - .000313912*p**6*z - .00142121*p**6*a*z + .0126803*p**2*a**2*z
           + .00334268*p**6*a**2*z + .00155334*p**2*a*z**2
           + .000302683*p**6*a*z**2 - .0001843*a**2*z**2
           - .000425399*p**3*a**2*z**2 - .0004659*p**6*a**2*z**2)
    kq1 = (-.032241*p - .108009*p*a - .00370871*z + .0209449*p*z
           + .00438388*p*a*z + .00318086*p**3*a + .0471729*a**2
           - .00383637*a**2*z - .00183491*p*z**2 + .000269551*a*z**2
           + .000055419*p**6*a**2*z**2)
    kq2 = (.00886523 - .0885381*p*a + .00474319*p*z - .00723408*a*z
           + .0417122*p**2*a**2 - .00318278*p**3*a**2*z + .00083265*a*z**2)
    kq3 = (.0558082*a + .0196283*a**2 - .030055*p*a**2 - .0106854*z
           + .00110903*p**3*z + .0035985*a*z + .000112451*p**2*z**2
           - .000029723*p**6*z**2 + .000086924*p**3*a**2*z**2)
    return kt0 + kt1*j + kt2*j*j + kt3*j**3, kq0 + kq1*j + kq2*j*j + kq3*j**3


@pytest.mark.parametrize('j,p,a,z', [(0, .8, .5, 3), (.47, 1.1, .85, 4), (.9, 1.3, 1.05, 5), (1.2, 1.4, .7, 7)])
def test_independent_grouped_polynomial(j, p, a, z):
    point = evaluate(j, pitch_diameter_ratio=p, expanded_area_ratio=a, blade_count=z)
    kt, kq = expanded_reference(j, p, a, z)
    assert point.kt == pytest.approx(kt, abs=3e-15)
    assert point.kq == pytest.approx(kq, abs=3e-15)


def test_eta_and_base_reynolds_metadata():
    point = evaluate()
    assert point.open_water_efficiency == pytest.approx(.6*point.kt/(2*math.pi*point.kq))
    assert point.reference_reynolds == 2e6
    assert 'B-series' in point.method and 'AU' not in point.method
    assert point.engineering_approved is False
    assert any('No Reynolds' in w for w in point.validity_warnings)
    changed = evaluate(reynolds=1e7)
    assert changed.kt == point.kt and changed.kq == point.kq
    assert any('requested Reynolds' in w for w in changed.validity_warnings)
    assert not changed.within_range


def test_extrapolation_and_nonphysical_eta_are_not_hidden():
    point = evaluate(1.5, pitch_diameter_ratio=1.6, expanded_area_ratio=1.2, blade_count=8)
    assert not point.within_range
    assert any('J' in w for w in point.validity_warnings)
    assert any('P/D' in w for w in point.validity_warnings)
    assert any('blade' in w for w in point.validity_warnings)
    # Positive geometry need not correspond to a tested blade-area combination.
    assert not evaluate(expanded_area_ratio=1.05, blade_count=2).within_range
    assert evaluate(1.4, pitch_diameter_ratio=.5).open_water_efficiency is None


@pytest.mark.parametrize('changes', [dict(advance_coefficient=float('nan')), dict(pitch_diameter_ratio=0),
    dict(expanded_area_ratio=-1), dict(blade_count=3.5), dict(blade_count=True), dict(reynolds=0)])
def test_rejects_invalid_scalar_inputs(changes):
    with pytest.raises(ValueError):
        evaluate(**changes)


def match_inputs(**changes):
    inputs = dict(resistance_n=100000, speed_ms=6, water_density_kg_m3=1025,
                  diameter_m=3, blade_count=4, pitch_diameter_ratio=1,
                  expanded_area_ratio=.7, thrust_deduction=.15, wake_fraction=.2,
                  relative_rotative_efficiency=1.04, shaft_efficiency=.97)
    inputs.update(changes)
    return inputs


def test_match_thrust_and_power_without_double_rotative_efficiency():
    result = propeller.match_propeller(**match_inputs(sfoc_g_per_kwh=190))
    assert result.status == 'matched'
    assert len(result.operating_points) == 1
    point = result.operating_points[0]
    assert point.n_rps > 0
    assert point.rpm == 60*point.n_rps
    assert point.advance_coefficient == pytest.approx(4.8/(point.n_rps*3))
    assert point.thrust_n == pytest.approx(100000/.85, rel=1e-10)
    assert abs(point.thrust_residual_n) < 1e-5
    q0 = 1025*point.n_rps**2 * 3**5 * point.kq
    assert point.open_water_torque_nm == pytest.approx(q0)
    assert point.delivered_power_kw == pytest.approx(2*math.pi*point.n_rps*q0/1.04/1000)
    assert point.brake_power_kw == pytest.approx(point.delivered_power_kw/.97)
    assert point.fuel_t_per_day == pytest.approx(point.brake_power_kw*190*24/1e6)
    assert result.engineering_approved is False


def test_matching_helma_example_uses_published_loading_not_own_kt():
    # Td=sqrt(T/(rho*Va²*D²))=.7, from Helma's section 3.2 example.
    result = propeller.match_propeller(**match_inputs(
        resistance_n=.7**2 * 1025 * 4.8**2 * 3**2 * .85,
        blade_count=5, expanded_area_ratio=.9, pitch_diameter_ratio=1.07))
    assert result.status == 'matched'
    point = result.operating_points[0]
    assert point.advance_coefficient == pytest.approx(.69, abs=.015)
    assert point.kq == pytest.approx(.041, abs=.001)
    assert point.open_water_efficiency == pytest.approx(.62, abs=.015)
    assert point.fuel_t_per_day is None


def test_no_root_in_explicit_engine_speed_interval():
    result = propeller.match_propeller(**match_inputs(n_rps_bounds=(1.5, 1.6)))
    assert result.status == 'no_root'
    assert result.operating_points == ()
    assert any('No physical' in w for w in result.validity_warnings)


def test_matching_refuses_outside_series_envelope():
    result = propeller.match_propeller(**match_inputs(blade_count=2, expanded_area_ratio=.9))
    assert result.status == 'outside_range'
    assert result.operating_points == ()


@pytest.mark.parametrize('changes', [dict(speed_ms=0), dict(resistance_n=0), dict(diameter_m=0),
    dict(water_density_kg_m3=float('nan')), dict(thrust_deduction=1), dict(wake_fraction=1),
    dict(relative_rotative_efficiency=0), dict(shaft_efficiency=1.1),
    dict(n_rps_bounds=(3, 2)), dict(n_rps_bounds=(0, 2)), dict(sfoc_g_per_kwh=-10)])
def test_matching_rejects_invalid_inputs(changes):
    with pytest.raises(ValueError):
        propeller.match_propeller(**match_inputs(**changes))


@pytest.mark.parametrize('coefficients,expected', [
    ((-.08, .66, -1.5, 1.), (.2, .5, .8)),
    ((-.075, .55, -1.3, 1.), (.3, .5)),  # double root at .5
    ((.25, -1., 1., 0.), (.5,)),
    ((0., -1., 1., 0.), (0., 1.)),
    ((-1., 1., 0., 0.), (1.,)),
    ((1., 0., 0., 0.), ()),
])
def test_cubic_bracketing_includes_all_roots_and_tangencies(coefficients, expected):
    roots = propeller._real_roots_in_interval(coefficients, 0., 1.)
    assert roots == pytest.approx(expected, abs=1e-10)


def test_matching_returns_multiple_physical_roots_without_selecting(monkeypatch):
    # A manufactured cubic, NOT B-series evidence: KT-C*J² has roots .2,.5,.8.
    # Ensure solver handling cannot silently choose an arbitrary operating root.
    loading = 100000/(.85*1025*4.8**2*3**2)
    synthetic_kt = ((-.08, 0, 0, 0, 0), (.66, 1, 0, 0, 0),
                    (loading-1.5, 2, 0, 0, 0), (1., 3, 0, 0, 0))
    monkeypatch.setattr(propeller, 'KT_TERMS', synthetic_kt)
    monkeypatch.setattr(propeller, 'KQ_TERMS', ((.3, 0, 0, 0, 0),))
    result = propeller.match_propeller(**match_inputs())
    assert result.status == 'multiple_roots'
    assert sorted(p.advance_coefficient for p in result.operating_points) == pytest.approx([.2, .5, .8])
    assert any('select' in w for w in result.validity_warnings)
