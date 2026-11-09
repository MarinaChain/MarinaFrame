"""Drawing fit of a whole draft in one frame that code measures on the sheet (no truth, no model reading).

The body-plan fit (``fit_feedback.score``) measures a draft only in its own
reading's body-plan frame. Two readings of one sheet can each fit their own
frame: a reading that puts x = 0 3 m forward of the hull's aft end
(shipd-1-08158-3v-L1 Sonnet live) traces the same body-plan ink as a correct
one and scored higher (0.919 against 0.872; truth 11.9 against 5.3 % RMS).

This score measures every draft of a task in one reference frame:

- body plan: each station curve in its body-plan panel (the draft's own panel
  calibration: body datums are snapped to drawn lines in every reading);
- profile: region from the intake, x = 0 at the outline's aft extreme (the
  frame the sheet-only reading states), z = 0 on the outline's lowest line,
  the draft's scale; keel and top heights at each station and the stem and
  stern ends at each height;
- half-breadth plan: region from the intake, centreline on the row where the
  plan outline's two ends meet it, x origin of the profile; each waterline at
  each station.

Cells are scored as in ``whole_vessel_score``; the draft fit is the mean of
the three view fits (a view the sheet lacks scores 0 for every draft). Equal
view weights, not cell counts: on 47 blurred L1 drafts the cell-weighted
mean, dominated by body-plan cells, ranked 69 % of draft pairs as truth does,
the equal mean 84 % (L0, 83 drafts: 85 % both; docs/HULL_SELECTION.md). The
frame takes nothing from the model's reading except the scale, so the score
can rank drafts from different readings.
"""
from __future__ import annotations

import numpy as np

from . import investigation as inv
from . import view_measure
from .fit_feedback import drawn_stations, measurement_table
from scipy import ndimage

from .vessel_description import OUTLINE_INK, _bottom_line_centre, _gray, _region, view_skew
from .whole_vessel_score import add_order_residuals, scoreboard

# Views of the draft fit, weighted equally.
FIT_VIEWS = ("body_plan", "profile", "half_breadth_plan")
# Columns at each end of the plan outline whose ink rows give the centreline row.
PLAN_END_COLUMNS = 6
# The plan view is used only when most of its outline ink lies on one side of
# the centreline row (half-breadths drawn upwards, as view_measure measures them).
PLAN_SIDE_SHARE = 0.8
# A view's outline is made of dark components at least this share of its region's width long.
OUTLINE_SHARE = 0.25
# The plan centreline estimate snaps to a drawn horizontal line within this many pixels.
CENTRELINE_SNAP_PX = 8.0
# Stem and stern ends are read at this many heights between keel and top.
END_HEIGHTS = 24
# Profile and plan share an x origin when their regions overlap by this share of the narrower width.
SHARED_X_SHARE = 0.8
# Profile grid rows at least this high above the baseline (m) are waterlines;
# the baseline itself is not a plan-view waterline.
MIN_WATERLINE_Z_M = 0.25


def _hint(hints, *labels):
    return next((list(h["region_px"]) for h in hints or [] if h.get("label") in labels and h.get("region_px")), None)


def view_outline(image, region) -> tuple[np.ndarray, list]:
    """Dark hull outline of a long view, and the view's box widened to the outline's full length.

    The intake can cut a long view short (shipd-1-09867-3v-L0: a profile
    region of the fore 62 m only). The outline is taken on the region's rows
    across the whole sheet: the dark components that reach into the region
    and are at least OUTLINE_SHARE of its width long.
    """
    left, top, right, bottom = _region(region, image.shape)
    band = _gray(image[top:bottom]) < OUTLINE_INK
    labels, _ = ndimage.label(band, structure=np.ones((3, 3)))
    keep = []
    for index, box in enumerate(ndimage.find_objects(labels), 1):
        if box is None or box[1].stop - box[1].start < OUTLINE_SHARE * (right - left):
            continue
        if box[1].stop > left and box[1].start < right:
            keep.append(index)
    outline = np.isin(labels, keep)
    columns = np.flatnonzero(outline.any(axis=0))
    if len(columns):
        left, right = min(left, int(columns[0])), max(right, int(columns[-1]) + 1)
    return outline[:, left:right], [left, top, right, bottom]


