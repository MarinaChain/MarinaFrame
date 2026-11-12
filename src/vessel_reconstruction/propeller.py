"""Wageningen B-series (not AU-series), base Reynolds number 2e6.

Version: Oosterveld & van Oossanen (1975), DOI 10.3233/ISP-1975-2225102.
The 39 KT and 47 KQ terms below use the *printed precision* in tables 1–2,
PDF pp. 26–27 of MacKenzie & Forrester's accepted manuscript (2007),
DOI 10.1016/j.oceaneng.2007.07.004:
https://strathprints.strath.ac.uk/5670/6/strathprints005670.pdf
Helma (2019), SMP'19, equations 1–6 and table 2 cross-check definitions,
Reynolds basis and blade/area combinations (not the coefficient list):
https://www.marinepropulsors.com/proceedings/2019/MA2-4.pdf

No Reynolds, cavitation, roughness, skew or scale correction is implemented.
A finite polynomial value is not proof of a physically valid operating point.
Geometry is checked against the per-blade EAR envelope in Helma table 2;
interior EAR values are interpolations. J in [0, 1.4] and P/D in [0.5, 1.4]
are conservative implementation screening bounds, NOT a guarantee of fit
accuracy or a claim that every combination was tested. Outside them the
raw evaluator flags extrapolation. Matching refuses such geometry and only
searches positive J up to 1.4. All results remain engineering-unapproved.
"""
from dataclasses import dataclass
import math


