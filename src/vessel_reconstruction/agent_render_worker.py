"""Private image/STEP observation worker for the typed agent tools.

Arguments are built exclusively by DomainTools. Limits precede parser/native
imports; the worker receives no provider credentials and executes no model code.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import resource
import time

from .resources import native_resource_profile, peak_rss_kib

# A region run (geometry.build_region_hull) is a compound whose solids end on
# station planes. Its audit cuts this far aft and forward of the station
# (0.1 micrometre, in STEP millimetres) and joins both cuts, so a solid that
# ends on the plane is cut too (as the benchmark scorer does).
REGION_CUT_OFFSET_MM = 1e-4
# Agreement required between each reimported solid volume and the engine's
# solid volume; the same bound as the whole-model metric check.
REGION_SOLID_VOLUME_TOLERANCE = 1e-6


def _reimport(run: Path):
    from .provenance import digest_file, safe_relative_file
    from .run_record import verify_run
    from .schema import load_bounded_json
    if not verify_run(run).get("valid"):
        raise ValueError("The immutable engine run does not verify.")
    record = load_bounded_json(run / "result.json", max_bytes=32 * 1024**2, max_nodes=600_000)
    if record["status"] != "review_required" or record["exports"].get("step_units") != "mm":
        raise ValueError("A verified millimetre STEP export is required.")
    path = safe_relative_file(run, record["exports"]["step"])
    import cadquery as cq
    shape = cq.importers.importStep(str(path)).val()
    bounds = shape.BoundingBox()
    metrics = {"length_m": bounds.xlen / 1000, "beam_m": bounds.ylen / 1000,
               "depth_m": bounds.zlen / 1000, "volume_m3": shape.Volume() / 1e9}
    extent_error = max(abs(metrics[k] - record["metrics"][k]) / max(abs(record["metrics"][k]), 1e-12)
                       for k in metrics)
    if "region_loft" in record["metrics"]:
        return shape, record, _region_audit(shape, record, path, metrics, extent_error)
    valid = shape.isValid() and len(shape.Solids()) == 1 and len(shape.Shells()) == 1 and shape.Shells()[0].Closed()
    if not valid or extent_error > 1e-6:
        raise ValueError("Reimported STEP topology, units, or metrics conflict with the engine record.")
    audit = {"source": "independently_reimported_exported_STEP", "step_sha256": digest_file(path),
             "step_units": "mm", "reported_units": "m", "valid_shape": bool(valid),
             "solid_count": len(shape.Solids()), "shell_count": len(shape.Shells()),
             "closed_shell": bool(shape.Shells()[0].Closed()), "metrics": metrics,
             "relative_metric_error": float(extent_error),
             "engineering_approved": False, "human_semantic_review_required": True}
    return shape, record, audit


def _region_audit(shape, record: dict, path: Path, metrics: dict, extent_error: float) -> dict:
    """Reimport audit of a region compound: every solid valid, closed and of the engine's volume.

    The solid list is sorted by volume, because STEP does not keep an order
    that the engine record could name; the engine's solid volumes are
    compared as a sorted list.
    """
    from .provenance import digest_file
    expected = record["metrics"]["solid_count"]
    solids = []
    for solid in shape.Solids():
        shells = solid.Shells()
        solids.append({"volume_m3": solid.Volume() / 1e9, "valid_shape": bool(solid.isValid()),
                       "shell_count": len(shells), "closed_shell": len(shells) == 1 and bool(shells[0].Closed())})
    solids.sort(key=lambda item: item["volume_m3"])
    engine = sorted(record["metrics"]["region_loft"]["solid_volumes_m3"])
    if len(solids) != expected or len(engine) != expected:
        raise ValueError("Reimported STEP solid count conflicts with the engine record.")
    volume_error = max(abs(item["volume_m3"] - volume) / max(volume, 1e-12) for item, volume in zip(solids, engine))
    closed = all(item["closed_shell"] for item in solids)
    valid = (shape.isValid() and closed and all(item["valid_shape"] and item["shell_count"] == 1 for item in solids)
             and len(shape.Shells()) == expected)
    if not valid or extent_error > 1e-6 or volume_error > REGION_SOLID_VOLUME_TOLERANCE:
        raise ValueError("Reimported STEP topology, units, or metrics conflict with the engine record.")
    return {"source": "independently_reimported_exported_STEP", "step_sha256": digest_file(path),
            "step_units": "mm", "reported_units": "m", "valid_shape": bool(valid),
            "solid_count": len(solids), "shell_count": len(shape.Shells()),
            "closed_shell": closed, "metrics": metrics,
            "relative_metric_error": float(extent_error),
            "expected_solid_count": expected, "solids": solids,
            "solid_volume_relative_error": float(volume_error),
            "engineering_approved": False, "human_semantic_review_required": True}


def _observed_samples(section: dict):
    """All observed samples of a section and, for a multi-piece section, each piece's share."""
    import numpy as np
    if "points_yz_m" in section:
        return np.asarray(section["points_yz_m"], dtype=float), []
    pieces = [np.asarray(piece["points_yz_m"] + piece.get("inner_points_yz_m", []), dtype=float)
              for piece in section["pieces"]]
    return np.vstack(pieces), [len(piece) for piece in pieces]


