"""Synthetic tests only: analytic cross-checks are not published validation data."""
import json

import numpy as np
import pytest

from vessel_reconstruction.resistance_thin_ship import HullOffsets, wave_resistance


def wigley(nx=129, nz=65, scale=1.0):
    x = np.linspace(-0.5, 0.5, nx) * scale
    z = np.linspace(-0.0625, 0, nz) * scale
    y = 0.05 * scale * (1 - (2 * x[:, None] / scale) ** 2) * (1 - (z[None, :] / (0.0625 * scale)) ** 2)
    return HullOffsets(x, z, y, 0.0625 * scale, 0.15 * scale**2, ("synthetic Wigley L/B=10 L/T=16",))


def analytic_rw(fn, count=2048, lambda_max=24):
    # Independent closed-form x and z integrals of the parabolic half-breadth.
    nodes, weights = np.polynomial.legendre.leggauss(count)
    t = (nodes + 1) * np.arccosh(lambda_max) / 2
    lam = np.cosh(t)
    a = lam**2 / fn**2
    k = lam / fn**2
    q = a * 0.0625
    depth = (1 - 2 / q**2 + 2 * np.exp(-q) * (1 / q + 1 / q**2)) / a
    # d(1-4*x²)/dx=-8*x; both halves give the factor 16.
    longitudinal = -16 * (np.sin(k / 2) - k / 2 * np.cos(k / 2)) / k**2
    integral = np.sum(weights * lam**2 * (0.05 * depth * longitudinal)**2) * np.arccosh(lambda_max) / 2
    return 4 * 1000 * 9.81 / (np.pi * fn**2) * integral


@pytest.mark.parametrize("fn", [0.2, 0.3, 0.4, 0.5])
def test_matches_independent_analytic_wigley(fn):
    result = wave_resistance(wigley(), speed_m_s=fn * np.sqrt(9.81))
    assert result.rw.value == pytest.approx(analytic_rw(fn), rel=0.003)


def test_record_and_force_coefficient_basis():
    result = wave_resistance(wigley(), speed_m_s=1.0)
    assert result.rw.value == pytest.approx(result.cw.value * 0.5 * 1000 * 0.15)
    record = json.loads(json.dumps(result.to_record_fragment(), allow_nan=False))
    assert record["engineering_approved"] is False
    for name in ("cw", "rw"):
        assert set(record[name]) == {"value", "unit", "uncertainty", "method", "method_version", "sources", "status"}
        assert record[name]["status"] == "review_required"
        assert record[name]["uncertainty"]["band"] is None


def test_scale_and_translation_invariance():
    first = wave_resistance(wigley(), speed_m_s=1.0)
    large = wigley(scale=10)
    shifted = HullOffsets(large.x_m + 1000, large.z_m, large.half_breadths_m, large.draft_m,
                          large.wetted_surface_m2, large.sources)
    second = wave_resistance(shifted, speed_m_s=np.sqrt(10))
    assert second.cw.value == pytest.approx(first.cw.value, rel=1e-10)
    assert second.rw.value == pytest.approx(first.rw.value * 1000, rel=1e-10)


def test_zero_hull_has_zero_wave_resistance():
    hull = wigley()
    zero = HullOffsets(hull.x_m, hull.z_m, hull.half_breadths_m * 0,
                       hull.draft_m, hull.wetted_surface_m2, hull.sources)
    assert wave_resistance(zero, speed_m_s=1).rw.value == 0


@pytest.mark.parametrize("field,value", [
    ("x_m", [0, 0]), ("z_m", [-0.0625, -0.03]),
    ("draft_m", -1), ("wetted_surface_m2", float("nan")), ("sources", ()),
    ("half_breadths_m", [[-1, 0], [0, 0]]),
])
def test_rejects_invalid_hull(field, value):
    hull = wigley(nx=2, nz=2)
    args = dict(x_m=hull.x_m, z_m=hull.z_m, half_breadths_m=hull.half_breadths_m,
                draft_m=hull.draft_m, wetted_surface_m2=hull.wetted_surface_m2, sources=hull.sources)
    args[field] = value
    with pytest.raises(ValueError):
        wave_resistance(HullOffsets(**args), speed_m_s=1)


def test_rejects_immersed_open_ends():
    hull = wigley()
    y = hull.half_breadths_m.copy()
    y[0] = 0.01
    with pytest.raises(ValueError, match="closed"):
        wave_resistance(HullOffsets(hull.x_m, hull.z_m, y, hull.draft_m,
                                    hull.wetted_surface_m2, hull.sources), speed_m_s=1)


@pytest.mark.parametrize("kwargs", [
    {"speed_m_s": 0}, {"speed_m_s": float("nan")},
    {"speed_m_s": 1, "density_kg_m3": -1}, {"speed_m_s": 1, "gravity_m_s2": 0},
    {"speed_m_s": 1, "angle_count": 1}, {"speed_m_s": 1, "angle_count": 2.5},
    {"speed_m_s": 1, "lambda_max": 1},
])
def test_rejects_invalid_solver_inputs(kwargs):
    with pytest.raises(ValueError):
        wave_resistance(wigley(), **kwargs)
