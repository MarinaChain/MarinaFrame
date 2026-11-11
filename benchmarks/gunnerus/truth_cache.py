"""Cut a cached truth BRep into a reduced section representation.

DATA-PRODUCTION utility. Reads ``truth_hull.brep`` (from load_truth_step.py or
a development IGES), cuts it at x = x0 + k * step (metres), and writes
``truth_sections.npz`` plus ``truth_hydrostatics.json`` with exact Boolean
volumes and waterplane areas at the requested drafts. Truth never enters
inference input.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path

import numpy as np

from .hull_metrics import (EDGE_DEFLECTION_MM, cut_mesh, cut_polylines, mesh_triangles, mesh_volume,
                           shape_volume_below)


def read_brep(path: Path):
    from OCP.BinTools import BinTools
    from OCP.BRep import BRep_Builder
    from OCP.TopoDS import TopoDS_Shape

    shape = TopoDS_Shape()
    if path.suffix == ".brep":
        BinTools.Read_s(shape, str(path))
    else:
        from OCP.BRepTools import BRepTools
        BRepTools.Read_s(shape, str(path), BRep_Builder())
    return shape


def is_closed_solid(shape) -> bool:
    from OCP.TopAbs import TopAbs_SOLID
    from OCP.TopExp import TopExp_Explorer

    return TopExp_Explorer(shape, TopAbs_SOLID).More()


def save_sections(path: Path, x_values: list[float], polylines_by_x: list[list[np.ndarray]]) -> None:
    """Store ragged polylines as flat arrays with offsets."""
    points, polyline_offsets, station_offsets = [], [0], [0]
    for polylines in polylines_by_x:
        for polyline in polylines:
            points.append(polyline)
            polyline_offsets.append(polyline_offsets[-1] + len(polyline))
        station_offsets.append(len(polyline_offsets) - 1)
    flat = np.vstack(points) if points else np.zeros((0, 2))
    np.savez_compressed(path, x_m=np.asarray(x_values), points=flat,
                        polyline_offsets=np.asarray(polyline_offsets),
                        station_offsets=np.asarray(station_offsets))


def load_sections(path: Path) -> tuple[np.ndarray, list[list[np.ndarray]]]:
    data = np.load(path)
    points, poff, soff = data["points"], data["polyline_offsets"], data["station_offsets"]
    result = []
    for s in range(len(data["x_m"])):
        result.append([points[poff[p]:poff[p + 1]] for p in range(soff[s], soff[s + 1])])
    return data["x_m"], result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--brep", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--x-start", type=float, required=True)
    parser.add_argument("--x-stop", type=float, required=True)
    parser.add_argument("--step", type=float, default=0.05)
    parser.add_argument("--draft", type=float, action="append", default=[])
    parser.add_argument("--mesh-deflection-mm", type=float, default=None,
                        help="Cut a tessellation with this chord deflection instead of the exact surfaces.")
    args = parser.parse_args()
    shape = read_brep(args.brep)
    count = int(round((args.x_stop - args.x_start) / args.step)) + 1
    xs = [round(args.x_start + k * args.step, 6) for k in range(count)]
    started = time.perf_counter()
    args.out.mkdir(parents=True, exist_ok=True)
    record = {"brep": args.brep.name, "brep_sha256": hashlib.sha256(args.brep.read_bytes()).hexdigest(),
              "x_start_m": args.x_start, "x_stop_m": args.x_stop, "step_m": args.step, "stations": len(xs)}
    if args.mesh_deflection_mm is not None:
        triangles = mesh_triangles(shape, args.mesh_deflection_mm)
        np.savez_compressed(args.out / "truth_mesh.npz", triangles=triangles.astype(np.float32))
        record.update(method="tessellation_cut", mesh_deflection_mm=args.mesh_deflection_mm,
                      mesh_triangles=int(len(triangles)), mesh_volume_m3=mesh_volume(triangles),
                      mesh_seconds=time.perf_counter() - started)
        print(json.dumps(record), flush=True)
        bounds = (triangles[:, :, 0].min(axis=1), triangles[:, :, 0].max(axis=1))
        cut = lambda x: cut_mesh(triangles, x, bounds)  # noqa: E731
    else:
        record.update(method="exact_surface_cut", edge_deflection_mm=EDGE_DEFLECTION_MM)
        cut = lambda x: cut_polylines(shape, x)  # noqa: E731
    cuts = []
    for index, x in enumerate(xs):
        cuts.append(cut(x))
        if index % 50 == 0:
            print(f"cut {index + 1}/{len(xs)} x={x:.3f} pieces={len(cuts[-1])} t={time.perf_counter() - started:.0f}s", flush=True)
    save_sections(args.out / "truth_sections.npz", xs, cuts)
    hydro = {}
    exact = is_closed_solid(shape) and args.mesh_deflection_mm is None
    for draft in args.draft:
        if exact:
            volume, waterplane = shape_volume_below(shape, draft)
            hydro[f"{draft:.3f}"] = {"volume_m3": volume, "waterplane_area_m2": waterplane}
        else:
            # Open surfaces have no Boolean volume; very large models are
            # integrated from their sections instead (see score.py).
            hydro[f"{draft:.3f}"] = None
    record.update(seconds=time.perf_counter() - started, exact_boolean=hydro,
                  sections_sha256=hashlib.sha256((args.out / "truth_sections.npz").read_bytes()).hexdigest())
    (args.out / "truth_hydrostatics.json").write_text(json.dumps(record, indent=2) + "\n")
    print(json.dumps(record, indent=2))


if __name__ == "__main__":
    main()
