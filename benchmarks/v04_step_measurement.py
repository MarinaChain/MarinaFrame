"""Receipt-bound outer-envelope STEP measurement, before reference scoring.

This separate instrument revision preserves the original frozen pixel tool.
It clamps admitted near-endpoint segment queries, records competing intersections
and interior horizontal overlaps, and binds the measured STEP and input spec to
the finalized attempt. No production solver or evaluation reference is imported.
"""
from __future__ import annotations

import importlib.util
import math
from pathlib import Path
import time

_source = Path(__file__).with_name("v04_sealed_eval.py")
_spec = importlib.util.spec_from_file_location("v04_receipt_utilities", _source)
_u = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_u)
read, write, digest, utc = _u.read, _u.write, _u.digest, _u.utc
TOL_MM = 1e-5


def bind_inputs(step_path, spec_path, freeze_path, attempt_path):
    freeze, attempt = _u.require_frozen_finalized(freeze_path, attempt_path)
    spec = read(spec_path)
    if spec.get("vessel_id") != attempt.get("case_id"):
        raise ValueError("Measurement case/spec identity mismatch")
    spec_hash = attempt.get("input_spec_sha256", attempt.get("input_sha256"))
    if not spec_hash or digest(spec_path) != spec_hash:
        raise ValueError("Measurement specification is not bound to the finalized attempt")
    step = Path(step_path).resolve()
    matching = [r for r in attempt.get("output_files", [])
                if Path(r["path"]).resolve() == step and r["sha256"] == digest(step)]
    if not matching:
        raise ValueError("Measured STEP is absent from the finalized output inventory")
    return freeze, attempt, spec


def bounded_segment(z_mm, z0, z1, y0, y1):
    """Nonhorizontal segment hits; tolerance never permits extrapolation."""
    import numpy as np
    take = (z_mm >= min(z0, z1)-TOL_MM) & (z_mm <= max(z0, z1)+TOL_MM)
    indices = np.flatnonzero(take)
    query = np.clip(z_mm[take], min(z0, z1), max(z0, z1))
    values = y0 + (query-z0)*(y1-y0)/(z1-z0)
    clamped = int(np.count_nonzero(query != z_mm[take]))
    valid = values >= -TOL_MM
    return indices[valid], np.maximum(values[valid], 0.), clamped


def summarize_hits(hits, horizontal):
    values, counts = [], []
    for row in hits:
        unique = []
        for value in sorted(row):
            if not unique or value-unique[-1] > TOL_MM:
                unique.append(value)
        values.append(max(unique)/1000 if unique else None)
        counts.append(len(unique))
    interior = range(1, max(1, len(hits)-1))
    return {
        "y_m": values,
        "nonnegative_intersection_count": counts,
        "unresolved": sum(v is None for v in values),
        "competing_intersection_ordinates": sum(n > 1 for n in counts),
        "competing_interior_ordinates": sum(counts[i] > 1 for i in interior),
        "horizontal_overlap_ordinates": sum(horizontal),
        "interior_horizontal_overlap_ordinates": sum(horizontal[i] for i in interior),
        "declared_boundary_horizontal_overlap_ordinates": sum(horizontal[i] for i in {0, len(hits)-1}),
    }


