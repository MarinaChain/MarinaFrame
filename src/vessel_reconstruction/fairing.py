"""Hull fairing: fit one fair hull surface to all station sections at once.

The builder (``geometry.build_hull``) goes through every section exactly and joins
neighbouring stations with straight panels, so one bad cell or one misread station bends the
hull there. A naval architect fairs the lines instead: one smooth surface through all the
evidence, and a point that disagrees with its neighbours is questioned, not followed.
docs/HULL_FAIRING.md has the plan, the metrics and the results.

Surface. Every section is a half-breadth curve y(z) between its keel height z0 and its top
height z1. The builder matches sections by normalized height t = (z - z0) / (z1 - z0), so the
surface is y(x, t) together with z0(x) and z1(x). Along every row of constant t the half-breadths
of all stations are fitted with one robust cubic smoothing spline over the station positions x;
z0(x) and z1(x) are fitted the same way. Across t the sections are dense traced curves, so the
surface keeps their resolution: there is a row at every source t value.

Fairness penalty. The smoothing spline minimises
    sum_i w_i (y_i - f(x_i))^2 + lambda * integral f''(x)^2 dx,
the second-derivative ("bending") energy of a spline batten. Its minimiser is a natural cubic
spline with knots at the station positions (Reinsch 1967), so the knots are the stations: no knot
placement choice is left. lambda is set from a fairing length (FAIRING_LENGTH_FRACTION of the hull
length): roughly the distance over which the fit averages its neighbours.

Weights by source label (LABEL_WEIGHTS): traced > read > repaired > interpolated > ai_inferred.
The two terminal stations (stem and transom ends) are held (TERMINAL_WEIGHT); the keel row (t = 0)
and the deck-edge row (t = 1) have a strong weight (EDGE_ROW_WEIGHT); points on the centreline
(y = 0) stay on it.

Robust loss. Huber, by iteratively reweighted least squares: a point whose residual is above the
Huber scale (HUBER_FRACTION of the half-beam) gets the weight scale / residual, so it pulls the
surface with a bounded force, however wrong it is. One bad cell therefore cannot bend the hull.

Explainable. Each output section keeps its id, x and source label. Its ``fairing`` record keeps
the input points and how far the fit moved them. A point moved more than its label's tolerance
(TOLERANCE_FRACTION) gives a check item with the distance.

Only single-region sections (``points_yz_m``) are faired; multi-region stations are returned
unchanged with a check item.
"""
from __future__ import annotations

import os

import numpy as np
from scipy.interpolate import CubicSpline

from .fairness import half_breadth_at
from .schema import gap

METHOD = "robust_row_smoothing_splines_v1"
# Environment setting that turns fairing on in the pipeline's hull build (off by default).
SETTING = "MARINAFRAME_HULL_FAIRING"

# Relative least-squares weight of a point by the source label of its section. A weight of w
# counts like w observations of a traced point. Order from the plan: traced > read > repaired >
# interpolated > guessed. Model-inferred sections (ai_inferred, guessed) are the least sure.
LABEL_WEIGHTS = {"traced": 1.0, "read": 0.8, "repaired": 0.5, "interpolated": 0.3,
                 "ai_inferred": 0.2, "guessed": 0.2}
UNKNOWN_LABEL_WEIGHT = 0.2
# The first and last stations close the hull at the transom and stem. This weight is so large
# against the others that the fit goes through them (to about 1e-4 of their residual).
TERMINAL_WEIGHT = 1e4
# The keel row (t = 0) and deck-edge row (t = 1) are fitted ten times as strongly as the rows
# between: the keel line and the sheer line are the hull's boundary curves.
EDGE_ROW_WEIGHT = 10.0
# Fairing length as a fraction of the hull length: half the spacing of a ten-station body plan.
# The fit averages over about this distance, so a feature longer than about a station spacing
# is kept and a one-station kink is pulled towards its neighbours.
FAIRING_LENGTH_FRACTION = 0.05
# Huber scale as a fraction of the half-beam (for z0 and z1: of the hull height): 1 %, half the
# RMS gate. Residuals below it are least squares; above it the pull of a point stops growing.
HUBER_FRACTION = 0.01
# Iteratively reweighted least squares stops when no fitted value changes by more than this
# fraction of the Huber scale, or after ROBUST_ITERATIONS rounds.
CONVERGENCE_FRACTION = 1e-4
ROBUST_ITERATIONS = 50
# A point moved further than this fraction of the half-beam gets a check item. Traced and read
# points are measured evidence (1 %, half the RMS gate); the others may move more (5 %).
TOLERANCE_FRACTION = {"traced": 0.01, "read": 0.01}
OTHER_TOLERANCE_FRACTION = 0.05
# Source t values closer than this are one row (a millionth of the section height).
ROW_DECIMALS = 6
# Rows evenly spaced in t for the sections added between stations (``between`` > 0).
BETWEEN_ROWS = 129
MINIMUM_SECTIONS = 4

