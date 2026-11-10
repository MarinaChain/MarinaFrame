"""CAD construction from measured half-sections.

Input/output reporting uses metres. The OpenCascade model and STEP use millimetres
to preserve conventional CAD units; mesh.json is explicitly in metres.
"""
from __future__ import annotations

import json
import math
from pathlib import Path
import numpy as np
import cadquery as cq
from OCP.BRepMesh import BRepMesh_IncrementalMesh

from . import section_regions
from .cad_exports import export_iges
from .progress import report as report_progress
from .rhino_exports import CadPart, export_3dm
from .errors import GeometryError


CAD_CONSTRUCTION_METHOD = "bounded_source_knots_ruled_panels_v3"
DEFAULT_MAX_DEVIATION_M = 0.001
MAX_COMMON_KNOTS = 513
MAX_ESTIMATED_FACES = 20_000
MAX_SECTION_POINTS = 1025
MAX_SECTIONS = 300
# OpenCascade stores this model in millimetres. This is only an equality
# tolerance for duplicate closure vertices; no positive breadth is invented.
_VERTEX_TOLERANCE_MM = 1e-7


def _bounded_knots(t: np.ndarray, y: np.ndarray, tolerance_m: float) -> np.ndarray:
    """Simplify a piecewise linear ordinate function with a vertical error bound.

    The difference of two piecewise linear functions has its absolute maximum
    at a knot of either function. Testing every source knot therefore bounds
    the *entire* observed curve, including features narrower than a sample grid.
    Zero/positive transitions are mandatory knots because topology is not an
    approximation tolerance. No positive minimum breadth is inserted.
    """
    mandatory = {0, len(t) - 1}
    for index in np.flatnonzero((y[:-1] == 0) != (y[1:] == 0)):
        mandatory.update((int(index), int(index + 1)))
    selected = set(mandatory)
    ordered = sorted(mandatory)
    pending = list(zip(ordered[:-1], ordered[1:]))
    while pending:
        first, last = pending.pop()
        if last <= first + 1:
            continue
        local_t = t[first + 1:last]
        predicted = y[first] + (y[last] - y[first]) * (local_t - t[first]) / (t[last] - t[first])
        errors = np.abs(y[first + 1:last] - predicted)
        offset = int(np.argmax(errors))
        if errors[offset] > tolerance_m:
            index = first + 1 + offset
            selected.add(index)
            pending.extend(((first, index), (index, last)))
    return np.asarray(sorted(selected), dtype=int)


# A draft build (fit_complexity=True) raises its approximation bound by this
# factor per step until the section curves fit the CAD limits. 1.25 keeps the
# final bound within 25 % of the smallest bound on the ladder that fits.
COMPLEXITY_FIT_STEP = 1.25


def _common_knots(knots: list[np.ndarray], samples: int | None) -> list[float]:
    """Union of normalized-height knots of all sections plus the optional minimum grid."""
    all_knots = [np.linspace(0, 1, samples)] if samples is not None else []
    all_knots.extend(knots)
    raw_knots = np.sort(np.concatenate(all_knots))
    # Fractional-height grids derived from different bases have roundoff-sized
    # differences. Coalesce those only; verify the final bound afterwards.
    common = [float(raw_knots[0])]
    for value in raw_knots[1:]:
        if value - common[-1] > 1e-12:
            common.append(float(value))
    common[0], common[-1] = 0.0, 1.0
    return common


def _estimated_faces(section_count: int, knot_count: int) -> int:
    return 2 * (section_count - 1) * knot_count + 2


def _fits_cad_limits(section_count: int, knot_count: int) -> bool:
    return knot_count <= MAX_COMMON_KNOTS and _estimated_faces(section_count, knot_count) <= MAX_ESTIMATED_FACES


def _select_knots(prepared: list[tuple], samples: int | None, bound_m: float,
                  fit_complexity: bool) -> tuple[float, list[np.ndarray], list[float]]:
    """Select source knots with ``bound_m``; a complexity fit raises the bound until they fit.

    The ladder ends at the largest ordinate span of any section. At that bound
    every chord is within tolerance, so only mandatory knots remain.
    """
    ceiling = max(float(np.ptp(yy)) for _, _, yy, _ in prepared)
    while True:
        selections = [_bounded_knots(t, yy, bound_m) for _, _, yy, t in prepared]
        common = _common_knots([t[selected] for (_, _, _, t), selected in zip(prepared, selections)], samples)
        if not fit_complexity or _fits_cad_limits(len(prepared), len(common)) or bound_m >= ceiling:
            return bound_m, selections, common
        bound_m = min(ceiling, max(bound_m, DEFAULT_MAX_DEVIATION_M) * COMPLEXITY_FIT_STEP)


