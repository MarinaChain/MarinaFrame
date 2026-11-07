"""Bounded, typed drawing specifications; no hidden geometry targets."""
from __future__ import annotations

import json
import math
import re
from pathlib import Path

MAX_LOCAL_METRES = 10_000_000.0
MAX_SPEC_BYTES = 2 * 1024 * 1024
MAX_SECTIONS = 300
MAX_TOTAL_CELLS = 4096
MAX_PIXEL_COORDINATE = 1_000_000
SHA256 = re.compile(r"^[0-9a-f]{64}$")
FORBIDDEN = {"points", "points_yz_m", "offsets", "ground_truth", "reference_mesh", "hull_parameters"}


class BoundedJSONError(ValueError):
    """Invalid or resource-excessive JSON, safe to report as a structured gap."""


def gap(kind: str, message: str, section_id: str | None = None, severity: str = "blocking") -> dict:
    result = {"id": f"{kind}:{section_id or 'vessel'}", "kind": kind, "severity": severity, "message": message}
    if section_id is not None:
        result["section_id"] = str(section_id)
    return result


def finite(value) -> bool:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return False
    try:
        return math.isfinite(value)
    except (OverflowError, ValueError):
        return False


def loads_bounded_json(raw: bytes | str, *, max_bytes=MAX_SPEC_BYTES, max_depth=32,
                       max_nodes=150_000, max_string=65_536):
    """Reject duplicate keys, nonfinite numbers and excessive trees before use."""
    if isinstance(raw, str):
        raw = raw.encode("utf-8")
    if not isinstance(raw, bytes) or len(raw) > max_bytes:
        raise BoundedJSONError("JSON exceeds the byte limit.")

    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise BoundedJSONError("Duplicate JSON object key.")
            result[key] = value
        return result

    def number(token):
        value = float(token)
        if not math.isfinite(value):
            raise BoundedJSONError("Nonfinite or overflowing JSON number.")
        return value

    def integer(token):
        if len(token.lstrip("-")) > 64:
            raise BoundedJSONError("JSON integer exceeds the numeric bound.")
        return int(token)

    def reject_constant(_token):
        raise BoundedJSONError("Nonfinite JSON constant.")

    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=pairs,
                           parse_float=number, parse_int=integer, parse_constant=reject_constant)
    except (UnicodeError, RecursionError, json.JSONDecodeError, ValueError) as exc:
        if isinstance(exc, BoundedJSONError):
            raise
        raise BoundedJSONError("Malformed or excessively nested JSON.") from exc
    stack, count = [(value, 0)], 0
    while stack:
        item, depth = stack.pop()
        count += 1
        if count > max_nodes or depth > max_depth:
            raise BoundedJSONError("JSON tree exceeds the depth or item limit.")
        if isinstance(item, str) and len(item) > max_string:
            raise BoundedJSONError("JSON string exceeds the length limit.")
        if isinstance(item, dict):
            for key, child in item.items():
                if len(key) > 256:
                    raise BoundedJSONError("JSON key exceeds the length limit.")
                stack.append((child, depth + 1))
        elif isinstance(item, list):
            stack.extend((child, depth + 1) for child in item)
    return value


def load_bounded_json(path: Path, **limits):
    limit = limits.get("max_bytes", MAX_SPEC_BYTES)
    with Path(path).open("rb") as handle:
        raw = handle.read(limit + 1)
    return loads_bounded_json(raw, **limits)


def _text(value, maximum=8192, *, optional=False):
    return (optional and value is None) or (isinstance(value, str) and bool(value.strip()) and len(value) <= maximum and "\x00" not in value)


def _rectangle(value):
    return (isinstance(value, list) and len(value) == 4 and all(finite(v) for v in value)
            and min(value) >= 0 and max(value) <= MAX_PIXEL_COORDINATE
            and value[2] > value[0] and value[3] > value[1])


