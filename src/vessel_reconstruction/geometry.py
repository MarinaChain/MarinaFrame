"""CAD construction from measured half-sections.

Input/output reporting uses metres. The OpenCascade model and STEP use millimetres
to preserve conventional CAD units; mesh.json is explicitly in metres.
"""
from __future__ import annotations

import json
from pathlib import Path
import numpy as np
import cadquery as cq


class GeometryError(ValueError):
    pass


CAD_CONSTRUCTION_METHOD = "explicit_correspondence_ruled_panels_v2"
# OpenCascade stores this model in millimetres. This is only an equality
# tolerance for duplicate closure vertices; no positive breadth is invented.
_VERTEX_TOLERANCE_MM = 1e-7


def normalize_sections(sections: list[dict], samples: int = 33) -> list[dict]:
    normalized = []
    for sec in sorted(sections, key=lambda s: s["x_m"]):
        points = np.asarray(sec["points_yz_m"], dtype=float)
        if points.ndim != 2 or points.shape[1] != 2 or len(points) < 5 or not np.isfinite(points).all():
            raise GeometryError(f"Invalid measured section: {sec['id']}")
        points = points[np.argsort(points[:, 1])]
        zz, idx = np.unique(points[:, 1], return_index=True)
        yy = points[idx, 0]
        if len(zz) < 5 or zz[-1] <= zz[0] or np.min(yy) < -1e-8:
            raise GeometryError(f"Section {sec['id']} is not a supported starboard half-section.")
        if np.max(yy) < 1e-5:
            raise GeometryError(f"Section {sec['id']} degenerates to a line; a point-ended loft requires an explicit supported end treatment.")
        z = np.linspace(zz[0], zz[-1], samples)
        y = np.interp(z, zz, yy)
        # Keep a single half-section contour, preserving flat bottoms when drawn.
        normalized.append({**sec, "cad_points_yz_m": np.column_stack([y, z]).tolist()})
    if len(normalized) < 3:
        raise GeometryError("At least three measured sections are required.")
    xs = np.array([s["x_m"] for s in normalized])
    if np.min(np.diff(xs)) <= 0:
        raise GeometryError("Section station coordinates are not strictly increasing.")
    return normalized


def _vector(point: np.ndarray) -> cq.Vector:
    return cq.Vector(*map(float, point))


def _planar_face(points: np.ndarray) -> cq.Face | None:
    """Make a cap/closure, retaining triangles where one breadth is zero."""
    clean: list[np.ndarray] = []
    for point in points:
        if not clean or np.linalg.norm(point - clean[-1]) > _VERTEX_TOLERANCE_MM:
            clean.append(point)
    if len(clean) > 1 and np.linalg.norm(clean[-1] - clean[0]) <= _VERTEX_TOLERANCE_MM:
        clean.pop()
    # When both endpoint breadths are zero there is an edge, not a face.
    if len(clean) < 3:
        return None
    return cq.Face.makeFromWires(cq.Wire.makePolygon([_vector(p) for p in clean], close=True))


def _terminal_cap(half: np.ndarray, section_id: str) -> cq.Face:
    positive = np.flatnonzero(half[:, 1] > 0)
    if not len(positive):
        raise GeometryError(f"Section {section_id} cannot enclose an area.")
    if np.any(half[positive[0]:positive[-1] + 1, 1] <= 0):
        raise GeometryError(f"Section {section_id} contains an unsupported interior centreline pinch.")
    # A leading/trailing centreline interval is retraced by the mirrored
    # profile and encloses zero area. Its final/first vertex still defines the
    # measured keel/top; remove only the redundant, zero-area wire spur.
    bounded = half[max(0, positive[0] - 1):min(len(half), positive[-1] + 2)]
    face = _planar_face(np.vstack([bounded, bounded[::-1] * [1, -1, 1]]))
    if face is None:
        raise GeometryError(f"Section {section_id} cannot enclose an area.")
    return face


