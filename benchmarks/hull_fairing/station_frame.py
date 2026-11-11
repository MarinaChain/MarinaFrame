"""Benchmark-only station alignment to independent profile evidence.

Arm B changes each station's vertical span within a fixed half-beam bound.
Arm C registers the complete station frame with one scale and two offsets.
Neither path reads truth or changes the runtime fitter's defaults.
"""
from __future__ import annotations

import numpy as np
from scipy.optimize import least_squares

from vessel_reconstruction import fairing_shared, fairing, three_view_fairing

# Search limits fixed before scoring. They permit a modest calibration error,
# without letting a fit collapse the hull or shift it to a different drawing.
SCALE_BOUNDS = (.8, 1.2)
X_OFFSET_LENGTH_FRACTION = .1
Z_OFFSET_HALF_BEAM_FRACTION = .1
BOUND_CANDIDATES = (.01, .025, .05)


def profile_curves(evidence):
    curves = {}
    for target in ("keel", "top"):
        rows = [p for p in evidence["points"] if p["view"] == "profile" and p["target"] == target]
        if len(rows) < 2:
            return None
        x = np.array([p["x_m"] for p in rows])
        z = np.array([p["z_m"] for p in rows])
        unique = np.unique(x)
        if len(unique) < 2:
            return None
        curves[target] = (unique, np.array([np.mean(z[x == value]) for value in unique]))
    return curves


def align_sections(sections, evidence, arm, bound_fraction=0.):
    """Return new sections and measured frame displacement; never alter inputs."""
    if arm == "current_joint":
        return sections, {"arm": arm, "applied": False, "max_endpoint_move_m": 0.}
    if arm not in ("bounded_endpoints", "registered_frame"):
        raise ValueError(f"Unknown station frame arm: {arm}")
    if not np.isfinite(bound_fraction) or bound_fraction < 0:
        raise ValueError("Endpoint bound must be finite and nonnegative")
    curves = profile_curves(evidence)
    if curves is None:
        return sections, {"arm": arm, "applied": False, "reason": "Missing keel/deck profile coverage"}
    source = fairing_shared.parse_stations(sections)
    if source is None:
        raise ValueError("Frame alignment needs valid single-region stations")
    half_beam = float(evidence["half_beam_m"])
    if not np.isfinite(half_beam) or half_beam <= 0:
        raise ValueError("Reference half-beam must be positive")
    report = {"arm": arm, "applied": True, "bound_fraction": bound_fraction,
              "bound_m": bound_fraction * half_beam, "uncovered_endpoints": 0}
    scale, dx, dz = 1., 0., 0.
    if arm == "registered_frame":
        length = source[-1]["x"] - source[0]["x"]
        xs = np.array([s["x"] for s in source])
        ends = np.array([[s["z"][0], s["z"][-1]] for s in source])

        def residual(parameters):
            factor, offset_x, offset_z = parameters
            mapped_x = factor * xs + offset_x
            values = []
            for index, target in enumerate(("keel", "top")):
                px, pz = curves[target]
                values.extend(factor * ends[:, index] + offset_z - np.interp(mapped_x, px, pz))
                # np.interp holds an end value outside coverage. Include the
                # actual distance outside the domain as a separate residual.
                values.extend(mapped_x - np.clip(mapped_x, px[0], px[-1]))
            return np.asarray(values)

        x_limit = X_OFFSET_LENGTH_FRACTION * length
        z_limit = Z_OFFSET_HALF_BEAM_FRACTION * half_beam
        before = residual((1., 0., 0.))
        fitted = least_squares(residual, (1., 0., 0.),
                               bounds=([SCALE_BOUNDS[0], -x_limit, -z_limit],
                                       [SCALE_BOUNDS[1], x_limit, z_limit]),
                               xtol=1e-12, ftol=1e-12, gtol=1e-12)
        if not fitted.success:
            raise ValueError(f"Station frame least squares failed: {fitted.message}")
        scale, dx, dz = map(float, fitted.x)
        report.update(scale=scale, x_offset_m=dx, z_offset_m=dz,
                      residual_rms_before_m=float(np.sqrt(np.mean(before ** 2))),
                      residual_rms_after_m=float(np.sqrt(np.mean(fitted.fun ** 2))),
                      jacobian_rank=int(np.linalg.matrix_rank(fitted.jac)),
                      active_bounds=fitted.active_mask.tolist(), solver_evaluations=fitted.nfev)
    result, displacements, endpoint_moves = [], [], []
    for station in source:
        original = station["points"]
        points = original.copy()
        mapped_x = scale * station["x"] + dx
        if arm == "bounded_endpoints":
            low, high = original[[0, -1], 1].copy()
            adjusted = [low, high]
            for index, target in enumerate(("keel", "top")):
                px, pz = curves[target]
                if px[0] <= station["x"] <= px[-1]:
                    target_z = np.interp(station["x"], px, pz)
                    adjusted[index] += np.clip(target_z - adjusted[index], -report["bound_m"], report["bound_m"])
                else:
                    report["uncovered_endpoints"] += 1
            if adjusted[1] <= adjusted[0]:
                raise ValueError("Bounded endpoints would reverse the station height span")
            share = (points[:, 1] - low) / (high - low)
            points[:, 1] = adjusted[0] + share * (adjusted[1] - adjusted[0])
        else:
            points[:, 0] *= scale
            points[:, 1] = scale * points[:, 1] + dz
        move = np.sqrt((mapped_x - station["x"]) ** 2 + np.sum((points - original) ** 2, axis=1))
        displacements.extend(move)
        endpoint_moves.extend(move[[0, -1]])
        result.append({**station["section"], "x_m": mapped_x, "points_yz_m": points.tolist()})
    report.update(max_point_move_m=float(max(displacements)), max_endpoint_move_m=float(max(endpoint_moves)))
    return result, report


