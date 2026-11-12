"""Hard-chine holdout: M/V COLLEEN (Chesapeake deadrise workboat, built 1962), HAER MD sheet 1 "Lines", body plan.

Protocol: docs/BODY_PLAN_CHINE.md, "Holdout protocol: WHITE GULL and COLLEEN".
Sheet: work/holdout/colleen/md1887-sheet-00001a-lines.tif (14400 x 9600, 1-bit, 400 dpi),
sha256 57333fa2faf334e731cd4e81941e2e4dde04232e45026a8d3d23c9f882ef556f.

Every constant below was set from the drawing's own scale bar, lines and labels before any
reader ran on this sheet. No truth value was used, and the table of offsets was not read.
Image coordinates are full-sheet pixels (row, column); the drawing is a CAD plot (zero slopes).

The body plan has no drawn waterlines or buttocks: only the base line, which lies ABOVE the
keel (the keel bottom is about 2 ft below it). Heights below the base line are negative. The
measuring rows are therefore a fixed grid of heights from the scale alone, as for E. C. COLLIER.
"""
from __future__ import annotations

from benchmarks.frozen_readers.v1 import body_plan_reader as bpr

# BODY_PLAN_CHINE.md V-bottom v1.1 uses this spent holdout for development.
STATUS = 'development'
PROTOCOL = 'docs/BODY_PLAN_CHINE.md (Holdout protocol: WHITE GULL and COLLEEN)'
# Frozen truth file work/holdout/<boat>/truth.json (main checkout, read-only): sha256 given by the PM
# before the run. The scorer stops if the file differs.
TRUTH_SHA256: str | None = 'bbc124ef17a273060a12b3378f0b934a391aed1399260b426a2a0d94e325a4cc'
SHEET_SHA256 = '57333fa2faf334e731cd4e81941e2e4dde04232e45026a8d3d23c9f882ef556f'

# ---------------------------------------------------------------- scale
# Feet scale bar (printed "SCALE: 3/4"=1'-0"", rows 8720 to 8840): "0" tick at column 6225.0,
# "5" tick at 7725.0, so 1500 / 5 = 300.0 px/ft (nominal 0.75 in x 400 dpi).
# Drawn dimensions: the body-plan beam "9'-5 3/8"" between its extension lines at columns 1425.5
# and 4258.5 = 2833 px / 9.448 ft = 299.9 px/ft; in the half-breadth plan the station spacing
# "4'-0"" is 1200 px (station lines 2438, 3638, ... 12038) = 300.0 px/ft, and "2'-6 3/4"" from
# the transom extension line (1666) to station 9 (2436) is 770 px = 300.5 px/ft.
PIXELS_PER_FT = 300.0
PIXELS_PER_M = PIXELS_PER_FT / 0.3048

# ---------------------------------------------------------------- body plan axes
# Centreline: the dash-dot centreline ink is columns 2825 to 2827 above the sheer (rows 1700 to
# 1950) and below the keel (rows 3900 to 4200).
CENTRE_COLUMN = 2826.0
# Base line: the drawn line labelled "Baseline", row 3133.0, zero slope over columns 1400 to 4400.
# It crosses the sections above the chine; the keel bottom is near row 3750 (-2.06 ft).
BASE_ROW = 3133.0
BASE_ROW_PER_COLUMN = 0.0

# ---------------------------------------------------------------- measuring rows
# Every 6 inches from 2.0 ft below the base line to 3.5 ft above it (12 rows, 150 px apart).
# Range: the keel bottom is at about -2.06 ft; the highest station sheer (station 1) is at about
# 3.4 ft (row 2110), and the stem head at 4.07 ft is not a station, so 3.5 ft is the top row.
# Why 6 inches: the readers' spacing-scaled constants were developed on 300 to 600 px between
# waterlines and E. C. COLLIER used 6 inches (75 px there). A 1-ft grid (300 px) would leave
# only five rows inside the hull for interpolation; 6 inches here is 150 px, twice COLLIER's
# spacing, so v2's waterline-rejection band and the chine-point radius are less tight than they
# were on COLLIER. The choice is made from the scale and the readers' constants only.
MEASURING_STEP_FT = 0.5
MEASURING_BOTTOM_FT = -2.0
MEASURING_TOP_FT = 3.5


def _label(height: float) -> str:
    """Signed feet-inches-eighths label of a grid height: 1.5 -> '1-6-0', -0.5 -> '-0-6-0'."""
    sign = '-' if height < 0 else ''
    magnitude = abs(height)
    feet = int(magnitude)
    inches = round((magnitude - feet) * 12)
    return f'{sign}{feet}-{inches}-0'