# Each row: coefficient, exponent of J, P/D, AE/A0, Z. Grouped by J power
# to match the printed tables, avoiding an implicit coefficient ordering.
KT_TERMS = (
    (.008804960, 0, 0, 0, 0), (.166351000, 0, 1, 0, 0),
    (.158114000, 0, 2, 0, 0), (.415437000, 0, 2, 1, 0),
    (.014404300, 0, 0, 0, 1), (.014348100, 0, 1, 0, 1),
    (-.012589400, 0, 0, 1, 1), (-.133698000, 0, 3, 0, 0),
    (.006384070, 0, 6, 0, 0), (-.050721400, 0, 0, 2, 0),
    (-.008417280, 0, 3, 0, 1), (-.031779100, 0, 3, 1, 1),
    (-.004107980, 0, 2, 2, 1), (-.000606848, 0, 0, 0, 2),
    (.000690904, 0, 0, 1, 2), (.004217490, 0, 3, 1, 2),
    (-.001465640, 0, 3, 2, 2),
    (-.204554000, 1, 0, 0, 0), (-.481497000, 1, 1, 1, 0),
    (.060682600, 1, 1, 0, 1), (.010968900, 1, 0, 1, 1),
    (.010465000, 1, 6, 2, 0), (.016842400, 1, 3, 0, 1),
    (.018604000, 1, 0, 2, 1), (-.004981900, 1, 0, 0, 2),
    (-.001636520, 1, 2, 0, 2), (-.000328787, 1, 6, 0, 2),
    (-.147581000, 2, 0, 1, 0), (-.053005400, 2, 0, 0, 1),
    (-.001327180, 2, 6, 0, 0), (.085455900, 2, 0, 2, 0),
    (-.006482720, 2, 6, 2, 0), (.002598300, 2, 0, 0, 2),
    (.000116502, 2, 6, 0, 2),
    (.168496000, 3, 0, 1, 0), (-.050447500, 3, 0, 2, 0),
    (-.001022960, 3, 3, 0, 1), (-.000560528, 3, 0, 0, 2),
    (.000056523, 3, 6, 1, 2),
)
KQ_TERMS = (
    (.003793690, 0, 0, 0, 0), (.003447780, 0, 2, 0, 0),
    (-.040881100, 0, 1, 1, 0), (.188561000, 0, 2, 1, 0),
    (.005136960, 0, 1, 0, 1), (-.026940300, 0, 2, 1, 1),
    (.016188600, 0, 3, 1, 0), (.015896000, 0, 0, 2, 0),
    (-.050278200, 0, 1, 2, 0), (-.039772200, 0, 3, 2, 0),
    (-.003500240, 0, 6, 2, 0), (-.000313912, 0, 6, 0, 1),
    (-.001421210, 0, 6, 1, 1), (.012680300, 0, 2, 2, 1),
    (.003342680, 0, 6, 2, 1), (.001553340, 0, 2, 1, 2),
    (.000302683, 0, 6, 1, 2), (-.000184300, 0, 0, 2, 2),
    (-.000425399, 0, 3, 2, 2), (-.000465900, 0, 6, 2, 2),
    (-.032241000, 1, 1, 0, 0), (-.108009000, 1, 1, 1, 0),
    (-.003708710, 1, 0, 0, 1), (.020944900, 1, 1, 0, 1),
    (.004383880, 1, 1, 1, 1), (.003180860, 1, 3, 1, 0),
    (.047172900, 1, 0, 2, 0), (-.003836370, 1, 0, 2, 1),
    (-.001834910, 1, 1, 0, 2), (.000269551, 1, 0, 1, 2),
    (.000055419, 1, 6, 2, 2),
    (.008865230, 2, 0, 0, 0), (-.088538100, 2, 1, 1, 0),
    (.004743190, 2, 1, 0, 1), (-.007234080, 2, 0, 1, 1),
    (.041712200, 2, 2, 2, 0), (-.003182780, 2, 3, 2, 1),
    (.000832650, 2, 0, 1, 2),
    (.055808200, 3, 0, 1, 0), (.019628300, 3, 0, 2, 0),
    (-.030055000, 3, 1, 2, 0), (-.010685400, 3, 0, 0, 1),
    (.001109030, 3, 3, 0, 1), (.003598500, 3, 0, 1, 1),
    (.000112451, 3, 2, 0, 2), (-.000029723, 3, 6, 0, 2),
    (.000086924, 3, 3, 2, 2),
)
REFERENCE_REYNOLDS = 2e6
METHOD = 'Wageningen B-series; Oosterveld & van Oossanen 1975; printed 2007 tables'
_BASE_WARNINGS = (
    'No Reynolds correction: coefficients are at reference Reynolds number 2e6.',
    'B-series only; no cavitation, roughness or full-scale correction; not engineering approved.',
    'Regression artefacts and multiple optima are documented by Helma (2019).',
)
_AREA_BOUNDS = {2: (.30, .38), 3: (.35, .80), 4: (.40, 1.00),
                5: (.45, 1.05), 6: (.50, .95), 7: (.55, .85)}


@dataclass(frozen=True)
class OpenWaterPoint:
    advance_coefficient: float
    kt: float
    kq: float
    open_water_efficiency: float | None
    within_range: bool
    validity_warnings: tuple[str, ...]
    reference_reynolds: float = REFERENCE_REYNOLDS
    method: str = METHOD
    engineering_approved: bool = False


def _positive(name: str, value: float) -> None:
    if not math.isfinite(value) or value <= 0:
        raise ValueError(f'{name} must be finite and > 0')


def _geometry_warnings(pitch: float, area: float, blades: int) -> list[str]:
    _positive('pitch_diameter_ratio', pitch)
    _positive('expanded_area_ratio', area)
    if isinstance(blades, bool) or not isinstance(blades, int) or blades < 1:
        raise ValueError('blade_count must be a positive integer')
    warnings = []
    if not .5 <= pitch <= 1.4:
        warnings.append('P/D outside implementation screening interval [0.5, 1.4].')
    bounds = _AREA_BOUNDS.get(blades)
    if bounds is None:
        warnings.append('blade_count outside published B-series range [2, 7].')
    elif not bounds[0] <= area <= bounds[1]:
        warnings.append(f'EAR outside published envelope {bounds} for {blades} blades.')
    if not .30 <= area <= 1.05:
        warnings.append('EAR outside overall published B-series envelope [0.30, 1.05].')
    return warnings


