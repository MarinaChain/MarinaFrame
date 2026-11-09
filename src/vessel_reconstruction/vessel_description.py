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


def printed_scale(description):
    """Pixels per metre printed on the sheet ("SCALE 1 m = 19.000 px"), or None."""
    text = description.get("dimension_text", "")
    match = re.search(r"\b1\s*m\s*=\s*(\d+(?:\.\d+)?)\s*px\b", text if isinstance(text, str) else "", re.I)
    return float(match[1]) if match and float(match[1]) > 0 else None


def _implied_scale(image, setup, printed):
    """Pixels per metre implied by a view's ink extent and a printed length (LOA or beam), or None."""
    extent = _extents(image, setup["region_px"], setup["pixels_per_metre"])
    if not extent:
        return None
    kind = setup.get("view", setup.get("kind"))
    loa, beam = (_value(printed.get(name)) for name in ("loa", "beam"))
    if kind in ("profile", "plan") and loa:
        return (extent["right_px"] - extent["left_px"]) / loa
    if kind == "body" and beam and setup.get("centreline_px") is not None:
        centre = setup["centreline_px"]
        return 2 * max(abs(extent["left_px"] - centre), abs(extent["right_px"] - centre)) / beam
    return None


def checked_scales(image, setups, description):
    """Each view's likely scale and a warning for every view whose scale disagrees with it.

    The likely scale is the printed sheet scale when one is legible, else the
    scale implied by the view's ink length and the printed LOA (beam for a
    body plan). Returns ({view_id: pixels_per_metre}, warnings); a view with no
    independent reading keeps its own scale. Advisory: the model re-proposes the setup.
    """
    sheet = printed_scale(description)
    printed = printed_dimensions(description)
    likely, warnings = {}, []
    for setup in setups:
        view_id = setup.get("view_id", setup.get("view"))
        own = float(setup["pixels_per_metre"])
        implied = sheet or _implied_scale(image, setup, printed)
        likely[view_id] = own
        if implied is None or not _different(own, implied):
            continue
        basis = (f"the sheet prints SCALE 1 m = {sheet:g} px" if sheet else
                 "the view's ink length over the printed LOA/beam gives " f"{implied:.2f} px/m")
        likely[view_id] = implied
        warnings.append(warning(f"views.{view_id}.pixels_per_metre", own, round(implied, 3),
            f"Scale conflict: this view uses {own:g} px/m but {basis}. Re-propose this view with "
            f"propose_sheet_setup and pixels_per_metre {implied:.3f}, or explain the difference."))
    return likely, warnings


# The deck line in a profile is the top edge of the large hull outline. Ink
# components narrower than DECK_COMPONENT_SHARE of the view (station numbers,
# labels) are not the outline. Columns within DECK_COLUMN_PX of the station are read.
DECK_COMPONENT_SHARE = 0.25
DECK_COLUMN_PX = 2
# A model baseline this far from the outline's lowest line is another grid
# line; OUTLINE_HALF_LINE_PX is half the width of a drawn hull line.
BASELINE_SNAP_PX = 3.0
OUTLINE_HALF_LINE_PX = 1.0
# Hull lines are dark; grid lines and the light baseline ruler are not (grey levels).
OUTLINE_INK = 110
# Blank rows that separate two views' outlines inside one region.
OUTLINE_GAP_ROWS = 10
# A model x origin outside the profile region, or within this of its edge, is
# not a datum read on the sheet.
ORIGIN_EDGE_PX = 3


def profile_deck_heights(image, setup, pixels_per_metre, stations):
    """Height of the profile's top outline (deck at side) at each station x, {id: z}."""
    return {sid: heights["deck"]
            for sid, heights in profile_outline_heights(image, setup, pixels_per_metre, stations).items()}


def _line_centre(rows, columns, from_top):
    """Row centre of the first ink run in ``columns``, from the top or from the bottom."""
    first = rows[0] if from_top else rows[-1]
    step = 1 if from_top else -1
    end = first
    while 0 <= end + step < len(columns) and columns[end + step].any():
        end += step
    return 0.5 * (first + end)


