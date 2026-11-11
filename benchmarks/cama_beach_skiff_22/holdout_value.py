"""Hard-chine holdout: CAMA BEACH SKIFF No. 22 (flat-bottom rowing skiff, 1934), HAER WA-199 sheet 1 "Lines".

Protocol: docs/BODY_PLAN_CHINE.md, "Holdout protocol: CAMA BEACH SKIFF No. 22".
Sheet: work/holdout/cama_beach_skiff_22/master-pnp-habshaer-wa-wa0800-wa0881-sheet-00001a.tif
(14400 x 9600, 1-bit, 400 dpi), sha256 db390a25fcd033c1912d4cbce248cb91cbe4b2e736203ecfcc3e34f395cc6e42.

Every constant below was set from the drawing's own scale bar, lines and labels before any reader
ran on this sheet (lane L, 2026-11-11). truth.json was not opened, and the table of offsets
(rows 1680 to 3440, columns 5680 to 12320) was not viewed at a legible scale: overviews were
downsampled 16 times, and every crop stayed outside that rectangle. Image coordinates are
full-sheet pixels (row, column); the drawing is a CAD plot (zero slopes). A second, independent
truth-blind agent measured scale, axes, waterlines, sides and reach on its own crops and agreed
(see the protocol amendment).

The body plan has drawn waterlines W1, W2, W3 (3, 6, 9 in) and the base line W0. The flat bottoms
and chines lie below the base line (heights there are negative), and the station tops reach about
17.6 in, so a few fixed rows are added below the base line and above W3.
"""
from __future__ import annotations

from benchmarks.frozen_readers.v1 import body_plan_reader as bpr

PROTOCOL = 'docs/BODY_PLAN_CHINE.md (Holdout protocol: CAMA BEACH SKIFF No. 22)'
# Frozen truth file work/holdout/cama_beach_skiff_22/truth.json (main checkout, read-only): sha256
# as recorded in the protocol. The scorer stops if the file differs.
TRUTH_SHA256: str | None = '473ef776bd3d0d022e4c5e7ee47dc223853cf5a2ae6e08c984ca0ba9f8651b1e'
SHEET_SHA256 = 'db390a25fcd033c1912d4cbce248cb91cbe4b2e736203ecfcc3e34f395cc6e42'

# ---------------------------------------------------------------- scale
# Feet scale bar (printed "SCALE: 1 1/2" = 1'-0"", bar rows 8497 to 8577): full-height ticks at
# columns 11361-11364 ("0"), 11961-11964 ("1"), 12561-12564 ("2 FEET"), with 3-inch ticks every
# 50 px between 0 and 1; so 1200 px / 2 ft = 600.0 px/ft (nominal 1.5 in x 400 dpi).
# Drawn dimensions: the profile station lines (dimensioned "1'-4"") are at columns 3586.5,
# 4386.5, ... 10786.5, 800 px apart = 600.0 px/ft; the overall length "13'-7"" between its
# extension lines at columns 3006 and 11160 = 8154 px / 13.583 ft = 600.3 px/ft.
PIXELS_PER_FT = 600.0
PIXELS_PER_M = PIXELS_PER_FT / 0.3048

# ---------------------------------------------------------------- body plan axes
# Centreline: dash-dot line at columns 3884 to 3886, rows 2222 to 3535.
CENTRE_COLUMN = 3885.0
# Base line: the drawn line labelled "Baseline", rows 3234 to 3236, the same rows at columns 2450,
# 2800 and 4500 (zero slope); it runs from about column 2420 to 5050.
BASE_ROW = 3235.0
BASE_ROW_PER_COLUMN = 0.0
# Drawn waterlines (labelled W1, W2, W3 in the profile): rows 3084-3086, 2934-2936, 2784-2786, so
# exactly 150 px = 3 in apart and on the scale above.

# ---------------------------------------------------------------- measuring rows
# Inches above the base line (negative below). 0, 3, 6 and 9 are the drawn W0 to W3.
# Below the base line: the lowest hull ink is row 3426 (3.8 in below). The drawn section bottoms
# are horizontal lines at rows 3197-3204, 3241-3246, 3340-3345 and 3400-3406 (left half) and about
# 3333-3338, 3385-3390 and 3415-3426 (right half), so a 3-inch grid would put -3 in (row 3385) on a
# bottom line. The rows are therefore every inch on the half inch: -0.5, -1.5, -2.5, -3.5 in
# (rows 3260, 3310, 3360, 3410); the row ink lists show no horizontal run on any of them.
# Above W3: the station tops (sheer corners) are near rows 2355 (station 1), 2422 (2), 2498 (3),
# 2567 (4), 2620 (5), 2635 (6), 2640 (7) on the right and 2565 (10), 2595 (9), 2640 (8) on the
# left; a 3-inch row at 12 in (2635) would pass within 5 px under the corners of 7 and 8. The rows
# are put in the gaps, each at least 27 px from every corner and from the transom top line (rows
# 2412-2417): 10.5 in (2710, below every top), 14 in (2535), 15.5 in (2460), 17 in (2385). The top
# 0.6 in of station 1 is not covered: a row at 18 in (2335) would run along the sheer at the stem
# head (row 2334).
MEASURING_HEIGHTS_IN = (-3.5, -2.5, -1.5, -0.5, 0.0, 3.0, 6.0, 9.0, 10.5, 14.0, 15.5, 17.0)
PIXELS_PER_IN = PIXELS_PER_FT / 12


