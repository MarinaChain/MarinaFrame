"""One stroke per station in a shared body-plan panel (overlay layout).

In an overlay body plan several stations share one drawing panel: the
forebody stations on one side of the centreline, the afterbody stations on
the other. The curves of one half nest: a station farther from midship is
narrower at every height. A best-score choice per section gives every
station of the panel the same stroke; this module gives each station its own.

The assignment is a recommendation, never identity: it orders the panel's
verified strokes by nesting (half-breadth at common heights), orders the
stations by their distance from midship (the side of the other panel, or the
middle of the station list), and matches the two orders while it prefers
hull-like strokes. It never refuses: a tie or too few strokes still gives a
best guess, with a warning and a lower confidence.
"""
from __future__ import annotations

import json
import math

import numpy as np

# Two strokes nest when they share at least this share of the shorter one's
# rows (and at least NEST_MIN_ROWS rows). Their median half-breadth
# difference on those rows says which is outside; within NEST_TIE_PX they
# are the same width there (converging curves near the keel, or one curve).
NEST_MIN_ROW_SHARE = 0.2
NEST_MIN_ROWS = 10
NEST_TIE_PX = 1.0
# A stroke with hull likeness below this floor (describe_stroke) is weak: it
# is used only when the panel has fewer hull-like strokes than stations.
LIKENESS_FLOOR = 0.3
# A stroke that spans at least this share of the section height is a station
# curve even when its likeness is low: a crossing, an occluded end or a short
# hook lowers likeness (smoothness, keel factor), not the stroke's length.
# A long stroke weighs at least LIKENESS_FLOOR, so every long distinct stroke
# is used before two stations share one stroke. Pieces of a broken stroke are
# shorter and stay weak.
LONG_STROKE_SHARE = 0.6
# Penalty of one stroke shared by two neighbouring stations. Stations share
# strokes only when the panel has fewer hull-like strokes than stations (one
# ink is listed once). Then the outermost stroke is the cheap one to share:
# stations near midship are often identical (a parallel middle body). Its
# penalty leaves a gain of at most LIKENESS_FLOOR (and at least
# SHARE_PENALTY_OUTERMOST is paid), so every hull-like stroke is used before
# the outermost is shared, and a weak stroke only when it beats sharing.
# Sharing any other stroke costs more than any likeness (<= 1).
SHARE_PENALTY_OUTERMOST = 0.2
SHARE_SLACK = 0.01
SHARE_PENALTY = 1.5
# An alternative within this likeness of the chosen stroke is a near tie.
NEAR_TIE = 0.05
MAX_ALTERNATIVES = 3
# Confidence factors (a ranking aid, not a probability).
SHARED_FACTOR = 0.4
NEAR_TIE_FACTOR = 0.6
PINNED_CONFIDENCE = 1.0
BASIS = ("nesting order of the panel's strokes matched to station distance from midship; "
         "hull likeness breaks ties; a recommendation, not identity or approval")


def panel_key(section: dict) -> str:
    """Sections with the same ROI share a panel.

    The calibration is not part of the key: on a scanned sheet each station's
    centreline and baseline are read separately and differ by a pixel or so.
    """
    return json.dumps(section["roi_px"])


def shared_panels(sections: list[dict]) -> list[list[dict]]:
    """Groups of two or more declared sections that share one panel, in declared order."""
    groups: dict[str, list[dict]] = {}
    for section in sections:
        if "pieces" in section or "roi_px" not in section:
            continue
        groups.setdefault(panel_key(section), []).append(section)
    return [members for members in groups.values() if len(members) > 1]


def station_order(members: list[dict], sections: list[dict]) -> tuple[list[dict], str]:
    """Panel stations from the widest expected (nearest midship) to the narrowest.

    When every other declared station lies on one side of the panel's
    stations in x, midship is on that side (fore and aft halves of an overlay
    body plan). Otherwise midship is taken as the middle of the station list.
    """
    ids = {s["id"] for s in members}
    others = [s["x_m"] for s in sections if s["id"] not in ids]
    xs = [s["x_m"] for s in members]
    if others and min(others) >= max(xs):
        return sorted(members, key=lambda s: -s["x_m"]), "other_half_forward"
    if others and max(others) <= min(xs):
        return sorted(members, key=lambda s: s["x_m"]), "other_half_aft"
    every = [s["x_m"] for s in sections]
    middle = 0.5 * (min(every) + max(every))
    return sorted(members, key=lambda s: (abs(s["x_m"] - middle), s["x_m"])), "middle_of_station_list"


