"""Anchored form fit: the first full hull of the vessel table, with no model call.

Whole-vessel design, section 4 (docs/plans/2026-11-08-whole-vessel-design.md).

1. **Anchors.** Traced sections of the deterministic draft (stroke discovery,
   C2 panel assignment) that pass the ink checks stay exactly as traced. The
   checks only remove ink that is not hull:
   * a vertical straight line (grid line, centreline, buttock) is not a hull;
   * a section that the D1 fairness check puts more than ``DROP_SCORE``
     allowances outside its neighbours' range is dropped (one allowance is
     15 % of the half-beam or of the hull height);
   * a top that runs up a vertical line to the panel top, while the
     neighbouring stations end lower, is cut where the run starts (the hull
     curve met a grid line);
   * ink at the top that turns flat inward (a station label or a closure
     line) is cut; when the side then ends just under the panel top, it is
     continued straight up to it (the row is then built as a curve);
   * a free stroke end is moved back by half the stroke width: the drawing
     pen's round cap puts ink beyond the curve end.
   When a build of the fitted table still fails (an invalid shell), the most
   suspect anchor is left out and the build is tried again (``first_hull``).
2. **Trend (the form family).** Each station is described by five numbers:
   keel height ``k``, top height ``t``, half-breadth scale ``b``, fullness
   ``p`` and bottom flat ``f0``. With ``eta = (z - k) / (t - k)`` the section
   is ``hb(z) = b * (f0 + (1 - f0) * (1 - (1 - eta)^p)^(1/p))``.
   Each of the five numbers is a smooth curve along x: a cubic B-spline with
   ``TREND_COEFFICIENTS`` (6) coefficients and a fixed second-difference
   penalty, fitted by weighted least squares to the anchors. That is 30
   numbers for the whole hull.

   Why this family: it is general, not a hull generator. A superellipse
   quarter spans the section forms of displacement hulls from V (p near 1)
   through round bilge (p near 2) to wall-sided U and box sections (large p);
   ``f0`` adds a flat of bottom or a transom-like flat lower edge; keel and top
   follow any profile (rise of floor, sheer, transom). It has no parameter for
   bulbs, knuckles or tumblehome: anchors carry those exactly, and the fit only
   has to fill gaps between them. It is not the Ship-D generator (design
   section 4, option A), so it does not flatter the Ship-D dev hulls.
3. **Table.** Anchored rows are the traced ink. A station without a usable
   anchor gets the trend plus the anchors' residuals (in ``eta``, and for keel
   and top heights), interpolated along x with PCHIP; beyond the last anchor
   the residual is 0 (trend only). Fitted rows are fair by construction: a
   smooth trend plus a shape-preserving interpolation of measured residuals.
4. **Fairness.** D1 runs on the finished rows; its findings are warnings.

Everything here is deterministic and uses no truth and no model. It never
refuses: with no usable anchor it returns ``None`` and the caller keeps its
draft (happy path first).
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .fairness import check_fairness, is_straight_line, section_features
from .vessel_model import FITTED_ROW_SAMPLES, StationRow, VesselTable, waterline_grid

METHOD = "anchored_form_fit_v1"
# D1 score (distance outside the neighbour range, in allowances) above which a
# traced section is not used as an anchor. D1 flags at 1; a hull that changes
# fast (a bulb station) can reach about 2, a wrong stroke goes further.
DROP_SCORE = 2.0
# Trend: coefficients per longitudinal curve and the weight of the
# second-difference penalty (relative to the mean anchor weight).
TREND_COEFFICIENTS = 6
TREND_PENALTY = 0.1
PARAMETERS = ("keel", "top", "breadth", "fullness", "flat")
FULLNESS_BOUNDS = (1.0, 12.0)
FLAT_BOUNDS = (0.0, 0.95)
# Points of the normalised height eta at which shapes and residuals are compared.
ETA_SAMPLES = 41
# A top run of constant half-breadth (within this many pixels) that is at least
# TOP_RUN_MIN_SHARE of the hull height long and reaches the panel top, while a
# neighbouring anchor ends lower by TOP_GAP_SHARE of the hull height, is not hull.
TOP_RUN_TOLERANCE_PX = 1.0
TOP_RUN_MIN_SHARE = 0.02
TOP_GAP_SHARE = 0.03
# Flat inward ink in this top share of the hull height, moving inward by more
# than INWARD_MIN_PX, is not hull (see inward_top_start).
TOP_WINDOW_SHARE = 0.03
INWARD_MIN_PX = 2.0
# A top this close to the declared panel top (pixels) is cut by the panel, not a free stroke end.
PANEL_TOP_TOLERANCE_PX = 1.5
# Ink darkness above the background, as a share of the stroke peak, that counts
# as the stroke (full width at half maximum).
STROKE_HALF_MAXIMUM = 0.5
STROKE_SEARCH_PX = 12
# Builds tried again, each with one more suspect anchor left out, after a failed build.
FALLBACK_RETRIES = 4


@dataclass
class Anchor:
    """One traced section offered as an anchor."""
    id: str
    x_m: float
    points_yz_m: list
    selection_section: dict
    z_max_m: float | None = None
    pixels_per_metre: float | None = None
    stroke_width_px: float | None = None
    weight: float = 1.0
    # True when check_tops continued the side above the traced ink: the row is
    # then built as a curve (the contour selection cannot extend ink).
    extended: bool = False
    notes: list = field(default_factory=list)


# ------------------------------------------------------------------ ink checks

def measure_stroke_width_px(image: np.ndarray, points_yz_m, calibration: dict) -> float | None:
    """Median stroke width along a traced curve, in pixels (full width at half maximum).

    Each sample counts the dark pixels across the curve on its image row and
    corrects the count for the curve slope. Returns None when nothing is measured.
    """
    if image is None:
        return None
    gray = image if image.ndim == 2 else image[..., :3].mean(axis=2)
    darkness = 255.0 - gray.astype(float)
    ppm = float(calibration["pixels_per_metre"])
    points = np.asarray(points_yz_m, dtype=float)
    points = points[points[:, 0] > 0]
    if len(points) < 5:
        return None
    cols = float(calibration["centerline_px"]) + points[:, 0] * ppm
    rows = float(calibration["baseline_px"]) - points[:, 1] * ppm
    slope = np.gradient(cols) / np.where(np.abs(np.gradient(rows)) > 1e-9, np.gradient(rows), 1e-9)
    background = float(np.median(darkness))
    widths = []
    for col, row, s in zip(cols, rows, slope):
        r, c = int(round(row)), int(round(col))
        if not (0 <= r < darkness.shape[0] and STROKE_SEARCH_PX <= c < darkness.shape[1] - STROKE_SEARCH_PX):
            continue
        line = darkness[r, c - STROKE_SEARCH_PX:c + STROKE_SEARCH_PX + 1] - background
        peak = float(line.max())
        if peak <= 0 or abs(s) > 1.0:  # A flat stretch of curve gives no horizontal width.
            continue
        centre = int(np.argmax(line))
        level = STROKE_HALF_MAXIMUM * peak
        left = centre
        while left > 0 and line[left - 1] >= level:
            left -= 1
        right = centre
        while right < len(line) - 1 and line[right + 1] >= level:
            right += 1
        widths.append((right - left + 1) / np.sqrt(1.0 + s * s))
    return float(np.median(widths)) if len(widths) >= 5 else None


def _clip_top(points: np.ndarray, top: float) -> np.ndarray:
    """The curve below height ``top``, ending exactly at ``top``."""
    below = points[points[:, 1] < top]
    if len(below) == 0:
        return points
    end = [float(np.interp(top, points[:, 1], points[:, 0])), top]
    return np.vstack([below, end])


def straight_top_run_start(points: np.ndarray, pixel_m: float, hull_height: float) -> float | None:
    """Height where a constant-breadth run that ends at the curve top begins, or None."""
    y, z = points[:, 0], points[:, 1]
    tolerance = TOP_RUN_TOLERANCE_PX * pixel_m
    index = len(points) - 1
    while index > 0 and abs(y[index - 1] - y[-1]) <= tolerance:
        index -= 1
    if y[-1] <= tolerance or z[-1] - z[index] < TOP_RUN_MIN_SHARE * hull_height:
        return None
    return float(z[index])


def inward_top_start(points: np.ndarray, pixel_m: float, hull_height: float) -> int | None:
    """Index of the last hull point before flat inward ink at the curve top, or None.

    A hull side near its top is steep or flares out. A segment in the top
    ``TOP_WINDOW_SHARE`` of the hull height that moves inward by more than it
    rises (and by more than ``INWARD_MIN_PX``) is a closure line or a label.
    The lowest such segment is where the hull ink ends.
    """
    y, z = points[:, 0], points[:, 1]
    window = z[-1] - TOP_WINDOW_SHARE * hull_height
    lowest = None
    for k in range(len(points) - 1):
        if z[k] < window:
            continue
        drop, rise = y[k] - y[k + 1], z[k + 1] - z[k]
        if drop > max(rise, INWARD_MIN_PX * pixel_m):
            lowest = k if lowest is None else min(lowest, k)
    return lowest if lowest is not None and lowest >= 4 else None


def check_tops(anchors: list[Anchor]) -> None:
    """Cut tops that are not hull ink (see the module notes). Changes anchors in place."""
    if not anchors:
        return
    ordered = sorted(anchors, key=lambda a: a.x_m)
    tops = [max(p[1] for p in a.points_yz_m) for a in ordered]
    keels = [min(p[1] for p in a.points_yz_m) for a in ordered]
    hull_height = max(max(tops) - min(keels), 1e-6)
    for index, anchor in enumerate(ordered):
        if not anchor.pixels_per_metre:
            continue
        pixel_m = 1.0 / anchor.pixels_per_metre
        points = np.asarray(anchor.points_yz_m, dtype=float)
        points = points[np.argsort(points[:, 1], kind="stable")]
        top = float(points[-1, 1])
        at_panel_top = anchor.z_max_m is not None and top >= anchor.z_max_m - PANEL_TOP_TOLERANCE_PX * pixel_m
        inward = inward_top_start(points, pixel_m, hull_height)
        if inward is not None:
            points = points[:inward + 1]
            cut = float(points[-1, 1])
            note = f"top cut at z {cut:.3f} m: the ink turns flat inward (a label or a closure line)"
            if at_panel_top and anchor.z_max_m - cut <= TOP_GAP_SHARE * hull_height:
                # The side reached the panel top under the flat ink: continue it straight up.
                points = np.vstack([points, [points[-1, 0], anchor.z_max_m]])
                anchor.extended = True
                note += f"; side continued straight up to the panel top z {anchor.z_max_m:.3f} m"
            anchor.points_yz_m = points.tolist()
            anchor.notes.append(note)
        elif at_panel_top:
            neighbours = [tops[j] for j in (index - 1, index + 1) if 0 <= j < len(ordered)]
            lower_neighbour = any(t < top - TOP_GAP_SHARE * hull_height for t in neighbours)
            start = straight_top_run_start(points, pixel_m, hull_height) if lower_neighbour else None
            if start is not None:
                anchor.points_yz_m = _clip_top(points, start).tolist()
                anchor.notes.append(f"top cut at z {start:.3f} m: a vertical line runs on to the panel top")
        elif anchor.stroke_width_px:
            cap = 0.5 * anchor.stroke_width_px * pixel_m
            anchor.points_yz_m = _clip_top(points, top - cap).tolist()
            anchor.notes.append(f"top moved down {cap:.3f} m: half the stroke width (pen cap)")


def check_anchors(anchors: list[Anchor]) -> tuple[list[Anchor], list[dict]]:
    """Anchors that pass the ink checks, and a record for each dropped one."""
    if not anchors:
        return [], []
    features = {a.id: section_features(a.points_yz_m) for a in anchors}
    half_beam = max(float(np.percentile([f["max_half_breadth"] for f in features.values()], 75)), 1e-6)
    hull_height = max(max(f["z_max"] for f in features.values()) - min(f["z_min"] for f in features.values()), 1e-6)
    dropped = [{"section_id": a.id, "reason": "vertical straight line, not a hull section"}
               for a in anchors if is_straight_line(features[a.id], half_beam, hull_height)]
    report = check_fairness([{"id": a.id, "x_m": a.x_m, "points_yz_m": a.points_yz_m} for a in anchors])
    gone = {d["section_id"] for d in dropped}
    for entry in report.get("sections", []):
        if entry["flagged"] and entry["section_id"] not in gone and entry["score"] >= DROP_SCORE:
            dropped.append({"section_id": entry["section_id"],
                            "reason": f"D1 fairness score {entry['score']:.2f} >= {DROP_SCORE}: {entry.get('reason', '')}"[:300]})
            gone.add(entry["section_id"])
    return [a for a in anchors if a.id not in gone], dropped


# ------------------------------------------------------------------ form family

def section_shape(eta: np.ndarray, fullness: float, flat: float) -> np.ndarray:
    """Normalised half-breadth (0..1) of the form family at normalised heights eta."""
    eta = np.clip(eta, 0.0, 1.0)
    curve = (1.0 - (1.0 - eta) ** fullness) ** (1.0 / fullness)
    return flat + (1.0 - flat) * curve


def station_parameters(points_yz_m) -> dict:
    """Keel, top, breadth scale, fullness and bottom flat of one section curve."""
    from scipy.optimize import least_squares

    points = np.asarray(points_yz_m, dtype=float)
    points = points[np.argsort(points[:, 1], kind="stable")]
    y, z = points[:, 0], points[:, 1]
    breadth = float(y.max())
    inside = np.flatnonzero(y > 0.01 * max(breadth, 1e-9))
    keel = float(z[inside[0]]) if len(inside) else float(z[0])
    top = float(z[-1])
    if breadth <= 0 or top - keel <= 1e-6:
        return {"keel": keel, "top": top, "breadth": max(breadth, 0.0), "fullness": 2.0, "flat": 0.0}
    eta = np.linspace(0.0, 1.0, ETA_SAMPLES)
    target = np.interp(keel + eta * (top - keel), z, y) / breadth

    def residual(values):
        return section_shape(eta, values[0], values[1]) - target

    fit = least_squares(residual, [2.0, 0.1], bounds=([FULLNESS_BOUNDS[0], FLAT_BOUNDS[0]],
                                                      [FULLNESS_BOUNDS[1], FLAT_BOUNDS[1]]))
    return {"keel": keel, "top": top, "breadth": breadth,
            "fullness": float(fit.x[0]), "flat": float(fit.x[1])}


def _basis(x: np.ndarray, x_range: tuple[float, float]) -> np.ndarray:
    from scipy.interpolate import BSpline

    degree = 3
    inner = TREND_COEFFICIENTS - degree - 1
    knots = np.concatenate([np.zeros(degree + 1), np.linspace(0, 1, inner + 2)[1:-1], np.ones(degree + 1)])
    span = max(x_range[1] - x_range[0], 1e-9)
    u = np.clip((np.asarray(x, dtype=float) - x_range[0]) / span, 0.0, 1.0)
    return BSpline.design_matrix(u, knots, degree).toarray()


def fit_trend(x: np.ndarray, values: np.ndarray, weights: np.ndarray, x_range: tuple[float, float]) -> np.ndarray:
    """Penalised least-squares B-spline coefficients of one longitudinal curve."""
    basis = _basis(x, x_range)
    difference = np.diff(np.eye(TREND_COEFFICIENTS), 2, axis=0)
    penalty = TREND_PENALTY * float(np.mean(weights)) * difference.T @ difference
    normal = basis.T @ (weights[:, None] * basis) + penalty
    return np.linalg.solve(normal, basis.T @ (weights * values))


def trend_at(coefficients: dict, x: float, x_range: tuple[float, float]) -> dict:
    row = _basis(np.array([x]), x_range)[0]
    values = {name: float(row @ np.asarray(coefficients[name])) for name in PARAMETERS}
    values["breadth"] = max(values["breadth"], 0.0)
    values["fullness"] = float(np.clip(values["fullness"], *FULLNESS_BOUNDS))
    values["flat"] = float(np.clip(values["flat"], *FLAT_BOUNDS))
    return values


def trend_curve(values: dict, eta: np.ndarray) -> np.ndarray:
    return values["breadth"] * section_shape(eta, values["fullness"], values["flat"])


def _eta_curve(points_yz_m, keel: float, top: float, eta: np.ndarray) -> np.ndarray:
    points = np.asarray(points_yz_m, dtype=float)
    points = points[np.argsort(points[:, 1], kind="stable")]
    return np.interp(keel + eta * (top - keel), points[:, 1], points[:, 0])


# ------------------------------------------------------------------ the fit

def _interpolate_residual(x_anchor: np.ndarray, values: np.ndarray, x: float) -> np.ndarray | float:
    """PCHIP along x through the anchors' residuals; 0 outside the anchored range."""
    from scipy.interpolate import PchipInterpolator

    if len(x_anchor) == 0 or x < x_anchor[0] or x > x_anchor[-1]:
        return np.zeros(values.shape[1:]) if values.ndim > 1 else 0.0
    if len(x_anchor) == 1:
        return values[0]
    return PchipInterpolator(x_anchor, values, axis=0, extrapolate=False)(x)


