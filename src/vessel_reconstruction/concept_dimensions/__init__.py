"""Public-fleet concept screening, not a design acceptance calculation.

L is always length between perpendiculars. Fleet uncertainty is an empirical
training envelope, not a confidence level or a joint feasible hull envelope.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Iterable

import numpy as np

VERSION = "1.0.0"
KNOT_M_S = 1852 / 3600
DIMENSIONS = {"lpp": "lpp_m", "beam": "beam_m", "depth": "depth_m", "draft": "draft_m", "cb": "cb"}
MIN_DESIGNS = 4


def _positive(name: str, value: float | None) -> None:
    if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float))
                              or not math.isfinite(value) or value <= 0):
        raise ValueError(f"{name} must be finite and positive")


def _quantity(value: float | None, unit: str, method: str, sources: Iterable[str],
              uncertainty: dict | None = None, reason: str = "not supplied") -> dict:
    return {
        "value": value, "unit": unit,
        "uncertainty": uncertainty if uncertainty is not None else {"reason": reason},
        "method": method, "method_version": VERSION, "sources": sorted(set(sources)),
        "status": "review_required",
    }


@dataclass(frozen=True)
class Requirements:
    dwt_t: float
    cargo_volume_m3: float | None = None
    service_speed_kn: float | None = None
    range_m: float | None = None
    max_draft_m: float | None = None
    max_beam_m: float | None = None
    cargo_types: tuple[str, ...] = ()
    class_notation: str | None = None
    flag: str | None = None

    def __post_init__(self) -> None:
        for name in ("dwt_t", "cargo_volume_m3", "service_speed_kn", "range_m", "max_draft_m", "max_beam_m"):
            _positive(name, getattr(self, name))
        if self.dwt_t is None:
            raise ValueError("dwt_t is required")

    def to_record_fragment(self) -> dict:
        fields = {"dwt": (self.dwt_t, "t"), "cargo_volume": (self.cargo_volume_m3, "m3"),
                  "service_speed_kn": (self.service_speed_kn, "kn"),
                  "service_speed_m_s": (None if self.service_speed_kn is None else self.service_speed_kn * KNOT_M_S, "m/s"),
                  "range": (self.range_m, "m"), "max_draft": (self.max_draft_m, "m"),
                  "max_beam": (self.max_beam_m, "m")}
        result = {name: _quantity(value, unit, "owner_requirement", ("input:requirements",),
                                 reason="owner input; tolerance not supplied" if value is not None else "not supplied")
                  for name, (value, unit) in fields.items()}
        result.update(cargo_types=list(self.cargo_types), class_notation=self.class_notation, flag=self.flag)
        return result


@dataclass(frozen=True)
class FleetShip:
    ship_id: str
    design_id: str
    dwt_t: float
    lpp_m: float
    beam_m: float
    depth_m: float
    draft_m: float
    cb: float
    sources: tuple[str, ...]
    cargo_volume_m3: float | None = None
    service_speed_kn: float | None = None
    cargo_types: tuple[str, ...] = ()
    length_basis: str = "lpp"

    def __post_init__(self) -> None:
        if not self.ship_id.strip() or not self.design_id.strip() or not self.sources or any(not source.strip() for source in self.sources):
            raise ValueError("ship, independent design and source IDs are required")
        if self.length_basis != "lpp":
            raise ValueError("length_basis must be lpp, never substitute LOA")
        for name in ("dwt_t", "lpp_m", "beam_m", "depth_m", "draft_m", "cb"):
            if getattr(self, name) is None:
                raise ValueError(f"{name} is required; incomplete fleet rows cannot train")
            _positive(name, getattr(self, name))
        for name in ("cargo_volume_m3", "service_speed_kn"):
            _positive(name, getattr(self, name))
        if self.cb > 1 or not self.draft_m < self.depth_m or not self.beam_m < self.lpp_m:
            raise ValueError("invalid hull dimensions or block coefficient")


def froude_number(speed_kn: float, lpp_m: float) -> float:
    """Fn = V/sqrt(g Lpp); g is standard gravity, in m/s2."""
    _positive("speed", speed_kn)
    _positive("lpp", lpp_m)
    return speed_kn * KNOT_M_S / math.sqrt(9.80665 * lpp_m)


def displacement_t(lpp_m: float, beam_m: float, draft_m: float, cb: float,
                   *, water_density_t_m3: float = 1.025) -> float:
    """Displacement identity; density must match the intended loading condition."""
    for name, value in locals().items():
        _positive(name, value)
    if cb > 1:
        raise ValueError("cb must not exceed 1")
    return lpp_m * beam_m * draft_m * cb * water_density_t_m3


@dataclass(frozen=True)
class DimensionRange:
    value: float
    lower: float
    upper: float
    unit: str
    basis: str
    sources: tuple[str, ...]
    method: str = "dwt_log_linear"

    def to_record_fragment(self) -> dict:
        return _quantity(self.value, self.unit, self.method, self.sources,
                         {"kind": "absolute_band", "lower": self.lower, "upper": self.upper, "basis": self.basis})


@dataclass(frozen=True)
class Proposal:
    requirements: Requirements
    dimensions: dict[str, DimensionRange]
    neighbours: dict[str, DimensionRange]
    references: tuple[dict, ...]
    constraints: tuple[dict, ...]
    warnings: tuple[str, ...]
    training_ship_ids: tuple[str, ...]

    def to_record_fragment(self) -> dict:
        states = {item["status"] for item in self.constraints}
        feasible = False if "infeasible" in states else (True if states == {"within"} else None)
        return {"requirements": self.requirements.to_record_fragment(),
                "main_dimensions": {key: value.to_record_fragment() for key, value in self.dimensions.items()},
                "neighbour_ranges": {key: value.to_record_fragment() for key, value in self.neighbours.items()},
                "references": list(self.references), "constraints": list(self.constraints),
                "warnings": list(self.warnings), "feasible": False if feasible is False else None,
                "port_limits_within_ranges": feasible,
                "training_ship_ids": list(self.training_ship_ids), "engineering_approved": False,
                "status": "review_required", "method_version": VERSION}


@dataclass(frozen=True)
class FleetModel:
    ships: tuple[FleetShip, ...]
    coefficients: dict[str, tuple[float, float]]
    log_bands: dict[str, float]

    @property
    def training_ship_ids(self) -> tuple[str, ...]:
        return tuple(ship.ship_id for ship in self.ships)

    @classmethod
    def fit(cls, ships: Iterable[FleetShip], *, excluded_ship_ids: Iterable[str] = (),
            excluded_design_ids: Iterable[str] = ()) -> FleetModel:
        rows = sorted(ships, key=lambda ship: ship.ship_id)
        if len({ship.ship_id for ship in rows}) != len(rows):
            raise ValueError("ship IDs must be unique")
        excluded_ships = set(excluded_ship_ids)
        unresolved = excluded_ships - {ship.ship_id for ship in rows}
        if unresolved:
            raise ValueError("unresolved excluded ship IDs; supply their rows or exclude design IDs instead")
        excluded_designs = set(excluded_design_ids) | {ship.design_id for ship in rows if ship.ship_id in excluded_ships}
        designs = {}
        for ship in rows:
            if ship.ship_id not in excluded_ships and ship.design_id not in excluded_designs:
                designs.setdefault(ship.design_id, ship)
        training = tuple(sorted(designs.values(), key=lambda ship: ship.design_id))
        if len(training) < MIN_DESIGNS:
            raise ValueError(f"at least {MIN_DESIGNS} independent designs required")
        x = np.log([ship.dwt_t for ship in training])
        if float(np.ptp(x)) < math.log(1.1):
            raise ValueError("training DWT must span at least 10 percent")
        matrix = np.column_stack((np.ones(len(x)), x))
        coefficients, bands = {}, {}
        for name, field in DIMENSIONS.items():
            y = np.log([getattr(ship, field) for ship in training])
            intercept, slope = np.linalg.lstsq(matrix, y, rcond=None)[0]
            coefficients[name] = (float(intercept), float(slope))
            # Fixed screening floor, not a fitted confidence level.
            floor = 0.05 if name == "cb" else 0.10
            bands[name] = float(np.max(np.abs(y - matrix @ [intercept, slope]))) + math.log1p(floor)
        return cls(training, coefficients, bands)

    def _distance(self, ship: FleetShip, req: Requirements) -> float:
        # Equal-weight log ratios. Missing optional inputs incur a fixed penalty.
        terms = [math.log(ship.dwt_t / req.dwt_t) ** 2]
        for actual, target in ((ship.cargo_volume_m3, req.cargo_volume_m3), (ship.service_speed_kn, req.service_speed_kn)):
            if target is not None:
                terms.append(math.log(actual / target) ** 2 if actual is not None else 1.0)
        if req.cargo_types and not set(req.cargo_types).issubset(ship.cargo_types):
            terms.append(1.0)
        return math.sqrt(sum(terms))

    def propose(self, req: Requirements, *, reference_count: int = 3) -> Proposal:
        if not isinstance(reference_count, int) or reference_count < 1:
            raise ValueError("reference_count must be a positive integer")
        ranked = sorted(self.ships, key=lambda ship: (self._distance(ship, req), ship.ship_id))[:reference_count]
        sources = tuple(sorted({source for ship in self.ships for source in ship.sources}))
        dimensions, neighbours = {}, {}
        for name, field in DIMENSIONS.items():
            intercept, slope = self.coefficients[name]
            value = math.exp(intercept + slope * math.log(req.dwt_t))
            band = self.log_bands[name]
            lower, upper = value * math.exp(-band), value * math.exp(band)
            if name == "cb":
                value, lower, upper = min(value, 1.0), min(lower, 1.0), min(upper, 1.0)
            unit = "1" if name == "cb" else "m"
            dimensions[name] = DimensionRange(value, lower, upper, unit,
                "max absolute training log residual + fixed 5% Cb / 10% dimension floor; not probabilistic", sources)
            values = [getattr(ship, field) for ship in ranked]
            neighbours[name] = DimensionRange(float(np.median(values)), min(values), max(values), unit,
                "observed nearest independent designs; not a prediction interval",
                tuple(sorted({source for ship in ranked for source in ship.sources})), "nearest_neighbour_envelope")
        constraints = []
        for name, limit in (("beam", req.max_beam_m), ("draft", req.max_draft_m)):
            if limit is not None:
                interval = dimensions[name]
                state = "infeasible" if interval.lower > limit else "within" if interval.upper <= limit else "overlap"
                constraints.append({"dimension": name, "status": state,
                    "limit": _quantity(limit, "m", "owner_requirement", ("input:requirements",)),
                    "margin_at_estimate": _quantity(limit - interval.value, "m", "port_limit_margin", sources,
                        reason="range is reported separately; no joint feasibility calculation")})
        warnings = ["Screening ranges are marginal, not a joint feasible hull or a confidence level.",
                    "Range, class, flag and cargo compatibility require engineering review; fuel and power are not modelled.",
                    "DWT-only regressions do not enforce cargo capacity or speed; reference search uses these inputs."]
        if not min(ship.dwt_t for ship in self.ships) <= req.dwt_t <= max(ship.dwt_t for ship in self.ships):
            warnings.append("DWT extrapolation outside training support; bands have no demonstrated coverage.")
        if req.cargo_volume_m3 is not None and any(ship.cargo_volume_m3 is None for ship in ranked):
            warnings.append("Missing cargo capacity in one or more references.")
        if req.cargo_types and any(not set(req.cargo_types).issubset(ship.cargo_types) for ship in ranked):
            warnings.append("Cargo type mismatch or unknown cargo compatibility in references.")
        references = tuple(self._reference(ship, req) for ship in ranked)
        return Proposal(req, dimensions, neighbours, references, tuple(constraints), tuple(warnings), self.training_ship_ids)

    def _reference(self, ship: FleetShip, req: Requirements) -> dict:
        differences = {}
        for name, actual, target, unit in (
            ("dwt", ship.dwt_t, req.dwt_t, "t"),
            ("cargo_volume", ship.cargo_volume_m3, req.cargo_volume_m3, "m3"),
            ("service_speed_kn", ship.service_speed_kn, req.service_speed_kn, "kn"),
            ("service_speed_m_s", None if ship.service_speed_kn is None else ship.service_speed_kn * KNOT_M_S,
             None if req.service_speed_kn is None else req.service_speed_kn * KNOT_M_S, "m/s"),
            ("payload", None, None, "t"), ("fuel_per_day", None, None, "t/day"),
        ):
            difference = actual - target if actual is not None and target is not None else None
            differences[name] = _quantity(difference, unit, "reference_minus_requirement", ship.sources,
                reason="input measurement tolerances not supplied" if difference is not None else "not supplied; DWT is not cargo payload")
        return {"ship_id": ship.ship_id, "design_id": ship.design_id,
                "distance": _quantity(self._distance(ship, req), "1", "equal_weight_log_distance", ship.sources,
                                      reason="ranking distance, not a probability"),
                "differences": differences,
                "dimensions": {name: _quantity(getattr(ship, field), "1" if name == "cb" else "m", "published_particulars", ship.sources,
                                               reason="source tolerances not supplied") for name, field in DIMENSIONS.items()}}


__all__ = ["Requirements", "FleetShip", "FleetModel", "Proposal", "DimensionRange", "displacement_t", "froude_number"]
