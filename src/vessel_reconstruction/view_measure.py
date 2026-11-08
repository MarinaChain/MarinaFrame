"""Measure a whole-vessel offset table against the ink of every drawn view.

Whole-vessel design (docs/plans/2026-11-08-whole-vessel-design.md), Phase 3.
The table says where each line must be drawn; code then measures the nearest
ink there ("predict, then measure"):

- body plan: at each station and waterline height, along the drawn row, the
  ink run nearest the predicted half-breadth; the keel and top end of each
  station curve; and drawn station lines that no table station explains;
- half-breadth plan: at each waterline and station, along the drawn column,
  the ink run nearest the predicted half-breadth; also the deck line;
- profile: keel and top (deck/sheer) heights along each station column, and
  the stem and stern x along each waterline row.

Each measurement is a cell with a signed residual (table minus ink, metres),
the number of competing ink runs near the prediction and a confidence. A
measurement never refuses: competing runs lower the confidence; ink found
only outside the search window is a miss (scored, with its distance); a scan
line with no ink at all is a gap (reported, not scored). This replaces the
W15 rule "one unique crossing or refuse", which refused all 792 Gunnerus
plan anchors.

Each scan runs a few pixels beside the station or waterline position, on both
sides, and the two residuals are averaged. The drawing has a grid line exactly
on each station (plan, profile) and waterline (body, profile); a scan along
that line would see only the grid line.

Display and self-check aid only: no truth input; nothing here fails a build.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path

import numpy as np

# Scans run this many pixels beside the nominal station / waterline line (both
# sides). Grid lines are 1-2 px wide; 4 px clears them with blur.
SCAN_OFFSET_PX = 4.0
# The nearest ink run is searched within this fraction of the half-beam of the
# prediction (at least SEARCH_MIN_PX), then on the whole scan line.
SEARCH_FRACTION = 0.15
SEARCH_MIN_PX = 12.0
# Other ink runs within this band of the prediction compete with the chosen
# run (design: 3 % of B/2, at least 6 px). They lower the confidence only.
BAND_FRACTION = 0.03
BAND_MIN_PX = 6.0
# Scans stay this far from a body-plan or plan-view centreline, which is
# drawn as a line of its own.
CENTRELINE_CLEARANCE_PX = 2.0
# Ink threshold: half way between the paper (median grey of the view) and the
# darkest ink (this percentile), never lighter than INK_THRESHOLD_MAX.
INK_DARK_PERCENTILE = 0.5
INK_THRESHOLD_MAX = 200
# A run longer than this many times the typical line width runs along the scan
# (the line is tangent there); its measured point is the prediction clamped
# into the run instead of the run's centre.
TANGENT_RUN_FACTOR = 2.5
# Line width assumed when a view has too few runs to estimate it, in pixels.
DEFAULT_LINE_WIDTH_PX = 3.0
# Pixel convention: pixel index i covers sheet coordinates [i, i + 1), so its
# centre is at i + 0.5. Calibrations (datum lines in pixels) use these
# coordinates; the factory renderer draws in them (supersampled, then reduced).
PIXEL_CENTRE = 0.5
# Section ends in the body plan: the end direction is taken over this many
# pixels of the table curve, and sampled every END_STEP_PX along it.
END_TANGENT_PX = 6.0
END_STEP_PX = 0.5
# A column inked on at least this fraction of a body-plan panel's rows is a
# grid or centre line (a hull section is never vertical over most of the
# panel height); its runs are not drawn stations.
VERTICAL_LINE_ROW_FRACTION = 0.8
# A run centred within this many pixels of such a column belongs to that line.
VERTICAL_LINE_MATCH_PX = 1.5
# Samples per station when an outline is drawn for the overlay.
CURVE_SAMPLES = 200


# --------------------------------------------------------------------------
# The table (stand-in for lane A's vessel_model table)
# --------------------------------------------------------------------------

@dataclass
class VesselTable:
    """Minimal whole-vessel offset table: the interface this module reads.

    Stand-in for the table of ``vessel_model.py`` (lane A, W19a), with the
    fields of design section 2: station x, waterline z, half-breadth cells
    (NaN where the hull has no breadth at that cell), keel and top heights per
    station, full-resolution station curves (``extra_rows``) and the profile
    end polylines. Any table with these attributes can be measured.
    """

    station_ids: list[str]
    x_m: np.ndarray                       # (stations,)
    waterline_ids: list[str]
    z_m: np.ndarray                       # (waterlines,)
    hb_m: np.ndarray                      # (stations, waterlines), NaN = no hull
    keel_z_m: np.ndarray                  # (stations,), NaN = unknown
    top_z_m: np.ndarray                   # (stations,), NaN = unknown
    rows_yz_m: list = field(default_factory=list)   # per station: (n, 2) y, z curve or None
    stem_xz_m: np.ndarray | None = None   # forward end of the profile, (n, 2) x, z
    stern_xz_m: np.ndarray | None = None  # aft end of the profile, (n, 2) x, z

    @classmethod
    def from_rows(cls, station_ids, x_m, rows_yz_m, z_m, waterline_ids=None, *,
                  stem_xz_m=None, stern_xz_m=None) -> "VesselTable":
        """Table from one station curve per station (None for a missing station)."""
        z = np.asarray(z_m, dtype=float)
        rows = [None if r is None or len(r) < 2 else np.asarray(r, dtype=float) for r in rows_yz_m]
        hb = np.full((len(rows), len(z)), np.nan)
        keel, top = np.full(len(rows), np.nan), np.full(len(rows), np.nan)
        for i, row in enumerate(rows):
            if row is None:
                continue
            keel[i], top[i] = row[:, 1].min(), row[:, 1].max()
            hb[i] = outer_half_breadth(row, z)
        ids = waterline_ids or [f"wl{j + 1:02d}" for j in range(len(z))]
        return cls(list(station_ids), np.asarray(x_m, dtype=float), list(ids), z, hb, keel, top, rows,
                   None if stem_xz_m is None else np.asarray(stem_xz_m, dtype=float),
                   None if stern_xz_m is None else np.asarray(stern_xz_m, dtype=float))

    def half_beam_m(self) -> float:
        """Largest half-breadth in the table (cells or station curves)."""
        values = [np.nanmax(self.hb_m)] if np.isfinite(self.hb_m).any() else []
        values += [float(np.abs(r[:, 0]).max()) for r in self.rows_yz_m if r is not None]
        return float(max(values)) if values else 0.0

    def row(self, i: int):
        return self.rows_yz_m[i] if i < len(self.rows_yz_m) else None

    def has_station(self, i: int) -> bool:
        return self.row(i) is not None or bool(np.isfinite(self.hb_m[i]).any())

    def station_hb(self, i: int, z: float) -> float:
        """Half-breadth of station i at height z: its curve, else its cells; NaN outside the hull."""
        row = self.row(i)
        if row is not None:
            return float(outer_half_breadth(row, np.array([z]))[0])
        column = self.hb_m[i]
        known = np.isfinite(column)
        if known.sum() < 2 or not (self.z_m[known].min() <= z <= self.z_m[known].max()):
            return float("nan")
        return float(np.interp(z, self.z_m[known], column[known]))

    def deck_hb(self, i: int) -> float:
        """Half-breadth at the top of station i (the plan-view deck line); NaN when unknown."""
        row = self.row(i)
        if row is not None:
            return float(abs(row[int(np.argmax(row[:, 1])), 0]))
        column = self.hb_m[i]
        known = np.flatnonzero(np.isfinite(column))
        return float(column[known[-1]]) if len(known) else float("nan")

    def along_x(self, values: np.ndarray, x: float) -> float:
        """A per-station quantity at x: linear between the stations that have it, constant past the ends."""
        known = np.isfinite(values)
        if not known.any():
            return float("nan")
        return float(np.interp(x, self.x_m[known], values[known]))

    def end_x(self, which: str, z: float) -> float:
        """x of the stem ('stem') or stern ('stern') profile end at height z; NaN when unknown."""
        polyline = self.stem_xz_m if which == "stem" else self.stern_xz_m
        if polyline is None or len(polyline) < 2:
            return float("nan")
        order = np.argsort(polyline[:, 1])
        zs, xs = polyline[order, 1], polyline[order, 0]
        if not (zs[0] <= z <= zs[-1]):
            return float("nan")
        return float(np.interp(z, zs, xs))


def outer_half_breadth(points_yz: np.ndarray, heights: np.ndarray) -> np.ndarray:
    """Largest |y| where the polyline crosses each height; NaN where it does not reach it."""
    points = np.asarray(points_yz, dtype=float)
    y0, z0, y1, z1 = points[:-1, 0], points[:-1, 1], points[1:, 0], points[1:, 1]
    low, high = np.minimum(z0, z1), np.maximum(z0, z1)
    result = np.full(len(heights), np.nan)
    for index, z in enumerate(np.asarray(heights, dtype=float)):
        hit = (low <= z) & (z <= high) & (high > low)
        if hit.any():
            t = (z - z0[hit]) / (z1[hit] - z0[hit])
            result[index] = float(np.abs(y0[hit] + t * (y1[hit] - y0[hit])).max())
        else:
            flat = (np.abs(z0 - z) < 1e-9) & (np.abs(z1 - z) < 1e-9)
            if flat.any():
                result[index] = float(max(np.abs(y0[flat]).max(), np.abs(y1[flat]).max()))
    return result


def profile_ends(polylines_xz: list, z_levels) -> tuple[np.ndarray, np.ndarray]:
    """Stern (min x) and stem (max x) polylines of a profile outline, sampled at ``z_levels``.

    ``polylines_xz`` are the outline pieces (each n x 2, x and z), for example
    the centreplane cut; each height takes the outline's crossings.
    """
    stern, stem = [], []
    for z in np.asarray(sorted(z_levels), dtype=float):
        crossings = []
        for piece in polylines_xz:
            piece = np.asarray(piece, dtype=float)
            x0, z0, x1, z1 = piece[:-1, 0], piece[:-1, 1], piece[1:, 0], piece[1:, 1]
            hit = (np.minimum(z0, z1) <= z) & (z <= np.maximum(z0, z1)) & (z1 != z0)
            t = (z - z0[hit]) / (z1[hit] - z0[hit])
            crossings.extend(x0[hit] + t * (x1[hit] - x0[hit]))
        if crossings:
            stern.append((min(crossings), z))
            stem.append((max(crossings), z))
    return np.array(stern).reshape(-1, 2), np.array(stem).reshape(-1, 2)


# --------------------------------------------------------------------------
# Views
# --------------------------------------------------------------------------

def side_of(roi_px, centerline_px: float) -> int:
    """+1 when a body-plan station is drawn right of its centreline, -1 when mirrored to the left."""
    return 1 if 0.5 * (roi_px[0] + roi_px[2]) >= centerline_px else -1


def views_from_three_view(views_json: dict) -> dict:
    """View geometry from a factory ``views.json`` (layout lines_3view)."""
    by_kind = {v["kind"]: v for v in views_json["views"]}
    result = {}
    body = by_kind.get("body_plan")
    if body:
        cal = body["calibration"]
        panels = {}
        for station in views_json.get("stations", []):
            side = -1 if station.get("body_plan_half") == "left" else 1
            panels[station["id"]] = {"roi_px": list(body["roi_px"]), "calibration": dict(cal), "side": side}
        result["body_plan"] = {"view_id": body["id"], "kind": "body_plan", "roi_px": list(body["roi_px"]),
                               "panels": panels}
    for kind in ("half_breadth_plan", "profile"):
        view = by_kind.get(kind)
        if view:
            result[kind] = {"view_id": view["id"], "kind": kind, "roi_px": list(view["roi_px"]),
                            "calibration": dict(view["calibration"])}
    return result


def views_from_spec(spec: dict) -> dict:
    """Body-plan-only view geometry from a section spec: one panel per section."""
    panels = {}
    for section in spec["sections"]:
        cal = section["calibration"]
        panels[section["id"]] = {"roi_px": list(section["roi_px"]), "calibration": dict(cal),
                                 "side": side_of(section["roi_px"], float(cal["centerline_px"]))}
    rois = np.array([p["roi_px"] for p in panels.values()], dtype=float)
    box = [float(rois[:, 0].min()), float(rois[:, 1].min()), float(rois[:, 2].max()), float(rois[:, 3].max())]
    return {"body_plan": {"view_id": "body_plan", "kind": "body_plan", "roi_px": box, "panels": panels}}


def load_grey(path: Path) -> np.ndarray:
    """The drawing as a float grey image (0 black, 255 white)."""
    from PIL import Image
    with Image.open(path) as image:
        return np.asarray(image.convert("L"), dtype=float)


# --------------------------------------------------------------------------
# Scanning
# --------------------------------------------------------------------------

@dataclass
class Sheet:
    """Grey image with an ink threshold per view region."""

    grey: np.ndarray
    thresholds: dict = field(default_factory=dict)
    ink_tables: dict = field(default_factory=dict)

    def threshold(self, roi_px) -> float:
        key = tuple(int(v) for v in roi_px)
        if key not in self.thresholds:
            region = self._crop(roi_px)
            if region.size == 0:
                self.thresholds[key] = 128.0
            else:
                paper, dark = float(np.median(region)), float(np.percentile(region, INK_DARK_PERCENTILE))
                self.thresholds[key] = min(INK_THRESHOLD_MAX, 0.5 * (paper + dark))
        return self.thresholds[key]

    def ink_sums(self, roi_px) -> np.ndarray:
        """Summed-area table (h + 1, w + 1) of the ink pixels of the sheet at this region's threshold."""
        key = tuple(int(v) for v in roi_px)
        if key not in self.ink_tables:
            ink = (self.grey < self.threshold(roi_px)).astype(np.int32)
            table = np.zeros((ink.shape[0] + 1, ink.shape[1] + 1), dtype=np.int32)
            table[1:, 1:] = ink.cumsum(axis=0).cumsum(axis=1)
            self.ink_tables[key] = table
        return self.ink_tables[key]

    def _crop(self, roi_px) -> np.ndarray:
        h, w = self.grey.shape
        x0, y0 = max(0, int(roi_px[0])), max(0, int(roi_px[1]))
        x1, y1 = min(w, int(roi_px[2])), min(h, int(roi_px[3]))
        return self.grey[y0:y1, x0:x1]


