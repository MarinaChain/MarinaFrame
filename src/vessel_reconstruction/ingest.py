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
    def __init__(self, kind: str, message: str, diagnostics: dict[str, Any] | None = None):
        super().__init__(message)
        self.kind = kind
        self.diagnostics = diagnostics or {}


MAX_ROW_CANDIDATES = 64
MAX_TRACE_CANDIDATES = 50_000


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
    from .resources import ResourceLimitError, inspect_source
    try:
        bounded = inspect_source(path, source, role="source")
    except ResourceLimitError as exc:
        raise DrawingError(exc.kind, str(exc)) from exc
    if path.suffix.lower() == ".pdf":
        import fitz
        dpi = _finite_number(bounded.get("render_dpi", source.get("render_dpi", 144)), "source.render_dpi")
        page_number = bounded.get("page_index", source.get("page_index", 0))
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
    primary = quantized > threshold
    # Darker ink cannot establish the engineering identity of a stroke. Keep
    # lower contrast candidates for tracing and ambiguity checks, even when
    # two-tier photometric separation would discard them. A robust paper-noise
    # estimate suppresses isolated scan noise; thresholds remain recorded and
    # do not imply that every possible faint feature has been detected.
    median_ink = float(np.median(quantized))
    mad_ink = float(np.median(np.abs(quantized.astype(float) - median_ink)))
    candidate_threshold = max(12.0, min(35.0, median_ink + 4 * mad_ink))
    raw = quantized > candidate_threshold
    labels, count = ndimage.label(raw, structure=np.ones((3, 3), dtype=int))
    sizes = np.bincount(labels.ravel())
    min_component = max(6, round(crop.shape[0] * 0.012))
    keep = sizes >= min_component
    keep[0] = False
    mask = keep[labels]
    return mask, ink, {"ink_threshold": threshold, "coarse_ink_threshold": coarse_threshold,
                        "candidate_ink_threshold": candidate_threshold,
                        "foreground_contrast_span": contrast_span,
                        "ink_filter_version": "cross_contrast_candidates_v3",
                        "paper_luminance": background,
                        "high_contrast_ink_fraction": float(primary.mean()),
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
    candidate_count = 0
    for row_index in range(h):
        runs = _runs(mask[row_index])
        # Baselines and horizontal rulers cross a large part of the panel.
        # They supply no local half-breadth observation on that row.
        runs = [(a, b) for a, b in runs if b - a <= broad_row_limit]
        candidate_count += len(runs)
        if len(runs) > MAX_ROW_CANDIDATES or candidate_count > MAX_TRACE_CANDIDATES:
            raise DrawingError("resource_limit", "Contour candidate complexity exceeds the bounded tracing budget; select a smaller panel.")
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


def _selection_mask(section: dict, shape: tuple[int, int], origin: tuple[int, int]) -> tuple[np.ndarray | None, dict | None]:
    selection = section.get("contour_selection")
    if selection is None:
        return None, None
    if not isinstance(selection, dict) or set(selection) != {"anchors_px", "half_width_px"}:
        raise DrawingError("invalid_contour_selection", "contour_selection requires only anchors_px and half_width_px.")
    anchors = selection["anchors_px"]
    if not isinstance(anchors, list) or not 2 <= len(anchors) <= 64:
        raise DrawingError("invalid_contour_selection", "A contour selection requires 2..64 source-pixel anchors.")
    try:
        if any(not isinstance(p, list) or len(p) != 2 or
               any(isinstance(v, bool) or not isinstance(v, (int, float)) for v in p) for p in anchors):
            raise ValueError
        values = np.asarray(anchors, dtype=float)
        half_width = selection["half_width_px"]
        if (isinstance(half_width, bool) or not isinstance(half_width, (int, float))
                or not math.isfinite(half_width) or not 0 < half_width <= min(128, section["roi_px"][2] - section["roi_px"][0])
                or not np.isfinite(values).all()):
            raise ValueError
    except (ValueError, TypeError, OverflowError):
        raise DrawingError("invalid_contour_selection", "Contour anchors and width must be finite bounded source-pixel coordinates.") from None
    left, top, right, bottom = section["roi_px"]
    if (np.any(values[:, 0] < left) or np.any(values[:, 0] >= right)
            or np.any(values[:, 1] < top) or np.any(values[:, 1] >= bottom)):
        raise DrawingError("invalid_contour_selection", "Contour selection anchors must lie inside the declared panel.")
    values = values[np.argsort(values[:, 1])]
    if np.any(np.diff(values[:, 1]) <= 0):
        raise DrawingError("invalid_contour_selection", "Contour selection anchors require distinct pixel elevations.")
    h, w = shape
    ox, oy = origin
    if values[0, 1] > oy or values[-1, 1] < oy + h - 1:
        raise DrawingError("invalid_contour_selection", "Contour selection anchors must span the complete calibrated vertical range; selection is not extrapolated.")
    centers = np.interp(np.arange(h) + oy, values[:, 1], values[:, 0]) - ox
    eligible = np.abs(np.arange(w)[None, :] - centers[:, None]) <= float(half_width)
    return eligible, {"anchors_px": values.tolist(), "half_width_px": float(half_width),
                      "meaning": "Explicit caller-supplied source-pixel corridor; geometry is still measured from retained image ink"}


def _contrasting_subruns(ink_row: np.ndarray, first: int, last: int) -> tuple[list[tuple[int, int]], float | None]:
    """Retain observed contrast islands inside a broad horizontal source run.

    A pale ruler can share a row with a darker curved stroke. Deleting the
    complete connected run loses that stroke; clipping the ruler to an input
    corridor invents it. This separation happens on the original source run,
    before any corridor. It is a photometric hypothesis, not contour identity.
    Uniform broad ink supplies no such separation and remains excluded.
    """
    values = np.rint(np.clip(ink_row[first:last], 0, 255)).astype(np.uint8)
    if not len(values) or int(values.max()) - int(values.min()) < 24:
        return [], None
    threshold = max(float(values.min()) + 12., _otsu(values))
    return [(a + first, b + first) for a, b in _runs(values > threshold)], threshold


def _adjacent_localized_ink(localized: np.ndarray, row: int, first: int, last: int) -> bool:
    """True when ink outside broad runs touches [first, last) in the row above or below."""
    left, right = max(0, first - 1), min(localized.shape[1], last + 1)
    neighbours = [r for r in (row - 1, row + 1) if 0 <= r < localized.shape[0]]
    return any(bool(localized[r, left:right].any()) for r in neighbours)


def _eligible_trace_mask(mask: np.ndarray, selection: np.ndarray | None,
                         ink: np.ndarray | None = None) -> tuple[np.ndarray, dict]:
    """Reject broad source rulers before clipping to a selection corridor.

    Clipping a full-width baseline to a narrow corridor otherwise manufactures
    a short apparent stroke whose centre is the corridor centre, not an image
    observation. In particular it can invent breadth below a zero-width keel.
    Horizontal-run classification must therefore use the original panel mask.
    When source contrast separates a shorter stroke from a broad ruler, retain
    that observed subset before clipping, but only when it continues into an
    adjacent row outside the ruler. Sustained alternatives still come
    from the unmodified source mask and require explicit identity resolution.
    """
    eligible = mask.copy()
    broad_limit = max(12, round(mask.shape[1] * .16))
    broad_runs = [(row, first, last) for row in range(mask.shape[0])
                  for first, last in _runs(mask[row]) if last - first > broad_limit]
    for row, first, last in broad_runs:
        eligible[row, first:last] = False
    runs_removed = len(broad_runs)
    rows_removed = {row for row, _, _ in broad_runs}
    islands = []
    for row, first, last in (broad_runs if ink is not None else []):
        subruns, threshold = _contrasting_subruns(ink[row], first, last)
        # A nearly full-width high-contrast ruler is not a
        # localized observation merely because its edges vary.
        islands.extend((row, a, b, threshold) for a, b in subruns if b - a < .72 * mask.shape[1])
    # A stroke that crosses, leaves or runs along a ruler is connected, row by
    # row, to ink outside the ruler. Support starts at ink outside every broad
    # run and grows through accepted islands in adjacent rows. An island never
    # reached is tone variation inside the ruler itself (for example the
    # aliased edge of a scanned 1-bit line), not a separate observation.
    support = eligible.copy()
    pending = islands
    accepted = []
    while pending:
        reached = [_adjacent_localized_ink(support, row, a, b) for row, a, b, _ in pending]
        if not any(reached):
            break
        for island, supported in zip(pending, reached):
            if supported:
                row, a, b, _ = island
                support[row, a:b] = mask[row, a:b]
                accepted.append(island)
        pending = [island for island, supported in zip(pending, reached) if not supported]
    unsupported_count = len(pending)
    retained_runs = []
    retained_count = len(accepted)
    for row, a, b, threshold in sorted(accepted, key=lambda island: island[:3]):
        eligible[row, a:b] = mask[row, a:b]
        if len(retained_runs) < 1025:
            retained_runs.append({"row": row, "span": [a, b], "ink_threshold": threshold})
    if selection is not None:
        eligible &= selection
    return eligible, {"horizontal_source_runs_excluded_before_selection": runs_removed,
                      "horizontal_source_rows_with_exclusions": len(rows_removed),
                      "retained_contrast_subruns": retained_runs,
                      "retained_contrast_subrun_count": retained_count,
                      "retained_contrast_subrun_details_omitted": retained_count > len(retained_runs),
                      "unsupported_contrast_subrun_count": unsupported_count,
                      "selection_trace_policy": "Broad horizontal strokes are classified in the original panel; only contrast-separated source ink may be retained before corridor clipping. Contrast does not certify contour identity."}


def _source_endpoint_hypothesis(mask: np.ndarray, ink: np.ndarray, rows: np.ndarray,
                                xs: np.ndarray, centre_local: float, stroke_width: float) -> dict | None:
    """Offer a source-supported lower-endpoint interpretation for review.

    Row centroids are poor endpoint locations for a nearly horizontal curve.
    An alternative may use the calibrated centreline contact only if actual
    connected ink reaches it and the adjacent trace approaches it. A uniform
    broad ruler, disconnected mark or straight horizontal-bottom/vertical-side
    corner does not meet this contract. The original trace is never replaced
    here; the domain catalog exposes both hypotheses as separate candidate IDs.
    """
    h, w = mask.shape
    if h < 16 or len(rows) < 6:
        return None
    boundary = h - 1
    if boundary - rows[-1] > 3:
        return None
    old_endpoint = float(np.interp(boundary, rows, xs))
    if old_endpoint - centre_local < max(3., 1.5 * stroke_width):
        return None
    nearby = (rows >= boundary - 7) & (rows < boundary)
    near_rows, near_xs = rows[nearby], xs[nearby]
    if len(near_rows) < 3 or np.ptp(near_xs) < max(3., 2 * stroke_width):
        return None  # A flat-bottom corner is not a single-valued curve endpoint.
    if float(np.mean(np.diff(near_xs) <= max(1., stroke_width))) < .75:
        return None
    centre_pixel = int(round(centre_local))
    if not 0 <= centre_pixel < w or abs(centre_pixel - centre_local) > .51:
        return None
    broad_limit = max(12, round(w * .16))
    contacts = []
    for a, b in _runs(mask[boundary]):
        if b - a > broad_limit:
            runs, threshold = _contrasting_subruns(ink[boundary], a, b)
        else:
            runs, threshold = [(a, b)], None
        for first, last in runs:
            if (first <= centre_pixel < last and first >= centre_pixel - 1
                    and max(6., 3 * stroke_width) <= last - first < .72 * w):
                contacts.append((first, last, threshold))
    if len(contacts) != 1:
        return None
    first, last, threshold = contacts[0]
    # For an already isolated run, use only ink at the contact's contrast.
    # The witness must connect to the neighboring trace through actual pixels.
    if threshold is None:
        threshold = max(0., float(np.min(ink[boundary, first:last])) - 1.)
    start_row = max(0, boundary - 8)
    local = mask[start_row:] & (ink[start_row:] > threshold)
    labels, _ = ndimage.label(local, structure=np.ones((3, 3), dtype=int))
    contact = int(labels[boundary - start_row, centre_pixel])
    if not contact:
        return None
    witnesses = []
    for row, x in zip(near_rows, near_xs):
        rr, cc = int(row) - start_row, int(round(x))
        if rr >= 0 and np.any(labels[rr, max(0, cc - 2):min(w, cc + 3)] == contact):
            witnesses.append([float(x), float(row)])
    if len(witnesses) < 2:
        return None
    new_rows, new_xs = rows.copy(), xs.copy()
    if rows[-1] == boundary:
        new_xs[-1] = centre_local
    else:
        new_rows = np.append(new_rows, float(boundary))
        new_xs = np.append(new_xs, centre_local)
    return {"rows": new_rows, "xs": new_xs,
            "evidence": {"version": "source_endpoint_contact_v1", "boundary": "lower",
                "contact_local_px": [float(centre_local), float(boundary)],
                "source_run_local_px": [first, last - 1],
                "ink_threshold": float(threshold), "connected_trace_witnesses_local_px": witnesses,
                "original_row_centroid_local_px": [old_endpoint, float(boundary)],
                "interpretation": "Connected source ink reaches the calibrated centreline; a row centroid may mislocalize the stroke endpoint.",
                "uncertainty": "A source-supported endpoint hypothesis, not subpixel truth or proof of material-boundary semantics; retain the original centroid alternative.",
                "human_semantic_review_required": True, "engineering_approved": False}}


def _candidate_evidence(mask: np.ndarray, ink: np.ndarray, rows: np.ndarray, xs: np.ndarray,
                        centre_local: float, origin: tuple[int, int], stroke_width: float,
                        selection: np.ndarray | None) -> dict:
    """Retain reviewable evidence for competing strokes across contrast bands.

    Full source pixels remain the evidence of record. Stored points are an
    explicitly bounded review sample of each sustained competing component.
    A selected corridor can exclude candidates, but cannot erase their record.
    """
    h, w = mask.shape
    proposed = np.interp(np.arange(h), rows, xs)
    alternatives = np.zeros_like(mask, dtype=bool)
    points: list[tuple[int, int, float, bool]] = []
    separation = max(2.0, 1.25 * stroke_width)
    centre_band = max(2.0, w * .008)
    broad_limit = max(12, round(w * .16))
    for row in range(h):
        runs = [(a, b) for a, b in _runs(mask[row]) if b - a <= broad_limit]
        if len(runs) > MAX_ROW_CANDIDATES:
            raise DrawingError("resource_limit", "Contour candidate complexity exceeds the bounded evidence budget.")
        for a, b in runs:
            weights = np.maximum(1.0, ink[row, a:b])
            col = int(round(float(np.average(np.arange(a, b), weights=weights))))
            if abs(col - proposed[row]) <= separation or col <= centre_local + centre_band:
                continue
            active = selection is None or bool(selection[row, col])
            points.append((row, col, float(np.mean(weights)), active))
            alternatives[row, col] = True
            if len(points) > MAX_TRACE_CANDIDATES:
                raise DrawingError("resource_limit", "Contour candidate complexity exceeds the bounded evidence budget.")
    linked = ndimage.binary_dilation(alternatives, structure=np.ones((5, 5), dtype=bool))
    labels, count = ndimage.label(linked)
    grouped: dict[int, list[tuple[int, int, float, bool]]] = {}
    for point in points:
        grouped.setdefault(int(labels[point[0], point[1]]), []).append(point)
    candidates = []
    maximum_active_span = 0
    ox, oy = origin
    minimum_rows = max(12, int(math.ceil(.12 * h)))
    minimum_span = max(16, int(math.ceil(.15 * h)))
    for label, observed in sorted(grouped.items()):
        observed_rows = sorted({p[0] for p in observed})
        span = observed_rows[-1] - observed_rows[0] + 1
        if len(observed_rows) < minimum_rows or span < minimum_span or len(observed_rows) / span < .5:
            continue
        active_rows = sorted({p[0] for p in observed if p[3]})
        active_span = active_rows[-1] - active_rows[0] + 1 if active_rows else 0
        unresolved = (len(active_rows) >= minimum_rows and active_span >= minimum_span
                      and len(active_rows) / max(1, active_span) >= .5)
        if unresolved:
            maximum_active_span = max(maximum_active_span, active_span)
        indices = np.unique(np.linspace(0, len(observed) - 1, min(129, len(observed))).astype(int))
        candidates.append({
            "candidate_id": f"competing-{label}",
            "status": "unresolved" if unresolved else "excluded_by_explicit_pixel_selection",
            "bounds_px": [min(p[1] for p in observed) + ox, observed_rows[0] + oy,
                          max(p[1] for p in observed) + ox + 1, observed_rows[-1] + oy + 1],
            "observed_row_count": len(observed_rows), "observed_point_count": len(observed),
            "vertical_span_fraction": float(span / h),
            "eligible_observed_row_count": len(active_rows),
            "contrast_ink_median": float(np.median([p[2] for p in observed])),
            "contrast_ink_range": [min(p[2] for p in observed), max(p[2] for p in observed)],
            "source_points_px": [[observed[i][1] + ox, observed[i][0] + oy] for i in indices],
            "point_sampling": "at most 129 evenly indexed observed pixel-run centres; complete evidence is in the immutable source image",
        })
        if len(candidates) > 64:
            raise DrawingError("resource_limit", "Too many sustained candidate contours for bounded review; split the panel.")
    selected_indices = np.unique(np.linspace(0, len(rows) - 1, min(257, len(rows))).astype(int))
    return {"candidate_evidence": candidates, "competing_candidate_count": len(candidates),
            "unresolved_candidate_count": sum(c["status"] == "unresolved" for c in candidates),
            "alternative_contour_span_fraction": float(maximum_active_span / h),
            "candidate_identity_policy": "Contrast does not identify engineering semantics; sustained alternatives require explicit source-pixel selection or abstention",
            "candidate_detection_limits": {"minimum_vertical_span_fraction": .15, "minimum_observed_row_fraction": .12,
                                            "minimum_component_coverage": .5, "maximum_review_points_per_candidate": 129},
            "proposed_trace_px": [[float(xs[i] + ox), float(rows[i] + oy)] for i in selected_indices],
            "proposed_trace_sampling": "at most 257 evenly indexed observed rows, for review only"}


def _run_containing(mask_row: np.ndarray, x: float) -> tuple[int, int] | None:
    """Return the half-open source run that contains the observed position."""
    column = int(round(x))
    for start, stop in _runs(mask_row):
        if start <= column < stop:
            return start, stop
    return None


def _lower_boundary_run_end(source_mask: np.ndarray, rows: np.ndarray,
                            xs: np.ndarray) -> tuple[float, dict] | None:
    """Bound an unobserved lower-boundary ordinate by touching source ink.

    When the lowest calibrated row has no trace observation, sampling holds the
    lowest observed centroid constant down to the boundary. If a source run on
    the boundary row touches the run of that lowest observation, the stroke
    continues on the boundary row and that position has no ink. The boundary
    ordinate is then the touching end of the boundary run: the nearest position
    that the boundary-row ink supports. This keeps the centroid interpretation;
    it does not claim centreline contact (see _source_endpoint_hypothesis).
    """
    boundary = source_mask.shape[0] - 1
    if not len(rows) or rows[-1] != boundary - 1:
        return None
    observed = _run_containing(source_mask[boundary - 1], xs[-1])
    if observed is None:
        return None
    observed_first, observed_last = observed[0], observed[1] - 1
    touching = []
    for first, stop in _runs(source_mask[boundary]):
        last = stop - 1
        if abs(observed_first - last) <= 1 and last < observed_last:
            touching.append(float(last))  # Stroke descends inward to the boundary.
        elif abs(first - observed_last) <= 1 and first > observed_first:
            touching.append(float(first))  # Stroke descends outward to the boundary.
    if len(touching) != 1:
        return None
    return touching[0], {"method": "touching_boundary_run_end_v1",
                         "boundary_row_local_px": boundary,
                         "boundary_ordinate_local_px": touching[0],
                         "lowest_centroid_local_px": float(xs[-1]),
                         "scope": "The unobserved boundary ordinate is bounded by the end of connected boundary-row ink; not centreline contact and not subpixel truth."}


def _bounded_source_samples(rows: np.ndarray, xs: np.ndarray, *, baseline: float,
                            trace_top: int, ppm: float, z_min: float, z_max: float,
                            minimum_samples: int, centre_local: float) -> tuple[np.ndarray, np.ndarray, dict]:
    """Retain source-row features with a declared ordinate error bound.

    Uniform output heights alone can miss a narrow observed chine before CAD
    ever sees it. Treat that grid as a minimum density and insert source knots
    until the complete observed piecewise-linear trace is within 0.25 pixel.
    This bounds resampling loss only, not image or semantic accuracy. The
    original 1025-point resource limit remains a refusal, never a smoothing cap.
    """
    tolerance_px = .25
    source_z = (baseline - (rows[::-1] + trace_top)) / ppm
    source_x = xs[::-1]
    uniform = np.linspace(z_min, z_max, minimum_samples)
    interior = source_z[(source_z > z_min) & (source_z < z_max)]
    knots = np.unique(np.concatenate((uniform, interior)))
    values = np.interp(knots, source_z, source_x)
    mandatory = set(np.searchsorted(knots, uniform).tolist())
    # These are source ordinate transitions, not invented minimum breadths.
    # Keep every exact source zero/positive transition if present.
    for index in np.flatnonzero((values[:-1] <= centre_local) != (values[1:] <= centre_local)):
        mandatory.update((int(index), int(index + 1)))
    selected = set(mandatory)
    if len(selected) > 1025:
        raise DrawingError("resource_limit", "Preserving source zero-width transitions exceeds 1025 output points; split the calibrated view or review its complexity.")
    ordered = sorted(mandatory)
    pending = list(zip(ordered[:-1], ordered[1:]))
    while pending:
        first, last = pending.pop()
        if last <= first + 1:
            continue
        prediction = values[first] + (values[last] - values[first]) * (
            (knots[first + 1:last] - knots[first]) / (knots[last] - knots[first]))
        errors = np.abs(values[first + 1:last] - prediction)
        offset = int(np.argmax(errors))
        if errors[offset] > tolerance_px:
            middle = first + 1 + offset
            selected.add(middle)
            if len(selected) > 1025:
                raise DrawingError("resource_limit", "Preserving the observed source trace within 0.25 pixel exceeds 1025 output points; split the calibrated view or review its complexity.")
            pending.extend(((first, middle), (middle, last)))
    indices = np.asarray(sorted(selected), dtype=int)
    maximum = float(np.max(np.abs(np.interp(knots, knots[indices], values[indices]) - values)))
    if maximum > tolerance_px + 1e-9:
        raise DrawingError("invalid_curve", "Source resampling could not satisfy its declared pixel error bound.")
    return knots[indices], values[indices], {
        "method": "bounded_observed_row_knots_v1", "minimum_requested_samples": minimum_samples,
        "output_point_count": len(indices), "observed_row_count": len(rows),
        "maximum_allowed_ordinate_deviation_px": tolerance_px,
        "maximum_ordinate_deviation_px": maximum,
        "point_limit": 1025,
        "scope": "Interpolation loss relative to the measured row-centroid trace only; excludes endpoint identity, source raster error, calibration, gaps, and semantics."}


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
    selection, selection_record = _selection_mask(section, mask.shape, (trace_left, trace_top))
    diagnostic.update({"pixel_trace_bounds": [trace_left, trace_top, right, trace_bottom + 1],
                       "contour_selection": selection_record,
                       "quality_score_type": "heuristic_not_probability",
                       "identity_status": "unresolved"})
    if diagnostic["retained_ink_fraction"] < .0005:
        raise DrawingError("missing_curve", "The selected panel contains no sufficiently supported curve ink.", diagnostic)
    if diagnostic["raw_ink_fraction"] > .45:
        raise DrawingError("ambiguous_curve", "The panel is too densely marked to identify a single contour reliably.", diagnostic)
    eligible_mask, eligibility_diagnostic = _eligible_trace_mask(mask, selection, ink)
    diagnostic.update(eligibility_diagnostic)
    try:
        rows, xs, trace_diag = _trace(eligible_mask, ink, centre - trace_left)
    except DrawingError as exc:
        exc.diagnostics = {**diagnostic, **exc.diagnostics}
        raise
    diagnostic.update(trace_diag)
    diagnostic.update(_candidate_evidence(mask, ink, rows, xs, centre - trace_left,
                                          (trace_left, trace_top), diagnostic["median_stroke_width_px"], selection))
    coverage = len(rows) / mask.shape[0]
    allowed_gap = max(3, int(math.ceil(mask.shape[0] * .025)))
    if diagnostic["max_missing_run_px"] > allowed_gap:
        raise DrawingError("missing_curve_segment", f"A curve segment is missing for {diagnostic['max_missing_run_px']} pixels (limit {allowed_gap}); long gaps are not filled.", diagnostic)
    if coverage < .9:
        raise DrawingError("missing_curve_segment", f"Only {coverage:.1%} of calibrated rows have source evidence; at least 90% is required.", diagnostic)
    if diagnostic["unresolved_candidate_count"]:
        raise DrawingError("ambiguous_curve", "Multiple sustained source strokes remain plausible across contrast bands. Supply an explicit source-pixel contour selection or separate the views; darkness is not contour identity.", diagnostic)
    if diagnostic["long_component_support_fraction"] < .65:
        raise DrawingError("unreliable_curve", "Most trace points lack sustained connected ink support; the panel may contain noise or fragmented marks.", diagnostic)
    sample_count = section.get("sample_count", 129)
    if not isinstance(sample_count, int) or isinstance(sample_count, bool) or not 65 <= sample_count <= 1025:
        raise DrawingError("invalid_view", "sample_count must be an integer between 65 and 1025.")
    # Boundary ink is classified in the unclipped source: a selection corridor
    # must not hide the boundary-row run or create one.
    unclipped_mask, _ = _eligible_trace_mask(mask, None, ink)
    boundary_end = _lower_boundary_run_end(unclipped_mask, rows, xs)
    diagnostic["lower_boundary_run_end"] = boundary_end[1] if boundary_end else None
    if boundary_end is not None:
        rows = np.append(rows, float(mask.shape[0] - 1))
        xs = np.append(xs, boundary_end[0])
    z_values, measured_x, sampling = _bounded_source_samples(rows, xs, baseline=baseline,
        trace_top=trace_top, ppm=ppm, z_min=z_min, z_max=z_max, minimum_samples=sample_count,
        centre_local=centre - trace_left)
    pixel_x = measured_x + trace_left
    y_values = (pixel_x - centre) / ppm
    if float(y_values.min()) < -0.51 / ppm:
        raise DrawingError("invalid_curve", "Measured contour crosses the declared starboard half-section boundary.")
    y_values = np.maximum(0, y_values)
    warnings = ["View ROI, centreline, baseline, longitudinal position, and scale are caller-supplied calibration; metadata does not authenticate who selected it.",
                "Confidence is a heuristic image quality score, not a correctness probability or engineering approval."]
    if diagnostic["interpolated_row_count"]:
        warnings.append(f"Interpolated {diagnostic['interpolated_row_count']} unsupported rows across short gaps; longest gap {diagnostic['max_missing_run_px']} pixels.")
    warnings.append("Output samples retain the observed row trace within 0.25 pixel interpolation loss; sample_count is a minimum density. No hull-family shape prior or reference geometry is used.")
    if selection_record is not None:
        warnings.append("Contour identity is constrained by an explicit caller-supplied source-pixel selection; excluded candidate strokes remain in diagnostics.")
    else:
        warnings.append("One sustained candidate was detected in the declared view; this is not proof of semantic identity or absence of undetectably faint features.")
    contrast = min(1.0, diagnostic["mean_trace_contrast"] / .7)
    confidence = float(np.clip(coverage * (.65 + .2 * contrast + .15 * diagnostic["long_component_support_fraction"]) * (1 - .25 * diagnostic["alternative_contour_span_fraction"]), 0, 1))
    diagnostic["measurement_uncertainty_m"] = float(max(.75, diagnostic["median_stroke_width_px"] / 2) / ppm)
    diagnostic["coverage"] = coverage
    diagnostic["sample_count"] = len(z_values)
    diagnostic["source_sampling"] = sampling
    diagnostic["identity_status"] = "explicit_supplied_pixel_selection" if selection_record is not None else "single_detected_candidate_in_declared_view"
    result = {"id": section_id, "x_m": x_m,
              "points_yz_m": [[float(y), float(z)] for y, z in zip(y_values, z_values)],
              "confidence": confidence, "coverage": coverage,
              "evidence": {"roi_px": list(roi), "calibration": dict(calibration),
                           "source_file": source_file, "input_form": input_details["input_form"],
                           "human_assistance": section.get("evidence", "Caller-supplied panel and coordinate calibration"),
                           "contour_selection": selection_record,
                           "identity_status": diagnostic["identity_status"],
                           "competing_candidate_count": diagnostic["competing_candidate_count"],
                           "pixel_trace_bounds": [trace_left, trace_top, right, trace_bottom + 1],
                           "measurement_uncertainty_m": diagnostic["measurement_uncertainty_m"],
                           "source_sampling": sampling,
                           "uncertainty_basis": "Half detected stroke width or 0.75 pixel; excludes calibration error, scan distortion, and as-built uncertainty"},
              "warnings": warnings}
    return result, diagnostic


# A multi-piece station keeps all its observed samples within the per-section
# sample bound of the run record and the audit contract.
MAX_PIECE_SAMPLES = 1025
PIECE_READING = "explicit_piece_corridors_to_outline_regions_v1"


def _trace_piece(image, section, selection, low, high, source_file, input_details):
    """Trace one curve of a piece in its own corridor and height interval."""
    piece_view = {key: value for key, value in section.items() if key not in ("pieces", "contour_selection")}
    piece_view.update(z_min_m=low, z_max_m=high, contour_selection=selection)
    result, diagnostic = _extract_one(image, piece_view, source_file, input_details)
    points = np.asarray(result["points_yz_m"], dtype=float)
    return points[np.argsort(points[:, 1], kind="stable")], result, diagnostic


def extract_pieces(image: np.ndarray, section: dict[str, Any], source_file: str,
                   input_details: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Read a multi-piece station into outline rings and one-interval-per-height regions.

    Each declared piece is traced with the same engine as a single section, in
    its own explicit corridor and height interval; ``section_regions``
    decomposes the closed rings into regions for ``geometry.build_region_hull``.
    Overlapping pieces are refused, not merged.
    """
    from .errors import GeometryError
    from .section_regions import decompose_outline, piece_ring

    section_id = str(section.get("id", "unnamed"))
    pieces = section.get("pieces")
    if not isinstance(pieces, list) or not 1 <= len(pieces) <= 8:
        raise DrawingError("invalid_pieces", "pieces must list 1..8 declared piece corridors.")
    records, rings, diagnostics = [], [], []
    for index, piece in enumerate(pieces):
        try:
            low, high = _finite_number(piece.get("z_min_m"), "z_min_m"), _finite_number(piece.get("z_max_m"), "z_max_m")
            outer, outer_result, outer_diag = _trace_piece(image, section, piece.get("contour_selection"), low, high,
                                                           source_file, input_details)
            inner = inner_result = None
            if "inner_selection" in piece:
                inner, inner_result, inner_diag = _trace_piece(image, section, piece["inner_selection"], low, high,
                                                               source_file, input_details)
                diagnostics.append({"piece": index, "outer": outer_diag, "inner": inner_diag})
            else:
                diagnostics.append({"piece": index, "outer": outer_diag})
            rings.append(piece_ring(outer, inner, section_id=section_id))
        except (DrawingError, GeometryError, AttributeError) as exc:
            if isinstance(exc, DrawingError):
                kind = exc.kind
            else:
                kind = "invalid_outline" if isinstance(exc, GeometryError) else "invalid_pieces"
            raise DrawingError(kind, f"Piece {index}: {exc}", {"pieces": diagnostics,
                               **(exc.diagnostics if isinstance(exc, DrawingError) else {})}) from None
        record = {"z_range_m": [low, high], "points_yz_m": outer.tolist(),
                  "evidence": {"contour_selection": outer_result["evidence"]["contour_selection"],
                               "measurement_uncertainty_m": outer_result["evidence"]["measurement_uncertainty_m"]}}
        if inner is not None:
            record["inner_points_yz_m"] = inner.tolist()
            record["evidence"]["inner_selection"] = inner_result["evidence"]["contour_selection"]
            record["evidence"]["measurement_uncertainty_m"] = max(record["evidence"]["measurement_uncertainty_m"],
                                                                  inner_result["evidence"]["measurement_uncertainty_m"])
        records.append((record, outer_result, inner_result))
    samples = sum(len(r["points_yz_m"]) + len(r.get("inner_points_yz_m", [])) for r, _, _ in records)
    if samples > MAX_PIECE_SAMPLES:
        raise DrawingError("input_limit", f"The pieces give {samples} samples; at most {MAX_PIECE_SAMPLES} per station. Lower sample_count.")
    try:
        regions = decompose_outline([ring.tolist() for ring in rings], section_id=section_id)
    except GeometryError as exc:
        raise DrawingError("invalid_outline", str(exc), {"pieces": diagnostics}) from None
    results = [result for _, outer_result, inner_result in records for result in (outer_result, inner_result) if result]
    first = results[0]
    uncertainty = max(r["evidence"]["measurement_uncertainty_m"] for r in results)
    coverage = min(r["coverage"] for r in results)
    result = {"id": section_id, "x_m": first["x_m"],
              "pieces": [record for record, _, _ in records],
              "outline_rings_yz_m": [ring.tolist() for ring in rings],
              "regions": [{"kind": region["kind"], "rows_m": region["rows_m"]} for region in regions],
              "confidence": min(r["confidence"] for r in results), "coverage": coverage,
              "evidence": {"roi_px": list(section["roi_px"]), "calibration": dict(section["calibration"]),
                           "source_file": source_file, "input_form": input_details["input_form"],
                           "human_assistance": section.get("evidence", "Caller-supplied panel and coordinate calibration"),
                           "reading": PIECE_READING, "piece_count": len(records),
                           "region_count": len(regions), "region_kinds": [region["kind"] for region in regions],
                           "identity_status": "explicit_supplied_piece_selections",
                           "measurement_uncertainty_m": uncertainty,
                           "uncertainty_basis": "Largest piece uncertainty: half detected stroke width or 0.75 pixel; excludes calibration error, scan distortion, and as-built uncertainty"},
              "warnings": ["Each piece is traced in an explicit caller-supplied corridor and height interval; "
                           "which drawn curves form the station is caller evidence, not proof of contour identity.",
                           "A piece without an inner curve is closed horizontally to the centreline at its ends; "
                           "an offset piece holds material only between its inner and outer curves."]}
    return result, {"pieces": diagnostics, "coverage": coverage, "measurement_uncertainty_m": uncertainty,
                    "identity_status": "explicit_supplied_piece_selections", "region_count": len(regions)}


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
            extract = extract_pieces if "pieces" in section else _extract_one
            result, diagnostic = extract(image, section, source["file"], input_details)
            output["sections"].append(result)
            output["diagnostics"]["sections"][section_id] = diagnostic
        except DrawingError as exc:
            output["gaps"].append(_gap(section_id, exc.kind, str(exc)))
            output["diagnostics"]["sections"][section_id] = {**exc.diagnostics, "status": "abstained", "reason": exc.kind}
        except (ValueError, TypeError, IndexError, OverflowError) as exc:
            output["gaps"].append(_gap(section_id, "invalid_view", f"Cannot interpret section metadata: {exc}"))
    return output