def _cut_edges(shape, x: float, regions: bool):
    """Edges of the STEP section at station x; a region compound joins cuts on both sides."""
    import cadquery as cq
    offsets = (-REGION_CUT_OFFSET_MM, REGION_CUT_OFFSET_MM) if regions else (0.0,)
    edges = []
    for offset in offsets:
        cut = cq.Workplane("YZ", origin=(x * 1000 + offset, 0, 0)).newObject([shape]).section().val()
        edges.extend(cut.Edges())
    return edges


def render_step(run: Path, view: str, out: Path):
    import numpy as np
    from PIL import Image, ImageDraw, ImageFont
    from .fonts import dejavu_sans
    from OCP.BRepMesh import BRepMesh_IncrementalMesh
    shape, record, audit = _reimport(run)
    if view not in {"body", "plan", "profile", "oblique"}:
        raise ValueError("Unsupported named view.")
    tolerance = max(.5, audit["metrics"]["beam_m"] * 1000 / 600)
    BRepMesh_IncrementalMesh(shape.wrapped, tolerance, False, .18, False)
    vectors, triangles = shape.tessellate(tolerance, .18)
    if not 0 < len(vectors) <= 150_000 or not 0 < len(triangles) <= 250_000:
        raise ValueError("Render tessellation exceeds its observation budget.")
    vertices = np.array([[v.x, v.y, v.z] for v in vectors]) / 1000
    centred = vertices - (np.min(vertices, axis=0) + np.max(vertices, axis=0)) / 2
    if view == "body":
        horizontal, vertical, depth = np.array([0, 1, 0]), np.array([0, 0, 1]), np.array([1, 0, 0])
        axes = "Horizontal: y (port/starboard); vertical: z; looking along +x"
    elif view == "plan":
        horizontal, vertical, depth = np.array([1, 0, 0]), np.array([0, 1, 0]), np.array([0, 0, 1])
        axes = "Horizontal: x (longitudinal); vertical: y; looking down from +z"
    elif view == "profile":
        horizontal, vertical, depth = np.array([1, 0, 0]), np.array([0, 0, 1]), np.array([0, 1, 0])
        axes = "Horizontal: x (longitudinal); vertical: z; starboard profile"
    else:
        horizontal = np.array([.75, -.66, 0]); horizontal /= np.linalg.norm(horizontal)
        depth = np.array([.52, .59, .62]); depth /= np.linalg.norm(depth)
        vertical = np.cross(depth, horizontal); vertical /= np.linalg.norm(vertical)
        axes = "Oblique orthographic view; longitudinal x, transverse y, vertical z"
    projection = np.c_[centred @ horizontal, centred @ vertical]
    spans = np.maximum(np.ptp(projection, axis=0), 1e-9)
    scale = min(1040 / spans[0], 590 / spans[1])
    pixels = np.c_[600 + projection[:, 0] * scale, 410 - projection[:, 1] * scale]
    canvas = Image.new("RGB", (1200, 820), "#f4f7fa")
    draw = ImageDraw.Draw(canvas)
    try:
        font = dejavu_sans(18)
        small = dejavu_sans(15)
    except OSError:
        font = small = ImageFont.load_default()
    draw.text((28, 20), "PROVISIONAL HULL | " + view.upper() + " | ACTUAL STEP REIMPORT", fill="#17344a", font=font)
    draw.text((28, 55), "Human semantic review required. Flat terminal caps / symmetry / upper closure are disclosed assumptions.", fill="#765434", font=small)
    depths = centred @ depth
    order = sorted(range(len(triangles)), key=lambda i: float(np.mean(depths[list(triangles[i])])))
    for i in order:
        tri = list(triangles[i])
        a, b, c = centred[tri]
        normal = np.cross(b - a, c - a)
        length = np.linalg.norm(normal)
        intensity = .62 + .30 * abs(float(normal @ depth) / length) if length else .6
        color = tuple(int(v * intensity) for v in (94, 156, 184))
        draw.polygon([tuple(p) for p in pixels[tri]], fill=color, outline=color)
    # Render opaque triangulated surfaces. Drawing every BRep edge over these
    # surfaces would show occluded internal/back edges as a misleading X-ray.
    audit["render_mode"] = "orthographic_depth_sorted_opaque_STEP_tessellation"
    draw.text((28, 738), axes, fill="#25465d", font=small)
    m = audit["metrics"]
    draw.text((28, 766), f"Length {m['length_m']:.5g} m  |  Beam {m['beam_m']:.5g} m  |  Depth {m['depth_m']:.5g} m  |  Volume {m['volume_m3']:.5g} m³", fill="#25465d", font=small)
    draw.text((28, 792), "STEP SHA-256 " + audit["step_sha256"], fill="#657581", font=small)
    canvas.save(out / "render.png")
    from .agent_tools import _model_observation_image
    return {"geometry_audit": audit, "view": view,
            "model_observation": _model_observation_image(out / "render.png")}