def ink_runs(sheet: Sheet, roi_px, axis: str, line_px: float, low_px: float, high_px: float) -> list[tuple]:
    """Ink runs along one scan line, inside the view region and the window [low, high].

    ``axis`` 'row' scans a horizontal line at y = line_px (positions are
    columns); 'col' scans a vertical line at x = line_px (positions are rows).
    Each run is (start, end, centroid) in sheet coordinates (start and end
    are pixel centres); the centroid is weighted by darkness, for sub-pixel
    positions.
    """
    h, w = sheet.grey.shape
    line = int(np.floor(line_px))
    if axis == "row":
        if not (max(0, roi_px[1]) <= line < min(h, roi_px[3])):
            return []
        start = int(max(0, roi_px[0], np.floor(low_px)))
        stop = int(min(w, roi_px[2], np.ceil(high_px) + 1))
        values = sheet.grey[line, start:stop] if stop > start else np.zeros(0)
    else:
        if not (max(0, roi_px[0]) <= line < min(w, roi_px[2])):
            return []
        start = int(max(0, roi_px[1], np.floor(low_px)))
        stop = int(min(h, roi_px[3], np.ceil(high_px) + 1))
        values = sheet.grey[start:stop, line] if stop > start else np.zeros(0)
    if not len(values):
        return []
    threshold = sheet.threshold(roi_px)
    ink = values < threshold
    edges = np.flatnonzero(np.diff(np.concatenate([[0], ink.astype(int), [0]])))
    runs = []
    for a, b in zip(edges[0::2], edges[1::2] - 1):
        weight = threshold - values[a:b + 1]
        positions = np.arange(a, b + 1) + start + PIXEL_CENTRE
        runs.append((float(positions[0]), float(positions[-1]), float(np.sum(positions * weight) / np.sum(weight))))
    return runs