def fit_sections(sections, evidence, arm, bound_fraction=0., *, plan_weight=.5, fairness=.02):
    """Keep the joint fit unchanged; include original-body movement in diagnostics."""
    adjusted, registration = align_sections(sections, evidence, arm, bound_fraction)
    result, report = three_view_fairing.fair_sections(adjusted, evidence, plan_weight=plan_weight, fairness=fairness)
    report["station_frame"] = registration
    if arm == "current_joint" or not registration["applied"]:
        return result, report
    output = {s["id"]: s for s in result}
    stations = fairing_shared.parse_stations(sections)
    moves, by_label = [], {}
    for original, changed in zip(stations, adjusted):
        points = np.asarray(changed["points_yz_m"])
        fitted = np.asarray(output[changed["id"]]["points_yz_m"])
        y = np.interp(points[:, 1], fitted[:, 1], fitted[:, 0])
        distance = np.sqrt((changed["x_m"] - original["x"]) ** 2
                           + (y - original["y"]) ** 2 + (points[:, 1] - original["z"]) ** 2)
        moves.append(distance)
        by_label.setdefault(original["label"], []).extend(distance)
        output[changed["id"]]["fairing"].update(input_points_yz_m=original["points"].tolist(),
                                                  max_move_m=float(max(distance)))
    half_beam = float(evidence["half_beam_m"])
    report["moves_by_label"] = fairing_shared.moves_by_label(stations, moves, half_beam)
    report["check_items"].extend(fairing_shared.check_items(stations, moves, half_beam))
    report["hard_boundary_max_move_m"] = registration["max_endpoint_move_m"]
    report["moves_by_view"]["body_plan"] = {}
    for label, values in by_label.items():
        tolerance = fairing.tolerance_fraction(label) * half_beam
        report["moves_by_view"]["body_plan"][label] = {
            "points": len(values), "unavailable": 0, "median_m": float(np.median(values)),
            "p95_m": float(np.percentile(values, 95)), "max_m": float(max(values)),
            "tolerance_m": tolerance, "within_tolerance": float(np.mean(np.asarray(values) <= tolerance))}
    # Keep original body-point excess locations as well as independent-view ones.
    report["point_excesses"] = [p for p in report["point_excesses"] if p["view"] != "body_plan"]
    for station, distances in zip(stations, moves):
        for (y, z), distance in zip(station["points"], distances):
            if distance > fairing.tolerance_fraction(station["label"]) * half_beam:
                report["point_excesses"].append({"view": "body_plan", "curve_id": station["section"]["id"],
                    "source_label": station["label"], "x_m": station["x"], "y_m": float(y), "z_m": float(z),
                    "move_m": float(distance)})
    return result, report


def require_fit_population(entries, protocol):
    """Validate metadata before opening geometry; check rows are never accepted."""
    expected = set(protocol["fit_cases"])
    if any(row["split"] != "fit" or row["case"] not in expected for row in entries):
        raise ValueError("Station frame experiment accepts protocol fit rows only")
    delivered = [row["case"] for row in entries if row["delivered"]]
    if set(delivered) != expected or len(delivered) != len(expected):
        raise ValueError("Fit population differs from frozen protocol")


def candidate_summary(scores):
    complete = bool(scores) and all(score is not None for score in scores)
    return {"planned": len(scores), "available": sum(score is not None for score in scores),
            "passes": sum(bool(score and score["passes"]) for score in scores),
            "mean_rms_pct": float(np.mean([s["rms_pct"] for s in scores])) if complete else None,
            "mean_abs_volume_pct": float(np.mean([abs(s["volume_pct"]) for s in scores])) if complete else None}


def select_candidate(candidates):
    def key(candidate):
        stats = candidate_summary(candidate["scores"])
        return (stats["available"] != stats["planned"], -stats["passes"],
                stats["mean_rms_pct"] if stats["mean_rms_pct"] is not None else float("inf"),
                stats["mean_abs_volume_pct"] if stats["mean_abs_volume_pct"] is not None else float("inf"))
    return min(candidates, key=key)