def _outside(first: dict, second: dict) -> int:
    """+1 when ``first`` is outside ``second`` at their common heights, -1 inside, 0 tie/unknown."""
    rows = np.intersect1d(first["rows"], second["rows"])
    shorter = min(len(first["rows"]), len(second["rows"]))
    if len(rows) >= max(NEST_MIN_ROWS, NEST_MIN_ROW_SHARE * shorter):
        difference = float(np.median(np.interp(rows, first["rows"], first["breadth"])
                                     - np.interp(rows, second["rows"], second["breadth"])))
    else:
        # No common heights: the wider stroke overall is taken as outside.
        difference = float(np.max(first["breadth"]) - np.max(second["breadth"]))
    if abs(difference) <= NEST_TIE_PX:
        return 0
    return 1 if difference > 0 else -1


def nesting_order(strokes: list[dict]) -> tuple[list[int], float]:
    """Stroke indices from outermost to innermost, and the share of stroke pairs that agree.

    Each stroke scores the strokes it lies outside minus those it lies inside
    (a Copeland count over pairwise comparisons); the widest stroke breaks ties.
    """
    count = len(strokes)
    relation = np.zeros((count, count), dtype=int)
    for i in range(count):
        for j in range(i + 1, count):
            relation[i, j] = _outside(strokes[i], strokes[j])
            relation[j, i] = -relation[i, j]
    scores = relation.sum(axis=1)
    order = sorted(range(count), key=lambda i: (-scores[i], -float(np.max(strokes[i]["breadth"]))))
    position = {index: rank for rank, index in enumerate(order)}
    pairs = [(i, j) for i in range(count) for j in range(count) if relation[i, j] == 1]
    agree = sum(position[i] < position[j] for i, j in pairs)
    return order, (agree / len(pairs) if pairs else 1.0)


def _monotone_assignment(weights: np.ndarray, pinned: dict[int, int], may_share: bool) -> list[int]:
    """Stroke index (in nesting order) per station (widest first), non-decreasing.

    Maximises the summed weight. Without ``may_share`` (and with at least as
    many strokes as stations) each station gets its own stroke; otherwise
    consecutive stations on one stroke pay SHARE_PENALTY
    (SHARE_PENALTY_OUTERMOST on the outermost stroke). ``pinned`` fixes a
    station to a stroke.
    """
    stations, count = weights.shape
    may_share = may_share or count < stations
    share_cost = np.full(count, SHARE_PENALTY if may_share else math.inf)
    if may_share:
        outermost = float(np.max(weights[:, 0]))
        share_cost[0] = max(SHARE_PENALTY_OUTERMOST, outermost - LIKENESS_FLOOR + SHARE_SLACK)
    score = np.full((stations, count), -math.inf)
    back = np.zeros((stations, count), dtype=int)
    allowed = np.ones((stations, count), dtype=bool)
    for station, stroke in pinned.items():
        allowed[station] = False
        allowed[station, stroke] = True
    score[0] = np.where(allowed[0], weights[0], -math.inf)
    for station in range(1, stations):
        for stroke in range(count):
            if not allowed[station, stroke]:
                continue
            best, arg = -math.inf, 0
            for previous in range(stroke + 1):
                value = score[station - 1, previous] - (share_cost[stroke] if previous == stroke else 0.0)
                if value > best:
                    best, arg = value, previous
            score[station, stroke] = best + weights[station, stroke]
            back[station, stroke] = arg
    last = int(np.argmax(score[-1]))
    if not math.isfinite(score[-1, last]):
        # Inconsistent pins (out of nesting order): drop them, never refuse.
        return _monotone_assignment(weights, {}, may_share)
    path = [last]
    for station in range(stations - 1, 0, -1):
        path.append(int(back[station, path[-1]]))
    return path[::-1]