def normalize_sections(
    sections: list[dict], samples: int | None = None, *,
    max_deviation_m: float = DEFAULT_MAX_DEVIATION_M, fit_complexity: bool = False,
) -> list[dict]:
    """Create bounded, explicit correspondence without dropping narrow features.

    All sections share a union of normalized-height source knots. Different
    elevation domains consequently correspond by their declared height
    fraction. ``samples`` is retained as an optional *minimum* density; it is
    never a cap on retained source detail. The default 1 mm bound is a CAD
    approximation bound relative to the observed polyline, not source accuracy.
    Excessive correspondence/face complexity is rejected before native CAD.

    A draft build sets ``fit_complexity``: instead of a rejection, the bound is
    raised step by step until the knots fit the CAD limits. Each record then
    keeps the requested bound in ``complexity_fit`` and the raised bound as its
    allowed deviation, so the simplification is visible and verifiable.
    """
    if not isinstance(sections, list) or not 3 <= len(sections) <= MAX_SECTIONS:
        raise GeometryError(f"At least three measured sections are required; the limit is {MAX_SECTIONS}.")
    if (isinstance(max_deviation_m, bool) or not isinstance(max_deviation_m, (int, float))
            or not math.isfinite(max_deviation_m) or not 0 <= max_deviation_m <= 0.01):
        raise GeometryError("max_deviation_m must be a finite number between 0 and 0.01 metres.")
    if samples is not None and (isinstance(samples, bool) or not isinstance(samples, int)
                                or not 2 <= samples <= MAX_COMMON_KNOTS):
        raise GeometryError(f"Optional minimum samples must be an integer from 2 to {MAX_COMMON_KNOTS}.")
    try:
        xs = [s["x_m"] for s in sections]
        if any(isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x)
               or abs(x) > 1e7 for x in xs):
            raise GeometryError("Invalid measured station coordinate.")
        ordered_sections = sorted(sections, key=lambda s: s["x_m"])
    except (KeyError, TypeError) as exc:
        raise GeometryError("Invalid measured section metadata.") from exc
    if np.min(np.diff([s["x_m"] for s in ordered_sections])) <= 0:
        raise GeometryError("Section station coordinates are not strictly increasing.")
    prepared = []
    for sec in ordered_sections:
        section_id = sec.get("id", "unnamed")
        try:
            points = np.asarray(sec["points_yz_m"], dtype=float)
        except (KeyError, TypeError, ValueError, OverflowError) as exc:
            raise GeometryError(f"Invalid measured section: {section_id}") from exc
        if (points.ndim != 2 or points.shape[1] != 2 or not 5 <= len(points) <= MAX_SECTION_POINTS
                or not np.isfinite(points).all() or np.max(np.abs(points)) > 1e7):
            raise GeometryError(f"Invalid measured section: {section_id}; require 5..{MAX_SECTION_POINTS} finite bounded points.")
        points = points[np.argsort(points[:, 1], kind="stable")]
        zz, yy = points[:, 1], points[:, 0]
        if np.any(np.diff(zz) <= 0):
            raise GeometryError(f"Section {section_id} requires unique increasing elevations; duplicate ordinates are ambiguous.")
        if zz[-1] <= zz[0] or np.min(yy) < 0:
            raise GeometryError(f"Section {section_id} is not a supported starboard half-section.")
        if np.max(yy) < 1e-5:
            raise GeometryError(f"Section {section_id} degenerates to a line; a point-ended loft requires an explicit supported end treatment.")
        positive = np.flatnonzero(yy > 0)
        if np.any(yy[positive[0]:positive[-1] + 1] == 0):
            raise GeometryError(f"Section {section_id} contains an unsupported interior centreline pinch.")
        t = (zz - zz[0]) / (zz[-1] - zz[0])
        prepared.append((sec, zz, yy, t))
    bound_m, selections, common = _select_knots(prepared, samples, float(max_deviation_m), fit_complexity)
    if len(common) > MAX_COMMON_KNOTS:
        raise GeometryError(f"CAD complexity limit: {len(common)} common knots exceeds {MAX_COMMON_KNOTS}; split the job or review source complexity.")
    estimated_faces = _estimated_faces(len(prepared), len(common))
    if estimated_faces > MAX_ESTIMATED_FACES:
        raise GeometryError(f"CAD complexity limit: {estimated_faces} estimated faces exceeds {MAX_ESTIMATED_FACES}; split the job.")
    complexity_fit = None
    if bound_m > max_deviation_m:
        complexity_fit = {"requested_maximum_deviation_m": float(max_deviation_m),
                          "reason": f"section curves simplified to fit {MAX_COMMON_KNOTS} common knots "
                                    f"and {MAX_ESTIMATED_FACES} faces"}
    common_t = np.asarray(common)
    normalized = []
    for (sec, zz, yy, t), selected in zip(prepared, selections):
        z = zz[0] + common_t * (zz[-1] - zz[0])
        y = np.interp(common_t, t[selected], yy[selected])
        check_t = np.unique(np.concatenate((t, common_t)))
        differences = np.interp(check_t, common_t, y) - np.interp(check_t, t, yy)
        maximum = float(np.max(np.abs(differences)))
        if maximum > bound_m + 1e-10:
            raise GeometryError(f"Section {sec['id']} cannot meet the declared CAD approximation bound after knot correspondence.")
        if np.any(np.diff(z) <= 0):
            raise GeometryError(f"Section {sec['id']} has unresolvable elevation spacing at the declared coordinate scale.")
        # Integral of the square of a linear error over each interval is exact.
        rms = math.sqrt(float(np.sum(np.diff(check_t) *
                                     (differences[:-1] ** 2 + differences[:-1] * differences[1:] + differences[1:] ** 2) / 3)))
        source_area = float(2 * np.trapezoid(yy, zz))
        cad_area = float(2 * np.trapezoid(y, z))
        diagnostics = {
            "method": "vertical_error_bounded_source_knots_v1",
            "correspondence": "shared_normalized_height_source_knot_union",
            "maximum_allowed_half_breadth_deviation_m": float(bound_m),
            "maximum_half_breadth_deviation_m": maximum,
            "height_weighted_rms_deviation_m": rms,
            "source_point_count": len(yy), "retained_source_knots": len(selected),
            "common_knot_count": len(common), "estimated_face_count": estimated_faces,
            "source_section_area_m2": source_area, "cad_section_area_m2": cad_area,
            "section_area_error_m2": cad_area - source_area,
            "section_beam_error_m": float(2 * (np.max(y) - np.max(yy))),
            "uncertainty_scope": "CAD approximation of measured polyline only; excludes contour identity, calibration, interpolation between stations, and source accuracy",
        }
        if complexity_fit is not None:
            diagnostics["complexity_fit"] = complexity_fit
        normalized.append({**sec, "cad_points_yz_m": np.column_stack([y, z]).tolist(),
                           "cad_approximation": diagnostics})
    return normalized


