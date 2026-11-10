"""Hard-chine holdout: M/V WHITE GULL (Chesapeake deadrise workboat), HAER MD sheet 1 "Lines", body plan.

Protocol: docs/BODY_PLAN_CHINE.md, "Holdout protocol: WHITE GULL and COLLEEN".
Sheet: work/holdout/white-gull/md1939-sheet-00001a-lines.tif (14400 x 9600, 1-bit, 400 dpi),
sha256 905e9150de0fa71dd3c76c7aff8fabc10f95a43e2e61c7d2331fa0732d6b5177.

Every constant below was set from the drawing's own scale bars, lines and labels before any
reader ran on this sheet. No truth value was used, and the table of offsets was not read.
Image coordinates are full-sheet pixels (row, column). The drawing is a CAD plot: its grid
lines are exactly horizontal and vertical (fits give zero slope).
"""
from __future__ import annotations

from vessel_reconstruction import body_plan_reader as bpr

PROTOCOL = 'docs/BODY_PLAN_CHINE.md (Holdout protocol: WHITE GULL and COLLEEN)'
# Frozen truth file work/holdout/<boat>/truth.json: its sha256 is given by the PM before the run.
# None until then; the scorer refuses to load any truth while it is None.
TRUTH_SHA256: str | None = None
SHEET_SHA256 = '905e9150de0fa71dd3c76c7aff8fabc10f95a43e2e61c7d2331fa0732d6b5177'

# ---------------------------------------------------------------- scale
# Feet scale bar (printed "1/2" = 1'-0"", rows 8478 to 8612): its "0" tick is at column 2014.0
# and its "50" tick at column 12014.0, so 10000 / 50 = 200.0 px/ft (nominal 0.5 in x 400 dpi).
# Metres bar below it: "0" at 3174.0, "12" at 11046.0, 656.0 px/m = 199.95 px/ft (0.03 %).
# Drawn dimensions in the profile and half-breadth plan: the ten station lines are 800.0 px
# apart (columns 3527 to 10727), dimensioned "4'-0"" = 200.0 px/ft; the last space to the stem
# perpendicular (10727 to 11416, 689 px) is dimensioned "3'-5 5/16"" = 200.1 px/ft.
PIXELS_PER_FT = 200.0
PIXELS_PER_M = PIXELS_PER_FT / 0.3048

# ---------------------------------------------------------------- body plan axes
# Centreline: the dash-dot centreline ink is columns 3778 to 3781 above the sheer (rows 2400 to
# 2700) and below the base (rows 4160 to 4300); the buttock lines are symmetric about it
# (3579.5 / 3979.5 ... 2579.5 / 4979.5).
CENTRE_COLUMN = 3779.5
# Base line: the drawn line labelled "Baseline", row 4146.0, zero slope over columns 2300 to 5300.
BASE_ROW = 4146.0
BASE_ROW_PER_COLUMN = 0.0

# ---------------------------------------------------------------- waterlines
# The profile labels W1 to W6 at its right end; there they are 200 px (1 ft) apart above the
# baseline (profile rows: baseline 6015, W1 5815, W2 5615, W3 5415, W4 5215, W5 5015), so Wk is
# k ft above base. In the body plan W2 to W6 are drawn; their measured rows are used.
# W1 (1 ft) is not drawn in the body plan (it would only cut the keel and the lowest bottom
# lines); its row is set from the scale, 200 px above the base line.
# A "Painted Waterline" is also drawn (row 3658, 2.44 ft above base). It is not a numbered
# waterline, so it is not a measuring row (the readers see it as a crossing line).
WATERLINE_ROWS = {'W1': 3946, 'W2': 3746, 'W3': 3546, 'W4': 3345, 'W5': 3145, 'W6': 2945}
WATERLINE_HEIGHTS_FT = {f'W{k}': float(k) for k in range(1, 7)}  # nominal heights of the labels
WATERLINES = tuple(WATERLINE_ROWS)  # low to high

# ---------------------------------------------------------------- sides
# Reading 1 (labels in the body plan): the left half carries "Sta.1" (innermost, highest sheer)
# to "Sta.5" (outermost), each with a leader to its curve; the right half carries "Sta.6"
# (outermost) to "Sta.10" (innermost). Left-half sections are steep V forms with the chine rising
# inward; right-half sections have flat, low-deadrise bottoms.
# Reading 2 (profile and half-breadth plan, no station numbers printed there): the stem is at the
# right of the profile (sheer rises to it) and the transom at the left. The half-breadth plan's
# outer line at the station line nearest the stem (column 10727) is 670 px from its centreline;
# the body plan's innermost left curve ("Sta.1") has its sheer about 690 px out. At the station
# line nearest the transom (3527) it is 1074 to 1102 px, matching the innermost right curve
# ("Sta.10", about 1020 to 1070 px), while no left curve is that narrow at the top. So stations
# count from the bow; the left half is the forebody and the right half the aftbody.
# Both readings agree.
# Note: the right half also has a heavy unlabelled curve inside "Sta.10" with a heavy horizontal
# lower edge at row 3771 (the transom outline). It is not a station and is not listed.
FORE_STATIONS_OUTER_FIRST = (5, 4, 3, 2, 1)
AFT_STATIONS_OUTER_FIRST = (6, 7, 8, 9, 10)
STATIONS = tuple(range(1, 11))
# Buttocks: vertical grid lines every 200 px (1 ft) on both halves, 1 to 6 ft out (the profile
# labels B4, B5, B6). Measured columns.
FORE_GRID_COLUMNS = (3579.5, 3379.5, 3179.5, 2979.5, 2779.5, 2579.5)
AFT_GRID_COLUMNS = (3979.5, 4179.5, 4379.5, 4579.5, 4779.5, 4979.5)

# ---------------------------------------------------------------- reach
# Outermost hull ink: left 1341.5 px (the sheer ends of stations 4 and 5, row 2940), right about
# 1320 px (station 6 sheer; the "Sta.6"/"Sta.7" leaders touch it and run out to 1372 px).
# Labels: left "Sta.4" text ends at 1371.5 px; right "Painted Waterline" text starts at 1358.5 px.
# 1356 px clears the left hull by 14 px and stops before both.
# Not excluded by the reach: the left "Chine" label (rows 3732 to 3800, 1220 to 1410 px out)
# lies across the W2 row (3746) outside the hull; the right "Chine" label starts at row 3759.
MAX_OFFSET_PX = 1356

# Body-plan region (rows, columns) drawn in the calibration overlay.
OVERLAY_REGION = (2650, 4350, 2050, 5800)  # stops left of the table of offsets


def base_row_at(column: float) -> float:
    """Image row of the drawn base line at `column`."""
    return BASE_ROW + BASE_ROW_PER_COLUMN * (column - CENTRE_COLUMN)


def height_ft(row: float, column: float) -> float:
    """Height above base (ft) of an image point."""
    return (base_row_at(column) - row) / PIXELS_PER_FT


def sheet_layout() -> bpr.SheetLayout:
    """Host calibration: forebody (stations 1 to 5) left of the centreline, aftbody (6 to 10) right."""
    sides = (bpr.SideLayout('fore', -1, FORE_STATIONS_OUTER_FIRST, FORE_GRID_COLUMNS),
             bpr.SideLayout('aft', 1, AFT_STATIONS_OUTER_FIRST, AFT_GRID_COLUMNS))
    return bpr.SheetLayout(CENTRE_COLUMN, PIXELS_PER_M, dict(WATERLINE_ROWS), MAX_OFFSET_PX, sides)