def build_hull(sections: list[dict], samples: int = 33) -> tuple[cq.Shape, list[dict]]:
    """Build an explicitly matched ruled BRep from normalized observations.

    Each half-section has the same sampling indices. Corresponding straight
    segments on neighbouring stations bound a standard OpenCascade ruled face.
    Mirroring supplies the declared opposite side; planar top/bottom closures
    and terminal caps close the envelope. A zero-width keel may therefore meet
    a measured flat bottom without a closed-wire loft guessing edge matches.

    Beyond the existing ``samples``-point linear resampling, this introduces
    no curve fitting, smoothing, minimum breadth or coordinate adjustment.
    """
    sections = normalize_sections(sections, samples=samples)
    profiles = [np.column_stack([
        np.full(len(section["cad_points_yz_m"]), section["x_m"]),
        section["cad_points_yz_m"],
    ]) * 1000 for section in sections]
    faces: list[cq.Face] = []
    try:
        for left, right in zip(profiles, profiles[1:]):
            for j in range(len(left) - 1):
                panel = np.array([left[j], left[j + 1], right[j], right[j + 1]])
                # Both sides would coincide on the centreplane here; this
                # zero-width interval contributes neither skin nor volume.
                if np.all(panel[:, 1] == 0):
                    continue
                for sign in (1, -1):
                    side = panel * [1, sign, 1]
                    first = cq.Edge.makeLine(_vector(side[0]), _vector(side[1]))
                    second = cq.Edge.makeLine(_vector(side[2]), _vector(side[3]))
                    faces.append(cq.Face.makeRuledSurface(first, second))
            for index in (0, -1):
                closure = _planar_face(np.array([
                    left[index], right[index],
                    right[index] * [1, -1, 1], left[index] * [1, -1, 1],
                ]))
                if closure is not None:
                    faces.append(closure)
        for index in (0, -1):
            faces.append(_terminal_cap(profiles[index], sections[index]["id"]))
        shell = cq.Shell.makeShell(faces)
        if shell.ShapeType() != "Shell" or len(shell.Shells()) != 1 or not shell.Closed() or not shell.isValid():
            raise GeometryError("The measured section panels do not form one valid closed CAD shell; inspect centreline pinches or intersecting profiles.")
        solid = cq.Solid.makeSolid(shell)
    except GeometryError:
        raise
    except Exception as exc:
        raise GeometryError(f"The CAD kernel could not build the measured ruled panels: {type(exc).__name__}") from exc
    if not solid.isValid() or len(solid.Solids()) != 1 or solid.Volume() <= 0:
        raise GeometryError("The reconstructed envelope is not a valid positive-volume CAD solid.")
    return solid, sections


def metrics_for(shape: cq.Shape) -> dict:
    b = shape.BoundingBox()
    return {
        "volume_m3": float(shape.Volume() / 1e9),
        "surface_area_m2": float(shape.Area() / 1e6),
        "length_m": float(b.xlen / 1000), "beam_m": float(b.ylen / 1000), "depth_m": float(b.zlen / 1000),
        "bbox_m": {"min": [b.xmin / 1000, b.ymin / 1000, b.zmin / 1000], "max": [b.xmax / 1000, b.ymax / 1000, b.zmax / 1000]},
        "cad_valid": bool(shape.isValid()), "solid_count": len(shape.Solids()),
        "volume_definition": "Enclosed envelope over the declared stations and vertical range; not steel volume or automatically displacement.",
    }


def export_geometry(shape: cq.Shape, out: Path, *, export_cad: bool = True) -> tuple[dict, dict]:
    metrics = metrics_for(shape)
    tolerance_mm = max(0.5, metrics["beam_m"] * 1000 / 800)
    vertices, faces = shape.tessellate(tolerance_mm, 0.15)
    mesh = {
        "units": "m",
        "vertices": [[v.x / 1000, v.y / 1000, v.z / 1000] for v in vertices],
        "faces": [[int(i) for i in f] for f in faces],
        "parts": [{"id": "hull", "face_start": 0, "face_count": len(faces)}],
    }
    (out / "mesh.json").write_text(json.dumps(mesh, separators=(",", ":"), allow_nan=False), encoding="utf-8")
    exports = {"mesh": "mesh.json", "mesh_units": "m"}
    if export_cad:
        shape.exportStep(str(out / "model.step"), write_pcurves=False)
        shape.exportStl(str(out / "model.stl"), tolerance=tolerance_mm, angularTolerance=0.15)
        reread = cq.importers.importStep(str(out / "model.step")).val()
        if not reread.isValid() or len(reread.Solids()) != 1:
            raise GeometryError("The exported STEP file failed independent reload validation.")
        reloaded = metrics_for(reread)
        rel = abs(reloaded["volume_m3"] - metrics["volume_m3"]) / metrics["volume_m3"]
        extent_error = max(abs(reloaded[k] - metrics[k]) / max(metrics[k], 1e-12) for k in ("length_m", "beam_m", "depth_m"))
        if rel > 1e-6 or extent_error > 1e-6:
            raise GeometryError("STEP round-trip altered geometry or units beyond tolerance.")
        metrics["step_roundtrip_relative_error"] = float(rel)
        metrics["step_roundtrip_extent_error"] = float(extent_error)
        exports.update({"step": "model.step", "step_units": "mm", "stl": "model.stl", "stl_units": "mm"})
    metrics["mesh_vertices"] = len(vertices)
    metrics["mesh_faces"] = len(faces)
    return exports, metrics
