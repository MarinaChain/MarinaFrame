"""Source-transcribed Holtrop resistance and propulsion-interaction regressions.

Sources (equations, not ship validation data):
* J. Holtrop and G. G. J. Mennen, 'An approximate power prediction method',
  International Shipbuilding Progress 29(335), 1982, pp. 166-170.
* J. Holtrop, 'A statistical re-analysis of resistance and propulsion data',
  International Shipbuilding Progress 31(363), 1984, pp. 272-276.

The supplied public scan contains these on pages 1-5 and 6-8 respectively.
All dimensions are SI. L is LWL, not Lpp. LCB is percent LWL, positive forward
of midships. Displacement is immersed volume, not mass. Water properties are
mandatory. These empirical estimates are not an engineering approval.

The 1984 option retains unchanged 1982 terms and replaces form factor, wave
resistance and single-screw wake/thrust regressions as stated in the 1984 paper.
It does not implement the separate propeller open-water/matching procedure,
full-scale wake extrapolation, or an independently specified aerodynamic force.
"""
from dataclasses import dataclass
import math
from typing import Literal


HoltropMethod = Literal["holtrop_mennen_1982", "holtrop_1984"]
_METHODS = ("holtrop_mennen_1982", "holtrop_1984")


@dataclass(frozen=True)
class HoltropHull:
    """Hull inputs; Cb and Cp are derived on the explicit LWL basis.

    Draft is mean moulded draft. Optional forward/aft drafts default to it.
    Bulb area is the transverse area at FP; bulb height is above the baseline.
    Transom area is immersed transverse area at zero speed, including a skeg.
    Appendage factor is the area-weighted (1+k2), not k2. Tunnel coefficient
    is CBTO in the 1982 paper (typically .003-.012), not an area coefficient.
    Cstern: -10 V-shaped, 0 normal, +10 U-shaped (1984 also -25 pram with gondola).
    No automatic conversion from the mesh API's Lpp-based coefficients is made.
    """
    lwl_m: float
    beam_m: float
    draft_m: float
    volume_m3: float
    cm: float
    cwp: float
    lcb_percent_lwl_forward: float
    bulb_area_m2: float = 0.0
    bulb_center_height_m: float = 0.0
    transom_area_m2: float = 0.0
    wetted_surface_m2: float | None = None
    appendage_area_m2: float = 0.0
    appendage_form_factor: float = 1.0
    stern_parameter: float = 0.0
    aft_draft_m: float | None = None
    forward_draft_m: float | None = None
    tunnel_diameter_m: float = 0.0
    tunnel_coefficient: float = 0.0
    single_screw_stern: Literal["conventional", "open_stern"] = "conventional"

    @property
    def cb_lwl(self) -> float:
        return self.volume_m3 / (self.lwl_m * self.beam_m * self.draft_m)

    @property
    def cp_lwl(self) -> float:
        return self.cb_lwl / self.cm


@dataclass(frozen=True)
class HoltropPropeller:
    """Explicit propeller geometry; no efficiency or engine defaults.

    Blade count is optional provenance: these interaction equations use area
    ratio and pitch ratio, not blade count. They do not predict KT, KQ or eta0.
    """
    diameter_m: float
    blade_area_ratio: float
    pitch_diameter_ratio: float
    propeller_count: int = 1
    blade_count: int | None = None


@dataclass(frozen=True)
class HoltropResistance:
    total_resistance_n: float
    effective_power_kw: float
    friction_resistance_n: float
    viscous_resistance_n: float
    appendage_resistance_n: float
    wave_resistance_n: float
    bulb_resistance_n: float
    transom_resistance_n: float
    correlation_resistance_n: float
    tunnel_resistance_n: float
    wetted_surface_m2: float
    form_factor: float
    friction_coefficient: float
    correlation_coefficient: float
    reynolds: float
    froude: float
    method: str
    validity_warnings: tuple[str, ...]
    range_warnings: tuple[str, ...] = ()
    engineering_approved: bool = False


@dataclass(frozen=True)
class HoltropInteraction:
    wake_fraction: float
    thrust_deduction: float
    relative_rotative_efficiency: float
    hull_efficiency: float
    method: str
    validity_warnings: tuple[str, ...]
    range_warnings: tuple[str, ...] = ()
    engineering_approved: bool = False