# Fairness metrics (docs/HULL_FAIRING.md 3.2). Waterlines evenly spaced between the lowest keel
# and the highest top, the end rows left out; heights per section, evenly spaced.
METRIC_WATERLINES = 20
METRIC_SECTION_HEIGHTS = 21
# A second difference smaller than this fraction of the half-beam (per station spacing squared
# along a waterline, per height step squared along a section) is noise, not a change of sign.
METRIC_NOISE_FLOOR = 0.002


def enabled() -> bool:
    """True when the environment setting turns fairing on."""
    return os.environ.get(SETTING, "").strip() == "1"


def label_of(section: dict) -> str:
    return str(section.get("source_label") or "traced")


def label_weight(label: str) -> float:
    return LABEL_WEIGHTS.get(label, UNKNOWN_LABEL_WEIGHT)


def tolerance_fraction(label: str) -> float:
    return TOLERANCE_FRACTION.get(label, OTHER_TOLERANCE_FRACTION)


def bending_matrix(x: np.ndarray) -> np.ndarray:
    """K with integral f''^2 = g^T K g for the natural cubic spline through values g at knots x.

    Reinsch's form K = Q R^-1 Q^T: Q (n x n-2) takes second divided differences, R (n-2 x n-2)
    is the tridiagonal Gram matrix of the hat functions of the second derivative.
    """
    n = len(x)
    h = np.diff(x)
    q = np.zeros((n, n - 2))
    r = np.zeros((n - 2, n - 2))
    for j in range(n - 2):
        q[j, j] = 1 / h[j]
        q[j + 1, j] = -1 / h[j] - 1 / h[j + 1]
        q[j + 2, j] = 1 / h[j + 1]
        r[j, j] = (h[j] + h[j + 1]) / 3
        if j + 1 < n - 2:
            r[j, j + 1] = r[j + 1, j] = h[j + 1] / 6
    return q @ np.linalg.solve(r, q.T)


def smoothing_lambda(n_stations: int, fairing_length_fraction: float) -> float:
    """lambda for x measured in hull lengths, so the fit averages over the fairing length.

    For a smoothing spline with a weight density rho per unit length, the equivalent kernel
    has the width (lambda / rho)^(1/4) (Silverman 1984). With n stations of unit weight over
    one hull length rho = n - 1, so lambda = (n - 1) * length^4.
    """
    return (n_stations - 1) * fairing_length_fraction ** 4


