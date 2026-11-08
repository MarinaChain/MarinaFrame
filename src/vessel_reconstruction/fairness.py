"""Cross-station fairness check: name the draft section that breaks the hull.

Hull sections vary smoothly along the length. At a fixed height the
half-breadth of successive stations forms a smooth curve over x, and so do the
keel and top heights of the sections. A grid line taken as a section, a partial
stroke bridged straight, a curve of another station or a bad authored section
stands out from that curve.

Rule (leave one out). Inside the hull a section must lie between its nearest
neighbours on the left and right, with a small allowance: at each compared
height for the half-breadth, and for the keel and top heights. A smooth curve
over x passes between its neighbours except at a peak, where the parallel
midbody makes the difference small. An end section has a neighbour on one side
only. A hull narrows towards its ends by any amount, so an end is only checked
for being wider than its nearest neighbour or the straight-line continuation of
the two nearest.

The worst section outside its range is flagged and taken out of the neighbour
set, so it does not spoil the ranges of its neighbours; then the check repeats.
The result is a ranked list with a one-line reason and a suggested fix.

This is a warning only. It never blocks a build and it has no access to truth.
Calibration on development truth hulls and built drafts: work/d1-fairness/.
"""
from __future__ import annotations

import numpy as np

METHOD = "neighbour_range_station_fairness_v1"
# Heights where half-breadths are compared, as fractions of the robust hull
# height range. The keel and top rows are left out: closures vary there.
HEIGHT_FRACTIONS = tuple(float(f) for f in np.round(np.arange(.05, 1., .1), 2))
# Allowance outside the neighbour range: half-breadth as a fraction of the
# robust half-beam; keel and top heights as a fraction of the hull height.
HALF_BREADTH_ALLOWANCE = .15
HEIGHT_ALLOWANCE = .15
# Fewer sections than this are not checked. Outliers are taken out while at
# least three remain: three give each section a range from two others.
MINIMUM_SECTIONS = 4
MINIMUM_NEIGHBOUR_SET = 3
# Half-breadth spread, as a fraction of the half-beam, below which a section
# is a straight vertical line (a grid line, centreline or buttock).
STRAIGHT_LINE_SPREAD = .05
# A straight line counts only when it is away from the centreline (wider than
# this fraction of the half-beam; a thin stem stays a hull) and spans at least
# this fraction of the hull height.
STRAIGHT_LINE_MINIMUM_BREADTH = .1
STRAIGHT_LINE_MINIMUM_SPAN = .3
PROFILE_SAMPLES = 200
FEATURE_NAMES = {"half_breadth": "half-breadth", "keel_height": "keel (lowest point)", "top_height": "top"}
STRAIGHT_LINE_FIX = ("Its half-breadth is almost constant: probably a grid line, centreline or buttock. "
                     "Pick the curved candidate of this station, or propose_section.")


def half_breadth_at(points: np.ndarray, heights: np.ndarray, outside: float = 0.) -> np.ndarray:
    """Outer half-breadth of a section polyline at each height; ``outside`` above or below it."""
    y, z = points[:, 0], points[:, 1]
    result = np.full(len(heights), outside, dtype=float)
    low, high = np.minimum(z[:-1], z[1:]), np.maximum(z[:-1], z[1:])
    for index, height in enumerate(heights):
        hit = np.flatnonzero((low <= height) & (height <= high))
        if not len(hit):
            continue
        z0, z1, y0, y1 = z[hit], z[hit + 1], y[hit], y[hit + 1]
        span = z1 - z0
        safe = np.where(span == 0, 1., span)
        crossing = np.where(span == 0, np.maximum(y0, y1), y0 + (height - z0) / safe * (y1 - y0))
        result[index] = max(0., float(crossing.max()))
    return result


def section_features(points_yz_m) -> dict:
    """Keel and top heights, area, maximum half-breadth and half-breadth spread."""
    points = np.asarray(points_yz_m, dtype=float)
    z_min, z_max = float(points[:, 1].min()), float(points[:, 1].max())
    profile_z = np.linspace(z_min, z_max, PROFILE_SAMPLES)
    profile = half_breadth_at(points, profile_z)
    return {"z_min": z_min, "z_max": z_max, "max_half_breadth": float(points[:, 0].max()),
            "area": float(np.trapezoid(profile, profile_z)), "profile_spread": float(np.ptp(profile))}


