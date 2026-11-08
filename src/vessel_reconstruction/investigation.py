"""Model investigation tools: views, corridor traces, station assignment, sheet setup.

The live model may look at any part of the captured sheet at any zoom and ask
for a trace inside a corridor that it draws on a view. It never supplies a
line: every proposed line is traced from source ink by the engine's own
tracer and is accepted only when the engine re-reads it inside a tight
corridor (``_extract_one``). Station assignments and sheet setups are claims
that deterministic verifiers check here. A verified assignment becomes an open
draft guess of kind ``model_choice``; only a person confirms it, and the Rust
controller refuses review readiness while it is open.

The functions take the domain state and the captured spec and return plain
data; ``DomainTools`` owns locking, persistence and artifacts.
"""
from __future__ import annotations

import io
import math
from pathlib import Path

import numpy as np

from .provenance import digest_object

# Largest model view: the provider worker accepts at most 2048 px per side and
# 1 Mpx, and the controller attaches at most this many PNG bytes per image.
MAX_VIEW_SIDE_PX = 1024
MAX_VIEW_PIXELS = 1_000_000
MAX_VIEW_BYTES = 190_000
# A view may enlarge a small region by at most this factor (nearest neighbour).
MAX_ZOOM = 4.0
# DeepSeek through OpenCode Go reads text from about this glyph height (view
# pixels) up; it downscales images over 2048 px a side (docs/CONTINUATION_STATUS.md),
# so views stay at MAX_VIEW_SIDE_PX and say how small sheet text may be.
READABLE_TEXT_VIEW_PX = 16
# Spacing of the coordinate ticks drawn on the edges of every view.
TICK_SPACING_VIEW_PX = 100
# Engine thresholds repeated for a corridor trace (ingest._extract_one).
MIN_ROW_COVERAGE = 0.9
GAP_FRACTION = 0.025
MIN_LONG_COMPONENT_SUPPORT = 0.65
# A traced line must cover at least this share of its section's calibrated
# height, so a short fragment (a numeral, a tick) cannot become a station.
MIN_VERTICAL_SHARE = 0.25
# Tight corridor of an accepted trace: the same half width as inspection candidates.
SNAPPED_HALF_WIDTH_PX = 2.75
# Two traces closer than this (source px) on most shared rows are the same ink.
SAME_INK_DISTANCE_PX = 2.0
SAME_INK_ROW_SHARE = 0.8
# Sheet setup: a detected grid spacing must match the claimed scale within this
# relative error, and a claimed datum line must lie this close to detected ink.
GRID_SCALE_TOLERANCE = 0.02
DATUM_TOLERANCE_PX = 3.0
DECLARED_SCALE_TOLERANCE = 0.01
# A long straight line covers at least this share of the region side.
LONG_LINE_SHARE = 0.5
# Ink is at least this many grey levels darker than the paper (98th percentile).
INK_CONTRAST = 30


class VerificationError(ValueError):
    """A model proposal that a deterministic check refused; the reason goes back to the model."""

    def __init__(self, code: str, message: str, evidence: dict | None = None):
        super().__init__(message)
        self.code = code
        self.evidence = evidence or {}


# ------------------------------------------------------------------ views

def clip_region(region, width: int, height: int) -> list[int]:
    left, top, right, bottom = (int(v) for v in region)
    clipped = [max(0, left), max(0, top), min(width, right), min(height, bottom)]
    if clipped[2] - clipped[0] < 8 or clipped[3] - clipped[1] < 8:
        raise VerificationError("region_outside_sheet",
                                f"The region must overlap the sheet ({width} x {height} px) by at least 8 x 8 px.")
    return clipped


def _encode(image) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()


def _draw_ticks(image, region: list[int], scale: float):
    """Red edge ticks every TICK_SPACING_VIEW_PX view pixels, labelled with the view coordinate."""
    from PIL import ImageDraw
    draw = ImageDraw.Draw(image)
    width, height = image.size
    for x in range(0, width, TICK_SPACING_VIEW_PX):
        draw.line((x, 0, x, 7), fill=(220, 0, 0))
        draw.line((x, height - 8, x, height - 1), fill=(220, 0, 0))
        draw.text((x + 2, 8), str(x), fill=(220, 0, 0))
    for y in range(0, height, TICK_SPACING_VIEW_PX):
        draw.line((0, y, 7, y), fill=(220, 0, 0))
        draw.line((width - 8, y, width - 1, y), fill=(220, 0, 0))
        if y:
            draw.text((9, y + 1), str(y), fill=(220, 0, 0))


def render_view(image: np.ndarray, region: list[int], max_side: int, *, overlay=None) -> tuple[bytes, dict]:
    """A bounded PNG of a sheet region for the model, with its pixel mapping.

    ``overlay(draw, to_view)`` may draw evidence (traces, corridors) in view
    coordinates. Geometry never uses these pixels.
    """
    from PIL import Image, ImageDraw
    left, top, right, bottom = region
    crop = Image.fromarray(image[top:bottom, left:right]).convert("L")
    width, height = crop.size
    scale = min(max_side / max(width, height), math.sqrt(MAX_VIEW_PIXELS / (width * height)), MAX_ZOOM)
    while True:
        size = (max(1, int(width * scale)), max(1, int(height * scale)))
        resample = Image.Resampling.LANCZOS if scale < 1 else Image.Resampling.NEAREST
        view = crop.resize(size, resample).convert("RGB")
        sx, sy = size[0] / width, size[1] / height
        if overlay is not None:
            overlay(ImageDraw.Draw(view), lambda x, y: ((x - left) * sx, (y - top) * sy))
        _draw_ticks(view, region, scale)
        payload = None
        for colors in (64, 32, 16):
            encoded = _encode(view.quantize(colors=colors, method=Image.Quantize.MEDIANCUT))
            if len(encoded) <= MAX_VIEW_BYTES:
                payload = encoded
                break
        if payload is not None:
            break
        scale *= 0.85
    # The vision model reads text of READABLE_TEXT_VIEW_PX or more; smaller text needs a closer view.
    readable = math.ceil(READABLE_TEXT_VIEW_PX / min(sx, sy))
    return payload, {"crop_box_px": region, "pixel_size": [size[0], size[1]],
                     "view_px_per_source_px": [sx, sy],
                     "coordinates": "view pixels from the top-left corner; red ticks every 100 view px; "
                                    "sheet px = crop left/top + view px / view_px_per_source_px",
                     "readable_text_min_sheet_px": readable,
                     "text_note": (f"Text under {readable} sheet px tall is too small to read here; view a smaller "
                                   "region to read it." if readable > READABLE_TEXT_VIEW_PX else
                                   "Text of normal size is readable in this view.")}


def view_to_source(view: dict, point) -> tuple[float, float]:
    sx, sy = view["view_px_per_source_px"]
    left, top = view["crop_box_px"][:2]
    return left + float(point[0]) / sx, top + float(point[1]) / sy


# --------------------------------------------------------- mirrored halves
# A section drawn left of its centreline (ingest.drawn_left_of_centreline) is
# traced on the image flipped left to right. The public trace functions below
# flip on entry and return every pixel coordinate in the source frame.

def _flipped(image: np.ndarray, section: dict) -> tuple[np.ndarray, dict]:
    from .ingest import mirror_section
    return np.ascontiguousarray(image[:, ::-1]), mirror_section(section, image.shape[1])


def _mirror_stroke(stroke: dict, width: int) -> dict:
    """A traced stroke's pixel fields reflected between the source and the flipped image."""
    from .ingest import mirror_points
    result = dict(stroke)
    selection = stroke.get("contour_selection")
    if isinstance(selection, dict):
        result["contour_selection"] = {**selection, "anchors_px": mirror_points(selection["anchors_px"], width)}
    if "trace_xs_px" in stroke:
        result["trace_xs_px"] = [round(width - 1 - float(x), 2) for x in stroke["trace_xs_px"]]
    if stroke.get("seed_px"):
        result["seed_px"] = mirror_points([stroke["seed_px"]], width)[0]
    corridor = stroke.get("corridor_source_px")
    if isinstance(corridor, dict):
        result["corridor_source_px"] = {**corridor, "path": mirror_points(corridor["path"], width)}
    return result


def _is_left(section: dict) -> bool:
    from .ingest import drawn_left_of_centreline
    return drawn_left_of_centreline(section)


# --------------------------------------------------------- corridor trace