def robust_smooth(u: np.ndarray, values: np.ndarray, weights: np.ndarray, lam: float,
                  scale: float, held: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Huber smoothing splines of several rows at once.

    ``values`` and ``weights`` are (rows, stations); ``u`` the station positions in hull lengths;
    ``held`` marks stations that are never down-weighted (the terminal stations). Returns the
    fitted values at the stations and the final Huber weights (1 inside the scale).
    """
    penalty = lam * bending_matrix(u)
    huber = np.ones_like(values)
    fitted = values.copy()
    for _ in range(ROBUST_ITERATIONS):
        w = weights * huber
        system = penalty[None, :, :] + w[:, :, None] * np.eye(len(u))[None, :, :]
        new = np.linalg.solve(system, (w * values)[:, :, None])[:, :, 0]
        change = float(np.max(np.abs(new - fitted)))
        fitted = new
        residual = np.abs(values - fitted)
        huber = np.where(residual > scale, scale / np.maximum(residual, 1e-300), 1.0)
        huber[:, held] = 1.0
        if change <= CONVERGENCE_FRACTION * scale:
            break
    return fitted, huber


def _parse(sections: list[dict]) -> list[dict] | None:
    """Stations ordered by x with points sorted by height, or None when one cannot be faired."""
    stations = []
    for section in sorted(sections, key=lambda s: float(s["x_m"])):
        if "regions" in section or "points_yz_m" not in section:
            return None
        points = np.asarray(section["points_yz_m"], dtype=float)
        if points.ndim != 2 or points.shape[1] != 2 or len(points) < 2 or not np.isfinite(points).all():
            return None
        points = points[np.argsort(points[:, 1], kind="stable")]
        y, z = points[:, 0], points[:, 1]
        if np.any(np.diff(z) <= 0) or np.min(y) < 0:
            return None
        stations.append({"section": section, "x": float(section["x_m"]), "y": y, "z": z,
                         "t": np.round((z - z[0]) / (z[-1] - z[0]), ROW_DECIMALS),
                         "label": label_of(section)})
    if len(stations) < MINIMUM_SECTIONS or np.min(np.diff([s["x"] for s in stations])) <= 0:
        return None
    return stations


def _half_beam(stations: list[dict]) -> float:
    """Largest half-breadth of the measured (traced or read) stations, else of all stations."""
    measured = [s for s in stations if s["label"] in TOLERANCE_FRACTION] or stations
    return float(max(np.max(s["y"]) for s in measured))


def _not_applied(sections: list[dict], reason: str) -> tuple[list[dict], dict]:
    item = gap("fairing_not_applied", f"Hull fairing was not applied: {reason} The hull goes through "
               "the sections as given.", severity="warning")
    return sections, {"method": METHOD, "applied": False, "reason": reason, "check_items": [item]}


def fair_sections(sections: list[dict], *, fairing_length_fraction: float = FAIRING_LENGTH_FRACTION,
                  between: int = 0, fair_heights: bool = True) -> tuple[list[dict], dict]:
    """Sections taken from one fair surface fitted to all of ``sections``, and a report.

    ``between`` adds that many faired sections (label ``interpolated``) between each pair of
    neighbouring stations, so the solid follows the faired surface between stations too.
    ``fair_heights`` also fairs the keel and top heights z0(x), z1(x).
    """
    stations = _parse(sections)
    if stations is None:
        return _not_applied(sections, "it needs at least four single-region sections with increasing "
                                      "heights and distinct stations.")
    x = np.array([s["x"] for s in stations])
    length = float(x[-1] - x[0])
    u = (x - x[0]) / length
    lam = smoothing_lambda(len(x), fairing_length_fraction)
    half_beam = _half_beam(stations)
    held = np.zeros(len(x), dtype=bool)
    held[[0, -1]] = True
    station_weight = np.array([label_weight(s["label"]) for s in stations])
    station_weight[held] = TERMINAL_WEIGHT

    rows = np.unique(np.concatenate([s["t"] for s in stations]
                                    + ([np.linspace(0, 1, BETWEEN_ROWS)] if between else [])))
    values = np.array([np.interp(rows, s["t"], s["y"]) for s in stations]).T  # (rows, stations)
    weights = np.repeat(station_weight[None, :], len(rows), axis=0)
    weights[(rows == 0) | (rows == 1)] *= EDGE_ROW_WEIGHT
    fitted, huber = robust_smooth(u, values, weights, lam, HUBER_FRACTION * half_beam, held)

    z0 = np.array([s["z"][0] for s in stations])
    z1 = np.array([s["z"][-1] for s in stations])
    if fair_heights:
        height = float(np.max(z1) - np.min(z0))
        heights, _ = robust_smooth(u, np.vstack([z0, z1]), np.vstack([station_weight, station_weight]),
                                   lam, HUBER_FRACTION * height, held)
        z0_fit, z1_fit = heights
        if np.any(z1_fit <= z0_fit):
            z0_fit, z1_fit = z0, z1
    else:
        z0_fit, z1_fit = z0, z1

    faired, moves = [], []
    for j, station in enumerate(stations):
        index = np.searchsorted(rows, station["t"])
        y = _keep_centreline(station["y"], fitted[index, j])
        z = z0_fit[j] + station["t"] * (z1_fit[j] - z0_fit[j])
        move = np.hypot(y - station["y"], z - station["z"])
        moves.append(move)
        record = {"method": METHOD, "input_points_yz_m": np.column_stack([station["y"], station["z"]]).tolist(),
                  "max_move_m": float(np.max(move)), "tolerance_m": tolerance_fraction(station["label"]) * half_beam,
                  "down_weighted_points": int(np.sum(huber[index, j] < 1))}
        faired.append({**station["section"], "points_yz_m": np.column_stack([y, z]).tolist(), "fairing": record})
    if between:
        faired = _with_between(faired, stations, u, rows, fitted, z0_fit, z1_fit, x, between)

    check_items = _check_items(stations, moves, half_beam)
    report = {
        "method": METHOD, "applied": True,
        "parameters": {"fairing_length_fraction": fairing_length_fraction, "lambda": lam,
                       "huber_scale_m": HUBER_FRACTION * half_beam, "half_beam_m": half_beam,
                       "label_weights": LABEL_WEIGHTS, "terminal_weight": TERMINAL_WEIGHT,
                       "edge_row_weight": EDGE_ROW_WEIGHT, "rows": len(rows), "between": between,
                       "fair_heights": fair_heights},
        "moves_by_label": _moves_by_label(stations, moves, half_beam),
        "check_items": check_items,
        "engineering_approved": False,
    }
    return faired, report


def _keep_centreline(y_in: np.ndarray, y_fit: np.ndarray) -> np.ndarray:
    """Faired half-breadths: centreline points stay on it, no negative breadth, no interior pinch.

    Where clipping would put a zero between positive breadths (an interior pinch the builder
    cannot loft), the input breadth is kept at that point.
    """
    y = np.where(y_in > 0, np.maximum(y_fit, 0.0), 0.0)
    positive = np.flatnonzero(y_in > 0)
    if len(positive):
        span = slice(positive[0], positive[-1] + 1)
        pinch = (y[span] <= 0) & (y_in[span] > 0)
        y[span] = np.where(pinch, y_in[span], y[span])
    return y


def _with_between(faired: list[dict], stations: list[dict], u: np.ndarray, rows: np.ndarray,
                  fitted: np.ndarray, z0: np.ndarray, z1: np.ndarray, x: np.ndarray, between: int) -> list[dict]:
    """Insert ``between`` sections of the faired surface between each pair of stations."""
    grid = np.linspace(0, 1, BETWEEN_ROWS)
    index = np.searchsorted(rows, np.round(grid, ROW_DECIMALS))
    surface = CubicSpline(u, fitted[index].T, axis=0, bc_type="natural")
    keel = CubicSpline(u, z0, bc_type="natural")
    top = CubicSpline(u, z1, bc_type="natural")
    result = []
    for j in range(len(stations) - 1):
        result.append(faired[j])
        for k in range(1, between + 1):
            share = k / (between + 1)
            x_new = float(x[j] + share * (x[j + 1] - x[j]))
            u_new = (x_new - x[0]) / (x[-1] - x[0])
            y = np.maximum(surface(u_new), 0.0)
            if stations[j]["y"][0] == 0 and stations[j + 1]["y"][0] == 0:
                y[0] = 0.0
            # Where the spline dips to zero above the keel point (an interior pinch the builder
            # cannot loft), the straight line between the two faired stations is used.
            straight = (1 - share) * fitted[index, j] + share * fitted[index, j + 1]
            positive = np.flatnonzero(y > 0)
            if len(positive):
                span = slice(positive[0], positive[-1] + 1)
                y[span] = np.where(y[span] > 0, y[span], straight[span])
            z = float(keel(u_new)) + grid * float(top(u_new) - keel(u_new))
            ids = (stations[j]["section"].get("id"), stations[j + 1]["section"].get("id"))
            result.append({"id": f"faired-{ids[0]}-{ids[1]}-{k}", "x_m": x_new,
                           "points_yz_m": np.column_stack([y, z]).tolist(), "confidence": 0.0, "coverage": 0.0,
                           "source_label": "interpolated",
                           "evidence": {"basis": f"Faired hull surface between stations {ids[0]} and {ids[1]}."},
                           "warnings": [], "fairing": {"method": METHOD, "between": [ids[0], ids[1]]}})
    result.append(faired[-1])
    return result


def _moves_by_label(stations: list[dict], moves: list[np.ndarray], half_beam: float) -> dict:
    summary = {}
    for label in sorted({s["label"] for s in stations}):
        distance = np.concatenate([m for s, m in zip(stations, moves) if s["label"] == label])
        tolerance = tolerance_fraction(label) * half_beam
        summary[label] = {"points": int(len(distance)), "max_m": float(np.max(distance)),
                          "p95_m": float(np.percentile(distance, 95)), "tolerance_m": tolerance,
                          "within_tolerance": float(np.mean(distance <= tolerance))}
    return summary


def _check_items(stations: list[dict], moves: list[np.ndarray], half_beam: float) -> list[dict]:
    """One check item per section with points moved further than their label's tolerance."""
    items = []
    for station, move in zip(stations, moves):
        tolerance = tolerance_fraction(station["label"]) * half_beam
        outside = move > tolerance
        if not outside.any():
            continue
        worst = int(np.argmax(move))
        section_id = station["section"].get("id", "unnamed")
        items.append(gap(
            "fairing_moved_point",
            f"Fairing moved {int(outside.sum())} {station['label']} point(s) of this section by up to "
            f"{move[worst] * 1000:.0f} mm (tolerance {tolerance * 1000:.0f} mm); the largest at z = "
            f"{station['z'][worst]:.2f} m. The section disagrees with its neighbouring stations there: "
            "check its trace or reading.", section_id, severity="warning"))
    return items


# Fairness metrics ---------------------------------------------------------------------------


def _sign_changes(second: np.ndarray, floor: float) -> int:
    signs = np.sign(second[np.abs(second) > floor])
    return int(np.sum(signs[1:] != signs[:-1]))


def fairness_metrics(sections: list[dict], half_beam: float | None = None) -> dict:
    """Inflections per waterline and per section, and the largest curvature jump.

    Waterlines: half-breadth at METRIC_WATERLINES heights at every station whose height range
    covers that height; second divided differences over x in half-beams per mean station spacing
    squared. Sections: half-breadth at METRIC_SECTION_HEIGHTS heights between keel and top;
    plain second differences in half-beams. Inflections are sign changes of the second
    difference above METRIC_NOISE_FLOOR; the curvature jump is the largest change of the
    waterline second difference between neighbouring stations.
    """
    ordered = sorted((s for s in sections if "points_yz_m" in s), key=lambda s: float(s["x_m"]))
    curves = []
    for section in ordered:
        points = np.asarray(section["points_yz_m"], dtype=float)
        curves.append((float(section["x_m"]), points[np.argsort(points[:, 1], kind="stable")]))
    if half_beam is None:
        half_beam = float(max(np.max(p[:, 0]) for _, p in curves))
    low = min(p[0, 1] for _, p in curves)
    high = max(p[-1, 1] for _, p in curves)
    heights = low + (np.arange(METRIC_WATERLINES) + 0.5) / METRIC_WATERLINES * (high - low)
    x_all = np.array([x for x, _ in curves])
    spacing = (x_all[-1] - x_all[0]) / max(len(x_all) - 1, 1)
    waterline_inflections, jumps = [], []
    for height in heights:
        inside = [(x, float(half_breadth_at(p, np.array([height]))[0])) for x, p in curves
                  if p[0, 1] <= height <= p[-1, 1]]
        if len(inside) < 4:
            continue
        xs, ys = np.array(inside).T
        ys = ys / half_beam
        h = np.diff(xs) / spacing
        slope = np.diff(ys) / h
        second = 2 * np.diff(slope) / (h[:-1] + h[1:])
        waterline_inflections.append(_sign_changes(second, METRIC_NOISE_FLOOR))
        if len(second) > 1:
            jumps.append(float(np.max(np.abs(np.diff(second)))))
    section_inflections = []
    for _, p in curves:
        z = np.linspace(p[0, 1], p[-1, 1], METRIC_SECTION_HEIGHTS)
        y = np.interp(z, p[:, 1], p[:, 0]) / half_beam
        section_inflections.append(_sign_changes(np.diff(y, 2), METRIC_NOISE_FLOOR))
    return {"waterline_inflections": int(sum(waterline_inflections)), "waterlines": len(waterline_inflections),
            "section_inflections": int(sum(section_inflections)), "sections": len(section_inflections),
            "max_curvature_jump": float(max(jumps)) if jumps else 0.0}
