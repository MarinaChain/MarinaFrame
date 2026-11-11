"""Replayable three-view point sets, measured with the existing hull ink tools.

No truth or model calls. The stored hull predicts which ink to search. Even a
unique crossing does not prove a waterline's identity; that association is kept
in every plan point. Competing or shared ink has a lower source weight.
"""
from __future__ import annotations

from collections import Counter

import numpy as np

from . import draft_fit, view_measure as vm
from .fairing import label_of

METHOD = "stored_three_view_ink_v1"
# Four intervals per source gap provide evidence away from station columns.
SAMPLES_PER_GAP = 4
PROFILE_END_SAMPLES = 24
SHARED_INK_PX = 1.5


def prediction_table(sections: list[dict], heights: list[float]) -> vm.VesselTable:
    """Dense search predictions, interpolated at true height between source rows."""
    ordered = sorted(sections, key=lambda s: s["x_m"])
    source_x = np.array([s["x_m"] for s in ordered])
    curves = [np.asarray(s["points_yz_m"], dtype=float) for s in ordered]
    xs = np.unique(np.concatenate([np.linspace(a, b, SAMPLES_PER_GAP + 1)
                                   for a, b in zip(source_x[:-1], source_x[1:])]))
    rows = []
    for x in xs:
        i = min(int(np.searchsorted(source_x, x, side="right")) - 1, len(source_x) - 2)
        share = (x - source_x[i]) / (source_x[i + 1] - source_x[i])
        a, b = curves[i], curves[i + 1]
        low, high = (1 - share) * a[[0, -1], 1] + share * b[[0, -1], 1]
        z = np.unique(np.r_[np.linspace(low, high, 65), [h for h in heights if low <= h <= high]])
        y = (1 - share) * np.interp(z, a[:, 1], a[:, 0]) + share * np.interp(z, b[:, 1], b[:, 0])
        rows.append(np.column_stack([y, z]))
    table = vm.VesselTable.from_rows([f"sample-{i}" for i in range(len(xs))], xs, rows, heights)
    table.stern_xz_m, table.stem_xz_m = draft_fit.end_polylines(table)
    return table


def mark_shared_ink(points: list[dict], *, pixels_per_metre: float) -> None:
    """Do not give separate traced weights to curves assigned the same ink."""
    columns = {}
    for point in points:
        if point["view"] == "half_breadth_plan":
            columns.setdefault(point["x_m"], []).append(point)
    for column in columns.values():
        column.sort(key=lambda p: p["y_m"])
        for a, b in zip(column[:-1], column[1:]):
            if abs(a["y_m"] - b["y_m"]) * pixels_per_metre <= SHARED_INK_PX:
                for point in (a, b):
                    point.update(source_label="repaired", confidence=min(point["confidence"], .25), shared_ink=True)


def collect(sections: list[dict], grey: np.ndarray, views: dict) -> dict:
    """Point observations and coverage, independent of truth and future injections.

    Profile points have no y: a silhouette constrains the surface domain, not
    the breadth of an interior cell. Missing scans are counted, never filled.
    """
    points = []
    for section in sections:
        for index, (y, z) in enumerate(section["points_yz_m"]):
            points.append({"view": "body_plan", "target": "section", "curve_id": section["id"],
                           "station_id": section["id"], "point_index": index, "source_label": label_of(section),
                           "x_m": float(section["x_m"]), "y_m": float(y), "z_m": float(z),
                           "confidence": float(section.get("confidence", 1.)), "association": "stored_section"})
    heights = views.get("profile", {}).get("waterlines_z_m", [])
    table = prediction_table(sections, heights)
    source_x = {float(s["x_m"]) for s in sections}
    coverage = {}
    for kind in ("half_breadth_plan", "profile"):
        view = views.get(kind)
        stats = {"available": view is not None, "attempted": 0, "missing": 0, "points": 0,
                 "ambiguous": 0, "between_station_points": 0}
        coverage[kind] = stats
        if view is None:
            continue
        if kind == "half_breadth_plan" and not heights:
            # The deck is still measurable. No height label means no plan waterline.
            stats["waterline_labels_missing"] = True
        measured_table = table
        if kind == "profile":
            ends_z = np.linspace(min(table.keel_z_m), max(table.top_z_m), PROFILE_END_SAMPLES + 2)[1:-1]
            measured_table = vm.VesselTable.from_rows(table.station_ids, table.x_m, table.rows_yz_m, ends_z,
                                                     stem_xz_m=table.stem_xz_m, stern_xz_m=table.stern_xz_m)
        cells = vm.measure_views(measured_table, {kind: view}, grey)
        cal = view["calibration"]
        ppm = cal["pixels_per_metre"]
        for cell in cells:
            stats["attempted"] += 1
            if cell["status"] != "measured":
                stats["missing"] += 1
                continue
            x, z = cell["x_m"], cell["z_m"]
            target = cell["target"]
            y = None
            if kind == "half_breadth_plan":
                y = (cal["centerline_px"] - cell["measured_px"]) / ppm
                if z is None:
                    z = float(table.along_x(table.top_z_m, x))
                pixel = [cal["x_origin_px"] + x * ppm, cell["measured_px"]]
            elif target in ("keel", "top"):
                z = (cal["baseline_px"] - cell["measured_px"]) / ppm
                pixel = [cal["x_origin_px"] + x * ppm, cell["measured_px"]]
            else:
                x = (cell["measured_px"] - cal["x_origin_px"]) / ppm
                pixel = [cell["measured_px"], cal["baseline_px"] - z * ppm]
            ambiguous = cell["competing_runs"] > 0 or cell["beyond_search"] or cell["scans"] < 2
            points.append({"view": kind, "target": target,
                           "curve_id": cell.get("waterline_id") if target == "waterline" else target,
                           "source_label": "repaired" if ambiguous else "traced",
                           "x_m": float(x), "y_m": None if y is None else float(y), "z_m": float(z),
                           "confidence": float(cell["confidence"]) * (.25 if ambiguous else 1.),
                           "pixel_xy": pixel, "competing_runs": cell["competing_runs"],
                           "beyond_search": cell["beyond_search"], "scans": cell["scans"],
                           "association": "stored_hull_prediction"})
    if "half_breadth_plan" in views:
        mark_shared_ink(points, pixels_per_metre=views["half_breadth_plan"]["calibration"]["pixels_per_metre"])
    for kind, stats in coverage.items():
        rows = [p for p in points if p["view"] == kind]
        stats.update(points=len(rows), ambiguous=sum(p["source_label"] == "repaired" for p in rows),
                     between_station_points=sum(p["x_m"] not in source_x for p in rows),
                     by_target=dict(Counter(p["target"] for p in rows)))
    return {"method": METHOD, "points": points, "coverage": coverage, "views": views,
            "half_beam_m": float(max(y for s in sections if label_of(s) in ("read", "traced")
                                     for y, _ in s["points_yz_m"])) if any(label_of(s) in ("read", "traced") for s in sections)
            else float(max(y for s in sections for y, _ in s["points_yz_m"])),
            "engineering_approved": False}