def nearest_run(runs: list[tuple], predicted: float, band_px: float, line_width_px: float):
    """Measured position, distance and competing-run count of the run nearest a prediction."""
    best, best_distance, competing_distances = None, float("inf"), []
    for start, end, centroid in runs:
        if end - start + 1 > TANGENT_RUN_FACTOR * line_width_px:
            # The line runs along the scan: take the prediction clamped into its centre part.
            half = 0.5 * line_width_px
            point = float(np.clip(predicted, start + half, max(start + half, end - half)))
        else:
            point = centroid
        distance = abs(point - predicted)
        competing_distances.append(distance)
        if distance < best_distance:
            best, best_distance = point, distance
    competing = sum(1 for d in competing_distances if d <= band_px) - (1 if best_distance <= band_px else 0)
    return best, best_distance, competing


@dataclass
class ScanContext:
    sheet: Sheet
    half_beam_m: float
    line_width_px: float = DEFAULT_LINE_WIDTH_PX


def measure_point(context: ScanContext, roi_px, axis: str, line_px: float, predicted_px: float,
                  ppm: float, *, low_limit_px: float = -np.inf, high_limit_px: float = np.inf) -> dict:
    """One scan: the ink run nearest ``predicted_px`` along one line, with its competing runs."""
    search = max(SEARCH_MIN_PX, SEARCH_FRACTION * context.half_beam_m * ppm)
    band = max(BAND_MIN_PX, BAND_FRACTION * context.half_beam_m * ppm)
    low = max(low_limit_px, predicted_px - search)
    high = min(high_limit_px, predicted_px + search)
    runs = ink_runs(context.sheet, roi_px, axis, line_px, low, high) if high > low else []
    beyond_search = False
    if not runs:
        # Ink elsewhere on the line means the table is far off here (a miss, scored);
        # no ink on the whole line means the drawing does not show it (a gap).
        runs = ink_runs(context.sheet, roi_px, axis, line_px, low_limit_px, high_limit_px)
        beyond_search = bool(runs)
    if not runs:
        return {"status": "no_ink", "predicted_px": predicted_px}
    measured, _, competing = nearest_run(runs, predicted_px, band, context.line_width_px)
    return {"status": "measured", "predicted_px": predicted_px, "measured_px": measured,
            "competing_runs": int(competing), "beyond_search": beyond_search}