def _trace_window(section: dict, image_shape) -> tuple[int, int, int, int]:
    """The engine's trace window of a section: rows of its calibrated range, columns from the centreline."""
    calibration = section["calibration"]
    ppm, centre, baseline = (float(calibration[k]) for k in ("pixels_per_metre", "centerline_px", "baseline_px"))
    left, top, right, bottom = (int(v) for v in section["roi_px"])
    trace_top = max(top, int(round(baseline - float(section["z_max_m"]) * ppm)))
    trace_bottom = min(bottom - 1, int(round(baseline - float(section["z_min_m"]) * ppm)))
    trace_left = max(left, int(math.floor(centre)))
    return trace_left, trace_top, min(right, image_shape[1]), trace_bottom


def corridor_trace(image: np.ndarray, section: dict, source_file: str, details: dict,
                   view: dict, path_view_px, half_width_view_px: float) -> dict:
    """Trace the ink inside a model-drawn corridor and verify it with the engine.

    Returns the snapped candidate (corridor, vertical range, support scores and
    the dense trace). Raises VerificationError when no ink supports a line.
    """
    path = np.asarray([view_to_source(view, p) for p in path_view_px], dtype=float)
    half_width = float(half_width_view_px) / min(view["view_px_per_source_px"])
    return trace_in_source_corridor(image, section, source_file, details, path, half_width)


# Following a stroke from a point: how far (source px) the first ink may be from
# the point, how many rows without ink end the stroke, and the corridor that is
# then traced and verified like a model-drawn one.
SEED_SEARCH_PX = 8.0
SEED_MAX_GAP_ROWS = 6
SEED_CORRIDOR_HALF_WIDTH_PX = 4.0
SEED_HISTORY_ROWS = 24


_FOREGROUND_CACHE: dict = {}


def window_foreground(image: np.ndarray, section: dict):
    """Ink mask, ink strength and the broad-ruler-free mask of a section's trace window.

    Cached for the current worker process (one image), so enumerating many
    strokes of one panel computes the photometric masks once.
    """
    from .ingest import _eligible_trace_mask, _foreground
    window = _trace_window(section, image.shape)
    # Keep the image alive and compare identity, not its recyclable object id.
    if (_FOREGROUND_CACHE.get("image") is not image
            or _FOREGROUND_CACHE.get("window") != window):
        left, top, right, bottom = window
        mask, ink, _ = _foreground(image[top:bottom + 1, left:right])
        eligible, _ = _eligible_trace_mask(mask, None, ink)
        _FOREGROUND_CACHE.clear()
        _FOREGROUND_CACHE.update(image=image, window=window, masks=(mask, ink, eligible))
    return _FOREGROUND_CACHE["masks"]


# Stroke enumeration: scanlines at these shares of the calibrated height, and
# the most strokes that one call traces and shows. The scanlines are spread
# over the height so that a stroke broken by noise is seeded on each piece.
ENUMERATION_SCANLINES = (0.15, 0.3, 0.45, 0.6, 0.75, 0.9)
MAX_ENUMERATED_STROKES = 30
MAX_ENUMERATION_SEEDS = 90


def enumerate_strokes(image: np.ndarray, section: dict, source_file: str, details: dict,
                      height_m: float | None, known: list[dict]) -> tuple[list[dict], list[dict]]:
    """Every verified ink stroke that crosses the section's scanlines, best hull candidates first.

    Seeds are the ink runs on each scanline right of the centreline; each is
    followed (``follow_stroke_paths``), traced and verified as a corridor. A
    stroke with the same ink as an earlier one, or as a ``known`` candidate, is
    not repeated. Verified pieces of one broken stroke are then linked when
    their direction agrees (``link_fragments``), and every stroke is described
    and ordered by ``describe_stroke``: straight axis-aligned lines last, then
    by hull likeness. Returns (strokes, refusals). The harness finds the ink;
    the model only says which stroke is which station.
    """
    from .ingest import _runs
    if _is_left(section):
        width = image.shape[1]
        flipped, mirrored = _flipped(image, section)
        strokes, refusals = enumerate_strokes(flipped, mirrored, source_file, details, height_m,
                                              [_mirror_stroke(k, width) for k in known])
        return ([_mirror_stroke(s, width) for s in strokes],
                [_mirror_stroke(r, width) for r in refusals])
    left, top, right, bottom = _trace_window(section, image.shape)
    eligible = window_foreground(image, section)[2]
    calibration = section["calibration"]
    ppm, baseline, centre = (float(calibration[k]) for k in ("pixels_per_metre", "baseline_px", "centerline_px"))
    low, high = float(section["z_min_m"]), float(section["z_max_m"])
    heights = [height_m] if height_m is not None else [low + share * (high - low) for share in ENUMERATION_SCANLINES]
    seeds = []
    for z in heights:
        row = int(round(baseline - z * ppm)) - top
        if 0 <= row < eligible.shape[0]:
            seeds += [((a + b - 1) / 2 + left, row + top) for a, b in _runs(eligible[row])
                      if (a + b - 1) / 2 + left > centre + 3]
    strokes, refusals = [], []
    for seed in seeds[:MAX_ENUMERATION_SEEDS]:
        if len(strokes) >= MAX_ENUMERATED_STROKES:
            break
        if any(_point_on(seed, s) for s in strokes):
            continue
        try:
            traced = _trace_best_path(image, section, source_file, details, seed)
        except VerificationError as exc:
            refusals.append({"seed_px": [round(seed[0], 1), seed[1]], "reason": exc.code})
            continue
        probe = {"contour_selection": traced["contour_selection"]}
        if any(same_ink(probe, other) for other in [*strokes, *known]):
            continue
        strokes.append({**traced, "seed_px": [round(seed[0], 1), seed[1]]})
    strokes = link_fragments(image, section, source_file, details, strokes)
    grid = grid_columns(image, section)
    strokes = [{**stroke, **describe_stroke(stroke, section, grid)} for stroke in strokes]
    strokes.sort(key=lambda s: (s["kind"] == "straight_grid_line", -s["hull_likeness"]))
    return strokes, refusals


# A straight axis-aligned line: it spans at least this share of the section
# height, leans at most STRAIGHT_LINE_MAX_SLOPE px per row (a line drawn or
# scanned slightly off vertical), and STRAIGHT_LINE_ROW_SHARE of its rows lie
# within STRAIGHT_LINE_TOLERANCE_PX of a fitted straight line (raster
# thickness; the remaining rows allow bumps where other strokes cross it).
STRAIGHT_LINE_MIN_HEIGHT_SHARE = 0.5
STRAIGHT_LINE_MAX_SLOPE = 0.05
STRAIGHT_LINE_TOLERANCE_PX = 2.0
STRAIGHT_LINE_ROW_SHARE = 0.9
# A vertical grid line is a column inked on at least GRID_COLUMN_SHARE of the
# trace window height (a hull side is curved at the bilge, so it never spans
# the whole window). A stroke with GRID_RIDE_ROW_SHARE of its rows within
# GRID_RIDE_TOLERANCE_PX of such a column rides the grid line.
GRID_COLUMN_SHARE = 0.85
GRID_RIDE_TOLERANCE_PX = 2.0
GRID_RIDE_ROW_SHARE = 0.75


def grid_columns(image: np.ndarray, section: dict) -> list[float]:
    """Source columns (centres) of the vertical grid lines that span the section's trace window."""
    if _is_left(section):
        return [image.shape[1] - 1 - column for column in grid_columns(*_flipped(image, section))]
    left = _trace_window(section, image.shape)[0]
    mask = window_foreground(image, section)[0]
    if mask.shape[0] == 0:
        return []
    padded = np.pad(mask, ((0, 0), (1, 1)))
    band = padded[:, :-2] | padded[:, 1:-1] | padded[:, 2:]
    full = np.flatnonzero(band.mean(axis=0) >= GRID_COLUMN_SHARE)
    groups = np.split(full, np.flatnonzero(np.diff(full) > 1) + 1) if len(full) else []
    centre = float(section["calibration"]["centerline_px"])
    # The centreline is not a grid line here: hull strokes end on it.
    return [float(np.mean(g)) + left for g in groups
            if len(g) and abs(float(np.mean(g)) + left - centre) > GRID_RIDE_TOLERANCE_PX + 1.0]


