"""Trace calibrated half-section drawings without consulting reference geometry.

The input metadata supplies a human-selected panel and coordinate calibration.
The only shape observations come from the image.  Quality scores are heuristics,
not probabilities and not engineering approval.  This parser intentionally
abstains on uncalibrated, blank, fragmented, or ambiguous panels.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any
import math

import numpy as np
from PIL import Image
from scipy import ndimage


class DrawingError(ValueError):
    def __init__(self, kind: str, message: str):
        super().__init__(message)
        self.kind = kind


def _gap(section_id: str | None, kind: str, message: str) -> dict[str, Any]:
    return {"id": f"{section_id or 'source'}-{kind}", "kind": kind,
            "severity": "blocking", "section_id": section_id, "message": message}


def _finite_number(value: Any, name: str) -> float:
    if isinstance(value, bool):
        raise DrawingError("invalid_calibration", f"{name} must be a finite number.")
    try:
        result = float(value)
    except (TypeError, ValueError):
        raise DrawingError("invalid_calibration", f"{name} must be a finite number.") from None
    if not math.isfinite(result):
        raise DrawingError("invalid_calibration", f"{name} must be a finite number.")
    return result


def _read_image(source: dict[str, Any], base_dir: Path) -> tuple[np.ndarray, dict[str, Any]]:
    file = source.get("file")
    if not isinstance(file, str) or not file.strip():
        raise DrawingError("missing_source", "source.file must identify a drawing image or PDF.")
    path = (base_dir / file).resolve()
    if not path.is_file():
        raise DrawingError("missing_source", f"Source file does not exist: {file}")
    if path.suffix.lower() == ".pdf":
        import fitz
        dpi = _finite_number(source.get("render_dpi", 144), "source.render_dpi")
        page_number = source.get("page_index", 0)
        if not isinstance(page_number, int) or isinstance(page_number, bool) or page_number < 0:
            raise DrawingError("invalid_source", "source.page_index must be a nonnegative integer.")
        if not 36 <= dpi <= 600:
            raise DrawingError("invalid_source", "PDF render_dpi must be between 36 and 600.")
        try:
            with fitz.open(path) as document:
                if page_number >= len(document):
                    raise DrawingError("invalid_source", "PDF page_index is outside the document.")
                pix = document[page_number].get_pixmap(matrix=fitz.Matrix(dpi / 72, dpi / 72), alpha=False)
                array = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
                if pix.n == 1:
                    array = np.repeat(array, 3, axis=2)
                array = array[:, :, :3].copy()
        except DrawingError:
            raise
        except Exception as exc:
            raise DrawingError("unreadable_source", f"Could not render PDF: {exc}") from exc
        return array, {"input_form": "pdf_rendered_to_raster", "page_index": page_number,
                       "render_dpi": dpi, "coordinate_space": "rendered PDF pixels"}
    if path.suffix.lower() in {".dxf", ".dwg", ".step", ".stp", ".stl"}:
        raise DrawingError("unsupported_source", "This adapter accepts raster drawings or rendered PDF pages. Export the calibrated DXF/DWG view to an image; reference 3D geometry is never an inference input.")
    try:
        with Image.open(path) as im:
            # Composite transparent drawings onto paper; do not rotate EXIF pixels,
            # since the declared coordinate system must remain unchanged.
            im = im.convert("RGBA")
            paper = Image.new("RGBA", im.size, (255, 255, 255, 255))
            paper.alpha_composite(im)
            array = np.asarray(paper.convert("RGB")).copy()
    except Exception as exc:
        raise DrawingError("unreadable_source", f"Could not read drawing image: {exc}") from exc
    return array, {"input_form": "raster", "coordinate_space": "original image pixels"}


def _otsu(values: np.ndarray) -> float:
    hist = np.bincount(np.rint(np.clip(values, 0, 255)).astype(np.uint8).ravel(), minlength=256).astype(float)
    probability = hist / max(1.0, hist.sum())
    weight = np.cumsum(probability)
    mean = np.cumsum(probability * np.arange(256))
    variance = (mean[-1] * weight - mean) ** 2 / np.maximum(weight * (1 - weight), 1e-12)
    return float(np.argmax(variance))


def _foreground(crop: np.ndarray) -> tuple[np.ndarray, np.ndarray, dict[str, Any]]:
    rgb = crop.astype(float)
    luminance = rgb @ np.array([0.2126, 0.7152, 0.0722])
    background = float(np.percentile(luminance, 98))
    chroma = rgb.max(axis=2) - rgb.min(axis=2)
    # Saturated ink remains visible even when its luminance is close to paper.
    ink = np.maximum(background - luminance, 0.8 * chroma)
    # Use the same quantization for estimating and applying the threshold.
    # Comparing floating luminance to a truncated histogram bin can otherwise
    # retain an entire light grid that was intended to be below the cutoff.
    quantized = np.rint(np.clip(ink, 0, 255)).astype(np.uint8)
    coarse_threshold = max(35.0, _otsu(quantized))
    coarse = quantized > coarse_threshold
    threshold = coarse_threshold
    contrast_span = 0.0
    if np.any(coarse):
        foreground_values = quantized[coarse]
        contrast_span = float(np.percentile(foreground_values, 95) - np.percentile(foreground_values, 5))
        # Drafting strokes can form a distinct, darker population than grid
        # lines. Separate those populations without assuming a hull shape.
        # A uniformly faint contour is kept; similarly dark competing curves
        # still reach the ambiguity check. This is a photometric heuristic,
        # not semantic recognition of which engineering line is the hull.
        if contrast_span >= 60.0:
            threshold = max(threshold, _otsu(foreground_values))
    raw = quantized > threshold
    labels, count = ndimage.label(raw, structure=np.ones((3, 3), dtype=int))
    sizes = np.bincount(labels.ravel())
    min_component = max(6, round(crop.shape[0] * 0.012))
    keep = sizes >= min_component
    keep[0] = False
    mask = keep[labels]
    return mask, ink, {"ink_threshold": threshold, "coarse_ink_threshold": coarse_threshold,
                        "foreground_contrast_span": contrast_span,
                        "ink_filter_version": "quantized_two_tier_contrast_v2",
                        "paper_luminance": background,
                        "raw_ink_fraction": float(raw.mean()), "retained_ink_fraction": float(mask.mean()),
                        "component_filter_min_pixels": min_component,
                        "raw_component_count": int(count)}


def _runs(row: np.ndarray) -> list[tuple[int, int]]:
    indices = np.flatnonzero(row)
    if not len(indices):
        return []
    cuts = np.flatnonzero(np.diff(indices) > 1) + 1
    groups = np.split(indices, cuts)
    return [(int(group[0]), int(group[-1]) + 1) for group in groups]


def _trace(mask: np.ndarray, ink: np.ndarray, centre_local: float) -> tuple[np.ndarray, np.ndarray, dict[str, Any]]:
    """Viterbi trace through pixel-run centres; no parametric hull prior."""
    h, w = mask.shape
    rows: list[int] = []
    candidates: list[np.ndarray] = []
    strengths: list[np.ndarray] = []
    run_widths: list[np.ndarray] = []
    # Explicit centreline is the only axis whose identity we know.  Ignore it
    # as a competitor, but allow it as the hull's measured keel endpoint.
    centre_band = max(2.0, w * 0.008)
    broad_row_limit = max(12, round(w * 0.16))
    for row_index in range(h):
        runs = _runs(mask[row_index])
        # Baselines and horizontal rulers cross a large part of the panel.
        # They supply no local half-breadth observation on that row.
        runs = [(a, b) for a, b in runs if b - a <= broad_row_limit]
        centres = []
        evidence_strength = []
        widths = []
        for start, stop in runs:
            pixels = np.arange(start, stop)
            weights = np.maximum(1.0, ink[row_index, start:stop])
            x = float(np.average(pixels, weights=weights))
            centres.append(x)
            evidence_strength.append(float(np.mean(weights)) / 255.0)
            widths.append(stop - start)
        if centres:
            rows.append(row_index)
            candidates.append(np.asarray(centres))
            strengths.append(np.asarray(evidence_strength))
            run_widths.append(np.asarray(widths))
    if len(rows) < max(12, h * 0.5):
        raise DrawingError("missing_curve", "Too few drawing rows contain a supported section curve.")
    # Reward source contrast and only a mild outer-contour preference.  The
    # latter resolves an explicitly calibrated centreline versus the hull.
    costs = -strengths[0] - 0.25 * np.clip((candidates[0] - centre_local) / max(1, w), 0, 1)
    back = [np.full(len(candidates[0]), -1, dtype=int)]
    for index in range(1, len(rows)):
        dy = rows[index] - rows[index - 1]
        delta = np.abs(candidates[index][None, :] - candidates[index - 1][:, None])
        # Robust continuity cost tolerates a curved bilge without preferring
        # short disconnected text/noise fragments over a continuous contour.
        transition = 0.035 * delta / max(1.0, math.sqrt(dy))
        transition += 0.003 * np.maximum(0, delta - 0.12 * w) ** 2 / dy
        total = costs[:, None] + transition
        best = np.argmin(total, axis=0)
        emission = -strengths[index] - 0.25 * np.clip((candidates[index] - centre_local) / max(1, w), 0, 1)
        costs = total[best, np.arange(len(best))] + emission
        back.append(best)
    selected = np.zeros(len(rows), dtype=int)
    selected[-1] = int(np.argmin(costs))
    for index in range(len(rows) - 1, 0, -1):
        selected[index - 1] = back[index][selected[index]]
    x = np.asarray([candidates[i][selected[i]] for i in range(len(rows))])
    row_array = np.asarray(rows, dtype=float)
    widths = np.asarray([run_widths[i][selected[i]] for i in range(len(rows))])
    signal = np.asarray([strengths[i][selected[i]] for i in range(len(rows))])
    # Count a second sustained path away from the explicitly known centreline
    # and from the selected stroke.  Overlaid body plans require review.
    alternatives = np.zeros_like(mask, dtype=bool)
    separation = max(5.0, 2.5 * float(np.median(widths)))
    for index, row in enumerate(rows):
        for candidate in candidates[index]:
            if abs(candidate - x[index]) > separation and candidate > centre_local + centre_band:
                col = int(round(candidate))
                alternatives[row, max(0, col - 1):min(w, col + 2)] = True
    linked = ndimage.binary_dilation(alternatives, structure=np.ones((5, 5), dtype=bool))
    lab, nlab = ndimage.label(linked)
    alternative_span = 0
    for segment in ndimage.find_objects(lab):
        if segment:
            alternative_span = max(alternative_span, segment[0].stop - segment[0].start)
    max_gap = max(int(rows[0]), int(h - 1 - rows[-1]), int(np.max(np.diff(rows) - 1)) if len(rows) > 1 else h)
    gaps = np.diff(row_array)
    slopes = np.diff(x) / np.maximum(1, gaps)
    # Long vertical fragments are direct evidence of structure rather than a
    # random sequence of speckles.  Axis pixels do not count toward this test.
    support_mask = mask.copy()
    axis_end = min(w, max(0, int(math.floor(centre_local + centre_band))))
    support_mask[:, :axis_end] = False
    labs, _ = ndimage.label(support_mask, structure=np.ones((3, 3), dtype=int))
    long_components: set[int] = set()
    for label_index, segment in enumerate(ndimage.find_objects(labs), 1):
        if segment and segment[0].stop - segment[0].start >= max(8, h * 0.08):
            long_components.add(label_index)
    long_support = []
    for row, point in zip(rows, x):
        a, b = max(0, int(point) - 2), min(w, int(point) + 3)
        long_support.append(any(int(label) in long_components for label in labs[row, a:b]) or point <= centre_local + centre_band and row > h * .8)
    diagnostics = {"observed_row_count": len(rows), "trace_row_count": h,
                   "max_missing_run_px": max_gap, "alternative_contour_span_fraction": float(alternative_span / h),
                   "median_stroke_width_px": float(np.median(widths)),
                   "mean_trace_contrast": float(np.mean(signal)),
                   "long_component_support_fraction": float(np.mean(long_support)),
                   "maximum_step_px_per_row": float(np.max(np.abs(slopes))) if len(slopes) else 0.0,
                   "interpolated_row_count": h - len(rows)}
    return row_array, x, diagnostics


def _extract_one(image: np.ndarray, section: dict[str, Any], source_file: str, input_details: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    section_id = str(section.get("id", "unnamed"))
    x_m = _finite_number(section.get("x_m"), "x_m")
    calibration = section.get("calibration")
    if not isinstance(calibration, dict) or "pixels_per_metre" not in calibration:
        raise DrawingError("missing_scale", "A positive pixels_per_metre plus centreline/baseline calibration is required; image scale is not guessed.")
    ppm = _finite_number(calibration.get("pixels_per_metre"), "pixels_per_metre")
    if ppm <= 0:
        raise DrawingError("invalid_calibration", "pixels_per_metre must be positive.")
    centre = _finite_number(calibration.get("centerline_px"), "centerline_px")
    baseline = _finite_number(calibration.get("baseline_px"), "baseline_px")
    z_min = _finite_number(section.get("z_min_m"), "z_min_m")
    z_max = _finite_number(section.get("z_max_m"), "z_max_m")
    if z_max <= z_min:
        raise DrawingError("invalid_calibration", "z_max_m must be greater than z_min_m.")
    roi = section.get("roi_px")
    if not isinstance(roi, (list, tuple)) or len(roi) != 4:
        raise DrawingError("missing_view", "Each section requires one explicit four-coordinate roi_px.")
    coords = [_finite_number(v, "roi_px") for v in roi]
    if any(value != int(value) for value in coords):
        raise DrawingError("invalid_view", "ROI bounds must be integer pixel coordinates.")
    left, top, right, bottom = map(int, coords)
    height, width = image.shape[:2]
    if not (0 <= left < right <= width and 0 <= top < bottom <= height):
        raise DrawingError("invalid_view", "Section ROI falls outside the drawing or has no area.")
    if not left <= centre < right:
        raise DrawingError("invalid_calibration", "The declared centreline lies outside this panel.")
    py_top = baseline - z_max * ppm
    py_bottom = baseline - z_min * ppm
    if py_top < top - .51 or py_bottom > bottom - .49:
        raise DrawingError("invalid_calibration", "The specified vertical range extends outside the selected ROI.")
    trace_top = max(top, int(round(py_top)))
    trace_bottom = min(bottom - 1, int(round(py_bottom)))
    trace_left = max(left, int(math.floor(centre)))
    if trace_bottom - trace_top < 32 or right - trace_left < 8:
        raise DrawingError("insufficient_resolution", "At least 33 vertical pixels and 8 horizontal pixels are required to trace this section.")
    crop = image[trace_top:trace_bottom + 1, trace_left:right]
    mask, ink, diagnostic = _foreground(crop)
    if diagnostic["retained_ink_fraction"] < .0005:
        raise DrawingError("missing_curve", "The selected panel contains no sufficiently supported curve ink.")
    if diagnostic["raw_ink_fraction"] > .45:
        raise DrawingError("ambiguous_curve", "The panel is too densely marked to identify a single contour reliably.")
    rows, xs, trace_diag = _trace(mask, ink, centre - trace_left)
    diagnostic.update(trace_diag)
    coverage = len(rows) / mask.shape[0]
    allowed_gap = max(3, int(math.ceil(mask.shape[0] * .025)))
    if diagnostic["max_missing_run_px"] > allowed_gap:
        raise DrawingError("missing_curve_segment", f"A curve segment is missing for {diagnostic['max_missing_run_px']} pixels (limit {allowed_gap}); long gaps are not filled.")
    if coverage < .9:
        raise DrawingError("missing_curve_segment", f"Only {coverage:.1%} of calibrated rows have source evidence; at least 90% is required.")
    if diagnostic["alternative_contour_span_fraction"] > .5:
        raise DrawingError("ambiguous_curve", "A second sustained contour is present in this panel. Separate the views or select one contour before reconstruction.")
    if diagnostic["long_component_support_fraction"] < .65:
        raise DrawingError("unreliable_curve", "Most trace points lack sustained connected ink support; the panel may contain noise or fragmented marks.")
    sample_count = section.get("sample_count", 129)
    if not isinstance(sample_count, int) or isinstance(sample_count, bool) or not 65 <= sample_count <= 1025:
        raise DrawingError("invalid_view", "sample_count must be an integer between 65 and 1025.")
    z_values = np.linspace(z_min, z_max, sample_count)
    sampled_rows = baseline - z_values * ppm - trace_top
    pixel_x = np.interp(sampled_rows, rows, xs) + trace_left
    y_values = (pixel_x - centre) / ppm
    if float(y_values.min()) < -0.51 / ppm:
        raise DrawingError("invalid_curve", "Measured contour crosses the declared starboard half-section boundary.")
    y_values = np.maximum(0, y_values)
    warnings = ["View ROI, centreline, baseline, longitudinal position, and scale are human-supplied calibration.",
                "Confidence is a heuristic image quality score, not a correctness probability or engineering approval."]
    if diagnostic["interpolated_row_count"]:
        warnings.append(f"Interpolated {diagnostic['interpolated_row_count']} unsupported rows across short gaps; longest gap {diagnostic['max_missing_run_px']} pixels.")
    warnings.append("Output samples interpolate the observed stroke centre; no hull-family shape prior or reference geometry is used.")
    contrast = min(1.0, diagnostic["mean_trace_contrast"] / .7)
    confidence = float(np.clip(coverage * (.65 + .2 * contrast + .15 * diagnostic["long_component_support_fraction"]) * (1 - .25 * diagnostic["alternative_contour_span_fraction"]), 0, 1))
    diagnostic["measurement_uncertainty_m"] = float(max(.75, diagnostic["median_stroke_width_px"] / 2) / ppm)
    diagnostic["coverage"] = coverage
    diagnostic["sample_count"] = sample_count
    result = {"id": section_id, "x_m": x_m,
              "points_yz_m": [[float(y), float(z)] for y, z in zip(y_values, z_values)],
              "confidence": confidence, "coverage": coverage,
              "evidence": {"roi_px": list(roi), "calibration": dict(calibration),
                           "source_file": source_file, "input_form": input_details["input_form"],
                           "human_assistance": section.get("evidence", "Human-supplied panel and coordinate calibration"),
                           "pixel_trace_bounds": [trace_left, trace_top, right, trace_bottom + 1],
                           "measurement_uncertainty_m": diagnostic["measurement_uncertainty_m"],
                           "uncertainty_basis": "Half detected stroke width or 0.75 pixel; excludes calibration error, scan distortion, and as-built uncertainty"},
              "warnings": warnings}
    return result, diagnostic


def extract_sections(spec: dict, base_dir: Path) -> dict:
    """Measure supported starboard half-sections and return structured gaps.

    ``base_dir`` is the directory containing the drawing specification.  PDF
    pixel coordinates refer to the selected page rendered at source.render_dpi
    (144 by default).  This function does not use any reference or ground-truth
    files, does not infer missing dimensions, and does not manufacture CAD.
    """
    output: dict[str, Any] = {"sections": [], "gaps": [], "diagnostics": {}, "method": "raster_curve_tracking"}
    if not isinstance(spec, dict):
        output["gaps"].append(_gap(None, "invalid_specification", "The drawing specification must be an object."))
        return output
    if spec.get("units") != "m":
        output["gaps"].append(_gap(None, "unsupported_units", "Specification units must be explicit metres ('m')."))
        return output
    source = spec.get("source")
    if not isinstance(source, dict):
        output["gaps"].append(_gap(None, "missing_source", "A drawing source object is required."))
        return output
    try:
        image, input_details = _read_image(source, Path(base_dir))
    except DrawingError as exc:
        output["gaps"].append(_gap(None, exc.kind, str(exc)))
        return output
    output["diagnostics"] = {"source": {**input_details, "image_width_px": int(image.shape[1]), "image_height_px": int(image.shape[0])},
                             "sections": {}, "quality_score_type": "heuristic_not_probability",
                             "shape_inputs": "source image pixels only; explicitly supplied coordinate calibration"}
    sections = spec.get("sections")
    if not isinstance(sections, list) or not sections:
        output["gaps"].append(_gap(None, "missing_view", "At least one calibrated half-section panel is required."))
        return output
    seen: set[str] = set()
    for index, section in enumerate(sections):
        if not isinstance(section, dict):
            output["gaps"].append(_gap(f"section-{index}", "invalid_view", "Section must be an object."))
            continue
        section_id = str(section.get("id", f"section-{index}"))
        if not section.get("id") or section_id in seen:
            output["gaps"].append(_gap(section_id, "invalid_view", "Each section requires a unique nonempty id."))
            continue
        seen.add(section_id)
        try:
            result, diagnostic = _extract_one(image, section, source["file"], input_details)
            output["sections"].append(result)
            output["diagnostics"]["sections"][section_id] = diagnostic
        except DrawingError as exc:
            output["gaps"].append(_gap(section_id, exc.kind, str(exc)))
            output["diagnostics"]["sections"][section_id] = {"status": "abstained", "reason": exc.kind}
        except (ValueError, TypeError, IndexError, OverflowError) as exc:
            output["gaps"].append(_gap(section_id, "invalid_view", f"Cannot interpret section metadata: {exc}"))
    return output
