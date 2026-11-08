"""Declared sections for a sheet-only draft, made from the phase-1 reading.

A sheet-only intake spec (see intake.py) has no stations or calibration. In live
draft mode the model reads the sheet first (describe_views, propose_sheet_setup,
describe_vessel). This module turns that reading into declared sections (id,
x_m, roi_px, calibration, z range) so that the first hull and the normal loop run
as for a spec written by a person.

Every value comes from one of three places, and the section evidence says which:
- the model's reading (station positions, scale claims): ``ai_inferred``;
- code measurement (grid lines and ink extents on the sheet, the intake's view
  regions);
- a fallback with a warning when neither gives a value.
The model's view regions are checked against the intake's code regions: a body
region that is long and low, or that misses every intake body region (for
example normalized 0-1000 coordinates), is replaced by the intake regions.
Nothing here refuses: missing data becomes a fallback with a warning.
"""
from __future__ import annotations

import math
import re

import numpy as np
from scipy import ndimage

from . import investigation as inv
from .schema import validate_spec

# Stations made when the reading names fewer than three and no body panels exist.
FALLBACK_STATION_COUNT = 11
# Station spacing (metres) when no length or beam is read. Arbitrary; it only
# fixes the hull length, and a warning says so.
FALLBACK_STATION_SPACING_M = 10.0
# Typical length/beam ratio of a ship hull, used to guess a length from the beam.
LENGTH_BEAM_RATIO = 7.0
# Without any read dimension, a body panel is taken to show this depth (metres).
FALLBACK_PANEL_DEPTH_M = 10.0
# A model scale below this (pixels per metre) is the tool default, not a reading.
MIN_READ_PPM = 2.0
# A half body plan ROI reaches this fraction of the region width past the
# centreline, so a curve that touches the centreline stays inside its ROI.
CENTRELINE_OVERLAP = 0.1
# A body region at least this many times wider than tall is a long view, not a body plan.
LONG_VIEW_ASPECT = 2.2
# The model's body regions must overlap an intake body region at least this much (IoU).
MIN_REGION_AGREEMENT = 0.3
# Ink components shorter than this share of the region are labels or specks.
HULL_INK_SHARE = 0.05
# A model datum farther than this from the measured grid datum is replaced by it
# (the same distance measure_setup uses to snap a datum to a grid line).
DATUM_SNAP_PX = 8
BODY_KINDS = ("body", "body_fore", "body_aft")
SAFE_ID = re.compile(r"[^A-Za-z0-9_.-]")


