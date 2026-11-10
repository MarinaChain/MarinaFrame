"""Hard-chine holdout: skipjack CALEB JONES (Rice Brothers, Reedville VA, 1953), HAER MD-171 sheet 1 "Lines", body plan.

Protocol: docs/BODY_PLAN_CHINE.md, "Holdout protocol: CALEB JONES".
Sheet: work/holdout/caleb-jones/md1860-sheet-00001a-lines.tif (14400 x 9600, 1-bit, 400 dpi),
sha256 c05fb65a16a6221d3eddc984fba7c40c652c2bcef275ce12d044949b7a1485b8.

Every constant below was set from the drawing's own scale bars, lines and labels before any
reader ran on this sheet. No truth value was used, and the table of offsets was not read (see
the disclosure in the protocol section). Image coordinates are full-sheet pixels (row, column);
the drawing is a CAD plot (zero slopes).

The body plan has no drawn waterlines or buttocks: only the base line, which crosses the sections
just above the chine; the bottoms and the keel lie below it, so heights below the base line are
negative. The measuring rows are therefore a fixed grid of heights from the scale alone, as for
E. C. COLLIER and COLLEEN.
"""
from __future__ import annotations

from benchmarks.frozen_readers.v1 import body_plan_reader as bpr

PROTOCOL = 'docs/BODY_PLAN_CHINE.md (Holdout protocol: CALEB JONES)'
# Frozen truth file work/holdout/caleb-jones/truth.json (main checkout, read-only): sha256 given by
# the PM before the run. The scorer stops if the file differs.
TRUTH_SHA256: str | None = '1830c5213591604f52f5cb36c1924acee338ad3a1b52d706fff86c4b8dbae9e5'
SHEET_SHA256 = 'c05fb65a16a6221d3eddc984fba7c40c652c2bcef275ce12d044949b7a1485b8'

# ---------------------------------------------------------------- scale
# Feet scale bar (printed "SCALE: 1/2" = 1'-0"", rows 8718 to 8783): tick columns 11298-11300 ("0"),
# 11498-11500, 11698-11700, 11898-11900, 12098-12100, 12298-12300 ("5"), so 1000 / 5 = 200.0 px/ft
# (nominal 0.5 in x 400 dpi). The centimetre bar below it ("0" 11299-11302, "150" 12274-12277)
# gives 975 px / 1.5 m = 650 px/m = 198.1 px/ft: it is drawn 0.9 % short and is not used.
# Drawn dimensions: the body-plan beam "16'-9 15/16"" between its extension lines at columns
# 1753 and 5120 = 3367 px / 16.831 ft = 200.05 px/ft; in the profile and half-breadth plan the
# station lines are 800 px apart (columns 3224, 4024, ... 10425; dimensioned "4'-0"") = 200.0 px/ft.
PIXELS_PER_FT = 200.0
PIXELS_PER_M = PIXELS_PER_FT / 0.3048

# ---------------------------------------------------------------- body plan axes
# Centreline: the dash-dot centreline ink is columns 3435 to 3438 above the stem head (rows 1800
# to 1990) and below the keel (rows 3480 to 3560).
CENTRE_COLUMN = 3436.5
# Base line: the drawn line labelled "Baseline", row 2989.0 (one pixel), unbroken over columns
# 1583 to 5290, zero slope. The chines lie just below it; the keel bottom is near row 3445
# (-2.28 ft) and the bottoms meet the keel near row 3335 (-1.73 ft).
BASE_ROW = 2989.0
BASE_ROW_PER_COLUMN = 0.0