def combine_scans(scans: list[dict], sign: float, ppm: float) -> dict:
    """Average the measured scans of one cell (one on each side of the nominal line)."""
    measured = [s for s in scans if s["status"] == "measured"]
    if not measured:
        return {"status": "no_ink", "predicted_px": float(np.mean([s["predicted_px"] for s in scans]))}
    residual_px = float(np.mean([sign * (s["predicted_px"] - s["measured_px"]) for s in measured]))
    competing = max(s["competing_runs"] for s in measured)
    return {"status": "measured", "residual_px": residual_px, "residual_m": residual_px / ppm,
            "competing_runs": int(competing), "confidence": round(1.0 / (1.0 + competing), 4),
            "predicted_px": float(np.mean([s["predicted_px"] for s in measured])),
            "measured_px": float(np.mean([s["measured_px"] for s in measured])), "scans": len(measured),
            "beyond_search": any(s.get("beyond_search") for s in measured)}


def inked(sheet: Sheet, roi_px, x_px: float, y_px: float, radius_px: float) -> bool:
    """True when any pixel within ``radius_px`` (a square) of the point is ink."""
    return bool(inked_many(sheet, roi_px, np.array([x_px]), np.array([y_px]), radius_px)[0])


def inked_many(sheet: Sheet, roi_px, x_px: np.ndarray, y_px: np.ndarray, radius_px: float) -> np.ndarray:
    """``inked`` for many points at once (a summed-area table of the region's ink)."""
    h, w = sheet.grey.shape
    x0 = np.maximum(max(0, roi_px[0]), np.floor(x_px - PIXEL_CENTRE - radius_px)).astype(int)
    x1 = np.minimum(min(w, roi_px[2]), np.floor(x_px - PIXEL_CENTRE + radius_px) + 1).astype(int)
    y0 = np.maximum(max(0, roi_px[1]), np.floor(y_px - PIXEL_CENTRE - radius_px)).astype(int)
    y1 = np.minimum(min(h, roi_px[3]), np.floor(y_px - PIXEL_CENTRE + radius_px) + 1).astype(int)
    table = sheet.ink_sums(roi_px)
    valid = (x1 > x0) & (y1 > y0)
    x0, x1, y0, y1 = (np.clip(v, 0, n) for v, n in ((x0, w), (x1, w), (y0, h), (y1, h)))
    counts = table[y1, x1] - table[y0, x1] - table[y1, x0] + table[y0, x0]
    return valid & (counts > 0)


