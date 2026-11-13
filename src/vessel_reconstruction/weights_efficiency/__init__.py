"""Preliminary conventional tanker calculations, not statutory certification.

Scope: single liquid-fuel main engine, no PTO/PTI, ice, chemical-capacity,
CSR or innovative-technology corrections. Caller supplies reference-condition
speed and SFOC at the calculated power, not service speed or catalogue minimum.
CII is the unadjusted annual DWT-distance index, not a rating or voyage forecast.
"""
from dataclasses import asdict, dataclass
import math
from typing import Literal


CARBON_FACTORS = {"HFO": 3.114, "LFO": 3.151, "MDO": 3.206}
# MEPC.338(76), amended by MEPC.400(83), annex paragraph 4.
CII_REDUCTIONS = {2023: 5, 2024: 7, 2025: 9, 2026: 11,
                  2027: 13.625, 2028: 16.250, 2029: 18.875, 2030: 21.500}


def _positive(name: str, value: float) -> None:
    if not math.isfinite(value) or value <= 0:
        raise ValueError(f"{name} must be finite and positive")


def _sources(sources: tuple[str, ...]) -> None:
    if not sources or any(not s.strip() for s in sources):
        raise ValueError("input source citations are required")


def _carbon(fuel: str) -> float:
    if fuel not in CARBON_FACTORS:
        raise ValueError("only HFO, LFO and MDO single liquid fuels are supported")
    return CARBON_FACTORS[fuel]


@dataclass(frozen=True)
class Quantity:
    value: float
    unit: str
    uncertainty: dict
    method: str
    method_version: str
    sources: tuple[str, ...]
    status: str = "review_required"


@dataclass(frozen=True)
class Calculation:
    quantities: dict[str, Quantity]
    scope: str
    engineering_approved: bool = False

    def to_record_fragment(self) -> dict:
        """Return JSON-native lane data, independent of the design-record module."""
        result = asdict(self)
        for quantity in result["quantities"].values():
            quantity["sources"] = list(quantity["sources"])
        return result


def _quantity(value: float, unit: str, method: str, sources: tuple[str, ...]) -> Quantity:
    if not math.isfinite(value):
        raise ValueError("calculation produced a nonfinite quantity")
    return Quantity(value, unit, {"band": None, "reason": "Input uncertainty not supplied; no empirical error band established."},
                    method, "1", sources)


@dataclass(frozen=True)
class DesignIndexInput:
    deadweight_t: float
    mcr_kw: float
    reference_speed_kn: float
    main_sfoc_g_kwh: float
    auxiliary_sfoc_g_kwh: float
    main_fuel: str
    auxiliary_fuel: str
    sources: tuple[str, ...]
    index: Literal["EEDI", "EEXI"] = "EEDI"
    limited_mcr_kw: float | None = None


def design_index(data: DesignIndexInput) -> Calculation:
    """Uncorrected attained index; SFOC and speed must match reference power.

    MEPC.364(79) §§2.1, 2.2.1–2.2.7; MEPC.350(78) §2.2.1 for EPL.
    The original MCR is retained for the auxiliary load approximation (no PTO).
    """
    _sources(data.sources)
    for name in ("deadweight_t", "mcr_kw", "reference_speed_kn", "main_sfoc_g_kwh", "auxiliary_sfoc_g_kwh"):
        _positive(name, getattr(data, name))
    if data.index not in ("EEDI", "EEXI"):
        raise ValueError("index must be EEDI or EEXI")
    main = .75 * data.mcr_kw
    if data.limited_mcr_kw is not None:
        _positive("limited_mcr_kw", data.limited_mcr_kw)
        if data.index != "EEXI" or data.limited_mcr_kw > data.mcr_kw:
            raise ValueError("power limitation is only supported for EEXI and cannot exceed original MCR")
        main = min(main, .83 * data.limited_mcr_kw)
    auxiliary = .025 * data.mcr_kw + 250 if data.mcr_kw >= 10000 else .05 * data.mcr_kw
    emissions = main * data.main_sfoc_g_kwh * _carbon(data.main_fuel)
    emissions += auxiliary * data.auxiliary_sfoc_g_kwh * _carbon(data.auxiliary_fuel)
    sources = data.sources + ("MEPC.364(79)",)
    if data.index == "EEXI":
        sources += ("MEPC.350(78)",)
    method = f"conventional_tanker_{data.index.lower()}_uncorrected"
    values = {"attained_index": (emissions / (data.deadweight_t * data.reference_speed_kn), "g CO2/(t nm)"),
              "main_power_kw": (main, "kW"), "auxiliary_power_kw": (auxiliary, "kW"),
              "reference_speed_kn": (data.reference_speed_kn, "kn"),
              "reference_speed_ms": (data.reference_speed_kn * 1852 / 3600, "m/s")}
    return Calculation({k: _quantity(v, u, method, sources) for k, (v, u) in values.items()},
                       "Uncorrected conventional oil tanker only; no statutory compliance determination.")


@dataclass(frozen=True)
class OperationalInput:
    deadweight_t: float
    distance_nm: float
    fuel_t: tuple[tuple[str, float], ...]
    year: int
    sources: tuple[str, ...]


def operational_cii(data: OperationalInput) -> Calculation:
    """Annual unadjusted AER; all consumed fuel must be included by the caller.

    MEPC.352(78) G1, MEPC.353(78) G2 table 1. No G5 deductions
    (MEPC.355(78)), shuttle/STS correction or A–E rating is applied.
    """
    _sources(data.sources)
    _positive("deadweight_t", data.deadweight_t)
    _positive("distance_nm", data.distance_nm)
    if data.year not in CII_REDUCTIONS or not data.fuel_t:
        raise ValueError("CII requires annual fuel and a year from 2023 through 2030")
    co2_t = 0.0
    for fuel, mass in data.fuel_t:
        if not math.isfinite(mass) or mass < 0:
            raise ValueError("fuel mass must be finite and nonnegative")
        co2_t += mass * _carbon(fuel)
    reference = 5247 * data.deadweight_t ** -.610
    sources = data.sources + ("MEPC.352(78)", "MEPC.353(78)", "MEPC.338(76)", "MEPC.400(83)")
    values = {"attained_cii": co2_t * 1e6 / (data.deadweight_t * data.distance_nm),
              "reference_cii": reference,
              "required_cii": reference * (1 - CII_REDUCTIONS[data.year] / 100)}
    return Calculation({k: _quantity(v, "g CO2/(t nm)", "tanker_annual_aer", sources) for k, v in values.items()},
                       "Annual unadjusted tanker CII; no MEPC.355(78) deductions or rating.")
