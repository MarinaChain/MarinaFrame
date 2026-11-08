"""Built station cuts drawn back onto the source body plan, with a per-section scoreboard.

After a draft build, the render worker slices the tessellation of the
reimported STEP at every declared station and draws each cut on the source
panel, at that section's calibration. A person or the model can then see where
the CAD differs from the drawing. The scoreboard gives, for each section and in
metres:
  - the distance from the reference curve (the built trace or authored curve,
    or for an unbuilt station its best trace) to the built cut, and
  - the ink fit: the distance from the built cut to the nearest dark ink pixel
    in the section's source region, so an authored curve that misses the ink
    shows a large value even though the CAD follows the curve exactly,
and the section's source label (traced, repaired, interpolated, ai_inferred,
ai_corrected, ...).

The render tessellation is used, not an exact BRep section: an exact section
of a draft hull with thousands of faces takes seconds per station, and the
tessellation is already made for the render. Its chord tolerance is reported.

This is a display and self-check aid only. It never fails a build or a render:
the caller skips the overlay with a warning on any error.
"""
from __future__ import annotations

import json
from pathlib import Path
import time

import numpy as np

# Distinct line colours, one per station in a panel (Tableau 10, darkened for
# contrast on a light background).
PALETTE = ("#1f77b4", "#d62728", "#2ca02c", "#9467bd", "#ff7f0e",
           "#17becf", "#8c564b", "#e377c2", "#7f7f7f", "#bcbd22")
# The overlay cuts at most this many stations; a body plan has far fewer.
MAX_SECTIONS = 64
# Panels with more stations than this are still drawn, but share colours.
MAX_PANELS = 24
# Longest side of a panel image, in pixels; a smaller panel is enlarged up to
# MAX_PANEL_ENLARGEMENT times so its lines and labels stay readable.
MAX_PANEL_SIDE_PX = 1400
MAX_PANEL_ENLARGEMENT = 2.0
# Margin around the union of a panel's section regions, in source pixels.
PANEL_MARGIN_PX = 24
# Grey level (0-255) that black source ink takes in the faded panel background.
FADED_INK_GREY = 90
# Longest side of the sheet that tiles all panel images, in pixels.
MAX_SHEET_SIDE_PX = 2000
# Seconds the overlay may spend on cuts; later stations are skipped, so a big
# hull cannot push the render past its worker time limit.
CUT_BUDGET_SECONDS = 30.0
# Each station is sliced this far (m) aft and forward of its plane, and both
# slices are kept: a region solid or a terminal cap that ends exactly on the
# plane is then still cut.
SLICE_OFFSET_M = 1e-6
# A source pixel darker than this grey level (0-255) counts as ink.
INK_THRESHOLD = 128
# Ink fit ignores cut points within this many source pixels of the centreline
# or of the cut's top: those are closure lines, which the drawing need not ink.
INK_FIT_CLOSURE_MARGIN_PX = 2.0
# The ink-fit "near" fraction counts cut points within this many pixels of ink.
INK_NEAR_PX = 2.0
# A cut point counts as starboard (drawn) when its half-breadth is at least
# this value in metres; port-side points would draw over other ink.
STARBOARD_MIN_Y_M = -1e-6
# Built sections whose label says the curve was authored by the model.
AUTHORED_LABELS = ("ai_inferred", "ai_corrected")


def reference_distances(reference_yz: np.ndarray, starts: np.ndarray, ends: np.ndarray) -> dict:
    """Distance (m) from each reference sample to the nearest cut segment: max, RMS and 95th percentile."""
    vectors = ends - starts
    length2 = np.maximum(np.sum(vectors * vectors, axis=1), 1e-18)
    delta = reference_yz[:, None, :] - starts[None, :, :]
    parameter = np.clip(np.sum(delta * vectors[None, :, :], axis=2) / length2, 0, 1)
    closest = starts[None, :, :] + parameter[:, :, None] * vectors[None, :, :]
    distance = np.sqrt(np.min(np.sum((reference_yz[:, None, :] - closest) ** 2, axis=2), axis=1))
    return {"sample_count": int(len(distance)), "max_m": float(np.max(distance)),
            "rms_m": float(np.sqrt(np.mean(distance ** 2))), "p95_m": float(np.percentile(distance, 95))}