def _positive(name: str, value: float, *, zero: bool = False) -> None:
    if not math.isfinite(value) or (value < 0 if zero else value <= 0):
        raise ValueError(f"{name} must be finite and {'>= 0' if zero else '> 0'}")


def _power(base: float, exponent: float, name: str) -> float:
    """Fail with the regression domain, never silently use complex numbers."""
    _positive(name, base)
    try:
        result = base ** exponent
    except OverflowError as exc:
        raise ValueError(f"{name} exceeds numerical domain") from exc
    _positive(name, result)
    return result


def _exp(exponent: float, name: str) -> float:
    try:
        value = math.exp(exponent)
    except OverflowError as exc:
        raise ValueError(f"{name} exceeds numerical domain") from exc
    if not math.isfinite(value):
        raise ValueError(f"{name} exceeds numerical domain")
    return value


def _validate_hull(h: HoltropHull, method: str) -> None:
    if method not in _METHODS:
        raise ValueError(f"method must be one of {_METHODS}")
    for name in ("lwl_m", "beam_m", "draft_m", "volume_m3", "cm", "cwp",
                 "appendage_form_factor"):
        _positive(name, getattr(h, name))
    for name in ("bulb_area_m2", "bulb_center_height_m", "transom_area_m2",
                 "appendage_area_m2", "tunnel_diameter_m", "tunnel_coefficient"):
        _positive(name, getattr(h, name), zero=True)
    for name in ("wetted_surface_m2", "aft_draft_m", "forward_draft_m"):
        value = getattr(h, name)
        if value is not None:
            _positive(name, value)
    if not 0 < h.cm <= 1 or not 0 < h.cwp < 1:
        raise ValueError("cm must be in (0, 1]; cwp must be in (0, 1)")
    if not 0 < h.cb_lwl < 1 or not 0.25 < h.cp_lwl < 1:
        raise ValueError("LWL coefficients require 0 < Cb < 1 and .25 < Cp < 1")
    if not math.isfinite(h.lcb_percent_lwl_forward) or not -50 < h.lcb_percent_lwl_forward < 50:
        raise ValueError("LCB must be percent LWL forward of midships, in (-50, 50)")
    if not math.isfinite(h.stern_parameter):
        raise ValueError("stern_parameter must be finite")
    if h.single_screw_stern not in ("conventional", "open_stern"):
        raise ValueError("unknown single_screw_stern")
    if h.tunnel_diameter_m > 0 and h.tunnel_coefficient <= 0:
        raise ValueError("tunnel coefficient must be explicit and positive for a tunnel")
    if h.bulb_area_m2:
        tf = h.forward_draft_m if h.forward_draft_m is not None else h.draft_m
        if method == "holtrop_1984" and h.bulb_center_height_m > 0.6 * tf:
            raise ValueError("1984 bulb centre height exceeds source limit .6 Tf")
        _positive("bulb pressure-parameter denominator Tf - 1.5 hb",
                  tf - 1.5 * h.bulb_center_height_m)
        _positive("bulb immersion Tf - hb - .25 sqrt(Ab)",
                  tf - h.bulb_center_height_m - 0.25 * math.sqrt(h.bulb_area_m2))


def _run_length(h: HoltropHull) -> float:
    cp = h.cp_lwl
    value = h.lwl_m * (1 - cp + 0.06 * cp * h.lcb_percent_lwl_forward / (4 * cp - 1))
    _positive("length of run", value)
    return value


def _wetted_surface(h: HoltropHull) -> float:
    # 1982 p. 166, eq. (2); unchanged in the 1984 update.
    if h.wetted_surface_m2 is not None:
        return h.wetted_surface_m2
    b, t, cb = h.beam_m, h.draft_m, h.cb_lwl
    area = (h.lwl_m * (2 * t + b) * math.sqrt(h.cm)
            * (0.453 + 0.4425 * cb - 0.2862 * h.cm - 0.003467 * b / t + 0.3696 * h.cwp)
            + 2.38 * h.bulb_area_m2 / cb)
    _positive("regressed wetted surface", area)
    return area


