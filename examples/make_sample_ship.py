"""Generate the app's built-in sample vessel: station sections of an analytic hull form.

The hull is a small merchant-like form defined only by the formulas below (no
third-party offsets): a full midbody with a flat, slightly rising bottom and a
round bilge; a fine, hollow entrance forward; a transom stern over a narrow
skeg. The sheet draws each of the 11 stations in its own panel as the half right
of its centreline: afterbody stations 0 to 5 in the top row, forebody stations
6 to 10 in the bottom row, on a 1 m grid with waterlines, station captions and a
title block.

Why not one overlay body plan: there the stations of a half share a panel, so
no station has a unique curve and the deterministic policy (no AI) can only
build a draft with open guesses; curves left of the centreline get no
candidates at inspection. One right-hand curve per panel lets the deterministic
policy select every station, and the run ends ready for review.

Usage: python examples/make_sample_ship.py --out app/core/sample
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

# Main dimensions (m).
LENGTH_M = 60.0
HALF_BEAM_M = 5.5
DEPTH_M = 6.0
STATION_COUNT = 11  # stations 0 (transom) to 10 (stem), equally spaced
MIDSHIP_STATION = 5
STATION_SPACING_M = LENGTH_M / (STATION_COUNT - 1)

# Sheet layout (px). One metre is PPM pixels on both axes.
PPM = 36
GRID_WIDTH_M = 6  # each panel's grid extends past the half beam ...
GRID_HEIGHT_M = 7  # ... and above the deck
PANELS_PER_ROW = 6
PANEL_PITCH_PX = 290  # distance between neighbouring panel centrelines
MARGIN_PX = 60
ROW_TOP_PX = (90, 470)  # top of the grid in the aft row and in the fore row
SHEET_WIDTH_PX = 2 * MARGIN_PX + PANELS_PER_ROW * PANEL_PITCH_PX - (PANEL_PITCH_PX - GRID_WIDTH_M * PPM)
SHEET_HEIGHT_PX = 790

# A station's panel (ROI) reaches this far across its centreline, so the tracer
# sees where the curve meets the keel, and this far past the grid elsewhere.
PANEL_OVERLAP_PX = 10
PANEL_PAD_PX = 6

INK = 15
GRID_GREY = 205
TEXT_GREY = 70
LINE_WIDTH_PX = 3


def smoothstep(edge0: float, edge1: float, value: float) -> float:
    """0 below edge0, 1 above edge1, a smooth cubic in between."""
    t = min(1.0, max(0.0, (value - edge0) / (edge1 - edge0)))
    return t * t * (3.0 - 2.0 * t)


def station_form(xi: float) -> dict[str, float]:
    """Section parameters at the length fraction xi (0 = transom, 1 = stem).

    ``aft`` and ``fore`` are 0 at midship and grow to 1 at the ends. Every
    parameter moves the same way (thinner) as they grow, so the stations of
    each half nest: a station farther from midship is narrower at every height.
    """
    aft = 1.0 - smoothstep(0.0, 0.5, xi)
    fore = smoothstep(0.5, 1.0, xi)
    return {
        # Half-breadth at the deck, as a fraction of the half beam (transom 0.72, stem 0.16).
        "deck": 1.0 - 0.28 * aft ** 1.3 - 0.84 * fore ** 1.5,
        # Bilge tightness: large is a box with a small bilge radius, near 1 a V.
        "tightness": 10.0 - 7.0 * aft ** 0.7 - 8.3 * fore ** 0.7,
        # Bottom fullness: below 1 a flat, slightly rising bottom; above 1 a hollow
        # (a skeg aft, a fine entrance forward).
        "hollow": 0.25 + 2.0 * aft ** 1.5 + 1.1 * fore ** 1.2,
    }


def section_points(xi: float, samples: int = 400) -> np.ndarray:
    """Half section (y, z) in metres from the keel to the deck edge.

    y(z) = deck * (1 - (1 - z / D) ** tightness) ** hollow. The side is vertical
    at the deck (tightness > 1) and the curve meets the keel at the centreline.
    """
    form = station_form(xi)
    # Heights spaced closer near the keel, where the curve turns fastest.
    share = np.linspace(0.0, 1.0, samples) ** 2
    breadth = form["deck"] * HALF_BEAM_M * (1.0 - (1.0 - share) ** form["tightness"]) ** form["hollow"]
    return np.column_stack([breadth, share * DEPTH_M])


def half_breadth_at(points: np.ndarray, heights: np.ndarray) -> np.ndarray:
    """Half-breadth of a section at each height (sections are single-valued in height)."""
    return np.interp(heights, points[:, 1], points[:, 0])


def check_fair(minimum_gap_m: float = 0.03) -> None:
    """Fail unless the stations of each half nest (a fair form: no station bulges past a fuller one)."""
    heights = np.linspace(0.3, DEPTH_M, 200)
    for stations in (range(0, MIDSHIP_STATION + 1), range(MIDSHIP_STATION + 1, STATION_COUNT)):
        widths = {s: half_breadth_at(section_points(s / (STATION_COUNT - 1)), heights) for s in stations}
        by_distance = sorted(stations, key=lambda s: abs(s - MIDSHIP_STATION))
        for inner, outer in zip(by_distance[1:], by_distance):
            gap = float(np.min(widths[outer] - widths[inner]))
            if gap < minimum_gap_m:
                raise ValueError(f"station {inner} is not inside station {outer} (gap {gap:.3f} m)")


class Panel:
    """Where one station is drawn: its grid, with the centreline at the grid's left edge."""

    def __init__(self, station: int):
        self.station = station
        afterbody = station <= MIDSHIP_STATION
        slot = station if afterbody else station - (MIDSHIP_STATION + 1)
        self.centreline = MARGIN_PX + slot * PANEL_PITCH_PX
        self.top = ROW_TOP_PX[0 if afterbody else 1]
        self.baseline = self.top + GRID_HEIGHT_M * PPM

    def pixel(self, y_m: float, z_m: float) -> tuple[float, float]:
        return self.centreline + y_m * PPM, self.baseline - z_m * PPM

    def roi(self) -> list[int]:
        """The traced panel: the grid, a little past the centreline and the other edges."""
        return [self.centreline - PANEL_OVERLAP_PX, self.top - PANEL_PAD_PX,
                self.centreline + GRID_WIDTH_M * PPM + PANEL_PAD_PX, self.baseline + PANEL_PAD_PX]


