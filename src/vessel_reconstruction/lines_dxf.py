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
    further points that the drawing shows on the same station. In the
    single-curve mode, a pick that resolves to a different curve means the
    station is drawn in several pieces and the reader abstains; in the region
    mode every picked curve is one piece of the station outline.

    ``top_z_m`` is where this station ends, read from the drawing (for example
    the profile outline at the station). A curve that ends on the side line
    follows it up to this height; without it, up to ``SideLine.top_z_m``.
    """

    id: str
    x_m: float
    side: int
    pick_xy: tuple[float, float] | None = None
    extra_picks: tuple[tuple[float, float], ...] = ()
    evidence: str = ""
    top_z_m: float | None = None
    top_evidence: str = ""


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


def _station_top(side_line: SideLine, top_z_m: float | None) -> float:
    if top_z_m is None:
        return side_line.top_z_m
    if not isinstance(top_z_m, (int, float)) or not math.isfinite(top_z_m):
        raise LinesDxfError("invalid_station", "top_z_m must be a finite height.")
    return float(top_z_m)


def apply_side_line(section: np.ndarray, side_line: SideLine | None,
                    top_z_m: float | None = None) -> tuple[np.ndarray, bool]:
    """Follow the side line to the station top, or abstain if the curve stops elsewhere.

    The station top is ``top_z_m`` when the drawing gives one for this
    station, otherwise the side line's declared top.
    """
    if side_line is None:
        return section, False
    top = _station_top(side_line, top_z_m)
    last_y, last_z = section[-1]
    on_side = abs(last_y - side_line.y_m) <= side_line.tolerance_m
    at_top = last_z >= top - side_line.tolerance_m
    if on_side and not at_top:
        return np.vstack([section, [[last_y, top]]]), True
    if side_line.require_end and not (on_side or at_top):
        raise LinesDxfError("incomplete_curve", "The station curve stops before the side line or the declared top; it may be one piece of a split station.")
    return section, False


def outline_ring(piece_yz: np.ndarray, *, side_line: SideLine | None, top_z_m: float | None,
                 centreline_closure_m: float) -> tuple[np.ndarray, dict]:
    """Close one station piece into a ring of the starboard half-plane.

    The piece is ordered from its lower end. Its upper end must be on the
    centreline (within ``centreline_closure_m``), on the side line (which is
    followed up to the station top), or at the station top; it is then closed
    horizontally to the centreline. The lower end is closed horizontally to the
    centreline (a flat bottom, as ``build_hull`` closes a keel off the
    centreline). The centreline closes the ring. A piece that ends anywhere
    else is incomplete and the station is refused.
    """
    points = np.asarray(piece_yz, dtype=float)
    if points[-1, 1] < points[0, 1]:
        points = points[::-1]
    if np.all(points[0] == points[-1]):
        return points[:-1], {"top_closure": "closed_piece", "side_line_followed": False}
    top_y, top_z = points[-1]
    ring = list(points)
    followed = False
    if top_y <= centreline_closure_m:
        closure = "centreline"
    elif side_line is None or not side_line.require_end:
        closure = "free_end"
    else:
        top = _station_top(side_line, top_z_m)
        on_side = abs(top_y - side_line.y_m) <= side_line.tolerance_m
        if on_side and top_z < top - side_line.tolerance_m:
            ring.append(np.array([top_y, top]))
            top_z, closure, followed = top, "side_line", True
        elif top_z >= top - side_line.tolerance_m:
            closure = "station_top"
        else:
            raise LinesDxfError("incomplete_curve", "A station piece stops before the centreline, the side line or the "
                                "station top; it may be one piece of a split station.")
    if top_y > 0 or followed:
        ring.append(np.array([0.0, top_z]))
    if points[0, 0] > 0:
        ring.append(np.array([0.0, points[0, 1]]))
    return np.vstack(ring), {"top_closure": closure, "side_line_followed": followed,
                             "bottom_end_yz_m": points[0].tolist(), "top_end_yz_m": points[-1].tolist()}


def _picked_chains(request: StationRequest, chains: list[np.ndarray], tolerance: float) -> list[int]:
    if request.pick_xy is None:
        raise LinesDxfError("missing_identity", "Each station needs a pick point on its curve.")
    picked = []
    for point in (request.pick_xy, *request.extra_picks):
        index = pick_chain(chains, point, tolerance=tolerance)
        if index not in picked:
            picked.append(index)
    return picked


def _read_region_station(request: StationRequest, chains: list[np.ndarray], view: BodyPlanView, *,
                         pick_tolerance: float, side_line: SideLine | None, centreline_closure_m: float) -> dict:
    """One station as closed outline rings and their one-interval-per-height regions."""
    from .errors import GeometryError
    from .section_regions import decompose_outline

    rings, pieces = [], []
    for index in _picked_chains(request, chains, pick_tolerance):
        half = to_half_section_m(chains[index], view, request.side)
        if half[:, 0].min() < -centreline_closure_m:
            raise LinesDxfError("crosses_centreline", "A station piece crosses the centreline to the other side.")
        half[:, 0] = np.maximum(half[:, 0], 0.0)
        ring, closure = outline_ring(half, side_line=side_line, top_z_m=request.top_z_m,
                                     centreline_closure_m=centreline_closure_m)
        rings.append(ring)
        pieces.append({"chain_points": len(half), **closure})
    try:
        regions = decompose_outline([ring.tolist() for ring in rings], section_id=request.id)
    except GeometryError as exc:
        raise LinesDxfError("invalid_outline", str(exc)) from exc
    return {"id": request.id, "x_m": float(request.x_m),
            "regions": [{"kind": r["kind"], "rows_m": r["rows_m"]} for r in regions],
            "outline_rings_yz_m": [ring.tolist() for ring in rings],
            "evidence": {"input_form": "dxf_vector_body_plan", "reading": "outline_regions", "side": request.side,
                         "pick_xy": list(request.pick_xy), "extra_picks": [list(p) for p in request.extra_picks],
                         "pieces": pieces, "region_count": len(regions),
                         "region_kinds": [r["kind"] for r in regions],
                         "side_line_followed": any(p["side_line_followed"] for p in pieces),
                         "top_z_m": request.top_z_m, "top_evidence": request.top_evidence,
                         "centreline_closure_m": centreline_closure_m, "note": request.evidence}}


def read_stations(path: str | Path, view: BodyPlanView, stations: list[StationRequest], *,
                  pick_tolerance: float = 5.0, side_line: SideLine | None = None,
                  regions: bool = False, centreline_closure_m: float = 0.002) -> dict:
    """Read the requested stations; return sections plus per-station abstentions.

    With ``regions=False`` (default) each station must be one curve with one
    half-breadth per height (``points_yz_m``, accepted by ``build_hull``).
    With ``regions=True`` each station may have several pieces (all picks) and
    any number of material intervals per height; it is returned as closed
    outline rings and regions for ``geometry.build_region_hull``.
    """
    from .dxf_documents import read_document

    if not math.isfinite(centreline_closure_m) or not 0 <= centreline_closure_m <= 1.0:
        raise LinesDxfError("invalid_view", "centreline_closure_m must be a finite length from 0 to 1 m.")
    doc = read_document(path)
    chains = chain_fragments(read_view_curves(doc, view), view.join_tolerance)
    sections, abstentions = [], []
    for request in stations:
        try:
            if regions:
                sections.append(_read_region_station(request, chains, view, pick_tolerance=pick_tolerance,
                                                     side_line=side_line, centreline_closure_m=centreline_closure_m))
                continue
            picked = _picked_chains(request, chains, pick_tolerance)
            if len(picked) > 1:
                raise LinesDxfError("multiple_pieces", "The station is drawn as separate pieces; one half-section curve is required.")
            half = single_valued_section(to_half_section_m(chains[picked[0]], view, request.side))
            half, extended = apply_side_line(half, side_line, request.top_z_m)
            half = resample_by_arc_length(half)
            sections.append({"id": request.id, "x_m": float(request.x_m),
                             "points_yz_m": half.tolist(),
                             "evidence": {"input_form": "dxf_vector_body_plan", "side": request.side,
                                          "pick_xy": list(request.pick_xy), "side_line_followed": extended,
                                          "top_z_m": request.top_z_m, "top_evidence": request.top_evidence,
                                          "note": request.evidence}})
        except LinesDxfError as exc:
            abstentions.append({"id": request.id, "x_m": float(request.x_m), "kind": exc.kind, "message": str(exc)})
    return {"sections": sections, "abstentions": abstentions, "chain_count": len(chains),
            "method": "dxf_body_plan_outline_regions_v1" if regions else "dxf_body_plan_chains_v1"}


# Cross-view station identity ------------------------------------------------------
#
# A body-plan curve without a label can be identified by another view of the
# same drawing: the half-breadth plan gives, for each drawn waterline, the
# half-breadth along the ship. A station curve must show the same
# half-breadths at the waterline heights as the plan shows at its frame.


def _level_crossings(points: np.ndarray, axis: int, level: float) -> np.ndarray:
    """Values of the other coordinate where a polyline crosses ``axis == level``."""
    a, b = points[:-1], points[1:]
    low, high = np.minimum(a[:, axis], b[:, axis]), np.maximum(a[:, axis], b[:, axis])
    hit = (low <= level) & (level <= high) & (a[:, axis] != b[:, axis])
    t = (level - a[hit, axis]) / (b[hit, axis] - a[hit, axis])
    other = 1 - axis
    return a[hit, other] + t * (b[hit, other] - a[hit, other])


def outer_half_breadth_at(curve_yz: np.ndarray, z_m: float) -> float:
    """Largest half-breadth where a station curve (y, z metres) crosses height z; NaN if none."""
    values = _level_crossings(np.asarray(curve_yz, dtype=float), 1, z_m)
    return float(values.max()) if len(values) else math.nan


def plan_half_breadth_at(chains_xy: list[np.ndarray], x_drawing: float, centreline_y: float,
                         units_per_metre: float) -> float:
    """Largest half-breadth of plan-view waterline chains at drawing abscissa x; NaN if none."""
    values = [float(v) for chain in chains_xy
              for v in _level_crossings(np.asarray(chain, dtype=float), 0, x_drawing)]
    return (max(values) - centreline_y) / units_per_metre if values else math.nan


def cross_view_identity(curves: dict[str, np.ndarray], references: dict[str, dict[float, float]], *,
                        accept_rms_m: float = 0.05, ambiguity_ratio: float = 2.0,
                        min_heights: int = 3) -> tuple[dict[str, str], list[dict]]:
    """Match unlabelled station curves to frames by half-breadths at waterline heights.

    ``curves`` maps a curve key to its half-section (y, z metres).
    ``references`` maps a frame name to {waterline height: plan half-breadth}.
    A curve takes its best frame only when (1) at least ``min_heights``
    heights are compared, (2) the RMS difference is at most ``accept_rms_m``,
    (3) the second-best frame is at least ``ambiguity_ratio`` times worse, and
    (4) no other curve takes the same frame. Otherwise the curve is refused.
    The ledger records the best comparisons and the decision for each curve.
    """
    ledger, best = [], {}
    for key, curve in curves.items():
        scores = []
        for frame, table in references.items():
            pairs = [(outer_half_breadth_at(curve, z), hb) for z, hb in table.items()]
            pairs = [(c, r) for c, r in pairs if math.isfinite(c) and math.isfinite(r)]
            if len(pairs) >= min_heights:
                difference = np.array([c - r for c, r in pairs])
                scores.append((float(np.sqrt(np.mean(difference ** 2))), frame, len(pairs)))
        scores.sort()
        entry = {"curve": key,
                 "candidates": [{"frame": f, "rms_m": round(s, 5), "heights": n} for s, f, n in scores[:3]]}
        if not scores:
            entry["decision"] = "refused: too few comparable heights"
        elif scores[0][0] > accept_rms_m:
            entry["decision"] = f"refused: best RMS {scores[0][0]:.3f} m exceeds {accept_rms_m} m"
        elif len(scores) > 1 and scores[1][0] < ambiguity_ratio * scores[0][0]:
            entry["decision"] = f"refused: second frame within a factor {ambiguity_ratio}"
        else:
            best[key] = scores[0][1]
            entry["decision"] = f"frame {scores[0][1]}"
        ledger.append(entry)
    claimed: dict[str, list[str]] = {}
    for key, frame in best.items():
        claimed.setdefault(frame, []).append(key)
    assigned = {}
    for entry in ledger:
        frame = best.get(entry["curve"])
        if frame is None:
            continue
        if len(claimed[frame]) > 1:
            entry["decision"] = f"refused: frame {frame} is also best for {sorted(claimed[frame])}"
        else:
            assigned[entry["curve"]] = frame
    return assigned, ledger