def measure_curve_end(context: ScanContext, roi_px, curve_px: np.ndarray, ppm: float) -> dict:
    """Where the drawn line ends, measured along the table curve and past its end.

    ``curve_px`` runs towards the end (last point = the table's end). The
    path is the table curve itself (arc length s < 0) followed by its end
    tangent (s > 0). The measured end is the outer end of the inked stretch
    nearest the table's end. Residual (px) = table end beyond the ink end
    (positive: the table runs on past the drawn line).
    """
    path, steps = end_path(curve_px, max(SEARCH_MIN_PX, SEARCH_FRACTION * context.half_beam_m * ppm))
    if path is None:
        return {"status": "no_ink", "predicted_px": 0.0}
    # A small neighbourhood: a station label a few pixels past the end must not
    # read as the line running on.
    radius = max(1.0, 0.5 * context.line_width_px)
    ink = inked_many(context.sheet, roi_px, path[:, 0], path[:, 1], radius)
    if not ink.any():
        return {"status": "no_ink", "predicted_px": 0.0}
    # The inked stretch nearest the table's end (s = 0), then its outer end.
    nearest = int(np.flatnonzero(ink)[np.argmin(np.abs(steps[ink]))])
    last = nearest
    while last + 1 < len(steps) and ink[last + 1]:
        last += 1
    # The last inked sample sees ink up to ``radius`` ahead of it, and the line's
    # round end cap reaches half a line width past its end point.
    measured = float(steps[last]) - radius - 0.5 * context.line_width_px + PIXEL_CENTRE
    # Ink past the table's end may be the line running on, or a label or another
    # station's line next to it: half confidence. Ink stopping short of the
    # table's end is unambiguous.
    competing = 1 if measured > END_STEP_PX else 0
    return {"status": "measured", "predicted_px": 0.0, "measured_px": measured, "competing_runs": competing,
            "beyond_search": False}


def end_path(curve_px: np.ndarray, beyond_px: float):
    """Points every END_STEP_PX along a curve (s <= 0, ending at its last point) and past its end (s > 0)."""
    end = curve_px[-1]
    back = curve_px[:-1][np.linalg.norm(curve_px[:-1] - end, axis=1) >= END_TANGENT_PX]
    if not len(back):
        return None, None
    direction = (end - back[-1]) / np.linalg.norm(end - back[-1])
    reverse = curve_px[::-1]
    arc = np.concatenate([[0.0], np.cumsum(np.linalg.norm(np.diff(reverse, axis=0), axis=1))])
    behind = np.arange(0.0, arc[-1], END_STEP_PX)
    along = np.column_stack([np.interp(behind, arc, reverse[:, 0]), np.interp(behind, arc, reverse[:, 1])])
    ahead = np.arange(END_STEP_PX, beyond_px + END_STEP_PX, END_STEP_PX)
    points = np.vstack([along[::-1], end + ahead[:, None] * direction])
    return points, np.concatenate([-behind[::-1], ahead])


# --------------------------------------------------------------------------
# Per-view measurement
# --------------------------------------------------------------------------

def _cell(view: str, target: str, **fields) -> dict:
    return {"view": view, "target": target, **fields}


def measure_body(table: VesselTable, view: dict, context: ScanContext) -> list[dict]:
    """Body plan: each station curve at each waterline height, along the drawn row."""
    cells = []
    for i, sid in enumerate(table.station_ids):
        panel = view["panels"].get(sid)
        if panel is None:
            continue
        cal, roi, side = panel["calibration"], panel["roi_px"], panel["side"]
        ppm, centre, base = float(cal["pixels_per_metre"]), float(cal["centerline_px"]), float(cal["baseline_px"])
        offset_m = SCAN_OFFSET_PX / ppm
        clearance = CENTRELINE_CLEARANCE_PX
        limits = ({"low_limit_px": centre + clearance} if side > 0 else {"high_limit_px": centre - clearance})
        for j, wid in enumerate(table.waterline_ids):
            z = float(table.z_m[j])
            base_fields = {"station_id": sid, "waterline_id": wid, "x_m": float(table.x_m[i]), "z_m": z}
            if not table.has_station(i):
                cells.append(_cell("body_plan", "station", status="table_missing", **base_fields))
                continue
            if not np.isfinite(table.hb_m[i, j]):
                continue
            scans = []
            for dz in (-offset_m, offset_m):
                hb = table.station_hb(i, z + dz)
                if not np.isfinite(hb):
                    continue
                predicted = centre + side * hb * ppm
                scans.append(measure_point(context, roi, "row", base - (z + dz) * ppm, predicted, ppm, **limits))
            if scans:
                cells.append(_cell("body_plan", "station", **base_fields, **combine_scans(scans, side, ppm)))
        cells += measure_body_ends(table, i, panel, context)
    return cells + measure_body_coverage(table, view, context)