def stroke_kind(rows, xs, section: dict, grid_columns_px=None) -> str:
    """Label long, straight vertical evidence (grid, centreline, rulers) without removing it.

    Section traces are row-indexed, so horizontal grid lines are not enumerated
    as sustained strokes. ``rows`` are the first and last row of the trace.
    ``grid_columns_px`` (source columns of full-height vertical grid lines,
    ``grid_columns``) also labels a stroke that rides a grid line for most of
    its rows: a follower that left a hull curve at a crossing and ran on along
    the grid line (a hull curve only crosses a grid line).
    """
    calibration = section["calibration"]
    expected_height = (section["z_max_m"] - section["z_min_m"]) * calibration["pixels_per_metre"]
    if not len(xs):
        return "candidate_stroke"
    xs = np.asarray(xs, dtype=float)
    span = rows[-1] - rows[0]
    if grid_columns_px is not None and len(grid_columns_px):
        columns = np.asarray(grid_columns_px, dtype=float)
        distance = np.min(np.abs(xs[:, None] - columns[None, :]), axis=1)
        if float(np.mean(distance <= GRID_RIDE_TOLERANCE_PX)) >= GRID_RIDE_ROW_SHARE:
            return "straight_grid_line"
    if span >= 0.95 * expected_height and float(np.ptp(xs)) <= 2.0:
        return "straight_grid_line"
    if span < STRAIGHT_LINE_MIN_HEIGHT_SHARE * expected_height or len(xs) < 2:
        return "candidate_stroke"
    heights = np.linspace(rows[0], rows[-1], len(xs))
    slope, intercept = np.polyfit(heights, xs, 1)
    on_line = np.abs(xs - (slope * heights + intercept)) <= STRAIGHT_LINE_TOLERANCE_PX
    if abs(slope) <= STRAIGHT_LINE_MAX_SLOPE and float(on_line.mean()) >= STRAIGHT_LINE_ROW_SHARE:
        return "straight_grid_line"
    return "candidate_stroke"


# Hull likeness (a ranking heuristic, never identity): the half-breadth of a
# hull section is a smooth curve that spans the section height, mostly widens
# upwards and ends at the keel near the baseline or the centreline. Monotony
# is reduced by counter-movement (tumblehome, flare, a bulb) as a share of the
# breadth range. A stroke "reaches the keel" when its lowest point is within
# HULL_KEEL_SHARE of the height above the lowest calibrated height, or within
# that share of its own breadth from the centreline.
HULL_SAMPLES = 64
HULL_KEEL_SHARE = 0.1
HULL_TURN_DEG = 180.0


def describe_stroke(stroke: dict, section: dict, grid_columns_px=None) -> dict:
    """Kind, vertical coverage and hull-likeness of a verified stroke (added fields only).

    ``z_coverage_fraction`` is the share of the section's calibrated height
    that the stroke's ink spans. ``hull_likeness`` is in [0, 1]: coverage times
    the monotony, smoothness and keel factors. It orders candidates for the
    model; it does not certify that a stroke is a hull line.
    """
    rows_range, xs = stroke["trace_rows_px"], np.asarray(stroke["trace_xs_px"], dtype=float)
    kind = stroke_kind(rows_range, xs, section, grid_columns_px)
    low, high = float(section["z_min_m"]), float(section["z_max_m"])
    z_low, z_high = (float(v) for v in stroke["z_range_m"])
    coverage = float(np.clip((z_high - z_low) / (high - low), 0.0, 1.0))
    # Half-breadth (px from the centreline) against height, bottom first.
    centre = float(section["calibration"]["centerline_px"])
    side = -1.0 if _is_left(section) else 1.0
    half_breadth = side * (xs[::-1] - centre)
    heights = np.arange(len(half_breadth), dtype=float)
    steps = np.diff(half_breadth)
    breadth_range = max(float(np.ptp(half_breadth)), 1.0)
    counter = float(min(np.sum(np.maximum(-steps, 0)), np.sum(np.maximum(steps, 0)))) / breadth_range
    monotone = float(np.clip(1.0 - counter, 0.0, 1.0))
    # Smoothness: total turning of the curve, resampled evenly along its
    # length. Keel to deck turns through up to about HULL_TURN_DEG; a trace that
    # jumps between strokes turns back and forth much more.
    lengths = np.r_[0.0, np.cumsum(np.hypot(steps, 1.0))]
    along = np.linspace(0.0, lengths[-1], HULL_SAMPLES)
    curve = np.column_stack([np.interp(along, lengths, half_breadth), np.interp(along, lengths, heights)])
    directions = np.unwrap(np.arctan2(*np.diff(curve, axis=0).T[::-1]))
    turning = math.degrees(float(np.sum(np.abs(np.diff(directions)))))
    smooth = 1.0 / (1.0 + max(0.0, turning - HULL_TURN_DEG) / HULL_TURN_DEG)
    keel = (z_low - low <= HULL_KEEL_SHARE * (high - low)
            or float(half_breadth[0]) <= HULL_KEEL_SHARE * max(float(half_breadth.max()), 1.0))
    keel_factor = 1.0 if keel else 0.6
    likeness = coverage * (0.7 + 0.3 * monotone) * smooth * keel_factor
    if kind == "straight_grid_line":
        likeness *= 0.1
    return {"kind": kind, "z_coverage_fraction": round(coverage, 4), "hull_likeness": round(likeness, 4),
            "hull_likeness_factors": {"monotone": round(monotone, 3), "smooth": round(smooth, 3),
                                      "reaches_keel": bool(keel)},
            "hull_likeness_basis": "ranking heuristic over the traced half-breadth; not identity or approval"}


def _point_on(seed, stroke) -> bool:
    """True when a seed lies on an already traced stroke (2 px)."""
    rows, xs = stroke["trace_rows_px"], stroke["trace_xs_px"]
    row = int(seed[1]) - rows[0]
    return 0 <= row < len(xs) and abs(xs[row] - seed[0]) <= SAME_INK_DISTANCE_PX


def follow_stroke(image: np.ndarray, section: dict, seed_source) -> np.ndarray:
    """Follow the ink stroke through a seed point, row by row, up and down.

    At each row the run centre nearest to the position predicted from the
    recent slope continues the stroke; a crossing line or a short gap keeps
    the prediction. Returns (row, column) source points, or raises when no ink
    is at the seed. The result is only a corridor: the line itself is traced
    and verified by ``trace_in_source_corridor``.
    """
    from .ingest import _runs
    left, top, right, bottom = _trace_window(section, image.shape)
    eligible = window_foreground(image, section)[2]
    seed_x, seed_row = float(seed_source[0]) - left, int(round(float(seed_source[1]) - top))
    if not 0 <= seed_row < eligible.shape[0]:
        raise VerificationError("point_outside_section", "The point is outside the section's calibrated height range.")

    def centres(row):
        return [(a + b - 1) / 2 for a, b in _runs(eligible[row])]

    start = None
    for offset in (0, -1, 1, -2, 2, -3, 3):
        row = seed_row + offset
        if 0 <= row < eligible.shape[0]:
            near = [c for c in centres(row) if abs(c - seed_x) <= SEED_SEARCH_PX]
            if near:
                start = (row, min(near, key=lambda c: abs(c - seed_x)))
                break
    if start is None:
        raise VerificationError("no_ink_at_point",
                                f"No ink within {SEED_SEARCH_PX:g} source px of the point; click on the curve itself.")
    points = {start[0]: start[1]}
    for step in (-1, 1):
        history = [start]
        row, gap = start[0], 0
        while 0 <= row + step < eligible.shape[0] and gap <= SEED_MAX_GAP_ROWS:
            row += step
            # A quadratic fit of the last rows predicts the stroke through a
            # crossing; a straight line that crosses it bends away from it.
            recent = history[-SEED_HISTORY_ROWS:]
            slope, predicted = 0.0, history[-1][1]
            if len(recent) >= 6:
                rows_fit = np.array([r for r, _ in recent], dtype=float)
                fit = np.polyfit(rows_fit - row, [x for _, x in recent], 2 if len(recent) >= 12 else 1)
                predicted = float(fit[-1])
                slope = float(fit[-2])
            tolerance = 2.0 + 0.5 * abs(slope)
            near = [c for c in centres(row) if abs(c - predicted) <= tolerance]
            if near:
                history.append((row, min(near, key=lambda c: abs(c - predicted))))
                points[row] = history[-1][1]
                gap = 0
            else:
                gap += 1
    rows = np.array(sorted(points))
    return np.column_stack([rows + top, np.array([points[r] for r in rows]) + left])