def slice_mesh(vertices_m: np.ndarray, triangles: np.ndarray, x_m: float) -> np.ndarray:
    """Segments (n x 2 x 2; y and z in metres) where the triangle mesh crosses the plane x = x_m."""
    pieces = []
    for plane in (x_m - SLICE_OFFSET_M, x_m + SLICE_OFFSET_M):
        corners = vertices_m[triangles]                  # (T, 3 corners, xyz)
        signed = corners[:, :, 0] - plane                # (T, 3)
        above = signed >= 0
        crossing = above.any(axis=1) & ~above.all(axis=1)
        corners, signed, above = corners[crossing], signed[crossing], above[crossing]
        points, valid = [], []
        for a, b in ((0, 1), (1, 2), (2, 0)):
            cuts_edge = above[:, a] != above[:, b]
            denominator = np.where(cuts_edge, signed[:, a] - signed[:, b], 1.0)
            fraction = (signed[:, a] / denominator)[:, None]
            points.append(corners[:, a] + fraction * (corners[:, b] - corners[:, a]))
            valid.append(cuts_edge)
        points, valid = np.stack(points, axis=1), np.stack(valid, axis=1)
        # A crossing triangle has exactly two crossing edges; keep their points in order.
        pieces.append(points[valid].reshape(-1, 2, 3)[:, :, 1:])
    return np.concatenate(pieces)


def ink_fit(segments: np.ndarray, calibration: dict, roi_px, image: np.ndarray, side: int = 1) -> dict | None:
    """Distance (m) from built cut points to the nearest ink pixel in the section region, or None.

    Only starboard cut points away from the centreline and the cut's top are
    used (closure lines). None when the region has no ink or no usable point.
    ``side`` is -1 for a station drawn mirrored, left of its centreline.
    """
    from scipy.ndimage import distance_transform_edt
    ppm = float(calibration["pixels_per_metre"])
    margin = INK_FIT_CLOSURE_MARGIN_PX / ppm
    points = np.concatenate([segments[:, 0], segments[:, 1], segments.mean(axis=1)])
    points = points[(points[:, 0] > margin) & (points[:, 1] < points[:, 1].max() - margin)]
    height, width = image.shape[:2]
    x0, y0 = max(0, int(roi_px[0])), max(0, int(roi_px[1]))
    x1, y1 = min(width, int(roi_px[2])), min(height, int(roi_px[3]))
    ink = image[y0:y1, x0:x1] < INK_THRESHOLD
    if not ink.any() or not len(points):
        return None
    distance_px = distance_transform_edt(~ink)
    columns = np.rint(float(calibration["centerline_px"]) + side * points[:, 0] * ppm).astype(int) - x0
    rows = np.rint(float(calibration["baseline_px"]) - points[:, 1] * ppm).astype(int) - y0
    inside = (columns >= 0) & (columns < x1 - x0) & (rows >= 0) & (rows < y1 - y0)
    if not inside.any():
        return None
    measured = distance_px[rows[inside], columns[inside]]
    return {"sample_count": int(len(measured)), "outside_region_count": int(np.sum(~inside)),
            "max_m": float(np.max(measured) / ppm), "rms_m": float(np.sqrt(np.mean(measured ** 2)) / ppm),
            "near_fraction": float(np.mean(measured <= INK_NEAR_PX))}


def score_section(row: dict, reference_yz, segments: np.ndarray | None, pixels_per_metre: float) -> dict:
    """Fill a scoreboard row from its reference curve and its cut segments (shape n x 2 x 2)."""
    if segments is None or len(segments) == 0:
        return {**row, "status": "no_cut"}
    if reference_yz is None or len(reference_yz) == 0:
        return {**row, "status": "no_reference"}
    scores = reference_distances(np.asarray(reference_yz, dtype=float), segments[:, 0], segments[:, 1])
    return {**row, "status": "scored", **scores, "max_px": scores["max_m"] * pixels_per_metre}


def group_panels(sections: list[dict]) -> list[list[int]]:
    """Indices of sections grouped into panels: sections whose source regions overlap share a panel.

    Panels are ordered by their first station (``sections`` are in station order).
    """
    parent = list(range(len(sections)))

    def root(index):
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    for a in range(len(sections)):
        for b in range(a + 1, len(sections)):
            ax0, ay0, ax1, ay1 = sections[a]["roi_px"]
            bx0, by0, bx1, by1 = sections[b]["roi_px"]
            if min(ax1, bx1) > max(ax0, bx0) and min(ay1, by1) > max(ay0, by0):
                parent[root(b)] = root(a)
    groups = {}
    for index in range(len(sections)):
        groups.setdefault(root(index), []).append(index)
    return sorted(groups.values(), key=min)