def _weight(stroke: dict, height_px: float) -> float:
    """Assignment weight of a stroke: its hull likeness, at least LIKENESS_FLOOR for a long stroke."""
    likeness = float(stroke.get("hull_likeness", 0.0))
    rows = np.asarray(stroke["rows"])
    span = float(rows[-1]) - float(rows[0]) + 1.0 if len(rows) else 0.0
    return max(likeness, LIKENESS_FLOOR) if span >= LONG_STROKE_SHARE * height_px else likeness


def assign_panel(members: list[dict], sections: list[dict], strokes: list[dict],
                 pinned: dict[str, str] | None = None) -> dict:
    """Recommended stroke per station of one shared panel.

    ``strokes`` are verified strokes of the panel: ``candidate_id``,
    ``rows`` (dense source rows), ``xs`` (source columns), ``hull_likeness``
    and ``kind``. ``pinned`` maps a station to a candidate already chosen for
    it (a selection or a model claim). Returns ``{section_id: recommendation}``;
    a station gets no recommendation only when the panel has no stroke.
    """
    pinned = pinned or {}
    ordered_members, order_basis = station_order(members, sections)
    centre = float(members[0]["calibration"]["centerline_px"])
    height_px = max((float(members[0]["z_max_m"]) - float(members[0]["z_min_m"]))
                    * float(members[0]["calibration"]["pixels_per_metre"]), 1.0)
    usable = [{**s, "weight": _weight(s, height_px)} for s in strokes if s.get("kind") != "straight_grid_line"]
    good = [s for s in usable if s["weight"] >= LIKENESS_FLOOR]
    few_good = len(good) < len(members)
    pool = usable if few_good else good
    pool = [{**s, "rows": np.asarray(s["rows"]), "breadth": np.asarray(s["xs"], dtype=float) - centre}
            for s in pool]
    if not pool:
        return {}
    order, consistency = nesting_order(pool)
    ranked = [pool[i] for i in order]
    # The assignment weight: hull likeness, raised to the floor for a long stroke (_weight).
    likeness = np.array([s["weight"] for s in ranked])
    weights = np.tile(likeness, (len(ordered_members), 1))
    position = {s["candidate_id"]: rank for rank, s in enumerate(ranked)}
    pins = {index: position[pinned[m["id"]]] for index, m in enumerate(ordered_members)
            if pinned.get(m["id"]) in position}
    path = _monotone_assignment(weights, pins, few_good)
    result = {}
    for index, member in enumerate(ordered_members):
        rank = path[index]
        chosen = ranked[rank]
        low = path[index - 1] + 1 if index > 0 else 0
        high = path[index + 1] - 1 if index + 1 < len(path) else len(ranked) - 1
        between = [r for r in range(low, high + 1) if r != rank]
        between.sort(key=lambda r: (-likeness[r], abs(r - rank)))
        alternatives = [ranked[r]["candidate_id"] for r in between[:MAX_ALTERNATIVES]]
        warnings = []
        confidence = float(likeness[rank]) * consistency
        if index in pins:
            confidence = PINNED_CONFIDENCE
            warnings.append("station_pinned_by_existing_choice")
        shared = [m["id"] for other, m in enumerate(ordered_members) if other != index and path[other] == rank]
        if shared:
            confidence *= SHARED_FACTOR
            warnings.append("fewer_strokes_than_stations: shares the stroke with " + ", ".join(shared))
        if index not in pins and between and likeness[between[0]] >= likeness[rank] - NEAR_TIE:
            confidence *= NEAR_TIE_FACTOR
            warnings.append("near_tie: another stroke in the same nesting slot is about as hull-like")
        if likeness[rank] < LIKENESS_FLOOR:
            warnings.append("weak_stroke: low hull likeness; few hull-like strokes in the panel")
        result[member["id"]] = {
            "candidate_id": chosen["candidate_id"], "confidence": round(min(1.0, confidence), 3),
            "alternatives": alternatives, "nesting_rank": rank + 1, "strokes_in_panel": len(ranked),
            "expected_width_rank": index + 1, "station_order_basis": order_basis,
            "nesting_consistency": round(consistency, 3),
            "hull_likeness": round(float(chosen.get("hull_likeness", 0.0)), 4),
            "panel_section_ids": [m["id"] for m in ordered_members], "warnings": warnings,
            "basis": BASIS, "identity_certified": False}
    return result


