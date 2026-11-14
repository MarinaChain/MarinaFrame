"""Michell (1898) wave resistance for symmetric, closed-ended slender hulls.

SI inputs: x increases along the hull; z=0 at the waterline, z=-draft at
keel; y is nonnegative half-breadth. Offsets cover the complete immersed
hull. No transom, viscous, finite-depth, sinkage or trim correction is used.
This is not a total-resistance estimate or an engineering sign-off.
"""
from dataclasses import asdict, dataclass
from functools import lru_cache
import math

import numpy as np


MICHELL_SOURCE = "J. H. Michell (1898), Phil. Mag. 45:106–123, doi:10.1080/14786449808621111"


class HullOffsetsError(ValueError):
    """Offsets violate the Michell input contract; ``code`` is machine-readable."""

    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


@dataclass(frozen=True)
class HullOffsets:
    x_m: np.ndarray
    z_m: np.ndarray
    half_breadths_m: np.ndarray
    draft_m: float
    wetted_surface_m2: float
    sources: tuple[str, ...]


@dataclass(frozen=True)
class WaveQuantity:
    value: float
    unit: str
    uncertainty: dict
    method: str
    method_version: str
    sources: tuple[str, ...]
    status: str = "review_required"


@dataclass(frozen=True)
class WaveResistance:
    cw: WaveQuantity
    rw: WaveQuantity
    numerics: dict
    engineering_approved: bool = False

    def to_record_fragment(self) -> dict:
        result = asdict(self)
        for name in ("cw", "rw"):
            result[name]["sources"] = list(result[name]["sources"])
        return result


def _positive(name: str, value: float) -> None:
    if not math.isfinite(value) or value <= 0:
        raise ValueError(f"{name} must be finite and positive")


def _offsets(hull: HullOffsets) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    _positive("draft_m", hull.draft_m)
    _positive("wetted_surface_m2", hull.wetted_surface_m2)
    if not hull.sources or any(not s.strip() for s in hull.sources):
        raise ValueError("hull sources are required")
    x = np.asarray(hull.x_m, dtype=float)
    z = np.asarray(hull.z_m, dtype=float)
    y = np.asarray(hull.half_breadths_m, dtype=float)
    for name, grid in (("x", x), ("z", z)):
        if grid.ndim != 1 or grid.size < 2 or not np.isfinite(grid).all() or np.any(np.diff(grid) <= 0):
            raise HullOffsetsError(f"invalid_{name}_grid",
                                   f"{name} grid must be finite, strictly increasing, with at least two points; "
                                   "regenerate the offsets on an ordered grid")
    if y.shape != (x.size, z.size):
        raise HullOffsetsError("breadth_shape",
                               f"half-breadths have shape {y.shape}; expected ({x.size}, {z.size}) "
                               "with longitudinal stations first and depth levels second")
    if not np.isfinite(y).all():
        raise HullOffsetsError("nonfinite_half_breadth",
                               "half-breadths contain NaN or infinity; regenerate finite hull offsets")
    if np.any(y < 0):
        station, depth = np.unravel_index(np.argmin(y), y.shape)
        raise HullOffsetsError("negative_half_breadth",
                               f"negative half-breadth at [{station}, {depth}]: {y[station, depth]:.9g} m; "
                               "half-breadths must be nonnegative distances from the centreplane. "
                               "Check or regenerate the source geometry; values are not clipped")
    tolerance = 1e-10 * hull.draft_m
    if abs(z[0] + hull.draft_m) > tolerance or abs(z[-1]) > tolerance:
        raise HullOffsetsError("draft_span", "z must span -draft_m to waterline z=0; "
                               "check the draft and vertical coordinate origin")
    if np.any(y[[0, -1]] != 0):
        raise HullOffsetsError("open_ends", "closed ends required; immersed transom correction is not implemented. "
                               "Use a method that supports immersed open ends; do not force end breadths to zero")
    return x - x[0], z, y


@lru_cache(maxsize=16)
def _quadrature(count: int, lambda_max: float) -> tuple[np.ndarray, np.ndarray]:
    nodes, weights = np.polynomial.legendre.leggauss(count)
    upper = np.arccosh(lambda_max)
    # lambda=cosh(t) removes the integrable 1/sqrt(lambda²-1) endpoint.
    return np.cosh((nodes + 1) * upper / 2), weights * upper / 2