def _to_pixels(points_yz, calibration) -> list[tuple[float, float]]:
    ppm = float(calibration["pixels_per_metre"])
    centre, baseline = float(calibration["centerline_px"]), float(calibration["baseline_px"])
    return [(centre + y * ppm, baseline - z * ppm) for y, z in points_yz]


def draw_panel(image: np.ndarray, sections: list[dict], rows: list[dict], cuts: list, references: list,
               path: Path, title: str) -> dict:
    """One panel: faded source, each station's cut (solid) and reference (dots) in its own colour."""
    from PIL import Image, ImageDraw, ImageFont
    from .fonts import dejavu_sans
    box = (min(s["roi_px"][0] for s in sections) - PANEL_MARGIN_PX,
           min(s["roi_px"][1] for s in sections) - PANEL_MARGIN_PX,
           max(s["roi_px"][2] for s in sections) + PANEL_MARGIN_PX,
           max(s["roi_px"][3] for s in sections) + PANEL_MARGIN_PX)
    panel, (x0, y0, x1, y1), scale = faded_crop(image, box)
    # Text and lines grow with the panel, so they stay readable when the
    # panel is shrunk into the sheet.
    unit = max(1.0, panel.width / 500)
    text_px, line_px = int(13 * unit), int(18 * unit)
    try:
        font, small = dejavu_sans(int(16 * unit)), dejavu_sans(text_px)
    except OSError:
        font = small = ImageFont.load_default()
    legend_rows = len(sections) + 3
    canvas = Image.new("RGB", (max(panel.width, 720), panel.height + line_px * legend_rows + 16), "white")
    canvas.paste(panel, (0, 0))
    draw = ImageDraw.Draw(canvas)

    def to_view(px, py):
        return ((px - x0) * scale, (py - y0) * scale)

    for section, row, cut, reference in zip(sections, rows, cuts, references):
        colour = row["colour"]
        calibration = section["calibration"]
        if reference is not None and len(reference):
            for px, py in _to_pixels(reference, calibration):
                vx, vy = to_view(px, py)
                dot = 1.5 * unit
                draw.ellipse((vx - dot, vy - dot, vx + dot, vy + dot), fill=colour)
        label_at = None
        if cut is not None:
            for a, b in cut:
                if a[0] < STARBOARD_MIN_Y_M or b[0] < STARBOARD_MIN_Y_M:
                    continue
                pa, pb = (to_view(*p) for p in _to_pixels((a, b), calibration))
                draw.line([pa, pb], fill=colour, width=int(3 * unit))
                if label_at is None or pa[1] < label_at[1]:
                    label_at = pa
        if label_at is not None:
            draw.text((label_at[0] + 4, max(0, label_at[1] - line_px)), section["id"], fill=colour, font=small)
    top = panel.height + 6
    draw.text((8, top), title, fill="#17344a", font=font)
    for index, row in enumerate(rows):
        if row["status"] == "scored":
            score = f"ref max {row['max_m']:.3f} m, RMS {row['rms_m']:.3f} m"
        else:
            score = row["status"].replace("_", " ")
        if row.get("ink_fit"):
            score += f"  |  ink max {row['ink_fit']['max_m']:.3f} m, RMS {row['ink_fit']['rms_m']:.3f} m"
        line = f"{row['section_id']}  x={row['x_m']:.4g} m  {row['label']}  {score}"
        draw.text((8, top + line_px * (index + 1.2)), line, fill=row["colour"], font=small)
    draw.text((8, top + line_px * (len(rows) + 1.2)),
              "Solid: built STEP cut. Dots: reference curve (built trace or authored curve). Display aid only.",
              fill="#765434", font=small)
    canvas.save(path)
    return {"crop_box_px": [int(x0), int(y0), int(x1), int(y1)], "scale": float(scale)}


