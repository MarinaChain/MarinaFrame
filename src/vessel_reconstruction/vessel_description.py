"""Read a lines sheet before fitting geometry; all consistency checks are advisory.

View identity and text are model claims. Grid positions and ink extents are pixel
measurements. Keep both, and never call a fitted hull or evaluator truth here.
"""
from __future__ import annotations

import copy
import math
import re

import numpy as np
from scipy import ndimage

from . import investigation as inv

MAX_REGIONS = 32
MAX_STROKES = 6
DIMENSION_TOLERANCE = .02
GEOMETRY_KINDS = {"body", "body_fore", "body_aft", "plan", "profile"}
VIEW_KINDS = GEOMETRY_KINDS | {"title_block", "offsets_table", "other"}


def valid_description(description):
    """Check transport shape only; wrong physical values remain advisory."""
    if not isinstance(description, dict):
        return False
    for key in ("principal", "ends", "deck", "form"):
        if key in description and not isinstance(description[key], dict):
            return False
    for key, coordinate in (("stations", "x_m"), ("waterlines", "z_m"), ("buttocks", "y_m")):
        if key not in description:
            continue
        rows = description[key]
        if not isinstance(rows, list) or len(rows) > 300:
            return False
        for row in rows:
            if not isinstance(row, dict) or not isinstance(row.get("id"), str):
                return False
            value = row.get(coordinate)
            if type(value) not in (int, float) or not math.isfinite(value):
                return False
            if "label" in row and not isinstance(row["label"], str):
                return False
    for record in description.get("principal", {}).values():
        value = _value(record)
        if type(value) not in (int, float) or not math.isfinite(value):
            return False
        if isinstance(record, dict) and record.get("source") not in (None, "spec", "title_block", "measured", "ai_inferred"):
            return False
    ends = description.get("ends", {})
    return all(key not in ends or isinstance(ends[key], dict) for key in ("stem", "stern", "bulb"))


def warning(field, claimed, measured, fix):
    return {"field": field, "claimed_value": claimed, "measured_value": measured,
            "suggested_fix": fix}


def _gray(image):
    array = np.asarray(image)
    return array.mean(axis=2) if array.ndim == 3 else array.astype(float)


def _region(region, shape):
    width, height = shape[1], shape[0]
    left, top, right, bottom = [int(v) for v in region]
    left, top = max(0, min(left, width - 1)), max(0, min(top, height - 1))
    return [left, top, max(left + 1, min(right, width)), max(top + 1, min(bottom, height))]


def grid_families(image, region):
    left, top, right, bottom = _region(region, image.shape)
    gray = _gray(image[top:bottom, left:right])
    families = []
    for axis, orientation, offset in ((0, "horizontal", top), (1, "vertical", left)):
        positions = [offset + p for p in inv.long_lines(gray, axis)]
        families.append({"orientation": orientation, "positions_px": positions[:128],
                         "spacing_px": inv.grid_spacing(positions)})
    return families