def _grouped_coefficients(terms: tuple, pitch: float, area: float, blades: int) -> tuple[float, ...]:
    return tuple(math.fsum(c * pitch**t * area**u * blades**v
                           for c, s, t, u, v in terms if s == power)
                 for power in range(4))


def _polynomial(coefficients: tuple[float, ...], x: float) -> float:
    return ((coefficients[3]*x + coefficients[2])*x + coefficients[1])*x + coefficients[0]


def wageningen_b_series(*, advance_coefficient: float, pitch_diameter_ratio: float,
                        expanded_area_ratio: float, blade_count: int,
                        reynolds: float = REFERENCE_REYNOLDS) -> OpenWaterPoint:
    """Evaluate the published raw polynomials; return warnings, never clip KT/KQ.

    ``reynolds`` records the requested operating basis only. A different value
    does not alter coefficients: the result remains at Re=2e6 and is warned.
    Efficiency is None unless KT>0, KQ>0 and 0<=eta0<=1.
    """
    if not math.isfinite(advance_coefficient):
        raise ValueError('advance_coefficient must be finite')
    _positive('reynolds', reynolds)
    range_warnings = _geometry_warnings(pitch_diameter_ratio, expanded_area_ratio, blade_count)
    if not 0 <= advance_coefficient <= 1.4:
        range_warnings.append('J outside forward implementation screening interval [0, 1.4].')
    warnings = [*_BASE_WARNINGS, *range_warnings]
    if reynolds != REFERENCE_REYNOLDS:
        warnings.append('The requested Reynolds number differs from 2e6; no correction was applied.')
    coefficients = [_grouped_coefficients(terms, pitch_diameter_ratio, expanded_area_ratio, blade_count)
                    for terms in (KT_TERMS, KQ_TERMS)]
    kt, kq = (_polynomial(c, advance_coefficient) for c in coefficients)
    eta = advance_coefficient * kt / (2*math.pi*kq) if kt > 0 and kq > 0 else None
    if eta is None or not 0 <= eta <= 1:
        eta = None
        warnings.append('Not a physical forward propulsive point: require KT>0, KQ>0, 0<=eta0<=1.')
    within_range = not range_warnings and reynolds == REFERENCE_REYNOLDS
    return OpenWaterPoint(advance_coefficient, kt, kq, eta, within_range, tuple(warnings))


@dataclass(frozen=True)
class MatchedOperatingPoint:
    n_rps: float
    rpm: float
    advance_coefficient: float
    kt: float
    kq: float
    open_water_efficiency: float
    thrust_n: float
    thrust_residual_n: float
    open_water_torque_nm: float
    delivered_power_kw: float
    brake_power_kw: float
    fuel_t_per_day: float | None


@dataclass(frozen=True)
class PropellerMatch:
    status: str
    operating_points: tuple[MatchedOperatingPoint, ...]
    validity_warnings: tuple[str, ...]
    method: str = METHOD + '; thrust-equilibrium matching; Re=2e6 only'
    engineering_approved: bool = False


