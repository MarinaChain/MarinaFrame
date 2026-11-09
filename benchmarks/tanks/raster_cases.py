"""Host calibration of the raster tank-plan cases (docs/TANKS_V2.md section 2).

A person read these from the sheets without the truth: the window of each view (shares of the
sheet width and height), whether it is a profile or a plan and the plan's role, the frame spacing
printed on the sheet or the window of the graphic scale bar, and the window of the tank schedule.
No geometry is given here: scale, frame positions, boundaries and heights are read by code.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

from vessel_reconstruction.tank_plan_raster import FEET_M, INK_THRESHOLD, SheetSpec, ViewSpec


def _share(x0, y0, x1, y1, width, height):
    """A window measured on a reduced preview image of the sheet, as shares of the sheet."""
    return (x0 / width, y0 / height, x1 / width, y1 / height)


# Windows were measured on 40 dpi previews (1873 x 1325 px) of the A0 sheets.
PREVIEW = (1873, 1325)

GUNNERUS_TANK_PLAN = SheetSpec(
    views=[ViewSpec('profile', 'profile', _share(60, 655, 1250, 875, *PREVIEW)),
           ViewSpec('tank_top', 'plan', _share(60, 940, 1215, 1262, *PREVIEW), role='double_bottom')],
    frame_spacing_m=0.500,  # main dimensions table: "FRAME DISTANCE 500 MM"
    schedule=_share(1160, 52, 1850, 565, *PREVIEW))

GUNNERUS_TANK_ARRANGEMENT = SheetSpec(
    views=[ViewSpec('profile', 'profile', _share(40, 460, 1000, 606, *PREVIEW)),
           ViewSpec('below_1_deck', 'plan', _share(40, 648, 1000, 897, *PREVIEW), role='above'),
           ViewSpec('below_tank_top', 'plan', _share(40, 915, 1000, 1172, *PREVIEW), role='double_bottom')],
    frame_spacing_m=0.500,  # main particulars: "FRAME DISTANCE 500 (mm)"
    schedule=_share(1070, 385, 1392, 870, *PREVIEW))

# HAER sheets (400 dpi bilevel TIFF). Windows measured on 1/8 previews.
SAUGATUCK_SHEET4 = SheetSpec(
    views=[ViewSpec('profile', 'profile', _share(240, 270, 1950, 520, 2200, 1700)),
           ViewSpec('second_deck_and_hold', 'plan', _share(240, 1095, 1880, 1320, 2200, 1700), role='above')],
    scale_bar=_share(395, 1478, 1795, 1530, 2200, 1700), scale_bar_unit_m=FEET_M)

# Empire State V (HAER VA-131): the inboard capacity profile on sheet 6 and the double-bottom
# capacity plan on sheet 8; both print a schedule of rooms (names of the numbered spaces).
ESV_PREVIEW = (1800, 1200)
EMPIRE_STATE_V_SHEET6 = SheetSpec(
    views=[ViewSpec('profile', 'profile', _share(180, 300, 1640, 485, *ESV_PREVIEW))],
    scale_bar=_share(345, 688, 1470, 752, *ESV_PREVIEW), scale_bar_unit_m=FEET_M,
    schedule=_share(265, 800, 1550, 1025, *ESV_PREVIEW))
EMPIRE_STATE_V_SHEET8 = SheetSpec(
    views=[ViewSpec('double_bottom', 'plan', _share(270, 335, 1515, 530, *ESV_PREVIEW), role='double_bottom')],
    scale_bar=_share(345, 688, 1470, 752, *ESV_PREVIEW), scale_bar_unit_m=FEET_M,
    schedule=_share(265, 800, 1550, 985, *ESV_PREVIEW))
ESV_DIR = 'tanks-public/empire_state_v_haer_va131/'
ESV_SUFFIX = '_-_Empire_State_V,_James_River_Reserve_Fleet,_Newport_News,_Newport_News,_VA_HAER_VA-131_'

# Arthur M. Huddell (HAER VA-132), the holdout (docs/TANKS_V2.md section 4). Written from the
# sheets only, without access to the truth. Windows measured on 1/8 previews (1800 x 1200 px).
# All three sheets print the same 1/16 in = 1 ft graphic bar (feet above, metres below).
HUDDELL_PREVIEW = (1800, 1200)
HUDDELL_SHEET7 = SheetSpec(  # Inboard Capacity Plan: profile, deck line to baseline
    views=[ViewSpec('profile', 'profile', _share(220, 335, 1615, 528, *HUDDELL_PREVIEW))],
    scale_bar=_share(228, 700, 1638, 778, *HUDDELL_PREVIEW), scale_bar_unit_m=FEET_M,
    schedule=_share(612, 810, 1252, 987, *HUDDELL_PREVIEW))
HUDDELL_SHEET8 = SheetSpec(  # Upper Deck and Second Deck Capacity Plans
    views=[ViewSpec('upper_deck', 'plan', _share(218, 272, 1606, 462, *HUDDELL_PREVIEW), role='above'),
           ViewSpec('second_deck', 'plan', _share(215, 515, 1616, 708, *HUDDELL_PREVIEW), role='above')],
    scale_bar=_share(228, 765, 1638, 843, *HUDDELL_PREVIEW), scale_bar_unit_m=FEET_M,
    schedule=_share(505, 893, 1360, 1072, *HUDDELL_PREVIEW),
    notes=['The small "Flat between 2nd and upper decks" view (bow stores) is not given.'])
HUDDELL_SHEET9 = SheetSpec(  # Inner Bottom Capacity Plan and Deep Tank Top (a part plan)
    views=[ViewSpec('inner_bottom', 'plan', _share(240, 380, 1460, 592, *HUDDELL_PREVIEW), role='double_bottom'),
           ViewSpec('deep_tank_top', 'plan', _share(1190, 170, 1425, 325, *HUDDELL_PREVIEW), role='above')],
    scale_bar=_share(228, 668, 1638, 746, *HUDDELL_PREVIEW), scale_bar_unit_m=FEET_M,
    schedule=_share(505, 785, 1360, 1045, *HUDDELL_PREVIEW))
HUDDELL_DIR = 'tanks-public/arthur_m_huddell_haer_va132/'
HUDDELL_SUFFIX = '_-_Arthur_M._Huddell,_James_River_Reserve_Fleet,_Newport_News,_Newport_News,_VA_HAER_VA-132_'

# Case -> sheets (path under the sources folder, sheet description). A case may span sheets
# (a profile on one sheet, plans on others).
CASES = {
    'gunnerus_tank_plan': [('gunnerus/polarkonsult/Tank Plan Rev1.pdf', GUNNERUS_TANK_PLAN)],
    'gunnerus_tank_arrangement': [('gunnerus/extended/CJOB/Tank Arrangement Rev0.pdf', GUNNERUS_TANK_ARRANGEMENT)],
    'saugatuck': [('tanks-public/saugatuck_haer_va128/Capacity_Plan_Profile,_Upper_Deck_Capacity_Plan,_Second_Deck_'
                   'and_Hold_Capacity_Plan_-_Saugatuck,_James_River_Reserve_Fleet,_Newport_News,_Newport_News,_VA_'
                   'HAER_VA-128_(sheet_4_of_6).tif', SAUGATUCK_SHEET4)],
    'empire_state_v': [
        (ESV_DIR + 'Capacity_Plan_Inboard_Profile' + ESV_SUFFIX + '(sheet_6_of_13).tif', EMPIRE_STATE_V_SHEET6),
        (ESV_DIR + 'Capacity_Plan_Double_Bottom' + ESV_SUFFIX + '(sheet_8_of_13).tif', EMPIRE_STATE_V_SHEET8)],
    'arthur_m_huddell': [
        (HUDDELL_DIR + 'Inboard_Capacity_Plan' + HUDDELL_SUFFIX + '(sheet_7_of_20).tif', HUDDELL_SHEET7),
        (HUDDELL_DIR + 'Deep_Tank_Top,_Inner_Bottom_Capacity_Plan' + HUDDELL_SUFFIX + '(sheet_9_of_20).tif',
         HUDDELL_SHEET9),
        (HUDDELL_DIR + 'Upper_Deck_Capacity_Plan,_Second_Deck_Capacity_Plan' + HUDDELL_SUFFIX
         + '(sheet_8_of_20).tif', HUDDELL_SHEET8)],
}

# Scan variant (docs/TANKS_V2.md section 2): skew, blur, grey noise, 1-bit threshold, flips.
SCAN_SKEW_DEG = 0.2
SCAN_BLUR_SIGMA_PX = 0.8
SCAN_NOISE_SIGMA = 12.0
SCAN_FLIP_SHARE = 0.001


def render_pdf(path: Path, dpi: int) -> np.ndarray:
    """Grey page (uint8) of a one-page PDF."""
    import fitz

    with fitz.open(path) as document:
        pixmap = document[0].get_pixmap(dpi=dpi, colorspace=fitz.csGRAY, alpha=False)
        return np.frombuffer(pixmap.samples, np.uint8).reshape(pixmap.height, pixmap.width).copy()


def scan_variant(grey: np.ndarray, seed: int = 0) -> np.ndarray:
    """Ink mask of a simulated bilevel scan of a grey page."""
    import cv2

    rng = np.random.default_rng(seed)
    height, width = grey.shape
    matrix = cv2.getRotationMatrix2D((width / 2, height / 2), SCAN_SKEW_DEG, 1.0)
    turned = cv2.warpAffine(grey, matrix, (width, height), flags=cv2.INTER_LINEAR, borderValue=255)
    blurred = cv2.GaussianBlur(turned, (0, 0), SCAN_BLUR_SIGMA_PX).astype(np.float32)
    blurred += rng.normal(0, SCAN_NOISE_SIGMA, blurred.shape).astype(np.float32)
    ink = blurred < INK_THRESHOLD
    flips = rng.random(ink.shape) < SCAN_FLIP_SHARE
    return ink ^ flips


def load_sheet(path: Path, dpi: int | None, scan: bool) -> tuple[np.ndarray, float]:
    """Ink mask of a sheet and its dpi: a PDF page rendered at ``dpi`` (optionally as the scan
    variant), or a scanned TIFF at its own resolution."""
    from vessel_reconstruction.body_plan_crossings import load_ink

    if path.suffix.lower() == '.pdf':
        grey = render_pdf(path, dpi or 300)
        return (scan_variant(grey) if scan else grey < INK_THRESHOLD), float(dpi or 300)
    from PIL import Image

    Image.MAX_IMAGE_PIXELS = None
    with Image.open(path) as image:
        sheet_dpi = float((image.info.get('dpi') or (400, 400))[0])
    return load_ink(path), sheet_dpi


def load_case(sources: Path, case: str, dpi: int | None, scan: bool) -> list[tuple[np.ndarray, float, SheetSpec]]:
    """Ink mask, dpi and sheet description of each sheet of a case."""
    return [(*load_sheet(sources / relative, dpi, scan), spec) for relative, spec in CASES[case]]
