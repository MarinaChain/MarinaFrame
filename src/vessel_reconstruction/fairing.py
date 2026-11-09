"""Hull fairing: fit one fair hull surface to all station sections at once.

The builder (``geometry.build_hull``) goes through every section exactly and joins
neighbouring stations with straight panels, so one bad cell or one misread station bends the
hull there. A naval architect fairs the lines instead: one smooth surface through all the
evidence, and a point that disagrees with its neighbours is questioned, not followed.
docs/HULL_FAIRING.md has the plan, the metrics and the results.

Surface. Every section is a half-breadth curve y(z). The faired surface is y(u, z): along every
waterline (constant height z, as on a lines plan) the half-breadths of the stations that reach
that height are fitted with one cubic smoothing spline over the station coordinate u. There is a
waterline at every source height, so the surface keeps the resolution of the traced curves.
Keel and top heights of each station are kept: they come from the profile.

Station coordinate. u is the station index (0, 1, 2, ...), not the distance x. Stations are
drawn closer together where the hull changes faster, so the fairing length is a share of the
local station spacing everywhere.

Fairness penalty. The smoothing spline minimises
    sum_i w_i (y_i - f(u_i))^2 + lambda * integral f''(u)^2 du,
the second-derivative ("bending") energy of a spline batten. Its minimiser is a natural cubic
spline with knots at the stations (Reinsch 1967), so the knots are the stations: no knot placement
choice is left. lambda = FAIRING_LENGTH_SPACINGS^4: the fit averages over about that share of a
station spacing.

Weights by source label (LABEL_WEIGHTS): traced > read > repaired > interpolated > ai_inferred.
Constraints: with ``keep_ends`` only the stations from the first to the last measured (traced or
read) station are faired; the end stations outside them come from the profile and plan (stem,
transom) and are kept as given. A faired station that is a hull terminal is held
(TERMINAL_WEIGHT). Each station's keel point and deck-edge point are fitted strongly
(EDGE_POINT_WEIGHT); points on the centreline (y = 0) stay on it.

Robust loss. Huber weights: a half-breadth further than the Huber scale (HUBER_FRACTION of the
half-beam) outside the range of its two neighbouring stations on the same waterline gets the
weight scale / excess, so its pull is bounded. Limit (docs/HULL_FAIRING.md 6): a bad value inside
its neighbours' range is not recognised, and at a ten-station spacing the hull itself changes by
1-4 % of the half-beam between stations, so most single bad cells of that size are not. The weights are judged against the neighbours, not against the
fit: a fit residual would also down-weight a fair shoulder of the parallel middle body that the
spline cannot follow exactly, and the spline would then overshoot there.

Explainable. Each output section keeps its id, x and source label. Its ``fairing`` record keeps
the input points and how far the fit moved them. A point moved more than its label's tolerance
(TOLERANCE_FRACTION) gives a check item with the distance.

Only single-region sections (``points_yz_m``) are faired; multi-region stations are returned
unchanged with a check item.
"""
from __future__ import annotations

import os

import numpy as np

from .fairness import half_breadth_at
from .schema import gap

METHOD = "robust_waterline_smoothing_splines_v3"
# Environment setting that turns fairing on in the pipeline's hull build (off by default).
SETTING = "MARINAFRAME_HULL_FAIRING"

# Relative least-squares weight of a point by the source label of its section. A weight of w
# counts like w observations of a traced point. Order from the plan: traced > read > repaired >
# interpolated > guessed. Model-inferred sections (ai_inferred, guessed) are the least sure.
LABEL_WEIGHTS = {"traced": 1.0, "read": 0.8, "repaired": 0.5, "interpolated": 0.3,
                 "ai_inferred": 0.2, "guessed": 0.2}