def cut_step(step_path, spec_path, out, freeze_path, attempt_path, trace_path=None):
    _, attempt, spec = bind_inputs(step_path, spec_path, freeze_path, attempt_path)
    import cadquery as cq
    import numpy as np
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Section
    from OCP.BRepExtrema import BRepExtrema_DistShapeShape
    from OCP.gp import gp_Dir, gp_Pln, gp_Pnt
    traces = {}
    if trace_path is not None:
        trace_file = Path(trace_path).resolve()
        if not any(Path(r["path"]).resolve() == trace_file and r["sha256"] == digest(trace_file)
                   for r in attempt["output_files"]):
            raise ValueError("Selected trace file is absent from the finalized output inventory")
        trace_data = read(trace_file)
        trace_sections = trace_data["sections"] if isinstance(trace_data, dict) else trace_data
        traces = {s["id"]: s for s in trace_sections}
    start = time.monotonic()
    imported = cq.importers.importStep(str(step_path))
    shapes = imported.vals()
    solids = [s for q in shapes for s in q.Solids()]
    shape = cq.Compound.makeCompound(shapes)
    record = {
        "schema_version": "marinaframe-independent-step-envelope-measurement-3",
        "created_utc": utc(), "case_id": spec["vessel_id"],
        "attempt_id": attempt["attempt_id"], "step_sha256": digest(step_path),
        "input_spec_sha256": digest(spec_path), "step_units": "mm",
        "shape_valid": bool(shape.isValid()), "solid_count": len(solids),
        "volume_m3": float(shape.Volume()/1e9),
        "cut_deflection_requested_mm": .01, "numerical_endpoint_tolerance_mm": TOL_MM,
        "required_samples_per_station": 4097, "sections": [], "cadquery_version": cq.__version__,
        "measurement_definition": "Maximum nonnegative half-breadth intersection: the outer envelope. Multiple intersections and horizontal overlaps are separately counted; resolved coverage alone does not prove an unambiguous section.",
        "instrument_sha256": digest(__file__),
        "selected_trace": None if trace_path is None else {
            "file_sha256": digest(trace_path),
            "definition": "Euclidean nearest distance from every retained measured source-centre sample to the actual STEP section boundary, using OCCT shape-distance queries. This checks selected-trace consistency, not source contour identity.",
            "limit_mm": 1.1,
            "sections": [],
        },
    }
    for sec in spec.get("sections", []):
        plane = gp_Pln(gp_Pnt(float(sec["x_m"])*1000, 0, 0), gp_Dir(1, 0, 0))
        op = BRepAlgoAPI_Section(shape.wrapped, plane, False)
        op.Build()
        zgrid = np.linspace(float(sec["z_min_m"]), float(sec["z_max_m"]), 4097)
        zmm = zgrid*1000
        hits = [[] for _ in zgrid]
        horizontal = [False for _ in zgrid]
        edges = cq.Shape.cast(op.Shape()).Edges() if op.IsDone() else []
        vertex_count, clamped = 0, 0
        for edge in edges:
            points, _ = edge.sample(.01)
            vertex_count += len(points)
            for p, q in zip(points[:-1], points[1:]):
                z0, z1, y0, y1 = float(p.z), float(q.z), float(p.y), float(q.y)
                if abs(z1-z0) < 1e-9:
                    if max(y0, y1) < -TOL_MM:
                        continue
                    lo, hi = max(0., min(y0, y1)), max(0., max(y0, y1))
                    for i in np.flatnonzero(np.abs(zmm-z0) <= TOL_MM):
                        hits[i].extend([lo, hi])
                        horizontal[i] |= hi-lo > TOL_MM
                else:
                    indices, values, n = bounded_segment(zmm, z0, z1, y0, y1)
                    clamped += n
                    for i, y in zip(indices, values):
                        hits[i].append(float(y))
        record["sections"].append({
            "id": sec["id"], "x_m": sec["x_m"], "cut_done": bool(op.IsDone()),
            "edges": len(edges), "sampled_edge_vertices": vertex_count,
            "clamped_near_endpoint_segment_hits": clamped,
            "z_m": zgrid.tolist(), **summarize_hits(hits, horizontal),
        })
        if trace_path is not None:
            trace = traces.get(sec["id"])
            distances, unresolved = [], 0
            if trace is None or float(trace["x_m"]) != float(sec["x_m"]):
                trace_record = {"id": sec["id"], "missing_or_mismatched_trace": True,
                                "required_samples": 0, "unresolved_samples": 1,
                                "max_error_mm": None, "rms_error_mm": None}
            else:
                points = trace["points_yz_m"]
                boundary = op.Shape()
                for y, z in points:
                    if not edges or not all(math.isfinite(float(q)) for q in (y, z)):
                        distances.append(None); unresolved += 1; continue
                    vertex = cq.Vertex.makeVertex(float(sec["x_m"])*1000, float(y)*1000, float(z)*1000)
                    distance = BRepExtrema_DistShapeShape(vertex.wrapped, boundary)
                    distance.Perform()
                    if distance.IsDone():
                        distances.append(float(distance.Value()))
                    else:
                        distances.append(None); unresolved += 1
                good = [d for d in distances if d is not None]
                trace_record = {"id": sec["id"], "required_samples": len(points),
                                "unresolved_samples": unresolved,
                                "max_error_mm": max(good) if good else None,
                                "rms_error_mm": math.sqrt(sum(d*d for d in good)/len(good)) if good else None,
                                "distances_mm": distances}
            record["selected_trace"]["sections"].append(trace_record)
    if trace_path is not None:
        rows = record["selected_trace"]["sections"]
        maximum = max((r["max_error_mm"] for r in rows if r["max_error_mm"] is not None), default=None)
        unresolved = sum(r["unresolved_samples"] for r in rows)
        record["selected_trace"].update({"max_error_mm": maximum,
            "required_samples": sum(r["required_samples"] for r in rows),
            "unresolved_samples": unresolved,
            "passed": bool(rows and not unresolved and maximum is not None and maximum <= 1.1)})
    record["wall_seconds"] = time.monotonic()-start
    write(out, record)
    return {k: v for k, v in record.items() if k != "sections"}
