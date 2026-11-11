"""Three-view lines drawing renderer (layout ``lines_3view``).

One sheet, in the usual arrangement::

    +--------------------------------------+   +-------------+
    | PROFILE (x right, z up)              |   | BODY PLAN   |
    |  keel/stem/stern, sheer, buttocks    |   | aft | fore  |
    +--------------------------------------+   +-------------+
    | HALF-BREADTH PLAN (x right, y up)    |   | TITLE BLOCK |
    |  waterlines, deck line               |   |             |
    +--------------------------------------+   +-------------+

All three views have one scale. The body plan shares the profile baseline, so a waterline is one
straight row through profile and body plan. Station lines run through profile and plan at the same
columns. Bow is on the right.

The body plan is drawn as the ``overlay`` body plan of ``render.py`` (afterbody stations left of the
centreline, forebody right, station labels). Rendering parameters, degradation and the calibration
convention (datum read at the middle of each region after the sheet transform, plus the level's
calibration read error) are those of ``render.py``; that module is hashed by the sealed manifests
and is only called, not changed.

Outputs per case: ``drawing.png``, ``spec.json`` (body-plan sections, valid against the project schema)
and ``views.json`` (every view's region, kind, calibration and halves). No truth value enters either file.
"""
from __future__ import annotations

import math

import numpy as np
from PIL import Image, ImageDraw

from . import lines as L
from . import render as R

LAYOUT = "lines_3view"
LENGTH_PX = 1900.0  # drawn hull length at ppm_scale 1
MARGIN_PX = 90
LABEL_COLUMN_PX = 70  # left of the profile and plan, for WL and B labels
VIEW_GAP_X_PX = 110  # profile to body plan
VIEW_GAP_Y_PX = 70  # profile baseline to the plan's top
TOP_LABEL_PX = 40  # station labels above the profile
BODY_SIDE_MARGIN_PX = 30
TITLE_BLOCK_W_PX = 330
TITLE_BLOCK_H_PX = 170
ROI_PAD_PX = 12
CENTRELINE_OVERLAP_PX = 40  # columns kept across the centreline in a body-plan section ROI


def _ss(value: float) -> float:
    return value * R.SUPERSAMPLE


class SheetLayout:
    """Pixel positions of every view on the undistorted sheet (final size, not supersampled)."""

    def __init__(self, lines: L.Lines, ppm: float):
        self.ppm = ppm
        self.length_px = lines.length_m * ppm
        self.depth_px = lines.depth_m * ppm
        self.half_px = lines.max_half_breadth_m * ppm
        self.x_origin = MARGIN_PX + LABEL_COLUMN_PX  # column of x = 0 in profile and plan
        self.profile_top = MARGIN_PX + 30 + TOP_LABEL_PX
        self.baseline = self.profile_top + self.depth_px  # row of z = 0 in profile and body plan
        self.plan_top = self.baseline + VIEW_GAP_Y_PX
        self.plan_centreline = self.plan_top + self.half_px  # row of y = 0 in the plan
        self.body_half_w = math.ceil(self.half_px) + BODY_SIDE_MARGIN_PX
        self.body_centreline = self.x_origin + self.length_px + VIEW_GAP_X_PX + self.body_half_w
        self.title_x0 = self.body_centreline - self.body_half_w
        self.title_y0 = self.plan_top
        right = max(self.body_centreline + self.body_half_w, self.title_x0 + TITLE_BLOCK_W_PX)
        self.width = int(math.ceil(right + MARGIN_PX))
        bottom = max(self.plan_centreline + 50, self.title_y0 + TITLE_BLOCK_H_PX)
        self.height = int(math.ceil(bottom + MARGIN_PX))

    def regions(self) -> dict[str, list[int]]:
        pad = ROI_PAD_PX
        profile = [self.x_origin - pad, self.profile_top - pad, self.x_origin + self.length_px + pad, self.baseline + pad]
        plan = [self.x_origin - pad, self.plan_top - pad, self.x_origin + self.length_px + pad, self.plan_centreline + pad]
        body = [self.body_centreline - self.body_half_w, self.profile_top - pad, self.body_centreline + self.body_half_w,
                self.baseline + pad]
        title = [self.title_x0, self.title_y0, self.title_x0 + TITLE_BLOCK_W_PX, self.title_y0 + TITLE_BLOCK_H_PX]
        clamp = lambda box: [max(0, int(math.floor(box[0]))), max(0, int(math.floor(box[1]))),  # noqa: E731
                             min(self.width, int(math.ceil(box[2]))), min(self.height, int(math.ceil(box[3])))]
        return {"profile": clamp(profile), "half_breadth_plan": clamp(plan), "body_plan": clamp(body), "title_block": clamp(title)}