UNKNOWN_LABEL_WEIGHT = 0.2
# A held station's weight: so large against the others that the fit goes through it (to about
# 1e-4 of its residual).
TERMINAL_WEIGHT = 1e4
# Each station's keel point and deck-edge point are fitted ten times as strongly as its other
# points: the keel line and the sheer line are the hull's boundary curves.
EDGE_POINT_WEIGHT = 10.0
# Fairing length in station spacings: the fit averages over about this distance. 0.2 was chosen
# on the development replay (docs/HULL_FAIRING.md 6): 0.5 smoothed real shoulders of fine bows
# (shipd-1-09867-3v-L1 1.00 -> 2.37 % RMS). Outliers are handled by the robust weights below.
FAIRING_LENGTH_SPACINGS = 0.2
# Huber scale as a fraction of the half-beam: 1 %, half the RMS gate.
HUBER_FRACTION = 0.01
# A rejection distance (no weight from 2 % of half-beam outside the neighbours' range) was tried
# on the development replay and not kept: it moved fair traced points by metres where the hull
# changes faster than the station spacing (shipd-1-09867-3v-L0 3.25 -> 4.27 % RMS).
# A point moved further than this fraction of the half-beam gets a check item. Traced and read
# points are measured evidence (1 %, half the RMS gate); the others may move more (5 %).
TOLERANCE_FRACTION = {"traced": 0.01, "read": 0.01}
OTHER_TOLERANCE_FRACTION = 0.05
# Source heights closer than this are one waterline (a micrometre).
ROW_DECIMALS = 6
# Waterlines that fewer stations reach are not faired (three give each one two neighbours).
MINIMUM_ROW_STATIONS = 3
MINIMUM_SECTIONS = 4
# Added to the diagonal so a waterline with absent stations stays solvable; far below any weight.
RIDGE = 1e-9

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


def bending_matrix(u: np.ndarray) -> np.ndarray:
    """K with integral f''^2 = g^T K g for the natural cubic spline through values g at knots u.

    Reinsch's form K = Q R^-1 Q^T: Q (n x n-2) takes second divided differences, R (n-2 x n-2)
    is the tridiagonal Gram matrix of the hat functions of the second derivative.
    """
    n = len(u)
    h = np.diff(u)
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


def smoothing_lambda(fairing_length_spacings: float) -> float:
    """lambda for u in station spacings, so the fit averages over the fairing length.

    For a smoothing spline with a weight density rho per unit of u, the equivalent kernel has
    the width (lambda / rho)^(1/4) (Silverman 1984). One station of unit weight per spacing gives
    rho = 1, so lambda = length^4.
    """
    return fairing_length_spacings ** 4


def neighbour_excess(values: np.ndarray, present: np.ndarray) -> np.ndarray:
    """How far each half-breadth lies outside the range of its two neighbouring stations.

    ``values`` and ``present`` are (rows, stations). A value is judged only when both
    neighbouring stations reach that waterline; otherwise its excess is 0 (no evidence against
    it). A fair hull lies within these ranges except at a smooth peak, where the excess is small.
    """
    excess = np.zeros_like(values)
    left, middle, right = values[:, :-2], values[:, 1:-1], values[:, 2:]
    judged = present[:, :-2] & present[:, 1:-1] & present[:, 2:]
    outside = np.maximum(middle - np.maximum(left, right), np.minimum(left, right) - middle)
    excess[:, 1:-1] = np.where(judged, np.maximum(outside, 0.0), 0.0)
    return excess


