"""Read body-plan station curves from a vector (DXF) lines plan.

This module turns the station curves of a DXF body plan into the half-section
records that :func:`vessel_reconstruction.geometry.build_hull` accepts:
``{"id", "x_m", "points_yz_m"}``. It measures the build/loft stage on vector
input; it is not a raster reader and does not change the raster pipeline.

The caller supplies the body-plan view (centreline, baseline, scale, region and
layers) and one entry per station: its longitudinal position ``x_m`` and the
drawing side on which it is drawn. Station identity comes from the caller as a
pick point on the curve or as an ordering rule; it is never inferred from a
reference model. Every value in a configuration is drawing evidence that a
person or an assistant read; this module records it and does not verify it.

The module abstains (``LinesDxfError``) instead of guessing when a station
curve is missing, ambiguous, crosses the centreline, or is not single-valued
in height. Coordinates: x forward, y to starboard (half-breadth >= 0),
z up from the declared baseline, all in metres.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import numpy as np

SUPPORTED_ENTITIES = ("LINE", "ARC", "POLYLINE", "LWPOLYLINE", "SPLINE")
# geometry.build_hull accepts at most this many points per section.
MAX_SECTION_POINTS = 1025


class LinesDxfError(ValueError):
    """A station cannot be read without guessing; ``kind`` names the reason."""

    def __init__(self, kind: str, message: str):
        super().__init__(message)
        self.kind = kind


@dataclass(frozen=True)
class BodyPlanView:
    """Where and how the body plan is drawn, in drawing units.

    ``units_per_metre`` converts drawing units to metres (1000 for a
    full-scale drawing in millimetres). ``bounds`` is (xmin, ymin, xmax, ymax)
    of the body-plan region; curves are clipped to it by vertex membership.
    ``flatten_tolerance`` is the maximum chord deviation used to turn arcs
    and splines into polylines; ``join_tolerance`` is the largest endpoint gap
    that joins two fragments of one station curve.
    """

    centreline_x: float
    baseline_y: float
    units_per_metre: float
    bounds: tuple[float, float, float, float]
    layers: tuple[str, ...]
    flatten_tolerance: float = 0.5
    join_tolerance: float = 1.0

    def __post_init__(self):
        values = (self.centreline_x, self.baseline_y, self.units_per_metre, *self.bounds,
                  self.flatten_tolerance, self.join_tolerance)
        if not all(isinstance(v, (int, float)) and math.isfinite(v) for v in values):
            raise LinesDxfError("invalid_view", "Body-plan view values must be finite numbers.")
        if self.units_per_metre <= 0 or self.flatten_tolerance <= 0 or self.join_tolerance < 0:
            raise LinesDxfError("invalid_view", "Scale and tolerances must be positive.")
        xmin, ymin, xmax, ymax = self.bounds
        if xmax <= xmin or ymax <= ymin:
            raise LinesDxfError("invalid_view", "Body-plan bounds must have positive area.")
        if not xmin <= self.centreline_x <= xmax:
            raise LinesDxfError("invalid_view", "The centreline must lie inside the body-plan bounds.")
        if not self.layers:
            raise LinesDxfError("invalid_view", "Name at least one station-curve layer.")


@dataclass(frozen=True)
class StationRequest:
    """One station to read. ``side`` is +1 when drawn right of the centreline.

    ``pick_xy`` is a drawing point on the station curve. ``extra_picks`` are
    further points that the drawing shows on the same station; if any of them
    resolves to a different curve, the station is drawn in several pieces and
    the reader abstains.
    """

    id: str
    x_m: float
    side: int
    pick_xy: tuple[float, float] | None = None
    extra_picks: tuple[tuple[float, float], ...] = ()
    evidence: str = ""


@dataclass(frozen=True)
class SideLine:
    """The drawn vertical side line shared by stations (wall-sided hull).

    A station curve that ends on this line (within ``tolerance_m``) below
    ``top_z_m`` continues up it to ``top_z_m``. With ``require_end`` a station
    curve must end on this line or at ``top_z_m``; otherwise it is incomplete.
    """

    y_m: float
    top_z_m: float
    tolerance_m: float = 0.002
    require_end: bool = True


def _entity_points(entity, tolerance: float) -> np.ndarray | None:
    from ezdxf import path as dxf_path

    try:
        path = dxf_path.make_path(entity)
        points = np.array([(v.x, v.y) for v in path.flattening(tolerance)], dtype=float)
    except Exception:
        return None
    if len(points) < 2 or not np.isfinite(points).all():
        return None
    keep = np.ones(len(points), dtype=bool)
    keep[1:] = np.any(np.diff(points, axis=0) != 0, axis=1)
    points = points[keep]
    return points if len(points) >= 2 else None


def read_view_curves(doc, view: BodyPlanView) -> list[np.ndarray]:
    """Flatten every supported station-layer entity that lies in the view."""
    xmin, ymin, xmax, ymax = view.bounds
    curves = []
    for entity in doc.modelspace():
        if entity.dxftype() not in SUPPORTED_ENTITIES or entity.dxf.layer not in view.layers:
            continue
        points = _entity_points(entity, view.flatten_tolerance)
        if points is None:
            continue
        inside = ((points[:, 0] >= xmin) & (points[:, 0] <= xmax)
                  & (points[:, 1] >= ymin) & (points[:, 1] <= ymax))
        if inside.all():
            curves.append(points)
    return curves


def chain_fragments(curves: Iterable[np.ndarray], tolerance: float) -> list[np.ndarray]:
    """Join fragments whose endpoints meet one-to-one within ``tolerance``.

    An endpoint that meets two or more other endpoints is a junction (for
    example where many stations meet the keel), so no join is made there.
    """
    curves = [np.asarray(c, dtype=float) for c in curves]
    ends = []  # (curve index, 0 for start / 1 for end, point)
    for index, curve in enumerate(curves):
        ends.append((index, 0, curve[0]))
        ends.append((index, 1, curve[-1]))
    points = np.array([e[2] for e in ends]) if ends else np.zeros((0, 2))
    partner: dict[int, int] = {}
    for i in range(len(ends)):
        distance = np.hypot(*(points - points[i]).T)
        close = [j for j in np.flatnonzero(distance <= tolerance) if j != i and ends[j][0] != ends[i][0]]
        if len(close) == 1:
            partner[i] = int(close[0])
    links = {i: j for i, j in partner.items() if partner.get(j) == i}
    used = [False] * len(curves)
    chains = []

    def end_id(curve: int, which: int) -> int:
        return 2 * curve + which

    for start in range(len(curves)):
        if used[start]:
            continue
        # Walk to one free end of the chain first, so each chain is built once.
        curve, entry = start, 0
        seen = {start}
        while end_id(curve, entry) in links:
            other = links[end_id(curve, entry)]
            nxt, nxt_which = divmod(other, 2)
            if nxt in seen:
                break
            seen.add(nxt)
            curve, entry = nxt, 1 - nxt_which
        pieces, current, which_in = [], curve, entry
        visited = set()
        while True:
            visited.add(current)
            used[current] = True
            piece = curves[current] if which_in == 0 else curves[current][::-1]
            pieces.append(piece if not pieces else piece[1:])
            exit_end = end_id(current, 1 - which_in)
            if exit_end not in links:
                break
            nxt, nxt_which = divmod(links[exit_end], 2)
            if nxt in visited:
                break
            current, which_in = nxt, nxt_which
        chains.append(np.vstack(pieces))
    return chains


def to_half_section_m(chain: np.ndarray, view: BodyPlanView, side: int) -> np.ndarray:
    """Convert drawing coordinates to (half-breadth, height) in metres."""
    if side not in (1, -1):
        raise LinesDxfError("invalid_station", "side must be +1 (right of centreline) or -1 (left).")
    y = side * (chain[:, 0] - view.centreline_x) / view.units_per_metre
    z = (chain[:, 1] - view.baseline_y) / view.units_per_metre
    return np.column_stack([y, z])


def single_valued_section(points_yz: np.ndarray, *, centreline_tolerance_m: float = 0.002,
                          flat_tolerance_m: float = 1e-6) -> np.ndarray:
    """Return a half-section with strictly increasing height, or abstain.

    A horizontal run at the lowest or highest height (a flat bottom or deck
    line) is reduced to its outermost point; build_hull closes it with a flat
    segment. Any other height reversal means the curve is not single-valued
    in height (for example a skeg or a tumblehome loop), and the station is
    refused rather than simplified.
    """
    points = np.asarray(points_yz, dtype=float)
    if points.ndim != 2 or points.shape[1] != 2 or len(points) < 2:
        raise LinesDxfError("invalid_curve", "A station curve needs at least two points.")
    if points[:, 0].min() < -centreline_tolerance_m:
        raise LinesDxfError("crosses_centreline", "The station curve crosses the centreline to the other side.")
    points[:, 0] = np.maximum(points[:, 0], 0.0)
    if points[-1, 1] < points[0, 1]:
        points = points[::-1]
    z = points[:, 1]
    bottom, top = z.min(), z.max()
    if top - bottom <= flat_tolerance_m:
        raise LinesDxfError("invalid_curve", "The station curve has no vertical extent.")
    low = np.abs(z - bottom) <= flat_tolerance_m
    high = np.abs(z - top) <= flat_tolerance_m
    middle = ~(low | high)
    kept = [np.array([[points[low, 0].max(), bottom]])]
    if middle.any():
        first, last = np.flatnonzero(middle)[[0, -1]]
        interior = points[first:last + 1]
        if (low[first:last + 1] | high[first:last + 1]).any():
            raise LinesDxfError("multi_valued_section", "The curve returns to its lowest or highest height; it is not single-valued.")
        if np.any(np.diff(interior[:, 1]) <= 0):
            raise LinesDxfError("multi_valued_section", "Height reverses along the station curve; a single half-breadth per height is not defined.")
        kept.append(interior)
    kept.append(np.array([[points[high, 0].max(), top]]))
    section = np.vstack(kept)
    return section


def resample_by_arc_length(section: np.ndarray, maximum: int = MAX_SECTION_POINTS) -> np.ndarray:
    """Keep every vertex if allowed; otherwise resample evenly along the curve.

    The first and last points are always kept. Even arc-length sampling of a
    strictly height-increasing polyline keeps heights strictly increasing.
    """
    if len(section) <= maximum:
        return section
    steps = np.hypot(*np.diff(section, axis=0).T)
    distance = np.concatenate([[0.0], np.cumsum(steps)])
    targets = np.linspace(0.0, distance[-1], maximum)
    y = np.interp(targets, distance, section[:, 0])
    z = np.interp(targets, distance, section[:, 1])
    return np.column_stack([y, z])


def _distance_to_polyline(point: np.ndarray, polyline: np.ndarray) -> float:
    a, b = polyline[:-1], polyline[1:]
    ab = b - a
    length2 = np.maximum((ab ** 2).sum(axis=1), 1e-30)
    t = np.clip(((point - a) * ab).sum(axis=1) / length2, 0.0, 1.0)
    nearest = a + t[:, None] * ab
    return float(np.hypot(*(nearest - point).T).min())


def pick_chain(chains: list[np.ndarray], pick_xy: tuple[float, float], *, tolerance: float,
               ambiguity_ratio: float = 2.0) -> int:
    """Index of the one chain that passes nearest to a declared pick point."""
    point = np.asarray(pick_xy, dtype=float)
    distances = np.array([_distance_to_polyline(point, c) for c in chains])
    if not len(distances):
        raise LinesDxfError("missing_curve", "No station curve exists in the declared view.")
    order = np.argsort(distances)
    best = int(order[0])
    if distances[best] > tolerance:
        raise LinesDxfError("missing_curve", f"No station curve passes within {tolerance} drawing units of the pick point.")
    if len(order) > 1 and distances[order[1]] <= max(tolerance, ambiguity_ratio * distances[best]) and distances[order[1]] <= tolerance:
        raise LinesDxfError("ambiguous_curve", "Two station curves pass near the pick point; identity is not resolved.")
    return best


def apply_side_line(section: np.ndarray, side_line: SideLine | None) -> tuple[np.ndarray, bool]:
    """Follow the side line to its top, or abstain if the curve stops elsewhere."""
    if side_line is None:
        return section, False
    last_y, last_z = section[-1]
    on_side = abs(last_y - side_line.y_m) <= side_line.tolerance_m
    at_top = last_z >= side_line.top_z_m - side_line.tolerance_m
    if on_side and not at_top:
        return np.vstack([section, [[last_y, side_line.top_z_m]]]), True
    if side_line.require_end and not (on_side or at_top):
        raise LinesDxfError("incomplete_curve", "The station curve stops before the side line or the declared top; it may be one piece of a split station.")
    return section, False


def read_stations(path: str | Path, view: BodyPlanView, stations: list[StationRequest], *,
                  pick_tolerance: float = 5.0, side_line: SideLine | None = None) -> dict:
    """Read the requested stations; return sections plus per-station abstentions."""
    import ezdxf

    doc = ezdxf.readfile(str(path))
    chains = chain_fragments(read_view_curves(doc, view), view.join_tolerance)
    sections, abstentions = [], []
    for request in stations:
        try:
            if request.pick_xy is None:
                raise LinesDxfError("missing_identity", "Each station needs a pick point on its curve.")
            index = pick_chain(chains, request.pick_xy, tolerance=pick_tolerance)
            for extra in request.extra_picks:
                if pick_chain(chains, extra, tolerance=pick_tolerance) != index:
                    raise LinesDxfError("multiple_pieces", "The station is drawn as separate pieces; one half-section curve is required.")
            half = single_valued_section(to_half_section_m(chains[index], view, request.side))
            half, extended = apply_side_line(half, side_line)
            half = resample_by_arc_length(half)
            sections.append({"id": request.id, "x_m": float(request.x_m),
                             "points_yz_m": half.tolist(),
                             "evidence": {"input_form": "dxf_vector_body_plan", "side": request.side,
                                          "pick_xy": list(request.pick_xy), "side_line_followed": extended,
                                          "note": request.evidence}})
        except LinesDxfError as exc:
            abstentions.append({"id": request.id, "x_m": float(request.x_m), "kind": exc.kind, "message": str(exc)})
    return {"sections": sections, "abstentions": abstentions, "chain_count": len(chains),
            "method": "dxf_body_plan_chains_v1"}