# Two-dimensional stroke following. Row-by-row following loses a stroke where
# it runs nearly horizontally (bilge, flat bottom) and where a vertical ruler
# crosses it. This tracker steps along the ink direction instead. Vertical
# rulers are hidden from its direction choice, so it crosses them, and it
# bridges short breaks (scan noise, a crossing) along its heading and
# curvature. Its path is only a corridor: the line is traced and verified by
# ``trace_in_source_corridor`` like any other.
TRACK_STEP_PX = 2.0
# Look-ahead points from TRACK_LOOKAHEAD_MIN_PX to the larger of
# TRACK_LOOKAHEAD_MIN_REACH_PX and TRACK_LOOKAHEAD_WIDTHS stroke widths: along a
# thick stroke a longer ray tells its axis from a slanted chord. At least half
# of them (and TRACK_MIN_HITS) must be on ink. Ink up to TRACK_FAR_LOOKAHEAD_PX
# further on steers the track across a break.
TRACK_LOOKAHEAD_MIN_PX = 2.0
TRACK_LOOKAHEAD_MIN_REACH_PX = 5.0
TRACK_LOOKAHEAD_WIDTHS = 2.0
TRACK_LOOKAHEAD_POINTS = 6
TRACK_FAR_LOOKAHEAD_PX = 10
TRACK_MIN_HITS = 2
TRACK_FAN_DEG = 45  # the widest turn considered per step
TRACK_FAN_STEP_DEG = 5
TRACK_TURN_COST_PER_DEG = 0.01  # among equally supported directions, the straightest wins
TRACK_RECENTRE_PX = 3  # re-centre across the stroke within this half width (or one stroke width)
TRACK_MAX_WIDTH_PX = 15  # stroke width is measured up to this many px
TRACK_MAX_GAP_SHARE = 0.04  # longest bridged break: this share of the window height,
TRACK_MIN_GAP_PX = 10.0  # but at least this many source px
TRACK_LOOP_STEPS = 8  # a cell revisited after more steps than this ends the track
TRACK_HEADING_STEPS = 4  # heading is measured over this many steps (8 px)
TRACK_MAX_TURN = math.radians(4)  # largest curvature (per step) carried through a break
# A column inked on this share of the window rows (within one column either
# side) is a vertical ruler: grid, centreline or a drawn border. Where a stroke
# runs on a ruler (a wall side on a grid line) only straight-on steps continue.
RULER_COLUMN_SHARE = 0.5
RULER_MARGIN_PX = 2
RULER_FOLLOW_FAN_DEG = 10
# Corridor paths are simplified to this error before tracing.
PATH_TOLERANCE_PX = 1.0
# The stroke direction at a seed is the principal axis of the ink within this radius.
SEED_DIRECTION_RADIUS_PX = 8


def _ruler_columns(eligible: np.ndarray) -> np.ndarray:
    """Columns of the trace window that carry a long vertical ruler (with a stroke margin)."""
    from scipy import ndimage
    padded = np.pad(eligible, ((0, 0), (1, 1)))
    band = padded[:, :-2] | padded[:, 1:-1] | padded[:, 2:]
    ruler = band.mean(axis=0) >= RULER_COLUMN_SHARE
    return ndimage.binary_dilation(ruler, iterations=RULER_MARGIN_PX) if ruler.any() else ruler


def _ruler_mask(eligible: np.ndarray) -> np.ndarray:
    """Pixels of long vertical and horizontal rulers (grid, centreline, waterlines).

    Broad horizontal runs are already excluded from the eligible mask; a
    horizontal ruler broken by noise into shorter runs is found here.
    """
    return _ruler_columns(eligible)[None, :] | _ruler_columns(eligible.T)[:, None]


def _ink_at(mask: np.ndarray, x: float, y: float) -> bool:
    column, row = int(round(x)), int(round(y))
    return 0 <= row < mask.shape[0] and 0 <= column < mask.shape[1] and bool(mask[row, column])


def _rotate(vector: np.ndarray, angle: float) -> np.ndarray:
    cos, sin = math.cos(angle), math.sin(angle)
    return np.array([cos * vector[0] - sin * vector[1], sin * vector[0] + cos * vector[1]])


def _signed_angle(first: np.ndarray, second: np.ndarray) -> float:
    return math.atan2(first[0] * second[1] - first[1] * second[0], float(first @ second))


def _stroke_width(mask: np.ndarray, point: np.ndarray, direction: np.ndarray) -> float:
    """Width of the ink run through a point, across the given direction."""
    normal = np.array([-direction[1], direction[0]])
    width = 1
    for sign in (-1, 1):
        k = 1
        while k <= TRACK_MAX_WIDTH_PX and _ink_at(mask, *(point + sign * k * normal)):
            k += 1
        width += k - 1
    return float(min(width, TRACK_MAX_WIDTH_PX))


def _recentre(mask: np.ndarray, point: np.ndarray, direction: np.ndarray, radius: int) -> np.ndarray:
    """Move a point across the stroke to the centre of the ink run nearest to it."""
    normal = np.array([-direction[1], direction[0]])
    offsets = [k for k in range(-radius, radius + 1) if _ink_at(mask, *(point + k * normal))]
    if not offsets:
        return point
    # Keep only the contiguous run that is nearest to the point, so that a
    # neighbouring stroke within the search width does not pull it across.
    nearest = min(offsets, key=abs)
    run = [nearest]
    for step in (-1, 1):
        k = nearest + step
        while k in offsets:
            run.append(k)
            k += step
    return point + float(np.mean(run)) * normal