def principal_dimensions(lines: L.Lines) -> dict:
    """Dimensions printed in the title block, as a draughtsman would print them from the design."""
    return {"loa_m": lines.length_m, "lwl_m": lines.waterline_length_m, "beam_m": 2.0 * lines.max_half_breadth_m,
            "depth_m": lines.depth_m, "draft_m": lines.draft_m}


def _text(draw, xy, text, size, tone=40):
    draw.text((_ss(xy[0]), _ss(xy[1])), text, fill=R._ink(tone), font=R._font(int(size * R.SUPERSAMPLE)))


def _grid_line(draw, params, p0, p1):
    width = max(1, int(round(params["grid_width_px"] * R.SUPERSAMPLE)))
    draw.line((_ss(p0[0]), _ss(p0[1]), _ss(p1[0]), _ss(p1[1])), fill=R._ink(params["grid_tone"]), width=width)


def _datum_line(draw, params, p0, p1):
    width = max(1, int(round(params["grid_width_px"] * R.SUPERSAMPLE))) + R.SUPERSAMPLE
    draw.line((_ss(p0[0]), _ss(p0[1]), _ss(p1[0]), _ss(p1[1])), fill=R._ink(max(0, params["grid_tone"] - 60)), width=width)


CURVE_LABEL_SPACING_PX = 13


def _forward_end_row(polylines, ppm, datum_row) -> float:
    points = np.vstack(polylines)
    return datum_row - points[np.argmax(points[:, 0]), 1] * ppm


def _label_column(draw, texts: list[str], column: float, first_row: float) -> None:
    """Curve labels in one column right of a view, in the given order, one row apart."""
    for index, text in enumerate(texts):
        _text(draw, (column, first_row + index * CURVE_LABEL_SPACING_PX - 7), text, 11, 70)


def draw_profile(draw, lines: L.Lines, layout: SheetLayout, params: dict) -> None:
    ppm, x0, base = layout.ppm, layout.x_origin, layout.baseline
    right = x0 + layout.length_px
    for z in _grid_heights(lines):  # waterline rows run on through the body plan (drawn by its frame)
        row = base - z * ppm
        _grid_line(draw, params, (x0, row), (right, row))
        _text(draw, (x0 - LABEL_COLUMN_PX + 6, row - 7), f"WL{z:g}", 12, 90)
    _datum_line(draw, params, (x0 - 8, base), (right + 8, base))
    _text(draw, (x0 - LABEL_COLUMN_PX + 6, base - 7), "BL", 12, 60)
    _text(draw, (x0, MARGIN_PX), "PROFILE", 18)
    labels = []
    for y, polylines in lines.buttocks.items():
        if polylines:
            R._draw_curves(draw, polylines, _ss(x0), _ss(base), ppm, params)
            labels.append((_forward_end_row(polylines, ppm, base), f"B{y:g}"))
    if labels:  # buttock nearest the centreline first; it ends highest at the stem
        _label_column(draw, [text for _, text in labels], right + 10, min(row for row, _ in labels))
    R._draw_curves(draw, lines.profile, _ss(x0), _ss(base), ppm, params)
    R._draw_curves(draw, lines.keel, _ss(x0), _ss(base), ppm, params)
    if len(lines.deck):
        R._draw_curves(draw, [lines.deck[:, [0, 2]]], _ss(x0), _ss(base), ppm, params)