def neighbour_range(x: np.ndarray, values: np.ndarray, at: float, feature: str) -> dict | None:
    """Plausible range of a feature at ``at`` from the other sections, or None.

    Only finite values count: a half-breadth above a section's top or below its
    keel is not defined. Between two neighbours: their range, widened to a
    quadratic through up to two neighbours a side (a smooth peak). At an end
    (or where the sections on one side do not reach this height): from 0 up to
    the larger of the nearest value and the straight-line continuation of the
    two nearest (half-breadth only; end keels and tops vary too much). Returns
    ``low``, ``high`` and ``used`` (positions in ``x`` of the neighbours used).
    """
    finite = np.flatnonzero(np.isfinite(values))
    left, right = finite[x[finite] < at], finite[x[finite] > at]
    if len(left) and len(right):
        candidates = [values[left[-1]], values[right[0]]]
        nearby = np.concatenate([left[-2:], right[:2]])
        if len(nearby) >= 3:
            # A quadratic through up to two neighbours a side: room for a peak.
            candidates.append(np.polyval(np.polyfit(x[nearby], values[nearby], 2), at))
        return {"low": float(min(candidates)), "high": float(max(candidates)), "used": [left[-1], right[0]]}
    if feature != "half_breadth":
        return None
    side = right[:2] if len(right) else left[::-1][:2]
    if len(side) < 2:
        return None
    nearest, next_one = values[side[0]], values[side[1]]
    slope = (nearest - next_one) / (x[side[0]] - x[side[1]])
    continuation = nearest + slope * (at - x[side[0]])
    return {"low": 0., "high": float(max(nearest, continuation)), "used": sorted(side.tolist())}


def _worst_feature(index: int, active: list[int], x: np.ndarray, rows: dict, allowance: dict) -> dict:
    """Largest normalised distance of one section outside its neighbour ranges."""
    others = np.array([i for i in active if i != index])
    worst = {"score": 0.}
    for name, values in rows.items():
        columns = values if values.ndim == 2 else values[:, None]
        for column in range(columns.shape[1]):
            observed = float(columns[index, column])
            bounds = neighbour_range(x[others], columns[others, column], x[index], name)
            if bounds is None or not np.isfinite(observed):
                continue
            outside = max(bounds["low"] - observed, observed - bounds["high"], 0.)
            score = outside / allowance[name]
            if score > worst["score"]:
                worst = {"score": score, "feature": name, "column": column, "observed": observed,
                         "low": bounds["low"] - allowance[name], "high": bounds["high"] + allowance[name],
                         "neighbours": [int(others[i]) for i in bounds["used"]]}
    return worst


def _describe(section_id: str, worst: dict, heights: np.ndarray, features: dict,
              half_beam: float, neighbours: list[str]) -> tuple[str, str]:
    """One-line reason and a suggested fix in words."""
    low, high = max(0., worst["low"]), worst["high"]
    above = worst["observed"] > high
    difference = worst["observed"] - high if above else low - worst["observed"]
    source = ", ".join(neighbours)
    if worst["feature"] == "half_breadth":
        reason = (f"{section_id} half-breadth at z {heights[worst['column']]:.1f} m is {worst['observed']:.2f} m, "
                  f"{difference:.2f} m {'wider' if above else 'narrower'} than its neighbours ({source}) allow "
                  f"(expected {low:.2f}-{high:.2f} m).")
    else:
        reason = (f"{section_id} {FEATURE_NAMES[worst['feature']]} is at z {worst['observed']:.2f} m, "
                  f"{difference:.2f} m {'higher' if above else 'lower'} than its neighbours ({source}) allow "
                  f"(expected {low:.2f}-{high:.2f} m).")
    partial = (worst["feature"] == "keel_height" and above) or (worst["feature"] == "top_height" and not above)
    if features["profile_spread"] < STRAIGHT_LINE_SPREAD * half_beam:
        fix = STRAIGHT_LINE_FIX
    elif partial:
        fix = "It looks like a partial stroke. Re-trace it to the keel and deck, or propose_section."
    else:
        fix = "Re-trace this station, pick another candidate (check the station label), or propose_section."
    return reason, fix


def is_straight_line(features: dict, half_beam: float, hull_height: float) -> bool:
    """True for a vertical straight line away from the centreline: not a hull section."""
    return (features["profile_spread"] < STRAIGHT_LINE_SPREAD * half_beam
            and features["max_half_breadth"] > STRAIGHT_LINE_MINIMUM_BREADTH * half_beam
            and features["z_max"] - features["z_min"] > STRAIGHT_LINE_MINIMUM_SPAN * hull_height)


def _references(features: list[dict], indices: list[int]) -> tuple[float, float, float]:
    """Robust keel height, hull height and half-beam: a few bad sections do not move the quartiles."""
    keel = [features[i]["z_min"] for i in indices]
    top = [features[i]["z_max"] for i in indices]
    z_base = float(np.percentile(keel, 25))
    hull_height = max(float(np.percentile(top, 75)) - z_base, 1e-6)
    half_beam = max(float(np.percentile([features[i]["max_half_breadth"] for i in indices], 75)), 1e-6)
    return z_base, hull_height, half_beam


