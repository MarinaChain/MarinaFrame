"""Lines-drawing geometry: waterlines, buttocks, profile and deck line of one factory hull.

A full lines drawing has three views. The body plan uses the existing station sections
(``Hull.drawn_section``). This module adds the cuts of the other two views:

- waterline: horizontal plane z = const; drawn in the half-breadth plan as (x, y), y >= 0;
- buttock: longitudinal vertical plane y = const; drawn in the profile as (x, z);
- profile: the buttock at ``PROFILE_OFFSET_M`` (just off the centreplane), which gives the keel,
  stem and stern contour also for half hulls whose centreplane face lies exactly on y = 0; plus the
  keel line, the lowest centreline point of dense station sections, where a hull meets the centreplane
  only tangentially and the offset buttock misses it (the DTMB 5415 run aft);
- deck line: the top outer point of dense station sections; drawn in plan (x, y) and profile (x, z).

Exact hulls (``brep``) are cut with OpenCascade plane sections of the native shape, as the body plan
is. Ship-D hulls are cut from the same triangle mesh that their body plans and truth come from.

``hulls.py``, ``render.py`` and ``truth.py`` are hashed by the sealed v2 and v3 manifests, so this
code lives in a new module and only calls them.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from benchmarks.gunnerus.hull_metrics import crossings

from . import hulls as H
from . import render as R
from . import truth as T

X_AXIS, Y_AXIS, Z_AXIS = 0, 1, 2
# Buttock plane used for the profile contour. Half hulls often have a centreplane face exactly at y = 0,
# where a plane section is degenerate. 5 mm is 0.1 px at the largest drawing scale.
PROFILE_OFFSET_M = 0.005
# Waterlines and buttocks closer than this fraction to the hull top or the maximum half-breadth are not
# drawn as curves: the plane touches the hull only tangentially there.
CURVE_LIMIT_FRACTION = 0.995
# Points within this distance of a datum plane count as lying on it (centreplane faces, flat deck lids).
ON_PLANE_TOL_M = 1.0e-3
DECK_LINE_STEP_M = 1.0
# Waterline grid and buttock grid use the same step rule as the body-plan grid (render._draw_frame).
WATERLINE_GRID_LINES = 8
BUTTOCK_GRID_LINES = 6


# --- plane cuts ------------------------------------------------------------------------------
def exact_plane_cut(shape, frame: H.Frame, axis: int, value_m: float, deflection_native: float) -> list[np.ndarray]:
    """Exact OpenCascade section of a native shape by the canonical plane ``axis = value_m``.

    Returns polylines of canonical (x, y, z) points in metres. Same method as ``hulls.exact_section``,
    for any of the three canonical axes.
    """
    from OCP.BRepAdaptor import BRepAdaptor_Curve
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Section
    from OCP.GCPnts import GCPnts_QuasiUniformDeflection
    from OCP.gp import gp_Dir, gp_Pln, gp_Pnt
    from OCP.TopAbs import TopAbs_EDGE
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopoDS import TopoDS

    native_axis = frame.axes[axis]
    origin = [0.0, 0.0, 0.0]
    origin[native_axis] = frame.origin[native_axis] + value_m / frame.scale * frame.signs[axis]
    normal = [0.0, 0.0, 0.0]
    normal[native_axis] = 1.0
    section = BRepAlgoAPI_Section(shape, gp_Pln(gp_Pnt(*origin), gp_Dir(*normal)), False)
    section.Build()
    if not section.IsDone():
        raise RuntimeError(f"section failed at axis {axis} = {value_m}")
    polylines = []
    explorer = TopExp_Explorer(section.Shape(), TopAbs_EDGE)
    while explorer.More():
        curve = BRepAdaptor_Curve(TopoDS.Edge_s(explorer.Current()))
        sampler = GCPnts_QuasiUniformDeflection(curve, deflection_native)
        if sampler.IsDone() and sampler.NbPoints() >= 2:
            points = [sampler.Value(i) for i in range(1, sampler.NbPoints() + 1)]
        else:
            points = [curve.Value(float(t)) for t in np.linspace(curve.FirstParameter(), curve.LastParameter(), 65)]
        native = np.array([[p.X(), p.Y(), p.Z()] for p in points])
        polylines.append(frame.apply(native))
        explorer.Next()
    return polylines


def mesh_plane_cut(triangles: np.ndarray, axis: int, value_m: float) -> list[np.ndarray]:
    """Cut a canonical triangle mesh by the plane ``axis = value_m``; two-point (x, y, z) segments.

    As ``hull_metrics.cut_mesh``, the plane is moved by 0.1 micrometre so that no vertex lies on it.
    """
    value_m = value_m + 1.0e-7
    coordinate = triangles[:, :, axis]
    candidates = triangles[(coordinate.min(axis=1) < value_m) & (coordinate.max(axis=1) > value_m)]
    segments = []
    for triangle in candidates:
        points = []
        for first, second in ((0, 1), (1, 2), (2, 0)):
            p, q = triangle[first], triangle[second]
            if (p[axis] - value_m) * (q[axis] - value_m) < 0:
                t = (value_m - p[axis]) / (q[axis] - p[axis])
                points.append(p + t * (q - p))
        if len(points) == 2:
            segments.append(np.array(points))
    return segments


def plane_cut(hull: H.Hull, axis: int, value_m: float) -> list[np.ndarray]:
    """Chained in-plane polylines of the hull cut by ``axis = value_m``.

    In-plane coordinates: (x, y) for a waterline (axis z), (x, z) for a buttock (axis y).
    """
    if hull.shape is not None:
        pieces = exact_plane_cut(hull.shape, hull.frame, axis, value_m, H.TRUTH_DEFLECTION_M / hull.frame.scale)
    else:
        pieces = mesh_plane_cut(hull.triangles, axis, value_m)
    keep = [a for a in (X_AXIS, Y_AXIS, Z_AXIS) if a != axis]
    return H.chain_polylines([piece[:, keep] for piece in pieces])


def drop_on_line(polylines: list[np.ndarray], column: int, value: float, tol: float = ON_PLANE_TOL_M) -> list[np.ndarray]:
    """Remove segments whose two ends both lie within ``tol`` of ``coordinate[column] = value``.

    Used for centreplane faces of half hulls (waterlines) and flat deck lids (buttocks).
    """
    result = []
    for line in polylines:
        on = np.abs(line[:, column] - value) <= tol
        run = [line[0]]
        for index in range(1, len(line)):
            if on[index] and on[index - 1]:
                if len(run) >= 2:
                    result.append(np.array(run))
                run = [line[index]]
            else:
                run.append(line[index])
        if len(run) >= 2:
            result.append(np.array(run))
    return result


def starboard(polylines: list[np.ndarray]) -> list[np.ndarray]:
    """Keep y >= 0 of (x, y) polylines (``hulls.clip_half`` works on the first column)."""
    swapped = H.clip_half([line[:, ::-1] for line in polylines])
    return [line[:, ::-1] for line in swapped]


def waterline(hull: H.Hull, z_m: float) -> list[np.ndarray]:
    return drop_on_line(starboard(plane_cut(hull, Z_AXIS, z_m)), 1, 0.0)


def buttock(hull: H.Hull, y_m: float) -> list[np.ndarray]:
    return drop_on_line(plane_cut(hull, Y_AXIS, y_m), 1, hull.depth_m)


def deck_and_keel(hull: H.Hull, step_m: float = DECK_LINE_STEP_M) -> tuple[np.ndarray, np.ndarray]:
    """Deck edge (x, y, z) and keel line (x, z) from station sections every ``step_m``.

    Deck edge: the top outer point of each section. Keel: the lowest point on the centreplane; sections
    that do not reach the centreplane (a gap between skegs) break the keel line there. A rise steeper
    than 45 degrees between samples (stem, bulb, stern) also breaks it: the 1 m samples cannot follow
    such a contour, and the offset buttock (``profile``) draws it exactly.
    """
    deck, keel = [], []
    for x in np.arange(step_m / 2, hull.length_m, step_m):
        curves = R.clean_deck_edge(hull.drawn_section(float(x)), hull.depth_m)
        if not curves:
            continue
        points = np.vstack(curves)
        top = float(points[:, 1].max())
        near_top = points[points[:, 1] >= top - ON_PLANE_TOL_M]
        deck.append((float(x), float(near_top[:, 0].max()), top))
        on_centreplane = points[points[:, 0] <= ON_PLANE_TOL_M]
        keel.append((float(x), float(on_centreplane[:, 1].min()) if len(on_centreplane) else np.nan))
    deck_rows = np.array(deck) if deck else np.zeros((0, 3))
    keel_rows = []
    for row in keel:
        if keel_rows and np.isfinite(row[1]) and np.isfinite(keel_rows[-1][1]) and abs(row[1] - keel_rows[-1][1]) > step_m:
            keel_rows.append((row[0], np.nan))
        keel_rows.append(row)
    return deck_rows, _split_at_gaps(np.array(keel_rows) if keel_rows else np.zeros((0, 2)))


def _split_at_gaps(rows: np.ndarray) -> list[np.ndarray]:
    """Polylines of the finite rows; a NaN row ends a polyline."""
    pieces, run = [], []
    for row in rows:
        if np.isfinite(row).all():
            run.append(row)
        else:
            if len(run) >= 2:
                pieces.append(np.array(run))
            run = []
    if len(run) >= 2:
        pieces.append(np.array(run))
    return pieces


def grid_heights(depth_m: float) -> tuple[float, list[float]]:
    """Waterline step of the body-plan grid, and the heights drawn as waterline curves."""
    step = R._nice_step(depth_m, WATERLINE_GRID_LINES)
    heights = [round(k * step, 6) for k in range(1, int(depth_m / step) + 2) if k * step < CURVE_LIMIT_FRACTION * depth_m]
    return step, heights


def grid_offsets(max_half_breadth_m: float) -> tuple[float, list[float]]:
    """Buttock step of the body-plan grid, and the offsets drawn as buttock curves."""
    step = R._nice_step(max_half_breadth_m, BUTTOCK_GRID_LINES)
    offsets = [round(k * step, 6) for k in range(1, int(max_half_breadth_m / step) + 2)
               if k * step < CURVE_LIMIT_FRACTION * max_half_breadth_m]
    return step, offsets


# --- one hull's lines --------------------------------------------------------------------------
@dataclass
class Lines:
    """Every curve of one lines drawing, in canonical metres."""

    hull_id: str
    length_m: float
    depth_m: float
    max_half_breadth_m: float
    stations: list  # render.Station (body plan)
    waterline_step_m: float
    buttock_step_m: float
    waterlines: dict = field(default_factory=dict)  # z -> [(x, y) polylines]
    buttocks: dict = field(default_factory=dict)  # y -> [(x, z) polylines]
    profile: list = field(default_factory=list)  # [(x, z) polylines]
    deck: np.ndarray = field(default_factory=lambda: np.zeros((0, 3)))  # (x, y, z) rows
    keel: list = field(default_factory=list)  # [(x, z) polylines] lowest centreplane point of sections
    draft_m: float = 0.0
    waterline_length_m: float = 0.0  # length of the waterline at draft_m (LWL in the title block)

    def to_json(self) -> dict:
        def lines_json(polylines):
            return [np.round(p, 5).tolist() for p in polylines]

        return {"hull_id": self.hull_id, "length_m": self.length_m, "depth_m": self.depth_m,
                "max_half_breadth_m": self.max_half_breadth_m, "profile_offset_y_m": PROFILE_OFFSET_M,
                "stations": [{"id": s.station_id, "x_m": s.x_m, "yz_m": lines_json(s.curves)} for s in self.stations],
                "waterlines": [{"z_m": z, "xy_m": lines_json(c)} for z, c in self.waterlines.items()],
                "buttocks": [{"y_m": y, "xz_m": lines_json(c)} for y, c in self.buttocks.items()],
                "draft_m": self.draft_m, "waterline_length_m": self.waterline_length_m,
                "profile_xz_m": lines_json(self.profile), "deck_xyz_m": np.round(self.deck, 5).tolist(),
                "keel_xz_m": lines_json(self.keel)}


def build_lines(hull: H.Hull, stations: list, draft_m: float) -> Lines:
    """Every curve of the drawing. ``draft_m`` is the design waterline printed in the title block."""
    waterline_step, heights = grid_heights(hull.depth_m)
    buttock_step, offsets = grid_offsets(hull.max_half_breadth_m)
    lines = Lines(hull.hull_id, hull.length_m, hull.depth_m, hull.max_half_breadth_m, stations, waterline_step, buttock_step)
    lines.waterlines = {z: waterline(hull, z) for z in heights}
    lines.buttocks = {y: buttock(hull, y) for y in offsets}
    lines.profile = buttock(hull, PROFILE_OFFSET_M)
    lines.deck, lines.keel = deck_and_keel(hull)
    lines.draft_m = draft_m
    design = waterline(hull, draft_m)
    if design:
        x_values = np.concatenate([line[:, 0] for line in design])
        lines.waterline_length_m = float(x_values.max() - x_values.min())
    return lines


# --- cross-view consistency ----------------------------------------------------------------------
def _outer(values: np.ndarray) -> float | None:
    return float(np.abs(values).max()) if len(values) else None


def waterline_half_breadth_at(polylines: list[np.ndarray], x_m: float) -> float | None:
    """Outer half-breadth of waterline (x, y) polylines at x, or None if the waterline does not reach x."""
    (values,) = crossings([line[:, ::-1] for line in polylines], np.array([x_m]))
    return _outer(values)


def station_half_breadth_at(curves: list[np.ndarray], z_m: float) -> float | None:
    """Outer half-breadth of station (y, z) curves at height z, or None."""
    (values,) = crossings(curves, np.array([z_m]))
    return _outer(values)


def cross_check(lines: Lines, ppm: float) -> list[dict]:
    """Half-breadth of each waterline in plan at each station x against the body-plan station at that z.

    Returns one row per (station, waterline) pair that both views draw, with the difference in pixels at
    ``ppm`` pixels per metre.
    """
    rows = []
    for station in lines.stations:
        for z, polylines in lines.waterlines.items():
            plan = waterline_half_breadth_at(polylines, station.x_m)
            body = station_half_breadth_at(station.curves, z)
            if plan is None or body is None:
                continue
            rows.append({"station": station.station_id, "x_m": station.x_m, "z_m": z, "plan_y_m": plan,
                         "body_y_m": body, "difference_px": abs(plan - body) * ppm})
    return rows
