"""Conservative plan-view ink evidence for an existing body-plan corridor.

Waterline regions and their height identities must be declared from the same
source drawing. This module neither identifies labels nor supplies hull points.
The normal raster reader still measures ink inside any returned corridor.
"""
from __future__ import annotations

import math

import numpy as np

from .investigation import INK_CONTRAST


def _number(value, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{name} must be a finite number")
    return float(value)


def _region(value, width: int, height: int) -> tuple[int, int, int, int]:
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        raise ValueError("region_px requires four integer bounds")
    values = [_number(v, "region_px") for v in value]
    if any(v != int(v) for v in values):
        raise ValueError("region_px requires integer bounds")
    left, top, right, bottom = map(int, values)
    if not 0 <= left < right <= width or not 0 <= top < bottom <= height:
        raise ValueError("region_px is outside the image")
    return left, top, right, bottom


def derive_contour_selection(image: np.ndarray, section: dict, setup: dict,
                             waterlines: list[dict], *, half_width_px: float) -> dict:
    """Return selection input plus every accepted/refused anchor, never geometry.

    ``setup`` declares plan calibration and a region. Each waterline declares
    ``z_m``, ``region_px`` and nonempty identity ``evidence``. Regions can be
    station-local, but cannot be inferred from a body candidate or reference
    offsets. A three-column strip uses the same contrast as compare_views.
    More than one ink run, a clipped run, or missing ink supplies no anchor.
    """
    if image.ndim != 3 or image.shape[2] != 3 or not np.isfinite(image).all():
        raise ValueError("image must contain finite RGB pixels")
    height, width = image.shape[:2]
    left, top, right, bottom = _region(setup["region_px"], width, height)
    ppm = _number(setup["pixels_per_metre"], "pixels_per_metre")
    centre = _number(setup["centreline_px"], "centreline_px")
    origin = _number(setup["x_origin_px"], "x_origin_px")
    direction = _number(setup["x_direction"], "x_direction")
    breadth_direction = _number(setup["breadth_direction"], "breadth_direction")
    if ppm <= 0 or direction not in (-1, 1) or breadth_direction not in (-1, 1):
        raise ValueError("plan scale must be positive and directions must be -1 or 1")
    if not isinstance(setup.get("evidence"), str) or not setup["evidence"].strip():
        raise ValueError("plan setup needs drawing evidence")
    if not isinstance(waterlines, list) or not 1 <= len(waterlines) <= 64:
        raise ValueError("declare 1..64 waterlines")
    half_width = _number(half_width_px, "half_width_px")
    body_left, body_top, body_right, body_bottom = section["roi_px"]
    if not 0 < half_width <= min(128, body_right - body_left):
        raise ValueError("half_width_px is outside the existing corridor bound")
    calibration = section["calibration"]
    body_ppm = _number(calibration["pixels_per_metre"], "body pixels_per_metre")
    baseline = _number(calibration["baseline_px"], "baseline_px")
    body_centre = _number(calibration["centerline_px"], "centerline_px")
    if body_ppm <= 0:
        raise ValueError("body scale must be positive")
    column = origin + direction * _number(section["x_m"], "x_m") * ppm
    pixel_column = round(column)
    paper = float(np.percentile(image[top:bottom, left:right].mean(axis=2), 98))
    records, anchors = [], []
    for waterline in waterlines:
        z = _number(waterline["z_m"], "z_m")
        wl_left, wl_top, wl_right, wl_bottom = _region(waterline["region_px"], width, height)
        if not (left <= wl_left < wl_right <= right and top <= wl_top < wl_bottom <= bottom):
            raise ValueError("waterline region must lie within the plan region")
        record = {"z_m": z, "region_px": list(waterline["region_px"]),
                  "evidence": waterline.get("evidence", ""), "status": "refused",
                  "engineering_approved": False}
        records.append(record)
        if not isinstance(record["evidence"], str) or not record["evidence"].strip():
            record["reason"] = "missing_waterline_identity_evidence"
            continue
        # Never truncate the strip: an edge can hide a competing crossing.
        if not (wl_left <= column < wl_right and wl_left <= pixel_column - 1
                and pixel_column + 1 < wl_right):
            record["reason"] = "station_outside_waterline_region"
            continue
        dark = image[wl_top:wl_bottom, pixel_column - 1:pixel_column + 2].mean(axis=2) < paper - INK_CONTRAST
        column_runs = []
        for index in range(3):
            edges = np.flatnonzero(np.diff(np.r_[False, dark[:, index], False].astype(np.int8)))
            column_runs.append(list(zip(edges[::2], edges[1::2])))
        counts = [len(runs) for runs in column_runs]
        record["crossing_counts_by_column"] = counts
        record["crossing_count"] = counts[1]
        # A union of adjacent columns can merge two diagonal strokes. Require
        # uniqueness in every column, then measure the actual station column.
        if any(count > 1 for count in counts):
            record["reason"] = "ambiguous_crossing"
            continue
        if any(count == 0 for count in counts):
            record["reason"] = "no_crossing"
            continue
        if any(runs[0][0] == 0 or runs[0][1] == len(dark) for runs in column_runs):
            record["reason"] = "crossing_touches_region_boundary"
            continue
        first, stop = column_runs[1][0]
        plan_row = wl_top + (int(first) + int(stop) - 1) / 2
        half_breadth = breadth_direction * (plan_row - centre) / ppm
        point = [body_centre + half_breadth * body_ppm, baseline - z * body_ppm]
        if half_breadth < 0 or not (body_left <= point[0] < body_right and body_top <= point[1] < body_bottom):
            record["reason"] = "anchor_outside_body_panel"
            continue
        record.update(status="accepted", plan_row_px=plan_row, anchor_px=point)
        anchors.append(point)
    anchors.sort(key=lambda point: point[1])
    selection = None
    if len(anchors) < 2:
        reason = "insufficient_anchors"
    elif any(a[1] == b[1] for a, b in zip(anchors, anchors[1:])):
        reason = "duplicate_anchor_elevation"
    elif (anchors[0][1] > max(body_top, round(baseline - section["z_max_m"] * body_ppm))
          or anchors[-1][1] < min(body_bottom - 1, round(baseline - section["z_min_m"] * body_ppm))):
        reason = "anchors_do_not_span_calibrated_range"
    elif section.get("contour_selection") is not None:
        reason = "existing_contour_selection_preserved"
    else:
        reason = "declared_corridor"
        selection = {"anchors_px": anchors, "half_width_px": half_width}
    return {"method": "plan_waterline_corridor_v1", "section_id": section["id"],
            "plan_column_px": column, "setup": setup, "anchors": records,
            "contour_selection": selection, "reason": reason,
            "engineering_approved": False, "identity_certified": False,
            "interpretation": "Declared selection evidence from another view of the same drawing, never truth; geometry must still be read from body-plan ink."}
