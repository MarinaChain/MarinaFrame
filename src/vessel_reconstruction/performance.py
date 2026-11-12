"""Draft performance primitives, in SI units.

This module does not yet implement Holtrop-Mennen or Wageningen B-series.
Efficiencies supplied by a caller are assumptions, not regression predictions.
No ship performance or accuracy claim follows from these accounting equations.
"""
from dataclasses import dataclass
import math

import numpy as np

from .exports.hydrostatics import mesh_hydrostatics


@dataclass(frozen=True)
class ScalarEstimate:
    value: float
    unit: str
    method: str
    inputs: dict[str, float]
    validity_warnings: tuple[str, ...] = ()
    engineering_approved: bool = False


@dataclass(frozen=True)
class PropulsionPower:
    hull_efficiency: float
    delivered_power_kw: float
    brake_power_kw: float
    inputs: dict[str, float]
    method: str = "PE = PD * etaH * eta0 * etaR; PD = PB * etaS"
    validity_warnings: tuple[str, ...] = (
        "Caller-supplied efficiencies; no hull/propeller regression or matching calculation.",)
    engineering_approved: bool = False


@dataclass(frozen=True)
class HullParticulars:
    lpp_m: float
    waterline_length_m: float
    beam_m: float
    draft_m: float
    volume_m3: float
    cb_lpp: float
    cp_lpp: float
    cm: float
    cwp_lpp: float
    lcb_percent_lpp_forward_of_midships: float
    wetted_surface_m2: float
    scale: str
    aft_perpendicular_x_m: float
    forward_x_sign: int
    transom_area_m2: float | None = None
    method: str = "MarinaFrame mesh_hydrostatics; coefficients use explicit Lpp"
    validity_warnings: tuple[str, ...] = ()
    engineering_approved: bool = False


def _finite(name: str, value: float, *, minimum: float = 0, inclusive: bool = False) -> None:
    if not math.isfinite(value) or (value < minimum if inclusive else value <= minimum):
        bound = ">=" if inclusive else ">"
        raise ValueError(f"{name} must be finite and {bound} {minimum}")


def ittc1957_friction(reynolds: float) -> ScalarEstimate:
    """ITTC-1957 model-ship correlation line: Cf=0.075/(log10(Re)-2)^2.

    Reject Re <= 100 (the singularity and the nonphysical lower branch).
    Flag Re < 5e5: a turbulent friction line is not a laminar-flow model.
    """
    _finite("reynolds", reynolds, minimum=100)
    warnings = ("Outside turbulent-flow use: Re < 5e5.",) if reynolds < 5e5 else ()
    return ScalarEstimate(0.075 / (math.log10(reynolds) - 2) ** 2, "dimensionless",
                          "ITTC-1957 model-ship correlation line", {"reynolds": reynolds}, warnings)


def propulsion_power(*, effective_power_kw: float, thrust_deduction: float,
                     wake_fraction: float, open_water_efficiency: float,
                     relative_rotative_efficiency: float, shaft_efficiency: float) -> PropulsionPower:
    """Keep power at the propeller (delivered) separate from engine brake power.

    etaH=(1-t)/(1-w) can exceed one; etaR is also not capped at one.
    This is accounting with stated efficiencies, not an estimate of them.
    """
    inputs = dict(effective_power_kw=effective_power_kw, thrust_deduction=thrust_deduction,
                  wake_fraction=wake_fraction, open_water_efficiency=open_water_efficiency,
                  relative_rotative_efficiency=relative_rotative_efficiency,
                  shaft_efficiency=shaft_efficiency)
    _finite("effective_power_kw", effective_power_kw, inclusive=True)
    for name, value in (("thrust_deduction", thrust_deduction), ("wake_fraction", wake_fraction)):
        _finite(name, value, inclusive=True)
        if value >= 1:
            raise ValueError(f"{name} must be < 1")
    for name, value in (("open_water_efficiency", open_water_efficiency),
                        ("shaft_efficiency", shaft_efficiency)):
        _finite(name, value)
        if value > 1:
            raise ValueError(f"{name} must be <= 1")
    _finite("relative_rotative_efficiency", relative_rotative_efficiency)
    hull_efficiency = (1 - thrust_deduction) / (1 - wake_fraction)
    delivered = effective_power_kw / (hull_efficiency * open_water_efficiency
                                      * relative_rotative_efficiency)
    return PropulsionPower(hull_efficiency, delivered, delivered / shaft_efficiency, inputs)


def fuel_per_day(*, brake_power_kw: float, sfoc_g_per_kwh: float) -> ScalarEstimate:
    """Main-engine fuel only at constant power for 24 h; excludes auxiliaries.

    SFOC must refer to the stated engine operating point and brake power.
    There is no default SFOC or implied engine-load correction.
    """
    _finite("brake_power_kw", brake_power_kw, inclusive=True)
    _finite("sfoc_g_per_kwh", sfoc_g_per_kwh)
    return ScalarEstimate(brake_power_kw * sfoc_g_per_kwh * 24 / 1e6, "t/day",
                          "Brake kW * SFOC (g/kWh) * 24 h / 1e6 g/t",
                          dict(brake_power_kw=brake_power_kw, sfoc_g_per_kwh=sfoc_g_per_kwh),
                          ("Constant load and stated SFOC; excludes auxiliary consumption.",))


