"""Multi-region station sections: decomposition, matching and correspondence.

A single half-section ``points_yz_m`` gives one half-breadth per height. Some
stations do not: a twin skeg hangs below a tunnel roof, and a bulb can be drawn
apart from the bow above it. This module describes such a station as a set of
*regions*. In a region every height ``z`` has exactly one material interval
``[y_in(z), y_out(z)]`` on the starboard half-plane (``y >= 0``):

- ``centreline`` region: ``y_in = 0``; mirrored, it is one cross-section piece
  through the centreplane (the usual hull section);
- ``offset`` region: ``y_in > 0`` inside the region; mirrored, it is two
  pieces, one on each side (for example the twin skegs).

A region is stored as rows ``[z, y_in, y_out]`` with non-decreasing ``z``.
Two consecutive rows at the same height are a horizontal step in a boundary.

The decomposition is exact for polygon outlines: the outline is cut at every
vertex height, so in each horizontal slab every interval end lies on one
straight edge. No smoothing, minimum breadth or hull-family fit is applied.
This module needs only NumPy; :func:`vessel_reconstruction.geometry.build_region_hull`
lofts the regions into CAD.
"""
from __future__ import annotations


import numpy as np

from .errors import GeometryError

DECOMPOSITION_METHOD = "z_monotone_slab_regions_v1"
CENTRELINE = "centreline"
OFFSET = "offset"
REGION_KINDS = (CENTRELINE, OFFSET)
MAX_RING_POINTS = 20_000
MAX_RINGS = 16
MAX_COORDINATE_M = 1e7
# Interval ends and heights closer than this are the same value. It is a
# floating-point equality tolerance in metres, not a modelling tolerance.
EQUAL_M = 1e-9
# Vertex heights closer than this (1 micrometre, far below drawing precision)
# are one height; see _snap_heights.
HEIGHT_SNAP_M = 1e-6
# A region matches a region on the next station only if their overlap is at
# least this fraction of their union area (and the match is mutual). Station
# spacing moves a hull region by much less than this; a skeg tip or a wedge
# that changes shape quickly may fall below it and then ends with a closure.
MIN_MATCH_OVERLAP = 0.2


def _as_ring(ring, index: int, section_id: str) -> np.ndarray:
    try:
        points = np.asarray(ring, dtype=float)
    except (TypeError, ValueError, OverflowError) as exc:
        raise GeometryError(f"Section {section_id}: outline ring {index} is not numeric.") from exc
    if points.ndim != 2 or points.shape[1] != 2 or not 3 <= len(points) <= MAX_RING_POINTS:
        raise GeometryError(f"Section {section_id}: outline ring {index} needs 3..{MAX_RING_POINTS} (y, z) points.")
    if not np.isfinite(points).all() or np.max(np.abs(points)) > MAX_COORDINATE_M:
        raise GeometryError(f"Section {section_id}: outline ring {index} has nonfinite or unbounded points.")
    if np.all(points[0] == points[-1]):
        points = points[:-1]
    if points[:, 0].min() < 0:
        raise GeometryError(f"Section {section_id}: outline ring {index} crosses the centreline.")
    return points


def _snap_heights(rings: list[np.ndarray]) -> list[np.ndarray]:
    """Give vertex heights closer than HEIGHT_SNAP_M one common value.

    Drawn curves often hold vertices whose heights differ by rounding only
    (a flat bottom drawn 1e-12 m off level). Each such height difference would
    open a slab of no physical meaning and split a region. Heights are grouped
    when consecutive sorted values are closer than HEIGHT_SNAP_M; a group takes
    its lowest value. The change to any vertex is below the group span.
    """
    heights = np.unique(np.concatenate([ring[:, 1] for ring in rings]))
    group_start = np.concatenate([[True], np.diff(heights) > HEIGHT_SNAP_M])
    representative = heights[np.flatnonzero(group_start)[np.cumsum(group_start) - 1]]
    snapped = []
    for ring in rings:
        ring = ring.copy()
        ring[:, 1] = representative[np.searchsorted(heights, ring[:, 1])]
        keep = np.any(ring != np.roll(ring, 1, axis=0), axis=1)
        snapped.append(ring[keep] if keep.sum() >= 3 else ring)
    return snapped


