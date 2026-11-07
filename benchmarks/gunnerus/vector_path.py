"""Vector path: DXF body-plan stations -> MarinaFrame half-sections -> CAD.

Reads a station configuration (JSON), extracts the station curves with
``vessel_reconstruction.lines_dxf``, builds the hull with the production
``geometry.build_hull`` (ruled panels, flat terminal caps) and writes:

- ``sections.json``: the half-sections given to build_hull, with evidence;
- ``abstentions.json``: stations that were refused, with the reason;
- ``model.brep``: the built solid in millimetres (truth-free);
- ``vector_run.json``: summary with hashes.

This measures the build/loft stage on vector input. It never reads truth.

Configuration keys: ``dxf`` (path, relative to the config file), ``view``
(BodyPlanView fields), ``stations`` (list of StationRequest fields), optional
``side_line`` (SideLine fields): the drawn vertical side line that station
curves end on; it is followed up to its declared top.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path

from vessel_reconstruction import lines_dxf
from vessel_reconstruction.errors import GeometryError


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(config_path: Path, out: Path) -> dict:
    config = json.loads(config_path.read_text())
    dxf_path = (config_path.parent / config["dxf"]).resolve()
    view_fields = dict(config["view"])
    view_fields["bounds"] = tuple(view_fields["bounds"])
    view_fields["layers"] = tuple(view_fields["layers"])
    view = lines_dxf.BodyPlanView(**view_fields)
    requests = []
    for item in config["stations"]:
        fields = dict(item)
        if fields.get("pick_xy") is not None:
            fields["pick_xy"] = tuple(fields["pick_xy"])
        fields["extra_picks"] = tuple(tuple(p) for p in fields.get("extra_picks", ()))
        requests.append(lines_dxf.StationRequest(**fields))
    side_line = lines_dxf.SideLine(**config["side_line"]) if config.get("side_line") else None
    started = time.perf_counter()
    read = lines_dxf.read_stations(dxf_path, view, requests,
                                   pick_tolerance=config.get("pick_tolerance", 5.0), side_line=side_line)
    extended = [s["id"] for s in read["sections"] if s["evidence"]["side_line_followed"]]
    out.mkdir(parents=True, exist_ok=False)
    (out / "sections.json").write_text(json.dumps(read["sections"]) + "\n")
    (out / "abstentions.json").write_text(json.dumps(read["abstentions"], indent=2) + "\n")
    statuses = ([{"id": s["id"], "x_m": s["x_m"], "status": "read"} for s in read["sections"]]
                + [{"id": a["id"], "x_m": a["x_m"], "status": "abstained", "kind": a["kind"]}
                   for a in read["abstentions"]])
    (out / "stations.json").write_text(json.dumps(sorted(statuses, key=lambda s: s["x_m"]), indent=2) + "\n")
    summary = {"config": config_path.name, "config_sha256": _sha256(config_path),
               "dxf_sha256": _sha256(dxf_path), "requested": len(requests),
               "read": len(read["sections"]), "abstained": len(read["abstentions"]),
               "abstention_kinds": sorted({a["kind"] for a in read["abstentions"]}),
               "side_line_extended": extended, "chain_count": read["chain_count"],
               "status": "blocked", "build_error": None}
    try:
        from OCP.BinTools import BinTools
        from vessel_reconstruction.geometry import build_hull, metrics_for

        shape, normalized = build_hull(read["sections"])
        BinTools.Write_s(shape.wrapped, str(out / "model.brep"))
        summary.update(status="built", metrics=metrics_for(shape),
                       model_sha256=_sha256(out / "model.brep"),
                       x_range_m=[float(min(s["x_m"] for s in normalized)), float(max(s["x_m"] for s in normalized))],
                       max_cad_deviation_m=float(max(s["cad_approximation"]["maximum_half_breadth_deviation_m"] for s in normalized)))
    except GeometryError as exc:
        summary["build_error"] = str(exc)
    summary["seconds"] = time.perf_counter() - started
    (out / "vector_run.json").write_text(json.dumps(summary, indent=2) + "\n")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(run(args.config, args.out), indent=2))


if __name__ == "__main__":
    main()
