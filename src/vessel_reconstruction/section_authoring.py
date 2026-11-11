"""Model-authored section geometry (draft mode).

The model may write the shape of a section itself, whether ink exists or not:
as half-breadths at heights, as a blend of the two neighbouring sections, or as
a standard U/V form. This module turns that proposal into the same curve the
build uses for a traced section (``points_yz_m``: [half-breadth, height] pairs
in metres, heights increasing). Code only fairs the curve, clamps it to the
declared beam and depth, and reports what it changed as warnings. It refuses
only input that it cannot turn into a curve at all.

A model-authored section carries one source label: ``ai_inferred`` (no usable
ink) or ``ai_corrected`` (it replaces a traced line). This module has no image
or CAD code.
"""
from __future__ import annotations

import math

import numpy as np

# Source label of each section of a draft build.
SOURCE_LABELS = ("traced", "read", "repaired", "interpolated", "ai_inferred", "ai_corrected")
AUTHORED_LABELS = ("ai_inferred", "ai_corrected")
# A station curve measured by code on a scanned body plan (body_plan_intake): code-read ink,
# built from its points because it has no contour selection. Never model output.
READER_LABELS = ("read",)
# Curve sections that code fills in a draft: the vessel-table form fit
# (form_fit.py) labels a station it fills ``interpolated``. Never model output.
TABLE_FIT_LABELS = ("interpolated",)
FORMS = ("half_breadths", "blend", "standard_form")
SHAPES = ("U", "V")
# Bounds of the model's input. Few points are enough for a fair section; more
# than 24 is a trace, not a proposal.
MIN_OFFSETS, MAX_OFFSETS = 5, 24
FULLNESS_RANGE = (0.5, 1.5)
MAX_DEADRISE_DEG = 60.0
MAX_BASIS_CHARS = 300
MAX_DIMENSION_M = 1000.0
# Samples of the finished curve (the run record needs at least 5).
CURVE_SAMPLES = 65
# Passes of the [1, 2, 1] / 4 smoothing that fairs the resampled curve.
SMOOTHING_PASSES = 2
# Points of a standard form polyline before resampling.
FORM_SAMPLES = 200
# A section area further than this share from the neighbours' interpolated
# area is reported as unfair (a warning, not a refusal).
UNFAIR_AREA_SHARE = 0.5
# Heights closer than this are one height (metres).
HEIGHT_RESOLUTION_M = 1e-6


class ProposalError(ValueError):
    """A proposal that cannot become a curve; the message says what to change."""


def _finite(value, low=-math.inf, high=math.inf) -> bool:
    return type(value) in (int, float) and math.isfinite(value) and low <= value <= high


def check_proposal_arguments(arguments: dict) -> None:
    """Strict shape and bounds of the propose_section arguments (no geometry yet)."""
    form = arguments.get("form")
    if form not in FORMS:
        raise ProposalError("form must be half_breadths, blend or standard_form.")
    basis = arguments.get("basis")
    if type(basis) is not str or not 1 <= len(basis) <= MAX_BASIS_CHARS or not basis.isprintable():
        raise ProposalError(f"basis must be one printable line of 1-{MAX_BASIS_CHARS} characters.")
    replaces = arguments.get("replaces", "none")
    if type(replaces) is not str or not 1 <= len(replaces) <= 64:
        raise ProposalError("replaces must be 'none' or the candidate id the proposal corrects.")
    allowed = {"half_breadths": {"offsets_m"}, "blend": {"fullness"},
               "standard_form": {"shape", "beam_m", "draft_m", "bilge_radius_m", "deadrise_deg"}}[form]
    given = {k for k in ("offsets_m", "fullness", "shape", "beam_m", "draft_m", "bilge_radius_m", "deadrise_deg")
             if arguments.get(k) is not None}
    if given - allowed:
        raise ProposalError(f"Form {form} does not take: {', '.join(sorted(given - allowed))}.")
    if form == "half_breadths":
        offsets = arguments.get("offsets_m")
        if (type(offsets) is not list or not MIN_OFFSETS <= len(offsets) <= MAX_OFFSETS
                or any(type(p) is not list or len(p) != 2 or not all(_finite(v, -MAX_DIMENSION_M, MAX_DIMENSION_M)
                                                                     for v in p) for p in offsets)):
            raise ProposalError(f"offsets_m must be {MIN_OFFSETS}-{MAX_OFFSETS} [height_m, half_breadth_m] pairs.")
    if form == "blend" and arguments.get("fullness") is not None:
        if not _finite(arguments["fullness"], *FULLNESS_RANGE):
            raise ProposalError(f"fullness must be in [{FULLNESS_RANGE[0]}, {FULLNESS_RANGE[1]}]; 1 is the plain blend.")
    if form == "standard_form":
        if arguments.get("shape") not in SHAPES:
            raise ProposalError("shape must be U or V.")
        if not _finite(arguments.get("beam_m"), 1e-3, MAX_DIMENSION_M):
            raise ProposalError("beam_m (full beam at this section) is required and must be positive.")
        if not _finite(arguments.get("draft_m"), 1e-3, MAX_DIMENSION_M):
            raise ProposalError("draft_m (keel to design waterline) is required and must be positive.")
        if arguments.get("bilge_radius_m") is not None and not _finite(arguments["bilge_radius_m"], 0, MAX_DIMENSION_M):
            raise ProposalError("bilge_radius_m must be zero or positive.")
        if arguments.get("deadrise_deg") is not None and not _finite(arguments["deadrise_deg"], 0, MAX_DEADRISE_DEG):
            raise ProposalError(f"deadrise_deg must be in [0, {MAX_DEADRISE_DEG:g}].")