def tile_sheet(panel_paths: list[Path], path: Path) -> None:
    """All panel images in one sheet (rows of up to ceil(sqrt(n)) panels), scaled to fit."""
    import math
    from PIL import Image
    panels = [Image.open(p).convert("RGB") for p in panel_paths]
    columns = math.ceil(math.sqrt(len(panels)))
    cell_width, cell_height = max(p.width for p in panels), max(p.height for p in panels)
    rows = math.ceil(len(panels) / columns)
    sheet = Image.new("RGB", (cell_width * columns, cell_height * rows), "white")
    for index, panel in enumerate(panels):
        sheet.paste(panel, ((index % columns) * cell_width, (index // columns) * cell_height))
    sheet.thumbnail((MAX_SHEET_SIDE_PX, MAX_SHEET_SIDE_PX))
    sheet.save(path)


def build_overlay(*, sections: list[dict], labels: dict, references: dict, image: np.ndarray,
                  cut, out: Path, cut_tolerance_m: float | None = None,
                  cut_budget_seconds: float = CUT_BUDGET_SECONDS) -> dict:
    """Cut, score and draw every station; write panel images and the scoreboard JSON.

    ``sections`` give id, x_m, roi_px and calibration; ``labels`` map section
    id to source label; ``references`` map section id to (kind, points_yz_m);
    ``cut(x_m)`` returns the cut segments (n x 2 x 2, metres) at a station;
    ``cut_tolerance_m`` is its chord tolerance. ``image`` is the grey source.
    """
    sections = sorted(sections, key=lambda s: s["x_m"])[:MAX_SECTIONS]
    started = time.monotonic()
    panels = group_panels(sections)[:MAX_PANELS]
    rows, cuts, refs = {}, {}, {}
    for panel_index, members in enumerate(panels):
        for slot, index in enumerate(members):
            section = sections[index]
            sid = section["id"]
            kind, reference = references.get(sid, (None, None))
            row = {"section_id": sid, "x_m": float(section["x_m"]), "label": labels.get(sid, "not_built"),
                   "reference": kind, "panel": panel_index, "colour": PALETTE[slot % len(PALETTE)]}
            if time.monotonic() - started > cut_budget_seconds:
                rows[sid], cuts[sid], refs[sid] = {**row, "status": "skipped_time_budget"}, None, reference
                continue
            try:
                segments = cut(float(section["x_m"]))
            except Exception as exc:
                # One station that cannot be cut does not stop the others.
                rows[sid] = {**row, "status": "cut_failed", "error_type": type(exc).__name__}
                cuts[sid], refs[sid] = None, reference
                continue
            rows[sid] = score_section(row, reference, segments,
                                      float(section["calibration"]["pixels_per_metre"]))
            if segments is not None and len(segments):
                rows[sid]["ink_fit"] = ink_fit(segments, section["calibration"], section["roi_px"], image)
            cuts[sid], refs[sid] = segments, reference
    artifacts = []
    for panel_index, members in enumerate(panels):
        members_sorted = [sections[i] for i in members]
        filename = f"station-overlay-{panel_index:02d}.png"
        ids = [s["id"] for s in members_sorted]
        geometry = draw_panel(image, members_sorted, [rows[i] for i in ids], [cuts[i] for i in ids],
                              [refs[i] for i in ids], out / filename,
                              f"Panel {panel_index + 1}/{len(panels)}: built STEP station cuts on the source")
        artifacts.append({"file": filename, "kind": "station_overlay", "panel": panel_index,
                          "section_ids": ids, **geometry})
    # One image of every panel, for a reader (or model) that takes one picture.
    tile_sheet([out / a["file"] for a in artifacts], out / "station-overlay-sheet.png")
    artifacts.append({"file": "station-overlay-sheet.png", "kind": "station_overlay_sheet",
                      "panel_count": len(panels)})
    scoreboard = sorted(rows.values(), key=lambda r: r["x_m"])
    scored = [r for r in scoreboard if r["status"] == "scored"]
    worst = max(scored, key=lambda r: r["max_m"], default=None)
    inked = [r for r in scoreboard if r.get("ink_fit")]
    worst_ink = max(inked, key=lambda r: r["ink_fit"]["rms_m"], default=None)
    summary = {"status": "rendered", "section_count": len(scoreboard), "scored_count": len(scored),
               "worst_section_id": worst["section_id"] if worst else None,
               "worst_max_m": worst["max_m"] if worst else None,
               "worst_ink_fit_section_id": worst_ink["section_id"] if worst_ink else None,
               "worst_ink_fit_rms_m": worst_ink["ink_fit"]["rms_m"] if worst_ink else None,
               "distance_type": "reference curve samples to the nearest built STEP cut segment, metres",
               "ink_fit_type": ("built cut points to the nearest source pixel darker than "
                                f"{INK_THRESHOLD}/255 in the section region, metres; closure lines excluded"),
               "cut_method": "plane slice of the render tessellation of the reimported STEP",
               "cut_tolerance_m": cut_tolerance_m,
               "display_only": True, "scoreboard": scoreboard}
    (out / "station-scoreboard.json").write_text(json.dumps(summary, indent=2))
    artifacts.append({"file": "station-scoreboard.json", "kind": "station_scoreboard"})
    return {**summary, "artifacts": artifacts}


# Residual colour classes of the whole-vessel view overlays (design section 5):
# green below 1 % of the half-beam, orange below 3 %, red above.
RESIDUAL_COLOURS = ((0.01, "#2ca02c"), (0.03, "#ff7f0e"), (float("inf"), "#d62728"))
TABLE_LINE_COLOUR = "#1f77b4"


def residual_colour(fraction_of_half_beam: float) -> str:
    """Overlay colour of a residual given as a fraction of the half-beam."""
    return next(colour for limit, colour in RESIDUAL_COLOURS if fraction_of_half_beam < limit)


def faded_crop(image: np.ndarray, box_px) -> tuple:
    """The image inside ``box_px`` (x0, y0, x1, y1), faded to grey and enlarged or shrunk for display.

    Returns the PIL panel, the clipped box and the display scale.
    """
    from PIL import Image
    height, width = image.shape[:2]
    x0, y0 = max(0, int(box_px[0])), max(0, int(box_px[1]))
    x1, y1 = min(width, int(box_px[2])), min(height, int(box_px[3]))
    crop = image[y0:y1, x0:x1]
    if crop.ndim == 3:
        crop = crop[..., :3].mean(axis=2)
    # Fade the drawing so coloured lines read clearly while the ink stays visible:
    # black ink becomes a mid grey, white paper stays white.
    faded = (FADED_INK_GREY + crop.astype(float) * ((255 - FADED_INK_GREY) / 255)).astype(np.uint8)
    scale = min(MAX_PANEL_ENLARGEMENT, MAX_PANEL_SIDE_PX / max(crop.shape))
    panel = Image.fromarray(faded, "L").convert("RGB")
    if scale != 1.0:
        panel = panel.resize((max(1, int(panel.width * scale)), max(1, int(panel.height * scale))))
    return panel, (x0, y0, x1, y1), float(scale)


def draw_view_overlay(image: np.ndarray, roi_px, polylines: list, markers: list, path: Path, title: str) -> dict:
    """One whole-vessel view (body plan, half-breadth plan or profile) with the table drawn over the ink.

    ``polylines`` are (label, n x 2 sheet-pixel points), drawn solid in the
    table colour; ``markers`` are ((x, y) sheet pixels, colour), the measured
    ink points coloured by residual. Display aid only.
    """
    from PIL import Image, ImageDraw, ImageFont
    from .fonts import dejavu_sans
    box = (roi_px[0] - PANEL_MARGIN_PX, roi_px[1] - PANEL_MARGIN_PX,
           roi_px[2] + PANEL_MARGIN_PX, roi_px[3] + PANEL_MARGIN_PX)
    panel, (x0, y0, _, _), scale = faded_crop(image, box)
    # Long, flat views (plan, profile) size their text by the shorter side.
    unit = max(1.0, min(panel.width, 2 * panel.height) / 500)
    line_px = int(18 * unit)
    try:
        font = dejavu_sans(int(13 * unit))
    except OSError:
        font = ImageFont.load_default()
    title_width = int(ImageDraw.Draw(panel).textlength(title, font=font)) + 16
    canvas = Image.new("RGB", (max(panel.width, title_width), panel.height + 2 * line_px + 8), "white")
    canvas.paste(panel, (0, 0))
    draw = ImageDraw.Draw(canvas)

    def to_view(px, py):
        return ((px - x0) * scale, (py - y0) * scale)

    for label, points in polylines:
        view_points = [to_view(float(px), float(py)) for px, py in points]
        if len(view_points) >= 2:
            draw.line(view_points, fill=TABLE_LINE_COLOUR, width=max(1, int(1.5 * unit)))
            draw.text((view_points[0][0] + 3, view_points[0][1] - line_px), str(label), fill=TABLE_LINE_COLOUR,
                      font=font)
    dot = 2.0 * unit
    for (px, py), colour in markers:
        vx, vy = to_view(px, py)
        draw.ellipse((vx - dot, vy - dot, vx + dot, vy + dot), fill=colour)
    draw.text((8, panel.height + 4), title, fill="#17344a", font=font)
    canvas.save(path)
    return {"crop_box_px": [int(v) for v in box], "scale": scale}
