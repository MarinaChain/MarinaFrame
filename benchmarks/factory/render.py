"""Body-plan drawing renderer with controllable realism.

A drawing is made in four steps:

1. ``sample_params``: every rendering parameter is drawn from the ranges of one *degradation
   level* (0 clean ... 3 heavy) with a seeded generator. The full parameter record is stored
   with the case.
2. ``draw_sheet``: the true station curves are drawn at 2x supersampling (line weights, grid of
   water-lines and buttocks, station labels, centreline, baseline), then reduced to the target size.
3. ``degrade``: paper tone, uneven light, rotation and shear, blur, scan noise, speckle,
   partial occlusion and JPEG artefacts, in that fixed order.
4. ``make_spec``: the section specification (ROIs, scale, datum, station positions) that an
   operator would declare for this drawing. Rotation is compensated by declaring the datum
   at the middle of each ROI (the specification has no tilt field).

Two layouts:

- ``separate``: one starboard half section per panel, in a grid (section sheets). Each panel ROI
  holds one station curve. This is the layout the deterministic policy can resolve.
- ``overlay``: the classic body plan. All stations share one centreline, afterbody to the left and
  forebody to the right, with station labels. The sheet is then cut into a forebody and a mirrored
  afterbody panel (as the Gunnerus raster path does) and every ROI is the whole panel, so a
  section ROI holds many curves.

No truth value enters the specification: only station positions, ROIs, scale, datum, z range.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

SUPERSAMPLE = 2
STATION_FRACTIONS = tuple(round(0.1 * k, 1) for k in range(1, 10))  # 9 stations, 10 % ... 90 % of the length
ROI_LEFT_MARGIN_PX = 40  # columns kept left of the centreline in a panel
ROI_RIGHT_MARGIN_PX = 30
COMPOSITE_GAP_PX = 40
COMPOSITE_MARGIN_PX = 40
PAGE_MARGIN_PX = 90

LEVEL_NAMES = {0: "clean", 1: "mild", 2: "moderate", 3: "heavy"}

# (low, high) ranges drawn uniformly, per level. Integers are drawn as integers.
LEVELS: dict[int, dict] = {
    0: dict(ppm_scale=(1.0, 1.0), hull_w=(3.0, 3.0), hull_tone=(15, 15), grid_w=(1.0, 1.0), grid_tone=(205, 205),
            cl_style=("light",), cl_tone=(170, 170), paper=((255, 255, 255), (255, 255, 255)), illumination=(0.0, 0.0),
            rotation_deg=(0.0, 0.0), shear=(0.0, 0.0), blur_sigma=(0.0, 0.0), noise_sd=(0.0, 0.0),
            speckles_per_mpx=(0, 0), jpeg_quality=(100, 100), labels_in_roi_p=0.0, occlusions=(0, 0),
            calibration_read_error_px=(0.0, 0.0)),
    1: dict(ppm_scale=(0.9, 1.0), hull_w=(2.0, 4.0), hull_tone=(20, 50), grid_w=(1.0, 1.0), grid_tone=(170, 210),
            cl_style=("light", "dashdot"), cl_tone=(120, 170), paper=((236, 232, 218), (252, 250, 244)),
            illumination=(0.02, 0.05), rotation_deg=(-0.2, 0.2), shear=(-0.001, 0.001), blur_sigma=(0.4, 0.7),
            noise_sd=(2.0, 4.0), speckles_per_mpx=(20, 60), jpeg_quality=(88, 95), labels_in_roi_p=0.25,
            occlusions=(0, 0), calibration_read_error_px=(0.0, 0.0)),
    2: dict(ppm_scale=(0.75, 0.95), hull_w=(1.5, 4.0), hull_tone=(30, 80), grid_w=(1.0, 2.0), grid_tone=(130, 180),
            cl_style=("dashdot", "solid"), cl_tone=(80, 130), paper=((222, 216, 196), (244, 238, 224)),
            illumination=(0.05, 0.10), rotation_deg=(-0.6, 0.6), shear=(-0.003, 0.003), blur_sigma=(0.8, 1.2),
            noise_sd=(4.0, 8.0), speckles_per_mpx=(80, 200), jpeg_quality=(60, 80), labels_in_roi_p=0.6,
            occlusions=(0, 1), calibration_read_error_px=(0.0, 0.5)),
    3: dict(ppm_scale=(0.5, 0.8), hull_w=(1.5, 3.0), hull_tone=(50, 110), grid_w=(1.0, 2.0), grid_tone=(90, 140),
            cl_style=("solid", "dashdot"), cl_tone=(50, 100), paper=((200, 192, 168), (232, 224, 204)),
            illumination=(0.10, 0.18), rotation_deg=(-1.2, 1.2), shear=(-0.008, 0.008), blur_sigma=(1.2, 1.9),
            noise_sd=(8.0, 14.0), speckles_per_mpx=(200, 500), jpeg_quality=(35, 55), labels_in_roi_p=1.0,
            occlusions=(1, 2), calibration_read_error_px=(0.0, 1.5)),
}

PANEL_MAX_W_PX = 560.0  # starboard half-breadth plus margins fit this at ppm_scale 1
PANEL_MAX_H_PX = 640.0
SEPARATE_COLUMNS = 3
PANEL_GAP_X_PX = 120
PANEL_GAP_Y_PX = 130


def _uniform(rng: np.random.Generator, bounds: tuple) -> float:
    low, high = bounds
    return float(low if low == high else rng.uniform(low, high))


def sample_params(level: int, layout: str, seed: int) -> dict:
    """Draw every rendering parameter for one drawing. Pure function of (level, layout, seed)."""
    rng = np.random.default_rng(seed)
    cfg = LEVELS[level]
    low_paper, high_paper = np.array(cfg["paper"][0]), np.array(cfg["paper"][1])
    mix = float(rng.uniform())
    paper = [int(round(v)) for v in low_paper + mix * (high_paper - low_paper)]
    return {
        "level": level, "level_name": LEVEL_NAMES[level], "layout": layout, "seed": seed,
        "ppm_scale": _uniform(rng, cfg["ppm_scale"]), "hull_width_px": _uniform(rng, cfg["hull_w"]),
        "hull_tone": int(_uniform(rng, cfg["hull_tone"])), "grid_width_px": _uniform(rng, cfg["grid_w"]),
        "grid_tone": int(_uniform(rng, cfg["grid_tone"])),
        "centreline_style": str(rng.choice(cfg["cl_style"])), "centreline_tone": int(_uniform(rng, cfg["cl_tone"])),
        "paper_rgb": paper, "illumination_amplitude": _uniform(rng, cfg["illumination"]),
        "illumination_phase": [float(rng.uniform(0, 2 * math.pi)), float(rng.uniform(0, 2 * math.pi))],
        "rotation_deg": _uniform(rng, cfg["rotation_deg"]), "shear": _uniform(rng, cfg["shear"]),
        "blur_sigma_px": _uniform(rng, cfg["blur_sigma"]), "noise_sd": _uniform(rng, cfg["noise_sd"]),
        "speckles_per_mpx": int(_uniform(rng, cfg["speckles_per_mpx"])),
        "jpeg_quality": int(_uniform(rng, cfg["jpeg_quality"])),
        "labels_in_roi": bool(rng.uniform() < cfg["labels_in_roi_p"]),
        "occlusion_count": int(rng.integers(cfg["occlusions"][0], cfg["occlusions"][1] + 1)),
        "calibration_read_error_px": _uniform(rng, cfg["calibration_read_error_px"]),
        "noise_seed": int(rng.integers(0, 2 ** 31 - 1)),
    }


def _font(size: int):
    return ImageFont.load_default(size=size)


def _nice_step(extent: float, target_lines: int) -> float:
    for step in (0.25, 0.5, 1.0, 2.0, 2.5, 5.0, 10.0, 20.0, 25.0, 50.0):
        if extent / step <= target_lines:
            return step
    return 100.0


@dataclass
class Station:
    station_id: str
    x_m: float
    curves: list  # starboard polylines (y, z) in metres


@dataclass
class Sheet:
    image: Image.Image  # RGB at final size (before degradation)
    rois: dict  # station_id -> [x0, y0, x1, y1] on the sheet
    centreline_px: dict  # station_id -> column
    baseline_px: dict  # station_id -> row
    ppm: float
    plot_boxes: list  # [x0, y0, x1, y1] regions used for occlusion
    overlay_centreline_px: float | None = None


def _dashdot(draw: ImageDraw.ImageDraw, p0, p1, fill, width, scale):
    """Dash-dot line from p0 to p1 (either vertical or horizontal)."""
    pattern = [(18, True), (5, False), (3, True), (5, False)]
    (x0, y0), (x1, y1) = p0, p1
    length = math.hypot(x1 - x0, y1 - y0)
    dx, dy = (x1 - x0) / length, (y1 - y0) / length
    position, index = 0.0, 0
    while position < length:
        run, on = pattern[index % 4]
        run *= scale
        end = min(length, position + run)
        if on:
            draw.line((x0 + dx * position, y0 + dy * position, x0 + dx * end, y0 + dy * end), fill=fill, width=width)
        position, index = end, index + 1


def _ink(tone: int) -> tuple[int, int, int]:
    return (tone, tone, int(min(255, tone + 4)))


def _draw_frame(draw, params, x_cl, baseline, ppm, hb_max, depth, extent_left, extent_right, label_stations=True):
    """Grid of buttocks (vertical) and waterlines (horizontal), centreline, baseline. Pixel coords at SS scale."""
    ss = SUPERSAMPLE
    grid = _ink(params["grid_tone"])
    grid_w = max(1, int(round(params["grid_width_px"] * ss)))
    font = _font(12 * ss)
    buttock_step = _nice_step(hb_max, 6)
    waterline_step = _nice_step(depth, 8)
    top = baseline - depth * ppm * ss
    # Buttock lines (vertical, constant y).
    k = 1
    while k * buttock_step <= hb_max + 1e-9:
        for side, extent in ((1, extent_right), (-1, extent_left)):
            if k * buttock_step * ppm > extent:  # beyond the printed width of this side
                continue
            x = x_cl + side * k * buttock_step * ppm * ss
            draw.line((x, top, x, baseline), fill=grid, width=grid_w)
            draw.text((x - 6 * ss, baseline + 5 * ss), f"{k * buttock_step:g}", fill=_ink(90), font=font)
        k += 1
    # Waterlines (horizontal, constant z).
    k = 1
    while k * waterline_step <= depth + 1e-9:
        y = baseline - k * waterline_step * ppm * ss
        draw.line((x_cl - extent_left * ss, y, x_cl + extent_right * ss, y), fill=grid, width=grid_w)
        draw.text((x_cl - extent_left * ss - 38 * ss, y - 7 * ss), f"WL{k * waterline_step:g}", fill=_ink(90), font=font)
        k += 1
    # Baseline (keel datum): solid, heavier than the grid.
    draw.line((x_cl - extent_left * ss, baseline, x_cl + extent_right * ss, baseline), fill=_ink(max(0, params["grid_tone"] - 60)),
              width=grid_w + ss)
    # Centreline.
    tone = _ink(params["centreline_tone"])
    style = params["centreline_style"]
    p0, p1 = (x_cl, baseline + 8 * ss), (x_cl, top - 10 * ss)
    if style == "dashdot":
        _dashdot(draw, p0, p1, tone, grid_w + (ss // 2), ss)
    else:
        draw.line((p0, p1), fill=tone, width=grid_w + (ss // 2))
    return buttock_step, waterline_step


def _draw_curves(draw, curves, x_cl, baseline, ppm, params, mirror=False):
    ss = SUPERSAMPLE
    ink = _ink(params["hull_tone"])
    width = max(1, int(round(params["hull_width_px"] * ss)))
    sign = -1.0 if mirror else 1.0
    for curve in curves:
        points = [(x_cl + sign * y * ppm * ss, baseline - z * ppm * ss) for y, z in curve]
        draw.line(points, fill=ink, width=width, joint="curve")
        # Round end caps so a thick stroke does not end square.
        for px, py in (points[0], points[-1]):
            draw.ellipse((px - width / 2, py - width / 2, px + width / 2, py + width / 2), fill=ink)


def choose_ppm(depth: float, hb_max: float, scale: float) -> float:
    width_budget = PANEL_MAX_W_PX - ROI_LEFT_MARGIN_PX - ROI_RIGHT_MARGIN_PX
    return float(min(width_budget / hb_max, (PANEL_MAX_H_PX - 8) / depth) * scale)


def draw_separate(stations: list[Station], depth: float, hb_max: float, params: dict) -> Sheet:
    ss = SUPERSAMPLE
    ppm = choose_ppm(depth, hb_max, params["ppm_scale"])
    panel_w = ROI_LEFT_MARGIN_PX + math.ceil(hb_max * ppm) + ROI_RIGHT_MARGIN_PX
    panel_h = math.ceil(depth * ppm) + 4
    columns = SEPARATE_COLUMNS
    rows = math.ceil(len(stations) / columns)
    width = 2 * PAGE_MARGIN_PX + columns * panel_w + (columns - 1) * PANEL_GAP_X_PX
    height = 2 * PAGE_MARGIN_PX + rows * (panel_h + PANEL_GAP_Y_PX)
    image = Image.new("RGB", (width * ss, height * ss), (255, 255, 255))
    draw = ImageDraw.Draw(image)
    title_font = _font(17 * ss)
    tag_font = _font(15 * ss)
    rois, centre, base, boxes = {}, {}, {}, []
    for index, station in enumerate(stations):
        row, col = divmod(index, columns)
        x0 = PAGE_MARGIN_PX + col * (panel_w + PANEL_GAP_X_PX)
        y0 = PAGE_MARGIN_PX + row * (panel_h + PANEL_GAP_Y_PX) + 30
        x_cl = x0 + ROI_LEFT_MARGIN_PX
        baseline = y0 + 2 + depth * ppm
        _draw_frame(draw, params, x_cl * ss, baseline * ss, ppm, hb_max, depth, ROI_LEFT_MARGIN_PX - 8,
                    panel_w - ROI_LEFT_MARGIN_PX - 4)
        _draw_curves(draw, station.curves, x_cl * ss, baseline * ss, ppm, params)
        draw.text((x0 * ss, (y0 - 30) * ss), f"BODY PLAN  STATION {index + 1}", fill=_ink(40), font=title_font)
        if params["labels_in_roi"]:
            # A section tag inside the panel, near the upper right, as on drawings that label in place.
            draw.text(((x0 + panel_w - 62) * ss, (y0 + 10) * ss), f"No.{index + 1}", fill=_ink(60), font=tag_font)
        top = int(math.floor(baseline - depth * ppm)) - 2
        bottom = int(math.ceil(baseline)) + 2
        rois[station.station_id] = [x0, max(0, top), x0 + panel_w, bottom]
        centre[station.station_id], base[station.station_id] = float(x_cl), float(baseline)
        boxes.append([x0, max(0, top), x0 + panel_w, bottom])
    return Sheet(image.resize((width, height), Image.LANCZOS), rois, centre, base, ppm, boxes)


def draw_overlay(stations: list[Station], depth: float, hb_max: float, params: dict, aft_count: int) -> Sheet:
    """One shared centreline: the first ``aft_count`` stations to the left, the rest to the right."""
    ss = SUPERSAMPLE
    ppm = choose_ppm(depth, hb_max, params["ppm_scale"]) * 1.35  # a single plot can use a bigger sheet
    half_w = math.ceil(hb_max * ppm) + 30
    plot_h = math.ceil(depth * ppm) + 4
    width = 2 * PAGE_MARGIN_PX + 2 * half_w + 2 * ROI_LEFT_MARGIN_PX
    height = 2 * PAGE_MARGIN_PX + plot_h + 60
    image = Image.new("RGB", (width * ss, height * ss), (255, 255, 255))
    draw = ImageDraw.Draw(image)
    x_cl = width / 2
    baseline = PAGE_MARGIN_PX + 30 + 2 + depth * ppm
    _draw_frame(draw, params, x_cl * ss, baseline * ss, ppm, hb_max, depth, half_w, half_w)
    tag_font = _font(15 * ss)
    title_font = _font(18 * ss)
    draw.text(((x_cl - half_w) * ss, (PAGE_MARGIN_PX - 10) * ss), "BODY PLAN", fill=_ink(40), font=title_font)
    for index, station in enumerate(stations):
        mirror = index < aft_count
        _draw_curves(draw, station.curves, x_cl * ss, baseline * ss, ppm, params, mirror=mirror)
        # Station label just above the top end of its curve (always present on a body plan).
        top_point = max((p for c in station.curves for p in c), key=lambda p: p[1])
        sign = -1.0 if mirror else 1.0
        tx = x_cl + sign * top_point[0] * ppm - (10 if mirror else -2)
        ty = baseline - top_point[1] * ppm - 18
        draw.text((tx * ss, ty * ss), str(index + 1), fill=_ink(40), font=tag_font)
    top = int(math.floor(baseline - depth * ppm)) - 2
    bottom = int(math.ceil(baseline)) + 2
    sheet = Sheet(image.resize((width, height), Image.LANCZOS), {}, {}, {}, ppm,
                  [[int(x_cl - half_w), max(0, top), int(x_cl + half_w), bottom]], overlay_centreline_px=float(x_cl))
    sheet.baseline_px = {"overlay": float(baseline)}
    sheet.rois = {"overlay": [int(x_cl - half_w), max(0, top), int(x_cl + half_w), bottom]}
    return sheet


# --- degradation -----------------------------------------------------------------------------
def degrade(sheet: Sheet, params: dict) -> tuple[np.ndarray, np.ndarray]:
    """Return (degraded RGB uint8 array, 2x3 affine matrix mapping sheet pixels to output pixels)."""
    rng = np.random.default_rng(params["noise_seed"])
    image = np.asarray(sheet.image, dtype=np.float32)
    height, width = image.shape[:2]
    paper = np.array(params["paper_rgb"], dtype=np.float32) / 255.0
    # Paper tone and uneven light: ink stays dark, paper takes the tone.
    yy, xx = np.mgrid[0:height, 0:width].astype(np.float32)
    phase_x, phase_y = params["illumination_phase"]
    field = (np.sin(xx / width * math.pi * 1.3 + phase_x) + np.sin(yy / height * math.pi * 1.1 + phase_y)) * 0.5
    light = 1.0 - params["illumination_amplitude"] * (field * 0.5 + 0.5)
    image = image * paper[None, None, :] * light[:, :, None]
    # Rotation and shear about the page centre; the border takes the paper tone.
    angle = math.radians(params["rotation_deg"])
    rotation = np.array([[math.cos(angle), -math.sin(angle)], [math.sin(angle), math.cos(angle)]])
    shear = np.array([[1.0, params["shear"]], [0.0, 1.0]])
    linear = rotation @ shear
    centre = np.array([width / 2, height / 2])
    matrix = np.hstack([linear, (centre - linear @ centre)[:, None]])
    if params["rotation_deg"] != 0.0 or params["shear"] != 0.0:
        border = tuple(float(v) for v in (paper * 255.0 * (1.0 - params["illumination_amplitude"] * 0.5)))
        image = cv2.warpAffine(image, matrix, (width, height), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT,
                               borderValue=border)
    if params["blur_sigma_px"] > 0:
        image = cv2.GaussianBlur(image, (0, 0), params["blur_sigma_px"])
    if params["noise_sd"] > 0:
        grain = rng.normal(0.0, params["noise_sd"], (height, width)).astype(np.float32)
        image = image + grain[:, :, None]
        coarse = cv2.resize(rng.normal(0.0, params["noise_sd"] * 0.6, (height // 16 + 1, width // 16 + 1)).astype(np.float32),
                            (width, height), interpolation=cv2.INTER_CUBIC)
        image = image + coarse[:, :, None]
    speckles = int(params["speckles_per_mpx"] * height * width / 1e6)
    for _ in range(speckles):
        sx, sy = int(rng.integers(0, width)), int(rng.integers(0, height))
        radius = int(rng.integers(1, 3))
        cv2.circle(image, (sx, sy), radius, (float(rng.integers(20, 120)),) * 3, -1)
    # Partial occlusion: tape, stamp or stain rectangles anywhere inside a plot box (may cover the curve).
    occlusions = []
    for _ in range(params["occlusion_count"]):
        box = sheet.plot_boxes[int(rng.integers(0, len(sheet.plot_boxes)))]
        bw, bh = box[2] - box[0], box[3] - box[1]
        ow, oh = int(bw * rng.uniform(0.08, 0.18)), int(bh * rng.uniform(0.04, 0.10))
        ox = int(box[0] + rng.uniform(0, max(1, bw - ow)))
        oy = int(box[1] + rng.uniform(0, max(1, bh - oh)))
        tone = float(rng.integers(110, 215))
        alpha = float(rng.uniform(0.75, 1.0))
        region = image[oy:oy + oh, ox:ox + ow]
        image[oy:oy + oh, ox:ox + ow] = region * (1 - alpha) + tone * alpha
        occlusions.append({"x0": ox, "y0": oy, "x1": ox + ow, "y1": oy + oh, "tone": tone, "alpha": alpha})
    params["occlusions"] = occlusions
    image = np.clip(image, 0, 255).astype(np.uint8)
    if params["jpeg_quality"] < 100:
        ok, encoded = cv2.imencode(".jpg", cv2.cvtColor(image, cv2.COLOR_RGB2BGR), [cv2.IMWRITE_JPEG_QUALITY, params["jpeg_quality"]])
        if not ok:
            raise RuntimeError("JPEG encoding failed")
        image = cv2.cvtColor(cv2.imdecode(encoded, cv2.IMREAD_COLOR), cv2.COLOR_BGR2RGB)
    return image, matrix


def _apply(matrix: np.ndarray, x: float, y: float) -> tuple[float, float]:
    return (float(matrix[0, 0] * x + matrix[0, 1] * y + matrix[0, 2]), float(matrix[1, 0] * x + matrix[1, 1] * y + matrix[1, 2]))


def _bounding_roi(matrix: np.ndarray, roi: list, size: tuple[int, int]) -> list[int]:
    corners = [_apply(matrix, x, y) for x in (roi[0], roi[2]) for y in (roi[1], roi[3])]
    xs, ys = [c[0] for c in corners], [c[1] for c in corners]
    return [max(0, int(math.floor(min(xs)))), max(0, int(math.floor(min(ys)))),
            min(size[0], int(math.ceil(max(xs)))), min(size[1], int(math.ceil(max(ys))))]


# --- specification ---------------------------------------------------------------------------
def make_case(stations: list[Station], depth: float, hb_max: float, length_m: float, params: dict, vessel_id: str,
              licence: str, description: str, drawing_file: str = "drawing.png") -> tuple[np.ndarray, dict, dict]:
    """Render one case: returns (drawing array, spec dict, geometry-of-drawing record)."""
    layout = params["layout"]
    if layout == "separate":
        sheet = draw_separate(stations, depth, hb_max, params)
    else:
        aft_count = sum(1 for s in stations if s.x_m < 0.5 * length_m - 1e-6)  # aft of midships
        sheet = draw_overlay(stations, depth, hb_max, params, aft_count)
    image, matrix = degrade(sheet, params)
    height, width = image.shape[:2]
    rng = np.random.default_rng(params["noise_seed"] + 1)
    err = params["calibration_read_error_px"]
    sections, record = [], {"ppm": sheet.ppm, "sheet_size": [width, height], "matrix": matrix.tolist()}
    notes = ("Generated body-plan drawing (benchmark factory). Station position from the declared station list; "
             "scale, centreline and baseline read from the drawn grid at the middle of the ROI.")
    if layout == "separate":
        for station in stations:
            roi = sheet.rois[station.station_id]
            mid_x, mid_y = 0.5 * (roi[0] + roi[2]), 0.5 * (roi[1] + roi[3])
            x_cl_t, _ = _apply(matrix, sheet.centreline_px[station.station_id], mid_y)
            _, y_base_t = _apply(matrix, mid_x, sheet.baseline_px[station.station_id])
            new_roi = _bounding_roi(matrix, roi, (width, height))
            sections.append({
                "id": station.station_id, "x_m": station.x_m, "roi_px": new_roi,
                "calibration": {"centerline_px": x_cl_t + float(rng.uniform(-err, err)),
                                "baseline_px": y_base_t + float(rng.uniform(-err, err)),
                                "pixels_per_metre": sheet.ppm},
                "z_min_m": 0.0, "z_max_m": depth, "evidence": notes})
        output = image
        transformation = (f"Synthetic body-plan sheet, layout separate, degradation level {params['level']}; "
                          "no preprocessing between the sheet and drawing.png.")
    else:
        output, sections, transformation = _composite_overlay(image, sheet, matrix, stations, depth, length_m, params, rng, err, notes)
        height, width = output.shape[:2]
    spec = {"schema_version": "1.0", "vessel_id": vessel_id, "units": "m",
            "source": {"file": drawing_file, "license": licence, "description": description, "transformation": transformation},
            "symmetry": "port_starboard",
            "symmetry_evidence": "Body plan draws one half per station; port-starboard symmetry is assumed.",
            "end_closure": "flat_at_terminal_stations", "sections": sections, "components": []}
    record["image_size"] = [width, height]
    return output, spec, record


def _composite_overlay(image, sheet, matrix, stations, depth, length_m, params, rng, err, notes):
    """Cut the overlay sheet into right panel and mirrored left panel (as raster_path.compose)."""
    roi = sheet.rois["overlay"]
    mid_y = 0.5 * (roi[1] + roi[3])
    cl_x, _ = _apply(matrix, sheet.overlay_centreline_px, mid_y)
    _, base_y = _apply(matrix, sheet.overlay_centreline_px, sheet.baseline_px["overlay"])
    cl = int(round(cl_x))
    plot_left, plot_right = roi[0], roi[2]
    start = max(0, cl - COMPOSITE_MARGIN_PX)
    right = image[:, start:min(image.shape[1], plot_right + 40)]
    stop = min(image.shape[1], cl + COMPOSITE_MARGIN_PX + 1)
    left_mirrored = image[:, max(0, plot_left - 40):stop][:, ::-1]
    gap = np.full((image.shape[0], COMPOSITE_GAP_PX, 3), 255, dtype=np.uint8)
    composite = np.concatenate([right, gap, left_mirrored], axis=1)
    right_w = right.shape[1]
    mirrored_x0 = right_w + COMPOSITE_GAP_PX
    left_start = max(0, plot_left - 40)
    # original column c (c < stop) maps to mirrored_x0 + (stop - 1 - c) - left_start' ... computed from the slice
    left_width = stop - left_start
    def mirrored_col(c):
        return mirrored_x0 + (left_width - 1 - (c - left_start))
    right_cl = cl_x - start
    left_cl = mirrored_col(cl_x)
    new_roi = _bounding_roi(matrix, roi, (image.shape[1], image.shape[0]))
    top, bottom = new_roi[1], new_roi[3]
    aft_limit = 0.5 * length_m - 1e-6
    sections = []
    for station in stations:
        aft = station.x_m < aft_limit
        x0, x1 = (mirrored_x0, composite.shape[1]) if aft else (0, right_w)
        sections.append({
            "id": station.station_id, "x_m": station.x_m, "roi_px": [int(x0), int(max(0, top)), int(x1), int(min(image.shape[0], bottom))],
            "calibration": {"centerline_px": float((left_cl if aft else right_cl) + rng.uniform(-err, err)),
                            "baseline_px": float(base_y + rng.uniform(-err, err)), "pixels_per_metre": sheet.ppm},
            "z_min_m": 0.0, "z_max_m": depth,
            "evidence": notes + " ROI is the whole half body plan on this side; several stations share it."})
    transformation = (f"Synthetic body-plan sheet, layout overlay, degradation level {params['level']}; columns right of the "
                      f"centreline unchanged, then {COMPOSITE_GAP_PX} white columns, then the columns left of the centreline "
                      f"mirrored; each panel keeps {COMPOSITE_MARGIN_PX} columns across the centreline.")
    return composite, sections, transformation


def clean_deck_edge(curves: list, depth: float, tol_fraction: float = 1.0e-3) -> list:
    """Remove horizontal deck lid lines at the hull top; keep the outer deck-edge point.

    A body plan draws the half section up to the deck edge. Closed CAD hulls also cut the flat deck
    surface, which would appear as a horizontal line to the centreline.
    """
    top = depth - tol_fraction * depth
    cleaned = []
    for curve in curves:
        curve = np.asarray(curve)
        on_top = curve[:, 1] >= top
        if on_top.sum() >= 2:
            keep = ~on_top
            outer = np.flatnonzero(on_top)[np.argmax(curve[on_top, 0])]
            keep[outer] = True
            curve = curve[keep]
        if len(curve) >= 2:
            cleaned.append(curve)
    return cleaned