def measure_body_coverage(table: VesselTable, view: dict, context: ScanContext) -> list[dict]:
    """Drawn station lines that no table station explains, on each waterline row of each panel.

    Each drawn line belongs to some station. On a waterline row, every ink
    run in a panel half should lie within the competing band of some table
    station curve of that panel (distance in the drawing plane). A run that
    does not (for example the bow station of an overlay panel when the
    table reused a midship stroke for it) is an unexplained-ink cell: its
    residual is the distance to the nearest table curve. Long vertical lines
    (grid, centreline) and lines running along the row are not counted.
    """
    groups = {}
    for i, sid in enumerate(table.station_ids):
        panel = view["panels"].get(sid)
        if panel is not None:
            cal = panel["calibration"]
            key = (tuple(round(float(v)) for v in panel["roi_px"]), round(float(cal["centerline_px"])), panel["side"])
            groups.setdefault(key, []).append(i)
    curves = dict(view_polylines(table, {"body_plan": view}).get("body_plan", []))
    cells = []
    for members in groups.values():
        panel = view["panels"][table.station_ids[members[0]]]
        cal, roi, side = panel["calibration"], panel["roi_px"], panel["side"]
        ppm, centre, base = float(cal["pixels_per_metre"]), float(cal["centerline_px"]), float(cal["baseline_px"])
        low, high = ((centre + CENTRELINE_CLEARANCE_PX, roi[2]) if side > 0 else
                     (roi[0], centre - CENTRELINE_CLEARANCE_PX))
        masked = vertical_line_columns(context.sheet, roi, low, high)
        band = max(BAND_MIN_PX, BAND_FRACTION * context.half_beam_m * ppm)
        panel_curves = {table.station_ids[i]: curves[table.station_ids[i]] for i in members
                        if table.station_ids[i] in curves}
        if not panel_curves:
            continue
        for j, wid in enumerate(table.waterline_ids):
            z = float(table.z_m[j]) + SCAN_OFFSET_PX / ppm
            breadths = [table.station_hb(i, z) for i in members if table.has_station(i)]
            predictions = [centre + side * hb * ppm for hb in breadths if np.isfinite(hb)]
            if not predictions:
                # No table station reaches this row here: the section ends are measured instead.
                continue
            row_px = base - z * ppm
            runs = ink_runs(context.sheet, roi, "row", row_px, low, high)
            if not runs:
                continue
            centroids = np.array([centroid for _, _, centroid in runs])
            # A run that is some station's nearest run is already scored in that station's cell.
            claimed = {int(np.argmin(np.abs(centroids - predicted))) for predicted in predictions}
            for index, (start, end, centroid) in enumerate(runs):
                along_row = end - start + 1 > TANGENT_RUN_FACTOR * context.line_width_px
                on_vertical_line = np.any(np.abs(masked - centroid) <= VERTICAL_LINE_MATCH_PX)
                if index in claimed or along_row or on_vertical_line:
                    continue
                point = np.array([centroid, row_px])
                distances = {sid: point_to_polyline_px(point, curve) for sid, curve in panel_curves.items()}
                nearest = min(distances, key=distances.get)
                if distances[nearest] <= band:
                    continue
                residual_m = min(distances[nearest] / ppm, context.half_beam_m)
                cells.append(_cell("body_plan", "ink_unexplained", station_id=nearest, waterline_id=wid,
                                   x_m=None, z_m=float(table.z_m[j]), status="measured", residual_m=residual_m,
                                   residual_px=residual_m * ppm, competing_runs=0, confidence=1.0,
                                   predicted_px=None, measured_px=centroid))
    return cells


def point_to_polyline_px(point: np.ndarray, polyline: np.ndarray) -> float:
    """Distance from a point to a polyline (both in pixels)."""
    starts, ends = polyline[:-1], polyline[1:]
    vectors = ends - starts
    length2 = np.maximum(np.sum(vectors * vectors, axis=1), 1e-12)
    t = np.clip(np.sum((point - starts) * vectors, axis=1) / length2, 0.0, 1.0)
    closest = starts + t[:, None] * vectors
    return float(np.sqrt(np.min(np.sum((closest - point) ** 2, axis=1))))


def vertical_line_columns(sheet: Sheet, roi_px, low_px: float, high_px: float) -> np.ndarray:
    """Columns (sheet coordinates) inked on most rows of the view region: grid lines, not hull lines."""
    h, w = sheet.grey.shape
    x0, x1 = int(max(0, roi_px[0], np.floor(low_px))), int(min(w, roi_px[2], np.ceil(high_px)))
    y0, y1 = int(max(0, roi_px[1])), int(min(h, roi_px[3]))
    if x1 <= x0 or y1 <= y0:
        return np.zeros(0)
    fraction = (sheet.grey[y0:y1, x0:x1] < sheet.threshold(roi_px)).mean(axis=0)
    return np.flatnonzero(fraction >= VERTICAL_LINE_ROW_FRACTION) + x0 + PIXEL_CENTRE


def measure_body_ends(table: VesselTable, i: int, panel: dict, context: ScanContext) -> list[dict]:
    """Keel and top of one station curve in its body-plan panel.

    Keel: along a column just beside the centreline, the ink run nearest the
    height where the table curve crosses that column. Top: where the drawn
    line ends along the curve's end direction (``measure_curve_end``).
    """
    row = table.row(i)
    if row is None:
        return []
    cal, roi, side = panel["calibration"], panel["roi_px"], panel["side"]
    ppm, centre, base = float(cal["pixels_per_metre"]), float(cal["centerline_px"]), float(cal["baseline_px"])
    fields = {"station_id": table.station_ids[i], "x_m": float(table.x_m[i])}
    # The curve from its lower end up to its highest point.
    oriented = row if row[-1, 1] >= row[0, 1] else row[::-1]
    upward = oriented[:int(np.argmax(oriented[:, 1])) + 1]
    cells = []
    column_m = (CENTRELINE_CLEARANCE_PX + SCAN_OFFSET_PX) / ppm
    crossing = _lowest_crossing(oriented, column_m)
    if crossing is not None:
        scan = measure_point(context, roi, "col", centre + side * column_m * ppm, base - crossing * ppm, ppm)
        cells.append(_cell("body_plan", "keel", z_m=float(oriented[:, 1].min()), **fields,
                           **combine_scans([scan], -1.0, ppm)))
    if len(upward) >= 2:
        curve_px = np.column_stack([centre + side * np.abs(upward[:, 0]) * ppm, base - upward[:, 1] * ppm])
        end = measure_curve_end(context, roi, curve_px, ppm)
        cells.append(_cell("body_plan", "top", z_m=float(upward[-1, 1]), **fields,
                           **combine_scans([end], 1.0, ppm)))
    return cells


