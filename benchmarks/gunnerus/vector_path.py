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


# build_hull approximates each section within a vertical bound and shares one
# knot set across all its sections, capped at 513 knots. Many real sections
# exceed that cap, so (as its error message advises) the job is split into
# consecutive groups that share their boundary station. Each group is as long
# as fits at the 1 mm default bound; a pair of stations that does not fit even
# alone uses the smallest larger bound that fits, up to the 10 mm maximum.
CAD_DEVIATION_LADDER_M = (0.001, 0.002, 0.005, 0.010)


def _fits(group: list[dict], bound: float) -> bool:
    from vessel_reconstruction.geometry import normalize_sections

    try:
        normalize_sections(group, max_deviation_m=bound)
        return True
    except GeometryError as exc:
        if "complexity limit" in str(exc):
            return False
        raise


def plan_groups(sections: list[dict]) -> list[tuple[list[dict], float]]:
    """Consecutive groups of at least three stations, sharing end stations.

    build_hull needs three or more sections, so groups are cut at indices
    0 = c0 < c1 < ... < ck = n-1 with every gap >= 2. Each group is grown as long
    as it fits at its bound; if the stations left after a cut would be fewer
    than two, the cut moves back by one.
    """
    n = len(sections)
    if n < 3:
        raise GeometryError("At least three read stations are required.")
    groups, start = [], 0
    while start < n - 1:
        end = min(start + 2, n - 1)
        if end - start < 2:  # cannot happen when every cut leaves >= 2 gaps
            raise GeometryError("Group planning left fewer than three stations.")
        bound = next((b for b in CAD_DEVIATION_LADDER_M if _fits(sections[start:end + 1], b)), None)
        if bound is None:
            raise GeometryError(f"Stations {sections[start]['id']}-{sections[end]['id']} exceed the knot limit at 10 mm.")
        while end + 1 < n and _fits(sections[start:end + 2], bound):
            end += 1
        if 0 < n - 1 - end < 2:
            if end - start > 2:
                end -= 1  # leave at least two gaps for the final group
            else:
                # Three stations, one left over: take it in at the smallest bound that fits.
                end = n - 1
                bound = next((b for b in CAD_DEVIATION_LADDER_M if _fits(sections[start:end + 1], b)), None)
                if bound is None:
                    raise GeometryError("The last four stations exceed the knot limit at 10 mm.")
        groups.append((sections[start:end + 1], bound))
        start = end
    return groups


def _build_regions(sections: list[dict], out: Path) -> dict:
    """Region mode: one build_region_hull call over every read station.

    It splits long runs itself; the first CAD bound on the ladder at which
    every run fits is used.
    """
    from OCP.BinTools import BinTools
    from vessel_reconstruction.geometry import build_region_hull

    error = None
    for bound in CAD_DEVIATION_LADDER_M:
        try:
            shape, report = build_region_hull(sections, max_deviation_m=bound)
        except GeometryError as exc:
            error = str(exc)
            if "complexity limit" in error:
                continue
            break
        BinTools.Write_s(shape.wrapped, str(out / "model.brep"))
        (out / "region_report.json").write_text(json.dumps(report, indent=1) + "\n")
        xs = [s["x_m"] for s in sections]
        return {"status": "built", "build_error": None, "model_sha256": _sha256(out / "model.brep"),
                "x_range_m": [float(min(xs)), float(max(xs))], "max_cad_deviation_m": report["maximum_half_breadth_deviation_m"],
                "cad_bound_m": bound, "solid_count": report["solid_count"], "volume_m3": report["volume_m3"],
                "region_runs": len(report["runs"]), "unlofted_regions": report["unlofted_regions"],
                "region_counts": {s["id"]: len(s["regions"]) for s in report["stations"]}}
    return {"status": "blocked", "build_error": error}


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
    use_regions = bool(config.get("regions", False))
    started = time.perf_counter()
    read = lines_dxf.read_stations(dxf_path, view, requests,
                                   pick_tolerance=config.get("pick_tolerance", 5.0), side_line=side_line,
                                   regions=use_regions,
                                   centreline_closure_m=config.get("centreline_closure_m", 0.002))
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
    if use_regions:
        summary.update(_build_regions(read["sections"], out))
        summary["seconds"] = time.perf_counter() - started
        (out / "vector_run.json").write_text(json.dumps(summary, indent=2) + "\n")
        return summary
    try:
        from OCP.BinTools import BinTools
        from OCP.BRep import BRep_Builder
        from OCP.TopoDS import TopoDS_Compound
        from vessel_reconstruction.geometry import build_hull

        groups = plan_groups(sorted(read["sections"], key=lambda s: s["x_m"]))
        summary["groups"] = [{"stations": [s["id"] for s in g], "max_deviation_m": bound} for g, bound in groups]
        compound = TopoDS_Compound()
        builder = BRep_Builder()
        builder.MakeCompound(compound)
        deviations = []
        for group, bound in groups:
            shape, normalized = build_hull(group, max_deviation_m=bound)
            builder.Add(compound, shape.wrapped)
            deviations.extend(s["cad_approximation"]["maximum_half_breadth_deviation_m"] for s in normalized)
        BinTools.Write_s(compound, str(out / "model.brep"))
        summary.update(status="built", model_sha256=_sha256(out / "model.brep"),
                       x_range_m=[float(groups[0][0][0]["x_m"]), float(groups[-1][0][-1]["x_m"])],
                       max_cad_deviation_m=float(max(deviations)))
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
