"""Draw a WHITE GULL or COLLEEN body-plan calibration on its sheet, for a person to check by eye.

Draws the centre column, the base line, every measuring row with its label and height, the
buttock grid columns, the reach limits (MAX_OFFSET_PX) and the side / station assignment.
Reads the sheet only (body-plan region); no reader, no truth.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from vessel_reconstruction import body_plan_crossings as bpc

BOATS = {'white-gull': 'benchmarks.white_gull.holdout_value', 'colleen': 'benchmarks.colleen.holdout_value'}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--boat', choices=sorted(BOATS), required=True)
    parser.add_argument('--sheet', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    cal = importlib.import_module(BOATS[args.boat])
    if hashlib.sha256(args.sheet.read_bytes()).hexdigest() != cal.SHEET_SHA256:
        raise SystemExit('sheet sha256 is not the protocol sheet; stop')
    top, bottom, left, right = cal.OVERLAY_REGION
    ink = bpc.load_ink(args.sheet)[top:bottom, left:right]
    image = Image.fromarray(np.where(ink, 0, 255).astype(np.uint8)).convert('RGB')
    draw = ImageDraw.Draw(image)

    def at(row: float, column: float) -> tuple[float, float]:
        return column - left, row - top

    centre = cal.CENTRE_COLUMN
    draw.line([at(top, centre), at(bottom, centre)], fill=(0, 160, 0), width=2)
    draw.line([at(cal.base_row_at(left), left), at(cal.base_row_at(right), right)], fill=(0, 0, 255), width=2)
    for sign in (-1, 1):
        reach = centre + sign * cal.MAX_OFFSET_PX
        draw.line([at(top, reach), at(bottom, reach)], fill=(255, 140, 0), width=2)
    for column in cal.FORE_GRID_COLUMNS + cal.AFT_GRID_COLUMNS:
        draw.line([at(top, column), at(bottom, column)], fill=(0, 200, 200), width=1)
    for label, row in cal.WATERLINE_ROWS.items():
        draw.line([at(row, centre - cal.MAX_OFFSET_PX), at(row, centre + cal.MAX_OFFSET_PX)], fill=(220, 0, 0), width=1)
        draw.text(at(row - 14, centre + cal.MAX_OFFSET_PX + 8),
                  f'{label} ({cal.height_ft(row, centre):.2f} ft)', fill=(220, 0, 0))
    layout = cal.sheet_layout()
    for side in layout.sides:
        x = centre + side.sign * 700 - 250
        draw.text(at(top + 20, x), f'{side.name.upper()}: outer first {side.stations_outer_first}', fill=(0, 0, 255))
    draw.text(at(cal.BASE_ROW + 10, centre + 20), f'base row {cal.BASE_ROW}, {cal.PIXELS_PER_FT} px/ft',
              fill=(0, 0, 255))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    image.save(args.out)
    print(args.out)


if __name__ == '__main__':
    main()