def _lowest_crossing(points_yz: np.ndarray, y: float) -> float | None:
    """Lowest height where the curve crosses |y| = y."""
    hb = np.abs(points_yz[:, 0])
    heights = []
    for (a, za), (b, zb) in zip(zip(hb[:-1], points_yz[:-1, 1]), zip(hb[1:], points_yz[1:, 1])):
        if (a - y) * (b - y) <= 0 and a != b:
            heights.append(za + (y - a) / (b - a) * (zb - za))
    return min(heights) if heights else None


def measure_plan(table: VesselTable, view: dict, context: ScanContext) -> list[dict]:
    """Half-breadth plan: each waterline (and the deck line) at each station, along the drawn column."""
    cal, roi = view["calibration"], view["roi_px"]
    ppm, origin, centre = float(cal["pixels_per_metre"]), float(cal["x_origin_px"]), float(cal["centerline_px"])
    offset_m = SCAN_OFFSET_PX / ppm
    limit = {"high_limit_px": centre - CENTRELINE_CLEARANCE_PX}
    cells = []
    lines = [(wid, float(table.z_m[j]), table.hb_m[:, j]) for j, wid in enumerate(table.waterline_ids)]
    deck = np.array([table.deck_hb(i) for i in range(len(table.x_m))])
    lines.append(("deck", None, deck))
    for wid, z, values in lines:
        defined = np.isfinite(values)
        for i, sid in enumerate(table.station_ids):
            if not defined[i]:
                continue
            x = float(table.x_m[i])
            scans = []
            for dx in (-offset_m, offset_m):
                hb = table.along_x(values, x + dx)
                scans.append(measure_point(context, roi, "col", origin + (x + dx) * ppm, centre - hb * ppm, ppm,
                                           **limit))
            # Rows grow downwards and half-breadth upwards: table minus ink is measured minus predicted.
            cells.append(_cell("half_breadth_plan", "deck" if wid == "deck" else "waterline", station_id=sid,
                               waterline_id=wid, x_m=x, z_m=z, **combine_scans(scans, -1.0, ppm)))
    return cells


def measure_profile(table: VesselTable, view: dict, context: ScanContext) -> list[dict]:
    """Profile: keel and top heights at each station column; stem and stern x at each waterline row."""
    cal, roi = view["calibration"], view["roi_px"]
    ppm, origin, base = float(cal["pixels_per_metre"]), float(cal["x_origin_px"]), float(cal["baseline_px"])
    offset_m = SCAN_OFFSET_PX / ppm
    cells = []
    for target, values in (("keel", table.keel_z_m), ("top", table.top_z_m)):
        for i, sid in enumerate(table.station_ids):
            if not np.isfinite(values[i]):
                continue
            x = float(table.x_m[i])
            scans = [measure_point(context, roi, "col", origin + (x + dx) * ppm,
                                   base - table.along_x(values, x + dx) * ppm, ppm)
                     for dx in (-offset_m, offset_m)]
            cells.append(_cell("profile", target, station_id=sid, x_m=x, z_m=float(values[i]),
                               **combine_scans(scans, -1.0, ppm)))
    for target in ("stem", "stern"):
        for j, wid in enumerate(table.waterline_ids):
            z = float(table.z_m[j])
            scans = []
            for dz in (-offset_m, offset_m):
                x_end = table.end_x(target, z + dz)
                if np.isfinite(x_end):
                    scans.append(measure_point(context, roi, "row", base - (z + dz) * ppm, origin + x_end * ppm, ppm))
            if scans:
                cells.append(_cell("profile", target, waterline_id=wid, x_m=table.end_x(target, z), z_m=z,
                                   **combine_scans(scans, 1.0, ppm)))
    return cells


def estimate_line_width(sheet: Sheet, views: dict) -> float:
    """Typical drawn line width (px): median length of short ink runs across body-plan rows."""
    body = views.get("body_plan") or next(iter(views.values()))
    roi = body["roi_px"]
    lengths = []
    for line in np.linspace(roi[1] + 2, roi[3] - 2, 12):
        for start, end, _ in ink_runs(sheet, roi, "row", line, roi[0], roi[2]):
            lengths.append(end - start + 1)
    lengths = [v for v in lengths if v <= 12]
    return float(np.median(lengths)) if lengths else DEFAULT_LINE_WIDTH_PX


def measure_views(table: VesselTable, views: dict, grey: np.ndarray, *, half_beam_m: float | None = None) -> list[dict]:
    """Every cell of the table measured in every given view (body plan, half-breadth plan, profile)."""
    sheet = Sheet(grey)
    context = ScanContext(sheet, float(half_beam_m or table.half_beam_m() or 1.0))
    context.line_width_px = estimate_line_width(sheet, views)
    cells = []
    if "body_plan" in views:
        cells += measure_body(table, views["body_plan"], context)
    if "half_breadth_plan" in views:
        cells += measure_plan(table, views["half_breadth_plan"], context)
    if "profile" in views:
        cells += measure_profile(table, views["profile"], context)
    return cells


# --------------------------------------------------------------------------
# Body-plan ink fit per station (F1 reuse) and overlay drawing
# --------------------------------------------------------------------------

