"""Raster fixture with multi-piece stations: a bulb, a hull above it and a skeg.

Every station panel is drawn at 60 px/m with its baseline at row 210 (z = 0)
and its centreline at the panel's left edge plus 20 px. Each station has
three drawn curves, declared as pieces:

- bulb: a centreline piece from z = 0 to 1 m;
- hull: a centreline piece from z = 1.5 to 3 m, apart from the bulb;
- skeg: an offset piece from z = 0 to 1 m between two vertical lines.

The pieces declare only where to read (corridors and height intervals); the
half-breadths are measured from the drawn pixels.
"""
from __future__ import annotations

import json
from pathlib import Path

from PIL import Image, ImageDraw

PIXELS_PER_METRE = 60
BASELINE_PX = 210
PANEL_WIDTH_PX = 200
CORRIDOR_HALF_WIDTH_PX = 6


def _row(z_m: float) -> float:
    return BASELINE_PX - z_m * PIXELS_PER_METRE


def _curve(centre: float, y0_m: float, y1_m: float, z0_m: float, z1_m: float):
    """End points (px) of a straight drawn curve from (y0, z0) to (y1, z1)."""
    return [(centre + y0_m * PIXELS_PER_METRE, _row(z0_m)), (centre + y1_m * PIXELS_PER_METRE, _row(z1_m))]


def _corridor(points):
    return {"anchors_px": [[float(x), float(y)] for x, y in points], "half_width_px": CORRIDOR_HALF_WIDTH_PX}


def station_curves(index: int, centre: float, *, skeg: bool) -> dict:
    """Drawn curves of station ``index``; the shapes change slowly along the ship."""
    grow = 0.05 * index
    curves = {"bulb": _curve(centre, 0.5 + grow, 0.8 + grow, 0.0, 1.0),
              "hull": _curve(centre, 1.0 + grow, 1.3 + grow, 1.5, 3.0)}
    if skeg:
        curves["skeg_inner"] = _curve(centre, 1.2 + grow, 1.2 + grow, 0.0, 1.0)
        curves["skeg_outer"] = _curve(centre, 1.5 + grow, 1.5 + grow, 0.0, 1.0)
    return curves


def write(directory: Path, *, stations: int = 3, skeg: bool = True,
          blank: tuple[str, ...] = ()) -> tuple[Path, dict]:
    """Write drawing.png and spec.json; return the spec path and the spec.

    Stations named in ``blank`` keep their declared pieces but have no drawn
    curves, so they cannot be read (a draft spans them).
    """
    directory.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGB", (PANEL_WIDTH_PX * stations, 230), "white")
    draw = ImageDraw.Draw(image)
    sections = []
    for index in range(stations):
        left = index * PANEL_WIDTH_PX
        centre = left + 20
        curves = station_curves(index, centre, skeg=skeg)
        if f"st{index}" not in blank:
            for points in curves.values():
                draw.line(points, fill=(15, 15, 15), width=3)
        pieces = [{"z_min_m": 0.0, "z_max_m": 1.0, "contour_selection": _corridor(curves["bulb"])},
                  {"z_min_m": 1.5, "z_max_m": 3.0, "contour_selection": _corridor(curves["hull"])}]
        if skeg:
            pieces.append({"z_min_m": 0.0, "z_max_m": 1.0, "contour_selection": _corridor(curves["skeg_outer"]),
                           "inner_selection": _corridor(curves["skeg_inner"])})
        sections.append({"id": f"st{index}", "x_m": 2.0 * index, "roi_px": [left + 10, 20, left + 195, 220],
                         "calibration": {"centerline_px": centre, "baseline_px": BASELINE_PX,
                                         "pixels_per_metre": PIXELS_PER_METRE},
                         "z_min_m": 0.0, "z_max_m": 3.0, "pieces": pieces,
                         "evidence": "Independently specified multi-piece pixel fixture."})
    image.save(directory / "drawing.png")
    spec = {"schema_version": "1.0", "vessel_id": "region-fixture", "units": "m",
            "symmetry": "port_starboard", "symmetry_evidence": "Explicit symmetric test fixture assumption.",
            "end_closure": "flat_at_terminal_stations", "source": {"file": "drawing.png"}, "sections": sections,
            "components": []}
    path = directory / "spec.json"
    path.write_text(json.dumps(spec))
    return path, spec