def check_authored(authored, *, table_fit: bool = False) -> bool:
    """Shape of the ``authored`` record of a draft revision section.

    The ``interpolated`` label (TABLE_FIT_LABELS) is accepted only with ``table_fit``:
    the caller passes it when the vessel-table form fit filled the section (its draft
    guess is a bridged_gap or dropped_end). A model-authored section can therefore
    never be labelled as interpolated.
    """
    if type(authored) is not dict or set(authored) != {"source_label", "basis", "points_yz_m"}:
        return False
    points = authored["points_yz_m"]
    allowed = AUTHORED_LABELS + READER_LABELS + (TABLE_FIT_LABELS if table_fit else ())
    if (authored["source_label"] not in allowed or type(authored["basis"]) is not str
            or not 1 <= len(authored["basis"]) <= MAX_BASIS_CHARS
            or type(points) is not list or not 5 <= len(points) <= 1025):
        return False
    if any(type(p) is not list or len(p) != 2 or not all(_finite(v, -MAX_DIMENSION_M, MAX_DIMENSION_M) for v in p)
           for p in points):
        return False
    heights = [p[1] for p in points]
    return all(p[0] >= 0 for p in points) and all(b > a for a, b in zip(heights, heights[1:]))


def _smooth(values: np.ndarray) -> np.ndarray:
    """[1, 2, 1] / 4 smoothing of the interior points; the end points stay."""
    smoothed = values.copy()
    for _ in range(SMOOTHING_PASSES):
        smoothed[1:-1] = (smoothed[:-2] + 2 * smoothed[1:-1] + smoothed[2:]) / 4
    return smoothed