def profile_outline_heights(image, setup, pixels_per_metre, stations):
    """Deck-at-side and keel heights of the profile outline at each station x, {id: {"deck", "keel"}}.

    ``setup`` is the model's profile setup (region, x origin and direction,
    baseline); ``pixels_per_metre`` is the checked scale. Heights are line
    centres, as body-plan curve ends are read. A station outside the outline
    has no entry.
    """
    if setup.get("baseline_px") is None or setup.get("x_origin_px") is None:
        return {}
    outline, left, top = _profile_outline(image, setup)
    origin = checked_x_origin(image, setup)
    # A rotated scan tilts every horizontal line: rows are levelled about the view's middle column.
    slope = view_skew(image, setup["region_px"])
    middle = outline.shape[1] / 2

    def level(row, column):
        return row - slope * (column - middle)

    # The model's baseline row (taken as read at the view's middle, the
    # levelling pivot) is kept unless the outline's lowest line is more than
    # BASELINE_SNAP_PX away: it is then another grid line (dtmb5415 live: a
    # waterline 2 m up), and z = 0 is the outline's keel line.
    baseline = setup["baseline_px"] - top
    keel = _bottom_line_centre(outline, slope)
    if keel is not None and abs(keel - baseline) > BASELINE_SNAP_PX:
        baseline = keel
    heights = {}
    for station in stations:
        column = origin + (setup.get("x_direction") or 1) * station["x_m"] * pixels_per_metre - left
        columns = outline[:, max(0, int(round(column)) - DECK_COLUMN_PX):int(round(column)) + DECK_COLUMN_PX + 1]
        rows = np.flatnonzero(columns.any(axis=1))
        if not len(rows):
            continue
        heights[station["id"]] = {
            "deck": (baseline - level(_line_centre(rows, columns, True), column)) / pixels_per_metre,
            "keel": (baseline - level(_line_centre(rows, columns, False), column)) / pixels_per_metre}
    return heights


# Sheet rotation: a scanned or photographed sheet is rotated by a fraction of
# a degree, so long horizontal lines (grid, baseline, deck, keel) climb or
# fall across a long view. Slopes within +-SKEW_MAX_SLOPE (about 1.1 degrees)
# are tried; the one that stacks the view's line ink into the sharpest rows wins.
SKEW_MAX_SLOPE = 0.02
SKEW_STEPS = 161
SKEW_INK_CONTRAST = 25
SKEW_MIN_GAIN = 1.25


def view_skew(image, region):
    """Rows per column by which horizontal lines climb in a view (0 on an unrotated sheet)."""
    left, top, right, bottom = _region(region, image.shape)
    gray = _gray(image[top:bottom, left:right])
    ys, xs = np.nonzero(gray < np.percentile(gray, 95) - SKEW_INK_CONTRAST)
    if len(ys) < 100:
        return 0.0
    centred = xs - gray.shape[1] / 2

    def sharpness(slope):
        rows = np.rint(ys - slope * centred).astype(int)
        return float(np.sum(np.bincount(rows - rows.min()).astype(float) ** 2))

    level = sharpness(0.0)
    best, best_score = 0.0, level
    for slope in np.linspace(-SKEW_MAX_SLOPE, SKEW_MAX_SLOPE, SKEW_STEPS):
        score = sharpness(slope)
        if score > best_score:
            best, best_score = float(slope), score
    # A sloped sheer can also stack into rows; a rotated grid stacks far better.
    return best if best_score >= SKEW_MIN_GAIN * level else 0.0