def draw_panel(draw: ImageDraw.ImageDraw, panel: Panel, small: ImageFont.ImageFont,
               label: ImageFont.ImageFont) -> None:
    """Grid, scale and caption of one panel (outside its ROI) and the station curve."""
    for metre in range(GRID_WIDTH_M + 1):
        column, _ = panel.pixel(metre, 0)
        draw.line((column, panel.top, column, panel.baseline), fill=GRID_GREY, width=1)
        if metre % 2 == 0:
            draw.text((column, panel.baseline + 10), str(metre), fill=TEXT_GREY, font=small, anchor="mt")
    for metre in range(GRID_HEIGHT_M + 1):
        _, row = panel.pixel(0, metre)
        far, _ = panel.pixel(GRID_WIDTH_M, 0)
        draw.line((panel.centreline, row, far, row), fill=GRID_GREY, width=1)
        if metre % 2 == 0:
            text = "BL" if metre == 0 else f"WL{metre}"
            draw.text((far + 10, row), text, fill=TEXT_GREY, font=small, anchor="lm")
    curve = [panel.pixel(y, z) for y, z in section_points(panel.station / (STATION_COUNT - 1))]
    draw.line(curve, fill=INK, width=LINE_WIDTH_PX, joint="curve")
    middle, _ = panel.pixel(GRID_WIDTH_M / 2, 0)
    caption = f"Station {panel.station}   x = {panel.station * STATION_SPACING_M:.1f} m"
    draw.text((middle, panel.top - 14), caption, fill=INK, font=label, anchor="mb")


def draw_title_block(draw: ImageDraw.ImageDraw, title: ImageFont.ImageFont, small: ImageFont.ImageFont) -> None:
    """Title block in the free sixth slot of the fore row."""
    left = MARGIN_PX + (PANELS_PER_ROW - 1) * PANEL_PITCH_PX - 20
    right = SHEET_WIDTH_PX - 20
    top = ROW_TOP_PX[1] + 40
    bottom = top + 150
    draw.rectangle((left, top, right, bottom), outline=TEXT_GREY, width=2)
    draw.line((left, top + 44, right, top + 44), fill=TEXT_GREY, width=1)
    draw.text((left + 12, top + 22), "Sample hull (generated)", fill=INK, font=title, anchor="lm")
    lines = ("Station sections, one half each",
             f"LOA {LENGTH_M:.1f} m   B {2 * HALF_BEAM_M:.1f} m   D {DEPTH_M:.1f} m",
             f"Stations 0-10, {STATION_SPACING_M:.1f} m apart",
             "Grid 1 m. Analytic form, no source data.")
    for index, text in enumerate(lines):
        draw.text((left + 12, top + 62 + 22 * index), text, fill=TEXT_GREY, font=small, anchor="lm")


def section_spec(panel: Panel) -> dict:
    return {
        "id": f"st{panel.station:02d}",
        "x_m": round(panel.station * STATION_SPACING_M, 6),
        "roi_px": panel.roi(),
        "calibration": {"centerline_px": panel.centreline, "baseline_px": panel.baseline,
                        "pixels_per_metre": PPM},
        "z_min_m": 0.0,
        "z_max_m": DEPTH_M,
        "evidence": "Generated drawing (examples/make_sample_ship.py). Station position from the station "
                    "spacing; scale, centreline and baseline from the panel's 1 m grid. One station per "
                    "panel, drawn as the half right of its centreline.",
    }


def make_sample(out: Path) -> Path:
    check_fair()
    out.mkdir(parents=True, exist_ok=True)
    image = Image.new("L", (SHEET_WIDTH_PX, SHEET_HEIGHT_PX), 255)
    draw = ImageDraw.Draw(image)
    small = ImageFont.load_default(size=13)
    label = ImageFont.load_default(size=15)
    title = ImageFont.load_default(size=21)
    panels = [Panel(station) for station in range(STATION_COUNT)]
    for panel in panels:
        draw_panel(draw, panel, small, label)
    for row_top, text in zip(ROW_TOP_PX, ("AFT BODY (stations 0-5, transom to midship)",
                                          "FORE BODY (stations 6-10, to the stem)")):
        draw.text((MARGIN_PX - 20, row_top - 52), text, fill=TEXT_GREY, font=label, anchor="lb")
    draw_title_block(draw, title, small)
    image.save(out / "drawing.png", optimize=True)

    spec = {"schema_version": "1.0", "vessel_id": "sample-hull", "units": "m",
            "symmetry": "port_starboard",
            "symmetry_evidence": "Each station is drawn as one half; port-starboard symmetry is assumed.",
            "end_closure": "flat_at_terminal_stations",
            "source": {"file": "drawing.png",
                       "description": "Sample hull (generated): station sections of an analytic hull form "
                                      "drawn by examples/make_sample_ship.py. No third-party data."},
            "sections": [section_spec(panel) for panel in panels]}
    (out / "spec.json").write_text(json.dumps(spec, indent=2) + "\n")
    return out / "spec.json"


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, required=True)
    print(make_sample(parser.parse_args().out))