def _resample(z: np.ndarray, y: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """A shape-preserving (PCHIP) curve through the points, at CURVE_SAMPLES heights."""
    from scipy.interpolate import PchipInterpolator
    heights = np.linspace(z[0], z[-1], CURVE_SAMPLES)
    return heights, PchipInterpolator(z, y)(heights)


def _area(points: np.ndarray) -> float:
    """Half-section area (m2) of a [y, z] curve with increasing heights."""
    y, z = points[:, 0], points[:, 1]
    return float(np.sum((y[1:] + y[:-1]) * np.diff(z)) / 2)


def finish_curve(z, y, *, z_limits, half_beam_limit=None, smooth=True) -> tuple[list, list[str], dict]:
    """Fair, clamp and close one curve. Returns (points_yz_m, warnings, checks)."""
    warnings = []
    z, y = np.asarray(z, dtype=float), np.asarray(y, dtype=float)
    order = np.argsort(z, kind="stable")
    z, y = z[order], y[order]
    low, high = z_limits
    if z[0] < low - HEIGHT_RESOLUTION_M or z[-1] > high + HEIGHT_RESOLUTION_M:
        warnings.append(f"Heights clamped to the declared section range {low:g}..{high:g} m.")
        z = np.clip(z, low, high)
    keep = np.concatenate([[True], np.diff(z) > HEIGHT_RESOLUTION_M])
    if not keep.all():
        warnings.append(f"{int((~keep).sum())} point(s) at a repeated height dropped.")
        z, y = z[keep], y[keep]
    if len(z) < 2 or z[-1] - z[0] <= HEIGHT_RESOLUTION_M:
        raise ProposalError("The proposal spans no height inside the declared section range.")
    if (y < 0).any():
        warnings.append("Negative half-breadths set to 0 (the centreline).")
        y = np.maximum(y, 0)
    heights, breadths = _resample(z, y)
    if smooth:
        faired = _smooth(breadths)
        change = float(np.max(np.abs(faired - breadths)))
        if change > 0.01 * max(float(breadths.max()), 1e-9):
            warnings.append(f"Fairing moved the curve by up to {change:.3f} m.")
        breadths = faired
    breadths = np.maximum(breadths, 0)
    if half_beam_limit is not None and breadths.max() > half_beam_limit:
        warnings.append(f"Half-breadths clamped to the declared half beam {half_beam_limit:g} m.")
        breadths = np.minimum(breadths, half_beam_limit)
    closure = "keel_on_centreline" if breadths[0] <= HEIGHT_RESOLUTION_M else "flat_bottom_to_centreline"
    if closure == "flat_bottom_to_centreline":
        warnings.append(f"The lowest point has half-breadth {breadths[0]:.3f} m; "
                        "the build closes it to the centreline with a flat bottom.")
    if heights[-1] < high - HEIGHT_RESOLUTION_M:
        warnings.append(f"The curve ends at {heights[-1]:g} m, below the declared top {high:g} m.")
    points = np.column_stack([breadths, heights])
    checks = {"closure": closure, "half_breadth_max_m": round(float(breadths.max()), 4),
              "height_range_m": [round(float(heights[0]), 4), round(float(heights[-1]), 4)],
              "area_m2": round(_area(points), 4)}
    return [[round(float(a), 6), round(float(b), 6)] for a, b in points], warnings, checks


def standard_form_curve(shape: str, beam_m: float, draft_m: float, *, z_keel: float, z_top: float,
                        bilge_radius_m: float | None = None, deadrise_deg: float | None = None):
    """Polyline (z, y) of a standard section: a bottom rising at the deadrise
    angle from the keel, a bilge arc tangent to it and to a vertical side at the
    half beam, then the vertical side to the top. U: rounded bilge, small
    deadrise by default. V: hard chine (radius 0) and 20 degrees by default."""
    warnings = []
    half = beam_m / 2
    deadrise = math.radians(deadrise_deg if deadrise_deg is not None else (0.0 if shape == "U" else 20.0))
    radius = bilge_radius_m if bilge_radius_m is not None else (0.3 * min(half, draft_m) if shape == "U" else 0.0)
    rise = half * math.tan(deadrise)
    # The bilge must finish below the waterline and inside the half beam.
    largest = max(0.0, min(half, draft_m - rise))
    if radius > largest:
        warnings.append(f"Bilge radius reduced from {radius:g} m to {largest:g} m to fit the beam and draft.")
        radius = largest
    sine, cosine = math.sin(deadrise), math.cos(deadrise)
    centre_y = half - radius
    centre_z = z_keel + (radius + centre_y * sine) / cosine
    tangent = (centre_y + radius * sine, centre_z - radius * cosine)
    bottom_t = np.linspace(0, 1, FORM_SAMPLES // 4)
    ys = list(bottom_t * tangent[0])
    zs = list(z_keel + bottom_t * (tangent[1] - z_keel))
    if radius > 0:
        angles = np.linspace(deadrise - math.pi / 2, 0, FORM_SAMPLES // 2)[1:]
        ys += list(centre_y + radius * np.cos(angles))
        zs += list(centre_z + radius * np.sin(angles))
    top = max(z_top, zs[-1])
    side = np.linspace(zs[-1], top, FORM_SAMPLES // 4)[1:]
    ys += [half] * len(side)
    zs += list(side)
    z, y = np.asarray(zs), np.asarray(ys)
    if z[-1] > z_top + HEIGHT_RESOLUTION_M:
        warnings.append("The bilge rises above the declared section top; the form is cut there.")
    # A flat bottom has many points at the keel height: keep the outermost
    # one, so the curve is a function of height (the build closes it flat).
    keep = np.concatenate([np.diff(z) > HEIGHT_RESOLUTION_M, [True]])
    return z[keep], y[keep], warnings


def blend_curve(lower: tuple[float, list] | None, upper: tuple[float, list] | None, x_m: float,
                fullness: float = 1.0) -> tuple[np.ndarray, np.ndarray, list[str]]:
    """Linear blend (by station position) of the neighbouring curves, scaled by fullness."""
    neighbours = [n for n in (lower, upper) if n is not None]
    if not neighbours:
        raise ProposalError("No neighbouring section has a usable curve to blend; use half_breadths or standard_form.")
    warnings = []
    if len(neighbours) == 1:
        warnings.append("Only one neighbouring section has a curve; its shape is used.")
        lower = upper = neighbours[0]
    weight = 0.0 if lower[0] == upper[0] else (x_m - lower[0]) / (upper[0] - lower[0])
    weight = min(1.0, max(0.0, weight))
    t = np.linspace(0, 1, CURVE_SAMPLES)
    profiles = []
    for _, points in (lower, upper):
        array = np.asarray(points, dtype=float)
        z = array[0, 1] + t * (array[-1, 1] - array[0, 1])
        profiles.append(np.column_stack([np.interp(z, array[:, 1], array[:, 0]), z]))
    blended = (1 - weight) * profiles[0] + weight * profiles[1]
    return blended[:, 1], blended[:, 0] * fullness, warnings


def author_section(arguments: dict, *, x_m: float, z_limits: tuple[float, float],
                   half_beam_limit: float | None = None, depth_limit: float | None = None,
                   lower=None, upper=None) -> dict:
    """The finished curve of one proposal, with warnings and sanity checks.

    ``lower`` and ``upper`` are the nearest neighbouring sections with a curve,
    as (x_m, points_yz_m), or None. ``depth_limit`` lowers the top of the
    declared section range when the vessel depth is declared.
    """
    check_proposal_arguments(arguments)
    low, high = z_limits
    if depth_limit is not None:
        # Heights are measured from the baseline (z = 0), as the vessel depth is.
        high = min(high, depth_limit)
        if high <= low:
            raise ProposalError("The declared depth lies below this section's range.")
    form = arguments["form"]
    if form == "half_breadths":
        pairs = np.asarray(arguments["offsets_m"], dtype=float)
        z, y, warnings = pairs[:, 0], pairs[:, 1], []
    elif form == "blend":
        z, y, warnings = blend_curve(lower, upper, x_m, arguments.get("fullness") or 1.0)
    else:
        z, y, warnings = standard_form_curve(arguments["shape"], arguments["beam_m"], arguments["draft_m"],
                                             z_keel=low, z_top=high, bilge_radius_m=arguments.get("bilge_radius_m"),
                                             deadrise_deg=arguments.get("deadrise_deg"))
    points, more, checks = finish_curve(z, y, z_limits=(low, high), half_beam_limit=half_beam_limit,
                                        smooth=form == "half_breadths")
    warnings += more
    neighbour_areas = [_area(np.asarray(n[1], dtype=float)) for n in (lower, upper) if n is not None]
    if neighbour_areas:
        expected = float(np.mean(neighbour_areas))
        checks["neighbour_area_m2"] = round(expected, 4)
        if expected > 0 and abs(checks["area_m2"] - expected) > UNFAIR_AREA_SHARE * expected:
            warnings.append(f"Section area {checks['area_m2']:.3f} m2 differs from its neighbours' "
                            f"{expected:.3f} m2 by more than {UNFAIR_AREA_SHARE:.0%}; check it is not unfair.")
    return {"points_yz_m": points, "warnings": warnings[:16], "checks": checks}