def approximation_summary(sections: list[dict]) -> dict:
    """Expose the declared and measured approximation bounds in run metrics."""
    records = [s["cad_approximation"] for s in sections]
    summary = {
        "method": "vertical_error_bounded_source_knots_v1",
        "correspondence": "shared_normalized_height_source_knot_union",
        "maximum_allowed_half_breadth_deviation_m": max(r["maximum_allowed_half_breadth_deviation_m"] for r in records),
        "maximum_half_breadth_deviation_m": max(r["maximum_half_breadth_deviation_m"] for r in records),
        "maximum_height_weighted_rms_deviation_m": max(r["height_weighted_rms_deviation_m"] for r in records),
        "maximum_section_area_error_m2": max(abs(r["section_area_error_m2"]) for r in records),
        "maximum_section_beam_error_m": max(abs(r["section_beam_error_m"]) for r in records),
        "common_knot_count": records[0]["common_knot_count"],
        "estimated_face_count": records[0]["estimated_face_count"],
        "limits": {"common_knots": MAX_COMMON_KNOTS, "estimated_faces": MAX_ESTIMATED_FACES,
                   "sections": MAX_SECTIONS, "source_points_per_section": MAX_SECTION_POINTS},
        "uncertainty_scope": records[0]["uncertainty_scope"],
    }
    if "complexity_fit" in records[0]:
        summary["complexity_fit"] = records[0]["complexity_fit"]
    return summary


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


def build_hull(sections: list[dict], samples: int | None = None, *,
               max_deviation_m: float = DEFAULT_MAX_DEVIATION_M,
               fit_complexity: bool = False) -> tuple[cq.Shape, list[dict]]:
    """Build an explicitly matched ruled BRep from normalized observations.

    Each half-section has the same sampling indices. Corresponding straight
    segments on neighbouring stations bound a standard OpenCascade ruled face.
    Mirroring supplies the declared opposite side; planar top/bottom closures
    and terminal caps close the envelope. A zero-width keel may therefore meet
    a measured flat bottom without a closed-wire loft guessing edge matches.

    Source polyline approximation has an explicit maximum ordinate error.
    Correspondence retains narrow source features and zero-width transitions;
    no hull-family fit or minimum breadth is introduced. A draft build sets
    ``fit_complexity`` to simplify over-complex curves (see normalize_sections).
    """
    sections = normalize_sections(sections, samples=samples, max_deviation_m=max_deviation_m,
                                  fit_complexity=fit_complexity)
    profiles = [np.column_stack([
        np.full(len(section["cad_points_yz_m"]), section["x_m"]),
        section["cad_points_yz_m"],
    ]) * 1000 for section in sections]
    faces: list[cq.Face] = []
    try:
        for section_index, (left, right) in enumerate(zip(profiles, profiles[1:]), 1):
            report_progress('Building the hull', section_index, len(profiles), unit='section')
            for j in range(len(left) - 1):
                panel = np.array([left[j], left[j + 1], right[j], right[j + 1]])
                # Both sides would coincide on the centreplane here; this
                # zero-width interval contributes neither skin nor volume.
                if np.all(panel[:, 1] == 0):
                    continue
                for sign in (1, -1):
                    side = panel * [1, sign, 1]
                    if min(np.linalg.norm(side[1] - side[0]), np.linalg.norm(side[3] - side[2])) \
                            <= _VERTEX_TOLERANCE_MM:
                        # A repeated sample point makes a zero-length edge;
                        # OpenCascade cannot rule it (it crashes). The panel
                        # is the triangle of its distinct corners, if any.
                        triangle = _planar_face(side[[0, 1, 3, 2]])
                        if triangle is not None:
                            faces.append(triangle)
                        continue
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
        report_progress('Closing the hull', len(profiles), len(profiles), unit='section')
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