def profile_view(image, hints, pixels_per_metre: float) -> dict | None:
    """Profile view in the reference frame: x = 0 at the outline's aft extreme, z = 0 on its lowest line."""
    region = _hint(hints, "profile")
    if region is None:
        return None
    outline, box = view_outline(image, region)
    left, top = box[0], box[1]
    columns = np.flatnonzero(outline.any(axis=0))
    keel = _bottom_line_centre(outline, view_skew(image, box))
    if not len(columns) or keel is None:
        return None
    baseline = float(top + keel)
    calibration = {"pixels_per_metre": float(pixels_per_metre), "x_origin_px": float(left + columns[0]),
                   "baseline_px": baseline}
    # The drawn waterlines are the profile's horizontal grid rows above the baseline.
    rows = inv.datum_lines(_gray(image[box[1]:box[3], box[0]:box[2]]), 0)
    heights = sorted({round((baseline - (box[1] + row)) / float(pixels_per_metre), 3) for row in rows})
    return {"view_id": "profile", "kind": "profile", "roi_px": box, "calibration": calibration,
            "waterlines_z_m": [z for z in heights if z >= MIN_WATERLINE_Z_M]}


def plan_view(image, hints, pixels_per_metre: float, profile: dict | None) -> dict | None:
    """Half-breadth plan in the reference frame, or None when its centreline or side is unclear."""
    region = _hint(hints, "half_breadth", "half_breadth_plan", "plan")
    if region is None:
        return None
    outline, box = view_outline(image, region)
    left, top = box[0], box[1]
    columns = np.flatnonzero(outline.any(axis=0))
    if len(columns) < 2 * PLAN_END_COLUMNS:
        return None
    # The waterlines end on the centreline: its row is the lowest ink at the
    # outline's two ends, snapped to a drawn line there (the CL is drawn).
    ends = np.concatenate([columns[:PLAN_END_COLUMNS], columns[-PLAN_END_COLUMNS:]])
    centre = float(np.flatnonzero(outline[:, ends].any(axis=1)).max())
    lines = [box[1] - top + row for row in inv.datum_lines(_gray(image[box[1]:box[3], box[0]:box[2]]), 0)]
    nearest = min(lines, key=lambda row: abs(row - centre), default=None)
    if nearest is not None and abs(nearest - centre) <= CENTRELINE_SNAP_PX:
        centre = float(nearest)
    ink_rows = np.nonzero(outline)[0]
    if np.mean(ink_rows < centre - 1) < PLAN_SIDE_SHARE:
        return None
    origin = float(left + columns[0])
    if profile is not None:
        p_left, _, p_right, _ = profile["roi_px"]
        overlap = min(p_right, box[2]) - max(p_left, box[0])
        if overlap >= SHARED_X_SHARE * min(p_right - p_left, box[2] - box[0]):
            origin = profile["calibration"]["x_origin_px"]
    calibration = {"pixels_per_metre": float(pixels_per_metre), "x_origin_px": origin, "centerline_px": top + centre}
    return {"view_id": "half_breadth_plan", "kind": "half_breadth_plan", "roi_px": box, "calibration": calibration}


def reference_views(image, hints, pixels_per_metre: float) -> dict:
    """Profile and half-breadth plan views measured by code, keyed by kind (either may be missing)."""
    views = {}
    profile = profile_view(image, hints, pixels_per_metre)
    if profile is not None:
        views["profile"] = profile
    plan = plan_view(image, hints, pixels_per_metre, profile)
    if plan is not None:
        views["half_breadth_plan"] = plan
    return views


def _end_x(xs: np.ndarray, breadths: np.ndarray) -> float:
    """x where the hull starts along ``xs`` (stations in order from the end inward): breadth falls to 0.

    ``breadths`` is NaN or 0 where the hull does not reach the height. The end
    lies between the last station without breadth and the first with it, on
    the line through the first two stations with breadth (clamped to that gap).
    """
    present = np.flatnonzero(np.isfinite(breadths) & (breadths > 0))
    if not len(present):
        return float("nan")
    first = present[0]
    if first == 0:
        return float(xs[0])
    before = float(xs[first - 1])
    x0, b0 = float(xs[first]), float(breadths[first])
    if first + 1 < len(xs) and np.isfinite(breadths[first + 1]) and breadths[first + 1] > b0:
        x1, b1 = float(xs[first + 1]), float(breadths[first + 1])
        estimate = x0 - b0 * (x1 - x0) / (b1 - b0)
    else:
        estimate = 0.5 * (before + x0)
    low, high = min(before, x0), max(before, x0)
    return float(min(max(estimate, low), high))


