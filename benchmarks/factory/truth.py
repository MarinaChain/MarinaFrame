"""Sealed truth tables and the scorer for factory cases.

Metric definitions are those of docs/BENCHMARK_GUNNERUS.md section 3, implemented with the same
functions (``benchmarks.gunnerus.hull_metrics``): outer half-breadth, even-odd occupied width,
section area below the draft, volume and waterplane area by the trapezoid rule over one x grid for
truth and reconstruction. Two things are scaled to the hull, because the factory has hulls of
different depth (all hulls have length 100 m):

- height grid: ``Z_STEPS`` equal steps from z = 0 to just below the hull top
  (z_k = depth * k / Z_STEPS, k = 0 ... Z_STEPS - 1; the top point itself is excluded, as the half-open
  crossing rule gives no crossing at the top height);
- x grid: truth cuts every 0.5 m. "Between stations" is every truth cut inside the reconstruction.

Design draft T = ``DRAFT_FRACTION`` x depth (z_150 of the grid). Truth never enters inference input.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from benchmarks.gunnerus.hull_metrics import (area_below, cut_mesh, half_breadth_errors, mesh_triangles,
                                              mesh_volume, tabulate, width_at)

X_STEP_M = 0.5
Z_STEPS = 250
DRAFT_INDEX = 150  # z_150 = 0.6 depth
DRAFT_FRACTION = DRAFT_INDEX / Z_STEPS
STATION_CUT_OFFSET_M = 1.0e-4
RECON_MESH_DEFLECTION_MM = 0.1


def grids(length_m: float, depth_m: float) -> tuple[np.ndarray, np.ndarray]:
    x = np.round(np.arange(0, int(np.floor(length_m / X_STEP_M + 1e-9)) + 1) * X_STEP_M, 6)
    z = np.round(np.arange(Z_STEPS) * depth_m / Z_STEPS, 9)
    return x, z


def station_positions(length_m: float, fractions) -> list[float]:
    """Station x on the truth grid (nearest 0.5 m)."""
    return [round(round(f * length_m / X_STEP_M) * X_STEP_M, 6) for f in fractions]


def build_truth(hull, path: Path) -> dict:
    """Cut the hull mesh on the common grids and save the table (the sealed truth of one hull)."""
    x, z = grids(hull.length_m, hull.depth_m)
    triangles = hull.triangles
    bounds = (triangles[:, :, 0].min(axis=1), triangles[:, :, 0].max(axis=1))
    table = tabulate([cut_mesh(triangles, float(v), bounds) for v in x], x, z)
    draft = float(z[DRAFT_INDEX])
    area = area_below(table, draft)
    waterline = width_at(table, draft)
    record = {"hull_id": hull.hull_id, "length_m": hull.length_m, "depth_m": hull.depth_m, "max_half_breadth_m": hull.max_half_breadth_m, "draft_m": draft,
              "volume_below_draft_m3": float(np.trapezoid(area, x)),
              "waterplane_area_m2": float(np.trapezoid(waterline, x)),
              "mesh_deflection_m": hull.provenance.get("mesh_deflection_m"), "x_step_m": X_STEP_M, "z_steps": Z_STEPS}
    path.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(path, x_m=x, z_m=z, half_breadth=table.half_breadth, width=table.width,
                        record=json.dumps(record))
    return record


def load_truth(path: Path):
    data = np.load(path, allow_pickle=False)
    from benchmarks.gunnerus.hull_metrics import SectionTable

    table = SectionTable(data["x_m"], data["z_m"], data["half_breadth"], data["width"], np.zeros(len(data["x_m"])))
    return table, json.loads(str(data["record"]))


def _band(z, low, high):
    return (z >= low - 1e-12) & (z <= high + 1e-12)


def _bottom(half_breadth, z):
    hit = np.flatnonzero(half_breadth > 0)
    return float(z[hit[0]]) if len(hit) else None


def _integrate(x, values):
    return float(np.trapezoid(values, x)) if len(x) >= 2 else 0.0


def read_shape(path: Path):
    from OCP.STEPControl import STEPControl_Reader

    reader = STEPControl_Reader()
    reader.ReadFile(str(path))
    reader.TransferRoots()
    return reader.OneShape()


def score_model(truth_path: Path, model_path: Path | None, stations: list[dict]) -> dict:
    """Score one reconstruction (STEP, millimetres) against its hull's truth table."""
    table, record = load_truth(truth_path)
    x_truth, z = table.x_m, table.z_m
    draft, depth = record["draft_m"], record["depth_m"]
    bands = {"main": (None, float(z[-1])), "below_draft": (None, draft)}
    truth_area = area_below(table, draft)
    truth_waterline = width_at(table, draft)
    result = {"truth": record, "stations_requested": [s["id"] for s in stations]}
    if model_path is None:
        result["status"] = "no_model"
        return result
    triangles = mesh_triangles(read_shape(model_path), RECON_MESH_DEFLECTION_MM)
    bounds = (triangles[:, :, 0].min(axis=1), triangles[:, :, 0].max(axis=1))
    x_lo, x_hi = float(bounds[0].min()), float(bounds[1].max())
    result["reconstruction_x_range_m"] = [x_lo, x_hi]
    result["reconstruction_mesh_volume_m3"] = mesh_volume(triangles)

    def recon_table(xs):
        inward = [min(max(v, x_lo + STATION_CUT_OFFSET_M), x_hi - STATION_CUT_OFFSET_M) for v in xs]
        return tabulate([cut_mesh(triangles, v, bounds) for v in inward], inward, z)

    def truth_index(v):
        index = int(np.argmin(np.abs(x_truth - v)))
        if abs(x_truth[index] - v) > 1e-6:
            raise ValueError(f"Station x={v} is not on the truth grid.")
        return index

    station_table = recon_table([float(s["x_m"]) for s in stations])
    entries = []
    for k, station in enumerate(stations):
        index = truth_index(float(station["x_m"]))
        truth_hb, recon_hb = table.half_breadth[index], station_table.half_breadth[k]
        bottom = _bottom(truth_hb, z)
        entry = {"id": station["id"], "x_m": float(station["x_m"]), "truth_bottom_z_m": bottom}
        for name, (_, high) in bands.items():
            start = bottom if bottom is not None else 0.0
            mask = _band(z, start, high)
            entry[f"half_breadth_{name}"] = half_breadth_errors(truth_hb[mask], recon_hb[mask], z[mask]) if mask.any() else None
        below = z <= draft
        t_area = float(np.trapezoid(table.width[index][below], z[below]))
        r_area = float(np.trapezoid(station_table.width[k][below], z[below]))
        entry["section_area_below_draft"] = {"truth_m2": t_area, "reconstruction_m2": r_area, "error_m2": r_area - t_area,
                                             "relative": (r_area - t_area) / t_area if t_area > 0 else None}
        entries.append(entry)
    result["stations"] = entries

    inside = [float(v) for v in x_truth if x_lo < v < x_hi]
    dense = recon_table(inside) if inside else None
    errors = []
    for k, v in enumerate(inside):
        index = truth_index(v)
        bottom = _bottom(table.half_breadth[index], z)
        mask = _band(z, bottom if bottom is not None else 0.0, bands["main"][1])
        if mask.any():
            error = dense.half_breadth[k][mask] - table.half_breadth[index][mask]
            errors.append((v, float(np.sqrt(np.mean(error ** 2))), float(np.max(np.abs(error)))))
    result["between_station_half_breadth_main"] = {
        "stations": len(errors),
        "rms_of_station_rms_m": float(np.sqrt(np.mean([e[1] ** 2 for e in errors]))) if errors else None,
        "max_abs_m": float(max(e[2] for e in errors)) if errors else None}

    grid = np.array([x_lo + STATION_CUT_OFFSET_M] + inside + [x_hi - STATION_CUT_OFFSET_M])
    recon_grid = recon_table(list(grid))
    recon_volume = _integrate(grid, area_below(recon_grid, draft))
    recon_waterplane = _integrate(grid, width_at(recon_grid, draft))
    truth_volume_in = _integrate(grid, np.interp(grid, x_truth, truth_area))
    truth_waterplane_in = _integrate(grid, np.interp(grid, x_truth, truth_waterline))
    tv, tw = record["volume_below_draft_m3"], record["waterplane_area_m2"]
    result["hydrostatics_at_design_draft"] = {
        "draft_m": draft, "truth_volume_m3": tv, "truth_volume_within_range_m3": truth_volume_in,
        "reconstruction_volume_m3": recon_volume,
        "volume_error_relative_full": (recon_volume - tv) / tv,
        "volume_error_relative_within_range": (recon_volume - truth_volume_in) / truth_volume_in if truth_volume_in else None,
        "truth_waterplane_m2": tw, "truth_waterplane_within_range_m2": truth_waterplane_in,
        "reconstruction_waterplane_m2": recon_waterplane,
        "waterplane_error_relative_full": (recon_waterplane - tw) / tw if tw else None,
        "waterplane_error_relative_within_range": (recon_waterplane - truth_waterplane_in) / truth_waterplane_in
        if truth_waterplane_in else None}
    summary = {}
    for name in bands:
        values = [s[f"half_breadth_{name}"] for s in entries if s[f"half_breadth_{name}"] is not None]
        if values:
            summary[f"half_breadth_{name}"] = {
                "stations": len(values), "rms_of_station_rms_m": float(np.sqrt(np.mean([v["rms_m"] ** 2 for v in values]))),
                "median_station_rms_m": float(np.median([v["rms_m"] for v in values])),
                "max_abs_m": float(max(v["max_abs_m"] for v in values))}
    areas = [s["section_area_below_draft"]["relative"] for s in entries if s["section_area_below_draft"]["relative"] is not None]
    if areas:
        summary["section_area_below_draft_relative"] = {"stations": len(areas), "mean_abs": float(np.mean(np.abs(areas))),
                                                        "max_abs": float(np.max(np.abs(areas)))}
    result["summary"] = summary
    result["status"] = "scored"
    return result
