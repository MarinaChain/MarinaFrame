"""Source-table engine screening, with no bundled or inferred maker data.

The supplied layout must be convex in log(rpm), log(kW), as in two-stroke
layout diagrams. SFOC rows must apply to the selected SMCR tuning, fuel and
ambient conditions. This screens power/speed only, not propeller torque,
barred speeds, emissions, minimum power or transient capability.
"""
from dataclasses import dataclass
import math

from . import Calculation, _positive, _quantity, _sources
from ..holtrop import HoltropResistance
from ..performance import propulsion_power


def brake_power_from_holtrop(resistance: HoltropResistance, *, thrust_deduction: float,
                             wake_fraction: float, open_water_efficiency: float,
                             relative_rotative_efficiency: float, shaft_efficiency: float,
                             sources: tuple[str, ...]) -> Calculation:
    """Read the existing resistance result; keep explicit propulsion assumptions."""
    _sources(sources)
    power = propulsion_power(
        effective_power_kw=resistance.effective_power_kw,
        thrust_deduction=thrust_deduction, wake_fraction=wake_fraction,
        open_water_efficiency=open_water_efficiency,
        relative_rotative_efficiency=relative_rotative_efficiency,
        shaft_efficiency=shaft_efficiency,
    )
    quantity = _quantity(power.brake_power_kw, "kW", "effective_to_brake_power",
                         sources + (resistance.method,))
    warnings = resistance.validity_warnings + resistance.range_warnings
    scope = "Calm-water brake power; caller-supplied propulsion efficiencies."
    if warnings:
        scope += " Resistance warnings: " + "; ".join(warnings)
    return Calculation({"calm_brake_power_kw": quantity}, scope)


@dataclass(frozen=True)
class EngineLayout:
    name: str
    vertices: tuple[tuple[float, float], ...]  # rpm, kW, boundary order
    sfoc_by_load: tuple[tuple[float, float], ...]  # fraction of selected SMCR, g/kWh
    sources: tuple[str, ...]
    sfoc_rating_kw: float
    sfoc_rating_rpm: float


@dataclass(frozen=True)
class EngineRequest:
    calm_brake_power_kw: float
    rpm: float
    sea_margin: float
    engine_margin: float  # unused fraction of SMCR at service sea power
    sources: tuple[str, ...]


def _cross(a: tuple, b: tuple, p: tuple) -> float:
    return (b[0] - a[0]) * (p[1] - a[1]) - (b[1] - a[1]) * (p[0] - a[0])


def _layout_polygon(layout: EngineLayout) -> tuple:
    _sources(layout.sources)
    _positive("SFOC rating kW", layout.sfoc_rating_kw)
    _positive("SFOC rating rpm", layout.sfoc_rating_rpm)
    if not layout.name.strip() or len(layout.vertices) < 3:
        raise ValueError("named layout requires at least three boundary vertices")
    for rpm, power in layout.vertices:
        _positive("layout rpm", rpm)
        _positive("layout power", power)
    points = tuple((math.log(rpm), math.log(power)) for rpm, power in layout.vertices)
    turns = [_cross(points[i-1], points[i], points[(i+1) % len(points)]) for i in range(len(points))]
    if not (all(t > 0 for t in turns) or all(t < 0 for t in turns)):
        raise ValueError("layout must be a strictly convex ordered polygon in log coordinates")
    if len(layout.sfoc_by_load) < 2:
        raise ValueError("SFOC table requires at least two load points")
    previous = 0.0
    for load, sfoc in layout.sfoc_by_load:
        _positive("load fraction", load)
        _positive("SFOC", sfoc)
        if not previous < load <= 1:
            raise ValueError("SFOC load fractions must increase and be at most one")
        previous = load
    return points


def _interpolate_sfoc(rows: tuple, load: float) -> float | None:
    for (x0, y0), (x1, y1) in zip(rows, rows[1:]):
        if x0 <= load <= x1:
            return y0 + (y1-y0) * (load-x0) / (x1-x0)
    return None


def select_engine(request: EngineRequest, layouts: tuple[EngineLayout, ...]) -> tuple[Calculation, ...]:
    """Return feasible supplied layouts in input order; never extrapolate tables.

    SMCR = calm brake power * (1+sea margin)/(1-engine margin).
    Read Holtrop effective power through an explicit propulsion/shaft loss
    calculation before supplying brake power: effective power is not brake power.
    """
    _sources(request.sources)
    _positive("calm_brake_power_kw", request.calm_brake_power_kw)
    _positive("rpm", request.rpm)
    if not math.isfinite(request.sea_margin) or request.sea_margin < 0:
        raise ValueError("sea margin must be finite and nonnegative")
    if not math.isfinite(request.engine_margin) or not 0 <= request.engine_margin < 1:
        raise ValueError("engine margin must be in [0, 1)")
    sea_power = request.calm_brake_power_kw * (1 + request.sea_margin)
    smcr = sea_power / (1-request.engine_margin)
    _positive("SMCR", smcr)
    operating_load = 1-request.engine_margin
    operating_point = (math.log(request.rpm), math.log(smcr))
    results = []
    for layout in layouts:
        points = _layout_polygon(layout)
        sides = [_cross(points[i-1], points[i], operating_point) for i in range(len(points))]
        # Numerical tolerance is dimensionless in logarithmic coordinates.
        if not (all(s >= -1e-12 for s in sides) or all(s <= 1e-12 for s in sides)):
            continue
        if not (math.isclose(smcr, layout.sfoc_rating_kw, rel_tol=1e-9)
                and math.isclose(request.rpm, layout.sfoc_rating_rpm, rel_tol=1e-9)):
            continue
        sfoc = _interpolate_sfoc(layout.sfoc_by_load, operating_load)
        if sfoc is None:
            continue
        sources = request.sources + layout.sources
        values = {"smcr_kw": (smcr, "kW"), "sea_power_kw": (sea_power, "kW"),
                  "rpm": (request.rpm, "rpm"), "operating_sfoc": (sfoc, "g/kWh")}
        quantities = {k: _quantity(v, u, "source_layout_screen", sources) for k, (v, u) in values.items()}
        results.append(Calculation(quantities, f"Layout {layout.name}; SFOC valid only for caller-supplied selected-SMCR tuning table."))
    return tuple(results)
