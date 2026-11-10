"""Report-only hull-cell checks against independent views and section neighbours.

No truth, fit weights or acceptance gates are used. Plan scans find nearest ink,
not a labelled waterline: nearby curves can conceal errors. Missing/ambiguous
scans stay unavailable. Profile limits are one-sided; interior cells need not
lie on profile ink. See docs/HULL_FAIRING.md section 7 for the fixed protocol.
"""
from __future__ import annotations

import numpy as np

from . import view_measure as vm
from .schema import gap

METHOD = "cross_view_cells_v1"
# 20 mm rejects sub-centimetre drawing noise; 0.5 % is a quarter of the RMS gate.
MIN_TOLERANCE_M = 0.02
HALF_BEAM_FRACTION = 0.005
# Three pixels allow stroke thickness, scan offset and calibration noise.
PIXEL_TOLERANCE = 3.0
# A 5 %-height chord ignores dense trace jitter and spans the injected-cell scale.
NEIGHBOUR_HEIGHT_FRACTION = 0.05
# Real section curvature needs twice the independent-view allowance.
SECTION_TOLERANCE_FACTOR = 2.0
PROFILE_LIMITS = ("keel", "deck", "transom", "stem")


def _points(section):
    points = np.asarray(section.get("points_yz_m", []), dtype=float)
    if points.ndim != 2 or points.shape[1:] != (2,) or len(points) < 2 or not np.isfinite(points).all():
        raise ValueError("Each section needs at least two finite y,z points")
    return points


def _section_distance(points, index):
    """Distance to a bracketing chord; never extrapolate or cross non-monotone heights."""
    z = points[:, 1]
    if np.any(np.diff(z) <= 0):
        return None, "unsupported"
    height = NEIGHBOUR_HEIGHT_FRACTION * (z[-1] - z[0])
    left = np.flatnonzero(z <= z[index] - height)
    right = np.flatnonzero(z >= z[index] + height)
    if not len(left) or not len(right):
        return None, "missing"
    a, b = points[left[-1]], points[right[0]]
    chord = b - a
    t = np.clip(np.dot(points[index] - a, chord) / np.dot(chord, chord), 0, 1)
    return float(np.linalg.norm(points[index] - (a + t * chord))), "measured"


def detect_cells(sections: list[dict], *, evidence: dict | None = None, half_beam_m: float) -> dict:
    """Check measured source vertices, keyed by (section id, original point index).

    Evidence records contain optional plan scan, profile limits in metres and
    pixels_per_metre. Profile limits must come from the sheet, not these sections.
    Source geometry and evidence are never modified. Non-measured rows are skipped.
    """
    if not np.isfinite(half_beam_m) or half_beam_m <= 0:
        raise ValueError("half_beam_m must be finite and positive")
    cells, items = [], []
    evidence = evidence or {}
    for section in sections:
        if section.get("source_label", "traced") not in ("read", "traced"):
            continue
        points = _points(section)
        sid, x = section["id"], float(section["x_m"])
        if not np.isfinite(x):
            raise ValueError("Station x must be finite")
        for index, (y, z) in enumerate(points):
            record = evidence.get((sid, index), {})
            ppm = record.get("pixels_per_metre")
            if ppm is not None and (not np.isfinite(ppm) or ppm <= 0):
                raise ValueError("pixels_per_metre must be finite and positive")
            tolerance = max(MIN_TOLERANCE_M, HALF_BEAM_FRACTION * half_beam_m,
                            PIXEL_TOLERANCE / ppm if ppm else 0)
            distances = {"plan": None, **dict.fromkeys(PROFILE_LIMITS)}
            availability = {"plan": "missing", "profile": "missing"}
            plan = record.get("plan", {})
            if plan.get("status") == "measured" and np.isfinite(plan.get("residual_m", np.nan)):
                if plan.get("competing_runs", 0):
                    availability["plan"] = "ambiguous"
                else:
                    availability["plan"] = "measured"
                    distances["plan"] = abs(float(plan["residual_m"]))
            profile = record.get("profile", {})
            for limit, coordinate, sign in (("keel", z, -1), ("deck", z, 1),
                                             ("transom", x, -1), ("stem", x, 1)):
                value = profile.get(limit)
                if value is not None and np.isfinite(value):
                    distances[limit] = max(0.0, float(sign * (coordinate - value)))
                    availability["profile"] = "measured"
            distances["section"], availability["section"] = _section_distance(points, index)
            reasons = [name for name, distance in distances.items() if distance is not None
                       and distance > tolerance * (SECTION_TOLERANCE_FACTOR if name == "section" else 1)]
            cell = {"station_id": sid, "point_index": index, "x_m": x, "y_m": float(y), "z_m": float(z),
                    "distances_m": distances, "tolerance_m": tolerance, "availability": availability,
                    "flagged": bool(reasons), "reasons": reasons}
            cells.append(cell)
            if reasons:
                detail = ", ".join(f"{name}={distance:.4f} m" for name, distance in distances.items()
                                   if distance is not None)
                item = gap("cross_view_cell_outlier", f"Cell {index} at z={z:.4f} m: {detail}; "
                           f"tolerance={tolerance:.4f} m (section x{SECTION_TOLERANCE_FACTOR:g}). "
                           "Check the source views; no geometry was changed.", sid, severity="warning")
                item.update(point_index=index, distances_m=distances.copy(), tolerance_m=tolerance)
                items.append(item)
    coverage = {name: sum(c["availability"][name] == "measured" for c in cells)
                for name in ("plan", "profile", "section")}
    coverage["independent_cells"] = sum(any(c["availability"][name] == "measured"
                                           for name in ("plan", "profile")) for c in cells)
    return {"method": METHOD, "cells": cells, "coverage": coverage, "check_items": items,
            "engineering_approved": False, "geometry_changed": False}