def fit_vessel(declared: list[dict], anchors: list[Anchor]) -> VesselTable | None:
    """The first full hull: traced anchors kept exactly, gaps filled by the form fit.

    ``declared`` are the spec sections (``id``, ``x_m``, optional ``z_min_m``
    and ``z_max_m``). Returns None when no anchor is usable.
    """
    check_tops(anchors)
    kept, dropped = check_anchors(anchors)
    if not kept:
        return None
    kept = sorted(kept, key=lambda a: a.x_m)
    x_range = (min(float(s["x_m"]) for s in declared), max(float(s["x_m"]) for s in declared))
    params = [station_parameters(a.points_yz_m) for a in kept]
    x = np.array([a.x_m for a in kept])
    weights = np.array([max(a.weight, 1e-3) for a in kept])
    coefficients = {}
    for name in PARAMETERS:
        values = np.array([p[name] for p in params])
        if len(kept) >= 3:
            coefficients[name] = fit_trend(x, values, weights, x_range).tolist()
        else:  # Too few anchors for a curve: a constant.
            coefficients[name] = [float(np.average(values, weights=weights))] * TREND_COEFFICIENTS
    # Cosine spacing: more samples near the keel and the top, where sections turn fastest.
    eta = 0.5 * (1.0 - np.cos(np.linspace(0.0, np.pi, FITTED_ROW_SAMPLES)))
    residual_shape, residual_keel, residual_top = [], [], []
    for anchor, own in zip(kept, params):
        trend = trend_at(coefficients, anchor.x_m, x_range)
        residual_shape.append(_eta_curve(anchor.points_yz_m, own["keel"], own["top"], eta) - trend_curve(trend, eta))
        residual_keel.append(own["keel"] - trend["keel"])
        residual_top.append(own["top"] - trend["top"])
    residual_shape = np.array(residual_shape)
    residual_heights = np.column_stack([residual_keel, residual_top])
    by_id = {a.id: a for a in kept}
    dropped_by_id = {d["section_id"]: d["reason"] for d in dropped}
    rows, warnings = [], [{"kind": "anchor_dropped", "section_id": d["section_id"], "message": d["reason"]}
                          for d in dropped]
    for section in declared:
        sid, sx = section["id"], float(section["x_m"])
        anchor = by_id.get(sid)
        if anchor is not None:
            source = "fitted" if anchor.extended else "traced"
            rows.append(StationRow(id=sid, x_m=sx, points_yz_m=anchor.points_yz_m, source=source,
                                   locked=not anchor.extended, selection_section=anchor.selection_section,
                                   notes=list(anchor.notes)))
            continue
        trend = trend_at(coefficients, sx, x_range)
        keel_shift, top_shift = _interpolate_residual(x, residual_heights, sx)
        keel, top = trend["keel"] + float(keel_shift), trend["top"] + float(top_shift)
        low = float(section.get("z_min_m", keel))
        high = float(section.get("z_max_m", top))
        keel, top = max(keel, low), min(top, high)
        if top - keel <= 1e-3:
            keel, top = low, high
        breadths = trend_curve(trend, eta) + _interpolate_residual(x, residual_shape, sx)
        heights = keel + eta * (top - keel)
        points = np.column_stack([np.maximum(breadths, 0.0), heights])
        why = dropped_by_id.get(sid, "no traced line")
        rows.append(StationRow(id=sid, x_m=sx, points_yz_m=points.tolist(), source="fitted",
                               notes=[f"fitted ({why})"[:200]]))
    if not rows:
        return None
    report = check_fairness([{"id": r.id, "x_m": r.x_m, "points_yz_m": r.points_yz_m} for r in rows])
    warnings += [{"kind": "fairness", "section_id": e["section_id"], "message": e.get("reason", "")}
                 for e in report.get("sections", []) if e["flagged"]]
    trend_record = {"method": METHOD, "parameters": list(PARAMETERS), "x_range_m": list(x_range),
                    "coefficients": coefficients, "anchors": [a.id for a in kept],
                    "dropped": dropped}
    return VesselTable(rows, waterline_grid(rows), trend_record, warnings)


