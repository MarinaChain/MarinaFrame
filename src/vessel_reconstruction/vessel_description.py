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
    """Description claims are data, not a reason to stop the read phase."""
    return True


def _number(value):
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def normalize_description(description):
    """Keep every original claim; make only computational fields numeric or null."""
    result = copy.deepcopy(description) if isinstance(description, dict) else {"extra_metadata": description}
    warnings = []

    def changed(field, original, value):
        warnings.append(warning(field, original, value,
                                "Original data retained in model_description; check the normalized reading."))

    if not isinstance(description, dict):
        changed("description", description, None)
    for key in ("principal", "ends", "deck", "form"):
        if key in result and not isinstance(result[key], dict):
            original = result[key]
            result[key] = {"note": original}
            changed(key, original, result[key])
    known = {"units", "frame", "principal", "stations", "waterlines", "buttocks", "ends", "deck", "form", "warnings", "dimension_text"}
    for key in result.keys() - known:
        changed(key, result[key], None)
    principal = result.setdefault("principal", {})
    for name, original in list(principal.items()):
        record = copy.deepcopy(original) if isinstance(original, dict) else {"value": original}
        if record.get("source") not in (None, "spec", "title_block", "measured", "ai_inferred"):
            changed(f"principal.{name}.source", record["source"], None)
        if name not in {"loa", "lpp", "beam", "depth", "draft"}:
            changed(f"principal.{name}", original, None)
            continue  # Extra metadata, such as a scale string, is not a dimension.
        value = _number(record.get("value"))
        if record.get("value") != value or type(record.get("value")) not in (int, float, type(None)):
            changed(f"principal.{name}", original, value)
            record["original_value"] = record.get("value")
        record["value"] = value
        record.setdefault("source", "ai_inferred")
        principal[name] = record
    for key, coordinate in (("stations", "x_m"), ("waterlines", "z_m"), ("buttocks", "y_m")):
        if key not in result:
            continue
        original = result[key]
        rows = original
        if isinstance(rows, dict):
            rows = [{"id": str(k), **(v if isinstance(v, dict) else {coordinate: v})} for k, v in rows.items()]
            changed(key, original, None)
        if not isinstance(rows, list):
            changed(key, original, None)
            result[key] = []
            continue
        normalized = []
        for index, row in enumerate(rows[:300]):
            row = copy.deepcopy(row) if isinstance(row, dict) else {coordinate: row}
            row["id"] = str(row.get("id", f"{key}-{index + 1}"))
            value = _number(row.get(coordinate))
            if row.get(coordinate) != value or type(row.get(coordinate)) not in (int, float, type(None)):
                changed(f"{key}[{index}].{coordinate}", row.get(coordinate), value)
            row[coordinate] = value
            if "label" in row and not isinstance(row["label"], str):
                row["label"] = str(row["label"])
            normalized.append(row)
        if len(rows) > 300:
            changed(key, "More than 300 rows; original retained", 300)
        result[key] = normalized
    ends = result.setdefault("ends", {})
    for name, part in list(ends.items()):
        if name in {"stem", "bow", "stern", "bulb", "keel"} and not isinstance(part, dict):
            ends[name] = {"note": part, "source": "ai_inferred"}
            changed(f"ends.{name}", part, None)
    result["model_description"] = copy.deepcopy(description)
    return result, warnings


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
            if np.mean(line < 110) < .5:
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
    doubtful = {w.get("field") for w in description.get("warnings", [])}
    for name, field in (("beam", "beam_m"), ("depth", "depth_m"), ("loa", "length_m")):
        value = _value(description.get("principal", {}).get(name))
        if f"principal.{name}" in doubtful:
            continue
        if isinstance(value, (int, float)) and math.isfinite(value) and value > 0:
            result.setdefault("constraints", {})[field] = value
    return result


def printed_dimensions(description):
    """Parse labelled text transcribed by the model, never evaluator metadata/OCR."""
    text = description.get("dimension_text", "")
    if not isinstance(text, str):
        return {}
    labels = {"LOA": "loa", "LPP": "lpp", "BEAM": "beam", "DEPTH": "depth", "DRAFT": "draft"}
    readings = {}
    for match in re.finditer(r"\b(LOA|LPP|BEAM|DEPTH|DRAFT)\b\s*(?:\(DWL\))?\s*[:=]?\s*(\d+(?:\.\d+)?)\s*m\b", text, re.I):
        readings[labels[match[1].upper()]] = {"value": float(match[2]), "source": "title_block",
                                            "text": match[0]}
    return readings