def piece_ring(outer, inner=None, *, section_id: str = "section") -> np.ndarray:
    """Close one traced piece of a station into a ring of the starboard half-plane.

    ``outer`` and ``inner`` are (y, z) samples with increasing z. Without an
    inner curve the piece is closed horizontally to the centreline at its
    lowest and highest sample and along the centreline (the usual hull
    half-section). With an inner curve the material lies between the inner and
    the outer curve; the ring is the outer curve upward and the inner curve
    downward. No breadth or shape is added.
    """
    outer = np.asarray(outer, dtype=float)
    if inner is None:
        ring = [[0.0, outer[0, 1]]] if outer[0, 0] > 0 else []
        ring.extend(outer.tolist())
        if outer[-1, 0] > 0:
            ring.append([0.0, outer[-1, 1]])
        return np.asarray(ring, dtype=float)
    inner = np.asarray(inner, dtype=float)
    heights = np.union1d(outer[:, 1], inner[:, 1])
    if np.any(np.interp(heights, inner[:, 1], inner[:, 0]) > np.interp(heights, outer[:, 1], outer[:, 0])):
        raise GeometryError(f"Section {section_id}: the inner curve of a piece lies outside its outer curve.")
    return np.vstack([outer, inner[::-1]])


def ring_area(ring: np.ndarray) -> float:
    """Absolute shoelace area of one closed ring in the (y, z) half-plane."""
    y, z = ring[:, 0], ring[:, 1]
    return 0.5 * abs(float(np.dot(y, np.roll(z, -1)) - np.dot(z, np.roll(y, -1))))


def region_area(rows) -> float:
    """Exact area of a region whose boundaries are linear between rows."""
    rows = np.asarray(rows, dtype=float)
    width = rows[:, 2] - rows[:, 1]
    return float(np.sum(np.diff(rows[:, 0]) * (width[:-1] + width[1:]) / 2))


def _slab_intervals(edges: dict, h0: float, h1: float, section_id: str) -> list[tuple]:
    """Material intervals of one slab: (in0, out0, in1, out1, on_centreline).

    ``in0``/``out0`` are the interval ends at the slab bottom ``h0`` and
    ``in1``/``out1`` at its top ``h1``. Each ring is paired even-odd on its
    own; intervals of different rings must not overlap.
    """
    spanning = np.flatnonzero(edges["sloped"] & (edges["low"] <= h0) & (edges["high"] >= h1))
    z0, z1 = edges["z0"][spanning], edges["z1"][spanning]
    y0, y1 = edges["y0"][spanning], edges["y1"][spanning]
    at_bottom = y0 + (h0 - z0) / (z1 - z0) * (y1 - y0)
    at_top = y0 + (h1 - z0) / (z1 - z0) * (y1 - y0)
    middle = (at_bottom + at_top) / 2
    intervals = []
    for ring in np.unique(edges["ring"][spanning]):
        mine = np.flatnonzero(edges["ring"][spanning] == ring)
        mine = mine[np.argsort(middle[mine], kind="stable")]
        if len(mine) % 2:
            raise GeometryError(f"Section {section_id}: an outline ring is not closed at height {h0:.6f} m.")
        for left, right in zip(mine[0::2], mine[1::2]):
            intervals.append((at_bottom[left], at_bottom[right], at_top[left], at_top[right],
                              bool(edges["centreline"][spanning][left]), middle[left], middle[right]))
    intervals.sort(key=lambda item: item[5])
    for first, second in zip(intervals, intervals[1:]):
        if second[5] < first[6] - EQUAL_M:
            raise GeometryError(f"Section {section_id}: outline pieces overlap at height {(h0 + h1) / 2:.6f} m; "
                                "overlapping or nested pieces are not supported.")
    return [item[:5] for item in intervals]


def _overlap_length(a_in: float, a_out: float, b_in: float, b_out: float) -> float:
    return min(a_out, b_out) - max(a_in, b_in)