def _measuring_rows() -> dict:
    count = round((MEASURING_TOP_FT - MEASURING_BOTTOM_FT) / MEASURING_STEP_FT) + 1
    heights = [MEASURING_BOTTOM_FT + MEASURING_STEP_FT * k for k in range(count)]
    return {_label(h): int(round(BASE_ROW - h * PIXELS_PER_FT)) for h in heights}


# Label (signed feet-inches-eighths above base) -> image row, low to high.
WATERLINE_ROWS = _measuring_rows()
WATERLINE_HEIGHTS_FT = {label: (BASE_ROW - row) / PIXELS_PER_FT for label, row in WATERLINE_ROWS.items()}
WATERLINES = tuple(WATERLINE_ROWS)

# ---------------------------------------------------------------- sides
# Reading 1 (labels in the body plan): the right half carries "1" (innermost, highest sheer) to
# "6" (outermost) along its sheer; the left half carries "7", "8", "9" from the outside inward.
# Reading 2 (profile and half-breadth plan): the profile is labelled "Sta.9" (near the transom,
# left) to "Sta.1" (at the stem, right). Half-breadth plan values (px from its centreline,
# station line + 8 px) against the body plan near the chine (row 3230): station 7 chine 1311 vs
# the outermost left curve 1311.5; station 8 1289.5 vs 1287.5; station 9 1262.5 vs 1263.0 (aft
# of station 8 the chine lies outside the sheer, and the third left curve's top, 1213 px, matches
# station 9's sheer, 1219.5). Station 1's sheer is 685 px, the innermost right curve's top. So the
# left half is the aftbody (7 outermost) and the right half the forebody (6 outermost at the
# chine). Both readings agree.
# Notes: (1) the left half has a fourth, heavy, unlabelled curve inside station 9 with a heavy
# horizontal lower edge at the chine height (row 3239): the transom outline, not a station.
# (2) Forebody nesting: at the chine station 6 is outside station 5 (1297 vs 1238 px in the
# half-breadth plan), but at the sheer station 5 is wider (1439 vs 1425 px), so curves 5 and 6
# may cross near the top of the right half.
AFT_STATIONS_OUTER_FIRST = (7, 8, 9)
FORE_STATIONS_OUTER_FIRST = (6, 5, 4, 3, 2, 1)
STATIONS = tuple(range(1, 10))
AFT_GRID_COLUMNS: tuple[float, ...] = ()
FORE_GRID_COLUMNS: tuple[float, ...] = ()

# ---------------------------------------------------------------- reach
# Outermost hull ink: right 1443 px (stations 5/6 near the sheer, row 2503), left 1364 px
# (station 7 sheer, row 2559). 1465 px clears the right hull by 22 px.
# Labels inside the reach that the reach cannot exclude (one value serves both halves):
# left "7" (rows 2288 to 2392, 1378 to 1447 px; on the 2.5 ft row), left "Chine" (rows 3210 to
# 3310, from 1383 px; on the -0.5 ft row), right "Chine" (rows 3245 to 3346, from 1431 px; on the
# -0.5 ft row), right "4" (rows 2212 to 2311, from 1444 px; on the 3.0 ft row), right "2" (rows
# 2024 to 2124, 1166 to 1234 px; on the 3.5 ft row, above the hull there). Right "3" (1341 px)
# and "1" (728 px) lie between grid rows.
MAX_OFFSET_PX = 1465

# Body-plan region (rows, columns) drawn in the calibration overlay.
OVERLAY_REGION = (1750, 3900, 1150, 4800)  # stops left of the table of offsets


def base_row_at(column: float) -> float:
    """Image row of the drawn base line at `column`."""
    return BASE_ROW + BASE_ROW_PER_COLUMN * (column - CENTRE_COLUMN)


def height_ft(row: float, column: float) -> float:
    """Height above base (ft, negative below it) of an image point."""
    return (base_row_at(column) - row) / PIXELS_PER_FT


def sheet_layout() -> bpr.SheetLayout:
    """Host calibration: aftbody (stations 7 to 9) left of the centreline, forebody (1 to 6) right."""
    sides = (bpr.SideLayout('aft', -1, AFT_STATIONS_OUTER_FIRST, AFT_GRID_COLUMNS),
             bpr.SideLayout('fore', 1, FORE_STATIONS_OUTER_FIRST, FORE_GRID_COLUMNS))
    return bpr.SheetLayout(CENTRE_COLUMN, PIXELS_PER_M, dict(WATERLINE_ROWS), MAX_OFFSET_PX, sides)