def _depth_weights(z: np.ndarray, decay: np.ndarray) -> np.ndarray:
    """Exact integral of each piecewise-linear depth basis times exp(decay*z)."""
    q = decay[:, None] * np.diff(z)[None, :]
    small = q < 0.01
    # The small-q series avoids cancellation in the linear-basis moments.
    lower = np.empty_like(q)
    upper = np.empty_like(q)
    s = q[small]
    lower[small] = 0.5 - s / 3 + s**2 / 8 - s**3 / 30 + s**4 / 144
    upper[small] = 0.5 - s / 6 + s**2 / 24 - s**3 / 120 + s**4 / 720
    v = q[~small]
    lower[~small] = (-np.expm1(-v) - v * np.exp(-v)) / v**2
    upper[~small] = (v + np.expm1(-v)) / v**2
    factor = np.exp(decay[:, None] * z[None, 1:]) * np.diff(z)[None, :]
    weights = np.zeros((decay.size, z.size))
    weights[:, :-1] += lower * factor
    weights[:, 1:] += upper * factor
    return weights


def wave_resistance(hull: HullOffsets, *, speed_m_s: float,
                    density_kg_m3: float = 1000.0, gravity_m_s2: float = 9.81,
                    angle_count: int = 512, lambda_max: float = 24.0) -> WaveResistance:
    """Evaluate Michell's integral on piecewise-bilinear half-breadths.

    Rw = 4*rho*g²/(pi*U²) integral_1^infinity
         lambda²/sqrt(lambda²-1) * |integral y_x exp(g*z*lambda²/U²)
         exp(i*g*x*lambda/U²) dx dz|² d(lambda).

    Depth and longitudinal panel integrals are analytic. The remaining
    integral uses angle_count Gauss-Legendre nodes in t=acosh(lambda),
    truncated at lambda_max (not a universal error guarantee). Compare
    doubled panel/angle counts AND larger lambda_max for each hull/speed.
    Cw uses caller-supplied total wetted area: Rw/(0.5*rho*U²*S).
    """
    for name, value in (("speed_m_s", speed_m_s), ("density_kg_m3", density_kg_m3),
                        ("gravity_m_s2", gravity_m_s2)):
        _positive(name, value)
    if isinstance(angle_count, bool) or not isinstance(angle_count, int) or angle_count < 16:
        raise ValueError("angle_count must be an integer >=16")
    if not math.isfinite(lambda_max) or lambda_max <= 1:
        raise ValueError("lambda_max must be finite and >1")
    x, z, y = _offsets(hull)
    lam, weights = _quadrature(angle_count, lambda_max)
    wavenumber = gravity_m_s2 * lam / speed_m_s**2
    depth_weights = _depth_weights(z, gravity_m_s2 * lam**2 / speed_m_s**2)
    # Integrate y in depth at each station, then its constant x slope per panel.
    depth_integrals = np.einsum("az,xz->ax", depth_weights, y, optimize=False)
    delta = np.diff(depth_integrals, axis=1)
    midpoint = (x[:-1] + x[1:]) / 2
    phase = np.exp(1j * wavenumber[:, None] * midpoint[None, :])
    phase *= np.sinc(wavenumber[:, None] * np.diff(x)[None, :] / (2 * np.pi))
    amplitude = np.sum(delta * phase, axis=1)
    integral = float(np.sum(weights * lam**2 * np.abs(amplitude)**2))
    rw = 4 * density_kg_m3 * gravity_m_s2**2 / (np.pi * speed_m_s**2) * integral
    if not math.isfinite(rw):
        raise ValueError("nonfinite Michell integral; check physical scale and resolution")
    cw = rw / (0.5 * density_kg_m3 * speed_m_s**2 * hull.wetted_surface_m2)
    uncertainty = {"band": None, "reason": "No empirical error band; panel, angle and tail convergence required."}
    sources = (*hull.sources, MICHELL_SOURCE)
    method = "Michell integral; bilinear offsets, exact panel integrals, Gauss-Legendre acosh(lambda)"
    def quantity(value: float, unit: str) -> WaveQuantity:
        return WaveQuantity(value, unit, dict(uncertainty), method, "1", sources)
    return WaveResistance(quantity(cw, "dimensionless"), quantity(rw, "N"),
                          {"x_panels": int(x.size - 1), "z_panels": int(z.size - 1),
                           "angle_count": angle_count, "lambda_max": lambda_max,
                           "speed_m_s": speed_m_s, "draft_m": hull.draft_m,
                           "wetted_surface_m2": hull.wetted_surface_m2,
                           "density_kg_m3": density_kg_m3, "gravity_m_s2": gravity_m_s2,
                           "corrections": "none", "tail_error_bound": None})
