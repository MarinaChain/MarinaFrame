"""The vessel table: one offset table for the whole hull, and its build.

Whole-vessel design (docs/plans/2026-11-08-whole-vessel-design.md, section 2).
The table is the geometry state of a draft. Each station row holds one
half-section curve ``points_yz_m`` (y = half-breadth, z = height, metres) with
its source:

* ``traced``: measured ink, kept exactly (an anchor). It refers to the traced
  candidate's ``contour_selection``, so the build re-reads the same ink; the
  table may only clip its height range (``z_min_m``/``z_max_m``).
* ``fitted``: made by the anchored form fit (form_fit.py) where no anchor is
  usable. It builds as a curve and is shown as ``interpolated``.

The half-breadth cells ``hb(x_i, z_j)`` on stations x waterlines are a
projection of the rows (``cells``). The body plan, plan view (rows of the cell
matrix along x) and profile (keel and top per station) are all read from this
one table, so the views agree by construction.

This module has no image code and no CAD code. ``build_spec`` compiles the
table into an ordinary draft specification for the existing builder.
"""
from __future__ import annotations

import copy
import math
from dataclasses import asdict, dataclass, field

import numpy as np

from .draft import DRAFT_STATUS
from .provenance import digest_object

TABLE_VERSION = "vessel-table/v1"
ROW_SOURCES = ("traced", "fitted")
# The label each row source has in a draft build (section_authoring.SOURCE_LABELS).
BUILD_LABELS = {"traced": "traced", "fitted": "interpolated"}
# Waterlines of the cell matrix. The rows keep full resolution for the build;
# the cells are the table that views and scores compare.
DEFAULT_WATERLINES = 21
# Samples of a fitted row curve (the builder accepts 5 to 1025 points).
FITTED_ROW_SAMPLES = 65
MAX_BASIS_CHARS = 300
# The builder accepts curve sections of 5 to 1025 points with rising heights.
MAX_CURVE_POINTS = 1025
HEIGHT_RESOLUTION_M = 1e-6


@dataclass
class StationRow:
    """One station of the table: its half-section curve and where it came from."""
    id: str
    x_m: float
    points_yz_m: list
    source: str
    locked: bool = False
    keel_z_m: float | None = None
    top_z_m: float | None = None
    # Traced rows only: the declared section with the candidate's contour selection.
    selection_section: dict | None = None
    notes: list = field(default_factory=list)

    def __post_init__(self):
        if self.source not in ROW_SOURCES:
            raise ValueError(f"Row source must be one of {ROW_SOURCES}.")
        points = np.asarray(self.points_yz_m, dtype=float)
        if points.ndim != 2 or points.shape[1] != 2 or len(points) < 2 or not np.isfinite(points).all():
            raise ValueError(f"Station {self.id}: a row needs at least two finite [y, z] points.")
        points = points[np.argsort(points[:, 1], kind="stable")]
        self.points_yz_m = points.tolist()
        if self.keel_z_m is None:
            self.keel_z_m = float(points[0, 1])
        if self.top_z_m is None:
            self.top_z_m = float(points[-1, 1])


@dataclass
class VesselTable:
    """Stations x waterlines offset table with full-resolution rows."""
    stations: list
    waterlines_z_m: list
    trend: dict = field(default_factory=dict)
    warnings: list = field(default_factory=list)

    def __post_init__(self):
        self.stations = sorted(self.stations, key=lambda row: row.x_m)
        ids = [row.id for row in self.stations]
        if len(set(ids)) != len(ids):
            raise ValueError("Station ids must be unique.")

    def row(self, station_id: str) -> StationRow:
        return next(row for row in self.stations if row.id == station_id)

    def cells(self) -> np.ndarray:
        """Half-breadth hb[i][j] at station i and waterline j; NaN outside the hull."""
        z = np.asarray(self.waterlines_z_m, dtype=float)
        table = np.full((len(self.stations), len(z)), np.nan)
        for i, row in enumerate(self.stations):
            points = np.asarray(row.points_yz_m, dtype=float)
            inside = (z >= row.keel_z_m) & (z <= row.top_z_m)
            table[i, inside] = np.interp(z[inside], points[:, 1], points[:, 0])
        return table

    def sources(self) -> dict:
        return {row.id: row.source for row in self.stations}

    def to_json(self) -> dict:
        return {"version": TABLE_VERSION,
                "x_m": [row.x_m for row in self.stations],
                "z_m": list(self.waterlines_z_m),
                "cells_hb_m": [[None if math.isnan(v) else round(float(v), 5) for v in line]
                               for line in self.cells()],
                "stations": [asdict(row) for row in self.stations],
                "trend": self.trend, "warnings": self.warnings}

    @classmethod
    def from_json(cls, data: dict) -> "VesselTable":
        if data.get("version") != TABLE_VERSION:
            raise ValueError("Unsupported vessel table version.")
        return cls([StationRow(**row) for row in data["stations"]], list(data["z_m"]),
                   dict(data.get("trend") or {}), list(data.get("warnings") or []))


