"""Development cases on DTMB 5415 (never Gunnerus).

Subcommands:

``truth``      Convert the FORCE/IIHR/INSEAN 5415 IGES half-hull (model scale,
               OpenCascade millimetres) to ``truth_hull.brep``.
``synthetic``  Cut the truth at the 21 stations and write them as a DXF body
               plan (aft half drawn left of the centreline) plus a vector
               configuration. Station identity is exact by construction, so
               this case measures the DXF reader, the loft and the scorer.
``marin``      Write a vector configuration for the MARIN 5415 body-plan DXF
               (full scale, mm). Its station identity is an ORACLE: each
               curve is assigned to the truth station it matches best. The
               case measures drawing-vs-CAD agreement and loft error, not
               identity. It is development data only.

The 5415 model has LPP 5.72 m (scale 1:24.824 of the 142 m ship). Station i
is at x = i * LPP / 20 from the AP, with x forward.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

LPP_MODEL_M = 5.72
SCALE = 24.824
STATIONS = 21


def station_x(i: int) -> float:
    return round(i * LPP_MODEL_M / (STATIONS - 1), 6)


def cmd_truth(iges: Path, out: Path) -> None:
    from OCP.BinTools import BinTools
    from OCP.IFSelect import IFSelect_RetDone
    from OCP.IGESControl import IGESControl_Reader

    reader = IGESControl_Reader()
    if reader.ReadFile(str(iges)) != IFSelect_RetDone:
        raise SystemExit("cannot read IGES")
    reader.TransferRoots()
    out.mkdir(parents=True, exist_ok=True)
    BinTools.Write_s(reader.OneShape(), str(out / "truth_hull.brep"))


def cmd_synthetic(truth: Path, out: Path) -> None:
    import ezdxf
    from .hull_metrics import cut_polylines
    from .truth_cache import read_brep

    shape = read_brep(truth / "truth_hull.brep")
    doc = ezdxf.new("R2010")
    msp = doc.modelspace()
    stations = []
    for i in range(STATIONS):
        x = station_x(i)
        cuts = cut_polylines(shape, x)
        if len(cuts) != 1:
            print(f"station {i}: {len(cuts)} curves, skipped")
            continue
        curve = cuts[0]
        side = 1 if x >= LPP_MODEL_M / 2 else -1
        drawing = np.column_stack([side * curve[:, 0] * 1000.0, curve[:, 1] * 1000.0])
        msp.add_lwpolyline(drawing.tolist(), dxfattribs={"layer": "STATIONS"})
        middle = drawing[len(drawing) // 2]
        stations.append({"id": f"st{i:02d}", "x_m": x, "side": side, "pick_xy": middle.tolist(),
                         "evidence": "synthetic: station identity exact by construction"})
    out.mkdir(parents=True, exist_ok=True)
    doc.saveas(out / "bodyplan.dxf")
    config = {"dxf": "bodyplan.dxf",
              "view": {"centreline_x": 0.0, "baseline_y": 0.0, "units_per_metre": 1000.0,
                       "bounds": [-600.0, -200.0, 600.0, 800.0], "layers": ["STATIONS"],
                       "flatten_tolerance": 0.05, "join_tolerance": 0.01},
              "stations": stations, "pick_tolerance": 1.0}
    (out / "config.json").write_text(json.dumps(config, indent=2) + "\n")


def cmd_marin(truth: Path, dxf: Path, out: Path) -> None:
    import ezdxf
    from vessel_reconstruction import lines_dxf
    from .hull_metrics import outer_half_breadth
    from .truth_cache import load_sections

    view = lines_dxf.BodyPlanView(centreline_x=0.0, baseline_y=0.0, units_per_metre=1000.0 * SCALE,
                                  bounds=(-10500.0, -3200.0, 10500.0, 16500.0), layers=("HB",),
                                  flatten_tolerance=1.0, join_tolerance=1.0)
    chains = lines_dxf.chain_fragments(lines_dxf.read_view_curves(ezdxf.readfile(str(dxf)), view), 1.0)
    x_truth, cuts = load_sections(truth / "truth_sections.npz")
    z = np.arange(-0.15, 0.70, 0.002)
    candidates = {i: outer_half_breadth(cuts[int(np.argmin(np.abs(x_truth - station_x(i))))], z)
                  for i in range(STATIONS)}
    stations, used = [], set()
    for chain in chains:
        if len(chain) < 20:
            continue
        side = 1 if chain[:, 0].mean() > 0 else -1
        try:
            half = lines_dxf.single_valued_section(lines_dxf.to_half_section_m(chain, view, side))
        except lines_dxf.LinesDxfError:
            continue
        inside = (z >= half[0, 1]) & (z <= half[-1, 1])
        if inside.sum() < 20:
            continue
        hb = np.interp(z[inside], half[:, 1], half[:, 0])
        errors = {i: float(np.sqrt(np.mean((hb - c[inside]) ** 2))) for i, c in candidates.items()}
        best = min(errors, key=errors.get)
        if best in used or errors[best] > 0.01:
            continue
        used.add(best)
        middle = chain[len(chain) // 2]
        stations.append({"id": f"st{best:02d}", "x_m": station_x(best), "side": side,
                         "pick_xy": middle.tolist(),
                         "evidence": f"ORACLE identity: best truth match, rms {errors[best]:.4f} m"})
    out.mkdir(parents=True, exist_ok=True)
    config = {"dxf": str(dxf.resolve()), "view": {**view.__dict__, "bounds": list(view.bounds), "layers": list(view.layers)},
              "stations": sorted(stations, key=lambda s: s["x_m"]), "pick_tolerance": 2.0}
    (out / "config.json").write_text(json.dumps(config, indent=2) + "\n")
    print(f"{len(stations)} stations identified: {[s['id'] for s in config['stations']]}")


def cmd_raster_pdf(truth: Path, out: Path, stations: list[int], grid: bool = True) -> None:
    """Draw chosen truth stations as a body plan PDF with black BT/WL grid lines.

    Paper scale 1:5 (200 mm per model metre). Stations forward of midships are
    drawn right of the centreline, the others left (mirrored), as on a lines plan.
    The 5415 x axis runs aft from the FP, so station i < 10 is forward.
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from .hull_metrics import cut_polylines
    from .truth_cache import read_brep

    shape = read_brep(truth / "truth_hull.brep")
    width_m, z_lo, z_hi = 0.5, -0.15, 0.70
    figure = plt.figure(figsize=(2 * width_m * 200 / 25.4, (z_hi - z_lo) * 200 / 25.4))
    axis = figure.add_axes([0, 0, 1, 1])
    axis.set_xlim(-width_m, width_m)
    axis.set_ylim(z_lo, z_hi)
    axis.axis("off")
    for y in np.arange(-0.4, 0.41, 0.1):
        if grid or abs(y) < 1e-9:  # the centreline is always drawn
            axis.plot([y, y], [z_lo + 0.02, z_hi - 0.02], "k-", lw=0.5 if abs(y) > 1e-9 else 0.8)
    for z in np.arange(0.0, 0.61, 0.1):
        if grid or abs(z) < 1e-9:  # the baseline is always drawn
            axis.plot([-0.45, 0.45], [z, z], "k-", lw=0.5)
    for i in stations:
        cuts = cut_polylines(shape, station_x(i))
        side = 1 if i < 10 else -1
        for curve in cuts:
            axis.plot(side * curve[:, 0], curve[:, 1], "k-", lw=0.8)
    out.mkdir(parents=True, exist_ok=True)
    figure.savefig(out / "bodyplan.pdf")
    plt.close(figure)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["truth", "synthetic", "marin", "raster-pdf"])
    parser.add_argument("--stations", type=int, nargs="*", default=[])
    parser.add_argument("--no-grid", action="store_true", help="raster-pdf: draw only centreline and baseline")
    parser.add_argument("--iges", type=Path)
    parser.add_argument("--dxf", type=Path)
    parser.add_argument("--truth", type=Path, required=True)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    if args.command == "truth":
        cmd_truth(args.iges, args.truth)
    elif args.command == "synthetic":
        cmd_synthetic(args.truth, args.out)
    elif args.command == "raster-pdf":
        cmd_raster_pdf(args.truth, args.out, args.stations, grid=not args.no_grid)
    else:
        cmd_marin(args.truth, args.dxf, args.out)


if __name__ == "__main__":
    main()