# Multi-region stations ------------------------------------------------------------
#
# build_hull above needs one half-breadth per height. build_region_hull accepts
# stations whose cross-section has several regions (section_regions.py), for
# example twin skegs below a tunnel roof or a bulb drawn apart from the bow.
# Each region is lofted only to the matching region on the neighbouring
# station; a region without a match ends with a flat closure at its station.
# The result is a compound of closed solids that meet on shared faces.

REGION_LOFT_METHOD = "matched_region_ruled_lofts_v1"
# Relative agreement required between the kernel volume of each lofted solid
# and the exact prismatoid volume of its polygons (a loft between polygons
# whose vertices move on straight lines has a cross-section area quadratic in
# x, so Simpson's rule is exact). Larger differences mean a malformed solid.
_REGION_VOLUME_AUDIT_TOLERANCE = 1e-6
# The same audit for one B-spline face per side (``one_face_per_side``). The surface is the
# panel surface, but the kernel integrates one face of many spans less exactly: on the
# Gunnerus hull the difference was up to about 4e-6 relative. A malformed solid (open,
# inverted or missing a part) is wrong by whole percents, so this still finds it.
_BSPLINE_VOLUME_AUDIT_TOLERANCE = 1e-5


def _shoelace(yz: np.ndarray) -> float:
    y, z = yz[:, 0], yz[:, 1]
    return 0.5 * abs(float(np.dot(y, np.roll(z, -1)) - np.dot(z, np.roll(y, -1))))


def _region_side_polygons(kind: str, outer: np.ndarray, inner: np.ndarray | None) -> list[np.ndarray]:
    """Closed (y, z) station polygons of one region: one, or one per side."""
    if kind == section_regions.CENTRELINE:
        mirrored = outer[::-1] * [-1, 1]
        return [np.vstack([outer, mirrored])]
    starboard = np.vstack([outer, inner[::-1]])
    return [starboard, starboard * [-1, 1]]


def _panel_faces(left: np.ndarray, right: np.ndarray) -> list[cq.Face]:
    """Faces between corresponding edges of two closed station polygons (mm)."""
    faces = []
    count = len(left)
    for j in range(count):
        a, b = left[j], left[(j + 1) % count]
        d, c = right[j], right[(j + 1) % count]
        left_is_point = np.linalg.norm(a - b) <= _VERTEX_TOLERANCE_MM
        right_is_point = np.linalg.norm(c - d) <= _VERTEX_TOLERANCE_MM
        if left_is_point and right_is_point:
            continue
        if left_is_point or right_is_point:
            triangle = _planar_face(np.array([a, b, c, d]))
            if triangle is not None:
                faces.append(triangle)
            continue
        faces.append(cq.Face.makeRuledSurface(cq.Edge.makeLine(_vector(a), _vector(b)),
                                              cq.Edge.makeLine(_vector(d), _vector(c))))
    return faces


def _bilinear_side_faces(profiles: list[np.ndarray]) -> list[cq.Face]:
    """One side face and two end caps for a run piece, with the panel geometry unchanged.

    The ruled panels between corresponding polygon edges are bilinear patches. A B-spline
    surface of degree 1 in both directions through the same grid of polygon vertices
    (around the ring x stations) is the same surface, but it is one face instead of one
    face per panel. The STEP file and the mesh are then much smaller. The ring direction
    is periodic (the polygons are closed). The end caps are planar faces bounded by the
    end curves of the surface (polygon caps would split those curves into one STEP curve
    copy per polygon edge). Vertices repeated at some stations only (zero breadth there)
    stay as poles: they make patches of zero area, as the panel path skips them. The
    kernel's default volume integration is not exact on this surface; use
    ``precise_volume_mm3``.
    """
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeEdge, BRepBuilderAPI_MakeFace, BRepBuilderAPI_MakeWire
    from OCP.Geom import Geom_BSplineSurface
    from OCP.TColgp import TColgp_Array2OfPnt
    from OCP.TColStd import TColStd_Array1OfInteger, TColStd_Array1OfReal
    from OCP.gp import gp_Pnt

    # A ring edge of zero length at every station only adds a zero-width strip (for example
    # the keel point repeated at the closure); dropping its vertex keeps the geometry.
    grid = np.stack(profiles)  # stations x ring vertices x 3
    edge_lengths = np.linalg.norm(grid - np.roll(grid, -1, axis=1), axis=2)
    keep = edge_lengths.max(axis=0) > _VERTEX_TOLERANCE_MM
    profiles = [profile[keep] for profile in profiles]
    ring_count, station_count = len(profiles[0]), len(profiles)
    poles = TColgp_Array2OfPnt(1, ring_count, 1, station_count)
    for v, profile in enumerate(profiles, start=1):
        report_progress('Building the hull', v, station_count, unit='section')
        for u, point in enumerate(profile, start=1):
            poles.SetValue(u, v, gp_Pnt(*map(float, point)))
    # Periodic degree 1 in the ring direction: one knot per vertex plus the closing knot.
    u_knots = TColStd_Array1OfReal(1, ring_count + 1)
    u_mults = TColStd_Array1OfInteger(1, ring_count + 1)
    for index in range(ring_count + 1):
        u_knots.SetValue(index + 1, float(index))
        u_mults.SetValue(index + 1, 1)
    # Clamped degree 1 along the stations, parameterised by station x (mm).
    v_knots = TColStd_Array1OfReal(1, station_count)
    v_mults = TColStd_Array1OfInteger(1, station_count)
    for index, profile in enumerate(profiles):
        v_knots.SetValue(index + 1, float(profile[0][0]))
        v_mults.SetValue(index + 1, 2 if index in (0, station_count - 1) else 1)
    report_progress('Lofting the hull')
    surface = Geom_BSplineSurface(poles, u_knots, v_knots, u_mults, v_mults, 1, 1, True, False)
    side = cq.Face(BRepBuilderAPI_MakeFace(surface, 1e-6).Face())
    caps = []
    for profile in (profiles[0], profiles[-1]):
        edge = BRepBuilderAPI_MakeEdge(surface.VIso(float(profile[0][0]))).Edge()
        caps.append(cq.Face(BRepBuilderAPI_MakeFace(BRepBuilderAPI_MakeWire(edge).Wire(), True).Face()))
    return [side, *caps]


