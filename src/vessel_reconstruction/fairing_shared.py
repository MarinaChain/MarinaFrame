"""Shared station parsing and fairing review helpers."""
from __future__ import annotations

import numpy as np

from .schema import gap

METHOD = "robust_waterline_smoothing_splines_v3"
# Measured points carry more weight than repaired or inferred points.
LABEL_WEIGHTS = {"traced": 1.0, "read": 0.8, "repaired": 0.5, "interpolated": 0.3,
                 "ai_inferred": 0.2, "guessed": 0.2}
UNKNOWN_LABEL_WEIGHT = 0.2
# Measured points get a 1% half-beam tolerance; other points get 5%.
TOLERANCE_FRACTION = {"traced": 0.01, "read": 0.01}
OTHER_TOLERANCE_FRACTION = 0.05
# At least four stations are needed for the shared fit.
MINIMUM_SECTIONS = 4


def label_of(section: dict) -> str:
    return str(section.get("source_label") or "traced")


def label_weight(label: str) -> float:
    return LABEL_WEIGHTS.get(label, UNKNOWN_LABEL_WEIGHT)


def tolerance_fraction(label: str) -> float:
    return TOLERANCE_FRACTION.get(label, OTHER_TOLERANCE_FRACTION)


def parse_stations(sections: list[dict]) -> list[dict] | None:
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


def not_applied(sections: list[dict], reason: str) -> tuple[list[dict], dict]:
    item = gap("fairing_not_applied", f"Hull fairing was not applied: {reason} The hull goes through "
               "the sections as given.", severity="warning")
    return sections, {"method": METHOD, "applied": False, "reason": reason, "check_items": [item]}


def moves_by_label(stations: list[dict], moves: list[np.ndarray], half_beam: float) -> dict:
    summary = {}
    for label in sorted({s["label"] for s in stations}):
        distance = np.concatenate([m for s, m in zip(stations, moves) if s["label"] == label])
        tolerance = tolerance_fraction(label) * half_beam
        summary[label] = {"points": int(len(distance)), "max_m": float(np.max(distance)),
                          "p95_m": float(np.percentile(distance, 95)), "tolerance_m": tolerance,
                          "within_tolerance": float(np.mean(distance <= tolerance))}
    return summary


def check_items(stations: list[dict], moves: list[np.ndarray], half_beam: float) -> list[dict]:
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
