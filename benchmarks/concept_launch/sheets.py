"""Engineering-style sheets drawn from the concept model, with the exact region of every item.

Three sheets, each a PNG of ``SHEET_PX``:

- general arrangement: profile and main deck plan;
- lines plan: profile with buttocks, half-breadth plan with waterlines, body plan, and the
  hydrostatic particulars at the design waterline;
- tank arrangement: profile and plan of the tanks, and the tank table.

Everything is drawn from the model: part outlines are silhouettes of the part meshes, waterlines
and buttocks are plane cuts of the hull mesh, the body plan uses the loft stations, and the tank
table prints the capacity rows of the tank meshes. Every sheet carries ``SHEET_LABEL`` in a
banner and in its title block.

A region is ``(item id, view, [left, top, right, bottom])`` in sheet pixels. Because this code
draws the sheet, a region is the exact box of the item's ink plus ``REGION_PAD_PX``.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import math

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from . import SHEET_LABEL
from . import model as M

SHEET_PX = (3960, 2800)
SUPERSAMPLE = 2  # drawn at twice the size, then reduced: smooth lines
REGION_PAD_PX = 10
INK = (20, 24, 32)
FAINT = (150, 156, 166)
GRID = (196, 202, 210)
LABEL_RED = (176, 32, 32)
PAPER = (255, 255, 255)
CONTENT_FILL = {  # light fills of the tank plan, by content
    "fresh water": (190, 222, 250),
    "fuel oil": (250, 214, 170),
    "diesel oil": (246, 232, 160),
    "water ballast": (196, 236, 204),
}
DATE = "2026-11-11"
# Sheet frame: border inset, the banner row and the standard title-block box.
BORDER_PX = 40
BANNER_ROWS = (60, 140)
TITLE_BLOCK_BOX = (3080, 2140, 3920, 2760)


def _font(size: float):
    return ImageFont.load_default(size=max(8, int(round(size * SUPERSAMPLE))))


@dataclass
class View:
    """Maps model metres (a, b) to sheet pixels: column = origin_col + scale * a * a_sign,
    row = origin_row - scale * b."""
    name: str  # record view: profile, plan, body plan, table
    origin_col: float
    origin_row: float
    scale_px_per_m: float
    a_sign: float = 1.0

    def px(self, a: float, b: float) -> tuple[float, float]:
        return (self.origin_col + self.a_sign * self.scale_px_per_m * a, self.origin_row - self.scale_px_per_m * b)

    def box(self, a0: float, a1: float, b0: float, b1: float) -> list[float]:
        (c0, r0), (c1, r1) = self.px(a0, b0), self.px(a1, b1)
        return [min(c0, c1), min(r0, r1), max(c0, c1), max(r0, r1)]


@dataclass
class Sheet:
    key: str  # ga, lines, tanks
    file_name: str
    title: str
    number: int
    image: Image.Image = field(init=False)
    draw: ImageDraw.ImageDraw = field(init=False)
    regions: list[tuple[str, str, list[float]]] = field(default_factory=list)

    def __post_init__(self):
        width, height = SHEET_PX
        self.image = Image.new("RGB", (width * SUPERSAMPLE, height * SUPERSAMPLE), PAPER)
        self.draw = ImageDraw.Draw(self.image)

    # --- drawing primitives (sheet pixel coordinates) ---
    @staticmethod
    def _scaled(points):
        return [(x * SUPERSAMPLE, y * SUPERSAMPLE) for x, y in points]

    def line(self, points, width: float = 2.0, fill=INK, dash: tuple[float, float] | None = None):
        points = [tuple(map(float, p)) for p in points]
        if len(points) < 2:
            return
        if dash is None:
            self.draw.line(self._scaled(points), fill=fill, width=max(1, int(round(width * SUPERSAMPLE))), joint="curve")
            return
        for piece in _dashed(points, *dash):
            self.draw.line(self._scaled(piece), fill=fill, width=max(1, int(round(width * SUPERSAMPLE))))

    def polygon(self, points, outline=INK, fill=None, width: float = 2.0):
        points = [tuple(map(float, p)) for p in points]
        if fill is not None:
            self.draw.polygon(self._scaled(points), fill=fill)
        if outline is not None:
            self.line(points + [points[0]], width=width, fill=outline)

    def rect(self, box, outline=INK, fill=None, width: float = 2.0):
        left, top, right, bottom = box
        self.polygon([(left, top), (right, top), (right, bottom), (left, bottom)], outline, fill, width)

    def text(self, xy, text: str, size: float = 22, fill=INK, anchor: str = "la"):
        self.draw.text((xy[0] * SUPERSAMPLE, xy[1] * SUPERSAMPLE), text, font=_font(size), fill=fill, anchor=anchor)

    def text_box(self, xy, text: str, size: float = 22, anchor: str = "la") -> list[float]:
        left, top, right, bottom = self.draw.textbbox((xy[0] * SUPERSAMPLE, xy[1] * SUPERSAMPLE), text,
                                                      font=_font(size), anchor=anchor)
        return [left / SUPERSAMPLE, top / SUPERSAMPLE, right / SUPERSAMPLE, bottom / SUPERSAMPLE]

    # --- regions ---
    def add_region(self, item: str, view: str, box: list[float], pad: float = REGION_PAD_PX):
        width, height = SHEET_PX
        left, top, right, bottom = box
        padded = [max(0.0, left - pad), max(0.0, top - pad), min(float(width), right + pad), min(float(height), bottom + pad)]
        self.regions.append((item, view, [round(v, 1) for v in padded]))

    def finish(self) -> Image.Image:
        return self.image.resize(SHEET_PX, Image.Resampling.LANCZOS)


def _dashed(points, on: float, off: float):
    """Split a polyline into dash pieces of ``on`` pixels with gaps of ``off`` pixels."""
    pieces, current, drawn, pen_down = [], [points[0]], 0.0, True
    for (x0, y0), (x1, y1) in zip(points, points[1:]):
        length = math.hypot(x1 - x0, y1 - y0)
        position = 0.0
        while length - position > 1e-9:
            limit = (on if pen_down else off) - drawn
            step = min(limit, length - position)
            position += step
            drawn += step
            t = position / length
            point = (x0 + (x1 - x0) * t, y0 + (y1 - y0) * t)
            if pen_down:
                current.append(point)
            if drawn >= (on if pen_down else off) - 1e-9:
                if pen_down and len(current) > 1:
                    pieces.append(current)
                pen_down, drawn, current = not pen_down, 0.0, [point]
    if pen_down and len(current) > 1:
        pieces.append(current)
    return pieces


# --- mesh cuts --------------------------------------------------------------------------------

AXIS = {"x": 0, "y": 1, "z": 2}


def plane_segments(triangles: np.ndarray, axis: int, value: float) -> np.ndarray:
    """Segments (n, 2, 3) where the plane ``coordinate[axis] = value`` cuts a triangle soup."""
    value = value + 1e-7  # keep vertices off the plane
    distance = triangles[:, :, axis] - value
    crossing = (distance.min(axis=1) < 0) & (distance.max(axis=1) > 0)
    tri, dist = triangles[crossing], distance[crossing]
    segments = []
    for i, j in ((0, 1), (1, 2), (2, 0)):
        di, dj = dist[:, i], dist[:, j]
        cut = di * dj < 0
        t = np.where(cut, di / np.where(cut, di - dj, 1.0), 0.0)
        point = tri[:, i] + t[:, None] * (tri[:, j] - tri[:, i])
        segments.append((cut, point))
    rows = []
    for k in range(len(tri)):
        found = [point[k] for cut, point in segments if cut[k]]
        if len(found) == 2:
            rows.append(found)
    return np.array(rows).reshape(-1, 2, 3)


def silhouette(triangles: np.ndarray, a_axis: int, b_axis: int, samples: int = 80) -> list[tuple[float, float]]:
    """Outline [(a, b), ...] of the projection of a mesh on the (a, b) plane, sampled across a:
    the lower boundary forward, the upper boundary back. Exact for shapes whose cut at each a is
    one interval of b (every part outline drawn here)."""
    low, high = float(triangles[:, :, a_axis].min()), float(triangles[:, :, a_axis].max())
    inset = (high - low) * 1e-4
    lower, upper = [], []
    for a in np.linspace(low + inset, high - inset, samples):
        cut = plane_segments(triangles, a_axis, a)
        if not len(cut):
            continue
        values = cut[:, :, b_axis]
        lower.append((float(a), float(values.min())))
        upper.append((float(a), float(values.max())))
    if not lower:
        return []
    return [(low, lower[0][1]), *lower, (high, lower[-1][1]), (high, upper[-1][1]), *upper[::-1], (low, upper[0][1])]


def chain_segments(segments: np.ndarray, a_axis: int, b_axis: int, tol: float = 1e-6) -> list[list[tuple[float, float]]]:
    """Join cut segments into polylines in (a, b)."""
    pieces = [[(float(s[0, a_axis]), float(s[0, b_axis])), (float(s[1, a_axis]), float(s[1, b_axis]))] for s in segments]
    chains: list[list[tuple[float, float]]] = []
    while pieces:
        chain = pieces.pop()
        grown = True
        while grown:
            grown = False
            for index, piece in enumerate(pieces):
                for start, end in ((piece[0], piece[1]), (piece[1], piece[0])):
                    if math.dist(chain[-1], start) < tol:
                        chain.append(end)
                    elif math.dist(chain[0], end) < tol:
                        chain.insert(0, start)
                    else:
                        continue
                    pieces.pop(index)
                    grown = True
                    break
                if grown:
                    break
        chains.append(chain)
    return chains


def station_label(station_id: str) -> str:
    """'st09h' -> '9.5', 'st00' -> '0'."""
    number = int(station_id[2:4])
    return f"{number}.5" if station_id.endswith("h") else str(number)


def _runs(points, keep) -> list[list]:
    """Runs of consecutive points for which ``keep(point)`` is true."""
    runs, current = [], []
    for point in points:
        if keep(point):
            current.append(point)
        elif current:
            runs.append(current)
            current = []
    if current:
        runs.append(current)
    return runs


def _px_box(points_px) -> list[float]:
    columns = [p[0] for p in points_px]
    rows = [p[1] for p in points_px]
    return [min(columns), min(rows), max(columns), max(rows)]


# --- shared furniture -------------------------------------------------------------------------

def draw_frame_and_banner(sheet: Sheet) -> None:
    width, height = SHEET_PX
    sheet.rect((BORDER_PX, BORDER_PX, width - BORDER_PX, height - BORDER_PX), width=4)
    sheet.rect((BORDER_PX + 12, BORDER_PX + 12, width - BORDER_PX - 12, height - BORDER_PX - 12), width=1.5)
    top, bottom = BANNER_ROWS
    sheet.rect((BORDER_PX + 12, top, width - BORDER_PX - 12, bottom), outline=LABEL_RED, fill=(253, 240, 240), width=3)
    sheet.text((width / 2, (top + bottom) / 2), SHEET_LABEL, size=40, fill=LABEL_RED, anchor="mm")


def draw_title_block(sheet: Sheet, notes: list[str]) -> None:
    left, top, right, bottom = TITLE_BLOCK_BOX
    sheet.rect((left, top, right, bottom), width=3)
    rows = [top + 110, top + 200, top + 290, top + 380]
    for row in rows:
        sheet.line([(left, row), (right, row)], width=1.5)
    sheet.text((left + 20, top + 18), "CONCEPT PREVIEW", size=34, fill=LABEL_RED)
    sheet.text((left + 20, top + 62), "Example drawing generated for this demo. Not a real vessel.", size=21, fill=LABEL_RED)
    sheet.text((left + 20, rows[0] + 18), "SURVEY LAUNCH 24 m", size=34)
    sheet.text((left + 20, rows[0] + 60), "Example vessel (made up)", size=22)
    sheet.text((left + 20, rows[1] + 18), sheet.title.upper(), size=34)
    sheet.text((left + 20, rows[1] + 60), f"Sheet {sheet.number} of 3", size=22)
    sheet.text((left + 20, rows[2] + 18), "Drawn from the MarinaFrame concept 3D model", size=22)
    sheet.text((left + 20, rows[2] + 50), f"Dimensions in metres. Date {DATE}.", size=22)
    for index, note in enumerate(notes[:6]):
        sheet.text((left + 20, rows[3] + 16 + 34 * index), note, size=21)


def draw_scale_bar(sheet: Sheet, col: float, row: float, scale_px_per_m: float, metres: int = 5) -> None:
    for i in range(metres):
        left = col + i * scale_px_per_m
        sheet.rect((left, row, left + scale_px_per_m, row + 14), fill=INK if i % 2 == 0 else None, width=1.5)
    for i in (0, metres):
        sheet.text((col + i * scale_px_per_m, row + 22), f"{i} m", size=20, anchor="ma")
    sheet.text((col, row - 12), "SCALE BAR", size=20, anchor="ld")


def draw_frame_scale(sheet: Sheet, view: View, row: float, last_frame: int = 48) -> None:
    """Frame ticks along a view (every frame), numbers every 5 frames."""
    start, end = view.px(0, 0)[0], view.px(last_frame * M.FRAME_SPACING_M, 0)[0]
    sheet.line([(start, row), (end, row)], width=1.5)
    for frame in range(0, last_frame + 1):
        col = view.px(frame * M.FRAME_SPACING_M, 0)[0]
        tall = frame % 5 == 0
        sheet.line([(col, row), (col, row + (18 if tall else 9))], width=1.5)
        if tall:
            sheet.text((col, row + 22), str(frame), size=19, anchor="ma")
    sheet.text((start - 16, row + 4), "FR", size=19, anchor="rm")


def view_title(sheet: Sheet, xy, text: str) -> None:
    sheet.text(xy, text, size=30)
    box = sheet.text_box(xy, text, size=30)
    sheet.line([(box[0], box[3] + 6), (box[2], box[3] + 6)], width=2)


# --- geometry helpers for drawing ---------------------------------------------------------------

def keel_line(samples: int = 160) -> list[tuple[float, float]]:
    return [(float(x), M.keel_height(float(x))) for x in np.linspace(0.0, M.BOW_END_X_M, samples)]


def hull_profile_outline() -> list[tuple[float, float]]:
    """Centreline profile of the moulded hull: transom, keel, stem and deck."""
    return [(0.0, M.DEPTH_M), *keel_line(), (M.BOW_END_X_M, M.DEPTH_M)]


def deck_edge(samples: int = 160) -> list[tuple[float, float]]:
    return [(float(x), M.deck_half_breadth(float(x))) for x in np.linspace(0.0, M.BOW_END_X_M, samples)]


@dataclass
class Model:
    """What the sheets need from the model: parts by id with their meshes (metres)."""
    parts: dict  # id -> model.Part
    triangles: dict  # id -> (n, 3, 3)
    capacity: dict  # tank id -> capacity row (vessel_reconstruction.tanks.capacity_row)
    hydrostatics: dict  # at the design draft


def _part_outline(sheet: Sheet, view: View, model: Model, part_id: str, a_axis: str, b_axis: str,
                  width: float = 2.5, fill=None, record: bool = True) -> list[tuple[float, float]]:
    outline = silhouette(model.triangles[part_id], AXIS[a_axis], AXIS[b_axis])
    points = [view.px(a, b) for a, b in outline]
    sheet.polygon(points, outline=INK, fill=fill, width=width)
    if record:
        sheet.add_region(part_id, view.name, _px_box(points))
    return points


# --- sheet 1: general arrangement ---------------------------------------------------------------

GA_SCALE = 110.0
GA_PROFILE = View("profile", 300, 1500, GA_SCALE)
GA_PLAN = View("plan", 300, 2130, GA_SCALE)


def draw_ga(model: Model, file_name: str) -> Sheet:
    sheet = Sheet("ga", file_name, "General arrangement", 1)
    draw_frame_and_banner(sheet)
    profile, plan = GA_PROFILE, GA_PLAN
    view_title(sheet, (300, 170), "PROFILE")
    view_title(sheet, (300, 1650), "MAIN DECK PLAN")

    # Profile: hull, decks, inner bottom, waterline.
    hull_points = [profile.px(x, z) for x, z in hull_profile_outline()]
    sheet.polygon(hull_points, width=3.5)
    sheet.line([profile.px(-0.6, 0), profile.px(24.6, 0)], width=1.2, fill=FAINT, dash=(26, 10))
    sheet.text(profile.px(-0.7, 0), "BL", size=20, anchor="rm")
    dwl = M.DESIGN_DRAFT_M
    sheet.line([profile.px(-0.6, dwl), profile.px(24.6, dwl)], width=1.5, fill=(40, 90, 170), dash=(30, 8))
    sheet.text(profile.px(24.7, dwl), f"DWL {dwl:.2f}", size=20, fill=(40, 90, 170), anchor="lm")
    deck_box = _px_box([profile.px(0, M.DEPTH_M - 0.06), profile.px(M.BOW_END_X_M, M.DEPTH_M + 0.06)])
    sheet.add_region("main_deck", "profile", deck_box)
    sheet.text(profile.px(4.6, M.DEPTH_M + 0.12), f"MAIN DECK {M.DEPTH_M:.2f}", size=21, anchor="ld")
    ib0, ib1 = M.INNER_BOTTOM_X_M
    sheet.line([profile.px(ib0, M.INNER_BOTTOM_Z_M), profile.px(ib1, M.INNER_BOTTOM_Z_M)], width=1.5, fill=FAINT, dash=(14, 8))

    # Superstructure, bulwarks, deck equipment and appendages, each a silhouette of its mesh.
    for part_id in ("house_t1", "wheelhouse", "aft_bulwark", "fwd_bulwark", "a_frame", "mast", "rudder", "skeg",
                    "sonar_gondola"):
        _part_outline(sheet, profile, model, part_id, "x", "z")
    _ga_windows(sheet, profile)
    sheet.text(profile.px(12.6, 3.85), "SURVEY LAB", size=24, anchor="mm")
    sheet.text(profile.px(13.1, 6.4), "WHEELHOUSE", size=24, anchor="mm")
    sheet.text(profile.px(1.6, 7.6), "A-FRAME", size=20, anchor="lm")
    sheet.text(profile.px(13.5, 11.3), "MAST", size=20, anchor="lm")
    sheet.text(profile.px(16.7, -0.25), "SONAR GONDOLA", size=19, anchor="lm")
    sheet.text(profile.px(0.7, 1.1), "RUDDER", size=19, anchor="mm")
    sheet.text(profile.px(5.0, 0.6), "SKEG", size=19, anchor="mm")

    # Bulkheads (full lines) and web frames (thin dash-dot), as the model has them.
    for part_id, _, frame in M.BULKHEADS:
        x = M.frame_x(frame)
        points = [profile.px(x, M.keel_height(x)), profile.px(x, M.DEPTH_M)]
        sheet.line(points, width=3)
        sheet.add_region(part_id, "profile", _px_box(points))
        sheet.text(profile.px(x, M.DEPTH_M - 0.35), "BHD", size=17, anchor="mm")
    for frame in M.WEB_FRAMES:
        x = M.frame_x(frame)
        points = [profile.px(x, M.keel_height(x)), profile.px(x, M.DEPTH_M)]
        sheet.line(points, width=1.2, fill=(90, 96, 110), dash=(16, 6))
        sheet.add_region(f"web_fr{frame:02d}", "profile", _px_box(points), pad=6)
    draw_frame_scale(sheet, profile, 1575)

    # Plan: deck edge, bulwark insides, centreline, deckhouse, A-frame.
    edge = deck_edge()
    port = [plan.px(x, y) for x, y in edge]
    starboard = [plan.px(x, -y) for x, y in edge]
    deck_points = port + starboard[::-1]
    sheet.polygon(deck_points, width=3.5)
    sheet.add_region("main_deck", "plan", _px_box(deck_points))
    sheet.line([plan.px(-0.6, 0), plan.px(24.6, 0)], width=1.2, fill=FAINT, dash=(40, 8))
    sheet.text(plan.px(24.7, 0), "CL", size=20, anchor="lm")
    for part_id, x_range in (("aft_bulwark", (0.0, 9.0)), ("fwd_bulwark", (17.0, M.BOW_END_X_M))):
        xs = np.linspace(*x_range, 60)
        inside = [(float(x), M.deck_half_breadth(float(x)) - M.BULWARK_PLATE_M) for x in xs
                  if M.deck_half_breadth(float(x)) - M.BULWARK_PLATE_M > 0.03]
        for side in (1, -1):
            sheet.line([plan.px(x, side * y) for x, y in inside], width=1.5)
        outside = [plan.px(float(x), side * M.deck_half_breadth(float(x))) for x in xs for side in (1, -1)]
        sheet.add_region(part_id, "plan", _px_box(outside))
    _part_outline(sheet, plan, model, "house_t1", "x", "y", fill=(240, 242, 246))
    sheet.text(plan.px(13.0, 0.6), "DECKHOUSE TIER 1", size=24, anchor="mm")
    sheet.text(plan.px(13.0, -0.6), "(survey lab below wheelhouse)", size=20, anchor="mm")
    _part_outline(sheet, plan, model, "a_frame", "x", "y")
    sheet.text(plan.px(1.2, 2.9), "A-FRAME", size=19, anchor="lm")
    draw_frame_scale(sheet, plan, 2570)

    _particulars_panel(sheet, model, (3080, 200))
    draw_scale_bar(sheet, 3110, 2050, GA_SCALE, 5)
    draw_title_block(sheet, ["Profile and main deck plan.", "Wheelhouse plan not drawn (deliberate:",
                             "its breadth is a labelled guess in the demo)."])
    return sheet


def _ga_windows(sheet: Sheet, profile: View) -> None:
    for x in np.arange(9.6, 16.4, 1.1):
        sheet.rect(_px_box([profile.px(x, 4.5), profile.px(x + 0.6, 5.2)]), width=1.5)
    for x in np.arange(11.3, 14.6, 0.85):
        sheet.rect(_px_box([profile.px(x, 7.0), profile.px(x + 0.55, 7.8)]), width=1.5)
    sheet.rect(_px_box([profile.px(16.2, 3.5), profile.px(16.75, 5.3)]), width=1.5)  # door


def _particulars_panel(sheet: Sheet, model: Model, origin) -> None:
    col, row = origin
    hydro = model.hydrostatics
    lines = [
        ("PRINCIPAL PARTICULARS", None),
        ("Length overall", f"{M.LENGTH_M:.2f} m"),
        ("Beam moulded", f"{2 * M.HALF_BEAM_M:.2f} m"),
        ("Depth moulded", f"{M.DEPTH_M:.2f} m"),
        ("Design draft", f"{M.DESIGN_DRAFT_M:.2f} m"),
        ("Displacement", f"{hydro['displacement_t']:.1f} t"),
        ("Frame spacing", f"{M.FRAME_SPACING_M:.2f} m"),
    ]
    for index, (name, value) in enumerate(lines):
        y = row + 46 * index
        if value is None:
            sheet.text((col, y), name, size=26)
            continue
        sheet.text((col, y), name, size=22)
        sheet.text((col + 790, y), value, size=22, anchor="ra")


# --- sheet 2: lines plan -------------------------------------------------------------------------

LINES_SCALE = 125.0
LINES_PROFILE = View("profile", 250, 690, LINES_SCALE)
LINES_PLAN = View("plan", 250, 1260, LINES_SCALE)
BODY_SCALE = 250.0
BODY_PLAN = View("body plan", 1200, 2330, BODY_SCALE)
WATERLINES_M = (0.4, 0.8, 1.2, 1.6, 2.0, 2.4, 2.8)
BUTTOCKS_M = (0.8, 1.6, 2.4, 3.2)


def draw_lines(model: Model, file_name: str) -> Sheet:
    sheet = Sheet("lines", file_name, "Lines plan", 2)
    draw_frame_and_banner(sheet)
    profile, plan, body = LINES_PROFILE, LINES_PLAN, BODY_PLAN
    hull = model.triangles["hull"]
    view_title(sheet, (250, 170), "PROFILE (BUTTOCKS)")
    view_title(sheet, (250, 760), "HALF-BREADTH PLAN (WATERLINES)")
    view_title(sheet, (250, 1330), "BODY PLAN")

    # Grids: waterlines across profile and body plan, buttocks across plan and body plan, stations.
    for z in (0.0, *WATERLINES_M, M.DEPTH_M):
        sheet.line([profile.px(-0.3, z), profile.px(24.3, z)], width=1, fill=GRID)
        sheet.text(profile.px(-0.4, z), "BL" if z == 0 else f"WL {z:.1f}", size=17, fill=FAINT, anchor="rm")
    for y in (0.0, *BUTTOCKS_M):
        sheet.line([plan.px(-0.3, y), plan.px(24.3, y)], width=1, fill=GRID)
        sheet.text(plan.px(-0.4, y), "CL" if y == 0 else f"B {y:.1f}", size=17, fill=FAINT, anchor="rm")
    for station_id, x in M.BODY_PLAN_STATIONS:
        for view, top in ((profile, M.DEPTH_M + 0.15), (plan, M.HALF_BEAM_M + 0.1)):
            sheet.line([view.px(x, -0.05), view.px(x, top)], width=1, fill=GRID)
        sheet.text(profile.px(x, M.DEPTH_M + 0.25), station_label(station_id),
                   size=18, fill=FAINT, anchor="md")

    # Profile: centreline outline and buttocks cut from the hull mesh.
    outline = [profile.px(x, z) for x, z in hull_profile_outline()]
    sheet.polygon(outline, width=3)
    for y in BUTTOCKS_M:
        for chain in chain_segments(plane_segments(hull, 1, y), 0, 2):
            sheet.line([profile.px(a, b) for a, b in chain], width=1.6)
    sheet.line([profile.px(-0.3, M.DESIGN_DRAFT_M), profile.px(24.3, M.DESIGN_DRAFT_M)], width=1.5,
               fill=(40, 90, 170), dash=(30, 8))
    sheet.add_region("hull", "profile", _px_box(outline))

    # Plan: waterlines (starboard half cut, drawn to port as is customary) and the deck line.
    plan_ink = []
    for z in WATERLINES_M:
        for chain in chain_segments(plane_segments(hull, 2, z), 0, 1):
            # Keep the starboard half of each closed waterline, run by run (no jumps across).
            for run in _runs(chain, lambda point: point[1] <= 1e-6):
                if len(run) < 2:
                    continue
                points = [plan.px(a, abs(b)) for a, b in run]
                sheet.line(points, width=2.2 if abs(z - M.DESIGN_DRAFT_M) < 1e-9 else 1.6,
                           fill=(40, 90, 170) if abs(z - M.DESIGN_DRAFT_M) < 1e-9 else INK)
                plan_ink += points
    deck = [plan.px(x, y) for x, y in deck_edge()]
    sheet.line(deck, width=3)
    plan_ink += deck + [plan.px(0, 0), plan.px(M.BOW_END_X_M, 0)]
    sheet.add_region("hull", "plan", _px_box(plan_ink))

    # Body plan: the loft stations; aft half to the left of the centreline, forward to the right.
    for z in (0.0, *WATERLINES_M, M.DEPTH_M):
        sheet.line([body.px(-3.9, z), body.px(3.9, z)], width=1, fill=GRID)
    for y in (*BUTTOCKS_M, 0.0):
        for side in (1, -1):
            sheet.line([body.px(side * y, -0.1), body.px(side * y, M.DEPTH_M + 0.1)], width=1, fill=GRID)
    sheet.line([body.px(-3.9, M.DESIGN_DRAFT_M), body.px(3.9, M.DESIGN_DRAFT_M)], width=1.5, fill=(40, 90, 170), dash=(24, 8))
    sheet.text(body.px(-1.9, -0.25), "AFT (st 0 to 5)", size=21, anchor="mt")
    sheet.text(body.px(1.9, -0.25), "FORWARD (st 6 to 9.5)", size=21, anchor="mt")
    body_ink = []
    labelled_cols: list[float] = []
    for station_id, x in M.BODY_PLAN_STATIONS:
        side = -1.0 if x <= M.LENGTH_M / 2 + 1e-9 else 1.0
        points = [body.px(side * y, z) for y, z in M.section_points(x)]
        sheet.line(points, width=2.2)
        # Coinciding stations (the parallel midbody) get their labels stacked, not overprinted.
        label_col, label_row = points[-1]
        stacked = sum(1 for col in labelled_cols if abs(col - label_col) < 30)
        labelled_cols.append(label_col)
        label_row -= 8
        label_col += side * 24 * stacked  # outward, away from the centreline
        sheet.text((label_col, label_row), station_label(station_id), size=18, anchor="md")
        sheet.add_region(station_id, "body plan", _px_box(points + [(label_col, label_row - 20)]))
        body_ink += points
    sheet.add_region("hull", "body plan", _px_box(body_ink))

    _hydrostatics_table(sheet, model, (2300, 1400))
    draw_scale_bar(sheet, 3110, 2050, LINES_SCALE, 5)
    draw_title_block(sheet, ["Body plan drawn at twice the scale of", "profile and plan. Lines are cuts of",
                             "the concept hull model."])
    return sheet


def _hydrostatics_table(sheet: Sheet, model: Model, origin) -> None:
    col, row = origin
    hydro = model.hydrostatics
    entries = [
        ("Draft (level)", f"{hydro['draft_m']:.2f} m"),
        ("Displacement (sea water)", f"{hydro['displacement_t']:.1f} t"),
        ("Volume of displacement", f"{hydro['volume_m3']:.1f} m3"),
        ("LCB from transom", f"{hydro['lcb_m']:.2f} m"),
        ("KB", f"{hydro['kb_m']:.2f} m"),
        ("KM transverse", f"{hydro['km_m']:.2f} m"),
        ("Waterplane area", f"{hydro['waterplane_area_m2']:.1f} m2"),
        ("LCF from transom", f"{hydro['lcf_m']:.2f} m"),
        ("Tonnes per cm immersion", f"{hydro['tpc_t_cm']:.2f} t"),
        ("Block coefficient", f"{hydro['block_coefficient']:.3f}"),
    ]
    sheet.text((col, row), "HYDROSTATICS AT DWL", size=26)
    top = row + 44
    for index, (name, value) in enumerate(entries):
        y = top + 44 * index
        sheet.line([(col, y - 8), (col + 900, y - 8)], width=1, fill=GRID)
        sheet.text((col, y), name, size=21)
        sheet.text((col + 900, y), value, size=21, anchor="ra")
    sheet.add_region("hydrostatics", "table", [col, row - 30, col + 900, top + 44 * len(entries)])


# --- sheet 3: tank arrangement ---------------------------------------------------------------------

TANK_SCALE = 125.0
TANK_PROFILE = View("profile", 250, 700, TANK_SCALE)
TANK_PLAN = View("plan", 250, 1340, TANK_SCALE)
TABLE_ORIGIN = (250, 1960)
TABLE_COLUMNS = (("Tank", 0), ("Content", 520), ("Frames", 860), ("Volume 100 %", 1180), ("Weight 98 %", 1460),
                 ("LCG", 1730), ("VCG", 1930))


def draw_tank_plan(model: Model, file_name: str) -> Sheet:
    sheet = Sheet("tanks", file_name, "Tank arrangement", 3)
    draw_frame_and_banner(sheet)
    profile, plan = TANK_PROFILE, TANK_PLAN
    view_title(sheet, (250, 170), "PROFILE AT CENTRELINE")
    view_title(sheet, (250, 820), "TANK PLAN (TANKS AT THEIR TOPS)")
    tanks = [part for part in model.parts.values() if part.op == "tank"]

    # Profile: tanks first (filled), then hull, inner bottom and bulkheads over them.
    for part in tanks:
        fill = CONTENT_FILL.get(part.tank.content)
        outline = silhouette(model.triangles[part.id], 0, 2)
        points = [profile.px(a, b) for a, b in outline]
        guessed_top = part.guess is not None
        sheet.polygon(points, outline=None if guessed_top else INK, fill=fill, width=2)
        if guessed_top:  # the top of this tank is deliberately not drawn
            sheet.line(points[: len(points) // 2 + 1], width=2)
        sheet.add_region(part.id, "profile", _px_box(points))
    sheet.polygon([profile.px(x, z) for x, z in hull_profile_outline()], width=3)
    ib0, ib1 = M.INNER_BOTTOM_X_M
    ib = [profile.px(ib0, M.INNER_BOTTOM_Z_M), profile.px(ib1, M.INNER_BOTTOM_Z_M)]
    sheet.line(ib, width=2.5)
    sheet.add_region("inner_bottom", "profile", _px_box(ib))
    sheet.text(profile.px(ib0 - 0.1, M.INNER_BOTTOM_Z_M + 0.05), f"INNER BOTTOM {M.INNER_BOTTOM_Z_M:.2f}", size=18, anchor="rd")
    girder = [profile.px(ib0, 0.02), profile.px(ib1, 0.02)]
    sheet.line(girder, width=1.2, fill=(90, 96, 110), dash=(10, 6))
    sheet.add_region("centre_girder", "profile", _px_box(ib + girder))
    for part_id, label, frame in M.BULKHEADS:
        x = M.frame_x(frame)
        points = [profile.px(x, M.keel_height(x)), profile.px(x, M.DEPTH_M)]
        sheet.line(points, width=3.5)
        sheet.add_region(part_id, "profile", _px_box(points))
        sheet.text(profile.px(x, M.DEPTH_M + 0.12), f"BHD FR {frame}", size=18, anchor="md")
    profile_labels = {"tank_fw1": "FW1", "tank_fo1": "FO1", "tank_wb1": "WB1 / WB2 (P/S)", "tank_do1": "DO1",
                      "tank_fpt": "FPT"}
    for part in tanks:
        if part.id not in profile_labels:
            continue
        x0, x1 = part.tank.x_m
        label_x = (x0 + x1) / 2 + (0.6 if part.id == "tank_fpt" else 0.0)
        label_z = 2.1 if part.id == "tank_fpt" else 0.6
        sheet.text(profile.px(label_x, label_z), profile_labels[part.id], size=18, anchor="mm")
    draw_frame_scale(sheet, profile, 770)

    # Plan: hull at the inner bottom (solid) and the deck edge (dashed); tanks as projections.
    hull = model.triangles["hull"]
    for chain in chain_segments(plane_segments(hull, 2, M.INNER_BOTTOM_Z_M), 0, 1):
        sheet.line([plan.px(a, b) for a, b in chain], width=2.5)
    for side in (1, -1):
        sheet.line([plan.px(x, side * y) for x, y in deck_edge()], width=1.2, fill=FAINT, dash=(16, 8))
    sheet.line([plan.px(-0.4, 0), plan.px(24.4, 0)], width=1.2, fill=FAINT, dash=(40, 8))
    for part in tanks:
        fill = CONTENT_FILL.get(part.tank.content)
        points = [plan.px(a, b) for a, b in silhouette(model.triangles[part.id], 0, 1)]
        sheet.polygon(points, fill=fill, width=2)
        sheet.add_region(part.id, "plan", _px_box(points))
        x0, x1 = part.tank.x_m
        y0, y1 = part.tank.y_m
        centre_y = (max(y0, -2.0) + min(y1, 2.0)) / 2
        sheet.text(plan.px((x0 + x1) / 2, centre_y + 0.18), part.id.replace("tank_", "").upper(), size=20, anchor="mm")
        sheet.text(plan.px((x0 + x1) / 2, centre_y - 0.22), f"{model.capacity[part.id]['volume_100_m3']:.1f} m3",
                   size=18, anchor="mm")
    for part_id, _, frame in M.BULKHEADS:
        x = M.frame_x(frame)
        half = M.deck_half_breadth(x)
        sheet.line([plan.px(x, -half), plan.px(x, half)], width=3)
    draw_frame_scale(sheet, plan, 1840)

    _tank_table(sheet, model, tanks)
    _legend(sheet, (3110, 1500))
    draw_scale_bar(sheet, 3110, 2050, TANK_SCALE, 5)
    draw_title_block(sheet, ["Volumes are of the moulded tank solids", "(no deduction for structure).",
                             "FW1 top deliberately not drawn."])
    return sheet


def _tank_table(sheet: Sheet, model: Model, tanks) -> None:
    col, row = TABLE_ORIGIN
    width = 2100
    sheet.text((col, row - 50), "TANK TABLE", size=26)
    sheet.rect((col, row, col + width, row + 46 * (len(tanks) + 1)), width=2)
    for name, offset in TABLE_COLUMNS:
        sheet.text((col + 12 + offset, row + 12), name, size=21)
    for index, part in enumerate(tanks):
        top = row + 46 * (index + 1)
        sheet.line([(col, top), (col + width, top)], width=1.2)
        capacity = model.capacity[part.id]
        frames = f"{round(part.tank.x_m[0] / M.FRAME_SPACING_M)} to {round(part.tank.x_m[1] / M.FRAME_SPACING_M)}"
        cells = [f"{part.id.replace('tank_', '').upper()}  {part.label}", part.tank.content, frames,
                 f"{capacity['volume_100_m3']:.2f} m3", f"{capacity['weight_98_t']:.2f} t",
                 f"{capacity['lcg_m']:.2f} m", f"{capacity['vcg_m']:.2f} m"]
        for (_, offset), cell in zip(TABLE_COLUMNS, cells):
            sheet.text((col + 12 + offset, top + 12), cell, size=21)
        sheet.add_region(part.id, "table", [col, top, col + width, top + 46], pad=2)


def _legend(sheet: Sheet, origin) -> None:
    col, row = origin
    sheet.text((col, row - 40), "LEGEND", size=24)
    for index, (content, fill) in enumerate(CONTENT_FILL.items()):
        top = row + 44 * index
        sheet.rect((col, top, col + 60, top + 30), fill=fill, width=1.5)
        sheet.text((col + 80, top + 4), content, size=21)


def draw_all(model: Model, names: dict[str, str]) -> list[Sheet]:
    """The three sheets; ``names`` gives the file name of each sheet key."""
    return [draw_ga(model, names["ga"]), draw_lines(model, names["lines"]), draw_tank_plan(model, names["tanks"])]