def _real_roots_in_interval(coefficients: tuple[float, ...], lower: float,
                            upper: float) -> tuple[float, ...]:
    """All isolated roots of a cubic on a closed interval, including tangencies.

    Derivative roots partition the interval into monotonic pieces. Bisection
    therefore cannot skip a crossing as a fixed sampling grid can. At stationary
    points, a roundoff-sized polynomial value counts as a repeated root. A
    constant zero polynomial is indeterminate, not an arbitrary operating root.
    """
    scale = max(abs(c) for c in coefficients)
    if not scale:
        raise ValueError('Thrust equilibrium is indeterminate: polynomial is identically zero')
    c0, c1, c2, c3 = (c/scale for c in coefficients)
    normalized = (c0, c1, c2, c3)
    stationary = []
    a, b, c = 3*c3, 2*c2, c1
    if a == 0:
        if b != 0:
            stationary.append(-c/b)
    else:
        discriminant = b*b - 4*a*c
        if discriminant >= 0:
            # Stable quadratic formula; avoid cancellation for one of the roots.
            q = -.5 * (b + math.copysign(math.sqrt(discriminant), b))
            if q == 0:
                stationary.append(-b/(2*a))
            else:
                stationary.extend((q/a, c/q))
    cuts = sorted({lower, upper, *(x for x in stationary if lower < x < upper)})

    def near_zero(x: float, value: float) -> bool:
        magnitude = math.fsum(abs(coefficient)*abs(x)**i for i, coefficient in enumerate(normalized))
        return abs(value) <= 32*math.ulp(1.0)*magnitude

    values = [_polynomial(normalized, x) for x in cuts]
    roots = [x for x, value in zip(cuts, values) if near_zero(x, value)]
    for left, right, fleft, fright in zip(cuts, cuts[1:], values, values[1:]):
        if near_zero(left, fleft) or near_zero(right, fright) or fleft*fright >= 0:
            continue
        # 100 halvings exceed binary64 resolution on this bounded J interval.
        for _ in range(100):
            middle = left + (right-left)/2
            if middle == left or middle == right:
                break
            value = _polynomial(normalized, middle)
            if value == 0:
                left = right = middle
                break
            if (value > 0) == (fleft > 0):
                left, fleft = middle, value
            else:
                right = middle
        roots.append(left + (right-left)/2)
    return tuple(sorted(roots))