def _form_factor(h: HoltropHull, method: str, run: float) -> float:
    l, b, t, cp = h.lwl_m, h.beam_m, h.draft_m, h.cp_lwl
    if method == "holtrop_1984":
        # 1984 p. 272; replaces the 1982 product including c13.
        c14 = 1 + 0.011 * h.stern_parameter
        # The printed paper defines c14 = 1 + .011 Cstern.
        return (0.93 + 0.487118 * c14 * (b / l) ** 1.06806 * (t / l) ** 0.46106
                * (l / run) ** 0.121563 * (l ** 3 / h.volume_m3) ** 0.36486
                * (1 - cp) ** -0.604247)
    c13 = 1 + 0.003 * h.stern_parameter
    ratio = t / l
    if ratio > 0.05:
        c12 = ratio ** 0.2228446
    elif ratio > 0.02:
        c12 = 48.20 * (ratio - 0.02) ** 2.078 + 0.479948
    else:
        c12 = 0.479948
    return c13 * (0.93 + c12 * (b / run) ** 0.92497
                  * _power(0.95 - cp, -0.521448, "1982 .95 - Cp")
                  * _power(1 - cp + 0.0225 * h.lcb_percent_lwl_forward,
                           0.6906, "1982 form-factor Cp/LCB base"))


def _wave(h: HoltropHull, fn: float, rho: float, g: float, run: float,
          method: str) -> float:
    # 1982 pp. 167-168 eq. (5), with 1984 pp. 272-273 replacements.
    if fn == 0:
        return 0.0
    l, b, t, cp, volume = h.lwl_m, h.beam_m, h.draft_m, h.cp_lwl, h.volume_m3
    tf = h.forward_draft_m if h.forward_draft_m is not None else t
    c3 = (0.56 * h.bulb_area_m2 ** 1.5
          / (b * t * (0.31 * math.sqrt(h.bulb_area_m2) + tf - h.bulb_center_height_m))) if h.bulb_area_m2 else 0
    c2 = math.exp(-1.89 * math.sqrt(c3))
    c5 = 1 - 0.8 * h.transom_area_m2 / (b * t * h.cm)
    _positive("wave transom factor c5", c5)
    slenderness = l ** 3 / volume
    if slenderness < 512:
        c15 = -1.69385
    elif slenderness > 1727:
        c15 = 0.0
    else:
        c15 = -1.69385 + (l / volume ** (1 / 3) - 8) / 2.36
    lam = 1.446 * cp - (0.03 * l / b if l / b < 12 else 0.36)

    def oscillation(froude: float) -> float:
        if method == "holtrop_1984":
            return c15 * 0.4 * math.exp(-0.034 * froude ** -3.29)
        return c15 * cp ** 2 * math.exp(-0.1 * froude ** -2)

    def low_speed(froude: float) -> float:
        breadth_ratio = b / l
        if breadth_ratio < 0.11:
            c7 = 0.229577 * breadth_ratio ** (1 / 3)
        elif breadth_ratio > 0.25:
            c7 = 0.5 - 0.0625 * l / b
        else:
            c7 = breadth_ratio
        entrance_base = _power(1 - cp - 0.0225 * h.lcb_percent_lwl_forward,
                               0.6367, "entrance-angle Cp/LCB base")
        entrance = 1 + 89 * math.exp(-(l / b) ** 0.80856 * (1 - h.cwp) ** 0.30484
                                     * entrance_base * (run / b) ** 0.34574
                                     * (100 * volume / l ** 3) ** 0.16302)
        c1 = 2223105 * c7 ** 3.78613 * (t / b) ** 1.07961 * (90 - entrance) ** -1.37565
        c16 = (8.07981 * cp - 13.8673 * cp ** 2 + 6.984388 * cp ** 3
               if cp < 0.8 else 1.73014 - 0.7067 * cp)
        m1 = 0.0140407 * l / t - 1.75254 * volume ** (1 / 3) / l - 4.79323 * b / l - c16
        return c1 * c2 * c5 * volume * rho * g * _exp(
            m1 * froude ** -0.9 + oscillation(froude) * math.cos(lam * froude ** -2),
            "low-speed wave resistance")

    def high_speed(froude: float) -> float:
        c17 = 6919.3 * h.cm ** -1.3346 * (volume / l ** 3) ** 2.00977 * _power(l / b - 2, 1.40692, "1984 L/B - 2")
        m3 = -7.2035 * (b / l) ** 0.326869 * (t / b) ** 0.605375
        return c17 * c2 * c5 * volume * rho * g * _exp(
            m3 * froude ** -0.9 + oscillation(froude) * math.cos(lam * froude ** -2),
            "high-speed wave resistance")

    if method == "holtrop_mennen_1982" or fn <= 0.4:
        return low_speed(fn)
    if fn >= 0.55:
        return high_speed(fn)
    # 1984 equation (17): interpolate the forces, not coefficients.
    fraction = (fn - 0.4) / (0.55 - 0.4)
    return low_speed(0.4) * (1 - fraction) + high_speed(0.55) * fraction