def check_fairness(sections: list[dict]) -> dict:
    """Ranked fairness outliers of sections with ``id``, ``x_m`` and ``points_yz_m``.

    Returns a report with ``status`` (``checked`` or ``too_few_sections``), the
    compared heights, the robust half-beam and hull height, the flagged
    ``outliers`` (section ids, worst first) and ``sections`` (every scored
    section, ranked: flagged first, then unflagged, each by score). A score is
    the distance outside the neighbour range in allowances; above 1 flags.
    Straight vertical lines are always flagged (feature ``straight_line``, score
    at least 1) and are not used as neighbours.
    """
    usable = sorted((s for s in sections if len(s.get("points_yz_m") or []) >= 2), key=lambda s: s["x_m"])
    report = {"method": METHOD, "status": "too_few_sections", "outliers": [], "sections": []}
    if len(usable) < MINIMUM_SECTIONS:
        return report
    ids = [s["id"] for s in usable]
    x = np.array([float(s["x_m"]) for s in usable])
    features = [section_features(s["points_yz_m"]) for s in usable]
    keel = np.array([f["z_min"] for f in features])
    top = np.array([f["z_max"] for f in features])
    everything = list(range(len(usable)))
    z_base, hull_height, half_beam = _references(features, everything)
    straight = [i for i in everything if is_straight_line(features[i], half_beam, hull_height)]
    active = [i for i in everything if i not in straight]
    if straight and len(active) >= MINIMUM_SECTIONS:
        # Straight lines are not hull sections: leave them out of the references.
        z_base, hull_height, half_beam = _references(features, active)
    heights = z_base + np.array(HEIGHT_FRACTIONS) * hull_height
    rows = {"half_breadth": np.array([half_breadth_at(np.asarray(s["points_yz_m"], dtype=float), heights, np.nan)
                                      for s in usable]),
            "keel_height": keel, "top_height": top}
    allowance = {"half_breadth": HALF_BREADTH_ALLOWANCE * half_beam,
                 "keel_height": HEIGHT_ALLOWANCE * hull_height, "top_height": HEIGHT_ALLOWANCE * hull_height}
    flagged = []
    while len(active) >= MINIMUM_NEIGHBOUR_SET:
        scored = {i: _worst_feature(i, active, x, rows, allowance) for i in active}
        index = max(scored, key=lambda i: scored[i]["score"])
        if scored[index]["score"] <= 1.:
            break
        flagged.append((index, scored[index], [ids[i] for i in scored[index]["neighbours"]]))
        active.remove(index)
    final = {i: _worst_feature(i, active, x, rows, allowance) for i in active}
    entries = []
    for index in straight:
        f = features[index]
        # Scored against the sections that stayed fair, for the ranking only.
        score = max(1., _worst_feature(index, active, x, rows, allowance)["score"])
        entries.append({"section_id": ids[index], "x_m": float(x[index]), "flagged": True, "score": round(score, 3),
                        "feature": "straight_line", "observed_m": round(f["max_half_breadth"], 4),
                        "reason": (f"{ids[index]} is a vertical straight line: half-breadth {f['max_half_breadth']:.2f} m "
                                   f"from z {f['z_min']:.2f} to {f['z_max']:.2f} m, not a hull section."),
                        "suggestion": STRAIGHT_LINE_FIX})
    for index, worst, neighbours in flagged:
        reason, fix = _describe(ids[index], worst, heights, features[index], half_beam, neighbours)
        entries.append({"section_id": ids[index], "x_m": float(x[index]), "flagged": True,
                        "score": round(worst["score"], 3), "feature": worst["feature"],
                        "observed_m": round(worst["observed"], 4),
                        "expected_range_m": [round(max(0., worst["low"]), 4), round(worst["high"], 4)],
                        "reason": reason, "suggestion": fix})
    entries.sort(key=lambda entry: -entry["score"])
    for index in sorted(final, key=lambda i: -final[i]["score"]):
        entries.append({"section_id": ids[index], "x_m": float(x[index]), "flagged": False,
                        "score": round(final[index]["score"], 3)})
    for rank, entry in enumerate(entries, 1):
        entry["rank"] = rank
    report.update(status="checked", heights_m=[round(float(h), 4) for h in heights],
                  half_beam_m=round(half_beam, 4), hull_height_m=round(hull_height, 4),
                  outliers=[entry["section_id"] for entry in entries if entry["flagged"]], sections=entries)
    return report


def fairness_warnings(report: dict) -> list[dict]:
    """One warning gap per flagged section, worst first (never blocking)."""
    from .schema import gap

    return [gap("draft_fairness_outlier", f"{entry['reason']} {entry['suggestion']}", entry["section_id"], severity="warning")
            for entry in report["sections"] if entry["flagged"]]
