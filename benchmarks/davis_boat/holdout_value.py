"""Round-bilge holdout: 14'-3" Double Ended Davis Boat, HAER WA-227 sheet 1, body plan.

Protocol: docs/holdouts/davis-boat.md.
Sheet: work/holdout/davis_boat/master-pnp-habshaer-wa-wa0900-wa0928-sheet-00001a.tif
(14400 x 9600, 1-bit, 400 dpi), sha256 728ea5130529fbd9945fd4045a42bc274085ad89d8cf5a9dea1415d2271b7465.

Every constant below was set from the drawing's own scale bar, lines and labels before any reader
ran on this sheet (lane L, 2026-11-11). truth.json was not opened, and the table of offsets
(upper left, columns below 6500) was not viewed at a legible scale: overviews were downsampled 16
times, and every crop stayed at columns 6600 and above or rows 6300 and below. Image coordinates
are full-sheet pixels (row, column); the drawing is a CAD plot (zero slopes). A second,
independent truth-blind agent measured scale, axes, waterlines, sides and reach on its own crops
and agreed (see the protocol amendment).

Same interface as the hard-chine holdout calibrations (benchmarks/caleb_jones/holdout_value.py),
for the waterline cells read with benchmarks.deadrise_holdout.score.parse_truth and scored with
benchmarks.balclutha.model_value.score (protocol section 4). The measuring rows are the drawn
waterlines WL 3 to WL 24; the buttocks are given as grid columns (as for PARDON ME).
"""
from __future__ import annotations

from benchmarks.frozen_readers.v1 import body_plan_reader as bpr

PROTOCOL = 'docs/holdouts/davis-boat.md'
# Frozen truth file work/holdout/davis_boat/truth.json (main checkout, read-only): sha256 as
# recorded in the protocol section 1. The scorer stops if the file differs.
TRUTH_SHA256: str | None = '5bd7cd2824493218e16a4d932dd619c4e08262f2ba9abbe0889546e86e6ac3c6'
SHEET_SHA256 = '728ea5130529fbd9945fd4045a42bc274085ad89d8cf5a9dea1415d2271b7465'

# ---------------------------------------------------------------- scale
# Feet scale bar (printed "SCALE: 1 1/2" = 1'-0"", bar rows 8869 to 8986): full-height ticks at
# columns 8123-8125 ("0"), 8723-8725 ("1"), 9323-9325 ("2 FEET"), with 3-inch ticks every 50 px
# between 0 and 1; so 1200 px / 2 ft = 600.0 px/ft (nominal 1.5 in x 400 dpi).
# Drawn dimension: the profile notes print "STATION SPACING = 21 3/8""; the profile station lines
# are at columns 2876 (8), 3410 (7.5), 3945 (7), 5013, 6082, 7151, 8220, 9288, 10357 (1),
# 10892 (0.5), 11426 (0); (10357 - 3945) / 6 = 1068.67 px per 1.78125 ft = 599.95 px/ft.
# The body-plan waterlines (every 3 in) are 150 px apart and the buttocks (every 6 in) 300 px.
PIXELS_PER_FT = 600.0
PIXELS_PER_M = PIXELS_PER_FT / 0.3048

# ---------------------------------------------------------------- body plan axes
# Centreline: the one-pixel line at column 8450 (labelled "CL" below the body plan). The keel and
# stem siding lines are symmetric about it: columns 8399-8401 and 8499-8501 (+-50 px), 8428-8434
# and 8466-8472 (about +-19 px).
CENTRE_COLUMN = 8450.0
# Base line: the dashed one-pixel line labelled "BASELINE" at row 3243 across the whole body plan
# (one row from column 7000 to 9950: zero slope).
BASE_ROW = 3243.0
BASE_ROW_PER_COLUMN = 0.0

# ---------------------------------------------------------------- measuring rows
# The drawn dashed waterlines, labelled "WL 3" to "WL 24" (inches above the base line), are
# single-pixel rows 3093, 2943, 2793, 2643, 2493, 2343, 2193, 2043: 150 px = 3 in apart. Labels
# are feet-inches-eighths (WL 21 -> '1-9-0'), as the protocol renames the printed rows.
# Near-corner rows (drawn, kept as the protocol fixes them): WL 18 (2343) passes about 10 px under
# the sheer corner of station 4 (about row 2333) and about 25 px under station 3 (about 2318);
# the top of station 0.5 (about row 2045, where it leaves the sheer) is just below WL 24 (2043),
# so WL 24 meets the sheer there, not station 0.5.
WATERLINE_ROWS = {'0-3-0': 3093, '0-6-0': 2943, '0-9-0': 2793, '1-0-0': 2643,
                  '1-3-0': 2493, '1-6-0': 2343, '1-9-0': 2193, '2-0-0': 2043}