def holtrop_resistance(hull: HoltropHull, *, speed_ms: float,
                       water_density_kg_m3: float, kinematic_viscosity_m2_s: float,
                       method: HoltropMethod = "holtrop_mennen_1982",
                       include_correlation_allowance: bool = True,
                       gravity_ms2: float = 9.81) -> HoltropResistance:
    """Return all resistance terms in N and PE in kW for calm, deep water.

    Set include_correlation_allowance=False for model force; CA is a ship/model
    correlation term, not model resistance. The source CA includes an empirical
    still-air contribution. No above-water area/drag or wind force is added.
    Zero speed returns the continuous zero-force limit; 0 < Re <= 100 is rejected.
    Invalid fractional-power domains raise ValueError, not a complex estimate.
    Extrapolation warnings do not establish a calibrated validity envelope.
    """
    h = hull
    _validate_hull(h, method)
    for name, value in (("water_density_kg_m3", water_density_kg_m3),
                        ("kinematic_viscosity_m2_s", kinematic_viscosity_m2_s),
                        ("gravity_ms2", gravity_ms2)):
        _positive(name, value)
    _positive("speed_ms", speed_ms, zero=True)
    l, b, t = h.lwl_m, h.beam_m, h.draft_m
    rho, g, speed = water_density_kg_m3, gravity_ms2, speed_ms
    run = _run_length(h)
    surface = _wetted_surface(h)
    form = _form_factor(h, method, run)
    _positive("form factor (1+k1)", form)
    reynolds = speed * l / kinematic_viscosity_m2_s
    fn = speed / math.sqrt(g * l)
    if speed and (not math.isfinite(reynolds) or reynolds <= 100):
        raise ValueError("ITTC friction requires finite Reynolds number > 100")
    cf = 0.075 / (math.log10(reynolds) - 2) ** 2 if speed else 0.0
    tf = h.forward_draft_m if h.forward_draft_m is not None else t
    c4 = min(tf / l, 0.04)
    c3 = (0.56 * h.bulb_area_m2 ** 1.5
          / (b * t * (0.31 * math.sqrt(h.bulb_area_m2) + tf - h.bulb_center_height_m))) if h.bulb_area_m2 else 0.0
    c2 = math.exp(-1.89 * math.sqrt(c3))
    ca = (0.006 * (l + 100) ** -0.16 - 0.00205
          + 0.003 * math.sqrt(l / 7.5) * h.cb_lwl ** 4 * c2 * (0.04 - c4)) if include_correlation_allowance else 0.0
    dynamic_pressure = 0.5 * rho * speed ** 2
    friction = dynamic_pressure * surface * cf
    viscous = friction * form
    appendage = dynamic_pressure * h.appendage_area_m2 * h.appendage_form_factor * cf
    wave = _wave(h, fn, rho, g, run, method)
    bulb = 0.0
    if h.bulb_area_m2 and speed:
        root_area = math.sqrt(h.bulb_area_m2)
        pb = 0.56 * root_area / (tf - 1.5 * h.bulb_center_height_m)
        fni = speed / math.sqrt(g * (tf - h.bulb_center_height_m - 0.25 * root_area)
                                + 0.15 * speed ** 2)
        bulb = (0.11 * math.exp(-3 * pb ** -2) * fni ** 3 * h.bulb_area_m2 ** 1.5
                * rho * g / (1 + fni ** 2))
    transom = 0.0
    if h.transom_area_m2:
        fnt = speed / math.sqrt(2 * g * h.transom_area_m2 / (b + b * h.cwp))
        c6 = 0.2 * (1 - 0.2 * fnt) if fnt < 5 else 0.0
        transom = dynamic_pressure * h.transom_area_m2 * c6
    correlation = dynamic_pressure * surface * ca
    tunnel = rho * speed ** 2 * h.tunnel_diameter_m ** 2 * h.tunnel_coefficient
    total = viscous + appendage + wave + bulb + transom + correlation + tunnel
    power = total * speed / 1000
    if not all(math.isfinite(v) for v in (total, power, wave, bulb, transom)):
        raise ValueError("resistance calculation exceeds finite numerical domain")
    warnings = [
        "Empirical regression for conventional displacement hulls; no universal calibrated hull-ratio envelope is supplied and an empty range_warnings is not validation.",
        "Calm deep water only; no shallow-water, roughness increment, fouling or weather correction.",
        "No separate aerodynamic force: source CA includes empirical still-air effects only when enabled.",
    ]
    if h.wetted_surface_m2 is None:
        warnings.append("Wetted surface is regressed, not a measured or mesh-integrated area.")
    if not include_correlation_allowance:
        warnings.append("Ship/model correlation allowance CA disabled explicitly.")
    range_warnings = []
    if 0 < reynolds < 5e5:
        range_warnings.append("Re < 5e5: turbulent ITTC-1957 friction may not apply.")
    if method == "holtrop_mennen_1982" and fn > 0.4:
        warnings.append("1982 wave regression extrapolated above Fn=0.4; 1984 revises this speed region.")
    if method == "holtrop_1984" and fn >= 0.55:
        warnings.append("1984 high-speed wave branch in use; source supplies no universal calibrated upper-speed envelope.")
    if h.cp_lwl > 0.8:
        warnings.append("Cp > 0.8: inspect applicability carefully; no universal calibrated hull-form envelope is supplied.")
    if h.tunnel_diameter_m and not 0.003 <= h.tunnel_coefficient <= 0.012:
        range_warnings.append("Tunnel CBTO is outside the source's approximate .003-.012 range.")
    if ca < 0 or total < 0:
        range_warnings.append("Negative correlation coefficient or total force: outside useful regression domain.")
    return HoltropResistance(total, power, friction, viscous, appendage, wave, bulb,
                             transom, correlation, tunnel, surface, form, cf, ca,
                             reynolds, fn, method, tuple(warnings + range_warnings),
                             tuple(range_warnings))


