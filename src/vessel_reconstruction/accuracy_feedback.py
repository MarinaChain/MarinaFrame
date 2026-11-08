"""Advisory geometry hints only: no filtering, selection or build authority."""
from __future__ import annotations

import math
import re


def candidate_feedback(section: dict, candidate: dict, label: str = "") -> dict:
    calibration = section.get("calibration", {})
    ppm = calibration.get("pixels_per_metre", 1.)
    anchors = candidate.get("contour_selection", {}).get("anchors_px", [])
    points = candidate.get("authored", {}).get("points_yz_m", [])
    breadths = [p[0] / ppm for p in anchors] if anchors else [p[0] for p in points]
    declared = max(0., section.get("z_max_m", 0.) - section.get("z_min_m", 0.))
    span = candidate.get("z_range_m")
    if span:
        height = max(0., span[1] - span[0])
    elif anchors:
        height = (max(p[1] for p in anchors) - min(p[1] for p in anchors)) / ppm
    elif points:
        height = max(p[1] for p in points) - min(p[1] for p in points)
    else:
        height = 0.
    coverage = min(1., height / declared) if declared else 0.
    mean = sum(breadths) / len(breadths) if breadths else 0.
    deviation = math.sqrt(sum((v - mean) ** 2 for v in breadths) / len(breadths)) if breadths else None
    warnings = []
    if deviation is not None and deviation < .1:
        warnings.append("Nearly constant half-breadth: this may be a grid, centreline or buttock, not a hull curve.")
    if coverage < .9:
        warnings.append(f"Trace covers {coverage:.0%} of the declared calibrated height span; it may be a fragment. Continue toward keel and deck with trace_from_point, or complete it with propose_section.")
    if re.search(r"[A-Za-z].*\d.*[Ww]", label):
        warnings.append(f"Label {label[:64]} looks like a waterline/buttock/diagonal tag, not a station number. Check the station label; the assignment is kept.")
    return {"coverage_percent": round(100 * coverage, 1), "coverage_basis": "declared_calibrated_height_span_not_truth",
            "half_breadth_std_m": round(deviation, 4) if deviation is not None else None,
            "warnings": warnings, "suggested_next_tools": ["trace_from_point", "propose_section"] if warnings else []}


def candidate_catalog(section: dict, entry: dict) -> list[dict]:
    preferred = entry.get("grid_evidence", {}).get("unique_non_grid_candidate_id")
    candidates = entry.get("candidates", [])
    ordered = sorted(candidates, key=lambda c: (c.get("candidate_id") != preferred,
        not c.get("candidate_id", "").startswith("contour-"), c.get("candidate_id", "")))
    return [{"candidate_id": c["candidate_id"], "recommended": c["candidate_id"] == preferred,
             "recommendation": "Unambiguous contour candidate; prefer this over a grid or short fragment." if c["candidate_id"] == preferred else "",
             **candidate_feedback(section, c)} for c in ordered[:40]]