def end_polylines(table: view_measure.VesselTable) -> tuple[np.ndarray, np.ndarray]:
    """Stern and stem (x, z) polylines of a table: where the hull starts at each height, from each end."""
    keel, top = np.nanmin(table.keel_z_m), np.nanmax(table.top_z_m)
    stern, stem = [], []
    for z in np.linspace(keel, top, END_HEIGHTS + 2)[1:-1]:
        breadths = np.array([table.station_hb(i, float(z)) for i in range(len(table.x_m))])
        aft = _end_x(table.x_m, breadths)
        fore = _end_x(table.x_m[::-1], breadths[::-1])
        if np.isfinite(aft):
            stern.append((aft, z))
        if np.isfinite(fore):
            stem.append((fore, z))
    return np.array(stern).reshape(-1, 2), np.array(stem).reshape(-1, 2)


def whole_table(table, waterlines_z_m) -> view_measure.VesselTable:
    """Measurement table of every row (hull ends included) at the drawn waterlines, with stem and stern ends."""
    rows = [np.asarray(row.points_yz_m, dtype=float) for row in table.stations]
    heights = list(waterlines_z_m) or list(table.waterlines_z_m)
    measured = view_measure.VesselTable.from_rows([row.id for row in table.stations],
                                                  [row.x_m for row in table.stations], rows, heights)
    measured.stern_xz_m, measured.stem_xz_m = end_polylines(measured)
    return measured


def score(table, spec: dict, image, hints, pixels_per_metre: float, half_beam_m: float) -> dict:
    """Scoreboard of a vessel_model table in the body plan (own panels) and the reference profile and plan."""
    grey = image[..., :3].mean(axis=2) if image.ndim == 3 else image
    drawn = drawn_stations(table)
    cells = []
    if drawn is not None:
        body = measurement_table(drawn)
        body_cells = view_measure.measure_views(body, view_measure.views_from_spec(spec), grey,
                                                half_beam_m=half_beam_m)
        add_order_residuals(body_cells, body)
        cells += body_cells
    views = reference_views(image, hints, pixels_per_metre)
    if views:
        heights = views.get("profile", {}).get("waterlines_z_m", [])
        cells += view_measure.measure_views(whole_table(table, heights), views, grey, half_beam_m=half_beam_m)
    board = scoreboard(cells, half_beam_m)
    board["method"] = "draft_fit_v1"
    fits = [(board["views"].get(kind) or {}).get("fit") for kind in FIT_VIEWS]
    board["draft_fit"] = round(sum(fit or 0.0 for fit in fits) / len(FIT_VIEWS), 4)
    board["reference_views"] = {kind: view["calibration"] for kind, view in views.items()}
    return board


def summary(board: dict) -> dict:
    """Combined fit and the fit of each view (compact, for state and logs)."""
    return {"draft_fit": board.get("draft_fit"),
            **{f"fit_{kind}": stats.get("fit") for kind, stats in board.get("views", {}).items()}}


def task_score(tools, table) -> dict:
    """Draft fit of a task's vessel_model table (the summary, with the reference frame used).

    Needs ``fit_feedback.score`` to have set the task's ``score_half_beam_m``.
    A failure is reported, never raised: the score only ranks drafts.
    """
    try:
        image, _, _ = tools._source()
        sections = tools.spec.get("sections") or []
        scale = float(sections[0]["calibration"]["pixels_per_metre"])
        board = score(table, tools.spec, image, tools.intake_hints(), scale, float(tools.state["score_half_beam_m"]))
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        return {"draft_fit": None, "error": f"{type(exc).__name__}: {exc}"[:300]}
    return {**summary(board), "reference_views": board["reference_views"]}