# Relative error goal of the adaptive volume integration on B-spline faces.
_PRECISE_VOLUME_EPS = 1e-9


def precise_volume_mm3(shape: cq.Shape) -> float:
    """Volume with adaptive integration: exact enough on degree-1 B-spline faces."""
    from OCP.BRepGProp import BRepGProp
    from OCP.GProp import GProp_GProps

    properties = GProp_GProps()
    BRepGProp.VolumeProperties_s(shape.wrapped, properties, _PRECISE_VOLUME_EPS)
    return properties.Mass()


def _one_face_solid(profiles: list[np.ndarray], prismatoid_m3: float,
                    audit_tolerance: float = _BSPLINE_VOLUME_AUDIT_TOLERANCE) -> tuple[cq.Solid, float] | None:
    """The run piece side as one B-spline face, or None when that solid is not good.

    Happy path: the caller then builds the piece from ruled panels (the same geometry,
    more faces), so the hull always builds. The solid must be one valid closed shell and
    pass the volume audit against the polygon prismatoid.
    """
    from OCP.ShapeFix import ShapeFix_Shape

    try:
        shell = cq.Shell.makeShell(_bilinear_side_faces(profiles))
        if shell.ShapeType() != "Shell":
            return None
        # Sewing the B-spline side to its caps can leave edge parameter flags unset.
        fix = ShapeFix_Shape(shell.wrapped)
        fix.Perform()
        shell = cq.Shape.cast(fix.Shape())
        if shell.ShapeType() != "Shell" or not shell.Closed() or not shell.isValid():
            return None
        solid = cq.Solid.makeSolid(shell)
        if precise_volume_mm3(solid) < 0:
            solid = cq.Solid(solid.wrapped.Reversed())
        volume = precise_volume_mm3(solid) / 1e9
    except Exception:
        return None
    if not solid.isValid() or abs(volume - prismatoid_m3) > audit_tolerance * max(prismatoid_m3, 1e-12):
        return None
    return solid, volume


# Volume audit of a tank loft (relative). A tank ring meets itself at the bottom of a V section
# (zero breadth there); the kernel's integration over those patches is about 3e-5 off the exact
# prismatoid, so the hull's 1e-5 would refuse good solids. 1e-4 is far inside the 0.5 % of the
# sounding-table check T1 (docs/TANKS_V1.md).
_LOFT_VOLUME_AUDIT_TOLERANCE = 1e-4


def ruled_loft_solid(rings_m: np.ndarray) -> cq.Solid | None:
    """A closed solid through rings of equal point count at increasing x, or None.

    ``rings_m`` is (stations, ring points, 3) in metres, each ring in one plane x = const (a
    tank loft, ``tanks.TankLoft``). The side is one degree-1 B-spline face through the rings
    and the ends are planar caps, as a hull run piece; the solid is in millimetres. None when
    the kernel cannot build it or its volume fails the audit against the polygon prismatoid.
    """
    xs = rings_m[:, 0, 0]
    sections = rings_m[:, :, 1:]
    prismatoid = sum((x1 - x0) / 6 * (_shoelace(a) + 4 * _shoelace((a + b) / 2) + _shoelace(b))
                     for a, b, x0, x1 in zip(sections, sections[1:], xs, xs[1:]))
    built = _one_face_solid([ring * 1000 for ring in rings_m], prismatoid, _LOFT_VOLUME_AUDIT_TOLERANCE)
    return built[0] if built else None