# ------------------------------------------------------------ catalog side

def _stroke_of(candidate: dict, section: dict, grid_columns_px=None) -> dict | None:
    """Dense trace and description of a catalog candidate, as an assignment stroke.

    ``grid_columns_px`` (``investigation.grid_columns``) tags a candidate that
    rides a vertical grid line, also when its stored description predates it.
    """
    from . import investigation as inv
    trace = inv.dense_trace(candidate)
    if trace is None or len(trace[0]) < 2:
        return None
    if "hull_likeness" in candidate and "kind" in candidate:
        kind, likeness = candidate["kind"], candidate["hull_likeness"]
    else:
        z_range = candidate.get("z_range_m") or [section["z_min_m"], section["z_max_m"]]
        described = inv.describe_stroke({"trace_rows_px": [int(trace[0][0]), int(trace[0][-1])],
                                         "trace_xs_px": trace[1], "z_range_m": z_range}, section, grid_columns_px)
        kind, likeness = described["kind"], described["hull_likeness"]
    if kind != "straight_grid_line" and grid_columns_px:
        rows = [int(trace[0][0]), int(trace[0][-1])]
        if inv.stroke_kind(rows, trace[1], section, grid_columns_px) == "straight_grid_line":
            kind = "straight_grid_line"
    return {"candidate_id": candidate["candidate_id"], "rows": trace[0], "xs": trace[1],
            "hull_likeness": likeness, "kind": kind}


def panel_stroke_candidate(traced: dict, source_sha: str, key: str, others: int) -> dict:
    """Catalog entry of a harness-enumerated panel stroke (not a model trace).

    It is selectable ink the engine verified in a corridor; it enters a draft
    only through the panel assignment (``recommended_station_assignment``).
    ``others`` (the panel's other strokes) keeps a policy from selecting it.
    """
    from .provenance import digest_object
    support = traced["support"]
    cid = "stroke-" + digest_object({"source": source_sha, "panel": key,
                                     "selection": traced["contour_selection"], "z_range_m": traced["z_range_m"]})[:20]
    return {"candidate_id": cid, "hypothesis": "panel_stroke_discovery", "generated_by": ["panel_assignment"],
            "selectable": True, "panel_stroke": True,
            "source_support": {"observed_row_fraction": support["row_coverage"],
                               "max_missing_run_px": support["max_missing_run_px"],
                               "maximum_step_px_per_row": support["maximum_step_px_per_row"],
                               "long_component_support_fraction": support["long_component_support_fraction"],
                               "mean_trace_contrast": support["mean_trace_contrast"]},
            "grid_supported_hypothesis": False, "non_grid_competing_components": others,
            "contour_selection": traced["contour_selection"], "z_range_m": traced["z_range_m"],
            "kind": traced["kind"], "z_coverage_fraction": traced["z_coverage_fraction"],
            "hull_likeness": traced["hull_likeness"], "identity_certified": False}


def _pins(members: list[dict], entries: list[dict], pool: list[dict], chosen: dict[str, str]) -> dict[str, str]:
    """Pool stroke of each station that already has a chosen candidate (same id or same ink)."""
    from . import investigation as inv
    pins = {}
    for member, entry in zip(members, entries):
        cid = chosen.get(member["id"])
        candidate = next((c for c in entry["candidates"] if c["candidate_id"] == cid), None)
        if candidate is None:
            continue
        match = next((p for p in pool if p["candidate_id"] == cid or inv.same_ink(candidate, p)), None)
        if match is not None:
            pins[member["id"]] = match["candidate_id"]
    return pins


