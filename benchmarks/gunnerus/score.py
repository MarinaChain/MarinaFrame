"""Score a reconstructed hull against a cached truth section table.

Inputs: the truth cache (truth_sections.npz + truth_hydrostatics.json from
truth_cache.py), a reconstructed solid (``model.brep`` or ``model.step``, in
millimetres), the list of input stations (id, x_m, status) and a metric
configuration (height grid, bands, design draft). Output: ``score.json`` and
``station_comparison.png``. Definitions: docs/BENCHMARK_GUNNERUS.md.

Truth and reconstruction are both cut as triangle meshes on the same x and z
grids, and volumes and waterplane areas of both are integrated from those
sections with the same rule, so the integration method is common to both.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np

from .hull_metrics import (area_below, cut_mesh, half_breadth_errors, mesh_triangles, mesh_volume, tabulate_union,
                           tabulate, width_at)
from .truth_cache import load_sections, read_brep

# Reconstruction cuts at a terminal station are moved this far into the hull so
# the cut never lies in a flat terminal cap.
STATION_CUT_OFFSET_M = 1.0e-4
# Chord deflection for meshing the reconstruction (ruled panels, nearly planar).
RECON_MESH_DEFLECTION_MM = 0.1


def read_shape(path: Path):
    if path.suffix.lower() in (".step", ".stp"):
        from OCP.STEPControl import STEPControl_Reader
        reader = STEPControl_Reader()
        reader.ReadFile(str(path))
        reader.TransferRoots()
        return reader.OneShape()
    return read_brep(path)


def _band(z: np.ndarray, low: float, high: float) -> np.ndarray:
    return (z >= low - 1e-12) & (z <= high + 1e-12)


def _bottom(half_breadth: np.ndarray, z: np.ndarray) -> float | None:
    hit = np.flatnonzero(half_breadth > 0)
    return float(z[hit[0]]) if len(hit) else None


def _integrate(x: np.ndarray, values: np.ndarray) -> float:
    return float(np.trapezoid(values, x)) if len(x) >= 2 else 0.0


def score(truth_dir: Path, model_path: Path | None, stations: list[dict], metric: dict, out: Path, *,
          union_cuts: bool = True) -> dict:
    """Score one model. ``union_cuts`` (round 2 default) measures each
    reconstruction cut as the union of cuts 0.1 um aft and forward of the
    plane, so a region solid that ends on a station plane is counted there.
    ``union_cuts=False`` reproduces the round 1 scorer (one cut 0.1 um forward)."""
    x_truth, truth_cuts = load_sections(truth_dir / "truth_sections.npz")
    hydro = json.loads((truth_dir / "truth_hydrostatics.json").read_text())
    z = np.round(np.arange(metric["z_min_m"], metric["z_max_m"] + 1e-9, metric["z_step_m"]), 6)
    draft = metric["design_draft_m"]
    bands = metric["bands"]
    truth_table = tabulate(truth_cuts, x_truth, z)
    truth_area = area_below(truth_table, draft)
    truth_waterline = width_at(truth_table, draft)
    result = {"metric": metric, "truth_sections_sha256": hydro["sections_sha256"], "union_cuts": union_cuts,
              "stations_read": [s["id"] for s in stations if s.get("status") == "read"],
              "stations_not_read": [s for s in stations if s.get("status") != "read"],
              "truth_volume_below_draft_m3": _integrate(x_truth, truth_area),
              "truth_waterplane_area_m2": _integrate(x_truth, truth_waterline),
              "stations": []}
    out.mkdir(parents=True, exist_ok=True)
    if model_path is None:
        result["status"] = "no_model"
        (out / "score.json").write_text(json.dumps(result, indent=2) + "\n")
        return result
    result["model_sha256"] = hashlib.sha256(model_path.read_bytes()).hexdigest()
    triangles = mesh_triangles(read_shape(model_path), RECON_MESH_DEFLECTION_MM)
    bounds = (triangles[:, :, 0].min(axis=1), triangles[:, :, 0].max(axis=1))
    x_lo, x_hi = float(bounds[0].min()), float(bounds[1].max())
    result["reconstruction_x_range_m"] = [x_lo, x_hi]
    result["reconstruction_mesh_volume_m3"] = mesh_volume(triangles)

    def recon_table(xs: list[float]):
        inward = [min(max(x, x_lo + STATION_CUT_OFFSET_M), x_hi - STATION_CUT_OFFSET_M) for x in xs]
        if not union_cuts:
            return tabulate([cut_mesh(triangles, x, bounds) for x in inward], inward, z)
        # cut_mesh moves its plane +0.1 um; these two cuts lie 0.1 um aft and forward of x.
        return tabulate_union([[cut_mesh(triangles, x - 2.0e-7, bounds), cut_mesh(triangles, x, bounds)]
                               for x in inward], inward, z)

    def truth_index(x: float) -> int:
        index = int(np.argmin(np.abs(x_truth - x)))
        if abs(x_truth[index] - x) > 1e-6:
            raise ValueError(f"Station x={x} is not on the truth grid.")
        return index

    # 1. Per input station.
    plot_data = []
    read = [s for s in stations if s.get("status") == "read"]
    station_recon = recon_table([float(s["x_m"]) for s in read]) if read else None
    for k, station in enumerate(read):
        x = float(station["x_m"])
        index = truth_index(x)
        truth_hb, recon_hb = truth_table.half_breadth[index], station_recon.half_breadth[k]
        bottom = _bottom(truth_hb, z)
        entry = {"id": station["id"], "x_m": x, "truth_bottom_z_m": bottom}
        for name, (low, high) in bands.items():
            start = (bottom if bottom is not None else metric["z_min_m"]) if low == "truth_bottom" else low
            mask = _band(z, start, high)
            # The truth hull can start above a band (bow top); the band is then empty.
            entry[f"half_breadth_{name}"] = (half_breadth_errors(truth_hb[mask], recon_hb[mask], z[mask])
                                             if mask.any() else None)
        below = z <= draft
        t_area = float(np.trapezoid(truth_table.width[index][below], z[below]))
        r_area = float(np.trapezoid(station_recon.width[k][below], z[below]))
        entry["section_area_below_draft"] = {"truth_m2": t_area, "reconstruction_m2": r_area,
                                             "error_m2": r_area - t_area,
                                             "relative": (r_area - t_area) / t_area if t_area > 0 else None}
        result["stations"].append(entry)
        plot_data.append((station["id"], x, truth_hb, recon_hb))

    # 2. Between stations: every n-th truth station inside the reconstruction.
    every = int(metric.get("dense_every_truth_station", 5))
    inside = [float(x) for x in x_truth if x_lo < x < x_hi]
    dense_x = inside[::every]
    dense = recon_table(dense_x) if dense_x else None
    low, high = bands["main"]
    dense_errors = []
    for k, x in enumerate(dense_x):
        index = truth_index(x)
        bottom = _bottom(truth_table.half_breadth[index], z)
        start = (bottom if bottom is not None else metric["z_min_m"]) if low == "truth_bottom" else low
        mask = _band(z, start, high)
        if not mask.any():
            continue
        error = dense.half_breadth[k][mask] - truth_table.half_breadth[index][mask]
        dense_errors.append((x, float(np.sqrt(np.mean(error ** 2))), float(np.max(np.abs(error)))))
    result["between_station_half_breadth_main"] = {
        "stations": len(dense_errors),
        "rms_of_station_rms_m": float(np.sqrt(np.mean([e[1] ** 2 for e in dense_errors]))) if dense_errors else None,
        "max_abs_m": float(max(e[2] for e in dense_errors)) if dense_errors else None,
        "x_at_max_m": float(max(dense_errors, key=lambda e: e[2])[0]) if dense_errors else None}

    # 3. Hydrostatics at the design draft, both by the same section integral.
    grid = np.array([x_lo + STATION_CUT_OFFSET_M] + inside + [x_hi - STATION_CUT_OFFSET_M])
    recon_grid = recon_table(list(grid))
    recon_volume = _integrate(grid, area_below(recon_grid, draft))
    recon_waterplane = _integrate(grid, width_at(recon_grid, draft))
    truth_volume_in = _integrate(grid, np.interp(grid, x_truth, truth_area))
    truth_waterplane_in = _integrate(grid, np.interp(grid, x_truth, truth_waterline))
    truth_volume, truth_waterplane = result["truth_volume_below_draft_m3"], result["truth_waterplane_area_m2"]
    result["hydrostatics_at_design_draft"] = {
        "draft_m": draft, "basis": "section integral, same x and z grids for truth and reconstruction",
        "truth_volume_m3": truth_volume, "truth_volume_within_reconstruction_range_m3": truth_volume_in,
        "reconstruction_volume_m3": recon_volume,
        "volume_error_relative_full": (recon_volume - truth_volume) / truth_volume,
        "volume_error_relative_within_range": (recon_volume - truth_volume_in) / truth_volume_in if truth_volume_in else None,
        "truth_waterplane_m2": truth_waterplane, "truth_waterplane_within_reconstruction_range_m2": truth_waterplane_in,
        "reconstruction_waterplane_m2": recon_waterplane,
        "waterplane_error_relative_full": (recon_waterplane - truth_waterplane) / truth_waterplane,
        "waterplane_error_relative_within_range": (recon_waterplane - truth_waterplane_in) / truth_waterplane_in if truth_waterplane_in else None}

    summary = {}
    for name in bands:
        values = [s[f"half_breadth_{name}"] for s in result["stations"] if s[f"half_breadth_{name}"] is not None]
        if values:
            summary[f"half_breadth_{name}"] = {
                "stations": len(values),
                "rms_of_station_rms_m": float(np.sqrt(np.mean([v["rms_m"] ** 2 for v in values]))),
                "median_station_rms_m": float(np.median([v["rms_m"] for v in values])),
                "max_abs_m": float(max(v["max_abs_m"] for v in values))}
    areas = [s["section_area_below_draft"]["relative"] for s in result["stations"]
             if s["section_area_below_draft"]["relative"] is not None]
    if areas:
        summary["section_area_below_draft_relative"] = {"stations": len(areas), "mean_abs": float(np.mean(np.abs(areas))),
                                                        "max_abs": float(np.max(np.abs(areas)))}
    result["summary"] = summary
    result["status"] = "scored"
    (out / "score.json").write_text(json.dumps(result, indent=2) + "\n")
    _plot(out, z, plot_data, metric)
    return result


def _plot(out: Path, z: np.ndarray, plot_data: list, metric: dict) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    if not plot_data:
        return
    columns = 8
    rows = int(np.ceil(len(plot_data) / columns))
    figure, axes = plt.subplots(rows, columns, figsize=(columns * 2.2, rows * 2.6), squeeze=False)
    for axis in axes.flat:
        axis.set_visible(False)
    for axis, (station_id, x, truth_hb, recon_hb) in zip(axes.flat, plot_data):
        axis.set_visible(True)
        axis.plot(truth_hb, z, "k-", lw=1.0, label="truth")
        axis.plot(recon_hb, z, "r--", lw=0.8, label="reconstruction")
        axis.axhline(metric["design_draft_m"], color="b", lw=0.4)
        axis.set_title(f"{station_id} x={x:.2f}", fontsize=7)
        axis.tick_params(labelsize=5)
    axes.flat[0].legend(fontsize=5)
    figure.tight_layout()
    figure.savefig(out / "station_comparison.png", dpi=110)
    plt.close(figure)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--truth", type=Path, required=True)
    parser.add_argument("--model", type=Path)
    parser.add_argument("--stations", type=Path, required=True, help="JSON list of {id, x_m, status}")
    parser.add_argument("--metric", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    result = score(args.truth, args.model, json.loads(args.stations.read_text()),
                   json.loads(args.metric.read_text()), args.out)
    print(json.dumps({k: result.get(k) for k in ("status", "summary", "between_station_half_breadth_main",
                                                 "hydrostatics_at_design_draft")}, indent=2))


if __name__ == "__main__":
    main()