def _closed_solid(faces: list[cq.Face], label: str) -> cq.Solid:
    try:
        shell = cq.Shell.makeShell(faces)
        if shell.ShapeType() != "Shell" or not shell.Closed() or not shell.isValid():
            raise GeometryError(f"Region loft {label} does not form one valid closed shell.")
        solid = cq.Solid.makeSolid(shell)
        if solid.Volume() < 0:
            solid = cq.Solid(solid.wrapped.Reversed())
    except GeometryError:
        raise
    except Exception as exc:
        raise GeometryError(f"The CAD kernel could not build region loft {label}: {type(exc).__name__}") from exc
    if not solid.isValid() or solid.Volume() <= 0:
        raise GeometryError(f"Region loft {label} is not a valid positive-volume solid.")
    return solid


def _prepare_region(rows: np.ndarray, kind: str, tolerance_m: float) -> dict:
    t = section_regions.normalized_height(rows)
    prepared = {"rows": rows, "t": t, "kind": kind,
                "outer_knots": section_regions.boundary_knots(t, rows[:, 2], tolerance_m)}
    if kind == section_regions.OFFSET:
        prepared["inner_knots"] = section_regions.boundary_knots(t, rows[:, 1], tolerance_m)
    return prepared


def _run_knots(members: list[dict]) -> tuple[list, list | None]:
    outer = section_regions.merge_knots([m["outer_knots"] for m in members])
    inner = None
    if members[0]["kind"] == section_regions.OFFSET:
        inner = section_regions.merge_knots([m["inner_knots"] for m in members])
    return outer, inner


def _knot_count(knots: list | None) -> int:
    return 0 if knots is None else sum(count for _, count in knots)


def _fits(members: list[dict]) -> bool:
    outer, inner = _run_knots(members)
    sides = 1 if members[0]["kind"] == section_regions.CENTRELINE else 2
    vertices = 2 * _knot_count(outer) if sides == 1 else _knot_count(outer) + _knot_count(inner)
    faces = sides * vertices * (len(members) - 1) + 2 * sides
    return max(_knot_count(outer), _knot_count(inner)) <= MAX_COMMON_KNOTS and faces <= MAX_ESTIMATED_FACES


def _station_polygons(member: dict, outer_knots: list, inner_knots: list | None) -> tuple[list[np.ndarray], float]:
    """Polygons of one region at one station on the run's knots, and their deviation."""
    rows, t = member["rows"], member["t"]
    z0, z1 = rows[0, 0], rows[-1, 0]

    def boundary(column: int, knots: list) -> tuple[np.ndarray, float]:
        values = section_regions.evaluate_boundary(t, rows[:, column], knots)
        knot_t = np.repeat([value for value, _ in knots], [count for _, count in knots])
        error = section_regions.deviation(t, rows[:, column], knots, values)
        return np.column_stack([values, z0 + knot_t * (z1 - z0)]), error

    outer, outer_error = boundary(2, outer_knots)
    inner, inner_error = (None, 0.0) if inner_knots is None else boundary(1, inner_knots)
    return _region_side_polygons(member["kind"], outer, inner), max(outer_error, inner_error)