def dimension_conflicts(name, readings):
    """Compare independent readings pairwise; no fitted value becomes truth."""
    conflicts = []
    for index, first in enumerate(readings):
        for second in readings[index + 1:]:
            if _different(first["value"], second["value"]):
                conflicts.append(warning(f"principal.{name}", first["value"], second["value"],
                    f"Recheck {name}: {first['view_id']} disagrees with {second['view_id']} by more than 2%; retain the printed reading when legible."))
    return conflicts


def describe_table(table, description):
    """Use the read waterline grid and carry form/end hints via the public table."""
    if not description:
        return
    heights = [w.get("z_m") for w in description.get("waterlines", [])]
    if len(heights) >= 2 and all(isinstance(z, (int, float)) and math.isfinite(z) for z in heights):
        table.waterlines_z_m = sorted(set(heights))
    table.trend["description"] = copy.deepcopy(description)
    table.warnings.extend(copy.deepcopy(description.get("warnings", [])))
    points = [point for row in table.stations for point in row.points_yz_m]
    if points:
        hull = {"beam": 2 * max(abs(p[0]) for p in points),
                "depth": max(p[1] for p in points) - min(p[1] for p in points)}
        for name, value in hull.items():
            record = description.get("principal", {}).get(name, {})
            readings = copy.deepcopy(record.get("measurements", [])) if isinstance(record, dict) else []
            claimed = _number(_value(record))
            if claimed is not None:
                readings.append({"view_id": "description", "value": claimed})
            readings.append({"view_id": "draft_hull", "value": value})
            table.warnings.extend(dimension_conflicts(name, readings))
        table.trend["description"]["draft_hull_dimensions"] = hull