# ------------------------------------------------------------------ first hull

def suspect_order(anchors: list[Anchor]) -> list[str]:
    """Anchor ids, most suspect first: the D1 fairness ranking (flagged first, then by score)."""
    import copy

    probe = copy.deepcopy(anchors)
    check_tops(probe)
    report = check_fairness([{"id": a.id, "x_m": a.x_m, "points_yz_m": a.points_yz_m} for a in probe])
    ranked = [entry["section_id"] for entry in report.get("sections", [])]
    return ranked + [a.id for a in anchors if a.id not in ranked]


def first_hull(declared: list[dict], anchors: list[Anchor], base_spec: dict, build, *,
               max_retries: int = FALLBACK_RETRIES):
    """Fit, compile and build the first hull; a failed build never ends the draft.

    ``build(spec)`` builds one draft specification and returns a result that is
    truthy when a solid was made. When it fails (for example a centreline pinch
    makes an invalid shell), the most suspect anchor is left out and filled by
    the fit, and the build is tried again, up to ``max_retries`` times.
    Returns ``(table, result, left_out)``; ``result`` is falsy only when every
    try failed.
    """
    import copy

    from .vessel_model import build_spec

    order = suspect_order(anchors)
    left_out: list[str] = []
    table, result = None, None
    for _ in range(max_retries + 1):
        usable = [copy.deepcopy(a) for a in anchors if a.id not in left_out]
        table = fit_vessel(declared, usable)
        if table is None:
            break
        for row in table.stations:
            if row.id in left_out:
                row.notes.append("anchor left out: the build with it failed")
        result = build(build_spec(table, base_spec, declared))
        if result:
            break
        remaining = [sid for sid in order if sid not in left_out]
        if len(remaining) <= 1:
            break
        left_out.append(remaining[0])
    return table, result, left_out