def build_region_hull(sections: list[dict], *, max_deviation_m: float = DEFAULT_MAX_DEVIATION_M,
                      min_overlap: float = section_regions.MIN_MATCH_OVERLAP,
                      one_face_per_side: bool = False) -> tuple[cq.Shape, dict]:
    """Loft multi-region stations; return a compound of solids and an audit report.

    ``sections`` are ``{"id", "x_m", "regions": [{"kind", "rows_m"}]}`` records
    (see section_regions.decompose_outline); a legacy ``points_yz_m`` record is
    one centreline region. Regions are matched one-to-one between neighbouring
    stations (section_regions.match_regions). Each matched run is lofted with
    ruled faces between corresponding polygon edges; correspondence is by
    normalized height inside the region, with source knots kept within
    ``max_deviation_m``. A run longer than the knot or face limit is split at a
    shared station. A region that matches no neighbour cannot be lofted; it is
    listed in ``unlofted_regions`` with its area, never silently dropped.

    Every solid passes an exact volume audit (Simpson's rule on its station
    polygons). The report gives station areas, runs and the volume.

    ``one_face_per_side`` writes each run piece side as one degree-1 B-spline surface
    through the same polygon vertices (``_bilinear_side_faces``): the same geometry with
    far fewer faces, for a light STEP and mesh. The default keeps the panel faces of the
    benchmark path.
    """
    if (isinstance(max_deviation_m, bool) or not isinstance(max_deviation_m, (int, float))
            or not math.isfinite(max_deviation_m) or not 0 <= max_deviation_m <= 0.01):
        raise GeometryError("max_deviation_m must be a finite number between 0 and 0.01 metres.")
    if not isinstance(sections, list) or not 2 <= len(sections) <= MAX_SECTIONS:
        raise GeometryError(f"At least two stations are required; the limit is {MAX_SECTIONS}.")
    try:
        ordered = sorted(sections, key=lambda s: s["x_m"])
        xs = [float(s["x_m"]) for s in ordered]
    except (KeyError, TypeError, ValueError) as exc:
        raise GeometryError("Invalid station metadata.") from exc
    if not all(math.isfinite(x) and abs(x) <= 1e7 for x in xs) or np.min(np.diff(xs)) <= 0:
        raise GeometryError("Station coordinates must be finite and strictly increasing.")
    stations = [{"id": str(s.get("id", "unnamed")), "x_m": x, "regions": section_regions.section_regions(s)}
                for s, x in zip(ordered, xs)]
    links = [{i: j for i, j, _ in section_regions.match_regions(a["regions"], b["regions"], min_overlap=min_overlap)}
             for a, b in zip(stations, stations[1:])]
    runs, visited = [], set()
    for s, station in enumerate(stations):
        for r in range(len(station["regions"])):
            if (s, r) in visited:
                continue
            path = [(s, r)]
            while path[-1][0] < len(stations) - 1 and path[-1][1] in links[path[-1][0]]:
                path.append((path[-1][0] + 1, links[path[-1][0]][path[-1][1]]))
            visited.update(path)
            runs.append(path)
    unlofted = [{"station": stations[s]["id"], "x_m": stations[s]["x_m"], "region": r,
                 "kind": stations[s]["regions"][r]["kind"],
                 "half_area_m2": section_regions.region_area(stations[s]["regions"][r]["rows_m"])}
                for path in runs if len(path) == 1 for s, r in path]
    solids, solid_volumes, run_reports, deviations, panel_fallbacks = [], [], [], [], []
    for path in (p for p in runs if len(p) >= 2):
        kind = stations[path[0][0]]["regions"][path[0][1]]["kind"]
        members = [_prepare_region(stations[s]["regions"][r]["rows_m"], kind, max_deviation_m) for s, r in path]
        start, pieces = 0, []
        while start < len(path) - 1:
            end = start + 1
            if not _fits(members[start:end + 1]):
                raise GeometryError(f"CAD complexity limit: region {path[start]} between stations "
                                    f"{stations[path[start][0]]['id']} and {stations[path[end][0]]['id']} exceeds "
                                    f"{MAX_COMMON_KNOTS} knots or {MAX_ESTIMATED_FACES} faces; use a larger bound.")
            while end + 1 < len(path) and _fits(members[start:end + 2]):
                end += 1
            pieces.append((start, end))
            start = end
        run_volume, run_simpson = 0.0, 0.0
        for first, last in pieces:
            outer_knots, inner_knots = _run_knots(members[first:last + 1])
            station_polygons = []
            for index in range(first, last + 1):
                report_progress('Building the hull', path[index][0] + 1, len(stations), unit='section')
                polygons, error = _station_polygons(members[index], outer_knots, inner_knots)
                deviations.append(error)
                station_polygons.append(polygons)
            label = f"{kind}:{stations[path[first][0]]['id']}-{stations[path[last][0]]['id']}"
            for side in range(len(station_polygons[0])):
                rings = [station_polygons[k][side] for k in range(len(station_polygons))]
                xs_run = [stations[path[index][0]]["x_m"] for index in range(first, last + 1)]
                profiles = [np.column_stack([np.full(len(ring), x), ring]) * 1000 for ring, x in zip(rings, xs_run)]
                for cap in (profiles[0], profiles[-1]):
                    if _planar_face(cap) is None:
                        raise GeometryError(f"Region loft {label} has a terminal station without area.")
                simpson = sum((x1 - x0) / 6 * (_shoelace(a) + 4 * _shoelace((a + b) / 2) + _shoelace(b))
                              for a, b, x0, x1 in zip(rings, rings[1:], xs_run, xs_run[1:]))
                light = _one_face_solid(profiles, simpson) if one_face_per_side else None
                if light is not None:
                    solid, volume = light
                else:
                    if one_face_per_side:
                        panel_fallbacks.append(label)
                    faces = []
                    for panel_index, (left, right) in enumerate(zip(profiles, profiles[1:])):
                        report_progress('Building the hull', path[first + panel_index][0] + 1,
                                        len(stations), unit='section')
                        faces.extend(_panel_faces(left, right))
                    faces += [_planar_face(profiles[0]), _planar_face(profiles[-1])]
                    report_progress('Closing the hull')
                    solid = _closed_solid(faces, label)
                    volume = solid.Volume() / 1e9
                    if abs(volume - simpson) > _REGION_VOLUME_AUDIT_TOLERANCE * max(simpson, 1e-12):
                        raise GeometryError(f"Region loft {label} failed the volume audit: kernel {volume:.9f} m3, "
                                            f"polygon prismatoid {simpson:.9f} m3.")
                solids.append(solid)
                solid_volumes.append(volume)
                run_volume += volume
                run_simpson += simpson
        run_reports.append({"kind": kind, "stations": [stations[s]["id"] for s, _ in path],
                            "regions": [r for _, r in path],
                            "pieces": [[stations[path[a][0]]["id"], stations[path[b][0]]["id"]] for a, b in pieces],
                            "volume_m3": run_volume, "prismatoid_volume_m3": run_simpson})
    if not solids:
        raise GeometryError("No region matches a region on a neighbouring station; nothing can be lofted.")
    compound = cq.Compound.makeCompound(solids)
    station_reports = [{"id": st["id"], "x_m": st["x_m"],
                        "regions": [{"kind": reg["kind"], "z_range_m": [float(reg["rows_m"][0, 0]), float(reg["rows_m"][-1, 0])],
                                     "half_area_m2": section_regions.region_area(reg["rows_m"])}
                                    for reg in st["regions"]],
                        "section_area_m2": 2 * section_regions.total_area(st["regions"])}
                       for st in stations]
    report = {
        "method": REGION_LOFT_METHOD, "side_faces": "one_bilinear_bspline_per_side" if one_face_per_side
        else "ruled_panels", "panel_fallback_pieces": panel_fallbacks, "decomposition": section_regions.DECOMPOSITION_METHOD,
        "maximum_allowed_half_breadth_deviation_m": float(max_deviation_m),
        "maximum_half_breadth_deviation_m": float(max(deviations)),
        "min_match_overlap": float(min_overlap),
        "stations": station_reports, "runs": run_reports, "unlofted_regions": unlofted,
        "solid_count": len(solids), "volume_m3": float(sum(r["volume_m3"] for r in run_reports)),
        "solid_volumes_m3": [float(volume) for volume in solid_volumes],
        "volume_audit": "each solid's kernel volume equals its polygon prismatoid volume within "
                        f"{_BSPLINE_VOLUME_AUDIT_TOLERANCE if one_face_per_side else _REGION_VOLUME_AUDIT_TOLERANCE:g} "
                        "relative",
        "uncertainty_scope": "CAD approximation and region matching of measured outlines only; excludes contour "
                             "identity, calibration, interpolation between stations, and source accuracy",
    }
    return compound, report


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