def decompose_outline(rings, *, section_id: str = "section") -> list[dict]:
    """Split closed half-plane outline rings into one-interval-per-height regions.

    ``rings`` are closed polygons in (y, z) metres with ``y >= 0``; a piece of
    a station drawn from the centreline is closed along the centreline. The
    regions tile the outline exactly: their total area equals the ring area.
    """
    if not isinstance(rings, (list, tuple)) or not 1 <= len(rings) <= MAX_RINGS:
        raise GeometryError(f"Section {section_id}: give 1..{MAX_RINGS} outline rings.")
    prepared = _snap_heights([_as_ring(ring, index, section_id) for index, ring in enumerate(rings)])
    starts = np.vstack(prepared)
    ends = np.vstack([np.roll(ring, -1, axis=0) for ring in prepared])
    edges = {
        "y0": starts[:, 0], "z0": starts[:, 1], "y1": ends[:, 0], "z1": ends[:, 1],
        "ring": np.concatenate([np.full(len(ring), index) for index, ring in enumerate(prepared)]),
        "sloped": starts[:, 1] != ends[:, 1],
        "low": np.minimum(starts[:, 1], ends[:, 1]), "high": np.maximum(starts[:, 1], ends[:, 1]),
        "centreline": (starts[:, 0] == 0) & (ends[:, 0] == 0),
    }
    heights = np.unique(starts[:, 1])
    if len(heights) < 2:
        raise GeometryError(f"Section {section_id}: the outline has no vertical extent.")
    regions: list[dict] = []
    open_regions: dict[int, int] = {}  # interval index in the previous slab -> region index
    previous: list[tuple] = []
    for h0, h1 in zip(heights[:-1], heights[1:]):
        current = _slab_intervals(edges, float(h0), float(h1), section_id)
        predecessors = {j: [i for i, before in enumerate(previous)
                            if _overlap_length(before[2], before[3], now[0], now[1]) > EQUAL_M]
                        for j, now in enumerate(current)}
        successor_count = {i: sum(i in found for found in predecessors.values()) for i in range(len(previous))}
        next_open: dict[int, int] = {}
        for j, (in0, out0, in1, out1, on_centreline) in enumerate(current):
            kind = CENTRELINE if on_centreline else OFFSET
            found = predecessors[j]
            continues = (len(found) == 1 and successor_count[found[0]] == 1 and found[0] in open_regions
                         and regions[open_regions[found[0]]]["kind"] == kind)
            if continues:
                region = regions[open_regions[found[0]]]
                last = region["rows_m"][-1]
                if abs(last[1] - in0) > EQUAL_M or abs(last[2] - out0) > EQUAL_M:
                    region["rows_m"].append([float(h0), float(in0), float(out0)])  # horizontal step
                region["rows_m"].append([float(h1), float(in1), float(out1)])
                next_open[j] = open_regions[found[0]]
            else:
                regions.append({"kind": kind, "rows_m": [[float(h0), float(in0), float(out0)],
                                                         [float(h1), float(in1), float(out1)]]})
                next_open[j] = len(regions) - 1
        open_regions, previous = next_open, current
    for region in regions:
        rows = np.asarray(region["rows_m"])
        if region["kind"] == CENTRELINE:
            rows[:, 1] = 0.0
            region["rows_m"] = rows.tolist()
        region["area_m2"] = region_area(rows)
        region["z_range_m"] = [float(rows[0, 0]), float(rows[-1, 0])]
    outline = sum(ring_area(ring) for ring in prepared)
    tiled = sum(region["area_m2"] for region in regions)
    if abs(tiled - outline) > 1e-9 * max(1.0, outline):
        raise GeometryError(f"Section {section_id}: region decomposition lost area ({tiled:.9f} vs {outline:.9f} m2).")
    return regions


