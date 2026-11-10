"""One robust tensor spline constrained by body, plan and profile observations.

The unknown is breadth y(x, t), t = sqrt((z - keel(x))/(deck(x)-keel(x))).
The square root resolves round bilges without many vertical knots. A Coons
boundary patch holds the two terminal sections and every keel/deck edge exactly.
A cubic tensor B-spline correction vanishes on those boundaries. Centreline
observations inside the patch are exact linear equalities, solved by elimination.

Profile keel/deck observations fit a robust, anchored height envelope between
source stations. Profile stem/stern observations are checked against the held
terminal domain: conflicting silhouettes are reported, never used to invent a
new terminal cap. Plan observations constrain breadth at true heights. Huber
IRLS and a second-difference coefficient penalty fit all adjustable breadths
at once. View weights are normalised by view count, so pixel density cannot
make a densely sampled view dominate solely by its point count.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy import linalg
from scipy.interpolate import BSpline, PchipInterpolator

from . import fairing
from . import fairing_shared
from .schema import gap

METHOD = "three_view_robust_tensor_spline_v1"
DEFAULT_PLAN_WEIGHT = 0.5
FAIRNESS = .02
IRLS_ITERATIONS = 12
# Output samples resolve the continuous surface between the original vertices.
SECTION_SAMPLES = 65
# A tiny positive interior breadth avoids a numerical pinch. All such projections
# are counted; source centreline points and hard boundaries are exempt.
MINIMUM_BREADTH_FRACTION = 1e-6


def _huber(residual, scale):
    return np.minimum(1., scale / np.maximum(np.abs(residual), 1e-300))


def _knots(interior):
    return np.r_[np.zeros(4), interior, np.ones(4)]


def _basis(values, knots):
    return BSpline.design_matrix(np.clip(values, 0, 1), knots, 3).toarray()


class Envelope:
    """Height curve with exact source heights and robust profile evidence in each gap."""

    def __init__(self, xs, heights, points, target, scale, profile_weight, fairness):
        self.xs = xs
        self.base = PchipInterpolator(xs, heights)
        self.amplitudes = np.zeros(len(xs) - 1)
        rows = [p for p in points if p["view"] == "profile" and p["target"] == target
                and xs[0] < p["x_m"] < xs[-1]]
        if not rows:
            return
        x = np.array([p["x_m"] for p in rows])
        z = np.array([p["z_m"] for p in rows])
        indices, bubbles = self._gaps(x)
        weight = np.array([profile_weight * fairing.label_weight(p["source_label"]) * p.get("confidence", 1.)
                           for p in rows]) / len(rows)
        residual = z - self.base(x)
        for _ in range(IRLS_ITERATIONS):
            w = weight * _huber(residual - bubbles * self.amplitudes[indices], scale)
            numerator = np.bincount(indices, weights=w * bubbles * residual, minlength=len(self.amplitudes))
            denominator = np.bincount(indices, weights=w * bubbles ** 2, minlength=len(self.amplitudes))
            self.amplitudes = numerator / (denominator + fairness / len(self.amplitudes))

    def _gaps(self, x):
        i = np.clip(np.searchsorted(self.xs, x, side="right") - 1, 0, len(self.xs) - 2)
        share = (x - self.xs[i]) / (self.xs[i + 1] - self.xs[i])
        # Value and first derivative are zero at both anchors.
        return i, (4 * share * (1 - share)) ** 2

    def __call__(self, x):
        i, bubble = self._gaps(x)
        return self.base(x) + bubble * self.amplitudes[i]


@dataclass
class Surface:
    stations: list[dict]
    points: list[dict]
    half_beam: float
    profile_weight: float
    fairness: float

    def __post_init__(self):
        self.xs = np.array([s["x"] for s in self.stations])
        self.length = self.xs[-1] - self.xs[0]
        self.scale = fairing.HUBER_FRACTION * self.half_beam
        self.low = Envelope(self.xs, [s["z"][0] for s in self.stations], self.points, "keel",
                            self.scale, self.profile_weight, self.fairness)
        self.high = Envelope(self.xs, [s["z"][-1] for s in self.stations], self.points, "top",
                             self.scale, self.profile_weight, self.fairness)
        self.low_y = PchipInterpolator(self.xs, [s["y"][0] for s in self.stations])
        self.high_y = PchipInterpolator(self.xs, [s["y"][-1] for s in self.stations])
        self.x_knots = _knots((self.xs[1:-1] - self.xs[0]) / self.length)
        self.t_knots = _knots(np.arange(.1, 1., .1))
        self.shape = (len(self.x_knots) - 4, len(self.t_knots) - 4)
        self.coefficients = np.zeros(np.prod(self.shape))

    def coordinates(self, x, z):
        x, z = np.broadcast_arrays(np.asarray(x, dtype=float), np.asarray(z, dtype=float))
        low, high = self.low(x), self.high(x)
        if np.any(high <= low):
            raise ValueError("Profile envelope has nonpositive height")
        return (x - self.xs[0]) / self.length, np.sqrt(np.clip((z - low) / (high - low), 0, 1))

    def boundary(self, x, t):
        u = (x - self.xs[0]) / self.length
        left, right = self.stations[0], self.stations[-1]
        left_z = left["z"][0] + t ** 2 * (left["z"][-1] - left["z"][0])
        right_z = right["z"][0] + t ** 2 * (right["z"][-1] - right["z"][0])
        across = (1 - u) * np.interp(left_z, left["z"], left["y"]) + u * np.interp(right_z, right["z"], right["y"])
        along = (1 - t) * self.low_y(x) + t * self.high_y(x)
        corners = ((1 - u) * ((1 - t) * left["y"][0] + t * left["y"][-1])
                   + u * ((1 - t) * right["y"][0] + t * right["y"][-1]))
        return across + along - corners

    def design(self, x, z):
        u, t = self.coordinates(x, z)
        tensor = np.einsum("ij,ik->ijk", _basis(u, self.x_knots), _basis(t, self.t_knots)).reshape(len(u), -1)
        mask = 16 * u * (1 - u) * t * (1 - t)
        return tensor * mask[:, None], self.boundary(x, t)

    def raw(self, x, z):
        x, z = np.broadcast_arrays(np.atleast_1d(x).astype(float), np.atleast_1d(z).astype(float))
        matrix, boundary = self.design(x, z)
        return boundary + matrix @ self.coefficients

    def breadth(self, x, z):
        values = self.raw(x, z)
        _, t = self.coordinates(np.broadcast_to(x, values.shape), np.broadcast_to(z, values.shape))
        boundary = (t < 1e-12) | (t > 1 - 1e-12)
        centreline = np.abs(values) < 1e-9
        return np.where(boundary | centreline, values, np.maximum(values, MINIMUM_BREADTH_FRACTION * self.half_beam))

    def fit(self, observations, plan_weight):
        x, y, z = np.array([[p["x_m"], p["y_m"], p["z_m"]] for p in observations]).T
        matrix, boundary = self.design(x, z)
        target = y - boundary
        counts = {view: sum(p["view"] == view for p in observations) for view in ("body_plan", "half_breadth_plan")}
        weights = np.array([(plan_weight if p["view"] == "half_breadth_plan" else 1.)
                            * fairing.label_weight(p["source_label"]) * p.get("confidence", 1.) / counts[p["view"]]
                           for p in observations])
        nx, nt = self.shape
        penalty = np.vstack([np.kron(np.diff(np.eye(nx), 2, axis=0), np.eye(nt)),
                             np.kron(np.eye(nx), np.diff(np.eye(nt), 2, axis=0))])
        penalty *= np.sqrt(self.fairness / len(penalty))
        centre = (y == 0) & (np.max(np.abs(matrix), axis=1) > 1e-10)
        constraints = matrix[centre]
        origin = np.zeros(matrix.shape[1])
        null = np.eye(matrix.shape[1])
        if len(constraints):
            origin = linalg.lstsq(constraints, target[centre], lapack_driver="gelsy")[0]
            if np.max(np.abs(constraints @ origin - target[centre])) > 1e-8:
                raise ValueError("Centreline conflicts with hard boundary patch")
            null = linalg.null_space(constraints)
        reduced = matrix @ null
        rhs = target - matrix @ origin
        regularizer = penalty @ null
        fixed_penalty = penalty @ origin
        current = np.zeros(null.shape[1])
        for iteration in range(IRLS_ITERATIONS):
            w = weights * _huber(reduced @ current - rhs, self.scale)
            system = reduced.T @ (w[:, None] * reduced) + regularizer.T @ regularizer
            system += 1e-10 * np.eye(len(system))
            next_values = linalg.solve(system, reduced.T @ (w * rhs) - regularizer.T @ fixed_penalty, assume_a="pos")
            change = np.max(np.abs(next_values - current), initial=0.)
            current = next_values
            if change < 1e-7 * self.half_beam:
                break
        self.coefficients = origin + null @ current
        return iteration + 1


def _body_points(stations):
    return [{"view": "body_plan", "target": "section", "curve_id": s["section"]["id"],
             "source_label": s["label"], "confidence": s["section"].get("confidence", 1.),
             "x_m": s["x"], "y_m": float(y), "z_m": float(z)}
            for s in stations for y, z in s["points"]]


def _half_stations(surface):
    measured = [s for s in surface.stations if s["label"] in ("traced", "read")]
    if len(measured) < 2:
        return []
    places = []
    for name, a, b in (("aft", measured[0], measured[1]), ("fore", measured[-2], measured[-1])):
        x = (a["x"] + b["x"]) / 2
        if x in surface.xs or any(p["x_m"] == x for p in places):
            continue
        # Both envelope curves need actual observations bracketing the place.
        covered = True
        for target in ("keel", "top"):
            xs = [p["x_m"] for p in surface.points if p["view"] == "profile" and p["target"] == target
                  and a["x"] <= p["x_m"] <= b["x"]]
            covered &= len(xs) >= 2 and min(xs) <= x <= max(xs)
        if covered:
            places.append({"id": f"fair-half-{name}", "x_m": x, "source_label": "interpolated",
                           "coverage": 0., "confidence": 0., "evidence": {
                               "basis": "Joint surface at a half station; profile fixes heights; shape fitted, not traced."}})
    return places


def _movement_report(surface, points):
    by_view, outside = {}, []
    # Longitudinal profile bounds at each height are found on the same domain.
    domain_x = np.unique(np.r_[surface.xs, np.linspace(surface.xs[0], surface.xs[-1], 801)])
    domain_low, domain_high = surface.low(domain_x), surface.high(domain_x)
    for point in points:
        view, label = point["view"], point["source_label"]
        x = float(np.clip(point["x_m"], surface.xs[0], surface.xs[-1]))
        z = point["z_m"]
        if view == "profile":
            if point["target"] in ("keel", "top"):
                fitted_z = float(surface.low(x) if point["target"] == "keel" else surface.high(x))
                distance = float(np.hypot(x - point["x_m"], fitted_z - z))
            else:
                present = domain_x[(domain_low <= z) & (domain_high >= z)]
                # No domain at this height is explicit unavailable evidence.
                if not len(present):
                    by_view.setdefault(view, {}).setdefault(label, []).append(None)
                    outside.append({**point, "move_m": None, "reason": "height outside fitted domain"})
                    continue
                fitted_x = present[-1] if point["target"] == "stem" else present[0]
                distance = float(abs(fitted_x - point["x_m"]))
        else:
            bounded_z = float(np.clip(z, surface.low(x), surface.high(x)))
            fitted_y = float(surface.breadth([x], [bounded_z])[0])
            distance = float(np.linalg.norm([x - point["x_m"], fitted_y - point["y_m"], bounded_z - z]))
        by_view.setdefault(view, {}).setdefault(label, []).append(distance)
        if distance > fairing.tolerance_fraction(label) * surface.half_beam:
            outside.append({"view": view, "curve_id": point["curve_id"], "source_label": label,
                            "x_m": point["x_m"], "z_m": z, "move_m": distance})
    summary = {}
    for view, labels in by_view.items():
        summary[view] = {}
        for label, values in labels.items():
            finite = [v for v in values if v is not None]
            tolerance = fairing.tolerance_fraction(label) * surface.half_beam
            summary[view][label] = {"points": len(values), "unavailable": len(values) - len(finite),
                                   "median_m": float(np.median(finite)) if finite else None,
                                   "p95_m": float(np.percentile(finite, 95)) if finite else None,
                                   "max_m": max(finite) if finite else None, "tolerance_m": tolerance,
                                   "within_tolerance": sum(v <= tolerance for v in finite) / len(values)}
    return summary, outside


def fair_sections(sections, evidence, *, plan_weight=DEFAULT_PLAN_WEIGHT, fairness=FAIRNESS, profile_weight=1.):
    stations = fairing_shared.parse_stations(sections)
    if stations is None:
        result, report = fairing_shared.not_applied(sections, "invalid single-region stations for a joint surface.")
        report.update(three_view_applied=False, three_view_reason=report["reason"])
        return result, report
    independent = [p for p in evidence.get("points", []) if p["view"] != "body_plan"]
    body = _body_points(stations)
    points = body + independent
    surface = Surface(stations, points, float(evidence["half_beam_m"]), profile_weight, fairness)
    observations = body + [p for p in independent if p["view"] == "half_breadth_plan"
                           and surface.xs[0] <= p["x_m"] <= surface.xs[-1]
                           and surface.low(p["x_m"]) <= p["z_m"] <= surface.high(p["x_m"])]
    iterations = surface.fit(observations, plan_weight)
    result, moves, projections = [], [], 0
    for i, station in enumerate(stations):
        source = station["points"]
        terminal = i in (0, len(stations) - 1)
        # Keep terminal polylines byte-for-byte, not approximately via a huge weight.
        if terminal:
            output = source.copy()
        else:
            z = np.unique(np.r_[station["z"], np.linspace(station["z"][0], station["z"][-1], SECTION_SAMPLES)])
            raw = surface.raw(np.full(len(z), station["x"]), z)
            projections += int(np.sum(raw < 0))
            y = np.maximum(raw, MINIMUM_BREADTH_FRACTION * surface.half_beam)
            # These are exact source boundary constraints, not a robust weight.
            y[0], y[-1] = source[0, 0], source[-1, 0]
            for height in station["z"][station["y"] == 0]:
                y[np.searchsorted(z, height)] = 0.
            output = np.column_stack([y, z])
        move = np.abs(np.interp(station["z"], output[:, 1], output[:, 0]) - station["y"])
        moves.append(move)
        result.append({**station["section"], "points_yz_m": output.tolist(), "fairing": {
            "method": METHOD, "input_points_yz_m": source.tolist(), "max_move_m": float(max(move)),
            "tolerance_m": fairing.tolerance_fraction(station["label"]) * surface.half_beam,
            "faired": not terminal, "held": terminal}})
    additions = _half_stations(surface)
    for place in additions:
        x = place["x_m"]
        z = np.linspace(surface.low(x), surface.high(x), SECTION_SAMPLES)
        y = surface.breadth(np.full(len(z), x), z)
        y[0], y[-1] = surface.low_y(x), surface.high_y(x)
        result.append({**place, "points_yz_m": np.column_stack([y, z]).tolist()})
    result.sort(key=lambda s: s["x_m"])
    summary, outside = _movement_report(surface, points)
    check_items = fairing_shared.check_items(stations, moves, surface.half_beam)
    # Each excess carries its location and distance in the report. A compact
    # check item per view/curve points the operator to that list.
    for view, curve in sorted({(p["view"], p["curve_id"]) for p in outside if p["view"] != "body_plan"}):
        rows = [p for p in outside if p["view"] == view and p["curve_id"] == curve]
        check_items.append(gap("fairing_view_conflict", f"{view} curve {curve}: {len(rows)} point(s) exceed "
                               "their source tolerance or lie outside the surface. Check the reported point distances "
                               "and the ink association; hard boundaries were kept.", severity="warning"))
    report = {"method": METHOD, "applied": True, "three_view_applied": True,
              "parameters": {"half_beam_m": surface.half_beam, "view_weights": {
                  "body_plan": 1., "half_breadth_plan": plan_weight, "profile": profile_weight},
                  "fairness": fairness, "huber_scale_m": surface.scale, "label_weights": fairing.LABEL_WEIGHTS,
                  "tensor_shape": list(surface.shape), "irls_iterations": iterations},
              "moves_by_label": fairing_shared.moves_by_label(stations, moves, surface.half_beam),
              "moves_by_view": summary, "point_excesses": outside,
              "coverage": evidence.get("coverage", {}), "hard_boundary_max_move_m": 0.,
              "negative_breadth_projections": projections, "added_half_stations": additions,
              "check_items": check_items, "engineering_approved": False}
    return result, report
