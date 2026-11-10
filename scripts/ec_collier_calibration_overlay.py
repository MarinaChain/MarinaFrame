"""Draw the E. C. COLLIER body-plan calibration on the sheet, for a person to check by eye.

Draws the centre column, the base line, every measuring row with its label, the reach limits
(MAX_OFFSET_PX) and the side/station assignment. Reads the sheet only; no reader, no truth.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from benchmarks.ec_collier import holdout_value as cal
from vessel_reconstruction import body_plan_crossings as bpc

# Body-plan region of the full sheet (rows, columns) drawn in the overlay.
TOP, BOTTOM, LEFT, RIGHT = 6250, 7800, 1650, 4750


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sheet', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    ink = bpc.load_ink(args.sheet)[TOP:BOTTOM, LEFT:RIGHT]
    image = Image.fromarray(np.where(ink, 0, 255).astype(np.uint8)).convert('RGB')
    draw = ImageDraw.Draw(image)

    def at(row: float, column: float) -> tuple[float, float]:
        return column - LEFT, row - TOP

    centre = cal.CENTRE_COLUMN
    draw.line([at(TOP, centre), at(BOTTOM, centre)], fill=(0, 160, 0), width=2)
    draw.line([at(cal.base_row_at(LEFT), LEFT), at(cal.base_row_at(RIGHT), RIGHT)], fill=(0, 0, 255), width=2)
    for sign in (-1, 1):
        reach = centre + sign * cal.MAX_OFFSET_PX
        draw.line([at(TOP, reach), at(BOTTOM, reach)], fill=(255, 140, 0), width=2)
    for label, row in cal.MEASURING_ROWS.items():
        left, right = centre - cal.MAX_OFFSET_PX, centre + cal.MAX_OFFSET_PX
        draw.line([at(row, left), at(row, right)], fill=(220, 0, 0), width=1)
        draw.text(at(row - 14, right + 8), f'{label} ({cal.MEASURING_HEIGHTS_FT[label]:.2f} ft)', fill=(220, 0, 0))
    draw.text(at(TOP + 20, centre - 900), f'AFT: outer first {cal.AFT_STATIONS_OUTER_FIRST}', fill=(0, 0, 255))
    draw.text(at(TOP + 20, centre + 300), f'FORE: outer first {cal.FORE_STATIONS_OUTER_FIRST}', fill=(0, 0, 255))
    draw.text(at(cal.BASE_ROW + 10, centre + 20), f'base row {cal.BASE_ROW}, {cal.PIXELS_PER_FT} px/ft',
              fill=(0, 0, 255))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    image.save(args.out)
    print(args.out)


if __name__ == '__main__':
    main()