def draw_plan(draw, lines: L.Lines, layout: SheetLayout, params: dict) -> None:
    ppm, x0, centre = layout.ppm, layout.x_origin, layout.plan_centreline
    right = x0 + layout.length_px
    for y in _grid_offsets(lines):
        row = centre - y * ppm
        _grid_line(draw, params, (x0, row), (right, row))
        _text(draw, (x0 - LABEL_COLUMN_PX + 6, row - 7), f"B{y:g}", 12, 90)
    _datum_line(draw, params, (x0 - 8, centre), (right + 8, centre))
    _text(draw, (x0 - LABEL_COLUMN_PX + 6, centre - 7), "CL", 12, 60)
    _text(draw, (x0, layout.plan_top - 34), "HALF-BREADTH PLAN", 18)
    labels = []
    for z, polylines in lines.waterlines.items():
        if polylines:
            R._draw_curves(draw, polylines, _ss(x0), _ss(centre), ppm, params)
            labels.append((_forward_end_row(polylines, ppm, centre), f"WL{z:g}"))
    if labels:  # waterlines meet near the stem: highest waterline first, the column ends at the centreline
        _label_column(draw, [text for _, text in reversed(labels)], right + 10,
                      centre - CURVE_LABEL_SPACING_PX * len(labels))
    if len(lines.deck):
        R._draw_curves(draw, [lines.deck[:, [0, 1]]], _ss(x0), _ss(centre), ppm, params)


def draw_stations(draw, lines: L.Lines, layout: SheetLayout, params: dict) -> None:
    """Station lines through profile and plan, numbered above the profile and below the plan."""
    ppm, x0 = layout.ppm, layout.x_origin
    for index, station in enumerate(lines.stations):
        col = x0 + station.x_m * ppm
        _grid_line(draw, params, (col, layout.profile_top), (col, layout.baseline))
        _grid_line(draw, params, (col, layout.plan_top), (col, layout.plan_centreline))
        _text(draw, (col - 4, layout.profile_top - 22), str(index + 1), 14)
        _text(draw, (col - 4, layout.plan_centreline + 10), str(index + 1), 14)


def draw_body_plan(draw, lines: L.Lines, layout: SheetLayout, params: dict) -> None:
    """The overlay body plan of render.draw_overlay, placed on the profile baseline."""
    ppm, centre, base = layout.ppm, layout.body_centreline, layout.baseline
    half = layout.body_half_w
    R._draw_frame(draw, params, _ss(centre), _ss(base), ppm, lines.max_half_breadth_m, lines.depth_m, half, half)
    _text(draw, (centre - half, MARGIN_PX), "BODY PLAN", 18)
    for index, station in enumerate(lines.stations):
        mirror = _is_aft(station, lines)
        R._draw_curves(draw, station.curves, _ss(centre), _ss(base), ppm, params, mirror=mirror)
        top_point = max((p for c in station.curves for p in c), key=lambda p: p[1])
        sign = -1.0 if mirror else 1.0
        tx = centre + sign * top_point[0] * ppm - (10 if mirror else -2)
        ty = base - top_point[1] * ppm - 18
        _text(draw, (tx, ty), str(index + 1), 15)


def draw_title_block(draw, layout: SheetLayout, dimensions: dict, vessel_id: str, params: dict) -> None:
    x0, y0 = layout.title_x0, layout.title_y0
    box = (_ss(x0), _ss(y0), _ss(x0 + TITLE_BLOCK_W_PX), _ss(y0 + TITLE_BLOCK_H_PX))
    draw.rectangle(box, outline=R._ink(40), width=2 * R.SUPERSAMPLE)
    rows = ["LINES PLAN", vessel_id,
            f"LOA  {dimensions['loa_m']:.2f} m     LWL {dimensions['lwl_m']:.2f} m",
            f"BEAM {dimensions['beam_m']:.2f} m     DEPTH {dimensions['depth_m']:.2f} m",
            f"DRAFT (DWL) {dimensions['draft_m']:.2f} m",
            f"SCALE 1 m = {layout.ppm:.3f} px"]
    for index, row in enumerate(rows):
        _text(draw, (x0 + 10, y0 + 8 + index * 20), row, 15 if index == 0 else 13)
    # Scale bar: 10 m in 5 m halves.
    bar_y = y0 + TITLE_BLOCK_H_PX - 26
    bar_len = 10.0 * layout.ppm
    for k in range(2):
        tone = 30 if k == 0 else 255
        left = x0 + 10 + k * bar_len / 2
        draw.rectangle((_ss(left), _ss(bar_y), _ss(left + bar_len / 2), _ss(bar_y + 6)), fill=R._ink(tone), outline=R._ink(30),
                       width=R.SUPERSAMPLE)
    _text(draw, (x0 + 14 + bar_len, bar_y - 4), "10 m", 12)