def audit_step(run: Path, out: Path):
    import cadquery as cq
    import numpy as np
    from PIL import Image, ImageDraw, ImageFont
    from .fonts import dejavu_sans
    from .provenance import write_json
    shape, record, audit = _reimport(run)
    regions = "region_loft" in record["metrics"]
    source_sections = record["sections"]
    indices = sorted(set([0, min(1, len(source_sections) - 1), len(source_sections) // 2,
                          max(0, len(source_sections) - 2), len(source_sections) - 1]))
    reports = []
    artifacts = []
    for index in indices:
        section = source_sections[index]
        x = float(section["x_m"])
        edges = _cut_edges(shape, x, regions)
        if not edges or len(edges) > 8192:
            raise ValueError("A sampled STEP section is missing or exceeds the cut complexity limit.")
        segments = []
        for edge in edges:
            points, _ = edge.sample(2 if edge.geomType() == "LINE" else 16)
            yz = np.array([[p.y / 1000, p.z / 1000] for p in points])
            segments.extend(zip(yz[:-1], yz[1:]))
        observed, piece_counts = _observed_samples(section)
        starts = np.array([s[0] for s in segments]); ends = np.array([s[1] for s in segments])
        vectors = ends - starts
        length2 = np.sum(vectors * vectors, axis=1)
        delta = observed[:, None, :] - starts[None, :, :]
        parameter = np.clip(np.sum(delta * vectors[None, :, :], axis=2) / np.maximum(length2, 1e-18), 0, 1)
        closest = starts[None, :, :] + parameter[:, :, None] * vectors[None, :, :]
        distance = np.sqrt(np.min(np.sum((observed[:, None, :] - closest) ** 2, axis=2), axis=1))
        ppm = section["evidence"]["calibration"]["pixels_per_metre"]
        report = {"section_id": section["id"], "x_m": x, "sample_count": len(observed),
                  "distance_type": "observed source-centre samples to actual STEP section boundary; no reference truth used",
                  "rms_m": float(np.sqrt(np.mean(distance ** 2))), "p95_m": float(np.percentile(distance, 95)),
                  "max_m": float(np.max(distance)), "max_px": float(np.max(distance) * ppm),
                  "source_measurement_uncertainty_m": section["evidence"].get("measurement_uncertainty_m"),
                  "section_edges": len(edges)}
        if regions:
            # Trace fidelity of each piece, so one piece cannot hide behind another.
            bounds = np.cumsum([0, *piece_counts])
            report["pieces"] = [{"piece": index, "sample_count": int(count),
                                 "max_m": float(np.max(distance[bounds[index]:bounds[index + 1]]))}
                                for index, count in enumerate(piece_counts)]
        reports.append(report)
        width, height = 950, 750
        canvas = Image.new("RGB", (width, height), "white"); draw = ImageDraw.Draw(canvas)
        try:
            font = dejavu_sans(16)
        except OSError:
            font = ImageFont.load_default()
        draw.text((24, 18), f"{section['id']} | observed source centre vs ACTUAL STEP CUT at x={x:.6g} m", fill="#17344a", font=font)
        all_points = np.vstack([starts, ends, observed])
        low, high = np.min(all_points, axis=0), np.max(all_points, axis=0)
        scale = min((width - 100) / max(high[0] - low[0], 1e-9), (height - 180) / max(high[1] - low[1], 1e-9))
        def project(point):
            return (50 + (point[0] - low[0]) * scale, height - 110 - (point[1] - low[1]) * scale)
        for a, b in segments:
            draw.line([project(a), project(b)], fill="#287da6", width=2)
        for p in observed:
            px, py = project(p); draw.ellipse((px - 2, py - 2, px + 2, py + 2), fill="#d26b1b")
        draw.text((24, height - 75), f"Blue: reimported STEP boundary. Orange: measured drawing samples. Max deviation {report['max_m']:.5g} m ({report['max_px']:.4g} px).", fill="#374d5c", font=font)
        draw.text((24, height - 46), "This checks source-to-CAD fidelity. It does not verify the selected contour, scale, symmetry, or vessel condition.", fill="#765434", font=font)
        filename = f"section-cut-{index:03d}.png"; canvas.save(out / filename)
        artifacts.append({"file": filename, "kind": "step_section_cut_comparison", "section_id": section["id"]})
    # The engine's own bounded approximation is <=1mm unless it blocks. Leave a
    # small numerical audit tolerance; report all measured deviations as well.
    geometry_passed = audit["valid_shape"] and all(r["max_m"] <= .0011 for r in reports)
    validation = {"geometry_checks_passed": bool(geometry_passed), "immutable_run_verified": True,
                  "geometry_audit": audit, "sampled_sections": reports,
                  "sampled_section_count": len(reports), "total_section_count": len(source_sections),
                  "section_sampling": "first two, middle, last two; bounded sample, not exhaustive",
                  "numeric_reference_truth_used": False,
                  "unresolved_semantics": ["contour identity", "caller calibration", "station correspondence",
                                           "symmetry", "terminal and upper closure", "current vessel condition"],
                  "human_semantic_review_required": True, "engineering_approved": False}
    write_json(out / "validation.json", validation)
    artifacts.append({"file": "validation.json", "kind": "step_reimport_validation"})
    return {"validation": validation, "artifacts": artifacts}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--operation", choices=("inspect", "render", "audit"), required=True)
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--limits", required=True)
    parser.add_argument("--parent", type=int, required=True)
    args = parser.parse_args()
    from .worker import apply_limits
    apply_limits(json.loads(args.limits), args.parent)
    from .schema import load_bounded_json
    from .provenance import write_json
    request = load_bounded_json(args.request)
    started = time.monotonic()
    try:
        if args.operation == "inspect":
            from .agent_tools import inspect_source_worker
            result = inspect_source_worker(Path(request["spec_path"]), request["section_ids"], args.out)
        else:
            args.out.mkdir(parents=True, exist_ok=False)
            result = (render_step(Path(request["run_dir"]), request["view"], args.out)
                      if args.operation == "render" else audit_step(Path(request["run_dir"]), args.out))
        usage = resource.getrusage(resource.RUSAGE_SELF)
        result["resources"] = {"wall_seconds": round(time.monotonic() - started, 4),
                               "cpu_seconds": round(usage.ru_utime + usage.ru_stime, 4),
                               "peak_rss_kib": peak_rss_kib(usage.ru_maxrss),
                               "resource_profile": native_resource_profile()}
        write_json(args.out / "observation.json", result)
        return 0
    except BaseException as exc:
        # Bounded diagnostic only; no exception message, path, request or secret.
        args.out.mkdir(parents=True, exist_ok=True)
        write_json(args.out / "worker-error.json", {"error_code": "domain_worker_failed",
                                                   "exception_type": type(exc).__name__})
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