def _profile_limits(sheet, view, x, z):
    """Outer ink crossings beside the grid give profile bounds, not section-derived predictions."""
    cal, roi = view["calibration"], view["roi_px"]
    ppm, origin, base = cal["pixels_per_metre"], cal["x_origin_px"], cal["baseline_px"]
    limits = {}
    for axis, line, low_name, high_name in (("col", origin + x * ppm, "deck", "keel"),
                                           ("row", base - z * ppm, "transom", "stem")):
        bounds = []
        for offset in (-vm.SCAN_OFFSET_PX, vm.SCAN_OFFSET_PX):
            low, high = (roi[1], roi[3]) if axis == "col" else (roi[0], roi[2])
            runs = vm.ink_runs(sheet, roi, axis, line + offset, low, high)
            if len(runs) >= 2:
                bounds.append((runs[0][2], runs[-1][2]))
        if len(bounds) != 2:
            continue
        low, high = np.mean(bounds, axis=0)
        if axis == "col":
            limits.update({low_name: float((base - low) / ppm), high_name: float((base - high) / ppm)})
        else:
            limits.update({low_name: float((low - origin) / ppm), high_name: float((high - origin) / ppm)})
    return limits


def measure_evidence(sections: list[dict], grey: np.ndarray, views: dict, *, half_beam_m: float) -> dict:
    """Raster adapter using existing ink scans; accepts calibrated views, never truth geometry.

    Scans are made at each source vertex (no interpolation across waterline labels).
    The nearest plan curve can be another waterline; this limitation is reported
    in the protocol and is why this check does not automatically alter a fit.
    """
    sheet = vm.Sheet(grey)
    context = vm.ScanContext(sheet, half_beam_m)
    evidence = {}
    for section in sections:
        if section.get("source_label", "traced") not in ("read", "traced"):
            continue
        x = float(section["x_m"])
        for index, (y, z) in enumerate(_points(section)):
            record, scales = {}, []
            plan = views.get("half_breadth_plan")
            if plan is not None:
                cal, roi = plan["calibration"], plan["roi_px"]
                ppm, origin, centre = cal["pixels_per_metre"], cal["x_origin_px"], cal["centerline_px"]
                scales.append(ppm)
                scans = [vm.measure_point(context, roi, "col", origin + x * ppm + offset,
                                          centre - y * ppm, ppm,
                                          high_limit_px=centre - vm.CENTRELINE_CLEARANCE_PX)
                         for offset in (-vm.SCAN_OFFSET_PX, vm.SCAN_OFFSET_PX)]
                record["plan"] = vm.combine_scans(scans, -1, ppm)
            profile = views.get("profile")
            if profile is not None:
                scales.append(profile["calibration"]["pixels_per_metre"])
                record["profile"] = _profile_limits(sheet, profile, x, z)
            if scales:
                record["pixels_per_metre"] = min(scales)
            evidence[(section["id"], index)] = record
    return evidence