def holtrop_interaction(hull: HoltropHull, propeller: HoltropPropeller, *,
                        speed_ms: float, water_density_kg_m3: float,
                        kinematic_viscosity_m2_s: float,
                        method: HoltropMethod = "holtrop_mennen_1982",
                        include_correlation_allowance: bool = True,
                        gravity_ms2: float = 9.81) -> HoltropInteraction:
    """HM nominal single/twin-screw w, t and etaR; no open-water matching.

    CV=(1+k1)CF+CA as defined in 1982 p. 168. etaR and twin-screw equations
    remain the 1982 equations in the 1984 variant. Interaction at rest is undefined.
    The source's high-speed loaded-propeller wake extrapolation is not applied.
    """
    h, p = hull, propeller
    for name in ("diameter_m", "blade_area_ratio", "pitch_diameter_ratio"):
        _positive(name, getattr(p, name))
    if p.propeller_count not in (1, 2):
        raise ValueError("interaction requires one or two propellers")
    if p.blade_count is not None and (not isinstance(p.blade_count, int) or p.blade_count < 2):
        raise ValueError("blade_count must be an integer >= 2 when supplied")
    _positive("interaction speed_ms", speed_ms)
    r = holtrop_resistance(h, speed_ms=speed_ms, water_density_kg_m3=water_density_kg_m3,
                           kinematic_viscosity_m2_s=kinematic_viscosity_m2_s,
                           method=method, include_correlation_allowance=include_correlation_allowance,
                           gravity_ms2=gravity_ms2)
    l, b, t, cp, cb, d = h.lwl_m, h.beam_m, h.draft_m, h.cp_lwl, h.cb_lwl, p.diameter_m
    ta = h.aft_draft_m if h.aft_draft_m is not None else t
    cv = r.form_factor * r.friction_coefficient + r.correlation_coefficient
    _positive("viscous coefficient CV", cv)
    if p.propeller_count == 1 and h.single_screw_stern == "open_stern":
        # 1982 p.169 tentative open-shaft formula; retained by 1984 p.274.
        wake = 0.3 * cb + 10 * cv * cb - 0.1
        thrust = 0.10
        eta_r = 0.98
    elif p.propeller_count == 2:
        wake = 0.3095 * cb + 10 * cv * cb - 0.23 * d / math.sqrt(b * t)
        thrust = 0.325 * cb - 0.1885 * d / math.sqrt(b * t)
        eta_r = 0.9737 + 0.111 * (cp - 0.0225 * h.lcb_percent_lwl_forward) - 0.06325 * p.pitch_diameter_ratio
    else:
        _positive("single-screw propeller clearance TA - D", ta - d)
        cp1 = 1.45 * cp - 0.315 - 0.0225 * h.lcb_percent_lwl_forward
        _positive("single-screw 1 - Cp1", 1 - cp1)
        c8 = (b * r.wetted_surface_m2 / (l * d * ta) if b / ta < 5
              else r.wetted_surface_m2 * (7 * b / ta - 25) / (l * d * (b / ta - 3)))
        c9 = c8 if c8 < 28 else 32 - 16 / (c8 - 24)
        c11 = ta / d if ta / d < 2 else 0.0833333 * (ta / d) ** 3 + 1.33333
        c19 = (0.12997 / (0.95 - cb) - 0.11056 / (0.95 - cp)
               if cp < 0.7 else 0.18567 / (1.3571 - h.cm) - 0.71276 + 0.38648 * cp)
        c20 = 1 + 0.015 * h.stern_parameter
        if method == "holtrop_1984":
            wake = (c9 * c20 * cv * l / ta * (0.050776 + 0.93405 * c11 * cv / (1 - cp1))
                    + 0.27915 * c20 * math.sqrt(b / (l * (1 - cp1))) + c19 * c20)
            thrust = (0.25014 * (b / l) ** 0.28956 * (math.sqrt(b * t) / d) ** 0.2624
                      / _power(1 - cp + 0.0225 * h.lcb_percent_lwl_forward,
                               0.01762, "1984 thrust Cp/LCB base")
                      + 0.0015 * h.stern_parameter)
        else:
            _positive("1982 wake .95 - Cp", 0.95 - cp)
            _positive("1982 wake .95 - Cb", 0.95 - cb)
            wake = (c9 * cv * l / ta * (0.0661875 + 1.21756 * c11 * cv / (1 - cp1))
                    + 0.24558 * math.sqrt(b / (l * (1 - cp1)))
                    - 0.09726 / (0.95 - cp) + 0.11434 / (0.95 - cb)
                    + 0.75 * h.stern_parameter * cv + 0.002 * h.stern_parameter)
            c10 = b / l if l / b > 5.2 else 0.25 - 0.003328402 / (b / l - 0.134615385)
            thrust = (0.001979 * l / (b - b * cp1)
                      + 1.0585 * c10 - 0.00524
                      - 0.1418 * d ** 2 / (b * t) + 0.0015 * h.stern_parameter)
        eta_r = 0.9922 - 0.05908 * p.blade_area_ratio + 0.07424 * (cp - 0.0225 * h.lcb_percent_lwl_forward)
    if not all(math.isfinite(value) for value in (wake, thrust, eta_r)) or wake >= 1 or thrust >= 1 or eta_r <= 0:
        raise ValueError("interaction regression outside usable domain (w,t < 1; etaR > 0)")
    warnings = (*r.validity_warnings,
                "Nominal interaction regression only; no propeller loading/matching or scale-dependent wake extrapolation.")
    if wake < 0 or thrust < 0:
        warnings += ("Negative wake or thrust deduction: inspect regression applicability; not clipped.",)
    return HoltropInteraction(wake, thrust, eta_r, (1 - thrust) / (1 - wake), method,
                              warnings, r.range_warnings)