@dataclass(frozen=True)
class ResistanceComparison:
    estimated_ct: float
    measured_ct: float
    ct_error_percent: float
    estimated_effective_power_kw: float
    measured_effective_power_kw: float
    effective_power_error_percent: float
    inputs: dict[str, float]
    scale: str
    source: str
    method: str = "CT=R/(0.5*rho*U²*S); PE=R*U; error=100*(estimate/measured-1)"
    validity_warnings: tuple[str, ...] = (
        "Caller must match draft, appendages, water properties, speed and Reynolds number.",)
    engineering_approved: bool = False


def compare_resistance(*, estimated_resistance_n: float, estimated_wetted_surface_m2: float,
                       measured_ct: float, measured_reference_surface_m2: float,
                       speed_ms: float, water_density_kg_m3: float,
                       scale: str, source: str) -> ResistanceComparison:
    """Compare at one speed with separate predicted and measured area bases.

    Published CT uses the experiment's reference area. Using an estimated area
    to recover measured resistance would hide geometry errors in power scores.
    This function is not a data loader or an empirical resistance predictor.
    """
    inputs = dict(estimated_resistance_n=estimated_resistance_n,
                  estimated_wetted_surface_m2=estimated_wetted_surface_m2,
                  measured_ct=measured_ct,
                  measured_reference_surface_m2=measured_reference_surface_m2,
                  speed_ms=speed_ms, water_density_kg_m3=water_density_kg_m3)
    for name, value in inputs.items():
        _finite(name, value, inclusive=name == "estimated_resistance_n")
    if scale not in ("model", "ship") or not source.strip():
        raise ValueError("scale must be model or ship and source must identify the measurement")
    dynamic_pressure = 0.5 * water_density_kg_m3 * speed_ms ** 2
    estimated_ct = estimated_resistance_n / (dynamic_pressure * estimated_wetted_surface_m2)
    measured_resistance = measured_ct * dynamic_pressure * measured_reference_surface_m2
    return ResistanceComparison(
        estimated_ct, measured_ct, 100 * (estimated_ct / measured_ct - 1),
        estimated_resistance_n * speed_ms / 1000, measured_resistance * speed_ms / 1000,
        100 * (estimated_resistance_n / measured_resistance - 1), inputs, scale, source)


def hull_particulars_from_mesh(triangles: np.ndarray, *, draft_m: float, lpp_m: float,
                              aft_perpendicular_x_m: float, forward_x_sign: int,
                              scale: str) -> HullParticulars:
    """Reuse hydrostatics on a closed mesh in metres; explicitly name LCB basis.

    draft_m is the waterline z coordinate, as required by mesh_hydrostatics.
    The returned draft is measured above the mesh keel. LCB is positive forward
    of midships, in percent Lpp, not a fraction from an unspecified origin.
    """
    _finite("lpp_m", lpp_m)
    if not math.isfinite(draft_m) or not math.isfinite(aft_perpendicular_x_m):
        raise ValueError("draft_m and aft_perpendicular_x_m must be finite")
    if forward_x_sign not in (-1, 1) or scale not in ("model", "ship"):
        raise ValueError("forward_x_sign must be -1 or 1; scale must be model or ship")
    mesh = np.asarray(triangles, dtype=float)
    if mesh.ndim != 3 or mesh.shape[1:] != (3, 3) or not mesh.size or not np.isfinite(mesh).all():
        raise ValueError("triangles must be finite with shape (n, 3, 3)")
    if draft_m <= float(mesh[:, :, 2].min()) or draft_m > float(mesh[:, :, 2].max()):
        raise ValueError("waterline must be above the keel and within the mesh height")
    h = mesh_hydrostatics(mesh, draft_m, "explicit mesh waterline z (m)")
    for name, value in (("volume", h.volume_m3), ("draft", h.draft_m),
                        ("beam", h.largest_breadth_below_waterline_m),
                        ("largest section", h.largest_section_area_m2),
                        ("wetted surface", h.wetted_surface_m2)):
        if value is None:
            raise ValueError(f"mesh hydrostatics did not compute {name}")
        _finite(name, value)
    if h.lcb_m is None:
        raise ValueError("mesh hydrostatics did not compute LCB")
    area = h.largest_section_area_m2
    beam = h.largest_breadth_below_waterline_m
    lcb_from_aft = forward_x_sign * (h.lcb_m - aft_perpendicular_x_m)
    return HullParticulars(
        lpp_m=lpp_m, waterline_length_m=h.waterline_length_m, beam_m=beam,
        draft_m=h.draft_m, volume_m3=h.volume_m3,
        cb_lpp=h.volume_m3 / (lpp_m * beam * h.draft_m),
        cp_lpp=h.volume_m3 / (lpp_m * area), cm=area / (beam * h.draft_m),
        cwp_lpp=h.waterplane_area_m2 / (lpp_m * beam),
        lcb_percent_lpp_forward_of_midships=100 * (lcb_from_aft / lpp_m - 0.5),
        wetted_surface_m2=h.wetted_surface_m2, scale=scale,
        aft_perpendicular_x_m=aft_perpendicular_x_m, forward_x_sign=forward_x_sign,
        validity_warnings=(
            "Mesh closure, units (metres), scale and perpendicular positions are caller responsibilities.",
            "Largest sampled section substitutes for midship area; transom area is not computed.",
            *h.warnings))
