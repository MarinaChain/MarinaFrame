"""Product body-plan side reading: the hard-chine polyline reader where it engages, the crossing reader otherwise.

One entry point (`read_side`) gives, for one half of a calibrated body plan, the waterline table, a drawn curve
per station and where each station's name came from. It combines two code-only readers
(docs/plans/2026-11-11-polyline-integration.md):

- the crossing reader (`body_plan_reader.measure_side`, names by nesting rank), which reads round-bilge halves;
- the polyline reader (`body_plan_polyline`), which traces each station along its own ink and finds the chine
  knuckle. A half with enough knuckled stations is read as a whole (names by nesting rank of the polylines). On
  any other half, a station with a clear knuckle is engaged one by one, under the name the crossing reader gave
  the same curve; every other station keeps the crossing reader's cells and curve.

A round-bilge half has no clear knuckle: its table and curves are the crossing reader's, unchanged. Truth,
vessel names and benchmark constants are never read. `engineering_approved` stays false wherever this is used.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from vessel_reconstruction import body_plan_polyline as polyline
from vessel_reconstruction import body_plan_reader as bpr

# Where a station's name came from (each station record states one).
IDENTITY_RANK = 'crossing reader: nesting order (outermost chain first)'
IDENTITY_POLYLINE = 'polyline reader: nesting order of the traced hard-chine stations'
IDENTITY_ENGAGED = 'polyline station, named by the crossing reader for the same curve'


@dataclass
class SideResult:
    """The product reading of one half."""

    side: str
    table: dict  # {(station, waterline label): half-breadth m}
    curves: dict  # {station: (n, 2) image points (row, column), the drawn curve of that station}
    identity_source: dict  # {station: IDENTITY_*}
    half: polyline.HalfReading  # the polyline reading, with the engaged stations
    fairness_flags: list = field(default_factory=list)

    @property
    def polyline_used(self) -> bool:
        return self.half.read or bool(self.half.engaged)


def read_side(ink: np.ndarray, layout: bpr.SheetLayout, reading) -> SideResult:
    """Read one half: `reading` is the crossing reader's `SideReading` of that half (`measure_side`).

    `ink` is the boolean ink mask the crossing reader read.
    """
    side = reading.layout
    identities = bpr.identities_by_rank(reading.chains, side.stations_outer_first)
    existing = bpr.table_from_identities(reading, identities, layout.pixels_per_metre, layout.centre_column)
    half = polyline.read_half(ink, layout, side)
    polyline.engage_stations(half, side, existing, layout, ink)
    table = polyline.half_table(half, existing, layout)
    curves, sources = {}, {}
    if half.read:
        for station in half.stations:
            curves[station.station] = station.points
            sources[station.station] = IDENTITY_POLYLINE
    else:
        engaged = {station.station: station for station in half.engaged}
        for chain_index, name in sorted(identities.items(), key=lambda item: item[1]):
            if name not in engaged:
                curves[name] = np.asarray(reading.chains[chain_index].path, dtype=float).reshape(-1, 2)
                sources[name] = IDENTITY_RANK
        for name, station in engaged.items():
            curves[name] = station.points
            sources[name] = IDENTITY_ENGAGED
    flags = bpr.fairness_flags(table, side.stations_outer_first, layout.waterlines_low_to_high())
    return SideResult(side.name, table, curves, sources, half, flags)


def read_sheet(ink: np.ndarray, layout: bpr.SheetLayout, readings: dict) -> dict[str, SideResult]:
    """`read_side` for each half; `readings` maps half name to the crossing reader's `SideReading`."""
    return {name: read_side(ink, layout, reading) for name, reading in readings.items()}