def waterline_grid(rows: list, count: int = DEFAULT_WATERLINES) -> list:
    """Evenly spaced waterlines from the lowest keel to the highest top of the rows."""
    low = min(row.keel_z_m for row in rows)
    high = max(row.top_z_m for row in rows)
    return [round(float(v), 6) for v in np.linspace(low, high, count)]


def _guess(section_id: str, kind: str, x_m: float, x_range, reason: str) -> dict:
    return {"guess_id": "guess-" + digest_object({"section_id": section_id, "kind": kind, "table": TABLE_VERSION})[:20],
            "section_id": section_id, "kind": kind, "x_m": x_m, "x_range_m": x_range,
            "chosen_candidate_id": None, "alternatives": [], "score": None, "reason": reason[:512],
            "status": "open"}


def _curve_points(points_yz_m) -> list:
    """Row points for a curve section: strictly rising heights, at most MAX_CURVE_POINTS."""
    points = np.asarray(points_yz_m, dtype=float)
    keep = np.concatenate([[True], np.diff(points[:, 1]) > HEIGHT_RESOLUTION_M])
    points = points[keep]
    if len(points) > MAX_CURVE_POINTS:
        points = points[np.linspace(0, len(points) - 1, MAX_CURVE_POINTS).round().astype(int)]
    return [[max(float(y), 0.0), float(z)] for y, z in points]


def build_spec(table: VesselTable, base_spec: dict, declared: list[dict] | None = None, *,
               basis: str = "Vessel table form fit") -> dict:
    """A draft specification that builds the table with the existing builder.

    ``base_spec`` is the draft revision spec the anchors came from (sources,
    calibration, open guesses); ``declared`` are the input spec sections, for
    stations the revision left out (no readable line). Traced rows keep their
    contour selection and take the row's top, so the build reads the same ink. Fitted rows
    become curve sections labelled ``interpolated``, each with an open guess
    that says it was filled by the fit. Every declared station is built.
    """
    spec = copy.deepcopy(base_spec)
    declared = {section["id"]: section for section in (declared or []) + spec["sections"]}
    old_guesses = {g["section_id"]: g for g in (spec.get("draft") or {}).get("guesses", [])}
    traced_x = [row.x_m for row in table.stations if row.source == "traced"]
    sections, guesses = [], []
    for row in table.stations:
        if row.source == "traced":
            section = copy.deepcopy(row.selection_section)
            if section is None or "contour_selection" not in section:
                raise ValueError(f"Traced row {row.id} has no contour selection to rebuild from.")
            # The build reads the ink only on the row's own height range: the
            # fit clips ink above the hull top, and a stroke that starts above
            # the declared keel height (a partial or end-station trace) must
            # not be read, or extended, below its ink.
            section["z_max_m"] = float(min(section.get("z_max_m", row.top_z_m), row.top_z_m))
            section["z_min_m"] = float(max(section.get("z_min_m", row.keel_z_m), row.keel_z_m))
            sections.append(section)
            if row.id in old_guesses and old_guesses[row.id].get("chosen_candidate_id") is not None:
                guesses.append(old_guesses[row.id])
            continue
        section = copy.deepcopy(declared.get(row.id) or {})
        if not section:
            raise ValueError(f"Fitted row {row.id} is not a declared station.")
        section.pop("contour_selection", None)
        section.pop("pieces", None)
        note = "; ".join(row.notes)[:120]
        section["authored"] = {"source_label": BUILD_LABELS[row.source],
                               "basis": (basis + (": " + note if note else ""))[:MAX_BASIS_CHARS],
                               "points_yz_m": _curve_points(row.points_yz_m)}
        section["evidence"] = (section.get("evidence", "")[:7000] +
                               " Filled by the vessel-table form fit; not measured ink; a person must confirm it.")
        sections.append(section)
        lower = max((x for x in traced_x if x < row.x_m), default=None)
        upper = min((x for x in traced_x if x > row.x_m), default=None)
        reason = "Form fit filled this station from the hull trend and the traced neighbours."
        if lower is not None and upper is not None:
            guesses.append(_guess(row.id, "bridged_gap", row.x_m, [lower, upper], reason))
        else:
            guesses.append(_guess(row.id, "dropped_end", row.x_m, None, reason + " It is outside the traced range."))
    spec["sections"] = sections
    if guesses:
        spec["draft"] = {"status": DRAFT_STATUS, "guesses": guesses}
    else:
        spec.pop("draft", None)  # Every row is selected ink: an ordinary build.
    return spec