def match_propeller(*, resistance_n: float, speed_ms: float, water_density_kg_m3: float,
                    diameter_m: float, blade_count: int, pitch_diameter_ratio: float,
                    expanded_area_ratio: float, thrust_deduction: float,
                    wake_fraction: float, relative_rotative_efficiency: float,
                    shaft_efficiency: float, sfoc_g_per_kwh: float | None = None,
                    n_rps_bounds: tuple[float, float] | None = None) -> PropellerMatch:
    """Match one propeller to total resistance at positive forward speed.

    T_required=RT/(1-t), Va=U(1-w), J=Va/(nD), T=rho*n²*D⁴*KT(J).
    Substitution gives a cubic KT(J)-[T_required/(rho*Va²*D²)]*J²=0.
    All roots in 0<J<=1.4 are considered, optionally restricted by caller
    shaft-speed limits in revolutions/second. Retain only KT>0, KQ>0 and
    0<eta0<=1. Multiple roots are returned, never silently optimized/selected.
    A no_root status is restricted to these bounds, not proof no root exists
    elsewhere. Static/bollard, windmilling, zero-load, multiple screws, engine
    torque limits and cavitation constraints are outside this API.

    Q0 is open-water torque. Delivered shaft power = 2*pi*n*Q0/etaR;
    propulsion_power computes that same quantity via PE/(etaH*eta0*etaR).
    etaR is applied once, not to both KT/KQ and power. PB=PD/etaS.
    All interaction factors and SFOC are caller assumptions, not predictions.
    """
    for name, value in (('resistance_n', resistance_n), ('speed_ms', speed_ms),
                        ('water_density_kg_m3', water_density_kg_m3), ('diameter_m', diameter_m),
                        ('relative_rotative_efficiency', relative_rotative_efficiency),
                        ('shaft_efficiency', shaft_efficiency)):
        _positive(name, value)
    if shaft_efficiency > 1:
        raise ValueError('shaft_efficiency must be <= 1')
    for name, value in (('thrust_deduction', thrust_deduction), ('wake_fraction', wake_fraction)):
        if not math.isfinite(value) or value >= 1:
            raise ValueError(f'{name} must be finite and < 1')
    if sfoc_g_per_kwh is not None:
        _positive('sfoc_g_per_kwh', sfoc_g_per_kwh)
    if n_rps_bounds is not None:
        if len(n_rps_bounds) != 2:
            raise ValueError('n_rps_bounds must contain two positive speeds')
        for speed in n_rps_bounds:
            _positive('n_rps_bounds', speed)
        if n_rps_bounds[0] >= n_rps_bounds[1]:
            raise ValueError('n_rps_bounds must be strictly increasing')
    warnings = [*_BASE_WARNINGS,
                'Caller-supplied t, w, etaR and etaS; single propeller, positive forward load only.',
                'Search is restricted to 0<J<=1.4 and any caller n_rps_bounds; no engine or cavitation feasibility check.']
    geometry_warnings = _geometry_warnings(pitch_diameter_ratio, expanded_area_ratio, blade_count)
    if geometry_warnings:
        return PropellerMatch('outside_range', (), tuple([*warnings, *geometry_warnings]))
    advance_speed = speed_ms * (1-wake_fraction)
    required_thrust = resistance_n/(1-thrust_deduction)
    loading = required_thrust/(water_density_kg_m3 * advance_speed**2 * diameter_m**2)
    kt_coefficients = list(_grouped_coefficients(KT_TERMS, pitch_diameter_ratio,
                                                expanded_area_ratio, blade_count))
    kt_coefficients[2] -= loading
    lower, upper = 0., 1.4
    if n_rps_bounds is not None:
        lower = advance_speed/(n_rps_bounds[1]*diameter_m)
        upper = min(upper, advance_speed/(n_rps_bounds[0]*diameter_m))
    roots = _real_roots_in_interval(tuple(kt_coefficients), lower, upper) if lower <= upper else ()
    operating_points = []
    for j in roots:
        if j <= 0:
            continue  # J=0 implies infinite n for nonzero advance speed.
        point = wageningen_b_series(advance_coefficient=j, pitch_diameter_ratio=pitch_diameter_ratio,
                                    expanded_area_ratio=expanded_area_ratio, blade_count=blade_count)
        if point.open_water_efficiency is None or point.open_water_efficiency <= 0:
            continue
        n = advance_speed/(j*diameter_m)
        thrust = water_density_kg_m3*n**2*diameter_m**4*point.kt
        residual = thrust-required_thrust
        if abs(residual) > 1e-8*required_thrust:
            continue  # A numerically unresolved root is not a reported match.
        # Import only when power is required; use the shared accounting primitives.
        from .performance import fuel_per_day, propulsion_power
        power = propulsion_power(effective_power_kw=resistance_n*speed_ms/1000,
                                 thrust_deduction=thrust_deduction, wake_fraction=wake_fraction,
                                 open_water_efficiency=point.open_water_efficiency,
                                 relative_rotative_efficiency=relative_rotative_efficiency,
                                 shaft_efficiency=shaft_efficiency)
        fuel = (fuel_per_day(brake_power_kw=power.brake_power_kw, sfoc_g_per_kwh=sfoc_g_per_kwh).value
                if sfoc_g_per_kwh is not None else None)
        operating_points.append(MatchedOperatingPoint(
            n, 60*n, j, point.kt, point.kq, point.open_water_efficiency, thrust, residual,
            water_density_kg_m3*n**2*diameter_m**5*point.kq,
            power.delivered_power_kw, power.brake_power_kw, fuel))
    # Increasing shaft speed makes the candidate list predictable, not preferred.
    operating_points.sort(key=lambda point: point.n_rps)
    if not operating_points:
        status = 'no_root'
        warnings.append('No physical thrust-equilibrium root found within the stated J and shaft-speed bounds.')
    elif len(operating_points) > 1:
        status = 'multiple_roots'
        warnings.append('Multiple physical roots: caller must select using operating constraints; no root was preferred.')
    else:
        status = 'matched'
    return PropellerMatch(status, tuple(operating_points), tuple(warnings))