def check_region(region: dict, section_id: str) -> np.ndarray:
    """Validate one region record and return its rows as an array."""
    if not isinstance(region, dict) or region.get("kind") not in REGION_KINDS:
        raise GeometryError(f"Section {section_id}: each region needs kind 'centreline' or 'offset'.")
    try:
        rows = np.asarray(region["rows_m"], dtype=float)
    except (KeyError, TypeError, ValueError, OverflowError) as exc:
        raise GeometryError(f"Section {section_id}: region rows must be [z, y_in, y_out] numbers.") from exc
    if rows.ndim != 2 or rows.shape[1] != 3 or not 2 <= len(rows) <= 2 * MAX_RING_POINTS:
        raise GeometryError(f"Section {section_id}: a region needs 2 or more [z, y_in, y_out] rows.")
    if not np.isfinite(rows).all() or np.max(np.abs(rows)) > MAX_COORDINATE_M:
        raise GeometryError(f"Section {section_id}: region rows are nonfinite or unbounded.")
    z = rows[:, 0]
    if np.any(np.diff(z) < 0) or z[-1] <= z[0]:
        raise GeometryError(f"Section {section_id}: region heights must not decrease and must span a height.")
    if np.any((z[2:] == z[1:-1]) & (z[1:-1] == z[:-2])):
        raise GeometryError(f"Section {section_id}: at most two region rows may share one height.")
    if rows[:, 1].min() < 0 or np.any(rows[:, 2] < rows[:, 1]):
        raise GeometryError(f"Section {section_id}: a region needs 0 <= y_in <= y_out.")
    if region["kind"] == CENTRELINE and np.any(rows[:, 1] != 0):
        raise GeometryError(f"Section {section_id}: a centreline region has y_in = 0.")
    if region_area(rows) <= 0:
        raise GeometryError(f"Section {section_id}: a region encloses no area.")
    return rows


def section_regions(section: dict) -> list[dict]:
    """Regions of a station record; a legacy half-section is one centreline region."""
    section_id = str(section.get("id", "unnamed"))
    if "regions" in section:
        regions = section["regions"]
        if not isinstance(regions, list) or not regions:
            raise GeometryError(f"Section {section_id}: regions must be a nonempty list.")
        return [{"kind": region["kind"], "rows_m": check_region(region, section_id)} for region in regions]
    try:
        points = np.asarray(section["points_yz_m"], dtype=float)
    except (KeyError, TypeError, ValueError, OverflowError) as exc:
        raise GeometryError(f"Invalid measured section: {section_id}") from exc
    if points.ndim != 2 or points.shape[1] != 2 or len(points) < 2:
        raise GeometryError(f"Invalid measured section: {section_id}")
    points = points[np.argsort(points[:, 1], kind="stable")]
    rows = np.column_stack([points[:, 1], np.zeros(len(points)), points[:, 0]])
    return [{"kind": CENTRELINE, "rows_m": check_region({"kind": CENTRELINE, "rows_m": rows}, section_id)}]


def region_overlap(a_rows: np.ndarray, b_rows: np.ndarray, samples: int = 400) -> float:
    """Approximate area shared by two regions placed in one (y, z) plane."""
    low, high = max(a_rows[0, 0], b_rows[0, 0]), min(a_rows[-1, 0], b_rows[-1, 0])
    if high <= low:
        return 0.0
    z = np.linspace(low, high, samples)
    a_in, a_out = np.interp(z, a_rows[:, 0], a_rows[:, 1]), np.interp(z, a_rows[:, 0], a_rows[:, 2])
    b_in, b_out = np.interp(z, b_rows[:, 0], b_rows[:, 1]), np.interp(z, b_rows[:, 0], b_rows[:, 2])
    shared = np.maximum(0.0, np.minimum(a_out, b_out) - np.maximum(a_in, b_in))
    return float(np.trapezoid(shared, z))