def _finite(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _principal(description: dict, name: str) -> float | None:
    record = (description.get("principal") or {}).get(name)
    value = record.get("value") if isinstance(record, dict) else record
    return float(value) if _finite(value) and value > 0 else None


def _iou(a, b) -> float:
    left, top = max(a[0], b[0]), max(a[1], b[1])
    right, bottom = min(a[2], b[2]), min(a[3], b[3])
    inter = max(0, right - left) * max(0, bottom - top)
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


def _clip(region, width, height) -> list[int]:
    left, top, right, bottom = [int(round(v)) for v in region]
    left, top = max(0, min(left, width - 1)), max(0, min(top, height - 1))
    return [left, top, max(left + 1, min(right, width)), max(top + 1, min(bottom, height))]


# ------------------------------------------------------------------ measurement
def _gray(image, region):
    left, top, right, bottom = region
    crop = image[top:bottom, left:right]
    return crop.mean(axis=2) if crop.ndim == 3 else crop.astype(float)


def hull_ink_box(image, region) -> list[float] | None:
    """Box of the long ink strokes in ``region`` (labels and specks left out)."""
    gray = _gray(image, region)
    mask = gray < min(float(np.percentile(gray, 98)) - inv.INK_CONTRAST, 110.0)
    labels, _ = ndimage.label(mask, structure=np.ones((3, 3)))
    longest = HULL_INK_SHARE * max(gray.shape)
    boxes = [box for box in ndimage.find_objects(labels) if box is not None
             and max(box[0].stop - box[0].start, box[1].stop - box[1].start) >= longest]
    if not boxes:
        return None
    left, top = region[0], region[1]
    return [left + min(b[1].start for b in boxes), top + min(b[0].start for b in boxes),
            left + max(b[1].stop for b in boxes), top + max(b[0].stop for b in boxes)]


def grid_datums(image, region) -> dict:
    """Centreline, baseline and grid spacing measured from the drawn grid lines.

    Lines are read at local contrast too (inv.drawn_lines), so the light grid
    of a blurred scan and a dash-dot centreline count as drawn lines; a dark
    baseline that hull ink thickens is still found by inv.long_lines.
    """
    gray = _gray(image, region)
    rows = [region[1] + v for v in inv.datum_lines(gray, 0)]
    columns = [region[0] + v for v in inv.datum_lines(gray, 1)]
    ink = hull_ink_box(image, region)
    centre = None
    if columns and ink:
        middle = [c for c in columns if ink[0] + 0.35 * (ink[2] - ink[0]) <= c <= ink[0] + 0.65 * (ink[2] - ink[0])]
        # An overlaid body plan has its centreline inside the ink; separate half
        # sections start at it.
        centre = min(middle, key=lambda c: abs(c - (ink[0] + ink[2]) / 2)) if middle else \
            min(columns, key=lambda c: abs(c - ink[0]))
    return {"centreline_px": centre, "baseline_px": max(rows) if rows else None, "ink_box": ink,
            "grid_spacing_px": inv.grid_spacing(rows) or inv.grid_spacing(columns)}


# ------------------------------------------------------------------ stations
def _station_id(raw, index: int, used: set) -> str:
    text = SAFE_ID.sub("", str(raw or ""))[:48] or f"s{index + 1:02d}"
    candidate, suffix = text, 2
    while candidate in used:
        candidate, suffix = f"{text}-{suffix}", suffix + 1
    used.add(candidate)
    return candidate


def read_stations(description: dict, panel_count: int, warnings: list) -> list[dict]:
    """Stations in increasing x, with unique ids and positions.

    Read stations without positions keep their order and are spaced evenly; with
    fewer than three, one station per body panel (or a fixed count) is made.
    The spacing is the read length (LOA, else LPP) over the stations, else a
    length guessed from the beam, else FALLBACK_STATION_SPACING_M.
    """
    rows = [s for s in description.get("stations", []) if isinstance(s, dict)]
    placed = sorted((s for s in rows if _finite(s.get("x_m"))), key=lambda s: float(s["x_m"]))
    stations, used, last = [], set(), None
    for index, row in enumerate(placed):
        x = float(row["x_m"])
        if last is not None and x - last < 1e-6:
            warnings.append(f"Station {row.get('id')} repeats x = {x:g} m; it is left out.")
            continue
        stations.append({"id": _station_id(row.get("id") or row.get("label"), index, used), "x_m": x,
                         "side": str(row.get("side", "")).lower()})
        last = x
    if len(stations) >= 3:
        return stations
    names = [s.get("id") or s.get("label") for s in rows] if len(rows) >= 3 else []
    count = len(names) or (panel_count if panel_count >= 3 else FALLBACK_STATION_COUNT)
    length, beam = _principal(description, "loa") or _principal(description, "lpp"), _principal(description, "beam")
    if length:
        spacing, basis = length / (count + 1), f"the read length {length:g} m"
    elif beam:
        spacing, basis = LENGTH_BEAM_RATIO * beam / (count + 1), f"a length of {LENGTH_BEAM_RATIO:g} x the read beam"
    else:
        spacing, basis = FALLBACK_STATION_SPACING_M, f"{FALLBACK_STATION_SPACING_M:g} m apart (no length was read)"
    warnings.append(f"Station positions were not read; {count} stations are spaced evenly over {basis}. "
                    "Station positions are a guess.")
    used = set()
    return [{"id": _station_id(names[i] if names else None, i, used), "x_m": round((i + 1) * spacing, 6),
             "side": ""} for i in range(count)]


# ------------------------------------------------------------------ views and scale
def _read_body_setups(state: dict) -> list[dict]:
    return [dict(s) for s in (state.get("sheet_setups") or {}).values()
            if s.get("view") == "body" and _finite(s.get("region_px", [None])[0])]


def _agrees(regions: list, hints: list) -> bool:
    """Whether the model's body regions are body views on this sheet."""
    if not regions:
        return False
    if any((r[2] - r[0]) >= LONG_VIEW_ASPECT * (r[3] - r[1]) for r in regions):
        return False
    if not hints:
        return True
    scores = [max(_iou(r, h) for h in hints) for r in regions]
    return sum(scores) / len(scores) >= MIN_REGION_AGREEMENT


def _long_view_region(described, hints) -> list | None:
    for view in described:
        r = view.get("region_px")
        if view.get("kind") in ("profile", "plan") and r and (r[2] - r[0]) >= LONG_VIEW_ASPECT * (r[3] - r[1]):
            return r
    for hint in hints:
        r = hint.get("region_px")
        if hint.get("label") in ("profile", "half_breadth") and r:
            return r
    return None


def read_scale(image, setups, described, hints, description, body_region, warnings) -> tuple[float, str]:
    """Pixels per metre: the model's body scale, else code measurement with a read dimension."""
    read = [float(s["pixels_per_metre"]) for s in setups
            if _finite(s.get("pixels_per_metre")) and s["pixels_per_metre"] >= MIN_READ_PPM]
    from .vessel_description import _different, printed_scale
    printed = printed_scale(description or {})
    if printed and read and _different(float(np.median(read)), printed):
        # The scale printed on the sheet outranks a scale read off the grid.
        warnings.append(f"The body-plan setup uses {float(np.median(read)):g} px/m but the sheet prints "
                        f"SCALE 1 m = {printed:g} px; the printed scale is used.")
        return printed, "the scale printed on the sheet (the model's setup disagreed)"
    if read:
        return float(np.median(read)), "the model's body-plan scale (setup)"
    spacing_m = [float(s["grid_spacing_m"]) for s in setups if _finite(s.get("grid_spacing_m"))
                 and s["grid_spacing_m"] > 0 and s["grid_spacing_m"] != 1.0]
    grid = grid_datums(image, body_region)
    if spacing_m and grid["grid_spacing_px"]:
        return grid["grid_spacing_px"] / spacing_m[0], f"the measured grid spacing and a {spacing_m[0]:g} m grid"
    loa = _principal(description, "loa")
    long_view = _long_view_region(described, hints)
    if loa and long_view:
        ink = hull_ink_box(image, _clip(long_view, image.shape[1], image.shape[0]))
        if ink:
            warnings.append("The body-plan scale was not read; it is the long view's ink length over the read LOA "
                            "(same scale assumed for all views).")
            return (ink[2] - ink[0]) / loa, f"long-view ink length / LOA {loa:g} m"
    beam, depth = _principal(description, "beam"), _principal(description, "depth")
    ink = grid["ink_box"] or body_region
    if beam:
        scale, basis = (ink[2] - ink[0]) / beam, f"body ink width / beam {beam:g} m"
    elif depth:
        scale, basis = (body_region[3] - ink[1]) / depth, f"body ink height / depth {depth:g} m"
    else:
        scale, basis = (body_region[3] - body_region[1]) / FALLBACK_PANEL_DEPTH_M, \
            f"panel height taken as {FALLBACK_PANEL_DEPTH_M:g} m"
    warnings.append(f"No body-plan scale was read; calibration comes from the panel extents ({basis}). "
                    "The scale is a guess.")
    return scale, basis


def body_panels(image, state, hints, warnings) -> list[dict]:
    """Body panels with datums: the model's setups, or the intake's body regions."""
    height, width = image.shape[:2]
    described = state.get("described_views") or []
    kinds = {v.get("view_id"): v.get("kind") for v in described}
    setups = _read_body_setups(state)
    hint_regions = [h["region_px"] for h in hints if h.get("label") == "body_plan" and h.get("region_px")]
    model_regions = [s["region_px"] for s in setups] or [
        v["region_px"] for v in described if v.get("kind") in BODY_KINDS and v.get("region_px")]
    if _agrees(model_regions, hint_regions):
        panels = setups or [{"region_px": r, "view_id": None} for r in model_regions]
        source = "the model's body views"
    elif hint_regions:
        warnings.append("The model's body-plan regions do not match the sheet's body-plan ink; the intake's "
                        "code regions are used.")
        panels, source = [{"region_px": r, "view_id": None} for r in hint_regions], "the intake's body regions"
    elif model_regions:
        panels, source = setups or [{"region_px": r, "view_id": None} for r in model_regions], "the model's views"
    else:
        warnings.append("No body view was named; the whole sheet is taken as the body plan.")
        panels, source = [{"region_px": [0, 0, width, height], "view_id": None}], "the whole sheet"
    result = []
    for panel in panels:
        region = _clip(panel["region_px"], width, height)
        grid = grid_datums(image, region)
        datums = {}
        for field in ("centreline_px", "baseline_px"):
            model = panel.get(field) if panel.get("setup_id") else None
            measured = grid[field]
            low, high = (region[0], region[2]) if field == "centreline_px" else (region[1], region[3])
            # A model datum is kept when it lies in the panel and no drawn grid
            # line contradicts it (measure_setup already snapped near lines).
            on_grid = measured is None or abs(model - measured) <= DATUM_SNAP_PX if _finite(model) else False
            if _finite(model) and low - 1 <= model <= high + 1 and on_grid:
                datums[field], how = float(model), "model (snapped to grid)"
            elif measured is not None:
                datums[field], how = float(measured), "grid line"
            else:
                datums[field] = (region[0] + region[2]) / 2 if field == "centreline_px" else region[3] - 1.0
                how = "region extent"
                warnings.append(f"No {field.replace('_px', '')} was read or found for a body panel; the region "
                                f"{'centre' if field == 'centreline_px' else 'bottom'} is used.")
            datums[field + "_source"] = how
        result.append({"region_px": region, "view_id": panel.get("view_id"), "setup_id": panel.get("setup_id"),
                       "kind": kinds.get(panel.get("view_id"), "body"), "source": source,
                       "pixels_per_metre": panel.get("pixels_per_metre"),
                       "grid_spacing_m": panel.get("grid_spacing_m"), **datums})
    return result


# ------------------------------------------------------------------ assignment
def _reading_order(panels: list[dict]) -> list[dict]:
    """Panels top row first, left to right (the usual order of separate panels)."""
    heights = sorted(p["region_px"][3] - p["region_px"][1] for p in panels)
    row = max(1.0, heights[len(heights) // 2] / 2)
    return sorted(panels, key=lambda p: (round(p["region_px"][1] / row), p["region_px"][0]))


def _half_roi(panel: dict, fore: bool) -> list[int]:
    """The fore (right) or aft (left) half of an overlaid body plan."""
    left, top, right, bottom = panel["region_px"]
    centre = float(panel["centreline_px"])
    overlap = CENTRELINE_OVERLAP * (right - left)
    if fore:
        return [int(max(left, centre - overlap)), top, right, bottom]
    return [left, top, int(min(right, centre + overlap)), bottom]


def assign(stations: list[dict], panels: list[dict], warnings: list) -> list[tuple]:
    """Pair each station with a panel and an ROI."""
    if len(panels) == len(stations):
        return [(s, p, list(p["region_px"]), "one panel per station in reading order")
                for s, p in zip(stations, _reading_order(panels))]
    fore_panels = [p for p in panels if p["kind"] == "body_fore"]
    aft_panels = [p for p in panels if p["kind"] == "body_aft"]
    xs = [s["x_m"] for s in stations]
    middle = (min(xs) + max(xs)) / 2
    sides = {s["side"] for s in stations}
    # Sides are used only when the reading names both halves and every aft
    # station lies aft of every fore one (x from aft). A reading that numbers
    # stations from the bow but has x from the stern (shipd-1-00679 live) is not.
    aft_x = [s["x_m"] for s in stations if s["side"] == "aft"]
    fore_x = [s["x_m"] for s in stations if s["side"] == "fore"]
    trust_sides = {"fore", "aft"} <= sides and max(aft_x) < min(fore_x)
    if {"fore", "aft"} <= sides and not trust_sides:
        warnings.append("The stations' fore/aft sides contradict their x positions; each station's half of the "
                        "body plan follows its x (aft of the middle station: left half).")
    if len(panels) == 1 or (fore_panels and aft_panels):
        pairs = []
        for station in stations:
            read_side = trust_sides and station["side"] in ("fore", "aft")
            fore = station["side"] == "fore" if read_side else station["x_m"] >= middle
            if fore_panels and aft_panels:
                panel = fore_panels[0] if fore else aft_panels[0]
                roi, basis = list(panel["region_px"]), "fore/aft body view"
            else:
                panel = panels[0]
                roi = _half_roi(panel, fore)
                basis = "fore half (right of centreline)" if fore else "aft half (left of centreline)"
            pairs.append((station, panel, roi, basis))
        return pairs
    warnings.append(f"{len(panels)} body panels for {len(stations)} stations; stations are spread over the "
                    "panels in reading order.")
    ordered = _reading_order(panels)
    return [(s, ordered[min(len(ordered) - 1, i * len(ordered) // len(stations))],
             list(ordered[min(len(ordered) - 1, i * len(ordered) // len(stations))]["region_px"]),
             "panel spread in reading order") for i, s in enumerate(stations)]


def materialize_sections(image, spec: dict, state: dict, hints: list[dict] | None = None) -> dict:
    """Return ``{"sections", "warnings", "report"}`` for a sheet-only spec.

    ``image`` is the source page. ``state`` is the domain state after phase 1
    (described_views, sheet_setups, vessel_description). ``hints`` are the
    intake's proposed regions of the source page. Fallbacks carry warnings.
    """
    hints = hints or []
    warnings: list[str] = []
    description = state.get("vessel_description") or {}
    described = state.get("described_views") or []
    panels = body_panels(image, state, hints, warnings)
    stations = read_stations(description, len(panels), warnings)
    union = [min(p["region_px"][0] for p in panels), min(p["region_px"][1] for p in panels),
             max(p["region_px"][2] for p in panels), max(p["region_px"][3] for p in panels)]
    # A scale read on regions that are not this sheet's body plan (wrong view or
    # wrong coordinates) is not a reading of these panels.
    trusted = _read_body_setups(state) if "model" in panels[0]["source"] else []
    scale, scale_basis = read_scale(image, trusted, described, hints, description, panels[0]["region_px"], warnings)
    depth = _principal(description, "depth")
    sections = []
    for station, panel, roi, basis in assign(stations, panels, warnings):
        cal = {"pixels_per_metre": float(scale), "centerline_px": float(panel["centreline_px"]),
               "baseline_px": float(panel["baseline_px"])}
        roi = _clip(roi, image.shape[1], image.shape[0])
        drawn_top = (cal["baseline_px"] - roi[1]) / cal["pixels_per_metre"]
        z_max = depth if depth else max(drawn_top, 0.1)
        sections.append({
            "id": station["id"], "x_m": station["x_m"], "roi_px": roi, "calibration": cal,
            "z_min_m": 0.0, "z_max_m": round(float(z_max), 6),
            "evidence": (f"ai_inferred: set from the phase-1 reading of a sheet-only intake. Station x from "
                         f"describe_vessel; scale from {scale_basis}; centreline from "
                         f"{panel['centreline_px_source']}, baseline from {panel['baseline_px_source']}; "
                         f"panel from {panel['source']}; ROI: {basis}. Not verified; a person must confirm it."),
        })
    report = {"section_count": len(sections), "panel_count": len(panels), "panel_source": panels[0]["source"],
              "scale_basis": scale_basis, "pixels_per_metre": round(float(scale), 6),
              "body_union_px": union, "source_label": "ai_inferred", "warnings": warnings}
    return {"sections": sections, "warnings": warnings, "report": report}


def materialized_spec(spec: dict, sections: list[dict], base_dir) -> tuple[dict, list[dict]]:
    """The captured spec with sections, and its validation gaps (normally none)."""
    result = dict(spec)
    result["sections"] = sections
    return result, validate_spec(result, base_dir)
