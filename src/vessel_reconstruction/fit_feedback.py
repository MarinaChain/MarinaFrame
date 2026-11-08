"""Drawing-only combined scores for the canonical vessel table."""
from __future__ import annotations

import numpy as np

from .vessel_model import VesselTable, StationRow, waterline_grid
from . import view_measure
from .whole_vessel_score import score_table


def measurement_table(table: VesselTable):
    rows = [np.asarray(row.points_yz_m, dtype=float) for row in table.stations]
    return view_measure.VesselTable(
        [r.id for r in table.stations], np.asarray([r.x_m for r in table.stations]),
        [f"wl{i + 1:02d}" for i in range(len(table.waterlines_z_m))],
        np.asarray(table.waterlines_z_m), table.cells(),
        np.asarray([r.keel_z_m for r in table.stations]), np.asarray([r.top_z_m for r in table.stations]), rows)


def current_table(tools):
    existing = tools.state.get("vessel_table")
    if existing:
        table = VesselTable.from_json(existing)
        for row in table.stations:
            curve = tools._section_curve(row.id)
            if curve is not None and (row.id in tools.state.get("authored_sections", {}) or row.id in tools.state.get("model_choices", {})):
                row.points_yz_m = curve
                row.keel_z_m, row.top_z_m = curve[0][1], curve[-1][1]
        return table
    rows = []
    for section in tools.spec["sections"]:
        curve = tools._section_curve(section["id"])
        if curve:
            rows.append(StationRow(section["id"], section["x_m"], curve, "fitted"))
    return VesselTable(rows, waterline_grid(rows)) if rows else None


def score(tools, table=None):
    table = table or current_table(tools)
    if table is None:
        return {"combined_fit": None, "cells": [], "station_ink_fit": {}}
    image, _, _ = tools._source()
    grey = image[..., :3].mean(axis=2) if image.ndim == 3 else image
    half_beam = tools.state.get("score_half_beam_m")
    if half_beam is None:
        half_beam = max(float(np.max(np.asarray(row.points_yz_m)[:, 0])) for row in table.stations)
        tools.state["score_half_beam_m"] = max(half_beam, .001)
    return score_table(measurement_table(table), view_measure.views_from_spec(tools.spec), grey,
                       half_beam_m=tools.state["score_half_beam_m"], overlays=False)
