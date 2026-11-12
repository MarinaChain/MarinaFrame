"""Draft model-scale full-form correction; protocol fixed before fitting.

Only excess viscous force is adjusted. This is not a change to Holtrop's
published equations, nor evidence of full-scale propulsion/fuel accuracy.
See docs/plans/2026-11-12-performance-calibration.md.
"""
from collections import Counter
from dataclasses import dataclass, replace
import math

from .holtrop import HoltropHull, HoltropResistance, holtrop_resistance

METHOD = "holtrop_1984_full_form_v1"
# Replaced by the single protocol-locked development fit before evaluator freeze.
FROZEN_ALPHA = 0.0


def full_form_weight(cb_lwl: float) -> float:
    """Fixed taper: no correction below .75, full correction above .80."""
    if not math.isfinite(cb_lwl):
        raise ValueError("Cb must be finite")
    return min(1.0, max(0.0, (cb_lwl - 0.75) / 0.05))


def calibrated_resistance(hull: HoltropHull, *, speed_ms: float,
                          water_density_kg_m3: float, kinematic_viscosity_m2_s: float,
                          alpha: float = FROZEN_ALPHA) -> HoltropResistance:
    """Model force only; preserve component accounting and baseline warnings."""
    if not math.isfinite(alpha) or not 0 <= alpha <= 1:
        raise ValueError("alpha must be finite and in [0, 1]")
    baseline = holtrop_resistance(
        hull, speed_ms=speed_ms, water_density_kg_m3=water_density_kg_m3,
        kinematic_viscosity_m2_s=kinematic_viscosity_m2_s, method="holtrop_1984",
        include_correlation_allowance=False)
    correction = alpha * full_form_weight(hull.cb_lwl) * (baseline.form_factor - 1)
    reduction = correction * baseline.friction_resistance_n
    total = baseline.total_resistance_n - reduction
    warnings = baseline.validity_warnings + (
        "Draft model-scale excess-form-factor calibration; no independent blind evidence yet.",)
    ranges = baseline.range_warnings
    if not (0.75 <= hull.cb_lwl <= 0.85 and 0.10 <= baseline.froude <= 0.20
            and 1e6 <= baseline.reynolds <= 2e7):
        ranges += ("Outside calibration envelope: Cb LWL .75-.85, Fn .10-.20, Re 1e6-2e7.",)
    return replace(baseline, total_resistance_n=total, effective_power_kw=total*speed_ms/1000,
                   viscous_resistance_n=baseline.viscous_resistance_n-reduction,
                   form_factor=baseline.form_factor-correction, method=METHOD,
                   validity_warnings=warnings, range_warnings=ranges)


@dataclass(frozen=True)
class CalibrationPoint:
    """CT(alpha) = baseline_ct - alpha*sensitivity_ct, on mesh area basis."""
    ship: str
    baseline_ct: float
    sensitivity_ct: float
    measured_ct: float


@dataclass(frozen=True)
class CalibrationFit:
    alpha: float
    unconstrained_alpha: float | None
    identifiable: bool
    bound_hit: bool
    ships: tuple[str, ...]


def fit_alpha(points: list[CalibrationPoint]) -> CalibrationFit:
    """Bounded scalar least squares, with equal total weight for each ship."""
    if not points:
        raise ValueError("fit requires nonempty points")
    for point in points:
        if not isinstance(point.ship, str) or not point.ship.strip():
            raise ValueError("ship must be nonempty text")
        values = (point.baseline_ct, point.sensitivity_ct, point.measured_ct)
        if (not all(math.isfinite(v) for v in values) or point.baseline_ct <= 0
                or point.measured_ct <= 0 or point.sensitivity_ct < 0):
            raise ValueError("fit CT values must be finite, positive; sensitivity must be >=0")
    counts = Counter(p.ship for p in points)
    numerator = denominator = 0.0
    for point in points:
        residual = point.baseline_ct / point.measured_ct - 1
        sensitivity = point.sensitivity_ct / point.measured_ct
        numerator += residual * sensitivity / counts[point.ship]
        denominator += sensitivity**2 / counts[point.ship]
    ships = tuple(sorted(counts))
    if denominator == 0:
        return CalibrationFit(0.0, None, False, False, ships)
    unconstrained = numerator / denominator
    alpha = min(1.0, max(0.0, unconstrained))
    return CalibrationFit(alpha, unconstrained, True, alpha in (0.0, 1.0), ships)


def leave_one_ship_out(points: list[CalibrationPoint]) -> dict[str, CalibrationFit]:
    """Fit each fold without any point of the omitted ship."""
    fit_alpha(points)  # Validate even when a fold would omit the invalid row.
    ships = sorted({p.ship for p in points})
    if len(ships) < 2:
        raise ValueError("leave-one-ship-out requires at least two ships")
    return {ship: fit_alpha([p for p in points if p.ship != ship]) for ship in ships}