def _grid_heights(lines: L.Lines) -> list[float]:
    step = lines.waterline_step_m
    return [round(k * step, 6) for k in range(1, int(lines.depth_m / step + 1e-9) + 1)]


def _grid_offsets(lines: L.Lines) -> list[float]:
    step = lines.buttock_step_m
    return [round(k * step, 6) for k in range(1, int(lines.max_half_breadth_m / step + 1e-9) + 1)]


def _is_aft(station, lines: L.Lines) -> bool:
    return station.x_m < 0.5 * lines.length_m - 1e-6


def draw_lines_sheet(lines: L.Lines, params: dict, vessel_id: str, dimensions: dict) -> tuple[R.Sheet, SheetLayout]:
    ppm = LENGTH_PX / lines.length_m * params["ppm_scale"]
    layout = SheetLayout(lines, ppm)
    image = Image.new("RGB", (layout.width * R.SUPERSAMPLE, layout.height * R.SUPERSAMPLE), (255, 255, 255))
    draw = ImageDraw.Draw(image)
    draw_stations(draw, lines, layout, params)
    draw_profile(draw, lines, layout, params)
    draw_plan(draw, lines, layout, params)
    draw_body_plan(draw, lines, layout, params)
    draw_title_block(draw, layout, dimensions, vessel_id, params)
    regions = layout.regions()
    plot_boxes = [regions[name] for name in ("profile", "half_breadth_plan", "body_plan")]
    sheet = R.Sheet(image.resize((layout.width, layout.height), Image.LANCZOS), {}, {}, {}, ppm, plot_boxes)
    return sheet, layout


# --- case ----------------------------------------------------------------------------------------
def make_lines_case(lines: L.Lines, params: dict, vessel_id: str, licence: str, description: str,
                    drawing_file: str = "drawing.png") -> tuple[np.ndarray, dict, dict, dict]:
    """Render one three-view case: (drawing array, spec, views, geometry-of-drawing record)."""
    if params["layout"] != LAYOUT:
        raise ValueError(f"layout must be {LAYOUT}")
    dimensions = principal_dimensions(lines)
    sheet, layout = draw_lines_sheet(lines, params, vessel_id, dimensions)
    image, matrix = R.degrade(sheet, params)
    height, width = image.shape[:2]
    size = (width, height)
    rng = np.random.default_rng(params["noise_seed"] + 1)
    err = params["calibration_read_error_px"]

    def read_error() -> float:
        return float(rng.uniform(-err, err))

    regions = layout.regions()
    moved = {name: R._bounding_roi(matrix, box, size) for name, box in regions.items()}

    def column_at_middle(column: float, box: list) -> float:
        return R._apply(matrix, column, 0.5 * (box[1] + box[3]))[0] + read_error()

    def row_at_middle(row: float, box: list) -> float:
        return R._apply(matrix, 0.5 * (box[0] + box[2]), row)[1] + read_error()

    ppm = layout.ppm
    body_box, profile_box, plan_box = regions["body_plan"], regions["profile"], regions["half_breadth_plan"]
    body_cal = {"pixels_per_metre": ppm, "centerline_px": column_at_middle(layout.body_centreline, body_box),
                "baseline_px": row_at_middle(layout.baseline, body_box)}
    profile_cal = {"pixels_per_metre": ppm, "x_origin_px": column_at_middle(layout.x_origin, profile_box),
                   "baseline_px": row_at_middle(layout.baseline, profile_box)}
    plan_cal = {"pixels_per_metre": ppm, "x_origin_px": column_at_middle(layout.x_origin, plan_box),
                "centerline_px": row_at_middle(layout.plan_centreline, plan_box)}
    views = {
        "schema": "marinaframe.factory.views/1", "layout": LAYOUT, "drawing": drawing_file, "units": "m",
        "sheet_size_px": [width, height],
        "frame": "x from the aft extreme (0) forward; y half-breadth from the centreplane; z up from the lowest hull point (0)",
        "calibration_note": ("Datum positions are read on the drawn grid at the middle of each region, after any sheet "
                             "rotation, with the level's calibration read error (as the body-plan sections in spec.json)."),
        "views": [
            {"id": "profile", "kind": "profile", "roi_px": moved["profile"], "calibration": profile_cal,
             "axes": {"horizontal": "x, +right (bow right)", "vertical": "z, +up"},
             "halves": {"bow": "right", "stern": "left"},
             "content": ["profile contour (keel, stem, stern) at y = %g m" % L.PROFILE_OFFSET_M,
                         "keel line (lowest centreplane point of sections)", "deck/sheer line",
                         "buttock curves", "waterline grid rows", "station lines"]},
            {"id": "half_breadth_plan", "kind": "half_breadth_plan", "roi_px": moved["half_breadth_plan"],
             "calibration": plan_cal, "axes": {"horizontal": "x, +right (bow right)", "vertical": "y half-breadth, +up"},
             "halves": {"bow": "right", "stern": "left", "above_centreline": "one side (port-starboard symmetric)"},
             "content": ["waterline curves", "deck line", "buttock grid rows", "station lines"]},
            {"id": "body_plan", "kind": "body_plan", "roi_px": moved["body_plan"], "calibration": body_cal,
             "axes": {"horizontal": "y half-breadth, + away from the centreline", "vertical": "z, +up"},
             "halves": {"right_of_centreline": "forebody (stations forward of midships)",
                        "left_of_centreline": "afterbody (stations aft of midships, drawn mirrored)"},
             "content": ["station curves", "waterline grid rows", "buttock grid columns"]},
            {"id": "title_block", "kind": "title_block", "roi_px": moved["title_block"]},
        ],
        "stations": [{"id": s.station_id, "number": i + 1, "x_m": s.x_m,
                      "body_plan_half": "left" if _is_aft(s, lines) else "right"} for i, s in enumerate(lines.stations)],
        "waterlines_z_m": list(lines.waterlines), "buttocks_y_m": list(lines.buttocks),
        "waterline_grid_z_m": _grid_heights(lines), "buttock_grid_y_m": _grid_offsets(lines),
    }
    spec = _spec(lines, layout, matrix, size, body_cal, vessel_id, licence, description, drawing_file, params)
    record = {"ppm": ppm, "sheet_size": [width, height], "image_size": [width, height], "matrix": matrix.tolist(),
              "regions_undistorted": regions, "principal_dimensions": dimensions,
              "datums_undistorted": {"x_origin_px": layout.x_origin, "baseline_px": layout.baseline,
                                     "plan_centreline_px": layout.plan_centreline,
                                     "body_centreline_px": layout.body_centreline}}
    return image, spec, views, record