def _profile_outline(image, setup):
    """The large hull outline of a profile view (dark ink, rulers kept), and its crop origin."""
    # Dark ink only, rulers kept: a flat deck or a keel line is as long as a ruler.
    left, top, right, bottom = _region(setup["region_px"], image.shape)
    mask = _gray(image[top:bottom, left:right]) < OUTLINE_INK
    labels, _ = ndimage.label(mask, structure=np.ones((3, 3)))
    wide = [index for index, box in enumerate(ndimage.find_objects(labels), 1)
            if box and box[1].stop - box[1].start >= DECK_COMPONENT_SHARE * mask.shape[1]]
    outline = np.isin(labels, wide)
    # A region drawn over two views (profile and the plan below it, series60-3v-L2
    # live) holds two outlines with blank rows between: the profile is the top one.
    rows = np.flatnonzero(outline.any(axis=1))
    gaps = np.flatnonzero(np.diff(rows) > OUTLINE_GAP_ROWS)
    if len(gaps):
        outline[rows[gaps[0]] + 1:] = False
    return outline, left, top


def checked_x_origin(image, setup):
    """The profile's x origin: the model's, or the outline's aft end when the model's is not a reading.

    A model origin outside the view region is a coordinate of its view crop,
    not of the sheet (dtmb5415 live: 10 px); one on the region's edge is the
    edge, not a datum (shipd-1-00679 live: 87 px, the region's left side).
    x = 0 is then taken at the hull's aft extreme, the frame the description
    states for these sheets.
    """
    left, _, right, _ = _region(setup["region_px"], image.shape)
    origin = float(setup["x_origin_px"])
    if left + ORIGIN_EDGE_PX < origin < right - ORIGIN_EDGE_PX:
        return origin
    outline, crop_left, _ = _profile_outline(image, setup)
    columns = np.flatnonzero(outline.any(axis=0))
    if not len(columns):
        return origin
    aft = columns[0] if (setup.get("x_direction") or 1) >= 0 else columns[-1]
    return float(aft + crop_left)


def _bottom_line_centre(outline, slope=0.0):
    """Levelled row (in the outline crop) of the centre of the hull outline's lowest ink, or None.

    z = 0 is the lowest hull point (a keel, or a bulb or dome below it); its
    drawn line centre is half a line width above the lowest inked row. Rows
    are levelled by ``slope`` about the crop's middle column (view_skew).
    """
    ys, xs = np.nonzero(outline)
    if not len(ys):
        return None
    return float(np.max(ys - slope * (xs - outline.shape[1] / 2))) - OUTLINE_HALF_LINE_PX


# Station lines: on a profile, the station lines are the only vertical lines
# that run over at least STATION_LINE_SHARE of the view height (waterlines are
# horizontal; hull ends are short). A model position more than
# STATION_TOLERANCE_M from its measured line is a misreading.
STATION_LINE_SHARE = 0.6
STATION_TOLERANCE_M = 0.5
MIN_STATION_LINES = 3
# Station lines are evenly spaced: every gap within this share of the median gap.
STATION_SPACING_SPREAD = 0.15


def profile_station_lines(image, setup, pixels_per_metre):
    """x positions (m, from the profile's x origin) of the full-height vertical lines in the profile."""
    left, top, right, bottom = _region(setup["region_px"], image.shape)
    crop = _gray(image[top:bottom, left:right])
    # Ink relative to the paper beside it (inv.drawn_lines): a scan's paper is
    # grey and uneven, and a blurred light station line is only a little darker.
    paper = ndimage.grey_closing(crop, size=(1, inv.LINE_BACKGROUND_PX))
    inked = paper - crop >= inv.LINE_CONTRAST
    columns = np.flatnonzero(inked.mean(axis=0) >= STATION_LINE_SHARE)
    groups = np.split(columns, np.flatnonzero(np.diff(columns) > 1) + 1) if len(columns) else []
    # Station lines are drawn light; a dark full-height line is hull ink (a transom, a stem).
    grid = [g for g in groups if len(g) and float(np.median(crop[:, g][inked[:, g]])) >= OUTLINE_INK]
    direction = setup.get("x_direction", 1) or 1
    return [round(direction * (float(np.mean(g)) + left - setup["x_origin_px"]) / pixels_per_metre, 3)
            for g in grid]


