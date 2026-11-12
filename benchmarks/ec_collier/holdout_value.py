"""Hard-chine holdout: E. C. COLLIER (skipjack, 1910), HAER MD-77 sheet 2, body plan.

Protocol: docs/BODY_PLAN_CHINE.md, "Holdout protocol" and "Holdout protocol amendment".
Sheet: work/holdout/ec-collier/md1203-sheet-00002a-lines.tif (14460 x 9632, 1-bit, 400 dpi),
sha256 80e689130705ffcbd46716320865502a618a69cdd94d96191c3cafc3b22e0637.

Every constant below was set from the drawing's own scale bars, lines and labels before any
reader ran on this sheet. No truth value was used. Image coordinates are full-sheet pixels
(row, column); the body plan crop bodyplan_crop.png starts at column 1550, row 5850.

The body plan has no drawn waterlines or buttocks (sheet note). The reader needs horizontal
measuring rows, so this file defines them on a fixed grid of heights above the base line from
the scale alone (MEASURING_STEP_FT); they are not placed at any printed point height.
"""
from __future__ import annotations

from benchmarks.frozen_readers.v1 import body_plan_reader as bpr

# BODY_PLAN_CHINE.md V-bottom reader explicitly makes this a development case.
STATUS = 'development'
PROTOCOL = 'docs/BODY_PLAN_CHINE.md (Holdout protocol amendment)'
SHEET_SHA256 = '80e689130705ffcbd46716320865502a618a69cdd94d96191c3cafc3b22e0637'

# ---------------------------------------------------------------- scale
# Feet scale bar (printed "SCALE: 3/8" = 1'0""): its "0" tick is at column 1995.0 and its "70"
# tick at column 12512.5 (centres of the vertical ticks, rows 8120 to 8310), so
# (12512.5 - 1995.0) / 70 = 150.25 px/ft. The nominal value at 400 dpi is 0.375 in x 400 = 150.0.
# Check against the drawing: the vertical dimension "8'-10 1/2" EXTREME HALF-BREADTH" in the
# half-breadth plan runs from row 3757 (sheer line) to row 5087.5 (centreline), 1330.5 px /
# 8.875 ft = 149.9 px/ft (0.2 % from the bar). Two references disagree and are NOT used:
# the metres bar (labelled 1:24, which does not match 3/8" = 1'; ticks give 500.2 px/m =
# 152.5 px/ft) and the "45'-10" between perpendiculars" dimension (7033 px = 153.4 px/ft).
# The feet bar is the printed scale, agrees with the drawn vertical dimension, and is used for
# both directions.
PIXELS_PER_FT = 150.25
PIXELS_PER_M = PIXELS_PER_FT / 0.3048

# ---------------------------------------------------------------- body plan axes
# Centreline: a straight fit through the thin vertical centreline ink (rows 6180 to 7920) gives
# column = 3224.98 - 0.00226 x row; at row 6950, the middle of the hull's height, it is 3209.3.
# Over the hull rows (6450 to 7450) it moves by +1.2 to -1.1 px from this value.
CENTRE_COLUMN = 3209.3
# Base line: the drawn "BASE LINE" under the body plan, fitted over columns 1800 to 4700:
# row = 7652.46 + 0.001144 x column, which is row 7656.1 at the centre column. Heights above base
# are measured from this sloped line (the sheet is turned by about 0.07 degrees).
BASE_ROW = 7656.1
BASE_ROW_PER_COLUMN = 0.001144