def robust_smooth(u: np.ndarray, values: np.ndarray, weights: np.ndarray, present: np.ndarray,
                  lam: float, scale: float, held: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Huber-weighted smoothing splines of all waterlines at once.

    ``values``, ``weights`` and ``present`` are (rows, stations); absent stations have no
    weight. A value more than ``scale`` outside its neighbours' range gets the Huber weight
    scale / excess. Returns the fitted values (absent and thin rows unchanged) and the weights.
    """
    excess = neighbour_excess(values, present)
    huber = np.where(excess > scale, scale / np.maximum(excess, 1e-300), 1.0)
    huber[:, held] = 1.0
    w = np.where(present, weights * huber, 0.0)
    system = lam * bending_matrix(u)[None, :, :] + (w + RIDGE)[:, :, None] * np.eye(len(u))[None, :, :]
    fitted = np.linalg.solve(system, (w * values)[:, :, None])[:, :, 0]
    thin = present.sum(axis=1) < MINIMUM_ROW_STATIONS
    fitted = np.where(present & ~thin[:, None], fitted, values)
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
        if np.any(np.diff(points[:, 1]) <= 0) or np.min(points[:, 0]) < 0:
            return None
        stations.append({"section": section, "x": float(section["x_m"]), "points": points,
                         "y": points[:, 0], "z": points[:, 1], "label": label_of(section)})
    if len(stations) < MINIMUM_SECTIONS or np.min(np.diff([s["x"] for s in stations])) <= 0:
        return None
    return stations


def _half_beam(stations: list[dict]) -> float:
    """Largest half-breadth of the measured (traced or read) stations, else of all stations."""
    measured = [s for s in stations if s["label"] in TOLERANCE_FRACTION] or stations
    return float(max(np.max(s["y"]) for s in measured))


def _fitted_span(stations: list[dict], keep_ends: bool) -> slice:
    """Stations the fit may move: with ``keep_ends``, from the first to the last measured one."""
    measured = [j for j, s in enumerate(stations) if s["label"] in TOLERANCE_FRACTION]
    if keep_ends and measured:
        return slice(measured[0], measured[-1] + 1)
    return slice(0, len(stations))


def _not_applied(sections: list[dict], reason: str) -> tuple[list[dict], dict]:
    item = gap("fairing_not_applied", f"Hull fairing was not applied: {reason} The hull goes through "
               "the sections as given.", severity="warning")
    return sections, {"method": METHOD, "applied": False, "reason": reason, "check_items": [item]}


def fair_sections(sections: list[dict], *, fairing_length_spacings: float = FAIRING_LENGTH_SPACINGS,
                  keep_ends: bool = True) -> tuple[list[dict], dict]:
    """Sections taken from one fair surface fitted to all of ``sections``, and a report.

    ``keep_ends`` keeps the stations outside the measured ones as given (module docstring).
    """
    stations = _parse(sections)
    if stations is None:
        return _not_applied(sections, "it needs at least four single-region sections with increasing "
                                      "heights and distinct stations.")
    span = _fitted_span(stations, keep_ends)
    fitted_stations = stations[span]
    if len(fitted_stations) < MINIMUM_SECTIONS:
        return _not_applied(sections, f"fewer than {MINIMUM_SECTIONS} measured stations to fair.")
    u = np.arange(len(fitted_stations), dtype=float)
    lam = smoothing_lambda(fairing_length_spacings)
    half_beam = _half_beam(stations)
    # A station that is also a hull terminal (transom or stem end) is held.
    held = np.array([span.start + j in (0, len(stations) - 1) for j in range(len(fitted_stations))])
    station_weight = np.array([label_weight(s["label"]) for s in fitted_stations])
    station_weight[held] = TERMINAL_WEIGHT

    # Waterlines at every source height; (rows, stations) half-breadths where a station reaches.
    rows = np.unique(np.round(np.concatenate([s["z"] for s in fitted_stations]), ROW_DECIMALS))
    present = np.array([(rows >= np.round(s["z"][0], ROW_DECIMALS)) & (rows <= np.round(s["z"][-1], ROW_DECIMALS))
                        for s in fitted_stations]).T
    values = np.array([np.interp(rows, s["z"], s["y"]) for s in fitted_stations]).T
    weights = np.repeat(station_weight[None, :], len(rows), axis=0)
    for k, s in enumerate(fitted_stations):
        edges = np.searchsorted(rows, np.round([s["z"][0], s["z"][-1]], ROW_DECIMALS))
        weights[edges, k] *= EDGE_POINT_WEIGHT
    fitted, huber = robust_smooth(u, values, weights, present, lam, HUBER_FRACTION * half_beam, held)

    faired, moves = [], []
    for j, station in enumerate(stations):
        k = j - span.start
        inside = 0 <= k < len(fitted_stations)
        if inside:
            index = np.searchsorted(rows, np.round(station["z"], ROW_DECIMALS))
            y = _keep_centreline(station["y"], fitted[index, k])
            down_weighted = int(np.sum(huber[index, k] < 1))
        else:
            y, down_weighted = station["y"].copy(), 0
        move = np.abs(y - station["y"])
        moves.append(move)
        record = {"method": METHOD, "input_points_yz_m": station["points"].tolist(),
                  "max_move_m": float(np.max(move)), "tolerance_m": tolerance_fraction(station["label"]) * half_beam,
                  "faired": inside, "held": bool(inside and held[k]), "down_weighted_points": down_weighted}
        faired.append({**station["section"], "points_yz_m": np.column_stack([y, station["z"]]).tolist(),
                       "fairing": record})

    report = {
        "method": METHOD, "applied": True,
        "parameters": {"fairing_length_spacings": fairing_length_spacings, "lambda": lam,
                       "huber_scale_m": HUBER_FRACTION * half_beam, "half_beam_m": half_beam,
                       "label_weights": LABEL_WEIGHTS, "terminal_weight": TERMINAL_WEIGHT,
                       "edge_point_weight": EDGE_POINT_WEIGHT, "waterlines": len(rows),
                       "faired_stations": [s["section"].get("id") for s in fitted_stations],
                       "held_stations": [s["section"].get("id") for s, h in zip(fitted_stations, held) if h]},
        "moves_by_label": _moves_by_label(stations, moves, half_beam),
        "check_items": _check_items(stations, moves, half_beam),
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