def _label(height_in: float) -> str:
    """Signed feet-inches-eighths label of a height in inches: 15.5 -> '1-3-4', -0.5 -> '-0-0-4'."""
    sign = '-' if height_in < 0 else ''
    eighths_total = round(abs(height_in) * 8)
    feet, rest = divmod(eighths_total, 96)
    inches, eighths = divmod(rest, 8)
    return f'{sign}{feet}-{inches}-{eighths}'


def _measuring_rows() -> dict:
    return {_label(h): int(round(BASE_ROW - h * PIXELS_PER_IN)) for h in MEASURING_HEIGHTS_IN}


# Label (signed feet-inches-eighths above base) -> image row, low to high.
WATERLINE_ROWS = _measuring_rows()
WATERLINE_HEIGHTS_FT = {label: (BASE_ROW - row) / PIXELS_PER_FT for label, row in WATERLINE_ROWS.items()}
WATERLINES = tuple(WATERLINE_ROWS)

# ---------------------------------------------------------------- sides
# Reading 1 (body-plan labels): right half labelled "1" (innermost, highest sheer, at the stem) to
# "7" (outermost); left half "8" (outermost), "9", "10". At row 2790 the right curves are at columns
# 3987, 4268.5, 4532, 4755.5, 4918, 5010, 5039.5 (1 to 7) and the left at 2762.5, 2839.5, 2936.5
# (8, 9, 10). Curves 6 and 7 almost coincide below W2 and meet near the chine (row about 3425).
# Reading 2 (profile and half-breadth plan): the profile is labelled "10" (left, transom near
# column 3006) to "1" (right, raked stem near column 11084); station lines 3586.5 (10) to 10786.5
# (1). In the half-breadth plan (centreline row 7372) the W3 half-breadths at those station lines
# are 953, 1049.5, 1126.5, 1158, 1128.5, 1035, 872.5, 648, 383.5, 101 px (10 to 1); the body-plan
# curves at row 2790 give 948.5, 1045.5, 1122.5 (left 10, 9, 8) and 1154.5, 1125, 1033, 870.5,
# 647, 383.5, 102 (right 7 to 1): each within 4 px. So the right half is the forebody (1 to 7)
# and the left half the aftbody (8 to 10). No station is drawn on both halves: the left outermost
# curve is 32 to 37 px inside the right station 7 at W1 to W3, and the plan says it is station 8.
# Not stations, not listed: on the left a heavy unlabelled line inside station 10 (column 2991 at
# row 2790) that joins the transom top curve (top line rows 2412-2417 to the centreline), a thin
# line beside it (column 3047 at row 2790, ending in mid-air near row 3180), and an unlabelled
# notch line (from the transom top at column 3633 down to column 3700 near row 2810, then across to
# the centreline; 185 to 250 px left, crossed by the rows from 15.5 in to W3); on the right two vertical stem lines at
# columns 3900-3903 and 3933-3936 (station 1 runs into the second near the base line).
# Station 10 is labelled and drawn but has no printed offsets: it is named here so that rank
# naming does not shift, and it is not a scored station.
AFT_STATIONS_OUTER_FIRST = (8, 9, 10)
FORE_STATIONS_OUTER_FIRST = (7, 6, 5, 4, 3, 2, 1)
STATIONS = tuple(range(1, 10))  # scored stations, as in the protocol's parse check
AFT_GRID_COLUMNS: tuple[float, ...] = ()
FORE_GRID_COLUMNS: tuple[float, ...] = ()

# ---------------------------------------------------------------- reach
# Outermost hull ink: the sheer corners near row 2640, station 8 at column 2647 (1238 px left) and
# station 7 at column 5124 (1239 px right). 1250 px clears both by 11 px and stays inside the
# label "8" (from 1255 px, rows about 2600 to 2700) and the word "Baseline" (from 1262 px, on the
# base line). Labels inside the reach that the reach cannot exclude, all above the hull at their
# columns: right "3" (rows about 2340 to 2430, 695 to 770 px; on the 17 in row), "4" (rows about
# 2430 to 2505, 905 to 980 px; on the 15.5 in row), "5" (rows about 2460 to 2550, 1060 to 1125 px;
# on the 15.5 in and 14 in rows), "6" (rows about 2520 to 2600, 1200 to 1290 px; on the 14 in row);
# left "9" (rows about 2460 to 2560, 1185 to 1265 px; on the 15.5 in and 14 in rows) and "10"
# (rows about 2350 to 2440, 1050 to 1165 px; on the 17 in row).
MAX_OFFSET_PX = 1250

# Body-plan region (rows, columns) drawn in the calibration overlay; stops left of the table of
# offsets (which begins near column 5680).
OVERLAY_REGION = (2250, 3500, 2400, 5450)


def base_row_at(column: float) -> float:
    """Image row of the drawn base line at `column`."""
    return BASE_ROW + BASE_ROW_PER_COLUMN * (column - CENTRE_COLUMN)


def height_ft(row: float, column: float) -> float:
    """Height above base (ft, negative below it) of an image point."""
    return (base_row_at(column) - row) / PIXELS_PER_FT


def sheet_layout() -> bpr.SheetLayout:
    """Host calibration: aftbody (8 to 10) left of the centreline, forebody (1 to 7) right."""
    sides = (bpr.SideLayout('aft', -1, AFT_STATIONS_OUTER_FIRST, AFT_GRID_COLUMNS),
             bpr.SideLayout('fore', 1, FORE_STATIONS_OUTER_FIRST, FORE_GRID_COLUMNS))
    return bpr.SheetLayout(CENTRE_COLUMN, PIXELS_PER_M, dict(WATERLINE_ROWS), MAX_OFFSET_PX, sides)