WATERLINE_HEIGHTS_FT = {label: (BASE_ROW - row) / PIXELS_PER_FT for label, row in WATERLINE_ROWS.items()}
WATERLINES = tuple(WATERLINE_ROWS)

# ---------------------------------------------------------------- sides
# Body-plan labels (printed text "STA n" at each curve top): left half "STA 5" (outermost), "STA 6",
# "STA 7", "STA 7.5"; right half "STA 4" (outermost), "STA 3", "STA 2", "STA 1", "STA 0.5". At row
# 2496 the left curves are at columns 7284 (5), 7485 (6), 7902 (7), 8180 (7.5) and the right at
# 8694 (0.5), 8972 (1), 9398 (2), 9609 (3), 9669 (4). Stations 3 and 4 run as a close pair on the
# right half, 4 outside 3 at every waterline (4 ends at the sheer under "STA 4", column about 9700;
# 3 under "STA 3", about 9640): the names follow the labels. No curve is labelled on both halves.
# Station 4 is the widest curve (1250 px) and lies at mid-length in the profile (column 7151,
# halfway between 2876 and 11426), as expected.
# Bow and stern (double-ended; from the drawing alone this is a convention, not a proof): the
# profile is numbered 8 at the left end to 0 at the right end, station 0 is conventionally the
# forward end, and the forebody is conventionally drawn right of the body-plan centreline. So the
# right half is named 'fore' (0.5 to 4) and the left 'aft' (5 to 7.5). The second, independent
# check reached the same reading with the same low confidence. The protocol section 3 decides the
# same way from table column headers, which this lane did not view. The side names do not change
# any cell: stations are named from the labels.
# The half stations 7.5 and 0.5 are listed with placeholder numbers so that rank naming does not
# shift; they are not truth stations and are never scored (the loader keeps whole stations only).
HALF_STATION_7_5 = 1075
HALF_STATION_0_5 = 1005
AFT_STATIONS_OUTER_FIRST = (5, 6, 7, HALF_STATION_7_5)
FORE_STATIONS_OUTER_FIRST = (4, 3, 2, 1, HALF_STATION_0_5)
STATIONS = tuple(range(1, 8))  # scored stations 1 to 7 (protocol section 4)
# Dashed buttocks B-6, B-12, B-18, B-24 (columns from the centreline outward).
AFT_GRID_COLUMNS = (8150.0, 7850.0, 7550.0, 7250.0)
FORE_GRID_COLUMNS = (8750.0, 9050.0, 9350.0, 9650.0)

# ---------------------------------------------------------------- reach
# Outermost hull ink: station 4 at its sheer corner, column 9700 at row 2340 (1250 px right);
# station 5 at its top, column 7250 at row 2305 (1200 px left, touching the B-24 buttock).
# 1270 px clears the right by 20 px and stays inside the "WL n" and "BASELINE" labels (from about
# 1505 px left and 1525 px right). Text and lines inside the reach that it cannot exclude: the
# "STA n" labels above the sheer (rows 2000 to 2300); "DIAG A" left (rows about 2895 to 3020, 1200
# to 1350 px; on the WL 6 row at 1234 to 1306 px) and right (rows about 2830 to 3010, 1130 to
# 1350 px; on the WL 6 row at 1239 to 1278 px), both outside the hull; "DIAG B" left and right
# (rows about 3045 to 3255, 790 to 980 px; on the WL 3 row at 811 to 855 px), outside the hull;
# the two diagonal lines on each half, which cross the hull curves; the buttocks (grid columns);
# and the keel and stem siding lines at +-19 and +-50 px.
MAX_OFFSET_PX = 1270

# Body-plan region (rows, columns) drawn in the calibration overlay; stays right of the table of
# offsets (which ends left of column 6500).
OVERLAY_REGION = (1950, 3450, 6950, 9950)


def base_row_at(column: float) -> float:
    """Image row of the drawn base line at `column`."""
    return BASE_ROW + BASE_ROW_PER_COLUMN * (column - CENTRE_COLUMN)


def height_ft(row: float, column: float) -> float:
    """Height above base (ft) of an image point."""
    return (base_row_at(column) - row) / PIXELS_PER_FT


def sheet_layout() -> bpr.SheetLayout:
    """Host calibration: aftbody (5 to 7.5) left of the centreline, forebody (0.5 to 4) right."""
    sides = (bpr.SideLayout('aft', -1, AFT_STATIONS_OUTER_FIRST, AFT_GRID_COLUMNS),
             bpr.SideLayout('fore', 1, FORE_STATIONS_OUTER_FIRST, FORE_GRID_COLUMNS))
    return bpr.SheetLayout(CENTRE_COLUMN, PIXELS_PER_M, dict(WATERLINE_ROWS), MAX_OFFSET_PX, sides)
