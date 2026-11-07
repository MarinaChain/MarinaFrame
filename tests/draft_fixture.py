"""Synthetic drawings for the draft (best-effort) path. No reference geometry.

Each section is the pixel fixture of tests/test_agent_tools.py: a light grid and
one dark hull stroke. Optional changes make the drawing ambiguous:
  ambiguous=("s0",)   a second, faint complete vertical line in the section, so
                      the inspection keeps two lines and makes no unique choice
  blank=("s2",)       nothing drawn in the section, so no line can be read
"""
from __future__ import annotations

import json
from pathlib import Path

from PIL import Image, ImageDraw


def draft_drawing(directory: Path, *, count: int = 3, ambiguous=("s0",), blank=()):
    directory.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGB", (200 * count, 230), "white")
    draw = ImageDraw.Draw(image)
    sections = []
    for index in range(count):
        sid = f"s{index}"
        left, centre, bottom = index * 200, index * 200 + 20, 210
        if sid not in blank:
            for x in range(centre, centre + 151, 30):
                draw.line((x, 30, x, bottom), fill=(210,) * 3, width=1)
            for y in range(30, bottom + 1, 30):
                draw.line((centre, y, centre + 170, y), fill=(210,) * 3, width=1)
            draw.line([(centre + 30 + .25 * (bottom - row), row) for row in range(30, bottom + 1)],
                      fill=(15,) * 3, width=3)
            if sid in ambiguous:
                draw.line((centre + 137, 30, centre + 137, bottom), fill=(207,) * 3, width=3)
        sections.append({"id": sid, "x_m": index * 2., "roi_px": [left + 10, 20, left + 195, 220],
                         "calibration": {"centerline_px": centre, "baseline_px": bottom, "pixels_per_metre": 60},
                         "z_min_m": 0., "z_max_m": 3., "evidence": "Independently specified pixel fixture."})
    image.save(directory / "drawing.png")
    spec = {"schema_version": "1.0", "vessel_id": "draft-fixture", "units": "m",
            "symmetry": "port_starboard", "symmetry_evidence": "Explicit symmetric test fixture assumption.",
            "end_closure": "flat_at_terminal_stations", "source": {"file": "drawing.png"}, "sections": sections}
    path = directory / "spec.json"
    path.write_text(json.dumps(spec))
    return path, spec