def match_regions(first: list[dict], second: list[dict], *,
                  min_overlap: float = MIN_MATCH_OVERLAP) -> list[tuple[int, int, float]]:
    """One-to-one region matches between neighbouring stations.

    A pair matches when both regions are of the same kind, each is the
    other's best match by overlap over union (intersection over union, so a
    small region inside a large one does not take the large one's partner),
    and that ratio is at least ``min_overlap``. Other regions end at this
    station (flat closure).
    """
    if not first or not second:
        return []
    first = [{"kind": r["kind"], "rows_m": np.asarray(r["rows_m"], dtype=float)} for r in first]
    second = [{"kind": r["kind"], "rows_m": np.asarray(r["rows_m"], dtype=float)} for r in second]
    score = np.zeros((len(first), len(second)))
    for i, a in enumerate(first):
        for j, b in enumerate(second):
            if a["kind"] == b["kind"]:
                shared = region_overlap(a["rows_m"], b["rows_m"])
                union = region_area(a["rows_m"]) + region_area(b["rows_m"]) - shared
                score[i, j] = shared / union if union > 0 else 0.0
    matches = []
    for i in range(len(first)):
        j = int(np.argmax(score[i]))
        if score[i, j] >= min_overlap and int(np.argmax(score[:, j])) == i:
            matches.append((i, j, float(score[i, j])))
    return matches


# Correspondence between regions of one lofted run --------------------------------

def _bounded_knots(t: np.ndarray, y: np.ndarray, tolerance_m: float) -> np.ndarray:
    """Indices of a piecewise-linear function kept within a vertical bound.

    Same rule as ``geometry._bounded_knots``: every source knot is tested, so
    the bound holds on the whole polyline; zero/positive transitions are kept.
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


def boundary_knots(t: np.ndarray, y: np.ndarray, tolerance_m: float) -> dict[float, int]:
    """Knots of one boundary as {t: multiplicity}; a step gives multiplicity 2."""
    steps = np.flatnonzero(np.diff(t) == 0)
    cuts = [0, *(int(s) + 1 for s in steps), len(t)]
    knots: dict[float, int] = {}
    for start, stop in zip(cuts[:-1], cuts[1:]):
        if stop - start == 1:
            knots[float(t[start])] = knots.get(float(t[start]), 0) + 1
            continue
        for index in _bounded_knots(t[start:stop], y[start:stop], tolerance_m):
            value = float(t[start + index])
            knots[value] = knots.get(value, 0) + 1
    # Each piece contributes its end knots; only a real step keeps two.
    step_values = {float(t[s]) for s in steps}
    return {value: (2 if value in step_values else 1) for value in knots}


def merge_knots(sets: list[dict[float, int]]) -> list[tuple[float, int]]:
    """Union of knot sets; values closer than 1e-12 are one knot."""
    merged: dict[float, int] = {}
    for knots in sets:
        for value, count in knots.items():
            merged[value] = max(merged.get(value, 0), count)
    ordered: list[list] = []
    for value in sorted(merged):
        if ordered and value - ordered[-1][0] <= 1e-12:
            ordered[-1][1] = max(ordered[-1][1], merged[value])
        else:
            ordered.append([value, merged[value]])
    ordered[0][0], ordered[-1][0] = 0.0, 1.0
    return [(float(value), int(count)) for value, count in ordered]


def evaluate_boundary(t: np.ndarray, y: np.ndarray, knots: list[tuple[float, int]]) -> np.ndarray:
    """Boundary ordinates at the common knots; a step gives its left then right value."""
    values = []
    for value, count in knots:
        same = np.flatnonzero(np.abs(t - value) <= 1e-12)
        if len(same) >= 2:
            values.extend([y[same[0]], y[same[-1]]] if count == 2 else [y[same[0]]])
        else:
            values.extend([float(np.interp(value, t, y))] * count)
    return np.asarray(values, dtype=float)


def deviation(t: np.ndarray, y: np.ndarray, knots: list[tuple[float, int]], values: np.ndarray) -> float:
    """Largest ordinate difference between a boundary and its knot polyline."""
    knot_t = np.repeat([value for value, _ in knots], [count for _, count in knots])
    steps = {float(t[s]) for s in np.flatnonzero(np.diff(t) == 0)}
    keep = np.array([float(v) not in steps for v in t])
    if not keep.any():
        return 0.0
    return float(np.max(np.abs(np.interp(t[keep], knot_t, values) - y[keep])))


def normalized_height(rows: np.ndarray) -> np.ndarray:
    z = rows[:, 0]
    return (z - z[0]) / (z[-1] - z[0])


def total_area(regions: list[dict]) -> float:
    return float(sum(region_area(region["rows_m"]) for region in regions))