def check_station_positions(image, setups, description, warnings, hints=None):
    """Replace model station positions with the profile's station lines when they disagree.

    Same count: each station keeps its id and takes the measured x in order.
    Another count: the measured lines become the stations, numbered 1..n.
    Returns the (possibly new) station list; a warning names the change.
    """
    stations = description.get("stations") or []
    profile = profile_setup(setups, hints)
    if profile is None:
        return stations
    profile = {**profile, "x_origin_px": checked_x_origin(image, profile)}
    scale = (description.get("checked_scales") or {}).get(profile.get("view_id", "profile"),
                                                         profile["pixels_per_metre"])
    measured = sorted(x for x in profile_station_lines(image, profile, float(scale)) if x > -STATION_TOLERANCE_M)
    spacing = np.diff(measured)
    if len(measured) < MIN_STATION_LINES or np.max(np.abs(spacing - np.median(spacing))) > \
            STATION_SPACING_SPREAD * np.median(spacing):
        # Too few lines, or uneven ones (noise, a heavily degraded scan): not a station grid.
        return stations
    claimed = [s.get("x_m") for s in stations if isinstance(s, dict)]
    if len(claimed) == len(measured) and all(
            isinstance(x, (int, float)) and abs(x - m) <= STATION_TOLERANCE_M for x, m in zip(claimed, measured)):
        return stations
    if len(claimed) == len(measured):
        corrected = [{**station, "x_m": x, "source": "profile_station_lines", "model_x_m": station.get("x_m")}
                     for station, x in zip(stations, measured)]
    else:
        corrected = [{"id": str(i + 1), "x_m": x, "label": str(i + 1), "source": "profile_station_lines"}
                     for i, x in enumerate(measured)]
        # The body-plan half of a station is read from its label there: a model
        # station with the same number keeps its side (series60-3v-L1 live: ten
        # stations 0-9 over LOA, nine lines; station 5 is drawn on the fore half).
        read_sides = {str(s.get("id")): s.get("side") for s in stations
                      if isinstance(s, dict) and s.get("side") in ("fore", "aft")}
        for station in corrected:
            if station["id"] in read_sides:
                station["side"] = read_sides[station["id"]]
    warnings.append(warning("stations", claimed, measured,
        f"The profile's {len(measured)} station lines are at x {', '.join(f'{x:g}' for x in measured)} m; "
        "those positions are used. Read the station numbers along the profile or plan if these are not the stations."))
    return corrected


# The model's profile region is used when it overlaps the intake's proposed
# profile region by at least this IoU; otherwise the intake's region is (a
# model reading in view-crop pixels, dtmb5415-3v-L1 live: [60, 40, 800, 170]).
PROFILE_REGION_AGREEMENT = 0.5


def _iou(first, second) -> float:
    left, top = max(first[0], second[0]), max(first[1], second[1])
    right, bottom = min(first[2], second[2]), min(first[3], second[3])
    overlap = max(0, right - left) * max(0, bottom - top)
    union = ((first[2] - first[0]) * (first[3] - first[1]) + (second[2] - second[0]) * (second[3] - second[1])
             - overlap)
    return overlap / union if union > 0 else 0.0