def export_geometry(shape: cq.Shape, out: Path, *, export_cad: bool = True,
                    expected_solids: int = 1) -> tuple[dict, dict]:
    """Write mesh.json and, on request, STEP, IGES, 3dm and STL; reload STEP and compare.

    ``expected_solids`` is 1 for ``build_hull`` and the solid count of a
    ``build_region_hull`` compound; the reloaded STEP must hold exactly that many.
    """
    report_progress('Measuring the hull')
    metrics = metrics_for(shape)
    tolerance_mm = max(0.5, metrics["beam_m"] * 1000 / 800)
    # CadQuery's convenience mesh/STL functions default to relative deflection.
    # Our number is in millimetres: premesh explicitly with absolute deflection
    # and one native meshing thread, then read that triangulation for mesh.json.
    report_progress('Making the mesh')
    BRepMesh_IncrementalMesh(shape.wrapped, tolerance_mm, False, 0.15, False)
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
        report_progress('Exporting STEP', 1, 4, unit='format')
        shape.exportStep(str(out / "model.step"), write_pcurves=False)
        report_progress('Exporting IGES', 2, 4, unit='format')
        export_iges(shape, out / "model.iges")
        report_progress('Exporting 3dm', 3, 4, unit='format')
        export_3dm([CadPart("hull", shape, "Hull")], out / "model.3dm")
        report_progress('Exporting STL', 4, 4, unit='format')
        shape.exportStl(str(out / "model.stl"), tolerance=tolerance_mm, angularTolerance=0.15,
                        relative=False, parallel=False)
        report_progress('Checking the STEP export')
        reread = cq.importers.importStep(str(out / "model.step")).val()
        if not reread.isValid() or len(reread.Solids()) != expected_solids:
            raise GeometryError("The exported STEP file failed independent reload validation.")
        reloaded = metrics_for(reread)
        rel = abs(reloaded["volume_m3"] - metrics["volume_m3"]) / metrics["volume_m3"]
        extent_error = max(abs(reloaded[k] - metrics[k]) / max(metrics[k], 1e-12) for k in ("length_m", "beam_m", "depth_m"))
        if rel > 1e-6 or extent_error > 1e-6:
            raise GeometryError("STEP round-trip altered geometry or units beyond tolerance.")
        metrics["step_roundtrip_relative_error"] = float(rel)
        metrics["step_roundtrip_extent_error"] = float(extent_error)
        exports.update({"step": "model.step", "step_units": "mm", "stl": "model.stl", "stl_units": "mm"})
        exports.update({"iges": "model.iges", "iges_units": "mm"})
        exports.update({"3dm": "model.3dm", "3dm_units": "mm"})
    metrics["mesh_vertices"] = len(vertices)
    metrics["mesh_faces"] = len(faces)
    metrics["mesh_deflection_mm"] = float(tolerance_mm)
    metrics["mesh_deflection_mode"] = "absolute"
    return exports, metrics
