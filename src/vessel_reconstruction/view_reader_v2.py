"""Plan and profile view reader that does not use a stored hull prediction.

The first three-view reader (``three_view_evidence``) searched the plan view for
ink near the stored hull's predicted breadth, so a wrong hull chose the wrong
ink. This reader reads each view from the drawing alone:

- Sheet level: the sheet's small rotation (``view_skew``) is removed by
  resampling each view, so one levelled row is one height or one breadth.
- Profile: dark hull ink (lighter grid, baseline and centreline excluded by
  tone) in the large outline components. In each column the outer edge of the
  lowest run, less half a line, is the keel line and that of the highest run
  the deck/sheer line; in each row the first and last runs give the stern and
  stem. z = 0 is the drawn baseline (BL) row when it lies within
  BASELINE_MATCH_PX of the lowest keel ink, else that ink; x = 0 is the
  aftmost stern ink.
- Waterline heights: light grid rows of the profile that have a label beside
  the view (the "WL" text left of it) and lie on the grid spacing. A label with
  no visible row still gives a row when it lies on the spacing.
- Plan: dark runs above the centreline row in each column. A waterline ends
  on the centreline where the profile outline crosses its height, so each
  curve is named at its own end: a few line widths inside that x, the curves
  that end nearer lie nearer the centreline, which ranks the runs. Ends closer
  together than SEED_TIE_LW line widths cannot be ordered and give no name.
  A named curve is followed column by column along its own line. It stops at
  a bunch of curves (one long run), at a crossing or split (two runs on its
  line) and outside the profile's keel-to-deck span. Where every other curve
  present holds its own run, the one run left names the last curve
  (exclusion). Curves followed from both ends must agree; one-end names are
  labelled ``repaired``; two curves on one run abstain there.

No order from the centreline is assumed: hulls with tumblehome or crossing
waterlines (shipd-1-00679, shipd-1-08158) change that order along the length.
Every breadth is the distance of an ink run above the centreline row, so it is
positive by construction. Unsure reads are abstentions with a reason; they are
never clamped or filled. No truth, no model and no stored hull is read.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from scipy import ndimage

from .vessel_description import view_skew

METHOD = "view_reader_v2"

# Ink tones. Hull lines are the darkest ink; grid, baseline and centreline are
# lighter. A pixel is hull ink below dark + HULL_TONE_SHARE * (paper - dark).
# 0.35 separates the 128-tone baseline/centreline from blurred hull cores (<95)
# on L0 and L1 sheets.
HULL_TONE_SHARE = 0.35
PAPER_PERCENTILE = 90
DARK_PERCENTILE = 0.5
# A light line pixel is at least this much darker than the paper (grid tone 205-210 on 250 paper).
LIGHT_CONTRAST = 15.0
# A component of hull ink belongs to the outline when it is at least this share of the view wide.
OUTLINE_SHARE = 0.25
# A grid row is light ink over at least this share of the view's width.
GRID_ROW_SHARE = 0.5
# The centreline (dash-dot on degraded sheets) is any ink over at least this share.
CENTRELINE_ROW_SHARE = 0.4
# Waterline labels sit left of the view: this many pixels wide, this many rows either side of the row.
LABEL_BOX_PX = (80, 6)
LABEL_MIN_PIXELS = 6
# Label text is grey and thin: its ink is below dark + LABEL_TONE_SHARE * (paper - dark).
LABEL_TONE_SHARE = 0.6
# The drawn baseline is z = 0 when it lies within this many pixels of the lowest hull ink.
BASELINE_MATCH_PX = 3.0
# A labelled row must lie within this share of the grid spacing of a whole multiple.
GRID_SNAP_SHARE = 0.1
# Rows nearer the baseline than this (m) are the baseline itself, not a waterline.
MIN_WATERLINE_Z_M = 0.25
# A run longer than this many line widths runs along the scan (tangent): its centre is not a position.
TANGENT_FACTOR = 2.5
# Scans keep this many line widths away from the centreline row.
CENTRELINE_CLEARANCE_LW = 1.0
# A curve is named at its end on the centreline: SEED_OFFSET_LW line widths inside the profile's end x,
# ranked from the centreline by the curves that end nearer, if within SEED_MAX_Y_LW line widths of it
# and no other curve ends within SEED_TIE_LW line widths.
SEED_OFFSET_LW = 2.0
SEED_MAX_Y_LW = 8.0
SEED_TIE_LW = 3.0
# A waterline shows in the plan where it lies more than EXISTS_BAND_LW line widths inside the
# profile's keel and deck; exclusion naming runs at most EXCLUSION_PASSES times.
EXISTS_BAND_LW = 1.5
EXCLUSION_PASSES = 3
# A waterline end within this many line widths of the profile's deck height is on the deck line.
DECK_END_LW = 2.0
# Tracking: a curve is followed for at most this gap (px) without a named run, predicted
# from its last TRACK_POINTS named runs, and matched within max(TRACK_TOL_PX, TRACK_TOL_LW * lw).
TRACK_GAP_PX = 12
TRACK_POINTS = 6
TRACK_TOL_PX = 3.0
TRACK_TOL_LW = 1.2
# Curves named on runs closer than this (px) share ink.
SHARED_INK_PX = 1.0
# The sweeps from the two ends must agree within this many pixels.
SWEEP_AGREE_PX = 1.0
# Evidence points are emitted every SAMPLE_STEP_M along x and at PROFILE_END_HEIGHTS heights.
SAMPLE_STEP_M = 0.5
PROFILE_END_HEIGHTS = 24
DEFAULT_LINE_WIDTH_PX = 3.0

SETTINGS = {name: value for name, value in dict(globals()).items()
            if name.isupper() and isinstance(value, (int, float, tuple))}


# --------------------------------------------------------------------------
# Sheet helpers
# --------------------------------------------------------------------------

@dataclass
class Levelled:
    """A view resampled so that a drawn horizontal line is one row."""

    crop: np.ndarray
    left: int
    top: int
    slope: float
    centre_x: float

    def sheet_xy(self, column: float, row: float) -> tuple[float, float]:
        x = self.left + column
        return float(x), float(self.top + row + self.slope * (x - self.centre_x))


def levelled(grey: np.ndarray, roi, slope: float, centre_x: float) -> Levelled:
    left, top, right, bottom = (int(round(v)) for v in roi)
    left, top = max(0, left), max(0, top)
    right, bottom = min(grey.shape[1], right), min(grey.shape[0], bottom)
    rows, columns = np.mgrid[0:bottom - top, 0:right - left].astype(float)
    sheet_x = columns + left
    sheet_y = rows + top + slope * (sheet_x - centre_x)
    crop = ndimage.map_coordinates(grey, [sheet_y, sheet_x], order=1, mode="nearest")
    return Levelled(crop, left, top, slope, centre_x)


@dataclass
class Tones:
    paper: float
    dark: float

    @property
    def hull(self) -> float:
        return self.dark + HULL_TONE_SHARE * (self.paper - self.dark)


def tones(crop: np.ndarray) -> Tones:
    return Tones(float(np.percentile(crop, PAPER_PERCENTILE)), float(np.percentile(crop, DARK_PERCENTILE)))


def runs_1d(values: np.ndarray, threshold: float, offset: float = 0.0) -> list[tuple[float, float, float]]:
    """(start, end, centroid) of the runs below ``threshold``; positions are pixel centres + offset."""
    ink = values < threshold
    edges = np.flatnonzero(np.diff(np.concatenate([[0], ink.astype(int), [0]])))
    runs = []
    for a, b in zip(edges[0::2], edges[1::2] - 1):
        weight = threshold - values[a:b + 1]
        positions = np.arange(a, b + 1) + 0.5 + offset
        runs.append((float(positions[0]), float(positions[-1]), float(np.sum(positions * weight) / np.sum(weight))))
    return runs


def outline_mask(crop: np.ndarray, threshold: float) -> np.ndarray:
    """Hull ink in components at least OUTLINE_SHARE of the view wide (text and specks dropped)."""
    ink = crop < threshold
    labels, _ = ndimage.label(ink, structure=np.ones((3, 3)))
    keep = [index for index, box in enumerate(ndimage.find_objects(labels), 1)
            if box is not None and box[1].stop - box[1].start >= OUTLINE_SHARE * crop.shape[1]]
    return np.isin(labels, keep)


def line_width(crop: np.ndarray, mask: np.ndarray, threshold: float) -> float:
    lengths = []
    for column in np.linspace(2, crop.shape[1] - 3, 40).astype(int):
        values = np.where(mask[:, column], crop[:, column], 255.0)
        lengths += [end - start + 1 for start, end, _ in runs_1d(values, threshold) if end - start + 1 <= 8]
    return float(np.median(lengths)) if lengths else DEFAULT_LINE_WIDTH_PX


def masked_runs(crop, mask, threshold, index, axis):
    """Runs of outline ink along one column (axis 0) or row (axis 1) of the levelled crop."""
    if axis == 0:
        values = np.where(mask[:, index], crop[:, index], 255.0)
    else:
        values = np.where(mask[index, :], crop[index, :], 255.0)
    return runs_1d(values, threshold)


# --------------------------------------------------------------------------
# Profile
# --------------------------------------------------------------------------

@dataclass
class ProfileReading:
    ppm: float
    x_origin_px: float          # levelled column of x = 0 in the profile crop
    baseline_row: float         # levelled row of z = 0
    line_width_px: float
    x_m: np.ndarray             # one per crop column
    keel_z_m: np.ndarray        # NaN where abstained or outside the hull
    top_z_m: np.ndarray
    keel_status: list
    top_status: list
    waterlines: list            # [{"id", "z_m", "row", "label", "grid_row"}]
    waterline_status: dict
    view: Levelled = field(repr=False, default=None)
    tones: Tones = None
    mask: np.ndarray = field(repr=False, default=None)

    def at(self, values: np.ndarray, x: float) -> float:
        known = np.isfinite(values)
        if not known.any() or x < self.x_m[known][0] or x > self.x_m[known][-1]:
            return float("nan")
        return float(np.interp(x, self.x_m[known], values[known]))

    def x_to_column(self, x_m: float) -> float:
        return self.x_origin_px + x_m * self.ppm

    def ends_at(self, z_m: float) -> dict:
        """Stern and stem x at height z from the first and last outline runs of the levelled row."""
        row = int(np.floor(self.baseline_row - z_m * self.ppm))
        result = {}
        if not 0 <= row < self.mask.shape[0]:
            return {"stern": (None, "outside_view"), "stem": (None, "outside_view")}
        runs = masked_runs(self.view.crop, self.mask, self.tones.hull, row, axis=1)
        if not runs:
            return {"stern": (None, "no_ink"), "stem": (None, "no_ink")}
        # The outer edge of the outer run, less half a line (a line along the row still ends there).
        half = 0.5 * (self.line_width_px - 1)
        for name, column in (("stern", runs[0][0] + half), ("stem", runs[-1][1] - half)):
            result[name] = ((column - self.x_origin_px) / self.ppm, "read")
        return result


def read_profile(grey: np.ndarray, roi, ppm: float, slope: float, centre_x: float) -> ProfileReading:
    view = levelled(grey, roi, slope, centre_x)
    tone = tones(view.crop)
    mask = outline_mask(view.crop, tone.hull)
    width = line_width(view.crop, mask, tone.hull)
    columns = np.flatnonzero(mask.any(axis=0))
    if not len(columns):
        raise ValueError("Profile has no hull outline ink")
    keel_rows = np.full(view.crop.shape[1], np.nan)
    top_rows = np.full(view.crop.shape[1], np.nan)
    keel_status = ["outside_hull"] * view.crop.shape[1]
    top_status = ["outside_hull"] * view.crop.shape[1]
    for column in columns:
        runs = masked_runs(view.crop, mask, tone.hull, column, axis=0)
        if not runs:
            continue
        # The outer edge of the outer run, less half a line: neighbouring lines that merge
        # into the run (buttocks running along the keel) do not move it.
        half = 0.5 * (width - 1)
        for rows, status, run, row in ((keel_rows, keel_status, runs[-1], runs[-1][1] - half),
                                       (top_rows, top_status, runs[0], runs[0][0] + half)):
            if run[1] - run[0] + 1 > TANGENT_FACTOR * width:
                status[column] = "tangent"
            else:
                rows[column] = row
                status[column] = "read"
    baseline = float(np.nanmax(keel_rows))
    # x = 0: aftmost ink centre, read along rows (a transom is a vertical line).
    starts = []
    for row in range(mask.shape[0]):
        runs = masked_runs(view.crop, mask, tone.hull, row, axis=1)
        if runs and runs[0][1] - runs[0][0] + 1 <= TANGENT_FACTOR * width:
            starts.append(runs[0][2])
    x_origin = float(min(starts)) if starts else float(columns[0]) + 0.5 * width
    x_m = (np.arange(view.crop.shape[1]) + 0.5 - x_origin) / ppm
    reading = ProfileReading(ppm, x_origin, baseline, width, x_m, (baseline - keel_rows) / ppm,
                             (baseline - top_rows) / ppm, keel_status, top_status, [], {}, view, tone, mask)
    reading.waterlines, reading.baseline_row, reading.waterline_status = read_waterline_rows(
        grey, view, tone, baseline, ppm)
    if reading.baseline_row != baseline:
        reading.keel_z_m = (reading.baseline_row - keel_rows) / ppm
        reading.top_z_m = (reading.baseline_row - top_rows) / ppm
    return reading


def _row_peaks(share: np.ndarray, minimum: float) -> list[float]:
    """Weighted centres of consecutive rows whose share reaches ``minimum``."""
    hits = share >= minimum
    edges = np.flatnonzero(np.diff(np.concatenate([[0], hits.astype(int), [0]])))
    peaks = []
    for a, b in zip(edges[0::2], edges[1::2]):
        rows = np.arange(a, b)
        peaks.append(float(np.sum((rows + 0.5) * share[a:b]) / np.sum(share[a:b])))
    return peaks


def label_rows(grey, view: Levelled, tone: Tones) -> list[float]:
    """Centre rows (levelled view rows) of the text labels left of a view."""
    left = max(0, view.left - LABEL_BOX_PX[0])
    box = levelled(grey, [left, view.top, view.left - 2, view.top + view.crop.shape[0]], view.slope, view.centre_x)
    if not box.crop.size:
        return []
    ink = (box.crop < tone.dark + LABEL_TONE_SHARE * (tone.paper - tone.dark)).sum(axis=1)
    edges = np.flatnonzero(np.diff(np.concatenate([[0], (ink > 0).astype(int), [0]])))
    return [0.5 * (a + b) for a, b in zip(edges[0::2], edges[1::2]) if ink[a:b].sum() >= LABEL_MIN_PIXELS]


def read_waterline_rows(grey, view: Levelled, tone: Tones, baseline_row: float, ppm: float):
    """Waterline heights from labelled grid rows: ([{"id", "z_m", "row", ...}], baseline row, status).

    Each label left of the view names the grid row beside it (or, with no
    visible row, its own centre row). The lowest label is the baseline. The
    labelled rows set the grid spacing; every other labelled row must lie on a
    whole number of spacings above the baseline, and its height is that number
    of spacings (the drawn grid is regular). When the drawn baseline lies within
    BASELINE_MATCH_PX of the lowest hull ink, it is z = 0.
    """
    crop = view.crop
    light = (crop < tone.paper - LIGHT_CONTRAST) & (crop >= tone.hull)
    grid_rows = _row_peaks(light.mean(axis=1), GRID_ROW_SHARE)
    labels = label_rows(grey, view, tone)
    rows = []
    for label in labels:
        near = [row for row in grid_rows if abs(row - label) <= LABEL_BOX_PX[1]]
        rows.append((min(near, key=lambda row: abs(row - label)), True) if near else (label, False))
    status = {"grid_rows": len(grid_rows), "label_rows": len(labels)}
    paired = sorted(row for row, grid in rows if grid)
    gaps = np.diff(paired)
    gaps = gaps[gaps > 4]
    if len(rows) < 3 or not len(gaps):
        status["abstained"] = "no_regular_labelled_grid"
        return [], baseline_row, status
    spacing = float(np.median(gaps))
    datum = max(row for row, _ in rows)
    status.update(spacing_px=spacing, baseline_label_offset_px=float(datum - baseline_row))
    if abs(datum - baseline_row) <= BASELINE_MATCH_PX:
        baseline_row = datum
    by_step = {}
    for row, grid in rows:
        steps = (datum - row) / spacing
        k = int(round(steps))
        if k == 0:
            continue
        if k < 0 or abs(steps - k) > GRID_SNAP_SHARE:
            status["off_grid_labels"] = status.get("off_grid_labels", 0) + 1
            continue
        if k not in by_step or abs(steps - k) < abs(by_step[k][2] - k):
            by_step[k] = (row, grid, steps)
    waterlines = []
    for index, k in enumerate(sorted(by_step)):
        row, grid, _ = by_step[k]
        z = (baseline_row - (datum - k * spacing)) / ppm
        if z < MIN_WATERLINE_Z_M:
            continue
        waterlines.append({"id": f"wl{len(waterlines) + 1:02d}", "z_m": float(z), "row": float(datum - k * spacing),
                           "grid_row": bool(grid), "steps": k})
    status.update(waterlines=len(waterlines), from_label_only=sum(not w["grid_row"] for w in waterlines))
    return waterlines, baseline_row, status


# --------------------------------------------------------------------------
# Plan
# --------------------------------------------------------------------------

@dataclass
class PlanReading:
    ppm: float
    centre_row: float
    line_width_px: float
    x_m: np.ndarray
    curves: dict           # curve id -> {"z_m": float|None, "y_m": array, "status": list}
    view: Levelled = field(repr=False, default=None)


def centreline_row(crop: np.ndarray, tone: Tones, mask: np.ndarray) -> float:
    """The long horizontal line nearest below the lowest hull ink (the plan centreline)."""
    ink = crop < tone.paper - LIGHT_CONTRAST
    peaks = _row_peaks(ink.mean(axis=1), CENTRELINE_ROW_SHARE)
    rows = np.flatnonzero(mask.any(axis=1))
    if not peaks or not len(rows):
        raise ValueError("Plan has no centreline row")
    lowest = float(rows.max())
    return float(min(peaks, key=lambda row: abs(row - lowest)))


def curve_ends(profile: ProfileReading) -> dict:
    """Profile x of each curve's aft and fore end: {cid: (aft x or None, fore x or None, z or None)}.

    A waterline ends where the profile outline crosses its height; the deck
    line ends at the first and last columns where the profile's deck is read.
    """
    ends = {}
    near_deck = DECK_END_LW * profile.line_width_px / profile.ppm
    for line in profile.waterlines:
        found = profile.ends_at(line["z_m"])
        pair = []
        for name in ("stern", "stem"):
            x = found[name][0]
            # A waterline that ends on the deck line meets the deck edge, not the centreline.
            if x is not None and abs(profile.at(profile.top_z_m, x) - line["z_m"]) <= near_deck:
                x = None
            pair.append(x)
        ends[line["id"]] = (pair[0], pair[1], line["z_m"])
    top = np.isfinite(profile.top_z_m)
    if top.any():
        ends["deck"] = (float(profile.x_m[top][0]), float(profile.x_m[top][-1]), None)
    return ends


def _predict(track: list, column: int) -> float | None:
    if not track or abs(column - track[-1][0]) > TRACK_GAP_PX:
        return None
    recent = track[-TRACK_POINTS:]
    if len(recent) < 2:
        return recent[-1][1]
    columns, rows = np.array(recent).T
    slope, intercept = np.polyfit(columns, rows, 1)
    return float(slope * column + intercept)


def _position(run, prediction: float, line_px: float) -> float:
    """A run's position for a prediction: its centre, or the prediction clamped into a long run.

    A run longer than TANGENT_FACTOR line widths is a curve along the scan or a
    stack of coincident curves; either way the curve lies somewhere inside it.
    """
    start, end, centroid = run
    if end - start + 1 <= TANGENT_FACTOR * line_px:
        return centroid
    half = 0.5 * (line_px - 1)
    return float(np.clip(prediction, start + half, max(start + half, end - half)))


AMBIGUOUS = "ambiguous"


def _nearest(runs, prediction: float, tolerance_px: float, line_px: float):
    """(position, long run) of the run nearest a prediction; None when none is near, AMBIGUOUS when two are."""
    if not runs:
        return None
    positions = np.array([_position(run, prediction, line_px) for run in runs])
    distances = np.abs(positions - prediction)
    ranked = np.argsort(distances)
    if distances[ranked[0]] > tolerance_px:
        return None
    if len(ranked) > 1 and distances[ranked[1]] <= tolerance_px:
        return AMBIGUOUS
    run = runs[ranked[0]]
    return float(positions[ranked[0]]), run[1] - run[0] + 1 > TANGENT_FACTOR * line_px


def seed(ends: dict, cid: str, side: int, column_of, runs_by_column, centre: float, line_px: float):
    """(column, row) where curve ``cid`` leaves the centreline at one end, or None.

    ``side`` is 1 at the fore end (the curve is followed aft) and 0 at the aft
    end. SEED_OFFSET_LW line widths inside the end, the curves that end between
    that column and this curve's end lie nearer the centreline; their count is
    this curve's rank among the runs from the centreline. The seed needs that
    many distinct short runs near the centreline and no other end within
    SEED_TIE_LW line widths (coincident ends cannot be ordered).
    """
    x_end = ends[cid][side]
    if x_end is None:
        return None
    end_column = column_of(x_end)
    inward = -1 if side else 1
    column = int(round(end_column + inward * SEED_OFFSET_LW * line_px))
    rank = 0
    for other, values in ends.items():
        if other == cid or values[side] is None:
            continue
        other_column = column_of(values[side])
        if abs(other_column - end_column) <= SEED_TIE_LW * line_px \
                or abs(other_column - column) <= SEED_TIE_LW * line_px:
            return None  # coincident ends, or a curve that leaves the centreline at the seed column
        if (other_column - column) * inward < 0 < (other_column - end_column) * inward:
            rank += 1
    runs = sorted(runs_by_column.get(column, []), key=lambda run: -run[2])
    if len(runs) <= rank or any(run[1] - run[0] + 1 > TANGENT_FACTOR * line_px for run in runs[:rank + 1]):
        return None
    row = runs[rank][2]
    if centre - row > SEED_MAX_Y_LW * line_px:
        return None
    return column, row


def follow(start, direction: int, extent, runs_by_column, tolerance_px: float, line_px: float) -> dict:
    """{column: (row, in a long run)} of one curve followed from a seed, within its x extent."""
    column, row = start
    track, rows = [(column, row)], {column: (row, False)}
    while True:
        column += direction
        if column not in runs_by_column or not extent(column):
            break
        prediction = _predict(track, column)
        if prediction is None:
            break
        found = _nearest(runs_by_column[column], prediction, tolerance_px, line_px)
        if found is AMBIGUOUS or (found is not None and found[1]):
            # Two runs on the curve's line (a crossing or a split), or a long run (a bunch of
            # curves, or a curve along the column): the name is lost here.
            break
        if found is not None:
            track.append((column, found[0]))
            rows[column] = found
    return rows


def curve_exists(profile: ProfileReading, end: tuple, x: float, band_m: float) -> bool:
    """Whether a curve can show in the plan at x: inside its profile ends and between keel and deck."""
    aft, fore, z = end
    if (aft is not None and x < aft) or (fore is not None and x > fore):
        return False
    keel, top = profile.at(profile.keel_z_m, x), profile.at(profile.top_z_m, x)
    if not (np.isfinite(keel) and np.isfinite(top)):
        return False
    return z is None or keel + band_m < z < top - band_m


def combine(sweeps: dict, columns: int) -> dict:
    """{cid: {column: (row or None, status)}}: agreeing sweeps name a curve; disagreeing ones abstain."""
    named = {}
    for cid, tracks in sweeps.items():
        named[cid] = {}
        for column in range(columns):
            rows = [track[column][0] for track in tracks if column in track]
            if not rows:
                continue
            if max(rows) - min(rows) > SWEEP_AGREE_PX:
                named[cid][column] = (None, "abstain_sweeps_disagree")
            else:
                named[cid][column] = (float(np.mean(rows)), "tracked" if len(rows) > 1 else "tracked_one_end")
    return named


def excluded_curve(column: int, runs: list, named: dict, present: dict, line_px: float):
    """(cid, row) of the one unnamed curve at a column whose other curves each hold their own run."""
    if any(run[1] - run[0] + 1 > TANGENT_FACTOR * line_px for run in runs):
        return None
    here = [cid for cid in present if present[cid][column]]
    if len(runs) != len(here):
        return None
    unnamed = [cid for cid in here if named[cid].get(column, (None,))[0] is None]
    if len(unnamed) != 1:
        return None
    free = list(runs)
    for cid in here:
        if cid in unnamed:
            continue
        row = named[cid][column][0]
        match = [run for run in free if abs(run[2] - row) <= SHARED_INK_PX]
        if len(match) != 1:
            return None
        free.remove(match[0])
    return unnamed[0], free[0][2]


def read_plan(grey, roi, ppm: float, slope: float, centre_x: float, profile: ProfileReading,
              profile_view: Levelled) -> PlanReading:
    view = levelled(grey, roi, slope, centre_x)
    tone = tones(view.crop)
    mask = outline_mask(view.crop, tone.hull)
    width = line_width(view.crop, mask, tone.hull)
    centre = centreline_row(view.crop, tone, mask)
    clearance = CENTRELINE_CLEARANCE_LW * width
    # Plan and profile share sheet columns (same x origin) when their views are stacked.
    origin_sheet = profile_view.left + profile.x_origin_px
    x_m = (np.arange(view.crop.shape[1]) + 0.5 + view.left - origin_sheet) / ppm

    def column_of(x):
        return int(np.clip(round(x * ppm + origin_sheet - view.left - 0.5), 0, len(x_m) - 1))

    runs_by_column = {}
    for column in range(view.crop.shape[1]):
        values = np.where(mask[:, column], view.crop[:, column], 255.0)
        runs_by_column[column] = runs_1d(values[:max(0, int(np.floor(centre - clearance)))], tone.hull)
    ends = curve_ends(profile)
    tolerance = max(TRACK_TOL_PX, TRACK_TOL_LW * width)
    band_m = EXISTS_BAND_LW * width / ppm
    # Strictly inside the keel and deck: the curve must show (exclusion naming). Loosely: it may show
    # (following and output), which includes its own ends at the keel or deck.
    present = {cid: np.array([curve_exists(profile, ends[cid], float(x), band_m) for x in x_m]) for cid in ends}
    reach = {cid: np.array([curve_exists(profile, ends[cid], float(x), -band_m) for x in x_m]) for cid in ends}
    # Pass 1: each curve named at its centreline ends and followed inwards.
    sweeps = {cid: [] for cid in ends}
    for cid in ends:
        for side, direction in ((1, -1), (0, 1)):
            start = seed(ends, cid, side, column_of, runs_by_column, centre, width)
            if start is not None:
                sweeps[cid].append(follow(start, direction, reach[cid].__getitem__, runs_by_column, tolerance, width))
    # Later passes: where every other curve present is named on its own run and one run is left,
    # that run is the last curve (exclusion); it is followed both ways from there.
    for _ in range(EXCLUSION_PASSES):
        named = combine(sweeps, len(x_m))
        added = False
        for column, runs in runs_by_column.items():
            curve = excluded_curve(column, runs, named, present, width)
            if curve is None:
                continue
            cid, row = curve
            for direction in (-1, 1):
                sweeps[cid].append(follow((column, row), direction, reach[cid].__getitem__, runs_by_column,
                                          tolerance, width))
            named[cid][column] = (row, "tracked")
            added = True
        if not added:
            break
    named = combine(sweeps, len(x_m))
    curves = {}
    for cid, (aft, fore, z) in ends.items():
        y = np.full(len(x_m), np.nan)
        status = ["not_expected"] * len(x_m)
        for column in np.flatnonzero(reach[cid]):
            row, how = named[cid].get(column, (None, "abstain_unnamed"))
            status[column] = how
            if row is None:
                continue
            if centre - row < clearance + width:
                # The run touches the centreline line: the cut-off at the clearance biases its centre.
                status[column] = "abstain_near_centreline"
                continue
            y[column] = (centre - row) / ppm
        curves[cid] = {"z_m": z, "y_m": y, "status": status, "sweeps": len(sweeps[cid])}
    # Two curves on one run: one of them has left its own line (or both touch). Neither is named there.
    shared_m = SHARED_INK_PX / ppm
    for column in range(len(x_m)):
        on_ink = [c for c in curves.values() if c["status"][column] in NAMED]
        for curve in on_ink:
            if any(other is not curve and abs(other["y_m"][column] - curve["y_m"][column]) <= shared_m
                   for other in on_ink):
                curve["status"][column] = "abstain_shared_ink"
        for curve in on_ink:
            if curve["status"][column] == "abstain_shared_ink":
                curve["y_m"][column] = np.nan
    return PlanReading(ppm, centre, width, x_m, curves, view)


# --------------------------------------------------------------------------
# Whole reading and evidence points
# --------------------------------------------------------------------------

def read_views(grey: np.ndarray, views: dict) -> dict:
    """Profile and plan readings for the reference views of ``draft_fit.reference_views``.

    Only each view's region and the drawing scale are taken from ``views``;
    datums, heights and curve identities are read here.
    """
    profile_view = views.get("profile")
    if profile_view is None:
        return {"method": METHOD, "profile": None, "plan": None, "status": "no_profile"}
    ppm = float(profile_view["calibration"]["pixels_per_metre"])
    roi = profile_view["roi_px"]
    slope = view_skew(grey, roi)
    centre_x = 0.5 * (roi[0] + roi[2])
    profile = read_profile(grey, roi, ppm, slope, centre_x)
    plan = None
    if "half_breadth_plan" in views and profile.waterlines is not None:
        plan = read_plan(grey, views["half_breadth_plan"]["roi_px"], ppm, slope, centre_x, profile, profile.view)
    return {"method": METHOD, "profile": profile, "plan": plan, "slope": slope, "status": "read"}


def _sample_columns(x_m: np.ndarray, step_m: float) -> list[int]:
    targets = np.arange(np.ceil(x_m[0] / step_m) * step_m, x_m[-1], step_m)
    return sorted({int(np.argmin(np.abs(x_m - t))) for t in targets})


# A curve followed from both of its ends (agreeing) is traced; from one end only it is repaired.
CONFIDENCE = {"tracked": 1.0, "tracked_one_end": 0.5, "read": 1.0}
SOURCE_LABEL = {"tracked": "traced", "tracked_one_end": "repaired", "read": "traced"}
NAMED = ("tracked", "tracked_one_end")


def evidence_points(reading: dict) -> tuple[list[dict], dict]:
    """Points in the ``three_view_evidence`` format, and per-view counts with abstentions."""
    points, coverage = [], {}
    profile, plan = reading.get("profile"), reading.get("plan")
    if profile is not None:
        stats = {"available": True, "attempted": 0, "points": 0, "abstained": {}, "negative": 0}
        for column in _sample_columns(profile.x_m, SAMPLE_STEP_M):
            for target, values, status in (("keel", profile.keel_z_m, profile.keel_status),
                                           ("top", profile.top_z_m, profile.top_status)):
                if status[column] == "outside_hull":
                    continue
                stats["attempted"] += 1
                if status[column] != "read":
                    stats["abstained"][status[column]] = stats["abstained"].get(status[column], 0) + 1
                    continue
                points.append(_point("profile", target, target, "read", float(profile.x_m[column]), None,
                                     float(values[column])))
        top = float(np.nanmax(profile.top_z_m))
        for z in np.linspace(0, top, PROFILE_END_HEIGHTS + 2)[1:-1]:
            for target, (x, status) in profile.ends_at(float(z)).items():
                stats["attempted"] += 1
                if x is None:
                    stats["abstained"][status] = stats["abstained"].get(status, 0) + 1
                    continue
                points.append(_point("profile", target, target, "read", float(x), None, float(z)))
        stats["points"] = sum(p["view"] == "profile" for p in points)
        stats["waterline_rows"] = profile.waterline_status
        coverage["profile"] = stats
    else:
        coverage["profile"] = {"available": False}
    if plan is not None:
        stats = {"available": True, "attempted": 0, "points": 0, "abstained": {}, "negative": 0, "by_how": {}}
        for column in _sample_columns(plan.x_m, SAMPLE_STEP_M):
            x = float(plan.x_m[column])
            for cid, curve in plan.curves.items():
                status = curve["status"][column]
                if status == "not_expected":
                    continue
                stats["attempted"] += 1
                if status not in CONFIDENCE:
                    stats["abstained"][status] = stats["abstained"].get(status, 0) + 1
                    continue
                y = float(curve["y_m"][column])
                stats["negative"] += int(y < 0)
                z = curve["z_m"] if cid != "deck" else profile.at(profile.top_z_m, x)
                if z is None or not np.isfinite(z):
                    stats["abstained"]["no_height"] = stats["abstained"].get("no_height", 0) + 1
                    continue
                stats["by_how"][status] = stats["by_how"].get(status, 0) + 1
                points.append(_point("half_breadth_plan", "deck" if cid == "deck" else "waterline", cid, status,
                                     x, y, float(z)))
        stats["points"] = sum(p["view"] == "half_breadth_plan" for p in points)
        coverage["half_breadth_plan"] = stats
    else:
        coverage["half_breadth_plan"] = {"available": False}
    return points, coverage


def _point(view, target, curve_id, how, x, y, z):
    return {"view": view, "target": target, "curve_id": curve_id, "source_label": SOURCE_LABEL[how],
            "x_m": x, "y_m": y, "z_m": z, "confidence": CONFIDENCE[how], "how": how,
            "association": "drawing_order_and_profile" if view == "half_breadth_plan" else "profile_ink"}