# ---------------------------------------------------------------- sides
# Reading 1 (labels in the body plan crop): the left half carries the "TRANSOM" and station
# labels 0 and 1 inside, and 2, 3, 4 with leaders to the three outer curves (4 outermost); the
# right half carries labels 10, 9, 8, 7, 6, 5 from the centreline outwards (5 outermost).
# Reading 2 (profile against the body plan): in the sheer plan station 0 is at the transom
# (stern, left) and station 10 is at the stem (bow, right); the half-breadth plan's extreme
# half-breadth is at station 4 to 5. So the transom half (left) is the aftbody with its widest
# station 4 outermost, and the right half is the forebody with station 5 outermost and the
# narrow bow station 10 innermost. Both readings agree.
AFT_STATIONS_OUTER_FIRST = (4, 3, 2, 1, 0)
FORE_STATIONS_OUTER_FIRST = (5, 6, 7, 8, 9, 10)
STATIONS = tuple(range(0, 11))
# No buttocks are drawn, so there are no grid columns on either half.
AFT_GRID_COLUMNS: tuple[float, ...] = ()
FORE_GRID_COLUMNS: tuple[float, ...] = ()

# ---------------------------------------------------------------- reach
# Outermost hull ink: aft 1341 px (station 4 and log rail, rows 6750 to 6800), fore 1318 px
# (station 5 top). The aft station labels "2", "3", "4" start at 1381 px. 1370 px clears the
# hull by about 30 px and stops before those labels. (On the fore half the label "5" lies at
# 1286 to 1325 px beside station 5 and cannot be excluded by a reach limit.)
MAX_OFFSET_PX = 1370

# ---------------------------------------------------------------- measuring rows
# Rows every 6 inches above the base line, from 0.5 ft to 8.0 ft. The top row is above the
# drawn top of the log rail at the centreline (row about 6446, 8.05 ft), so above the sheer at
# every station; the lowest row is below the keel bottom (row about 7440, 1.4 ft).
# Why 6 inches: the reader's spacing-scaled constants (short-stroke test, chine-point match
# radius, lower-piece overshoot, the "line lies on a waterline" rejection band) were developed on
# sheets with 300 to 600 px between waterlines. A 3-inch grid here is 37.6 px; a band of about
# 13 px either side of each row would then cover most of any traced chine line, and v2 would
# reject it as a waterline. A 1-ft grid (150 px) is safer for those constants but gives few rows
# for interpolation. 6 inches (75.1 px) is the compromise; the choice is made from the scale and
# the reader's constants only.
MEASURING_STEP_FT = 0.5
MEASURING_TOP_FT = 8.0


def base_row_at(column: float) -> float:
    """Image row of the drawn base line at `column`."""
    return BASE_ROW + BASE_ROW_PER_COLUMN * (column - CENTRE_COLUMN)


def height_ft(row: float, column: float) -> float:
    """Height above base (ft) of an image point."""
    return (base_row_at(column) - row) / PIXELS_PER_FT


def _label(height: float) -> str:
    """Feet-inches-eighths label of a grid height, e.g. 2.5 ft -> '2-6-0'."""
    feet = int(height)
    inches = round((height - feet) * 12)
    return f'{feet}-{inches}-0'


def _measuring_rows() -> dict:
    count = round(MEASURING_TOP_FT / MEASURING_STEP_FT)
    heights = [MEASURING_STEP_FT * k for k in range(1, count + 1)]
    return {_label(h): int(round(BASE_ROW - h * PIXELS_PER_FT)) for h in heights}


# Label (feet-inches-eighths above base) -> nominal image row at the centre column.
MEASURING_ROWS = _measuring_rows()
MEASURING_HEIGHTS_FT = {label: (BASE_ROW - row) / PIXELS_PER_FT for label, row in MEASURING_ROWS.items()}
WATERLINES = tuple(MEASURING_ROWS)


def sheet_layout() -> bpr.SheetLayout:
    """Host calibration: aftbody (stations 0 to 4) left of the centreline, forebody (5 to 10) right."""
    sides = (bpr.SideLayout('aft', -1, AFT_STATIONS_OUTER_FIRST, AFT_GRID_COLUMNS),
             bpr.SideLayout('fore', 1, FORE_STATIONS_OUTER_FIRST, FORE_GRID_COLUMNS))
    return bpr.SheetLayout(CENTRE_COLUMN, PIXELS_PER_M, dict(MEASURING_ROWS), MAX_OFFSET_PX, sides)
