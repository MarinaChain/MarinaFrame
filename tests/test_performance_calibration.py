"""Synthetic calibration checks; no measured ship fixtures."""
from dataclasses import replace
import math

import pytest

from vessel_reconstruction.holtrop import HoltropHull, holtrop_resistance


def hull(cb=0.81):
    return HoltropHull(lwl_m=7, beam_m=1.2, draft_m=.45,
                      volume_m3=7*1.2*.45*cb, cm=.995, cwp=.9,
                      lcb_percent_lwl_forward=2, wetted_surface_m2=13)


def estimate(h, alpha):
    from vessel_reconstruction.performance_calibration import calibrated_resistance
    return calibrated_resistance(h, speed_ms=1.1, water_density_kg_m3=1000,
                                 kinematic_viscosity_m2_s=1e-6, alpha=alpha)


def test_only_excess_viscous_force_changes():
    h = hull()
    baseline = holtrop_resistance(h, speed_ms=1.1, water_density_kg_m3=1000,
                                 kinematic_viscosity_m2_s=1e-6, method='holtrop_1984',
                                 include_correlation_allowance=False)
    result = estimate(h, .5)
    delta = .5*(baseline.form_factor-1)*baseline.friction_resistance_n
    assert result.total_resistance_n == pytest.approx(baseline.total_resistance_n-delta)
    assert result.viscous_resistance_n == pytest.approx(baseline.viscous_resistance_n-delta)
    assert result.form_factor == pytest.approx(1+.5*(baseline.form_factor-1))
    assert result.effective_power_kw == pytest.approx(result.total_resistance_n*1.1/1000)
    for name in ('wave_resistance_n', 'bulb_resistance_n', 'appendage_resistance_n',
                 'transom_resistance_n', 'friction_resistance_n', 'correlation_resistance_n'):
        assert getattr(result, name) == getattr(baseline, name)
    assert result.engineering_approved is False
    assert result.method == 'holtrop_1984_full_form_v1'


@pytest.mark.parametrize('cb,weight', [(.7,0),(.75,0),(.775,.5),(.8,1),(.85,1)])
def test_fixed_full_form_weight(cb, weight):
    from vessel_reconstruction.performance_calibration import full_form_weight
    assert full_form_weight(cb) == pytest.approx(weight)


@pytest.mark.parametrize('alpha', [-.01,1.01,math.nan,math.inf])
def test_invalid_alpha_rejected(alpha):
    with pytest.raises(ValueError, match='alpha'):
        estimate(hull(), alpha)


def test_outside_envelope_warns_and_inside_retains_baseline_warnings():
    assert any('calibration envelope' in w for w in estimate(hull(.7), .5).range_warnings)
    assert estimate(hull(), .5).validity_warnings


def test_closed_form_fit_equal_ship_weight_and_bounds():
    from vessel_reconstruction.performance_calibration import CalibrationPoint, fit_alpha
    # Relative errors a-alpha*b: ship A wants 0, B wants 1; replication of A
    # cannot change equal-ship weighting. Both b=1.
    points = [CalibrationPoint('A',1,1,1)]*6 + [CalibrationPoint('B',2,1,1)]
    assert fit_alpha(points).alpha == pytest.approx(.5)
    assert fit_alpha([CalibrationPoint('A',3,1,1)]).alpha == 1
    assert fit_alpha([CalibrationPoint('A',.5,1,1)]).alpha == 0
    fit = fit_alpha([CalibrationPoint('A',1,0,1)])
    assert fit.alpha == 0
    assert not fit.identifiable


def test_leave_one_ship_out_uses_no_omitted_truth():
    from vessel_reconstruction.performance_calibration import CalibrationPoint, leave_one_ship_out
    points = [CalibrationPoint('A',1,1,1),CalibrationPoint('B',1.4,1,1),
              CalibrationPoint('C',1.8,1,1)]
    folds = leave_one_ship_out(points)
    assert folds['A'].alpha == pytest.approx(.6)
    assert folds['B'].alpha == pytest.approx(.4)
    assert folds['C'].alpha == pytest.approx(.2)
    changed = [replace(p, measured_ct=2) if p.ship=='A' else p for p in points]
    assert leave_one_ship_out(changed)['A'] == folds['A']


@pytest.mark.parametrize('values', [('A',1,1,0),('',1,1,1),('A',math.nan,1,1),
                                    ('A',1,-1,1)])
def test_invalid_fit_points(values):
    from vessel_reconstruction.performance_calibration import CalibrationPoint, fit_alpha
    with pytest.raises(ValueError):
        fit_alpha([CalibrationPoint(*values)])


def test_empty_fit_and_single_ship_loo_rejected():
    from vessel_reconstruction.performance_calibration import CalibrationPoint, fit_alpha, leave_one_ship_out
    with pytest.raises(ValueError):
        fit_alpha([])
    with pytest.raises(ValueError):
        leave_one_ship_out([CalibrationPoint('A',1,1,1)])