def measure_description(image, spec, description, setups):
    """Retain model readings, add measured values, and name every doubtful field."""
    result, warnings = normalize_description(description)
    result.setdefault("units", spec.get("units", "m"))
    result.setdefault("frame", "x aft to forward from station datum; z up from baseline; metres")
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
    for name in ("loa", "lpp", "beam", "depth", "draft"):
        value = _value(principal.get(name))
        if value is not None and value <= 0:
            warnings.append(warning(f"principal.{name}", value, None, "Read a positive principal dimension or label it as unknown/inferred."))
    for name in ("loa", "lpp", "draft"):
        if name not in measurements:
            record = principal.setdefault(name, {"value": None, "source": "ai_inferred"})
            warnings.append(warning(f"principal.{name}", _value(record), None,
                "No independent dimension measurement is available; read dimension text or retain this field as ai_inferred."))
    printed = printed_dimensions(result)
    declared_depth = max((s["z_max_m"] for s in spec.get("sections", [])), default=None)
    for name in sorted(set(measurements) | set(printed)):
        record = principal.get(name)
        record = copy.deepcopy(record) if isinstance(record, dict) else {"value": record, "source": "ai_inferred"}
        claimed = _number(_value(record))
        readings = copy.deepcopy(measurements.get(name, []))
        if claimed is not None:
            readings.insert(0, {"view_id": "model_reading", "value": claimed})
        if name == "depth" and declared_depth is not None:
            readings.append({"view_id": "declared_depth", "value": declared_depth})
        if name in printed:
            readings.append({"view_id": "printed_dimension", "value": printed[name]["value"]})
        warnings.extend(dimension_conflicts(name, readings))
        if name in {"beam", "depth"} and claimed is None and name not in printed:
            warnings.append(warning(f"principal.{name}", None, measurements.get(name),
                "No independent model/text reading supports the ink extent; annotation or competing strokes may inflate it. Read the dimension or mark it uncertain."))
        record["model_value"] = claimed
        record["measurements"] = readings
        if measurements.get(name):
            record["measured_value"] = measurements[name][0]["value"]
        if name in printed:
            record.update(printed[name])
        elif record.get("source") == "title_block" and claimed is not None:
            pass  # Explicit printed readings outrank approximate pixel extents.
        elif name == "depth" and declared_depth is not None:
            record.update(value=declared_depth, source="spec")
        elif measurements.get(name) and (record.get("source") == "measured" or claimed is None):
            record.update(value=measurements[name][0]["value"], source="measured")
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
    # Repeated panels have different origins. Read each declared drawing region,
    # not the blank gaps and labels inside a sheet-wide family bounding box.
    grid_setups = [{"region_px": s["roi_px"], "baseline_px": s["calibration"]["baseline_px"],
                    "pixels_per_metre": s["calibration"]["pixels_per_metre"], "z_max_m": s["z_max_m"]}
                   for s in spec.get("sections", [])]
    if not grid_setups:
        grid_setups = [s for s in setups if s.get("view") == "body" and s.get("baseline_px") is not None]
    for setup in grid_setups:
        for family in grid_families(image, setup["region_px"]):
            if family["orientation"] == "horizontal" and family["spacing_px"] is not None:
                interval = family["spacing_px"] / setup["pixels_per_metre"]
                for position in family["positions_px"]:
                    z = (setup["baseline_px"] - position) / setup["pixels_per_metre"]
                    if .05 < z <= setup.get("z_max_m", math.inf) + .02:
                        # Snap only to the measured lattice interval, not a hull reference.
                        grid_heights.append(round(z / interval) * interval)
    merged = []
    for z in sorted(grid_heights):
        if not merged or abs(z - merged[-1]) > .02 * max(1., abs(z)):
            merged.append(z)
    grid_heights = [round(z, 5) for z in merged]
    if len(grid_heights) >= 2:
        intervals = [f["spacing_px"] / s["pixels_per_metre"] for s in grid_setups
                     for f in grid_families(image, s["region_px"])
                     if f["orientation"] == "horizontal" and f["spacing_px"] is not None]
        interval = float(np.median(intervals)) if intervals else None
        if interval and interval > 0:
            # Read-error tolerance permits rounding a measured metric lattice.
            rounded = round(interval * 4) / 4
            if rounded > 0 and not _different(interval, rounded):
                interval = rounded
            depth_limit = max((s.get("z_max_m", 0) for s in grid_setups), default=0)
            if depth_limit:
                grid_heights = [round(i * interval, 5) for i in range(1, min(300, int(depth_limit / interval)) + 1)]
    waterlines = result.setdefault("waterlines", [{"id": f"wl{i}", "z_m": z, "label": f"WL {z:g}", "source": "measured"}
                                                  for i, z in enumerate(grid_heights)])
    heights = [w.get("z_m") for w in waterlines]
    if not grid_heights or len(heights) != len(grid_heights) or any(
            z is None or abs(z - g) > .02 * max(1., abs(g)) for z, g in zip(sorted(z for z in heights if z is not None), grid_heights)):
        warnings.append(warning("waterlines", heights, grid_heights or None,
            "Waterline set is incomplete or unconfirmed; read all labelled heights, excluding the baseline."))
    previous = -math.inf
    depth = _value(principal.get("depth"))
    for index, waterline in enumerate(waterlines):
        z = waterline.get("z_m")
        nearest = min(grid_heights, key=lambda g: abs(g - z)) if grid_heights and z is not None else None
        if z is None or z <= previous or (depth is not None and z > depth + .02 * max(depth, 1)) or (nearest is not None and abs(z - nearest) > .02):
            warnings.append(warning(f"waterlines[{index}].z_m", z, nearest,
                                    "Check the waterline height, order and depth against the body/profile grid."))
        previous = z if isinstance(z, (int, float)) else previous
    if grid_heights:
        # Preserve the model set above; the usable grid comes from measured panels.
        result["waterlines"] = [{"id": f"wl{i + 1}", "z_m": z, "label": f"WL {z:g}", "source": "measured"}
                                for i, z in enumerate(grid_heights)]
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
    for field, present in (("ends.keel", "keel" in ends or "keel_z" in ends or "rise_of_floor" in ends),
                           ("ends.stem", bool(ends.get("stem"))), ("ends.stern", bool(ends.get("stern"))),
                           ("ends.bulb", "bulb" in ends),
                           ("deck.sheer_z", bool(result.get("deck", {}).get("sheer_z"))),
                           ("form.type", bool(result.get("form", {}).get("type"))),
                           ("waterlines", bool(waterlines)), ("buttocks", "buttocks" in result)):
        if not present:
            warnings.append(warning(field, None, None, "Read this field from the views or state an explicit ai_inferred estimate."))
    for name in ("beam", "depth"):
        if name not in principal:
            warnings.append(warning(f"principal.{name}", None, None, "No usable ink extent; read the dimension or label an inference."))
    result.setdefault("buttocks", [])
    result.setdefault("deck", {"source": "ai_inferred"})
    result.setdefault("form", {"type": "displacement", "source": "ai_inferred"})
    result.update(warnings=warnings, engineering_approved=False)
    return result
