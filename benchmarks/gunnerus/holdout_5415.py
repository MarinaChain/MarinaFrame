"""Round 2 held-out evaluation on DTMB 5415 (never used to tune round 2 code).

The method is fixed before any run (docs/BENCHMARK_GUNNERUS.md section 7.6):

``synthetic``  Cut the 5415 truth at the 21 stations and write EVERY cut curve
               of a station as one piece of that station in a DXF body plan
               (round 1 skipped stations with more than one curve). Identity is
               exact by construction. Read in region mode.
``marin``      The MARIN 5415 body plan with the round 1 oracle identity
               configuration (dev_5415.cmd_marin), read once in single-curve
               mode (round 1 reader) and once in region mode.

``run`` reads, builds and scores one configuration with the development
metric (benchmarks/gunnerus/config/metric_dev5415.json). Outputs stay in the
git-ignored work/ folder.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from .dev_5415 import LPP_MODEL_M, STATIONS, station_x


def cmd_synthetic(truth: Path, out: Path) -> None:
    import ezdxf
    from .hull_metrics import cut_polylines
    from .truth_cache import read_brep

    shape = read_brep(truth / "truth_hull.brep")
    doc = ezdxf.new("R2010")
    stations = []
    for i in range(STATIONS):
        x = station_x(i)
        side = 1 if x >= LPP_MODEL_M / 2 else -1
        picks = []
        for curve in cut_polylines(shape, x):
            if len(curve) < 3:
                continue
            drawing = np.column_stack([side * curve[:, 0] * 1000.0, curve[:, 1] * 1000.0])
            doc.modelspace().add_lwpolyline(drawing.tolist(), dxfattribs={"layer": "STATIONS"})
            picks.append(drawing[len(drawing) // 2].tolist())
        if picks:
            stations.append({"id": f"st{i:02d}", "x_m": x, "side": side, "pick_xy": picks[0],
                             "extra_picks": picks[1:],
                             "evidence": f"synthetic: identity exact by construction; {len(picks)} piece(s)"})
    out.mkdir(parents=True, exist_ok=True)
    doc.saveas(out / "bodyplan.dxf")
    config = {"dxf": "bodyplan.dxf",
              "view": {"centreline_x": 0.0, "baseline_y": 0.0, "units_per_metre": 1000.0,
                       "bounds": [-600.0, -200.0, 600.0, 800.0], "layers": ["STATIONS"],
                       "flatten_tolerance": 0.05, "join_tolerance": 0.01},
              "stations": stations, "pick_tolerance": 1.0, "regions": True, "centreline_closure_m": 0.0005}
    (out / "config.json").write_text(json.dumps(config, indent=2) + "\n")


def cmd_run(config: Path, truth: Path, metric: Path, out: Path, regions: bool | None) -> dict:
    from . import score, vector_path

    data = json.loads(config.read_text())
    if regions is not None:
        data["regions"] = regions
    out.mkdir(parents=True, exist_ok=False)
    used = out / "config.json"
    used.write_text(json.dumps(data, indent=2) + "\n")
    if not Path(data["dxf"]).is_absolute():
        data["dxf"] = str((config.parent / data["dxf"]).resolve())
        used.write_text(json.dumps(data, indent=2) + "\n")
    summary = vector_path.run(used, out / "vector")
    stations = json.loads((out / "vector" / "stations.json").read_text())
    model = out / "vector" / "model.brep"
    result = score.score(truth, model if model.exists() else None, stations, json.loads(metric.read_text()),
                         out / "score")
    record = {"vector_run": {k: v for k, v in summary.items() if k not in ("region_counts",)},
              "score_status": result["status"], "summary": result.get("summary"),
              "hydrostatics": result.get("hydrostatics_at_design_draft"),
              "between": result.get("between_station_half_breadth_main")}
    (out / "holdout_record.json").write_text(json.dumps(record, indent=2, default=str) + "\n")
    return record


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["synthetic", "run"])
    parser.add_argument("--truth", type=Path, required=True)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--metric", type=Path)
    parser.add_argument("--mode", choices=["config", "single", "regions"], default="config")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "synthetic":
        cmd_synthetic(args.truth, args.out)
    else:
        regions = {"config": None, "single": False, "regions": True}[args.mode]
        print(json.dumps(cmd_run(args.config, args.truth, args.metric, args.out, regions), indent=1, default=str))


if __name__ == "__main__":
    main()
