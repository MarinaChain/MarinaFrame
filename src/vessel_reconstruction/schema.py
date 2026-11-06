"""Input validation, with explicit units and no hidden geometry targets."""
from __future__ import annotations

import math
from pathlib import Path

# Bound local physical coordinates before they reach the geometric kernel.
# This is deliberately far above any vessel size; it is a numeric/resource
# boundary, not an assumption about the shape being reconstructed.
MAX_LOCAL_METRES = 10_000_000.0


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


def validate_spec(spec: dict, base_dir: Path) -> list[dict]:
    errors = []
    if not isinstance(spec, dict):
        return [gap("invalid_spec", "A JSON object is required.")]
    if spec.get("schema_version") != "1.0":
        errors.append(gap("schema_version", "schema_version must be 1.0."))
    mode = spec.get("input_mode", "calibrated_section_curves")
    if mode not in {"calibrated_section_curves", "offset_table_ocr"}:
        errors.append(gap("unsupported_input_mode", "Choose calibrated_section_curves or offset_table_ocr."))
    if mode == "offset_table_ocr" and spec.get("table_value_units") != "feet_inches_eighths":
        errors.append(gap("table_units_unresolved", "Declare table_value_units='feet_inches_eighths' for this OCR adapter."))
    if spec.get("units") != "m":
        errors.append(gap("missing_units", "Declare units='m'; pixels are not physical dimensions."))
    if spec.get("symmetry") != "port_starboard":
        errors.append(gap("symmetry_unresolved", "This parser requires an explicit port_starboard symmetry assumption."))
    if not spec.get("symmetry_evidence"):
        errors.append(gap("symmetry_evidence_missing", "Record evidence for symmetry or explicitly declare it an assumption."))
    if spec.get("end_closure") != "flat_at_terminal_stations":
        errors.append(gap("end_closure_unresolved", "Declare flat_at_terminal_stations; the pipeline does not invent a bow/stern beyond observed stations."))
    source = spec.get("source", {})
    source_name = source.get("file") if isinstance(source, dict) else None
    if not isinstance(source_name, str) or not source_name:
        errors.append(gap("source_missing", "source.file must identify an input drawing."))
    else:
        source_path = (base_dir / source_name).resolve()
        if not source_path.is_file():
            errors.append(gap("source_missing", "The declared input drawing does not exist."))
    sections = spec.get("sections")
    if not isinstance(sections, list) or len(sections) < 3:
        errors.append(gap("insufficient_sections", "At least three calibrated sections are required."))
        return errors
    if len(sections) > 300:
        errors.append(gap("input_limit", "Maximum 300 section views per run."))
        return errors
    ids, stations = set(), set()
    for i, sec in enumerate(sections):
        if not isinstance(sec, dict):
            errors.append(gap("invalid_section", f"Section {i} is not an object."))
            continue
        sid = str(sec.get("id", i))
        if sid in ids:
            errors.append(gap("duplicate_identity", "Section identifiers must be unique.", sid))
        ids.add(sid)
        # Ground truth and offsets have no legal route through this input schema.
        forbidden = {"points", "points_yz_m", "offsets", "ground_truth", "reference_mesh", "hull_parameters"}
        if forbidden.intersection(sec) or forbidden.intersection(spec):
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
        if not isinstance(roi, list) or len(roi) != 4 or not all(finite(v) for v in roi):
            errors.append(gap("missing_view_region", "Declare the drawing view region in pixels.", sid))
        elif roi[2] <= roi[0] or roi[3] <= roi[1] or min(roi) < 0:
            errors.append(gap("invalid_view_region", "The view region must have positive area and nonnegative coordinates.", sid))
        if mode == "offset_table_ocr":
            cells = sec.get("cells")
            if not isinstance(cells, list) or len(cells) < 5:
                errors.append(gap("insufficient_table_rows", "At least five source measurement cells per station are required.", sid))
            else:
                zs = set()
                for cell in cells:
                    if not isinstance(cell, dict):
                        errors.append(gap("invalid_table_cell", "A cell must declare its source ROI and measured elevation.", sid))
                        continue
                    z = cell.get("z_m")
                    if not finite(z) or abs(z) > MAX_LOCAL_METRES or z in zs:
                        errors.append(gap("invalid_table_elevation", "Cell elevations must be finite, within the local coordinate limit, and unique per station.", sid))
                    else:
                        zs.add(z)
                    cr = cell.get("roi_px")
                    if not isinstance(cr, list) or len(cr) != 4 or not all(finite(v) for v in cr) or cr[2] <= cr[0] or cr[3] <= cr[1] or min(cr) < 0:
                        errors.append(gap("invalid_cell_region", "Each cell requires a valid source-pixel rectangle.", sid))
                    if any(k in cell for k in ("value", "y_m", "half_breadth_m", "ground_truth")):
                        errors.append(gap("geometry_in_input", "Numeric half-breadths must be read from source pixels, not supplied as hidden answers.", sid))
            if not sec.get("evidence"):
                errors.append(gap("calibration_evidence_missing", "Describe how the station and table-cell regions were identified.", sid))
            continue
        cal = sec.get("calibration", {})
        if not isinstance(cal, dict):
            cal = {}
        if not finite(cal.get("pixels_per_metre")) or cal.get("pixels_per_metre", 0) <= 0:
            errors.append(gap("missing_scale", "A positive pixels_per_metre calibration is required; scale will not be guessed.", sid))
        elif isinstance(roi, list) and len(roi) == 4 and all(finite(v) for v in roi):
            ppm = cal["pixels_per_metre"]
            # Compare before dividing so tiny scales cannot overflow.
            extent_px = max(abs(roi[2] - roi[0]), abs(roi[3] - roi[1]))
            center = cal.get("centerline_px")
            if finite(center):
                extent_px = max(extent_px, abs(roi[0] - center), abs(roi[2] - center))
            if not finite(extent_px) or ppm < extent_px / MAX_LOCAL_METRES:
                errors.append(gap("physical_extent_out_of_range", "Calibration implies an extent beyond 10,000,000 m; use a local vessel datum and a physical scale.", sid))
        for name in ("centerline_px", "baseline_px"):
            if not finite(cal.get(name)):
                errors.append(gap("missing_datum", f"Calibration requires {name}.", sid))
        zlo, zhi = sec.get("z_min_m"), sec.get("z_max_m")
        if not finite(zlo) or not finite(zhi) or zhi <= zlo:
            errors.append(gap("vertical_range_unresolved", "Declare a finite measured vertical interval z_min_m < z_max_m.", sid))
        elif max(abs(zlo), abs(zhi)) > MAX_LOCAL_METRES:
            errors.append(gap("vertical_range_out_of_range", "Use local elevations within +/-10,000,000 m before CAD construction.", sid))
        if not sec.get("evidence"):
            errors.append(gap("calibration_evidence_missing", "Describe the source of the view location and scale.", sid))
    constraints = spec.get("constraints", {})
    if not isinstance(constraints, dict):
        errors.append(gap("invalid_constraints", "constraints must be an object."))
    else:
        for name, value in constraints.items():
            if name in {"length_m", "beam_m", "depth_m"} and (not finite(value) or value <= 0):
                errors.append(gap("invalid_constraint", f"{name} must be positive and finite."))
            if name == "relative_tolerance" and (not finite(value) or not 0 < value <= 0.2):
                errors.append(gap("invalid_constraint_tolerance", "relative_tolerance must be a finite number in (0, 0.2], not a boolean or numeric string."))
    if spec.get("components"):
        errors.append(gap("unsupported_components", "This version reconstructs the hull envelope only. Internal components require separate evidenced geometry."))
    reference = spec.get("station_reference")
    if reference is not None:
        if not isinstance(reference, dict) or not isinstance(reference.get("file"), str) or not (base_dir / reference.get("file", "")).is_file():
            errors.append(gap("station_reference_missing", "The declared station coordinate reference file does not exist."))
    return errors