def _ink(image, region):
    """Dark sustained ink, without the long grid/ruler lines or small text specks."""
    left, top, right, bottom = _region(region, image.shape)
    gray = _gray(image[top:bottom, left:right])
    paper = float(np.percentile(gray, 98))
    mask = gray < min(paper - 35., 110.)
    # Detect grids in the unthresholded crop: light grid lines can cross dark ink.
    for family in grid_families(image, [left, top, right, bottom]):
        horizontal = family["orientation"] == "horizontal"
        for coordinate in family["positions_px"]:
            index = int(round(coordinate - (top if horizontal else left)))
            line = gray[index, :] if horizontal else gray[:, index]
            if np.mean(line < 110) < .9:
                continue  # Light grid and partial hull edges are not dark rulers.
            if horizontal:
                mask[max(0, index - 1):index + 2, :] = False
            else:
                mask[:, max(0, index - 1):index + 2] = False
    labels, count = ndimage.label(mask, structure=np.ones((3, 3)))
    sizes = np.bincount(labels.ravel())
    # Grid removal breaks curves into pieces; retain pieces, not just one component.
    keep = sizes >= max(4, min(gray.shape) // 30)
    keep[0] = False
    return keep[labels], left, top


def _strokes(image, region):
    """Bounded W18 direction-following discovery in a pixel-coordinate adapter."""
    left, top, right, bottom = region
    section = {"roi_px": region, "z_min_m": 0., "z_max_m": float(bottom - top - 1),
               "calibration": {"pixels_per_metre": 1., "centerline_px": float(left),
                               "baseline_px": float(bottom - 1)}}
    mask, _, _ = _ink(image, region)
    labels, _ = ndimage.label(mask, structure=np.ones((3, 3)))
    objects = ndimage.find_objects(labels)
    ranked = sorted(((i + 1, box) for i, box in enumerate(objects) if box),
                    key=lambda item: max(s.stop - s.start for s in item[1]), reverse=True)
    result = []
    for label, box in ranked[:MAX_STROKES]:
        rows, cols = np.nonzero(labels == label)
        if len(rows) < 12:
            continue
        seed = [float(cols[len(cols) // 2] + left), float(rows[len(rows) // 2] + top)]
        try:
            path = inv.follow_stroke_2d(image, section, seed)
        except inv.VerificationError:
            continue
        if len(path) < 12:
            continue
        result.append({"region_px": [float(path[:, 1].min()), float(path[:, 0].min()),
                                      float(path[:, 1].max()), float(path[:, 0].max())],
                       "length_rows_px": len(path), "seed_px": seed,
                       "kind": inv.stroke_kind(path[:, 0], path[:, 1], section)})
    return result


def survey_sheet(image, spec):
    """Tile a sheet and describe grid/stroke candidates, without naming any view."""
    height, width = image.shape[:2]
    regions = []
    for section in spec.get("sections", []):
        box = _region(section["roi_px"], image.shape)
        if box not in regions:
            regions.append(box)
    # Include uncalibrated parts of the sheet: profile, plan, tables and titles.
    tile = 768
    for top in range(0, height, tile):
        for left in range(0, width, tile):
            box = [left, top, min(left + tile, width), min(top + tile, height)]
            if not any(a <= left and b <= top and c >= box[2] and d >= box[3] for a, b, c, d in regions):
                regions.append(box)
    candidates = []
    for index, box in enumerate(regions[:MAX_REGIONS]):
        families = grid_families(image, box)
        from .ingest import _grid_evidence
        left, top, right, bottom = box
        gray = _gray(image[top:bottom, left:right])
        lattice = _grid_evidence(gray < float(np.percentile(gray, 98)) - inv.INK_CONTRAST, (left, top))
        candidates.append({"region_id": f"region-{index + 1}", "region_px": box, "kind": "unclassified",
                           "grid_evidence": lattice, "grid_families": families, "strokes": _strokes(image, box)})
    # Small components are text candidates, not OCR or certified labels.
    scale = max(1, int(math.ceil(max(width, height) / 1600)))
    mask = _gray(image)[::scale, ::scale] < 110
    labels, _ = ndimage.label(mask)
    boxes = []
    for box in ndimage.find_objects(labels):
        if box is None:
            continue
        dy, dx = (s.stop - s.start for s in box)
        if 2 <= dy <= 25 and 1 <= dx <= 100:
            boxes.append([box[1].start * scale, box[0].start * scale,
                          box[1].stop * scale, box[0].stop * scale])
        if len(boxes) >= 128:
            break
    declared = {"units": spec.get("units", "m"),
                "principal": copy.deepcopy(spec.get("principal", {})),
                "stations": [{"id": s["id"], "x_m": s["x_m"], "z_min_m": s["z_min_m"],
                              "z_max_m": s["z_max_m"]} for s in spec.get("sections", [])],
                "section_calibrations": [{"region_px": s["roi_px"],
                    "pixels_per_metre": s["calibration"]["pixels_per_metre"],
                    "centreline_px": s["calibration"]["centerline_px"],
                    "baseline_px": s["calibration"]["baseline_px"]} for s in spec.get("sections", [])]}
    return {"sheet_size_px": [width, height], "candidate_regions": candidates, "text_boxes": boxes,
            "declared": declared, "coordinates": "source pixels; whole-sheet image also uses 0-1000 axes",
            "warning": "Regions, text boxes and strokes are candidates. The model supplies identity, not the survey."}


def measure_setup(image, spec, setup):
    result = copy.deepcopy(setup)
    result["region_px"] = _region(setup["region_px"], image.shape)
    families = grid_families(image, result["region_px"])
    by_axis = {f["orientation"]: f for f in families}
    result.update(datum_snaps={}, warnings=[], proposed=copy.deepcopy(setup))
    prefix = f"views.{setup.get('view_id', setup['view'])}"
    for field, axis in (("centreline_px", "vertical" if setup["view"] == "body" else "horizontal"),
                        ("baseline_px", "horizontal"), ("x_origin_px", "vertical")):
        value = setup.get(field)
        if value is None:
            continue
        lines = by_axis[axis]["positions_px"]
        nearest = min(lines, key=lambda p: abs(p - value)) if lines else value
        distance = abs(nearest - value)
        # A distant grid line is not evidence of this datum's identity.
        snapped = nearest if distance <= 8 else value
        result[field] = snapped
        result["datum_snaps"][field] = {"proposed_px": value, "measured_px": snapped, "distance_px": distance}
        if not lines or distance > 8:
            result["warnings"].append(warning(f"{prefix}.{field}", value, nearest if lines else None,
                                               "Read this datum on the view crop; no nearby grid line supports it."))
    expected = setup["pixels_per_metre"] * setup["grid_spacing_m"]
    for family in families:
        spacing = family["spacing_px"]
        if spacing is None:
            continue
        ratio = expected / spacing
        nearest = max(1, round(ratio)) if ratio >= 1 else 1 / max(1, round(1 / ratio))
        if abs(ratio / nearest - 1) > DIMENSION_TOLERANCE:
            result["warnings"].append(warning(f"{prefix}.pixels_per_metre", setup["pixels_per_metre"],
                spacing / setup["grid_spacing_m"], "Check the labelled grid interval and scale; keep the declared calibration until resolved."))
    result["grid_families"] = families
    return result


def _value(record):
    return record.get("value") if isinstance(record, dict) else record


def _different(a, b, tolerance=DIMENSION_TOLERANCE):
    return abs(float(a) - float(b)) > tolerance * max(abs(float(b)), .001)


def _extents(image, region, ppm, centre=None, baseline=None):
    mask, left, top = _ink(image, region)
    rows, cols = np.nonzero(mask)
    if not len(rows):
        return {}
    result = {"left_px": float(cols.min() + left), "right_px": float(cols.max() + left),
              "top_px": float(rows.min() + top), "bottom_px": float(rows.max() + top)}
    if centre is not None:
        result["beam"] = 2 * max(abs(result["left_px"] - centre), abs(result["right_px"] - centre)) / ppm
    if baseline is not None:
        result["depth"] = (baseline - result["top_px"]) / ppm
    return result


def first_hull_spec(spec, description):
    """Apply usable description inputs to a copy, leaving frozen input untouched."""
    result = copy.deepcopy(spec)
    if not description:
        return result
    positions = {s.get("id"): s.get("x_m") for s in description.get("stations", [])}
    proposed = [positions.get(s["id"], s["x_m"]) for s in result["sections"]]
    if all(isinstance(x, (int, float)) and math.isfinite(x) for x in proposed) and all(
            a < b for a, b in zip(proposed, proposed[1:])):
        for section, x in zip(result["sections"], proposed):
            section["x_m"] = x
    for name, field in (("beam", "beam_m"), ("depth", "depth_m"), ("loa", "length_m")):
        value = _value(description.get("principal", {}).get(name))
        if isinstance(value, (int, float)) and math.isfinite(value) and value > 0:
            result.setdefault("constraints", {})[field] = value
    return result


def describe_table(table, description):
    """Use the read waterline grid and carry form/end hints via the public table."""
    if not description:
        return
    heights = [w.get("z_m") for w in description.get("waterlines", [])]
    if len(heights) >= 2 and all(isinstance(z, (int, float)) and math.isfinite(z) for z in heights):
        table.waterlines_z_m = sorted(set(heights))
    table.trend["description"] = copy.deepcopy(description)
    table.warnings.extend(copy.deepcopy(description.get("warnings", [])))


def measure_description(image, spec, description, setups):
    """Retain model readings, add measured values, and name every doubtful field."""
    result = copy.deepcopy(description)
    result.setdefault("units", spec.get("units", "m"))
    result.setdefault("frame", "x aft to forward from station datum; z up from baseline; metres")
    warnings = []
    principal = result.setdefault("principal", {})
    measurements = {}
    # The supplied body regions separate drawing labels from section ink and can
    # have individual datums (separate panels). They are not inferred geometry.
    body = []
    for section in spec.get("sections", []):
        cal = section["calibration"]
        body.append(_extents(image, section["roi_px"], cal["pixels_per_metre"],
                             cal["centerline_px"], cal["baseline_px"]))
    for name in ("beam", "depth"):
        values = [e[name] for e in body if name in e]
        if values:
            measurements[name] = [{"view_id": "declared_body", "value": max(values)}]
    profile = None
    for setup in setups:
        warnings.extend(copy.deepcopy(setup.get("warnings", [])))
        kind = setup.get("view", setup.get("kind"))
        if kind == "plan":
            # Plan breadth is a vertical distance from its centreline.
            extent = _extents(image, setup["region_px"], setup["pixels_per_metre"])
            if extent and setup.get("centreline_px") is not None:
                value = 2 * max(abs(extent["top_px"] - setup["centreline_px"]),
                                abs(extent["bottom_px"] - setup["centreline_px"])) / setup["pixels_per_metre"]
                measurements.setdefault("beam", []).append({"view_id": setup.get("view_id", "plan"), "value": value})
        if kind == "profile":
            profile = setup
            extent = _extents(image, setup["region_px"], setup["pixels_per_metre"], baseline=setup.get("baseline_px"))
            if "depth" in extent:
                measurements.setdefault("depth", []).append({"view_id": setup.get("view_id", "profile"), "value": extent["depth"]})
            if extent:
                measurements["loa"] = [{"view_id": setup.get("view_id", "profile"),
                                         "value": (extent["right_px"] - extent["left_px"]) / setup["pixels_per_metre"]}]
    for name, record in list(principal.items()):
        value = _value(record)
        if value is not None and value <= 0:
            warnings.append(warning(f"principal.{name}", value, None, "Read a positive principal dimension or label it as unknown/inferred."))
    for name in ("loa", "lpp", "draft"):
        if name not in measurements:
            record = principal.get(name)
            warnings.append(warning(f"principal.{name}", _value(record), None,
                "No independent dimension measurement is available; read dimension text or retain this field as ai_inferred."))
    for name, values in measurements.items():
        record = principal.get(name)
        if record is None:
            record = {"value": values[0]["value"], "source": "measured"}
        elif not isinstance(record, dict):
            record = {"value": record, "source": "ai_inferred"}
        claimed = _value(record)
        record["model_value"] = claimed
        record["measured_value"] = values[0]["value"]
        record["measurements"] = values
        for measured in values:
            if claimed is not None and _different(claimed, measured["value"]):
                warnings.append(warning(f"principal.{name}", claimed, measured["value"],
                    f"Check {name} against {measured['view_id']} ink and dimension text; do not treat the claim as verified."))
        if record.get("source") == "measured":
            record["value"] = values[0]["value"]
        principal[name] = record
    # Draft is a design waterline, not the top of a section. Do not substitute depth.
    if "draft" in principal:
        draft = _value(principal["draft"])
        depth = _value(principal.get("depth"))
        if draft is not None and depth is not None and draft > depth:
            warnings.append(warning("principal.draft", draft, depth, "Read the design waterline; draft must not exceed depth."))
    declared = {s["id"]: s for s in spec.get("sections", [])}
    stations = result.setdefault("stations", [{"id": s["id"], "x_m": s["x_m"], "label": s["id"], "source": "spec"}
                                             for s in spec.get("sections", [])])
    if len(stations) != len(declared) or {s.get("id") for s in stations} != set(declared):
        warnings.append(warning("stations", [s.get("id") for s in stations], list(declared), "Match the declared station ids and count."))
    previous = -math.inf
    for index, station in enumerate(stations):
        x = station.get("x_m")
        known = declared.get(station.get("id"))
        if x is None or x <= previous or (known and _different(x, known["x_m"])):
            warnings.append(warning(f"stations[{index}].x_m", x, known["x_m"] if known else None,
                                    "Use the declared station position or check the plan/profile station grid."))
        previous = x if isinstance(x, (int, float)) else previous
        if re.search(r"S?\d+(?:\.\d+)?[WB]$", station.get("label", ""), re.I):
            warnings.append(warning(f"stations[{index}].label", station["label"], None,
                                    "This looks like a waterline/buttock tag, not a station label."))
    grid_heights = []
    for setup in setups:
        if setup.get("view") != "body" or setup.get("baseline_px") is None:
            continue
        for family in grid_families(image, setup["region_px"]):
            if family["orientation"] == "horizontal" and family["spacing_px"] is not None:
                grid_heights.extend((setup["baseline_px"] - p) / setup["pixels_per_metre"]
                                    for p in family["positions_px"] if p <= setup["baseline_px"] + 1)
    grid_heights = sorted({round(z, 5) for z in grid_heights})
    waterlines = result.setdefault("waterlines", [{"id": f"wl{i}", "z_m": z, "label": f"WL {z:g}", "source": "measured"}
                                                  for i, z in enumerate(grid_heights)])
    heights = [w.get("z_m") for w in waterlines]
    if grid_heights and (len(heights) != len(grid_heights) or any(
            z is None or abs(z - g) > .02 * max(1., abs(g)) for z, g in zip(sorted(z for z in heights if z is not None), grid_heights))):
        warnings.append(warning("waterlines", heights, grid_heights, "Read the body-plan horizontal grid and include its labelled waterlines."))
    previous = -math.inf
    depth = _value(principal.get("depth"))
    for index, waterline in enumerate(waterlines):
        z = waterline.get("z_m")
        nearest = min(grid_heights, key=lambda g: abs(g - z)) if grid_heights and z is not None else None
        if z is None or z <= previous or (depth is not None and z > depth + .02 * max(depth, 1)) or (nearest is not None and abs(z - nearest) > .02):
            warnings.append(warning(f"waterlines[{index}].z_m", z, nearest,
                                    "Check the waterline height, order and depth against the body/profile grid."))
        previous = z if isinstance(z, (int, float)) else previous
    ends = result.setdefault("ends", {})
    for name, part in ends.items():
        if isinstance(part, dict) and profile is None:
            part["source"] = "ai_inferred"
    xs = [s["x_m"] for s in spec.get("sections", [])]
    length = _value(principal.get("loa")) or _value(principal.get("lpp"))
    limit = float(length) if length else max(xs, default=0)
    for end in ("stem", "stern"):
        for field, value in ends.get(end, {}).items():
            if field in {"x_top", "x_foot", "x_transom"} and isinstance(value, (int, float)) and not -.02 * max(limit, 1) <= value <= limit * 1.02:
                warnings.append(warning(f"ends.{end}.{field}", value, [0, limit], "Place the end inside the calibrated profile outline; check the x datum."))
    if ends.get("bulb", {}).get("present") and profile is None:
        warnings.append(warning("ends.bulb.present", True, None, "No profile supports this bulb claim; keep it ai_inferred."))
    result.setdefault("buttocks", [])
    result.setdefault("deck", {"source": "ai_inferred"})
    result.setdefault("form", {"type": "displacement", "source": "ai_inferred"})
    result.update(warnings=warnings, engineering_approved=False)
    return result