def _spec(lines, layout, matrix, size, body_cal, vessel_id, licence, description, drawing_file, params) -> dict:
    """Body-plan sections in the project spec form; aft stations use the left half of the body plan."""
    top, bottom = layout.profile_top - ROI_PAD_PX, layout.baseline + ROI_PAD_PX
    centre, half = layout.body_centreline, layout.body_half_w
    notes = ("Generated three-view lines drawing (benchmark factory). Station position from the declared station list; "
             "scale, centreline and baseline read from the body-plan grid at the middle of the body-plan region.")
    sections = []
    for station in lines.stations:
        aft = _is_aft(station, lines)
        box = ([centre - half, top, centre + CENTRELINE_OVERLAP_PX, bottom] if aft
               else [centre - CENTRELINE_OVERLAP_PX, top, centre + half, bottom])
        side = "left of the centreline (afterbody, mirrored)" if aft else "right of the centreline (forebody)"
        sections.append({"id": station.station_id, "x_m": station.x_m, "roi_px": R._bounding_roi(matrix, box, size),
                         "calibration": dict(body_cal), "z_min_m": 0.0, "z_max_m": lines.depth_m,
                         "evidence": f"{notes} Station curve is {side}; several stations share the ROI."})
    transformation = (f"Synthetic three-view lines sheet, layout {LAYOUT}, degradation level {params['level']}; "
                      "no preprocessing between the sheet and drawing.png. Other views: views.json.")
    return {"schema_version": "1.0", "vessel_id": vessel_id, "units": "m",
            "source": {"file": drawing_file, "license": licence, "description": description, "transformation": transformation},
            "symmetry": "port_starboard",
            "symmetry_evidence": "Body plan and half-breadth plan draw one half; port-starboard symmetry is assumed.",
            "end_closure": "flat_at_terminal_stations", "sections": sections, "components": []}
