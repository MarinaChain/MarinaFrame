"""Generate a synthetic offset-table image and its offset_table_vision spec.

The spec holds only human calibration: station positions, waterline heights
and cell regions. The printed tokens are written to a separate
``truth/printed_tokens.json`` for scoring a reading; that file is never an
inference input. No licensed drawing is used.
"""
import argparse
import json
from pathlib import Path

from PIL import Image, ImageDraw

from vessel_reconstruction.fonts import dejavu_sans

STATIONS_X_M = [0.0, 6.0, 12.0, 18.0]
WATERLINES_Z_M = [0.5, 1.0, 1.5, 2.0, 2.5]
CELL_W, CELL_H = 130, 44
LEFT, TOP = 110, 50
# Half-breadth in eighths of an inch per station (row: waterline). Hand-chosen
# plausible values: narrow ends, full middle, flare towards the top.
EIGHTHS = [
    [180, 236, 290, 333, 371],
    [470, 539, 581, 606, 622],
    [489, 552, 590, 612, 625],
    [262, 330, 392, 441, 482],
]


def token(eighths: int) -> str:
    feet, rest = divmod(eighths, 96)
    inches, eighth = divmod(rest, 8)
    return f"{feet}-{inches}-{eighth}"


def make_example(out: Path) -> Path:
    out = Path(out)
    out.mkdir(parents=True, exist_ok=False)
    width = LEFT + CELL_W * len(STATIONS_X_M) + 20
    height = TOP + CELL_H * len(WATERLINES_Z_M) + 20
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    font, small = dejavu_sans(22), dejavu_sans(16)
    draw.text((10, 12), "WL (m)", font=small, fill="black")
    for column, x in enumerate(STATIONS_X_M):
        draw.text((LEFT + column * CELL_W + 30, 12), f"ST {column}", font=small, fill="black")
    for row, z in enumerate(WATERLINES_Z_M):
        draw.text((20, TOP + row * CELL_H + 12), f"{z:.1f}", font=small, fill="black")
    for column in range(len(STATIONS_X_M) + 1):
        x = LEFT + column * CELL_W
        draw.line((x, TOP, x, TOP + CELL_H * len(WATERLINES_Z_M)), fill="black", width=2)
    for row in range(len(WATERLINES_Z_M) + 1):
        y = TOP + row * CELL_H
        draw.line((LEFT, y, LEFT + CELL_W * len(STATIONS_X_M), y), fill="black", width=2)
    sections, truth = [], {}
    for column, x_m in enumerate(STATIONS_X_M):
        left = LEFT + column * CELL_W
        cells = []
        for row, z_m in enumerate(WATERLINES_Z_M):
            top = TOP + row * CELL_H
            text = token(EIGHTHS[column][row])
            draw.text((left + 22, top + 9), text, font=font, fill="black")
            # Cell regions stay 4 px inside the grid lines.
            cells.append({"z_m": z_m, "roi_px": [left + 4, top + 4, left + CELL_W - 4, top + CELL_H - 4]})
            truth[f"c{column:03d}-{row:03d}"] = text
        sections.append({"id": f"st-{column}", "x_m": x_m, "roi_px": [left, TOP, left + CELL_W, TOP + CELL_H * len(WATERLINES_Z_M)],
                         "evidence": "Declared station column and waterline rows of a generated synthetic offset table.",
                         "cells": cells})
    image.save(out / "table.png")
    spec = {"schema_version": "1.0", "vessel_id": "synthetic-offset-table", "input_mode": "offset_table_vision",
            "units": "m", "table_value_units": "feet_inches_eighths", "table_surface": "Synthetic; not a real vessel surface.",
            "symmetry": "port_starboard", "symmetry_evidence": "Explicit generated fixture assumption.",
            "end_closure": "flat_at_terminal_stations", "source": {"file": "table.png"}, "sections": sections}
    (out / "spec.json").write_text(json.dumps(spec, indent=2) + "\n")
    (out / "truth").mkdir()
    (out / "truth" / "printed_tokens.json").write_text(json.dumps(truth, indent=2, sort_keys=True) + "\n")
    return out / "spec.json"


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    print(make_example(parser.parse_args().out))