def validate_spec(spec: dict, base_dir: Path) -> list[dict]:
    """Every JSON type yields validation gaps, never a metadata type exception."""
    errors = []
    if not isinstance(spec, dict):
        return [gap("invalid_spec", "A JSON object is required.")]

    def unknown(obj, allowed, label, sid=None):
        extras = sorted(set(obj) - allowed)
        if extras:
            errors.append(gap("unexpected_field", f"Unsupported {label} field(s): {', '.join(extras[:8])}.", sid))

    unknown(spec, {"schema_version", "vessel_id", "input_mode", "units", "source", "station_reference",
                   "symmetry", "symmetry_evidence", "end_closure", "sections", "constraints", "components",
                   "table_value_units", "table_surface", "scope_note", "historical_date"}, "specification")
    if FORBIDDEN.intersection(spec):
        errors.append(gap("geometry_in_input", "Drawing input must not contain target geometry or evaluation answers."))
    if spec.get("schema_version") != "1.0":
        errors.append(gap("schema_version", "schema_version must be 1.0."))
    mode = spec.get("input_mode", "calibrated_section_curves")
    # Offset-table OCR (Tesseract) was removed; table reading by the vision
    # model is not implemented yet. Archived OCR runs still verify (run_record).
    if not isinstance(mode, str) or mode != "calibrated_section_curves":
        errors.append(gap("unsupported_input_mode", "Only calibrated_section_curves is supported."))
    for name in ("vessel_id", "table_surface", "scope_note", "historical_date"):
        if name in spec and not _text(spec[name], 256 if name == "vessel_id" else 8192):
            errors.append(gap("invalid_metadata", f"{name} must be a bounded nonempty string."))
    if spec.get("units") != "m":
        errors.append(gap("missing_units", "Declare units='m'; pixels are not physical dimensions."))
    if spec.get("symmetry") != "port_starboard":
        errors.append(gap("symmetry_unresolved", "This parser requires an explicit port_starboard symmetry assumption."))
    if not _text(spec.get("symmetry_evidence")):
        errors.append(gap("symmetry_evidence_missing", "Record bounded text describing symmetry evidence or its explicit assumption."))
    if spec.get("end_closure") != "flat_at_terminal_stations":
        errors.append(gap("end_closure_unresolved", "Declare flat_at_terminal_stations; no unsupported bow/stern is invented."))
    for name in ("source", "station_reference"):
        if name == "station_reference" and name not in spec:
            continue
        source = spec.get(name)
        kind = "source_missing" if name == "source" else "station_reference_missing"
        if not isinstance(source, dict):
            errors.append(gap(kind, f"{name} must be an object identifying an input drawing."))
            continue
        unknown(source, {"file", "sha256", "url", "license", "page_index", "render_dpi", "roi_px",
                         "description", "original_scan_sha256", "upload_original_sha256", "transformation"}, name)
        filename = source.get("file")
        if not _text(filename, 4096):
            errors.append(gap(kind, f"{name}.file must be a bounded nonempty path."))
        else:
            try:
                if not (base_dir / filename).is_file():
                    errors.append(gap(kind, f"The declared {name} file does not exist."))
            except (OSError, ValueError):
                errors.append(gap(kind, f"The declared {name} path is not readable."))
        for field in ("sha256", "original_scan_sha256", "upload_original_sha256"):
            if field in source and (not isinstance(source[field], str) or not SHA256.fullmatch(source[field])):
                errors.append(gap("invalid_source_hash", f"{name}.{field} must be a lowercase SHA-256 digest."))
        for field in ("url", "license", "description", "transformation"):
            if field in source and not _text(source[field], optional=field in ("url", "license")):
                errors.append(gap("invalid_source_metadata", f"{name}.{field} must be bounded text."))
        if "page_index" in source and (type(source["page_index"]) is not int or not 0 <= source["page_index"] <= 9999):
            errors.append(gap("invalid_page_index", f"{name}.page_index must be an integer in [0, 9999]."))
        if "render_dpi" in source and (not finite(source["render_dpi"]) or not 1 <= source["render_dpi"] <= 600):
            errors.append(gap("invalid_render_dpi", f"{name}.render_dpi must be finite and within [1, 600]."))
        if "roi_px" in source and not _rectangle(source["roi_px"]):
            errors.append(gap("invalid_source_region", f"{name}.roi_px must be a bounded positive pixel rectangle."))
    sections = spec.get("sections")
    if not isinstance(sections, list) or len(sections) < 3:
        errors.append(gap("insufficient_sections", "At least three calibrated sections are required."))
        sections = []
    elif len(sections) > MAX_SECTIONS:
        errors.append(gap("input_limit", f"Maximum {MAX_SECTIONS} section views per run."))
        sections = []
    ids, stations, total_cells = set(), set(), 0
    for i, sec in enumerate(sections):
        if not isinstance(sec, dict):
            errors.append(gap("invalid_section", f"Section {i} is not an object."))
            continue
        sid = sec.get("id") if _text(sec.get("id"), 128) else f"section-{i}"
        if not _text(sec.get("id"), 128):
            errors.append(gap("invalid_section_identity", "Section id must be nonempty bounded text.", sid))
        elif sid in ids:
            errors.append(gap("duplicate_identity", "Section identifiers must be unique.", sid))
        ids.add(sid)
        unknown(sec, {"id", "x_m", "roi_px", "calibration", "z_min_m", "z_max_m", "evidence", "sample_count",
                      "cells", "contour_selection"}, "section", sid)
        if FORBIDDEN.intersection(sec):
            errors.append(gap("geometry_in_input", "Drawing input must not contain target geometry or evaluation answers.", sid))
        x = sec.get("x_m")
        if not finite(x):
            errors.append(gap("missing_station", "A finite station coordinate x_m is required.", sid))
        elif abs(x) > MAX_LOCAL_METRES:
            errors.append(gap("station_out_of_range", "Use a local vessel datum with |x_m| <= 10,000,000 m.", sid))
        elif float(x) in stations:
            errors.append(gap("conflicting_stations", "Two sections claim the same station coordinate.", sid))
        else:
            stations.add(float(x))
        roi = sec.get("roi_px")
        if not _rectangle(roi):
            errors.append(gap("invalid_view_region", "Declare a bounded positive drawing view region in pixels.", sid))
        if not _text(sec.get("evidence")):
            errors.append(gap("calibration_evidence_missing", "Describe the source of the view or table location and scale.", sid))
        if "sample_count" in sec and (type(sec["sample_count"]) is not int or not 17 <= sec["sample_count"] <= 513):
            errors.append(gap("invalid_sample_count", "sample_count must be an integer in [17, 513].", sid))
        if "contour_selection" in sec:
            selection = sec["contour_selection"]
            if not isinstance(selection, dict):
                errors.append(gap("invalid_contour_selection", "contour_selection must be an explicit pixel corridor object.", sid))
            else:
                unknown(selection, {"anchors_px", "half_width_px"}, "contour selection", sid)
                anchors, half_width = selection.get("anchors_px"), selection.get("half_width_px")
                okay = (isinstance(anchors, list) and 2 <= len(anchors) <= 64 and finite(half_width)
                        and 0 < half_width <= 128 and _rectangle(roi))
                if okay:
                    okay = half_width <= roi[2] - roi[0]
                    ys = set()
                    for point in anchors:
                        if not (isinstance(point, list) and len(point) == 2 and all(finite(v) for v in point)
                                and roi[0] <= point[0] <= roi[2] and roi[1] <= point[1] <= roi[3]
                                and point[1] not in ys):
                            okay = False
                            break
                        ys.add(point[1])
                if not okay:
                    errors.append(gap("invalid_contour_selection", "Selection requires 2..64 finite ROI anchors at distinct rows and half_width_px in (0,128].", sid))
        if "cells" in sec:
            errors.append(gap("unexpected_field", "Table cells are not supported.", sid))
        cal = sec.get("calibration")
        if not isinstance(cal, dict):
            errors.append(gap("invalid_calibration", "calibration must be an object.", sid))
            cal = {}
        unknown(cal, {"pixels_per_metre", "centerline_px", "baseline_px"}, "calibration", sid)
        ppm = cal.get("pixels_per_metre")
        if not finite(ppm) or ppm <= 0 or ppm > 1_000_000_000:
            errors.append(gap("missing_scale", "A bounded positive pixels_per_metre calibration is required.", sid))
        elif _rectangle(roi):
            extent_px = max(abs(roi[2] - roi[0]), abs(roi[3] - roi[1]))
            center = cal.get("centerline_px")
            if finite(center):
                extent_px = max(extent_px, abs(roi[0] - center), abs(roi[2] - center))
            if not finite(extent_px) or ppm < extent_px / MAX_LOCAL_METRES:
                errors.append(gap("physical_extent_out_of_range", "Calibration implies an extent beyond 10,000,000 m.", sid))
        for name in ("centerline_px", "baseline_px"):
            if not finite(cal.get(name)):
                errors.append(gap("missing_datum", f"Calibration requires finite {name}.", sid))
        zlo, zhi = sec.get("z_min_m"), sec.get("z_max_m")
        if not finite(zlo) or not finite(zhi) or zhi <= zlo:
            errors.append(gap("vertical_range_unresolved", "Declare a finite measured vertical interval z_min_m < z_max_m.", sid))
        elif max(abs(zlo), abs(zhi)) > MAX_LOCAL_METRES:
            errors.append(gap("vertical_range_out_of_range", "Use local elevations within +/-10,000,000 m before CAD.", sid))
    if total_cells > MAX_TOTAL_CELLS:
        errors.append(gap("input_limit", f"Maximum {MAX_TOTAL_CELLS} measurement cells per run."))
    constraints = spec.get("constraints", {})
    if not isinstance(constraints, dict):
        errors.append(gap("invalid_constraints", "constraints must be an object."))
    else:
        unknown(constraints, {"length_m", "beam_m", "depth_m", "relative_tolerance"}, "constraint")
        for name, value in constraints.items():
            if name in ("length_m", "beam_m", "depth_m") and (not finite(value) or not 0 < value <= 2 * MAX_LOCAL_METRES):
                errors.append(gap("invalid_constraint", f"{name} must be positive, finite and bounded."))
            if name == "relative_tolerance" and (not finite(value) or not 0 < value <= 0.2):
                errors.append(gap("invalid_constraint_tolerance", "relative_tolerance must be a finite number in (0, 0.2]."))
    if "components" in spec and (not isinstance(spec["components"], list) or spec["components"]):
        errors.append(gap("unsupported_components", "This version reconstructs the hull envelope only; components must be an empty list."))
    return errors