# ---------------------------------------------------------------- measuring rows
# Every 6 inches from 2.0 ft below the base line to 4.5 ft above it (14 rows, 100 px apart).
# Range: the -2.0 ft row is below every bottom-to-keel junction and above the keel bottom
# (-2.28 ft); there it crosses only the keel sides (within 44 px of the centreline). The highest
# station top is station 1 (side meets the top line near row 2150, about 4.2 ft); the stem head
# (about 4.9 ft) is not a station, so 4.5 ft is the top row. Why 6 inches: as COLLEEN (150 px)
# and COLLIER (75 px); here 100 px. The 0.0 ft row lies on the drawn base line (as on COLLEEN).
MEASURING_STEP_FT = 0.5
MEASURING_BOTTOM_FT = -2.0
MEASURING_TOP_FT = 4.5


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
# Reading 1 (labels in the body plan): the right half carries "1" (innermost, highest sheer, at
# the stem) to "7" (outermost) along its sheer; the left half carries "8", "9", "10" from the
# outside inward.
# Reading 2 (profile and half-breadth plan): the profile is labelled "10" (transom, left) to "1"
# (stem, right); the stem rakes forward at the right end. Half-breadth plan (centreline row 7563;
# station lines 5624 = 7, 4824 = 8, 4024 = 9, 3224 = 10) outer-line half-breadths 1683 / 1649 /
# 1567 / 1455 px against the left body-plan curve tops (at the top line) about 1681 / 1646 / 1561
# / 1451 px; heavy sheer line, fore: plan 433 / 855 / 1175.5 / 1635 / 1666 px (1, 2, 3, 6, 7)
# against right curves at the heavy sheer 435 / 855 / 1176 / 1636 / 1660 px. So the right half is
# the forebody (1 to 7) and the left half the aftbody (8 to 10). Both readings agree.
#
# Station 7 is drawn on BOTH halves. The left half's outermost curve has no label, and it is the
# mirror of the right half's station 7 (offsets left / right: row 2495 1683 / 1684 px, 2600 1656
# / 1657, 2800 1604 / 1604, 3100 1526 / 1527) and of the plan's station 7 (1683 px); the beam
# dimension "16'-9 15/16"" spans these two curves. The label "7" is printed on the right half, so
# the right curve is station 7. The left copy is listed with a placeholder number so that rank
# naming does not call it "8"; the placeholder is not a truth station and is never scored.
# Note: the left half also has a heavy, unlabelled transom outline inside station 10 (top edge
# near row 2355 running in to the centreline; side down to about row 2550, 1290 px out; then a
# heavy diagonal inward to about row 2925, 45 px out; then down beside the keel), and a thin line
# from about row 2955 (1290 px out) to row 3150 at the keel: not stations, not listed.
LEFT_COPY_OF_STATION_7 = 107
AFT_STATIONS_OUTER_FIRST = (LEFT_COPY_OF_STATION_7, 8, 9, 10)
FORE_STATIONS_OUTER_FIRST = (7, 6, 5, 4, 3, 2, 1)
STATIONS = tuple(range(1, 11))
AFT_GRID_COLUMNS: tuple[float, ...] = ()
FORE_GRID_COLUMNS: tuple[float, ...] = ()

# ---------------------------------------------------------------- reach
# Outermost hull ink: station 7 at its top, row 2495, 1683 px left and 1684 px right. 1705 px clears
# it by 21 px and stays inside the labels "7" (from 1792 px) and "Baseline" (from 1776 px).
# Labels inside the reach that the reach cannot exclude (one value serves both halves), all above
# the hull at their columns except "Sheer":
# left "8" (rows 2331 to 2398, 1638 to 1694 px; on the 3.0 ft row), right "6" (rows 2336 to 2404,
# 1656 to 1712 px; 3.0 ft row), left "9" (rows 2285 to 2352, 1542 to 1594 px; 3.5 ft row), left
# "10" (rows 2240 to 2308, 1392 to 1480 px; 3.5 ft row), right "4" (rows 2270 to 2335, 1388 to
# 1444 px; 3.5 ft row), right "2" (rows 2126 to 2192, 884 to 930 px; glyph foot on the 4.0 ft
# row), and the word "Sheer" inside the forebody between the sheer line and stations 1 and 2
# (rows 2263 to 2371, 534 to 752 px; 3.5 ft row). Right "5" (rows 2306 to 2374), "3" and "1"
# lie between grid rows.
MAX_OFFSET_PX = 1705

# Body-plan region (rows, columns) drawn in the calibration overlay; stops left of the table of
# offsets (which begins near column 5730).
OVERLAY_REGION = (1900, 3800, 1450, 5600)


def base_row_at(column: float) -> float:
    """Image row of the drawn base line at `column`."""
    return BASE_ROW + BASE_ROW_PER_COLUMN * (column - CENTRE_COLUMN)


def height_ft(row: float, column: float) -> float:
    """Height above base (ft, negative below it) of an image point."""
    return (base_row_at(column) - row) / PIXELS_PER_FT


def sheet_layout() -> bpr.SheetLayout:
    """Host calibration: aftbody (left copy of 7, then 8 to 10) left of the centreline, forebody (1 to 7) right."""
    sides = (bpr.SideLayout('aft', -1, AFT_STATIONS_OUTER_FIRST, AFT_GRID_COLUMNS),
             bpr.SideLayout('fore', 1, FORE_STATIONS_OUTER_FIRST, FORE_GRID_COLUMNS))
    return bpr.SheetLayout(CENTRE_COLUMN, PIXELS_PER_M, dict(WATERLINE_ROWS), MAX_OFFSET_PX, sides)