def pending_panels(sections: list[dict], catalog: dict) -> list[list[dict]]:
    """Shared panels whose sections are all inspected and not all assigned yet."""
    pending = []
    for members in shared_panels(sections):
        entries = [catalog.get(m["id"]) for m in members]
        if all(e is not None for e in entries) and not all("recommended_station_assignment" in e
                                                           for e in entries):
            pending.append(members)
    return pending


def _member_candidate(entry: dict, candidate: dict) -> str:
    """Id of ``candidate``'s ink in one section's catalog; the candidate is added when absent."""
    from . import investigation as inv
    for own in entry["candidates"]:
        if own["candidate_id"] == candidate["candidate_id"]:
            return own["candidate_id"]
    for own in entry["candidates"]:
        if (own.get("selectable") is True and "contour_selection" in own and "authored" not in own
                and not own.get("model_traced") and inv.same_ink(own, candidate)):
            return own["candidate_id"]
    entry["candidates"].append(json.loads(json.dumps(candidate)))
    return candidate["candidate_id"]


def assign_shared_panels(image, sections: list[dict], catalog: dict, source_file: str, details: dict,
                         source_sha: str, pinned: dict[str, str] | None = None) -> list[str]:
    """Add ``recommended_station_assignment`` to the catalog entries of every shared panel.

    Each panel is enumerated once (``investigation.enumerate_strokes``). A
    stroke that follows the ink of an existing candidate reuses it; the
    recommended stroke and its alternatives are added to each station's
    candidates. Panels already assigned, or not fully inspected, are skipped.
    Returns the ids of the sections that changed.
    """
    from . import investigation as inv
    changed = []
    pinned = pinned or {}
    for members in pending_panels(sections, catalog):
        entries = [catalog[m["id"]] for m in members]
        section = members[0]
        try:
            traced, _ = inv.enumerate_strokes(image, section, source_file, details, None, [])
        except Exception as exc:  # noqa: BLE001 - never refuse; fall back to inspected lines
            traced, failure = [], type(exc).__name__
        else:
            failure = None
        key = panel_key(section)
        found = [panel_stroke_candidate(stroke, source_sha, key, max(0, len(traced) - 1)) for stroke in traced]
        # Inspected lines of the panel join the enumerated strokes. One ink is
        # pooled once (each section has its own ids for it): the most
        # hull-like version is kept, so a full line beats its fragment.
        found += [c for entry in entries for c in entry.get("candidates", [])
                  if c.get("selectable") is True and "contour_selection" in c
                  and "authored" not in c and not c.get("model_traced") and not c.get("panel_stroke")]
        try:
            grid = inv.grid_columns(image, section)
        except Exception:  # noqa: BLE001 - a hint only; never refuse
            grid = []
        described = [(c, _stroke_of(c, section, grid)) for c in found]
        described.sort(key=lambda item: -(item[1]["hull_likeness"] if item[1] else -1.0))
        pool, strokes = [], []
        for candidate, stroke in described:
            if stroke is not None and not any(inv.same_ink(candidate, other) for other in pool):
                pool.append(candidate)
                strokes.append(stroke)
        recommendations = assign_panel(members, sections, strokes, _pins(members, entries, pool, pinned))
        by_id = {c["candidate_id"]: c for c in pool}
        for member, entry in zip(members, entries):
            recommendation = recommendations.get(member["id"])
            if recommendation is None:
                recommendation = {"candidate_id": None, "confidence": 0.0, "alternatives": [],
                                  "warnings": ["no_stroke_found_in_panel"], "basis": BASIS,
                                  "identity_certified": False}
            else:
                recommendation = {**recommendation,
                                  "candidate_id": _member_candidate(entry, by_id[recommendation["candidate_id"]]),
                                  "alternatives": [_member_candidate(entry, by_id[cid])
                                                   for cid in recommendation["alternatives"]]}
            if failure is not None:
                recommendation["warnings"] = [*recommendation["warnings"], "stroke_enumeration_failed: " + failure]
            entry["recommended_station_assignment"] = recommendation
            changed.append(member["id"])
    return changed