def _track(primary: np.ndarray, full: np.ndarray, start: np.ndarray, heading: np.ndarray,
           max_gap: float, stroke_width: float = 1.0) -> np.ndarray:
    """Points (x, y) of one direction of a stroke, ending at its last ink point."""
    height, width = primary.shape
    point, heading = start.astype(float), heading / np.linalg.norm(heading)
    angles = np.radians(np.arange(-TRACK_FAN_DEG, TRACK_FAN_DEG + 1, TRACK_FAN_STEP_DEG))
    reach = max(TRACK_LOOKAHEAD_MIN_REACH_PX, TRACK_LOOKAHEAD_WIDTHS * stroke_width)
    near = tuple(np.linspace(TRACK_LOOKAHEAD_MIN_PX, reach, TRACK_LOOKAHEAD_POINTS))
    far = tuple(float(r) for r in range(int(reach) + 1, int(reach) + 1 + TRACK_FAR_LOOKAHEAD_PX))
    needed = max(TRACK_MIN_HITS, len(near) // 2)
    recentre_radius = max(TRACK_RECENTRE_PX, int(math.ceil(stroke_width)))
    # In order: the stroke ahead; straight on along a ruler; ink further
    # ahead, which steers across a hidden ruler or a break towards the stroke.
    searches = ((primary, angles, needed, near),
                (full, angles[np.abs(angles) <= math.radians(RULER_FOLLOW_FAN_DEG) + 1e-9], len(near), near),
                (primary, angles, TRACK_MIN_HITS, far))
    points, last_ink, gap, turn, visited = [point], 1, 0.0, 0.0, {}
    for step in range(4 * (height + width)):
        best, search = None, None
        for search, (mask, fan, needed, radii) in enumerate(searches):
            for angle in fan:
                direction = _rotate(heading, angle)
                hits = sum(_ink_at(mask, *(point + r * direction)) for r in radii)
                score = hits - TRACK_TURN_COST_PER_DEG * abs(math.degrees(angle))
                if hits >= needed and (best is None or score > best[0]):
                    best = (score, direction, mask)
            if best is not None:
                break
        on_ink = best is not None and search < 2
        if on_ink:
            following = _recentre(best[2], point + TRACK_STEP_PX * best[1], best[1], recentre_radius)
            gap = 0.0
        else:
            # A break: continue along the heading (turning as the stroke
            # turned) or towards ink seen further ahead.
            if best is not None:
                heading = best[1]
            following = point + TRACK_STEP_PX * heading
            gap += TRACK_STEP_PX
            if gap > max_gap:
                break
        if not (0 <= following[0] < width and 0 <= following[1] < height):
            break
        cell = (int(following[0]) // 2, int(following[1]) // 2)
        if step - visited.setdefault(cell, step) > TRACK_LOOP_STEPS:
            break
        if float(np.linalg.norm(following - point)) < 1e-6:
            break
        point = following
        points.append(point)
        if on_ink:
            last_ink = len(points)
            # Heading and curvature over a few steps, so that re-centring
            # jitter of single steps does not steer a bridged break.
            recent = points[-1] - points[max(0, len(points) - 1 - TRACK_HEADING_STEPS)]
            if np.linalg.norm(recent) > 1e-6:
                earlier_end = max(0, len(points) - 1 - TRACK_HEADING_STEPS)
                earlier = points[earlier_end] - points[max(0, earlier_end - TRACK_HEADING_STEPS)]
                if np.linalg.norm(earlier) > 1e-6:
                    turn = float(np.clip(_signed_angle(earlier, recent) / TRACK_HEADING_STEPS,
                                         -TRACK_MAX_TURN, TRACK_MAX_TURN))
                heading = recent / np.linalg.norm(recent)
        elif best is None:
            heading = _rotate(heading, turn)
    return np.array(points[:last_ink])


def _principal_direction(mask: np.ndarray, point: np.ndarray, radius: int = 5) -> np.ndarray:
    """Direction of the ink around a point (principal axis), vertical when unclear."""
    x0, y0 = int(round(point[0])), int(round(point[1]))
    rows, cols = np.nonzero(mask[max(0, y0 - radius):y0 + radius + 1, max(0, x0 - radius):x0 + radius + 1])
    if len(rows) < 3:
        return np.array([0.0, 1.0])
    offsets = np.column_stack([cols + max(0, x0 - radius) - point[0], rows + max(0, y0 - radius) - point[1]])
    _, vectors = np.linalg.eigh(offsets.T @ offsets)
    direction = vectors[:, -1]
    return direction / np.linalg.norm(direction)


def follow_stroke_2d(image: np.ndarray, section: dict, seed_source, *, width_scaled: bool = True) -> np.ndarray:
    """Follow the ink stroke through a seed point along its own direction, both ways.

    ``width_scaled`` scales the look-ahead and re-centring to the stroke width
    measured at the seed; without it they suit a thin stroke. Neither setting
    is best on every scan, so ``_trace_best_path`` tries both.

    Returns (row, column) source points, one per row (the mean column where the
    stroke runs nearly horizontally), like ``follow_stroke``. Raises when no ink
    is at the seed.
    """
    left, top, _, _ = _trace_window(section, image.shape)
    eligible = window_foreground(image, section)[2]
    height = eligible.shape[0]
    primary = eligible & ~_ruler_mask(eligible)
    seed = np.array([float(seed_source[0]) - left, float(seed_source[1]) - top])
    if not 0 <= seed[1] < height:
        raise VerificationError("point_outside_section", "The point is outside the section's calibrated height range.")
    from scipy import ndimage
    y0, x0 = int(max(0, seed[1] - SEED_SEARCH_PX)), int(max(0, seed[0] - SEED_SEARCH_PX))
    near = primary[y0:int(seed[1] + SEED_SEARCH_PX) + 1, x0:int(seed[0] + SEED_SEARCH_PX) + 1]
    labels, _ = ndimage.label(near, structure=np.ones((3, 3), dtype=int))
    rows, cols = np.nonzero(near)
    points = np.column_stack([cols + x0, rows + y0]).astype(float)
    distances = np.linalg.norm(points - seed, axis=1) if len(points) else np.array([np.inf])
    if distances.min() > SEED_SEARCH_PX:
        # No ink off the rulers: a ruler itself is followed row by row
        # (``follow_stroke``); tracking from it would leave it onto a curve.
        raise VerificationError("no_ink_at_point",
                                f"No ink off a ruler within {SEED_SEARCH_PX:g} source px of the point.")
    # Prefer a stroke to a nearer noise speck: the nearest pixel of the
    # largest ink component around the point.
    component = labels[rows, cols]
    sizes = np.bincount(component)
    largest = (component == int(np.argmax(sizes))) & (distances <= SEED_SEARCH_PX)
    if largest.any():
        distances = np.where(largest, distances, np.inf)
    start = points[int(np.argmin(distances))]
    heading = _principal_direction(primary, start, radius=SEED_DIRECTION_RADIUS_PX)
    max_gap = max(TRACK_MIN_GAP_PX, TRACK_MAX_GAP_SHARE * height)
    stroke_width = _stroke_width(primary, start, heading) if width_scaled else 1.0
    start = _recentre(primary, start, heading, max(TRACK_RECENTRE_PX, int(math.ceil(stroke_width))))
    forward = _track(primary, eligible, start, heading, max_gap, stroke_width)
    backward = _track(primary, eligible, start, -heading, max_gap, stroke_width)
    path = np.vstack([backward[::-1], forward[1:]])
    rows = np.rint(path[:, 1]).astype(int)
    unique_rows = np.unique(rows)
    columns = np.array([path[rows == row, 0].mean() for row in unique_rows])
    return np.column_stack([unique_rows + top, columns + left])


def _simplified_path(followed: np.ndarray) -> np.ndarray:
    """(column, row) corridor points of a followed stroke, within PATH_TOLERANCE_PX of it."""
    rows, columns = followed[:, 0].astype(float), followed[:, 1].astype(float)
    keep = [0, len(rows) - 1]
    while True:
        keep.sort()
        residual = np.abs(np.interp(rows, rows[keep], columns[keep]) - columns)
        worst = int(np.argmax(residual))
        if residual[worst] <= PATH_TOLERANCE_PX or worst in keep:
            break
        keep.append(worst)
    return np.column_stack([columns[keep], rows[keep]])


def _trace_best_path(image: np.ndarray, section: dict, source_file: str, details: dict, seed_source) -> dict:
    """Follow a stroke from a seed by direction tracking and by row following; return the longest verified trace.

    Both followers only propose corridors. When neither is verified, the row
    follower's refusal is raised (its codes predate the tracker).
    """
    if _is_left(section):
        width = image.shape[1]
        seed = [width - 1 - float(seed_source[0]), float(seed_source[1])]
        return _mirror_stroke(_trace_best_path(*_flipped(image, section), source_file, details, seed), width)
    traced, refusal = [], None
    followers = (("direction_tracking", follow_stroke_2d),
                 ("direction_tracking_thin", lambda *a: follow_stroke_2d(*a, width_scaled=False)),
                 ("row_following", follow_stroke))
    for method, follow in followers:
        try:
            followed = follow(image, section, seed_source)
            if len(followed) < 33:
                raise VerificationError("stroke_too_short",
                                        f"The stroke at the point is followed for only {len(followed)} rows.")
            result = trace_in_source_corridor(image, section, source_file, details, _simplified_path(followed),
                                              SEED_CORRIDOR_HALF_WIDTH_PX)
            traced.append({**result, "follow_method": method})
        except VerificationError as exc:
            refusal = exc
    if not traced:
        raise refusal
    return max(traced, key=lambda t: t["trace_rows_px"][1] - t["trace_rows_px"][0])


# Linking verified pieces of one stroke broken by noise or a crossing: the
# lower piece must start within LINK_MAX_GAP_SHARE of the window height below
# the upper piece's end (or overlap it by at most LINK_MAX_OVERLAP_SHARE), its
# end must lie on the upper piece's extrapolated direction within
# LINK_MAX_OFFSET_PX plus LINK_OFFSET_PER_GAP_PX per px of gap, and the two end
# directions (fitted over LINK_FIT_ROWS rows) must agree within LINK_MAX_ANGLE_DEG.
# The joined corridor is then traced and verified like any other.
LINK_MAX_GAP_SHARE = 0.06
LINK_MAX_OVERLAP_SHARE = 0.04
LINK_MAX_OFFSET_PX = 4.0
LINK_OFFSET_PER_GAP_PX = 0.25
LINK_FIT_ROWS = 15
LINK_MAX_ANGLE_DEG = 25.0


def _end_direction(rows: np.ndarray, xs: np.ndarray, at_bottom: bool) -> tuple[np.ndarray, np.ndarray]:
    """End point (x, row) and unit direction pointing away from the piece."""
    part = slice(-LINK_FIT_ROWS, None) if at_bottom else slice(0, LINK_FIT_ROWS)
    r, x = rows[part].astype(float), xs[part]
    slope = float(np.polyfit(r, x, 1)[0]) if len(r) >= 2 else 0.0
    direction = np.array([slope, 1.0]) * (1 if at_bottom else -1)
    end = np.array([x[-1], r[-1]]) if at_bottom else np.array([x[0], r[0]])
    return end, direction / np.linalg.norm(direction)


def _pieces_agree(upper: dict, lower: dict, window_height: int) -> bool:
    a_rows = np.arange(upper["trace_rows_px"][0], upper["trace_rows_px"][1] + 1)
    b_rows = np.arange(lower["trace_rows_px"][0], lower["trace_rows_px"][1] + 1)
    gap = int(b_rows[0] - a_rows[-1])
    if gap > LINK_MAX_GAP_SHARE * window_height or -gap > LINK_MAX_OVERLAP_SHARE * window_height:
        return False
    if b_rows[-1] <= a_rows[-1] or b_rows[0] <= a_rows[0]:
        return False  # one piece contains the other in height
    a_end, a_dir = _end_direction(a_rows, np.asarray(upper["trace_xs_px"]), True)
    b_end, b_dir = _end_direction(b_rows, np.asarray(lower["trace_xs_px"]), False)
    angle = math.degrees(math.acos(float(np.clip(-(a_dir @ b_dir), -1.0, 1.0))))
    if angle > LINK_MAX_ANGLE_DEG:
        return False
    tolerance = LINK_MAX_OFFSET_PX + LINK_OFFSET_PER_GAP_PX * float(np.linalg.norm(b_end - a_end))
    # Each end must lie near the other piece's extrapolated direction.
    for end, origin, direction in ((b_end, a_end, a_dir), (a_end, b_end, b_dir)):
        offset = end - origin
        if abs(offset[0] * direction[1] - offset[1] * direction[0]) > tolerance:
            return False
    return True


def link_fragments(image: np.ndarray, section: dict, source_file: str, details: dict,
                   strokes: list[dict]) -> list[dict]:
    """Join verified stroke pieces whose ends agree in position and direction.

    A joined stroke replaces its pieces only when the engine verifies the
    joined corridor (the usual coverage and gap limits); otherwise the pieces
    stay as they are. Straight rulers are never joined.
    """
    window_height = _trace_window(section, image.shape)[3] - _trace_window(section, image.shape)[1] + 1
    pieces = list(strokes)
    joined = True
    while joined:
        joined = False
        curved = [p for p in pieces if stroke_kind(p["trace_rows_px"], p["trace_xs_px"], section) != "straight_grid_line"]
        pairs = [(u, l) for u in curved for l in curved
                 if u is not l and _pieces_agree(u, l, window_height)]
        pairs.sort(key=lambda pair: abs(pair[1]["trace_rows_px"][0] - pair[0]["trace_rows_px"][1]))
        for upper, lower in pairs:
            junction = (upper["trace_rows_px"][1] + lower["trace_rows_px"][0]) / 2
            followed = []
            for piece, keep in ((upper, lambda r: r < junction), (lower, lambda r: r >= junction)):
                rows = np.arange(piece["trace_rows_px"][0], piece["trace_rows_px"][1] + 1)
                xs = np.asarray(piece["trace_xs_px"], dtype=float)
                followed += [(r, x) for r, x in zip(rows, xs) if keep(r)]
            try:
                traced = trace_in_source_corridor(image, section, source_file, details,
                                                  _simplified_path(np.asarray(followed, dtype=float)),
                                                  SEED_CORRIDOR_HALF_WIDTH_PX)
            except VerificationError:
                continue
            span = traced["trace_rows_px"][1] - traced["trace_rows_px"][0]
            if span <= max(p["trace_rows_px"][1] - p["trace_rows_px"][0] for p in (upper, lower)):
                continue
            count = upper.get("linked_fragments", 1) + lower.get("linked_fragments", 1)
            pieces = [p for p in pieces if p is not upper and p is not lower]
            pieces.append({**traced, "seed_px": upper.get("seed_px"), "follow_method": "linked_fragments",
                           "linked_fragments": count})
            joined = True
            break
    return pieces


def trace_from_point(image: np.ndarray, section: dict, source_file: str, details: dict,
                     view: dict, point_view_px) -> dict:
    """Follow the stroke under a point the model chose, then trace and verify it as a corridor."""
    traced = _trace_best_path(image, section, source_file, details, view_to_source(view, point_view_px))
    return {**traced, **describe_stroke(traced, section)}


def trace_in_source_corridor(image: np.ndarray, section: dict, source_file: str, details: dict,
                             path: np.ndarray, half_width: float) -> dict:
    """Trace and verify the ink inside a corridor given in source pixels (see corridor_trace)."""
    from .agent_tools import _adaptive_anchors
    from .ingest import (COMPLEXITY_REDUCTION_WARNING, DrawingError, _eligible_trace_mask, _extract_one, _trace,
                         label_rows_above_curve)
    if _is_left(section):
        width = image.shape[1]
        mirrored_path = np.column_stack([width - 1 - path[:, 0], path[:, 1]])
        flipped, mirrored = _flipped(image, section)
        return _mirror_stroke(trace_in_source_corridor(flipped, mirrored, source_file, details, mirrored_path,
                                                       half_width), width)
    path = path[np.argsort(path[:, 1], kind="stable")]
    if np.any(np.diff(path[:, 1]) <= 0):
        raise VerificationError("corridor_path_invalid", "Corridor points must be at distinct heights.")
    left, top, right, bottom = _trace_window(section, image.shape)
    if bottom - top < 32 or right - left < 8:
        raise VerificationError("section_window_too_small", "The section has too few calibrated pixels to trace.")
    mask, ink, _ = window_foreground(image, section)
    rows_local = np.arange(mask.shape[0]) + top
    inside = (rows_local >= path[0, 1]) & (rows_local <= path[-1, 1])
    if inside.sum() < 33:
        raise VerificationError("corridor_outside_section",
                                "The corridor does not overlap the section's calibrated height range by 33 px or more.")
    centres = np.interp(rows_local, path[:, 1], path[:, 0]) - left
    corridor = (np.abs(np.arange(mask.shape[1])[None, :] - centres[:, None]) <= half_width) & inside[:, None]
    eligible, _ = _eligible_trace_mask(mask, corridor, ink)
    centre_local = float(section["calibration"]["centerline_px"]) - left
    # Trace only the rows that the corridor spans, so a curve that ends
    # inside the calibrated range is traced on its own height.
    first_row, last_row = int(np.flatnonzero(inside)[0]), int(np.flatnonzero(inside)[-1])
    ink_rows = int(eligible[first_row:last_row + 1].any(axis=1).sum())
    corridor_rows = last_row - first_row + 1
    diagnosis = {"corridor_rows": corridor_rows, "corridor_rows_with_ink": ink_rows,
                 "half_width_source_px": round(half_width, 2)}
    try:
        rows, xs, quality = _trace(eligible[first_row:last_row + 1], ink[first_row:last_row + 1], centre_local)
    except DrawingError as exc:
        raise VerificationError(
            "no_ink_in_corridor",
            f"No supported ink line in the corridor ({exc.kind}): ink on {ink_rows} of {corridor_rows} corridor "
            "rows. Look at the attached image of your corridor and move it onto the curve.", diagnosis) from None
    rows = rows + first_row
    # A stroke followed past the curve's top end runs onto its station label.
    label_rows = label_rows_above_curve(rows, xs, ink)
    rows, xs = rows[label_rows:], xs[label_rows:]
    if label_rows:
        diagnosis["label_rows_removed"] = label_rows
    first, last = int(rows[0]), int(rows[-1])
    span = last - first + 1
    gaps = np.diff(rows) - 1
    max_gap = int(gaps.max()) if len(gaps) else 0
    coverage = len(rows) / span
    support = {"observed_rows": int(len(rows)), "row_span": span, "row_coverage": round(coverage, 4),
               "max_missing_run_px": max_gap,
               "long_component_support_fraction": round(quality["long_component_support_fraction"], 4),
               "mean_trace_contrast": round(quality["mean_trace_contrast"], 4),
               "maximum_step_px_per_row": round(quality["maximum_step_px_per_row"], 4), **diagnosis}
    if (coverage < MIN_ROW_COVERAGE or max_gap > max(3, math.ceil(span * GAP_FRACTION))
            or quality["long_component_support_fraction"] < MIN_LONG_COMPONENT_SUPPORT):
        raise VerificationError("insufficient_ink_support",
                                "The ink in the corridor is broken or fragmented; no continuous line is supported.",
                                support)
    if span < MIN_VERTICAL_SHARE * mask.shape[0]:
        raise VerificationError("line_too_short",
                                f"The traced ink spans {span} px, under {MIN_VERTICAL_SHARE:.0%} of the section height.",
                                support)
    calibration = section["calibration"]
    ppm, baseline = float(calibration["pixels_per_metre"]), float(calibration["baseline_px"])
    # The vertical range of the accepted line is where its ink is, never a
    # model value: rows one pixel inside the traced ends.
    near_top = first <= max(3, math.ceil(mask.shape[0] * GAP_FRACTION))
    near_bottom = mask.shape[0] - 1 - last <= max(3, math.ceil(mask.shape[0] * GAP_FRACTION))
    z_max = float(section["z_max_m"]) if near_top else (baseline - (top + first + 1)) / ppm
    z_min = float(section["z_min_m"]) if near_bottom else (baseline - (top + last - 1)) / ppm
    z_max, z_min = round(min(z_max, float(section["z_max_m"])), 6), round(max(z_min, float(section["z_min_m"])), 6)
    narrowed = {**section, "z_min_m": z_min, "z_max_m": z_max}
    n_left, n_top, _, n_bottom = _trace_window(narrowed, image.shape)
    absolute_rows, absolute_xs = rows + top, xs + left
    anchors = _adaptive_anchors(absolute_rows, absolute_xs, float(n_top), float(n_bottom))
    if anchors is None:
        raise VerificationError("not_a_bounded_corridor", "The traced ink jumps between strokes; it is not one line.",
                                support)
    selection = {"anchors_px": anchors, "half_width_px": SNAPPED_HALF_WIDTH_PX}
    # The decisive check: the engine itself re-reads the line in the tight
    # corridor, with its own coverage, gap, ambiguity and side checks.
    try:
        _, engine = _extract_one(image, {**narrowed, "contour_selection": selection}, source_file, details)
    except DrawingError as exc:
        raise VerificationError("engine_rejected_line", f"The engine refused the traced line: {exc.kind}.",
                                {**support, "engine_reason": exc.kind}) from None
    dense_rows = np.arange(n_top, n_bottom + 1)
    dense_xs = np.interp(dense_rows, absolute_rows, absolute_xs)
    reduced = any(key in engine or key in quality for key in ("complexity_reduction", "evidence_complexity_reduction"))
    warnings = {"warnings": [COMPLEXITY_REDUCTION_WARNING]} if reduced else {}
    return {**warnings, "contour_selection": selection, "z_range_m": [z_min, z_max],
            "vertical_range_from_ink": not (near_top and near_bottom),
            "support": support, "corridor_source_px": {"path": path.round(2).tolist(),
                                                       "half_width_px": round(half_width, 3)},
            "trace_rows_px": [int(dense_rows[0]), int(dense_rows[-1])],
            "trace_xs_px": [round(float(v), 2) for v in dense_xs]}


def dense_trace(candidate: dict) -> tuple[np.ndarray, np.ndarray] | None:
    """Rows and columns of a candidate's corridor centre (its snapped ink)."""
    selection = candidate.get("contour_selection")
    if not isinstance(selection, dict):
        return None
    anchors = np.asarray(selection["anchors_px"], dtype=float)
    rows = np.arange(int(math.ceil(anchors[0, 1])), int(math.floor(anchors[-1, 1])) + 1)
    return rows, np.interp(rows, anchors[:, 1], anchors[:, 0])


def same_ink(first: dict, second: dict) -> bool:
    """True when two candidates follow the same ink on most of their shared rows."""
    a, b = dense_trace(first), dense_trace(second)
    if a is None or b is None:
        return False
    rows = np.intersect1d(a[0], b[0])
    if len(rows) < 0.5 * min(len(a[0]), len(b[0])):
        return False
    xa = np.interp(rows, a[0], a[1])
    xb = np.interp(rows, b[0], b[1])
    return float(np.mean(np.abs(xa - xb) <= SAME_INK_DISTANCE_PX)) >= SAME_INK_ROW_SHARE


def model_candidate_id(source_sha: str, section_id: str, selection: dict, z_range) -> str:
    return "trace-" + digest_object({"source": source_sha, "section": section_id,
                                     "selection": selection, "z_range_m": z_range})[:20]


# ------------------------------------------------------- station assignment

def label_view_box(state: dict, spec_sections: list[dict], view_id: str) -> list | None:
    """Sheet region of pixels the model was given: an investigation view or an inspection image.

    An inspection overlay shows its section's panel; the source page shows the sheet.
    """
    view = next((v for v in state.get("views", []) if v["view_id"] == view_id), None)
    if view is not None:
        return view["crop_box_px"]
    artifact = next((a for a in state.get("inspection_artifacts", [])
                     if a.get("id") == view_id and a.get("model_eligible") is True), None)
    if artifact is None:
        return None
    section = next((s for s in spec_sections if s.get("id") == artifact.get("section_id")), None)
    if section is not None:
        return list(section["roi_px"])
    return [0, 0, 10**6, 10**6] if artifact.get("evidence_kind") == "source_page" else None


def check_assignment(state: dict, spec_sections: list[dict], section_id: str, candidate_id: str,
                     label_view_id: str, label_text: str, comparison_id: str | None) -> dict:
    """Deterministic checks of a station-identity claim. Returns the verifier evidence."""
    section = next((s for s in spec_sections if s.get("id") == section_id), None)
    if section is None:
        raise VerificationError("unknown_section", "The section is not part of this task.")
    if section_id in state["selected"]:
        raise VerificationError("section_already_selected",
                                "This section already has a selected line; only a person changes it.")
    candidates = state["catalog"].get(section_id, {}).get("candidates", [])
    candidate = next((c for c in candidates if c["candidate_id"] == candidate_id), None)
    if candidate is None or candidate.get("selectable") is not True:
        raise VerificationError("unsnapped_or_unknown_candidate",
                                "Only a traced, selectable candidate of this section can be assigned.")
    box = label_view_box(state, spec_sections, label_view_id)
    if box is None:
        recent = [v["view_id"] for v in state.get("views", [])][-5:]
        raise VerificationError("unknown_label_view",
                                "The label evidence must name a view returned in this task (view_region, "
                                "read_region, trace_corridor, or an inspection image id). Recent view ids: "
                                + (", ".join(recent) or "none; make one with view_region") + ".")
    roi = section["roi_px"]
    margin_x, margin_y = 0.1 * (roi[2] - roi[0]), 0.1 * (roi[3] - roi[1])
    if (box[2] < roi[0] - margin_x or box[0] > roi[2] + margin_x
            or box[3] < roi[1] - margin_y or box[1] > roi[3] + margin_y):
        raise VerificationError("label_view_not_at_section",
                                "The label view does not overlap the section's drawing panel.")
    conflicts = []
    for other_id, choice in state.get("model_choices", {}).items():
        if other_id == section_id:
            continue
        other = next((c for c in state["catalog"].get(other_id, {}).get("candidates", [])
                      if c["candidate_id"] == choice["candidate_id"]), None)
        if other is not None and same_ink(candidate, other):
            conflicts.append(other_id)
    for other_id, other_cid in state["selected"].items():
        other = next((c for c in state["catalog"].get(other_id, {}).get("candidates", [])
                      if c["candidate_id"] == other_cid), None)
        if other is not None and same_ink(candidate, other):
            conflicts.append(other_id)
    if conflicts:
        raise VerificationError("ink_already_assigned",
                                "The same ink is already assigned to " + ", ".join(sorted(conflicts)[:4]) + ".",
                                {"conflicting_sections": sorted(conflicts)[:16]})
    comparison = None
    if comparison_id is not None:
        comparison = state.get("comparisons", {}).get(comparison_id)
        if comparison is None or comparison["section_id"] != section_id or comparison["candidate_id"] != candidate_id:
            raise VerificationError("unknown_comparison",
                                    "The comparison must be one made in this task for this section and candidate.")
    support = candidate.get("source_support", {})
    return {"verifier": "station_assignment_v1", "passed": True,
            "checks": ["candidate_traced_from_ink_and_selectable", "label_view_overlaps_section",
                       "ink_not_assigned_to_another_section"]
                      + (["comparison_recorded"] if comparison else []),
            "label_view_id": label_view_id, "label_text": label_text,
            "label_view_crop_box_px": box, "candidate_model_traced": bool(candidate.get("model_traced")),
            "observed_row_fraction": support.get("observed_row_fraction"),
            "comparison": None if comparison is None else {
                "comparison_id": comparison_id, "matched_fraction": comparison["matched_fraction"]},
            "identity_certified": False}


# ------------------------------------------------------------ sheet setup

def long_lines(gray: np.ndarray, axis: int) -> list[float]:
    """Centres of straight dark lines that cover LONG_LINE_SHARE of the region along ``axis``.

    axis 0: horizontal lines (rows); axis 1: vertical lines (columns).
    """
    mask = gray < float(np.percentile(gray, 98)) - INK_CONTRAST
    lines = mask if axis == 0 else mask.T
    length = lines.shape[1]
    hits = []
    for index, line in enumerate(lines):
        padded = np.concatenate([[0], line.astype(np.int8), [0]])
        changes = np.flatnonzero(np.diff(padded))
        longest = int((changes[1::2] - changes[0::2]).max()) if len(changes) else 0
        if longest >= LONG_LINE_SHARE * length:
            hits.append(index)
    groups, current = [], []
    for index in hits:
        if current and index - current[-1] > 2:
            groups.append(current)
            current = []
        current.append(index)
    if current:
        groups.append(current)
    return [float(np.mean(g)) for g in groups if len(g) <= 8]


def grid_spacing(positions: list[float]) -> float | None:
    """Smallest spacing of which most line gaps are whole multiples (3 % tolerance)."""
    if len(positions) < 3:
        return None
    gaps = np.diff(sorted(positions))
    gaps = gaps[gaps >= 4]
    for unit in sorted(gaps):
        multiples = np.round(gaps / unit)
        close = (multiples >= 1) & (np.abs(gaps / unit - multiples) <= 0.03 * multiples)
        if close.mean() >= 0.5:
            return float(np.median(gaps[close] / multiples[close]))
    return None


def check_sheet_setup(image: np.ndarray, spec_sections: list[dict], setup: dict) -> dict:
    """Check a proposed scale and datum against the grid lines and the declared calibration."""
    left, top, right, bottom = clip_region(setup["region_px"], image.shape[1], image.shape[0])
    gray = image[top:bottom, left:right].mean(axis=2)
    rows = [top + v for v in long_lines(gray, 0)]
    columns = [left + v for v in long_lines(gray, 1)]
    ppm, unit = float(setup["pixels_per_metre"]), float(setup["grid_spacing_m"])
    expected = ppm * unit
    measured = {"horizontal_lines": grid_spacing(rows), "vertical_lines": grid_spacing(columns)}
    evidence = {"region_px": [left, top, right, bottom], "expected_grid_spacing_px": round(expected, 3),
                "measured_grid_spacing_px": {k: None if v is None else round(v, 3) for k, v in measured.items()},
                "long_horizontal_lines": len(rows), "long_vertical_lines": len(columns)}
    found = [v for v in measured.values() if v is not None]
    if not found:
        raise VerificationError("no_grid_to_check_scale",
                                "No regular grid of long straight lines was found in the region; the scale cannot be checked.",
                                evidence)
    for value in found:
        # A grid drawn every n units also satisfies the claim when the claimed
        # unit is a whole multiple of the measured spacing, or the reverse.
        ratio = expected / value
        nearest = max(1, round(ratio)) if ratio >= 1 else 1 / max(1, round(1 / ratio))
        if abs(ratio / nearest - 1) > GRID_SCALE_TOLERANCE:
            raise VerificationError("scale_disagrees_with_grid",
                                    f"Claimed grid spacing {expected:.1f} px; measured {value:.1f} px.", evidence)
    checks = ["grid_spacing_matches_scale"]

    def near(value, lines):
        return lines and min(abs(value - v) for v in lines) <= DATUM_TOLERANCE_PX

    view = setup["view"]
    datums = {"centreline_px": columns if view == "body" else rows,
              "baseline_px": rows, "x_origin_px": columns}
    for name, lines in datums.items():
        value = setup.get(name)
        if value is None:
            continue
        if not near(float(value), lines):
            raise VerificationError("datum_not_on_a_drawn_line",
                                    f"{name} = {value} px is not within {DATUM_TOLERANCE_PX:g} px of a long straight line.",
                                    evidence)
        checks.append(name + "_on_drawn_line")
    if view == "body":
        inside = [s for s in spec_sections
                  if left <= s["calibration"]["centerline_px"] < right and top <= s["calibration"]["baseline_px"] <= bottom]
        for section in inside:
            calibration = section["calibration"]
            if abs(calibration["pixels_per_metre"] / ppm - 1) > DECLARED_SCALE_TOLERANCE:
                raise VerificationError("disagrees_with_declared_calibration",
                                        f"Section {section['id']} declares {calibration['pixels_per_metre']:.3f} px/m.",
                                        evidence)
            for name, key in (("centreline_px", "centerline_px"), ("baseline_px", "baseline_px")):
                if setup.get(name) is not None and abs(float(setup[name]) - calibration[key]) > DATUM_TOLERANCE_PX:
                    raise VerificationError("disagrees_with_declared_calibration",
                                            f"Section {section['id']} declares {key} {calibration[key]:.1f} px.",
                                            evidence)
        if inside:
            checks.append("agrees_with_declared_section_calibration")
        evidence["declared_sections_checked"] = len(inside)
    return {"verifier": "sheet_setup_v1", "passed": True, "checks": checks, **evidence}


# ------------------------------------------------------- view comparison

def compare_with_plan(image: np.ndarray, section: dict, candidate: dict, setup: dict,
                      heights_m: list[float]) -> dict:
    """Body-plan half-breadths of a candidate against ink crossings on the plan-view station line.

    The plan view's waterlines are not identified, so a match means only that
    plan ink exists at the candidate's half-breadth; it is evidence, not proof.
    """
    if setup["view"] != "plan" or setup.get("centreline_px") is None or setup.get("x_origin_px") is None:
        raise VerificationError("setup_not_a_plan_view",
                                "A comparison needs an accepted plan-view setup with centreline_px and x_origin_px.")
    trace = dense_trace(candidate)
    if trace is None:
        raise VerificationError("candidate_without_trace", "The candidate has no traced corridor.")
    plan_ppm = float(setup["pixels_per_metre"])
    column = float(setup["x_origin_px"]) + int(setup.get("x_direction") or 1) * float(section["x_m"]) * plan_ppm
    left, top, right, bottom = setup["region_px"]
    if not left <= column < right:
        raise VerificationError("station_outside_plan_view", "The station position lies outside the plan-view region.")
    paper = float(np.percentile(image[top:bottom, left:right].mean(axis=2), 98))
    gray = image[top:bottom, int(round(column)) - 1:int(round(column)) + 2].mean(axis=2).min(axis=1)
    dark = gray < paper - INK_CONTRAST
    crossings = []
    for index in np.flatnonzero(dark & ~np.r_[False, dark[:-1]]):
        stop = index
        while stop + 1 < len(dark) and dark[stop + 1]:
            stop += 1
        row = top + (index + stop) / 2
        crossings.append(abs(row - float(setup["centreline_px"])) / plan_ppm)
    calibration = section["calibration"]
    ppm, baseline, centre = (float(calibration[k]) for k in ("pixels_per_metre", "baseline_px", "centerline_px"))
    tolerance = max(2.0 / plan_ppm, 2.0 / ppm)
    rows = []
    for z in heights_m:
        row = baseline - float(z) * ppm
        if not trace[0][0] <= row <= trace[0][-1]:
            rows.append({"z_m": z, "body_half_breadth_m": None, "nearest_plan_crossing_m": None, "matched": False})
            continue
        half = (float(np.interp(row, trace[0], trace[1])) - centre) / ppm
        nearest = min(crossings, key=lambda c: abs(c - half)) if crossings else None
        rows.append({"z_m": z, "body_half_breadth_m": round(half, 4),
                     "nearest_plan_crossing_m": None if nearest is None else round(nearest, 4),
                     "matched": nearest is not None and abs(nearest - half) <= tolerance})
    measured = [r for r in rows if r["body_half_breadth_m"] is not None]
    matched = sum(r["matched"] for r in measured)
    return {"heights": rows, "plan_column_px": round(column, 2), "plan_crossing_count": len(crossings),
            "tolerance_m": round(tolerance, 4),
            "matched_fraction": round(matched / len(measured), 4) if measured else 0.0,
            "interpretation": "Plan ink at the body-plan half-breadth; plan waterlines are not identified."}