def station_ink_fits(table: VesselTable, views: dict, grey: np.ndarray) -> dict:
    """F1 ink fit (station_overlay.ink_fit) of each station curve in its body-plan panel."""
    from .station_overlay import ink_distance_px, ink_fit
    body = views.get("body_plan")
    result = {}
    if not body:
        return result
    distances = {}
    for i, sid in enumerate(table.station_ids):
        row, panel = table.row(i), body["panels"].get(sid)
        if row is None or panel is None:
            continue
        points = np.column_stack([np.abs(row[:, 0]), row[:, 1]])
        segments = np.stack([points[:-1], points[1:]], axis=1)
        key = tuple(int(v) for v in panel["roi_px"])
        if key not in distances:
            distances[key] = ink_distance_px(grey, panel["roi_px"])
        result[sid] = (ink_fit(segments, panel["calibration"], panel["roi_px"], grey, side=panel["side"],
                               distance_px=distances[key]) if distances[key] is not None else None)
    return result


def view_polylines(table: VesselTable, views: dict) -> dict:
    """The table drawn in each view, as sheet-pixel polylines: {view kind: [(label, points)]}."""
    result = {}
    body = views.get("body_plan")
    if body:
        lines = []
        for i, sid in enumerate(table.station_ids):
            panel = body["panels"].get(sid)
            if panel is None or not table.has_station(i):
                continue
            cal = panel["calibration"]
            ppm, centre, base = (float(cal["pixels_per_metre"]), float(cal["centerline_px"]),
                                 float(cal["baseline_px"]))
            row = table.row(i)
            if row is None:
                known = np.isfinite(table.hb_m[i])
                row = np.column_stack([table.hb_m[i][known], table.z_m[known]])
            px = np.column_stack([centre + panel["side"] * np.abs(row[:, 0]) * ppm, base - row[:, 1] * ppm])
            lines.append((sid, px))
        result["body_plan"] = lines
    plan = views.get("half_breadth_plan")
    if plan:
        cal = plan["calibration"]
        ppm, origin, centre = float(cal["pixels_per_metre"]), float(cal["x_origin_px"]), float(cal["centerline_px"])
        lines = []
        series = [(wid, table.hb_m[:, j]) for j, wid in enumerate(table.waterline_ids)]
        series.append(("deck", np.array([table.deck_hb(i) for i in range(len(table.x_m))])))
        for wid, values in series:
            known = np.isfinite(values)
            if known.sum() >= 2:
                xs = np.linspace(table.x_m[known].min(), table.x_m[known].max(), CURVE_SAMPLES)
                hb = np.interp(xs, table.x_m[known], values[known])
                lines.append((wid, np.column_stack([origin + xs * ppm, centre - hb * ppm])))
        result["half_breadth_plan"] = lines
    profile = views.get("profile")
    if profile:
        cal = profile["calibration"]
        ppm, origin, base = float(cal["pixels_per_metre"]), float(cal["x_origin_px"]), float(cal["baseline_px"])
        lines = []
        for label, values in (("keel", table.keel_z_m), ("top", table.top_z_m)):
            known = np.isfinite(values)
            if known.sum() >= 2:
                lines.append((label, np.column_stack([origin + table.x_m[known] * ppm, base - values[known] * ppm])))
        for label, polyline in (("stem", table.stem_xz_m), ("stern", table.stern_xz_m)):
            if polyline is not None and len(polyline) >= 2:
                lines.append((label, np.column_stack([origin + polyline[:, 0] * ppm, base - polyline[:, 1] * ppm])))
        result["profile"] = lines
    return result


def cell_marker_px(cell: dict, views: dict) -> tuple[float, float] | None:
    """Sheet-pixel position of a measured cell's ink point, for the overlay."""
    if cell.get("status") != "measured":
        return None
    view = views[cell["view"]]
    if cell["view"] == "body_plan":
        cal = view["panels"][cell["station_id"]]["calibration"]
        return cell["measured_px"], float(cal["baseline_px"]) - cell["z_m"] * float(cal["pixels_per_metre"])
    cal = view["calibration"]
    ppm, origin = float(cal["pixels_per_metre"]), float(cal["x_origin_px"])
    if cell["target"] in ("stem", "stern"):
        return cell["measured_px"], float(cal["baseline_px"]) - cell["z_m"] * ppm
    return origin + cell["x_m"] * ppm, cell["measured_px"]


def draw_overlays(table: VesselTable, views: dict, grey: np.ndarray, cells: list[dict], half_beam_m: float,
                  out: Path) -> list[dict]:
    """One overlay image per view: the table drawn over the faded ink, cells coloured by residual."""
    from .station_overlay import draw_view_overlay, residual_colour
    out.mkdir(parents=True, exist_ok=True)
    polylines = view_polylines(table, views)
    artifacts = []
    for kind, view in views.items():
        markers = []
        for cell in cells:
            if cell["view"] != kind:
                continue
            at = cell_marker_px(cell, views)
            if at is not None:
                markers.append((at, residual_colour(abs(cell["residual_m"]) / max(half_beam_m, 1e-9))))
        filename = f"view-overlay-{kind}.png"
        geometry = draw_view_overlay(grey, view["roi_px"], polylines.get(kind, []), markers, out / filename,
                                     f"{kind.replace('_', ' ')}: table (blue) over the drawing; "
                                     "dots: measured ink (green < 1 %, orange < 3 %, red above, of B/2)")
        artifacts.append({"file": filename, "kind": "view_overlay", "view": kind, **geometry})
    return artifacts


def write_cells(cells: list[dict], path: Path) -> None:
    path.write_text("".join(json.dumps(cell) + "\n" for cell in cells))