def profile_setup(setups, hints=None):
    """The model's profile setup, on the intake's profile region when the model's region disagrees, or None."""
    profile = next((s for s in setups if s.get("view") == "profile" and s.get("x_origin_px") is not None), None) \
        or next((s for s in setups if s.get("view") == "profile" and s.get("region_px")), None)
    if profile is None:
        return None
    if profile.get("x_origin_px") is None:
        # No origin read (shipd-1-09867-3v-L1 live): the region's edge, which
        # checked_x_origin takes as unread (x = 0 at the hull's aft end).
        profile = {**profile, "x_origin_px": float(profile["region_px"][0])}
    proposed = next((h["region_px"] for h in hints or [] if h.get("label") == "profile" and h.get("region_px")),
                    None)
    if proposed and _iou(profile["region_px"], proposed) < PROFILE_REGION_AGREEMENT:
        return {**profile, "region_px": list(proposed), "region_source": "intake proposal"}
    if proposed:
        # The intake's rows are measured on the ink. A taller model box adds
        # paper and labels that hide the station lines' full height
        # (series60-3v-L1 live: 100 px above a 175 px profile); a shorter one
        # cuts the keel off (another run: bottom 302 px over a keel at 303 px).
        # Columns are the union: an intake region can hold only part of a long
        # view (shipd-1-09867-3v-L0: the fore half of the profile).
        left, _, right, _ = profile["region_px"]
        return {**profile, "region_px": [min(left, proposed[0]), proposed[1], max(right, proposed[2]), proposed[3]],
                "region_source": "the intake's rows"}
    return profile


def with_outline_baseline(image, profile):
    """The profile setup with a baseline: the model's, or the outline's lowest line when none was read.

    z = 0 is the hull's lowest point (the frame these sheets state), drawn as
    the outline's lowest line; profile_outline_heights snaps a read baseline
    that is far from it to it as well. A model that read no baseline
    (dtmb5415-3v-L0 live) otherwise leaves the profile unused. None when the
    outline has no ink.
    """
    if profile.get("baseline_px") is not None:
        return profile
    outline, _, top = _profile_outline(image, profile)
    keel = _bottom_line_centre(outline, view_skew(image, profile["region_px"]))
    return None if keel is None else {**profile, "baseline_px": top + keel}


def station_outline_heights(image, setups, description, stations, hints=None):
    """Deck and keel heights per station from the model's profile setup at its checked scale."""
    profile = profile_setup(setups, hints)
    profile = with_outline_baseline(image, profile) if profile is not None else None
    if profile is None:
        return {}
    scales = (description or {}).get("checked_scales") or {}
    scale = scales.get(profile.get("view_id", "profile"), profile["pixels_per_metre"])
    return profile_outline_heights(image, profile, float(scale), stations)


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


def measure_description(image, spec, description, setups, hints=None):
    """Retain model readings, add measured values, and name every doubtful field.

    ``hints`` are the intake's proposed view regions (sheet-only intake).
    """
    result, warnings = normalize_description(description)
    scales, scale_warnings = checked_scales(image, setups, result)
    result["checked_scales"] = scales
    warnings.extend(scale_warnings)
    if not spec.get("sections"):
        # A sheet-only reading: the stations come from the model, checked against the profile.
        result["stations"] = check_station_positions(image, setups, result, warnings, hints)
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
    # The plan's length is a second LOA reading: a profile/plan disagreement
    # points at one view's scale (dimension_conflicts below).
    plan_lengths = []
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
            if extent:
                plan_lengths.append({"view_id": setup.get("view_id", "plan"),
                                     "value": (extent["right_px"] - extent["left_px"]) / setup["pixels_per_metre"]})
        if kind in ("body", "body_fore", "body_aft") and not body and setup.get("centreline_px") is not None:
            # A sheet-only intake declares no sections yet: the body setup gives the body-plan beam.
            extent = _extents(image, setup["region_px"], setup["pixels_per_metre"], setup["centreline_px"])
            if "beam" in extent:
                measurements.setdefault("beam", []).append({"view_id": setup.get("view_id", "body"),
                                                            "value": extent["beam"]})
        if kind == "profile":
            profile = setup
            extent = _extents(image, setup["region_px"], setup["pixels_per_metre"], baseline=setup.get("baseline_px"))
            if "depth" in extent:
                measurements.setdefault("depth", []).append({"view_id": setup.get("view_id", "profile"), "value": extent["depth"]})
            if extent:
                measurements["loa"] = [{"view_id": setup.get("view_id", "profile"),
                                         "value": (extent["right_px"] - extent["left_px"]) / setup["pixels_per_metre"]}]
    if plan_lengths:
        measurements["loa"] = measurements.get("loa", []) + plan_lengths
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
